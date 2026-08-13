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


class SyncServiceError(RuntimeError):
    """A short error which is safe to present in the local Divan UI."""


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
_host_snapshot_created = False
_host_totals = {"sent": 0, "received": 0, "conflicts": 0}
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
    return {"sent": 0, "received": 0, "conflicts": 0}


def _save_last_sync(
        peer_device_id: str, peer_name: str, totals: dict, *,
        generation: Optional[int] = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    safe_summary = {
        "sent": max(0, int(totals.get("sent") or 0)),
        "received": max(0, int(totals.get("received") or 0)),
        "conflicts": max(0, int(totals.get("conflicts") or 0)),
    }
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


def _public_conflicts(connection: sqlite3.Connection) -> list[dict]:
    labels = {
        "note": "Ustanın çalışma notu",
        "memory": "Onaylı hafıza kaydı",
        "goal": "Hedef",
        "checkin": "Anlık durum kaydı",
        "session_summary": "Seans özeti",
        "session_meta": "Seans çerçevesi",
        "message": "Mesaj",
        "conversation": "Görüşme",
    }
    rows = sync_engine.list_conflicts(connection)
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


def _host_on_batch(
        items: list, peer: transport.PeerIdentity, *,
        generation: Optional[int] = None) -> dict:
    global _host_cursor, _host_peer_device_id
    global _host_snapshot_created, _host_totals
    if generation is None:
        with _state_lock:
            generation = _runtime_generation
    _assert_generation(generation)
    _ensure_idle()
    if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items):
        raise SyncServiceError("Eşitleme kayıt paketi geçersiz.")
    if any(item.get("sender_device_id") != peer.device_id for item in items):
        raise SyncServiceError("Eş cihaz kimliği kayıt paketiyle uyuşmuyor.")
    incoming_count = sum(_batch_record_count(item) for item in items)
    if incoming_count and not _host_snapshot_created:
        if _snapshot_callback is not None:
            _snapshot_callback()
        _host_snapshot_created = True

    device_id = _device_id()
    apply_summaries = []
    with _locked():
        _assert_generation(generation)
        with _db_factory() as connection:
            _status_schema(connection)
            for item in items:
                result = sync_engine.apply_change_batch(
                    connection, item, device_id)
                apply_summaries.append(result)
            acknowledged = sync_engine.peer_ack_cursor(
                connection, peer.device_id)
            received = sync_engine.peer_cursor(connection, peer.device_id)
            with _state_lock:
                if _host_peer_device_id not in (None, peer.device_id):
                    raise SyncServiceError(
                        "Eşitleme oturumundaki cihaz beklenmedik biçimde değişti.")
                _host_peer_device_id = peer.device_id
                _host_cursor = max(int(_host_cursor or 0), acknowledged)
                outbound_after = _host_cursor
            outbound = _bounded_export(
                connection, device_id, outbound_after, received)
            with _state_lock:
                _host_cursor = int(outbound["cursor"])

    applied_conflicts = sum(
        int(item.get("conflicts") or 0) for item in apply_summaries)
    with _state_lock:
        _host_totals["received"] += incoming_count
        _host_totals["sent"] += _batch_record_count(outbound)
        _host_totals["conflicts"] += applied_conflicts
        totals = dict(_host_totals)
    _save_last_sync(
        peer.device_id, peer.name, totals, generation=generation)
    if incoming_count and _mutation_callback is not None:
        _mutation_callback()
    result = {
        "batch": outbound,
        "more": bool(outbound["has_more"]),
        "apply": {
            "records": incoming_count,
            "conflicts": applied_conflicts,
        },
    }
    if _json_bytes(result) > transport.MAX_BATCH_BYTES:
        raise SyncServiceError("Eşitleme yanıtı boyut sınırını aşıyor.")
    return result


