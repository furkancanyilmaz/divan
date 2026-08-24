"""Application-level same-Wi-Fi device sync for Divan.

The public HTTP application stays bound to loopback.  Only an explicit
``start_host`` call creates the separate, five-minute pinned-TLS listener
implemented by :mod:`secure_sync_transport`.

This service exchanges logical allowlisted records through :mod:`sync_engine`;
it never copies the SQLite database and it never addresses settings, provider
credentials, PIN state, model jobs, or chat request queues.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sqlite3
import threading
import time
from contextlib import nullcontext
from typing import Any, Callable, Optional

import secure_sync_transport as transport
import sync_engine
from sync_qr import pairing_qr_matrix


SYNC_STATUS_TABLE = "sync_local_status"
WIRE_TARGET_BYTES = 440 * 1024
WIRE_RECORD_LIMIT = 64
DEVICE_ID_SUFFIX = ".device-id"
PROJECTION_CONFIRM_KIND = "divan-projection-confirm"


class SyncServiceError(RuntimeError):
    """A short error which is safe to present in the local Divan UI."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


class _ClinicalSyncPause(RuntimeError):
    """Internal clean stop after either device requests local consent."""


_db_factory: Optional[Callable[[], sqlite3.Connection]] = None
_db_path_getter: Optional[Callable[[], str]] = None
_write_lock = None
_snapshot_callback: Optional[Callable[[], Any]] = None
_mutation_callback: Optional[Callable[[], Any]] = None
_idle_callback: Optional[Callable[[], bool]] = None
_state_lock = threading.RLock()
_identity_lock = threading.Lock()
_identity_reader: Optional[Callable[[str], str]] = None
_identity_writer: Optional[Callable[[str, str], Any]] = None
_session: Optional[transport.SecureSyncSession] = None
_invitation: Optional[transport.PairingInvitation] = None
_host_cursor: Optional[int] = None
_host_peer_device_id: Optional[str] = None
_host_ack_baseline: Optional[int] = None
_host_provisional_ack: Optional[int] = None
_host_offered_cursor: Optional[int] = None
_host_snapshot_created = False
_host_database_prepared = False
_host_prepare_lock = threading.Lock()
_host_totals = {
    "sent": 0, "received": 0, "conflicts": 0,
    "auto_merged": 0, "exact_equal": False,
    "clinical_confirmation_required": False,
    "clinical_safety_pause": False,
}
_active_client = None
_busy = False
_runtime_generation = 0


def configure(
        db_factory: Callable[[], sqlite3.Connection],
        db_path_getter: Callable[[], str],
        write_lock=None,
        snapshot_callback: Optional[Callable[[], Any]] = None,
        mutation_callback: Optional[Callable[[], Any]] = None,
        idle_callback: Optional[Callable[[], bool]] = None) -> None:
    """Attach the service to the current application database."""
    if not callable(db_factory) or not callable(db_path_getter):
        raise TypeError("sync database callbacks must be callable")
    global _db_factory, _db_path_getter, _write_lock
    global _snapshot_callback, _mutation_callback, _idle_callback
    _db_factory = db_factory
    _db_path_getter = db_path_getter
    _write_lock = write_lock
    _snapshot_callback = snapshot_callback
    _mutation_callback = mutation_callback
    _idle_callback = idle_callback


def configure_identity_store(
        reader: Optional[Callable[[str], str]] = None,
        writer: Optional[Callable[[str, str], Any]] = None) -> None:
    """Route the per-install sync identity to a device-bound store.

    Desktop keeps the historical sidecar file. Embedded platforms can provide
    Keychain/Keystore callbacks so restoring an application backup onto a
    second device cannot clone the identity used by the merge protocol.
    """
    if (reader is None) != (writer is None):
        raise TypeError("sync identity reader and writer must be paired")
    if reader is not None and (not callable(reader) or not callable(writer)):
        raise TypeError("sync identity callbacks must be callable")
    global _identity_reader, _identity_writer
    _identity_reader = reader
    _identity_writer = writer


def _configured() -> None:
    if _db_factory is None or _db_path_getter is None:
        raise SyncServiceError("Eşitleme hizmeti henüz hazır değil.")
    if (transport.SYNC_PROTOCOL_VERSION != sync_engine.BATCH_VERSION
            or transport.SCHEMA_PATH_V5_SYNC_CAPABILITY not in
                transport.SYNC_CAPABILITIES):
        # Fail before invitation generation, snapshotting or database refresh
        # if packaging ever combines incompatible engine/transport modules.
        raise SyncServiceError(
            transport.SYNC_PROTOCOL_ERROR_COPY,
            transport.SYNC_PROTOCOL_ERROR_CODE,
        )


def _locked():
    return _write_lock if _write_lock is not None else nullcontext()