def start_host(
        *, advertised_host: Optional[str] = None,
        ttl_seconds: int = transport.DEFAULT_TTL_SECONDS) -> dict:
    """Open the explicit one-peer desktop listener and return its QR."""
    global _session, _invitation, _host_cursor, _host_peer_device_id
    global _host_snapshot_created, _host_totals, _busy
    _configured()
    _ensure_idle()
    device_id = _prepare_database(refresh=True)
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
                _host_snapshot_created = False
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
    global _host_snapshot_created, _host_totals
    with _state_lock:
        session = _session
        _session = None
        _invitation = None
        _host_cursor = None
        _host_peer_device_id = None
        _host_snapshot_created = False
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
        device_id = _prepare_database(refresh=True)
        try:
            invitation = transport.parse_invitation(code)
        except ValueError as error:
            raise SyncServiceError(
                "Eşleme kodu geçersiz veya süresi dolmuş.") from error
        name = str(device_name or _device_label()).strip()[:64]
        system_name = str(
            platform_name or platform.system() or "Divan").strip()[:32]
        try:
            client, _ = transport.pair_with_invitation(
                invitation, device_id=device_id,
                public_key=os.urandom(32), name=name,
                platform=system_name, timeout=12.0)
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

        with _locked():
            _assert_generation(generation)
            with _db_factory() as connection:
                outgoing_cursor = sync_engine.peer_ack_cursor(
                    connection, invitation["desktop_device_id"])
        snapshot_created = False
        totals = _empty_totals()

        def next_batch(_peer_result):
            nonlocal outgoing_cursor
            _assert_generation(generation)
            with _locked():
                _assert_generation(generation)
                with _db_factory() as connection:
                    acknowledged_remote = sync_engine.peer_cursor(
                        connection, invitation["desktop_device_id"])
                    outbound = _bounded_export(
                        connection, device_id, outgoing_cursor,
                        acknowledged_remote)
            outgoing_cursor = int(outbound["cursor"])
            totals["sent"] += _batch_record_count(outbound)
            return [outbound], not bool(outbound["has_more"])

        def apply_result(result):
            nonlocal outgoing_cursor, snapshot_created
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
            record_count = _batch_record_count(incoming)
            if record_count and not snapshot_created:
                if _snapshot_callback is not None:
                    _snapshot_callback()
                snapshot_created = True
            with _locked():
                _assert_generation(generation)
                with _db_factory() as connection:
                    merged = sync_engine.apply_change_batch(
                        connection, incoming, device_id)
                    outgoing_cursor = max(
                        outgoing_cursor,
                        sync_engine.peer_ack_cursor(
                            connection,
                            invitation["desktop_device_id"]),
                    )
            totals["received"] += record_count
            totals["conflicts"] += int(merged.get("conflicts") or 0)
            host_apply = result.get("apply")
            if isinstance(host_apply, dict):
                totals["conflicts"] += int(
                    host_apply.get("conflicts") or 0)
            if record_count and _mutation_callback is not None:
                _mutation_callback()

        try:
            client.run_batches(next_batch, apply_result, max_rounds=10000)
        except transport.CertificatePinError as error:
            raise SyncServiceError(
                "QR kodundaki güvenlik doğrulaması başarısız.") from error
        except (transport.SecureSyncError, OSError, ValueError) as error:
            raise SyncServiceError(
                "Eşitleme tamamlanamadı. Güvenli geri dönüş noktası "
                "korundu; yeni bir QR ile yeniden deneyin.") from error
        stamp = _save_last_sync(
            invitation["desktop_device_id"], "Bilgisayar", totals,
            generation=generation)
        with _locked():
            with _db_factory() as connection:
                conflicts = _public_conflicts(connection)
        return {
            "ok": True,
            "summary": dict(totals),
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
    _prepare_database(refresh=False)
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
            _status_schema(connection)
            row = connection.execute(
                "SELECT * FROM sync_local_status WHERE singleton=1"
            ).fetchone()
            conflicts = _public_conflicts(connection)
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
        "scope": [
            "conversations", "messages", "notes", "memories",
            "goals", "checkins", "session_summaries",
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


def resolve_conflict(conflict_id: int, resolution: str) -> dict:
    """Apply an explicit local/remote choice and publish the chosen result."""
    if resolution not in ("local", "remote"):
        raise SyncServiceError("Geçerli bir çakışma kararı seçin.")
    device_id = _prepare_database(refresh=False)
    if _snapshot_callback is not None:
        _snapshot_callback()
    with _locked():
        with _db_factory() as connection:
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
            if resolution == "remote":
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
    global _host_snapshot_created, _host_totals, _active_client
    global _busy, _runtime_generation
    with _state_lock:
        _runtime_generation += 1
        session = _session
        client = _active_client
        _session = None
        _invitation = None
        _host_cursor = None
        _host_peer_device_id = None
        _host_snapshot_created = False
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