def _status_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS sync_local_status(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            last_sync_at TEXT,
            last_peer_device_id TEXT,
            last_peer_name TEXT,
            last_summary_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    connection.execute(
        "INSERT OR IGNORE INTO sync_local_status(singleton) VALUES(1)")


def _identity_path() -> str:
    _configured()
    return os.path.abspath(str(_db_path_getter())) + DEVICE_ID_SUFFIX


def _device_id_unlocked() -> str:
    """Return a per-install identity kept outside transferable SQLite data."""
    if _identity_reader is not None and _identity_writer is not None:
        key = "device_sync_installation_id"
        try:
            value = str(_identity_reader(key) or "").strip()
        except Exception as error:
            raise SyncServiceError(
                "Bu cihazın eşitleme kimliği okunamadı.") from error
        if (len(value) == 32 and
                all(char in "0123456789abcdef" for char in value)):
            return value
        value = os.urandom(16).hex()
        try:
            _identity_writer(key, value)
        except Exception as error:
            raise SyncServiceError(
                "Bu cihazın eşitleme kimliği oluşturulamadı.") from error
        return value

    path = _identity_path()
    try:
        with open(path, "r", encoding="ascii") as source:
            value = source.read(80).strip()
    except FileNotFoundError:
        value = ""
    except OSError as error:
        raise SyncServiceError(
            "Bu cihazın eşitleme kimliği okunamadı.") from error
    if len(value) == 32 and all(char in "0123456789abcdef" for char in value):
        return value

    value = os.urandom(16).hex()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary = "{}.{}.tmp".format(path, os.urandom(6).hex())
    descriptor = None
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            descriptor = None
            output.write(value + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.remove(temporary)
        except OSError:
            pass
        # A simultaneous first request may have won the atomic replace.
        try:
            with open(path, "r", encoding="ascii") as source:
                winner = source.read(80).strip()
        except OSError:
            winner = ""
        if (len(winner) == 32 and
                all(char in "0123456789abcdef" for char in winner)):
            return winner
        raise SyncServiceError(
            "Bu cihazın eşitleme kimliği oluşturulamadı.") from error
    return value


def _device_id() -> str:
    with _identity_lock:
        return _device_id_unlocked()


def _prepare_database(*, refresh: bool) -> str:
    device_id = _device_id()
    with _locked():
        with _db_factory() as connection:
            _status_schema(connection)
            if refresh:
                sync_engine.refresh_local_changes(connection, device_id)
            else:
                sync_engine.initialize_sync(
                    connection, device_id, bootstrap=False)
    return device_id


def _ensure_idle() -> None:
    if _idle_callback is not None and not _idle_callback():
        raise SyncServiceError(
            "Önce sürmekte olan yanıtın tamamlanmasını bekleyin.")


def _create_preflight_snapshot() -> bool:
    """Create the bounded restore point before local merge preparation."""
    if _snapshot_callback is None:
        return False
    try:
        _snapshot_callback()
    except Exception as error:
        raise SyncServiceError(
            "Eşitleme öncesi güvenli geri dönüş noktası oluşturulamadı."
        ) from error
    return True


def _protocol_update_error() -> SyncServiceError:
    return SyncServiceError(
        transport.SYNC_PROTOCOL_ERROR_COPY,
        transport.SYNC_PROTOCOL_ERROR_CODE,
    )


def _validate_peer_protocol(peer: transport.PeerIdentity) -> None:
    try:
        transport.validate_sync_protocol(
            peer.protocol_version, peer.capabilities)
    except transport.SyncProtocolMismatchError as error:
        raise _protocol_update_error() from error


def _prepare_host_database(generation: int) -> str:
    """Prepare local state only after the remote pair passed v8 preflight."""
    global _host_snapshot_created, _host_database_prepared
    with _host_prepare_lock:
        _assert_generation(generation)
        with _state_lock:
            if _host_database_prepared:
                return _device_id()
            snapshot_created = _host_snapshot_created
        if not snapshot_created:
            snapshot_created = _create_preflight_snapshot()
            with _state_lock:
                _assert_generation(generation)
                _host_snapshot_created = snapshot_created
        try:
            device_id = _prepare_database(refresh=True)
        except sync_engine.SyncError as error:
            raise SyncServiceError(
                "Yerel eşitleme kayıtlarından biri güvenli biçimde "
                "hazırlanamadı.") from error
        with _state_lock:
            _assert_generation(generation)
            if (_session is not None and
                    _session.desktop_device_id != device_id):
                raise SyncServiceError(
                    "Eşitleme cihaz kimliği beklenmedik biçimde değişti.")
            _host_database_prepared = True
        return device_id


def _assert_generation(expected: int) -> None:
    with _state_lock:
        if expected != _runtime_generation:
            raise SyncServiceError(
                "Eşitleme oturumu sıfırlandığı için işlem durduruldu.")


def _json_bytes(value: Any) -> int:
    return len(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8"))


def _bounded_export(
        connection: sqlite3.Connection, device_id: str,
        after_cursor: int, ack_cursor: int) -> dict:
    limit = WIRE_RECORD_LIMIT
    while limit >= 1:
        batch = sync_engine.export_change_batch(
            connection, device_id,
            after_cursor=after_cursor, ack_cursor=ack_cursor, limit=limit)
        if _json_bytes([batch]) <= WIRE_TARGET_BYTES:
            return batch
        limit //= 2
    raise SyncServiceError(
        "Tek bir kayıt güvenli eşitleme boyut sınırını aşıyor.")


def _batch_record_count(batch: Any) -> int:
    if not isinstance(batch, dict):
        return 0
    records = batch.get("records")
    return len(records) if isinstance(records, list) else 0


def _empty_totals() -> dict:
    return {
        "sent": 0, "received": 0, "conflicts": 0,
        "auto_merged": 0, "exact_equal": False,
        "clinical_confirmation_required": False,
        "clinical_safety_pause": False,
    }


def _set_peer_ack_cursor(
        connection: sqlite3.Connection, peer_device_id: str,
        acknowledged_cursor: int) -> None:
    """Persist only an acknowledgement proven inside this sync session."""
    if type(acknowledged_cursor) is not int or acknowledged_cursor < 0:
        raise SyncServiceError("Eşitleme onayı geçersiz.")
    # Ensure the table exists and validate the peer id through the engine's
    # public boundary before touching its internal cursor row.
    sync_engine.peer_ack_cursor(connection, peer_device_id)
    connection.execute(
        "INSERT INTO sync_peer_cursors("
        "peer_device_id,remote_cursor,acknowledged_local_cursor,updated_at) "
        "VALUES(?,0,?,?) "
        "ON CONFLICT(peer_device_id) DO UPDATE SET "
        "acknowledged_local_cursor=excluded.acknowledged_local_cursor,"
        "updated_at=excluded.updated_at",
        (peer_device_id, acknowledged_cursor,
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )


def _validated_projection(value: Any) -> dict:
    expected = {
        "projection_version", "protocol_version", "digest",
        "live_count", "type_counts", "pending",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise SyncServiceError("Eşitlik doğrulaması geçersiz.")
    digest = value.get("digest")
    counts = value.get("type_counts")
    if (value.get("projection_version") != sync_engine.PROJECTION_VERSION
            or value.get("protocol_version") != sync_engine.BATCH_VERSION
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or type(value.get("live_count")) is not int
            or value["live_count"] < 0
            or type(value.get("pending")) is not int
            or value["pending"] < 0
            or not isinstance(counts, dict)
            or any(key not in sync_engine.RECORD_TYPES for key in counts)
            or any(type(count) is not int or count < 0
                   for count in counts.values())
            or sum(counts.values()) != value["live_count"]):
        raise SyncServiceError("Eşitlik doğrulaması geçersiz.")
    return {
        "projection_version": value["projection_version"],
        "protocol_version": value["protocol_version"],
        "digest": digest,
        "live_count": value["live_count"],
        "type_counts": {key: counts[key] for key in sorted(counts)},
        "pending": value["pending"],
    }


def _projection_confirmation(
        connection: sqlite3.Connection, device_id: str) -> dict:
    return {
        "kind": PROJECTION_CONFIRM_KIND,
        "sender_device_id": device_id,
        "projection": sync_engine.projection_summary(connection),
    }


def _projections_equal(local: dict, remote: dict) -> bool:
    return (
        local["pending"] == 0 and remote["pending"] == 0
        and local["projection_version"] == remote["projection_version"]
        and local["protocol_version"] == remote["protocol_version"]
        and local["digest"] == remote["digest"]
        and local["live_count"] == remote["live_count"]
        and local["type_counts"] == remote["type_counts"]
    )


def _save_last_sync(
        peer_device_id: str, peer_name: str, totals: dict, *,
        generation: Optional[int] = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    safe_summary = {
        "sent": max(0, int(totals.get("sent") or 0)),
        "received": max(0, int(totals.get("received") or 0)),
        "conflicts": max(0, int(totals.get("conflicts") or 0)),
        "auto_merged": max(0, int(totals.get("auto_merged") or 0)),
        "exact_equal": bool(totals.get("exact_equal")),
        "clinical_confirmation_required": bool(
            totals.get("clinical_confirmation_required")),
        "clinical_safety_pause": bool(
            totals.get("clinical_safety_pause")),
    }
    if safe_summary["exact_equal"]:
        safe_summary["live_count"] = max(
            0, int(totals.get("live_count") or 0))
    with _locked():
        if generation is not None:
            _assert_generation(generation)
        with _db_factory() as connection:
            _status_schema(connection)
            connection.execute(
                "UPDATE sync_local_status SET last_sync_at=?,"
                "last_peer_device_id=?,last_peer_name=?,"
                "last_summary_json=? WHERE singleton=1",
                (
                    stamp, str(peer_device_id or "")[:128],
                    str(peer_name or "")[:64],
                    json.dumps(safe_summary, sort_keys=True),
                ),
            )
    return stamp


def _public_conflicts(
        connection: sqlite3.Connection, *, read_only: bool = False
        ) -> list[dict]:
    labels = {
        "note": "Ustanın çalışma notu",
        "memory": "Onaylı hafıza kaydı",
        "goal": "Hedef",
        "checkin": "Anlık durum kaydı",
        "session_summary": "Seans özeti",
        "session_meta": "Seans çerçevesi",
        "message": "Mesaj",
        "conversation": "Görüşme",
        "adhd_habit": "ADHD ritmi",
        "adhd_habit_event": "ADHD ritim geçmişi",
        "adhd_journal": "Paylaşılan ADHD defter yazısı",
        "schema_path": "Şema çalışma yolu",
        "schema_candidate": "Şema çalışma olasılığı",
        "schema_focus_check": "Şema odak doğrulaması",
        "schema_step": "Şema çalışma adımı",
        "schema_origin": "Kullanıcının bildirdiği erken örnek",
        "schema_growth": "Sağlıklı Yetişkin yaş basamağı",
        "schema_healthy_adult": "Sağlıklı Yetişkin sözü",
        "schema_transfer": "Bugüne taşıma planı",
        "schema_message_meta": "Sohbet içi Şema ilerleme notu",
    }
    # Missing parents are a transport-order condition, not a user decision.
    # The engine retries them automatically after every following batch.
    if read_only:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='sync_conflicts'"
        ).fetchone()
        if not table:
            rows = []
        else:
            rows = [dict(row) for row in connection.execute(
                "SELECT id,record_type,reason,created_at "
                "FROM sync_conflicts WHERE status='open' ORDER BY id"
            ).fetchall()]
    else:
        rows = sync_engine.list_conflicts(connection)
    rows = [
        row for row in rows
        if row.get("reason") != "missing_dependency"
    ]
    return [{
        "id": int(row["id"]),
        "record_type": row["record_type"],
        "title": labels.get(
            row["record_type"], "İki cihazda düzenlenen kayıt"),
        "summary": (
            "İki sürüm de korunuyor; hangisinin etkin kalacağına "
            "siz karar verin."
        ),
        "reason": row["reason"],
        "created_at": row["created_at"],
    } for row in rows]


def _pending_clinical_confirmations(
        connection: sqlite3.Connection) -> list[int]:
    """Return local conversation ids awaiting this installation's consent.

    These opaque local row ids let the loopback UI open the right Kerem
    conversation without exposing any clinical payload over the sync wire.
    Provider/model consent and clinical text remain outside this result.
    """
    tables = {str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('conversations','session_meta')"
    ).fetchall()}
    if tables != {"conversations", "session_meta"}:
        return []
    meta_columns = {str(row[1]) for row in connection.execute(
        "PRAGMA table_info(session_meta)"
    ).fetchall()}
    if not {
            "schema_clinical_sync_enabled",
            "schema_clinical_sync_initialized"}.issubset(meta_columns):
        return []
    conversation_columns = {str(row[1]) for row in connection.execute(
        "PRAGMA table_info(conversations)"
    ).fetchall()}
    ended = "COALESCE(v.ended,0)=0" if "ended" in conversation_columns \
        else "1=1"
    archived = "v.archived_at IS NULL" \
        if "archived_at" in conversation_columns else "1=1"
    guest = "COALESCE(v.is_guest,0)=0" \
        if "is_guest" in conversation_columns else "1=1"
    therapist = "v.therapist='young'" \
        if "therapist" in conversation_columns else "1=1"
    rows = connection.execute(
        "SELECT v.id FROM conversations v JOIN session_meta s ON s.conv=v.id "
        "WHERE s.schema_clinical_sync_enabled=1 "
        "AND s.schema_clinical_sync_initialized=0 AND {} AND {} AND {} "
        "AND {} ORDER BY v.id LIMIT 1000".format(
            ended, archived, guest, therapist)
    ).fetchall()
    return [int(row[0]) for row in rows]


def _host_on_batch(
        items: list, peer: transport.PeerIdentity, *,
        generation: Optional[int] = None) -> dict:
    global _host_cursor, _host_peer_device_id
    global _host_ack_baseline, _host_provisional_ack
    global _host_offered_cursor
    global _host_totals
    if generation is None:
        with _state_lock:
            generation = _runtime_generation
    _assert_generation(generation)
    _validate_peer_protocol(peer)
    _ensure_idle()
    if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items):
        raise SyncServiceError("Eşitleme kayıt paketi geçersiz.")
    sync_items = []
    confirmation = None
    for item in items:
        if item.get("kind") == sync_engine.BATCH_KIND:
            if item.get("sender_device_id") != peer.device_id:
                raise SyncServiceError(
                    "Eş cihaz kimliği kayıt paketiyle uyuşmuyor.")
            sync_items.append(item)
            continue
        if item.get("kind") == PROJECTION_CONFIRM_KIND:
            if (confirmation is not None or set(item) != {
                    "kind", "sender_device_id", "projection"}
                    or item.get("sender_device_id") != peer.device_id):
                raise SyncServiceError("Eşitlik doğrulaması geçersiz.")
            confirmation = _validated_projection(item.get("projection"))
            continue
        raise SyncServiceError("Eşitleme kayıt paketi geçersiz.")
    for item in sync_items:
        sync_engine.validate_change_batch(item)
    device_id = _prepare_host_database(generation)
    apply_summaries = []
    accepted_incoming_count = 0
    clinical_confirmation_required = False
    clinical_safety_pause = False
    with _locked():
        _assert_generation(generation)
        with _db_factory() as connection:
            _status_schema(connection)
            persistent_ack = sync_engine.peer_ack_cursor(
                connection, peer.device_id)
            persistent_offer = sync_engine.peer_offered_cursor(
                connection, peer.device_id)
            with _state_lock:
                if _host_peer_device_id not in (None, peer.device_id):
                    raise SyncServiceError(
                        "Eşitleme oturumundaki cihaz beklenmedik biçimde değişti.")
                if _host_peer_device_id is None:
                    _host_peer_device_id = peer.device_id
                    _host_ack_baseline = persistent_ack
                    _host_provisional_ack = persistent_ack
                    _host_offered_cursor = max(
                        persistent_ack, persistent_offer)
                    _host_cursor = persistent_ack
                offered_cursor = int(_host_offered_cursor or 0)
            for item in sync_items:
                if item["ack_cursor"] > offered_cursor:
                    raise SyncServiceError(
                        "Eş cihaz sunulmamış bir eşitleme kaydını onayladı.")
            for item in sync_items:
                try:
                    result = sync_engine.apply_change_batch(
                        connection, item, device_id)
                except sync_engine.ClinicalSyncConfirmationRequired:
                    clinical_confirmation_required = True
                    break
                except sync_engine.ClinicalSyncSafetyPause:
                    clinical_safety_pause = True
                    break
                apply_summaries.append(result)
                accepted_incoming_count += _batch_record_count(item)
            if clinical_confirmation_required or clinical_safety_pause:
                with _state_lock:
                    outbound_after = int(_host_provisional_ack or 0)
                received = sync_engine.peer_cursor(
                    connection, peer.device_id)
                outbound = {
                    "kind": sync_engine.BATCH_KIND,
                    "version": sync_engine.BATCH_VERSION,
                    "sender_device_id": device_id,
                    "after_cursor": outbound_after,
                    "cursor": outbound_after,
                    "ack_cursor": received,
                    "has_more": False,
                    "records": [],
                }
                local_projection = sync_engine.projection_summary(connection)
            else:
                incoming_ack = max(
                    [int(item["ack_cursor"]) for item in sync_items]
                    or [int(_host_provisional_ack or 0)])
                with _state_lock:
                    _host_provisional_ack = max(
                        int(_host_provisional_ack or 0), incoming_ack)
                    outbound_after = int(_host_provisional_ack)
                    _host_cursor = outbound_after
                # Network acknowledgements remain provisional until the final
                # two-sided projection proof succeeds.
                _set_peer_ack_cursor(
                    connection, peer.device_id,
                    int(_host_ack_baseline or 0))
                # Capture any application writer which did not explicitly enroll
                # its row while this QR session was open.
                sync_engine.refresh_local_changes(connection, device_id)
                received = sync_engine.peer_cursor(connection, peer.device_id)
                try:
                    outbound = _bounded_export(
                        connection, device_id, outbound_after, received)
                except sync_engine.ClinicalSyncSafetyPause:
                    clinical_safety_pause = True
                    outbound = {
                        "kind": sync_engine.BATCH_KIND,
                        "version": sync_engine.BATCH_VERSION,
                        "sender_device_id": device_id,
                        "after_cursor": outbound_after,
                        "cursor": outbound_after,
                        "ack_cursor": received,
                        "has_more": False,
                        "records": [],
                    }
                else:
                    sync_engine.record_peer_offer(
                        connection, peer.device_id,
                        int(outbound["cursor"]))
                local_projection = sync_engine.projection_summary(connection)
                with _state_lock:
                    _host_cursor = int(outbound["cursor"])
                    if not clinical_safety_pause:
                        _host_offered_cursor = max(
                            int(_host_offered_cursor or 0),
                            int(outbound["cursor"]))

    applied_conflicts = sum(
        int(item.get("conflicts") or 0) for item in apply_summaries)
    automatically_merged = sum(
        int(item.get("auto_merged") or 0) for item in apply_summaries)
    can_compare = (not clinical_confirmation_required
        and not clinical_safety_pause
        and confirmation is not None and not bool(
        outbound["has_more"]) and _batch_record_count(outbound) == 0
    )
    exact_equal = bool(
        can_compare
        and _projections_equal(local_projection, confirmation))
    confirmation_required = bool(
        not clinical_confirmation_required
        and not clinical_safety_pause
        and not outbound["has_more"] and confirmation is None)
    with _state_lock:
        _host_totals["received"] += accepted_incoming_count
        _host_totals["sent"] += _batch_record_count(outbound)
        _host_totals["conflicts"] += applied_conflicts
        _host_totals["auto_merged"] += automatically_merged
        _host_totals["exact_equal"] = exact_equal
        _host_totals["clinical_confirmation_required"] = bool(
            clinical_confirmation_required)
        _host_totals["clinical_safety_pause"] = bool(
            clinical_safety_pause)
        if exact_equal:
            _host_totals["live_count"] = local_projection["live_count"]
        totals = dict(_host_totals)
    if exact_equal:
        with _locked():
            _assert_generation(generation)
            with _db_factory() as connection:
                _set_peer_ack_cursor(
                    connection, peer.device_id,
                    int(_host_provisional_ack or 0))
    _save_last_sync(
        peer.device_id, peer.name, totals, generation=generation)
    if accepted_incoming_count and _mutation_callback is not None:
        _mutation_callback()
    result = {
        "batch": outbound,
        "more": bool(outbound["has_more"]),
        "apply": {
            "records": accepted_incoming_count,
            "conflicts": applied_conflicts,
            "auto_merged": automatically_merged,
        },
        "confirmation_required": confirmation_required,
        "clinical_confirmation_required": clinical_confirmation_required,
        "clinical_confirmation_device": (
            "computer" if clinical_confirmation_required else None),
        "clinical_safety_pause": clinical_safety_pause,
        "clinical_safety_device": (
            "computer" if clinical_safety_pause else None),
        "exact_equal": exact_equal,
        "projection": local_projection if exact_equal else None,
        "live_count": (
            local_projection["live_count"] if exact_equal else None),
    }
    # The transport may close only after the client has applied the host's
    # final empty batch and proved that both live projections match.  A
    # mismatching confirmation completes with exact_equal=false instead of
    # looping forever; the UI can ask for a fresh sync after inspection.
    result["more"] = bool(
        not clinical_confirmation_required and not clinical_safety_pause and (
        outbound["has_more"] or confirmation_required
        or (confirmation is not None and _batch_record_count(outbound) > 0)))
    if _json_bytes(result) > transport.MAX_BATCH_BYTES:
        raise SyncServiceError("Eşitleme yanıtı boyut sınırını aşıyor.")
    return result


def start_host(
        *, advertised_host: Optional[str] = None,
        ttl_seconds: int = transport.DEFAULT_TTL_SECONDS) -> dict:
    """Open the explicit one-peer desktop listener and return its QR."""
    global _session, _invitation, _host_cursor, _host_peer_device_id
    global _host_ack_baseline, _host_provisional_ack
    global _host_offered_cursor
    global _host_snapshot_created, _host_database_prepared
    global _host_totals, _busy
    _configured()
    _ensure_idle()
    with _state_lock:
        if _session is not None and _session.running:
            raise SyncServiceError("Bu cihaz zaten eşleşme bekliyor.")
        if _busy:
            raise SyncServiceError("Başka bir eşitleme işlemi sürüyor.")
        _busy = True
        generation = _runtime_generation
        previous = _session
        _session = None
        _invitation = None
    try:
        # The installation identity is needed in the invitation, but all
        # SQLite preparation/refresh and the restore-point snapshot wait until
        # an exact v8 checkpoint + Schema Path v5 pair reaches the first batch.
        device_id = _device_id()
    except Exception:
        with _state_lock:
            if generation == _runtime_generation:
                _busy = False
        raise
    if previous is not None:
        previous.stop()
    try:
        addresses = (
            [advertised_host] if advertised_host
            else transport.discover_lan_addresses())
        addresses = [value for value in addresses if value]
        if not addresses:
            raise SyncServiceError(
                "Aynı Wi‑Fi için kullanılabilecek yerel ağ adresi bulunamadı.")
        # V1 intentionally advertises IPv4 first for Android compatibility.
        addresses.sort(key=lambda value: (":" in value, value))
        def on_batch(items, peer):
            return _host_on_batch(
                items, peer, generation=generation)

        candidate = transport.SecureSyncSession(
            addresses[0], device_id, on_batch,
            ttl_seconds=ttl_seconds)
        try:
            invitation = candidate.start()
        except transport.TLSUnavailableError as error:
            raise SyncServiceError(
                "Bu pakette güvenli eşitleme bileşeni bulunamadı.") from error
        except OSError as error:
            raise SyncServiceError(
                "Güvenli bağlantı açılamadı; güvenlik duvarını "
                "ve Wi‑Fi bağlantısını denetleyin.") from error
        try:
            _assert_generation(generation)
        except Exception:
            candidate.stop()
            raise
        with _state_lock:
            stale = generation != _runtime_generation
            if not stale:
                _session = candidate
                _invitation = invitation
                _host_cursor = None
                _host_peer_device_id = None
                _host_ack_baseline = None
                _host_provisional_ack = None
                _host_offered_cursor = None
                _host_snapshot_created = False
                _host_database_prepared = False
                _host_totals = _empty_totals()
        if stale:
            candidate.stop()
            raise SyncServiceError(
                "Eşitleme oturumu sıfırlandığı için işlem durduruldu.")
        matrix = pairing_qr_matrix(invitation.qr_uri)
        return {
            "pairing_code": invitation.manual_code,
            "qr_matrix": matrix,
            "seconds_remaining": max(
                0, int(candidate.deadline - time.monotonic())),
        }
    finally:
        with _state_lock:
            if generation == _runtime_generation:
                _busy = False


def stop_host() -> dict:
    global _session, _invitation, _host_cursor, _host_peer_device_id
    global _host_ack_baseline, _host_provisional_ack
    global _host_offered_cursor
    global _host_snapshot_created, _host_database_prepared, _host_totals
    with _state_lock:
        session = _session
        _session = None
        _invitation = None
        _host_cursor = None
        _host_peer_device_id = None
        _host_ack_baseline = None
        _host_provisional_ack = None
        _host_offered_cursor = None
        _host_snapshot_created = False
        _host_database_prepared = False
        _host_totals = _empty_totals()
    if session is not None:
        session.stop()
    return status()


def _device_label(default: str = "Bu cihaz") -> str:
    try:
        hostname = socket.gethostname().strip()
    except OSError:
        hostname = ""
    return (hostname or default)[:64]


def join(
        code: str, *, device_name: Optional[str] = None,
        platform_name: Optional[str] = None) -> dict:
    """Join a scanned invitation, drain both change logs, then disconnect."""
    global _active_client, _busy
    _configured()
    _ensure_idle()
    with _state_lock:
        if _busy:
            raise SyncServiceError("Başka bir eşitleme zaten sürüyor.")
        _busy = True
        generation = _runtime_generation
    client = None
    try:
        try:
            invitation = transport.parse_invitation(code)
        except transport.SyncProtocolMismatchError as error:
            raise _protocol_update_error() from error
        except ValueError as error:
            raise SyncServiceError(
                "Eşleme kodu geçersiz veya süresi dolmuş.") from error
        # Pairing needs only the installation identity.  Snapshotting,
        # migration, refresh and all cursor reads wait for the authenticated
        # peer to echo the exact v8 capability contract.
        device_id = _device_id()
        name = str(device_name or _device_label()).strip()[:64]
        system_name = str(
            platform_name or platform.system() or "Divan").strip()[:32]
        try:
            client, _ = transport.pair_with_invitation(
                invitation, device_id=device_id,
                public_key=os.urandom(32), name=name,
                platform=system_name, timeout=12.0)
        except transport.SyncProtocolMismatchError as error:
            raise _protocol_update_error() from error
        except ValueError as error:
            # The invitation is parsed again by the pinned client.  It can
            # legitimately expire in the small interval between those two
            # checks; keep that boundary failure out of the generic HTTP 400.
            raise SyncServiceError(
                "Eşleme kodu geçersiz veya süresi dolmuş.") from error
        except transport.CertificatePinError as error:
            raise SyncServiceError(
                "QR kodundaki güvenlik doğrulaması başarısız.") from error
        except (transport.SecureSyncError, OSError) as error:
            raise SyncServiceError(
                "Diğer cihaza ulaşılamadı. İki cihazın aynı Wi‑Fi ağında "
                "olduğunu ve QR süresinin dolmadığını denetleyin.") from error

        _assert_generation(generation)
        with _state_lock:
            if generation != _runtime_generation:
                raise SyncServiceError(
                    "Eşitleme oturumu sıfırlandığı için işlem durduruldu.")
            _active_client = client

        # Pairing succeeded with the exact protocol/capability echo.  Only now
        # may local sync tables, refresh state or restore points be touched.
        preflight_snapshot_created = _create_preflight_snapshot()
        try:
            prepared_device_id = _prepare_database(refresh=True)
        except sync_engine.SyncError as error:
            raise SyncServiceError(
                "Yerel eşitleme kayıtlarından biri güvenli biçimde "
                "hazırlanamadı.") from error
        if prepared_device_id != device_id:
            raise SyncServiceError(
                "Eşitleme cihaz kimliği beklenmedik biçimde değişti.")

        with _locked():
            _assert_generation(generation)
            with _db_factory() as connection:
                ack_baseline = sync_engine.peer_ack_cursor(
                    connection, invitation["desktop_device_id"])
                persisted_offer = sync_engine.peer_offered_cursor(
                    connection, invitation["desktop_device_id"])
                outgoing_cursor = ack_baseline
        provisional_ack = ack_baseline
        offered_cursor = max(ack_baseline, persisted_offer)
        confirmation_in_flight = None
        snapshot_created = preflight_snapshot_created
        totals = _empty_totals()
        final_exact_equal = False
        final_live_count = 0
        clinical_confirmation_required = False
        clinical_confirmation_device = None
        clinical_safety_pause = False
        clinical_safety_device = None

        def next_batch(peer_result):
            nonlocal outgoing_cursor, offered_cursor
            nonlocal confirmation_in_flight
            nonlocal clinical_safety_pause, clinical_safety_device
            _assert_generation(generation)
            confirmation_in_flight = None
            with _locked():
                _assert_generation(generation)
                with _db_factory() as connection:
                    sync_engine.refresh_local_changes(
                        connection, device_id)
                    acknowledged_remote = sync_engine.peer_cursor(
                        connection, invitation["desktop_device_id"])
                    try:
                        outbound = _bounded_export(
                            connection, device_id, outgoing_cursor,
                            acknowledged_remote)
                    except sync_engine.ClinicalSyncSafetyPause:
                        clinical_safety_pause = True
                        clinical_safety_device = "this_device"
                        raise _ClinicalSyncPause()
                    sync_engine.record_peer_offer(
                        connection, invitation["desktop_device_id"],
                        int(outbound["cursor"]))
                    items = [outbound]
                    if (isinstance(peer_result, dict)
                            and peer_result.get(
                                "confirmation_required") is True
                            and not outbound["has_more"]
                            and _batch_record_count(outbound) == 0):
                        confirmation = _projection_confirmation(
                            connection, device_id)
                        items.append(confirmation)
                        confirmation_in_flight = dict(
                            confirmation["projection"])
            outgoing_cursor = int(outbound["cursor"])
            offered_cursor = max(offered_cursor, outgoing_cursor)
            totals["sent"] += _batch_record_count(outbound)
            return items, not bool(outbound["has_more"])

        def apply_result(result):
            nonlocal outgoing_cursor, snapshot_created
            nonlocal final_exact_equal, final_live_count
            nonlocal provisional_ack, confirmation_in_flight
            nonlocal clinical_confirmation_required
            nonlocal clinical_confirmation_device
            nonlocal clinical_safety_pause
            nonlocal clinical_safety_device
            _assert_generation(generation)
            if not isinstance(result, dict):
                raise SyncServiceError("Eşitleme yanıtı geçersiz.")
            incoming = result.get("batch")
            if not isinstance(incoming, dict):
                raise SyncServiceError("Eşitleme kayıt paketi eksik.")
            if incoming.get("sender_device_id") != invitation[
                    "desktop_device_id"]:
                raise SyncServiceError(
                    "Bilgisayar kimliği kayıt paketiyle uyuşmuyor.")
            sync_engine.validate_change_batch(incoming)
            if result.get("clinical_confirmation_required") is True:
                clinical_confirmation_required = True
                clinical_confirmation_device = "computer"
                raise _ClinicalSyncPause()
            if result.get("clinical_safety_pause") is True:
                clinical_safety_pause = True
                clinical_safety_device = "computer"
                raise _ClinicalSyncPause()
            if incoming["ack_cursor"] > offered_cursor:
                raise SyncServiceError(
                    "Bilgisayar sunulmamış bir eşitleme kaydını onayladı.")
            record_count = _batch_record_count(incoming)
            if record_count and not snapshot_created:
                if _snapshot_callback is not None:
                    _snapshot_callback()
                snapshot_created = True
            with _locked():
                _assert_generation(generation)
                with _db_factory() as connection:
                    try:
                        merged = sync_engine.apply_change_batch(
                            connection, incoming, device_id)
                    except sync_engine.ClinicalSyncConfirmationRequired:
                        clinical_confirmation_required = True
                        clinical_confirmation_device = "this_device"
                        raise _ClinicalSyncPause()
                    except sync_engine.ClinicalSyncSafetyPause:
                        clinical_safety_pause = True
                        clinical_safety_device = "this_device"
                        raise _ClinicalSyncPause()
                    provisional_ack = max(
                        provisional_ack, int(incoming["ack_cursor"]))
                    outgoing_cursor = max(outgoing_cursor, provisional_ack)
                    _set_peer_ack_cursor(
                        connection, invitation["desktop_device_id"],
                        ack_baseline)
                    sync_engine.refresh_local_changes(
                        connection, device_id)
                    local_projection = sync_engine.projection_summary(
                        connection)
            totals["received"] += record_count
            totals["conflicts"] += int(merged.get("conflicts") or 0)
            totals["auto_merged"] += int(
                merged.get("auto_merged") or 0)
            host_apply = result.get("apply")
            if isinstance(host_apply, dict):
                totals["conflicts"] += int(
                    host_apply.get("conflicts") or 0)
                totals["auto_merged"] += int(
                    host_apply.get("auto_merged") or 0)
            final_exact_equal = False
            if (result.get("exact_equal") is True
                    and confirmation_in_flight is not None
                    and result.get("more") is False
                    and result.get("confirmation_required") is False
                    and not incoming["has_more"]
                    and record_count == 0):
                try:
                    host_projection = _validated_projection(
                        result.get("projection"))
                except SyncServiceError:
                    host_projection = None
                final_exact_equal = bool(
                    host_projection is not None
                    and _projections_equal(
                        host_projection, confirmation_in_flight)
                    and _projections_equal(
                        local_projection, host_projection))
            if final_exact_equal:
                with _locked():
                    _assert_generation(generation)
                    with _db_factory() as connection:
                        _set_peer_ack_cursor(
                            connection,
                            invitation["desktop_device_id"],
                            provisional_ack)
                final_live_count = local_projection["live_count"]
            confirmation_in_flight = None
            if record_count and _mutation_callback is not None:
                _mutation_callback()

        try:
            client.run_batches(next_batch, apply_result, max_rounds=10000)
        except _ClinicalSyncPause:
            final_exact_equal = False
        except transport.CertificatePinError as error:
            raise SyncServiceError(
                "QR kodundaki güvenlik doğrulaması başarısız.") from error
        except (transport.SecureSyncError, OSError, ValueError) as error:
            raise SyncServiceError(
                "Eşitleme tamamlanamadı. Güvenli geri dönüş noktası "
                "korundu; yeni bir QR ile yeniden deneyin.") from error
        totals["exact_equal"] = final_exact_equal
        totals["clinical_confirmation_required"] = bool(
            clinical_confirmation_required)
        totals["clinical_safety_pause"] = bool(clinical_safety_pause)
        if final_exact_equal:
            totals["live_count"] = final_live_count
        stamp = _save_last_sync(
            invitation["desktop_device_id"], "Bilgisayar", totals,
            generation=generation)
        with _locked():
            with _db_factory() as connection:
                conflicts = _public_conflicts(connection)
                pending_clinical = _pending_clinical_confirmations(connection)
        return {
            "ok": True,
            "summary": dict(totals),
            "exact_equal": final_exact_equal,
            "clinical_confirmation_required": bool(
                clinical_confirmation_required),
            "clinical_confirmation_device": clinical_confirmation_device,
            "clinical_confirmation_message": (
                "Şema çalışma kayıtlarını bu cihazda onaylayın; ardından "
                "bilgisayarda yeni bir QR oluşturup yeniden eşitleyin."
                if clinical_confirmation_device == "this_device" else
                "Şema çalışma kayıtları için bilgisayarda cihaz onayı "
                "gerekiyor; onaydan sonra yeni QR ile yeniden eşitleyin."
                if clinical_confirmation_device == "computer" else None),
            "clinical_safety_pause": bool(clinical_safety_pause),
            "clinical_safety_device": clinical_safety_device,
            "clinical_safety_message": (
                "Bu cihazdaki güvenlik beklemesi sürerken Şema çalışma "
                "kayıtları alınmadı. Bekleme güvenle kapandıktan sonra "
                "bilgisayarda yeni bir QR oluşturup yeniden eşitleyin."
                if clinical_safety_device == "this_device" else
                "Bilgisayardaki güvenlik beklemesi sürerken Şema çalışma "
                "kayıtları alınmadı. Bekleme güvenle kapandıktan sonra "
                "yeni bir QR ile yeniden eşitleyin."
                if clinical_safety_device == "computer" else None),
            "pending_clinical_confirmation_conv_ids": pending_clinical,
            "pending_clinical_confirmation_count": len(pending_clinical),
            "live_count": final_live_count if final_exact_equal else None,
            "last_sync_at": stamp,
            "conflict_rows": conflicts,
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        with _state_lock:
            if _active_client is client:
                _active_client = None
            if generation == _runtime_generation:
                _busy = False


def status() -> dict:
    _configured()
    global _session, _invitation
    with _state_lock:
        running = bool(_session is not None and _session.running)
        if _session is not None and not running:
            _session = None
            _invitation = None
        seconds = (
            max(0, int(_session.deadline - time.monotonic()))
            if running else 0)
        busy = bool(_busy)
    with _locked():
        with _db_factory() as connection:
            status_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='sync_local_status'"
            ).fetchone()
            row = (connection.execute(
                "SELECT * FROM sync_local_status WHERE singleton=1"
            ).fetchone() if status_table else None)
            conflicts = _public_conflicts(connection, read_only=True)
            pending_clinical = _pending_clinical_confirmations(connection)
    value = dict(row) if row else {}
    try:
        summary = json.loads(value.get("last_summary_json") or "{}")
    except (TypeError, ValueError):
        summary = {}
    return {
        "host_running": running,
        "busy": busy,
        "seconds_remaining": seconds,
        "last_sync_at": value.get("last_sync_at"),
        "last_peer_name": value.get("last_peer_name"),
        "last_summary": summary,
        "conflicts": conflicts,
        "pending_clinical_confirmation_conv_ids": pending_clinical,
        "pending_clinical_confirmation_count": len(pending_clinical),
        "scope": [
            "conversations", "messages", "notes", "memories",
            "goals", "checkins", "session_summaries",
            "session_meta", "adhd_habits",
            "completed_adhd_habit_events",
            "shared_non_sensitive_adhd_journal_entries",
            "explicitly_consented_schema_path_v4_v5_projection",
        ],
        "device_local": [
            "reminders", "scheduled_messages", "jobs",
            "adhd_active_event_delivery_state", "adhd_private_journal",
            "schema_raw_observations_and_claims", "schema_provider_consent",
            "schema_experiential_prechecks", "schema_technique_transcripts",
            "schema_counterfactual_and_origin_ledgers",
            "schema_prompt_plans_and_results",
        ],
        "secrets_excluded": True,
    }


def is_busy() -> bool:
    with _state_lock:
        return bool(_busy)


def record_local_delete(
        connection: sqlite3.Connection, record_type: str, local_id: int, *,
        deleted_at: Optional[str] = None, cascade: bool = True,
        physical: bool = False) -> list[dict]:
    """Record and redact a deletion inside the caller's DB transaction.

    Application deletion paths should call this before removing the row.  The
    wrapper supplies the installation identity without exposing service
    internals and deliberately does not open a second connection or lock.
    """
    _configured()
    return sync_engine.record_local_delete(
        connection, record_type, local_id, _device_id(),
        deleted_at=deleted_at, cascade=cascade, physical=physical)


def _stop_schema_path_for_sync_choice(
        connection: sqlite3.Connection, local_id: int,
        device_id: str) -> None:
    """Close one losing active path without deleting its clinical history."""
    stamp = sync_engine._utcnow()
    row = connection.execute(
        "SELECT status FROM schema_paths WHERE id=?", (int(local_id),)
    ).fetchone()
    if row is None:
        raise sync_engine.SyncError("chosen Schema path is unavailable")
    if str(row[0]) in ("active", "paused"):
        connection.execute(
            "UPDATE schema_paths SET status='stopped',"
            "pause_reason='sync_conflict_rejected',resume_required=0,"
            "closed_at=COALESCE(closed_at,?),updated=?,revision=revision+1 "
            "WHERE id=?", (stamp, stamp, int(local_id)))
    sync_engine.record_local_change(
        connection, "schema_path", int(local_id), device_id)


def resolve_conflict(conflict_id: int, resolution: str) -> dict:
    """Apply an explicit local/remote choice and publish the chosen result."""
    if resolution not in ("local", "remote"):
        raise SyncServiceError("Geçerli bir çakışma kararı seçin.")
    device_id = _prepare_database(refresh=False)
    if _snapshot_callback is not None:
        _snapshot_callback()
    with _locked():
        with _db_factory() as connection:
            # Conflict rows created by older builds may contain guest-scope
            # clinical text. Quarantine them before looking up the requested
            # id so a stale UI action cannot revive or republish that data.
            sync_engine.scrub_guest_sync_state(connection)
            row = connection.execute(
                "SELECT * FROM sync_conflicts WHERE id=? AND status='open'",
                (int(conflict_id),),
            ).fetchone()
            if row is None:
                raise SyncServiceError("Açık çakışma bulunamadı.")
            record_type = row["record_type"]
            public_id = row["public_id"]
            meta_row = connection.execute(
                "SELECT * FROM sync_records WHERE record_type=? "
                "AND public_id=?",
                (record_type, public_id),
            ).fetchone()
            meta = dict(meta_row) if meta_row else None
            try:
                stored_incoming = json.loads(row["incoming_json"])
                sync_engine.validate_change_batch({
                    "kind": sync_engine.BATCH_KIND,
                    "version": sync_engine.BATCH_VERSION,
                    "sender_device_id": stored_incoming[
                        "origin_device_id"],
                    "after_cursor": 0,
                    "cursor": 0,
                    "ack_cursor": 0,
                    "has_more": False,
                    "records": [stored_incoming],
                })
            except Exception as error:
                raise SyncServiceError(
                    "Çakışma kaydı güvenli biçimde okunamadı.") from error
            if not sync_engine._clinical_replay_is_currently_safe(
                    connection, stored_incoming):
                # Consent, safety state, generation and exact source lineage
                # can change while a conflict waits for the user.  Erase the
                # stored branch before returning the failure; an explicit
                # commit prevents the context manager's following exception
                # from restoring sensitive conflict JSON.
                sync_engine._discard_stored_conflict(
                    connection, int(conflict_id), stored_incoming)
                connection.commit()
                raise SyncServiceError(
                    "Bu Şema kaydı artık bu cihazda uygulanabilir değil.")
            if row["reason"] == "concurrent_schema_path":
                try:
                    local_branch = json.loads(row["local_json"])
                    if (local_branch.get("record_type") != "schema_path"
                            or stored_incoming.get(
                                "record_type") != "schema_path"):
                        raise sync_engine.SyncError(
                            "active Schema path conflict is invalid")
                    local_meta_row = connection.execute(
                        "SELECT * FROM sync_records WHERE record_type=? "
                        "AND public_id=?",
                        ("schema_path", local_branch["public_id"]),
                    ).fetchone()
                    local_meta = (
                        dict(local_meta_row) if local_meta_row else None)
                    if not local_meta or local_meta.get("local_id") is None:
                        raise sync_engine.SyncError(
                            "local Schema path is unavailable")
                    if resolution == "remote":
                        # Publish the losing local path as stopped first.  Its
                        # change cursor precedes the chosen live path, so the
                        # peer frees the one-active-path constraint before it
                        # applies the chosen branch.
                        _stop_schema_path_for_sync_choice(
                            connection, int(local_meta["local_id"]),
                            device_id)
                        sync_engine._install_incoming(
                            connection, stored_incoming, meta)
                        remote_meta = connection.execute(
                            "SELECT local_id FROM sync_records "
                            "WHERE record_type='schema_path' AND public_id=?",
                            (stored_incoming["public_id"],),
                        ).fetchone()
                        if remote_meta is None or remote_meta[0] is None:
                            raise sync_engine.SyncError(
                                "remote Schema path is unavailable")
                        sync_engine.record_local_change(
                            connection, "schema_path", int(remote_meta[0]),
                            device_id)
                    else:
                        # The incoming path was never installed because of
                        # the UNIQUE collision.  Materialize it directly as a
                        # stopped causal child, then publish the chosen local
                        # path.  Both peers converge without deleting either
                        # path's already-consented history.
                        sync_engine._record_rejected_incoming_schema_path(
                            connection, stored_incoming, device_id)
                        sync_engine.record_local_change(
                            connection, "schema_path",
                            int(local_meta["local_id"]), device_id)
                    still_open = connection.execute(
                        "SELECT 1 FROM sync_conflicts WHERE id=? "
                        "AND status='open'", (int(conflict_id),)
                    ).fetchone()
                    if still_open is not None:
                        sync_engine.resolve_conflict(
                            connection, int(conflict_id),
                            "keep_{}".format(resolution))
                    conflicts = _public_conflicts(connection)
                except Exception as error:
                    raise SyncServiceError(
                        "Şema çalışma yolu kararı uygulanamadı.") from error
                if _mutation_callback is not None:
                    _mutation_callback()
                return {"ok": True, "conflicts": conflicts}
            chosen_local_payload = None
            if (resolution == "local"
                    and meta and meta.get("local_id") is not None):
                try:
                    _, chosen_local_payload = sync_engine._serialize_row(
                        connection, record_type, int(meta["local_id"]))
                    incoming = json.loads(row["incoming_json"])
                    sync_engine.validate_change_batch({
                        "kind": sync_engine.BATCH_KIND,
                        "version": sync_engine.BATCH_VERSION,
                        "sender_device_id": incoming["origin_device_id"],
                        "after_cursor": 0,
                        "cursor": 0,
                        "ack_cursor": 0,
                        "has_more": False,
                        "records": [incoming],
                    })
                    # Install the rejected branch as the causal parent, then
                    # restore the user's chosen local payload and publish one
                    # direct child.  The other peer can now converge without
                    # presenting the same clinical conflict again.  This is
                    # required for Schema v4 records as well as historical
                    # conversation singletons.
                    sync_engine._install_incoming(
                        connection, incoming, meta)
                    active = connection.execute(
                        "SELECT local_id FROM sync_records "
                        "WHERE record_type=? AND public_id=?",
                        (record_type, public_id),
                    ).fetchone()
                    if active is None or active[0] is None:
                        raise sync_engine.SyncError(
                            "chosen singleton record is unavailable")
                    sync_engine._write_payload(
                        connection, record_type, public_id,
                        chosen_local_payload, int(active[0]))
                    sync_engine.record_local_change(
                        connection, record_type, int(active[0]), device_id)
                except Exception as error:
                    raise SyncServiceError(
                        "Bu cihazdaki sürüm uygulanamadı.") from error
            elif resolution == "remote":
                try:
                    incoming = json.loads(row["incoming_json"])
                    sync_engine.validate_change_batch({
                        "kind": sync_engine.BATCH_KIND,
                        "version": sync_engine.BATCH_VERSION,
                        "sender_device_id": incoming["origin_device_id"],
                        "after_cursor": 0,
                        "cursor": 0,
                        "ack_cursor": 0,
                        "has_more": False,
                        "records": [incoming],
                    })
                    sync_engine._install_incoming(
                        connection, incoming, meta)
                except Exception as error:
                    raise SyncServiceError(
                        "Diğer cihazdaki sürüm uygulanamadı.") from error
                active = connection.execute(
                    "SELECT local_id FROM sync_records "
                    "WHERE record_type=? AND public_id=?",
                    (record_type, public_id),
                ).fetchone()
                if active and active[0] is not None:
                    sync_engine.record_local_change(
                        connection, record_type, int(active[0]), device_id)
            elif meta and meta.get("local_id") is not None:
                sync_engine.record_local_change(
                    connection, record_type, int(meta["local_id"]), device_id)
            sync_engine.resolve_conflict(
                connection, int(conflict_id),
                "keep_{}".format(resolution))
            conflicts = _public_conflicts(connection)
    if _mutation_callback is not None:
        _mutation_callback()
    return {"ok": True, "conflicts": conflicts}


def reset_runtime_state() -> dict:
    """Invalidate in-flight callbacks and forget all process-local sync state."""
    global _session, _invitation, _host_cursor, _host_peer_device_id
    global _host_ack_baseline, _host_provisional_ack
    global _host_offered_cursor
    global _host_snapshot_created, _host_database_prepared
    global _host_totals, _active_client
    global _busy, _runtime_generation
    with _state_lock:
        _runtime_generation += 1
        session = _session
        client = _active_client
        _session = None
        _invitation = None
        _host_cursor = None
        _host_peer_device_id = None
        _host_ack_baseline = None
        _host_provisional_ack = None
        _host_offered_cursor = None
        _host_snapshot_created = False
        _host_database_prepared = False
        _host_totals = _empty_totals()
        _active_client = None
        _busy = False
        generation = _runtime_generation
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    if session is not None:
        session.stop()
    return {"ok": True, "generation": generation}


def clear_sync_state() -> dict:
    """Stop active pairing and erase all persistent sync/merge metadata."""
    _configured()
    runtime = reset_runtime_state()
    with _locked():
        with _db_factory() as connection:
            cleared = sync_engine.reset_sync_state(connection)
    return {"ok": True, "generation": runtime["generation"],
            "cleared": cleared}


def shutdown() -> None:
    reset_runtime_state()


__all__ = [
    "SyncServiceError", "configure", "start_host", "stop_host", "join",
    "status", "is_busy", "record_local_delete", "resolve_conflict",
    "reset_runtime_state", "clear_sync_state", "shutdown",
]
