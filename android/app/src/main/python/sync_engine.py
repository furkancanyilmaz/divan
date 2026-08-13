"""Record-level, secret-free sync primitives for Divan.

This module deliberately does not copy SQLite files.  It exports a small
allowlist of logical records and keeps sync identity/version information in
shadow tables, so it can be added to databases created by older Divan builds.

Integration contract
--------------------
Call ``initialize_sync(conn, device_id)`` once after ``server.init_db()``.
After an allowed row is inserted or updated, call
``record_local_change(conn, record_type, local_id, device_id)`` in the same
transaction.  Before the existing deletion flow physically removes a row,
call ``record_local_delete(..., physical=False)`` in that transaction; for a
conversation, the default cascade records tombstones for its syncable child
rows too.

Exchange ``export_change_batch`` results over the authenticated same-Wi-Fi
transport and feed them to ``apply_change_batch``.  Cursors are local change
log positions, not SQLite row ids.  The transport is responsible for peer
authentication, confidentiality, size limits, and replay throttling.

Only RECORD_TYPES below can cross the wire.  In particular ``settings``
(including provider configuration and ``pin_hash``), ``jobs`` and
``chat_requests`` are not addressable by this API.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


BATCH_KIND = "divan-record-sync"
BATCH_VERSION = 2
DEFAULT_BATCH_LIMIT = 500
MAX_BATCH_LIMIT = 1000
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_TEXT_FIELD_BYTES = 512 * 1024
MAX_SHORT_TEXT_BYTES = 4096
MAX_IDENTIFIER_BYTES = 128
_PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_FORBIDDEN_KEYS = frozenset({
    "api_key", "deepseek_api_key", "openai_api_key",
    "anthropic_api_key", "lmstudio_api_key", "pin_hash",
    "password", "secret", "access_token", "refresh_token",
})

# The source database is intentionally more permissive than the wire.  These
# bounds protect a paired device from SQLite's dynamic typing and from records
# which are individually unreasonable even when the whole batch is still under
# MAX_PAYLOAD_BYTES.  Optional legacy columns may be absent, but values which
# are present must have the expected scalar type.
_REQUIRED_PAYLOAD_FIELDS = {
    "conversation": frozenset({"mode"}),
    "message": frozenset({"role", "content", "conversation_public_id"}),
    "note": frozenset({"mode", "content", "conversation_public_id"}),
    "goal": frozenset({"title"}),
    "checkin": frozenset(),
    "memory": frozenset({"therapist", "content"}),
    "session_summary": frozenset({"conversation_public_id"}),
    "session_meta": frozenset({"conversation_public_id"}),
}
_ENUM_FIELDS = {
    ("conversation", "mode"): frozenset({"terapi", "ders"}),
    ("message", "role"): frozenset({"user", "assistant", "system"}),
    ("goal", "status"): frozenset({"active", "done", "archived"}),
    ("session_summary", "status"): frozenset({
        "pending", "approved", "rejected",
    }),
    ("note", "scope"): frozenset({
        "therapist", "shared", "private", "excluded",
    }),
    ("memory", "scope"): frozenset({
        "therapist", "shared", "private", "excluded",
    }),
}
_BOOLEAN_INTEGER_FIELDS = frozenset({
    "ended", "source_mode", "safety_hold", "approved", "sensitive",
    "safety_ok", "precheck_done",
})
_RATING_FIELDS = frozenset({
    "mood", "energy", "happiness", "anxiety", "mood_start", "mood_end",
    "energy_start", "anxiety_start", "intensity_limit",
})
_INTEGER_FIELDS = _BOOLEAN_INTEGER_FIELDS | _RATING_FIELDS | frozenset({
    "available_minutes",
})
_TIMESTAMP_FIELDS = frozenset({
    "created", "updated", "approved_at", "archived_at",
})
_LONG_TEXT_FIELDS = frozenset({
    "content", "draft", "approved_content", "summary", "helpful",
    "next_step", "note", "focus", "avoid_topics",
})


@dataclass(frozen=True)
class RecordSpec:
    table: str
    fields: tuple[str, ...]
    references: tuple[tuple[str, str, str], ...] = ()
    primary_key: str = "id"
    native_public_id: bool = False
    clinical_editable: bool = False
    immutable: bool = False
    timestamp_field: Optional[str] = None


# Keep the wire allowlist intentionally small and auditable. Derived artifacts,
# provider/runtime state, and background work queues do not belong here.
RECORD_TYPES = {
    "conversation": RecordSpec(
        "conversations",
        (
            "mode", "submode", "therapist", "title", "created", "updated",
            "ended", "members", "source_mode", "case_id", "safety_hold",
            "archived_at",
        ),
        (("source_public_id", "source", "conversation"),),
        native_public_id=True,
        timestamp_field="updated",
    ),
    "message": RecordSpec(
        "messages",
        ("role", "content", "created"),
        (
            ("conversation_public_id", "conv", "conversation"),
            ("reply_to_public_id", "reply_to", "message"),
        ),
        native_public_id=True,
        immutable=True,
        timestamp_field="created",
    ),
    "note": RecordSpec(
        "notes",
        (
            "mode", "therapist", "content", "created", "approved", "scope",
            "sensitive", "updated",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "goal": RecordSpec(
        "goals",
        ("title", "status", "created", "updated"),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "checkin": RecordSpec(
        "checkins",
        ("mood", "energy", "happiness", "anxiety", "note", "created"),
        (("conversation_public_id", "conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="created",
    ),
    "memory": RecordSpec(
        "memories",
        (
            "therapist", "kind", "content", "approved", "scope",
            "sensitive", "created", "updated",
        ),
        (("conversation_public_id", "source_conv", "conversation"),),
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "session_summary": RecordSpec(
        "session_summaries",
        (
            "draft", "approved_content", "status", "created", "approved_at",
            "updated",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        primary_key="conv",
        clinical_editable=True,
        timestamp_field="updated",
    ),
    "session_meta": RecordSpec(
        "session_meta",
        (
            "focus", "mood_start", "mood_end", "summary", "helpful",
            "next_step", "energy_start", "anxiety_start",
            "available_minutes", "intensity_limit", "avoid_topics",
            "preferred_pace", "safety_ok", "precheck_done", "updated",
        ),
        (("conversation_public_id", "conv", "conversation"),),
        primary_key="conv",
        clinical_editable=True,
        timestamp_field="updated",
    ),
}

_DEPENDENCY_ORDER = {
    "conversation": 0,
    "message": 1,
    "note": 1,
    "checkin": 1,
    "memory": 1,
    "session_summary": 1,
    "session_meta": 1,
    "goal": 0,
}

# Provenance/context links can outlive their target in legacy databases.  A
# deleted source session or replied-to message must not prevent the surviving
# record from being enrolled in sync; it is transferred with that optional
# link cleared.
_OPTIONAL_REFERENCES = frozenset({
    ("conversation", "source"),
    ("message", "reply_to"),
    ("checkin", "conv"),
    ("memory", "source_conv"),
})


class SyncError(ValueError):
    """The caller supplied an invalid or unsafe sync operation."""


class _MissingDependency(Exception):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _row_dict(row) -> dict:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(
        "PRAGMA table_info({})".format(table)).fetchall()}


def _validate_device_id(device_id: str) -> str:
    if not isinstance(device_id, str) or not _DEVICE_ID_RE.fullmatch(device_id):
        raise SyncError("invalid device id")
    return device_id


def _validate_public_id(public_id: str) -> str:
    if not isinstance(public_id, str) or not _PUBLIC_ID_RE.fullmatch(public_id):
        raise SyncError("invalid public id")
    return public_id


def _new_public_id() -> str:
    return uuid.uuid4().hex


def _canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _payload_hash(payload, deleted_at=None) -> str:
    content = {"deleted_at": deleted_at, "payload": payload}
    return hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _sync_tables(conn: sqlite3.Connection) -> None:
    # ``executescript`` commits any transaction that was already open.  These
    # helpers are also called from application delete transactions, so an
    # implicit commit here would turn an all-or-nothing batch delete into a
    # partial delete.  Execute each DDL statement through the caller's
    # connection instead; SQLite then keeps schema creation/migration inside
    # the same transaction.
    statements = (
        """CREATE TABLE IF NOT EXISTS sync_records(
            record_type TEXT NOT NULL,
            local_id INTEGER,
            public_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            origin_device_id TEXT NOT NULL,
            parent_origin_device_id TEXT,
            parent_revision INTEGER,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            payload_hash TEXT NOT NULL,
            PRIMARY KEY(record_type, public_id)
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS sync_records_local
            ON sync_records(record_type, local_id)
            WHERE local_id IS NOT NULL""",
        """CREATE TABLE IF NOT EXISTS sync_changes(
            cursor INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            origin_device_id TEXT NOT NULL,
            parent_origin_device_id TEXT,
            parent_revision INTEGER,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            payload_json TEXT
        )""",
        """CREATE INDEX IF NOT EXISTS sync_changes_cursor
            ON sync_changes(cursor)""",
        """CREATE TABLE IF NOT EXISTS sync_seen_versions(
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            origin_device_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY(
                record_type, public_id, origin_device_id, revision)
        )""",
        """CREATE TABLE IF NOT EXISTS sync_conflicts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            public_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            local_json TEXT NOT NULL,
            incoming_json TEXT NOT NULL,
            incoming_event_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            resolved_at TEXT,
            resolution TEXT
        )""",
        """CREATE INDEX IF NOT EXISTS sync_conflicts_open
            ON sync_conflicts(status, id)""",
        """CREATE TABLE IF NOT EXISTS sync_peer_cursors(
            peer_device_id TEXT PRIMARY KEY,
            remote_cursor INTEGER NOT NULL DEFAULT 0,
            acknowledged_local_cursor INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )""",
    )
    for statement in statements:
        conn.execute(statement)
    peer_columns = _columns(conn, "sync_peer_cursors")
    if "acknowledged_local_cursor" not in peer_columns:
        conn.execute(
            "ALTER TABLE sync_peer_cursors ADD COLUMN "
            "acknowledged_local_cursor INTEGER NOT NULL DEFAULT 0")


def initialize_sync(
        conn: sqlite3.Connection,
        device_id: str,
        *,
        bootstrap: bool = True,
) -> dict:
    """Create additive shadow tables and optionally publish legacy rows."""
    device_id = _validate_device_id(device_id)
    _sync_tables(conn)
    privacy = scrub_all_deleted_history(conn)
    counts = {
        "bootstrapped": 0,
        "tables_missing": [],
        "scrubbed": privacy["records"],
    }
    if not bootstrap:
        return counts
    for record_type in sorted(
            RECORD_TYPES, key=lambda value: _DEPENDENCY_ORDER[value]):
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            counts["tables_missing"].append(spec.table)
            continue
        for row in conn.execute(
            "SELECT {0} FROM {1} ORDER BY {0}".format(
                spec.primary_key, spec.table)
        ).fetchall():
            local_id = row[0]
            exists = conn.execute(
                "SELECT 1 FROM sync_records "
                "WHERE record_type=? AND local_id=?",
                (record_type, local_id),
            ).fetchone()
            if not exists:
                record_local_change(
                    conn, record_type, local_id, device_id,
                    updated_at=_row_timestamp(
                        conn, record_type, local_id) or _utcnow(),
                )
                counts["bootstrapped"] += 1
    return counts


def _row_timestamp(
        conn: sqlite3.Connection, record_type: str, local_id: int
) -> Optional[str]:
    spec = RECORD_TYPES[record_type]
    cols = _columns(conn, spec.table)
    candidates = [
        value for value in (spec.timestamp_field, "updated", "created")
        if value and value in cols
    ]
    if not candidates:
        return None
    select = ",".join(candidates)
    row = conn.execute(
        "SELECT {} FROM {} WHERE {}=?".format(
            select, spec.table, spec.primary_key),
        (local_id,),
    ).fetchone()
    if not row:
        return None
    for value in row:
        if value:
            return str(value)
    return None


def _public_id_for_local(
        conn: sqlite3.Connection,
        record_type: str,
        local_id: Optional[int],
) -> Optional[str]:
    if local_id is None:
        return None
    row = conn.execute(
        "SELECT public_id FROM sync_records "
        "WHERE record_type=? AND local_id=?",
        (record_type, local_id),
    ).fetchone()
    if row:
        return row[0]
    spec = RECORD_TYPES[record_type]
    if spec.native_public_id and _table_exists(conn, spec.table):
        native = conn.execute(
            "SELECT public_id FROM {} WHERE {}=?".format(
                spec.table, spec.primary_key),
            (local_id,),
        ).fetchone()
        if native and native[0]:
            return str(native[0])
    return None


def _serialize_row(
        conn: sqlite3.Connection, record_type: str, local_id: int
) -> tuple[str, dict]:
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        raise SyncError("record table does not exist")
    row = conn.execute(
        "SELECT * FROM {} WHERE {}=?".format(
            spec.table, spec.primary_key), (local_id,)
    ).fetchone()
    if not row:
        raise SyncError("record does not exist")
    values = _row_dict(row)

    meta = conn.execute(
        "SELECT public_id FROM sync_records "
        "WHERE record_type=? AND local_id=?",
        (record_type, local_id),
    ).fetchone()
    public_id = str(meta[0]) if meta else ""
    if spec.native_public_id and not public_id:
        native = str(values.get("public_id") or "")
        if native:
            public_id = native
    collision = None
    if public_id:
        collision = conn.execute(
            "SELECT local_id FROM sync_records "
            "WHERE record_type=? AND public_id=?",
            (record_type, public_id),
        ).fetchone()
    if (
        not public_id
        or not _PUBLIC_ID_RE.fullmatch(public_id)
        or (collision and collision[0] != local_id)
    ):
        public_id = ""
    if not public_id:
        public_id = _new_public_id()
        if spec.native_public_id and "public_id" in values:
            conn.execute(
                "UPDATE {} SET public_id=? WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (public_id, local_id),
            )

    payload = {
        field: values[field]
        for field in spec.fields if field in values
    }
    for payload_name, column, target_type in spec.references:
        if column not in values:
            continue
        reference_id = values[column]
        if reference_id is None:
            payload[payload_name] = None
            continue
        reference_public_id = _public_id_for_local(
            conn, target_type, reference_id)
        if reference_public_id is None:
            if (record_type, column) in _OPTIONAL_REFERENCES:
                payload[payload_name] = None
                continue
            raise SyncError(
                "referenced {} row has no sync identity".format(target_type))
        payload[payload_name] = reference_public_id
    return public_id, payload


def _event_id(record: dict) -> str:
    return "{}:{}:{}:{}".format(
        record["origin_device_id"], record["record_type"],
        record["public_id"], record["revision"],
    )


def _append_change(conn: sqlite3.Connection, record: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sync_changes("
        "event_id,record_type,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            _event_id(record), record["record_type"], record["public_id"],
            record["revision"], record["origin_device_id"],
            record.get("parent_origin_device_id"),
            record.get("parent_revision"), record["updated_at"],
            record.get("deleted_at"),
            None if record.get("payload") is None
            else _canonical_json(record["payload"]),
        ),
    )


def _mark_seen(conn: sqlite3.Connection, record: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sync_seen_versions("
        "record_type,public_id,origin_device_id,revision,seen_at)"
        " VALUES(?,?,?,?,?)",
        (
            record["record_type"], record["public_id"],
            record["origin_device_id"], record["revision"], _utcnow(),
        ),
    )


def _scrub_deleted_record_history(
        conn: sqlite3.Connection, record_type: str, public_id: str) -> dict:
    """Keep one payload-free tombstone and erase content-bearing sync audit.

    ``sync_changes`` is a delivery queue, not an immutable clinical audit log.
    Once the current head is a deletion, retaining prior payload snapshots or
    conflict JSON would defeat the user's deletion request.  Seen-version rows
    are intentionally retained: they contain no user text and stop a stale
    peer from replaying a previously observed live version.
    """
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    if raw_meta is None:
        raise SyncError("sync record not found")
    meta = _row_dict(raw_meta)
    if meta["deleted_at"] is None:
        raise SyncError("live sync history cannot be scrubbed")
    tombstone = {
        "record_type": record_type,
        "public_id": public_id,
        "revision": int(meta["revision"]),
        "origin_device_id": meta["origin_device_id"],
        "parent_origin_device_id": meta["parent_origin_device_id"],
        "parent_revision": meta["parent_revision"],
        "updated_at": meta["updated_at"],
        "deleted_at": meta["deleted_at"],
        "payload": None,
    }
    _append_change(conn, tombstone)
    keep_event_id = _event_id(tombstone)
    # Repair old databases defensively in case the retained event was created
    # by a pre-redaction build with an unexpected payload.
    conn.execute(
        "UPDATE sync_changes SET record_type=?,public_id=?,revision=?,"
        "origin_device_id=?,parent_origin_device_id=?,parent_revision=?,"
        "updated_at=?,deleted_at=?,payload_json=NULL WHERE event_id=?",
        (
            record_type, public_id, tombstone["revision"],
            tombstone["origin_device_id"],
            tombstone["parent_origin_device_id"],
            tombstone["parent_revision"], tombstone["updated_at"],
            tombstone["deleted_at"], keep_event_id,
        ),
    )
    removed_changes = conn.execute(
        "DELETE FROM sync_changes WHERE record_type=? AND public_id=? "
        "AND event_id<>?",
        (record_type, public_id, keep_event_id),
    ).rowcount
    removed_conflicts = conn.execute(
        "DELETE FROM sync_conflicts WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).rowcount
    return {
        "record_type": record_type,
        "public_id": public_id,
        "removed_changes": max(0, int(removed_changes)),
        "removed_conflicts": max(0, int(removed_conflicts)),
        "tombstone_event_id": keep_event_id,
    }


def scrub_deleted_record_history(
        conn: sqlite3.Connection, record_type: str, public_id: str) -> dict:
    """Public privacy API for one record whose current head is a deletion."""
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    public_id = _validate_public_id(public_id)
    _sync_tables(conn)
    return _scrub_deleted_record_history(conn, record_type, public_id)


def scrub_all_deleted_history(conn: sqlite3.Connection) -> dict:
    """Upgrade old databases by redacting every already-deleted record."""
    _sync_tables(conn)
    rows = conn.execute(
        "SELECT record_type,public_id FROM sync_records "
        "WHERE deleted_at IS NOT NULL ORDER BY record_type,public_id"
    ).fetchall()
    result = {"records": 0, "removed_changes": 0, "removed_conflicts": 0}
    for row in rows:
        if row[0] not in RECORD_TYPES:
            continue
        cleaned = _scrub_deleted_record_history(conn, row[0], row[1])
        result["records"] += 1
        result["removed_changes"] += cleaned["removed_changes"]
        result["removed_conflicts"] += cleaned["removed_conflicts"]
    return result


def reset_sync_state(conn: sqlite3.Connection) -> dict:
    """Erase all merge/delivery state after an application-wide deletion.

    SQLite's AUTOINCREMENT high-water value is deliberately not reset.  New
    events therefore remain above cursors acknowledged by a previously paired
    device when the installation identity itself is retained.
    """
    _sync_tables(conn)
    result = {}
    for table in (
            "sync_conflicts", "sync_changes", "sync_seen_versions",
            "sync_records", "sync_peer_cursors"):
        result[table] = max(0, int(conn.execute(
            "DELETE FROM {}".format(table)).rowcount))
    if _table_exists(conn, "sync_local_status"):
        conn.execute(
            "UPDATE sync_local_status SET last_sync_at=NULL,"
            "last_peer_device_id=NULL,last_peer_name=NULL,"
            "last_summary_json='{}' WHERE singleton=1")
        result["sync_local_status"] = 1
    return result


def record_local_change(
        conn: sqlite3.Connection,
        record_type: str,
        local_id: int,
        device_id: str,
        *,
        updated_at: Optional[str] = None,
) -> dict:
    """Snapshot one allowed local row and append a causal change event."""
    device_id = _validate_device_id(device_id)
    if type(local_id) is not int or local_id < 1:
        raise SyncError("invalid local id")
    _sync_tables(conn)
    public_id, payload = _serialize_row(conn, record_type, local_id)
    previous = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    previous = _row_dict(previous) if previous else None
    revision = int(previous["revision"]) + 1 if previous else 1
    stamp = str(updated_at or _utcnow())
    record = {
        "record_type": record_type,
        "public_id": public_id,
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": (
            previous["origin_device_id"] if previous else None),
        "parent_revision": previous["revision"] if previous else None,
        "updated_at": stamp,
        "deleted_at": None,
        "payload": payload,
    }
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(record_type,public_id) DO UPDATE SET "
        "local_id=excluded.local_id,revision=excluded.revision,"
        "origin_device_id=excluded.origin_device_id,"
        "parent_origin_device_id=excluded.parent_origin_device_id,"
        "parent_revision=excluded.parent_revision,"
        "updated_at=excluded.updated_at,deleted_at=NULL,"
        "payload_hash=excluded.payload_hash",
        (
            record_type, local_id, public_id, revision, device_id,
            record["parent_origin_device_id"], record["parent_revision"],
            stamp, None, _payload_hash(payload),
        ),
    )
    _mark_seen(conn, record)
    _append_change(conn, record)
    return record


def _record_missing_local_delete(
        conn: sqlite3.Connection,
        meta: dict,
        device_id: str,
        deleted_at: str,
) -> dict:
    """Turn a live shadow row whose physical row vanished into a tombstone."""
    revision = int(meta["revision"]) + 1
    record = {
        "record_type": meta["record_type"],
        "public_id": meta["public_id"],
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": meta["origin_device_id"],
        "parent_revision": meta["revision"],
        "updated_at": deleted_at,
        "deleted_at": deleted_at,
        "payload": None,
    }
    conn.execute(
        "UPDATE sync_records SET local_id=NULL,revision=?,"
        "origin_device_id=?,parent_origin_device_id=?,parent_revision=?,"
        "updated_at=?,deleted_at=?,payload_hash=? "
        "WHERE record_type=? AND public_id=? AND local_id IS NOT NULL "
        "AND deleted_at IS NULL",
        (
            revision, device_id, meta["origin_device_id"], meta["revision"],
            deleted_at, deleted_at, _payload_hash(None, deleted_at),
            meta["record_type"], meta["public_id"],
        ),
    )
    _mark_seen(conn, record)
    _append_change(conn, record)
    _scrub_deleted_record_history(
        conn, record["record_type"], record["public_id"])
    return record


def refresh_local_changes(
        conn: sqlite3.Connection,
        device_id: str,
) -> dict:
    """Discover unhooked local writes and physical deletes by full scan.

    This is the safety net for legacy server mutation paths which do not yet
    call ``record_local_change``/``record_local_delete`` in their transaction.
    The scan compares canonical logical payload hashes, never raw SQLite
    pages.  Calling it repeatedly without an intervening physical mutation
    appends no new changes.
    """
    device_id = _validate_device_id(device_id)
    _sync_tables(conn)
    counts = {
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "unchanged": 0,
        "tables_missing": [],
    }
    ordered_types = sorted(
        RECORD_TYPES, key=lambda value: _DEPENDENCY_ORDER[value])

    # Parents are visited first so newly discovered child rows can encode
    # their references with the parent's stable public identity.
    for record_type in ordered_types:
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            counts["tables_missing"].append(spec.table)
            continue
        rows = conn.execute(
            "SELECT {0} FROM {1} ORDER BY {0}".format(
                spec.primary_key, spec.table)
        ).fetchall()
        for row in rows:
            local_id = int(row[0])
            raw_meta = conn.execute(
                "SELECT * FROM sync_records "
                "WHERE record_type=? AND local_id=?",
                (record_type, local_id),
            ).fetchone()
            if raw_meta is None:
                record_local_change(
                    conn, record_type, local_id, device_id)
                counts["added"] += 1
                continue
            meta = _row_dict(raw_meta)
            _, payload = _serialize_row(
                conn, record_type, local_id)
            if (
                meta["deleted_at"] is None
                and meta["payload_hash"] == _payload_hash(payload)
            ):
                counts["unchanged"] += 1
                continue
            record_local_change(
                conn, record_type, local_id, device_id)
            counts["updated"] += 1

    # A physical delete has no row left for record_local_delete to serialize.
    # Scan only live shadows, and clear local_id as part of the tombstone so a
    # second refresh cannot emit the same deletion again.
    stamp = _utcnow()
    for record_type in ordered_types:
        spec = RECORD_TYPES[record_type]
        if not _table_exists(conn, spec.table):
            continue
        live_meta = conn.execute(
            "SELECT * FROM sync_records WHERE record_type=? "
            "AND local_id IS NOT NULL AND deleted_at IS NULL "
            "ORDER BY local_id",
            (record_type,),
        ).fetchall()
        for raw_meta in live_meta:
            meta = _row_dict(raw_meta)
            exists = conn.execute(
                "SELECT 1 FROM {} WHERE {}=?".format(
                    spec.table, spec.primary_key),
                (meta["local_id"],),
            ).fetchone()
            if exists is not None:
                continue
            _record_missing_local_delete(
                conn, meta, device_id, stamp)
            counts["deleted"] += 1
    return counts


def _dependent_local_ids(
        conn: sqlite3.Connection, conversation_id: int
) -> list[tuple[str, int]]:
    result = []
    for record_type, spec in RECORD_TYPES.items():
        if record_type == "conversation" or not _table_exists(conn, spec.table):
            continue
        for _, column, target in spec.references:
            if target != "conversation" or column not in _columns(
                    conn, spec.table):
                continue
            result.extend(
                (record_type, row[0]) for row in conn.execute(
                    "SELECT {0} FROM {1} WHERE {2}=? ORDER BY {0}".format(
                        spec.primary_key, spec.table, column),
                    (conversation_id,),
                ).fetchall()
            )
    return result


def record_local_delete(
        conn: sqlite3.Connection,
        record_type: str,
        local_id: int,
        device_id: str,
        *,
        deleted_at: Optional[str] = None,
        cascade: bool = True,
        physical: bool = False,
) -> list[dict]:
    """Create durable tombstones before the application's physical delete."""
    device_id = _validate_device_id(device_id)
    if record_type not in RECORD_TYPES:
        raise SyncError("record type is not syncable")
    _sync_tables(conn)
    stamp = str(deleted_at or _utcnow())
    records = []
    if record_type == "conversation" and cascade:
        for child_type, child_id in _dependent_local_ids(conn, local_id):
            records.extend(record_local_delete(
                conn, child_type, child_id, device_id,
                deleted_at=stamp, cascade=False, physical=physical,
            ))

    public_id, _ = _serialize_row(conn, record_type, local_id)
    previous_row = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    previous = _row_dict(previous_row) if previous_row else None
    revision = int(previous["revision"]) + 1 if previous else 1
    record = {
        "record_type": record_type,
        "public_id": public_id,
        "revision": revision,
        "origin_device_id": device_id,
        "parent_origin_device_id": (
            previous["origin_device_id"] if previous else None),
        "parent_revision": previous["revision"] if previous else None,
        "updated_at": stamp,
        "deleted_at": stamp,
        "payload": None,
    }
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(record_type,public_id) DO UPDATE SET "
        "local_id=NULL,revision=excluded.revision,"
        "origin_device_id=excluded.origin_device_id,"
        "parent_origin_device_id=excluded.parent_origin_device_id,"
        "parent_revision=excluded.parent_revision,"
        "updated_at=excluded.updated_at,deleted_at=excluded.deleted_at,"
        "payload_hash=excluded.payload_hash",
        (
            record_type, None, public_id, revision, device_id,
            record["parent_origin_device_id"], record["parent_revision"],
            stamp, stamp, _payload_hash(None, stamp),
        ),
    )
    _mark_seen(conn, record)
    _append_change(conn, record)
    _scrub_deleted_record_history(conn, record_type, public_id)
    if physical:
        conn.execute(
            "DELETE FROM {} WHERE {}=?".format(
                RECORD_TYPES[record_type].table,
                RECORD_TYPES[record_type].primary_key),
            (local_id,),
        )
    records.append(record)
    return records


def export_change_batch(
        conn: sqlite3.Connection,
        device_id: str,
        *,
        after_cursor: int = 0,
        ack_cursor: int = 0,
        limit: int = DEFAULT_BATCH_LIMIT,
) -> dict:
    """Return a bounded, secret-free logical change batch."""
    device_id = _validate_device_id(device_id)
    if type(after_cursor) is not int or after_cursor < 0:
        raise SyncError("invalid cursor")
    if type(ack_cursor) is not int or ack_cursor < 0:
        raise SyncError("invalid acknowledgement cursor")
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH_LIMIT:
        raise SyncError("invalid batch limit")
    _sync_tables(conn)
    rows = conn.execute(
        "SELECT * FROM sync_changes WHERE cursor>? "
        "ORDER BY cursor LIMIT ?",
        (after_cursor, limit),
    ).fetchall()
    records = []
    cursor = after_cursor
    for raw in rows:
        row = _row_dict(raw)
        cursor = int(row["cursor"])
        record = {
            "record_type": row["record_type"],
            "public_id": row["public_id"],
            "revision": row["revision"],
            "origin_device_id": row["origin_device_id"],
            "parent_origin_device_id": row["parent_origin_device_id"],
            "parent_revision": row["parent_revision"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "payload": (
                None if row["payload_json"] is None
                else json.loads(row["payload_json"])),
        }
        if record["record_type"] not in RECORD_TYPES:
            raise SyncError("unsafe record found in change log")
        records.append(record)
    remaining = conn.execute(
        "SELECT 1 FROM sync_changes WHERE cursor>? LIMIT 1", (cursor,)
    ).fetchone() is not None
    return {
        "kind": BATCH_KIND,
        "version": BATCH_VERSION,
        "sender_device_id": device_id,
        "after_cursor": after_cursor,
        "cursor": cursor,
        "ack_cursor": ack_cursor,
        "has_more": remaining,
        "records": records,
    }


def _text_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _validate_text_field(record_type: str, key: str, value: str) -> None:
    if "\x00" in value:
        raise SyncError("payload text contains a null byte")
    if key in _TIMESTAMP_FIELDS:
        if not value or _text_size(value) > 64:
            raise SyncError("invalid payload timestamp")
        return
    if key in _LONG_TEXT_FIELDS:
        limit = MAX_TEXT_FIELD_BYTES
    elif key == "title":
        limit = MAX_SHORT_TEXT_BYTES
    elif key in {
            "mode", "submode", "therapist", "status", "scope", "kind",
            "preferred_pace", "case_id", "role"}:
        limit = MAX_IDENTIFIER_BYTES
    else:
        limit = MAX_SHORT_TEXT_BYTES
    if _text_size(value) > limit:
        raise SyncError("payload text field is too large")
    allowed = _ENUM_FIELDS.get((record_type, key))
    if allowed is not None and value not in allowed:
        raise SyncError("invalid enumerated payload field")


def _validate_payload(record_type: str, payload) -> None:
    if not isinstance(payload, dict):
        raise SyncError("live record payload must be an object")
    spec = RECORD_TYPES[record_type]
    allowed = set(spec.fields)
    allowed.update(item[0] for item in spec.references)
    unknown = set(payload) - allowed
    forbidden = set(payload) & _FORBIDDEN_KEYS
    if forbidden:
        raise SyncError("secret fields are forbidden")
    if unknown:
        raise SyncError("unknown logical record fields")
    required = _REQUIRED_PAYLOAD_FIELDS[record_type]
    if any(key not in payload or payload[key] is None for key in required):
        raise SyncError("required logical record field is missing")
    reference_fields = {item[0] for item in spec.references}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            raise SyncError("nested logical record fields are forbidden")
        if key in reference_fields:
            if value is not None:
                _validate_public_id(value)
            continue
        if value is None:
            continue
        if isinstance(value, bool):
            raise SyncError("boolean payload fields are forbidden")
        if isinstance(value, str):
            if key in _INTEGER_FIELDS:
                raise SyncError("numeric payload field must be an integer")
            _validate_text_field(record_type, key, value)
            continue
        if type(value) is not int:
            raise SyncError("unsupported logical record field type")
        if key not in _INTEGER_FIELDS:
            raise SyncError("text payload field must be a string")
        if key in _BOOLEAN_INTEGER_FIELDS and value not in (0, 1):
            raise SyncError("invalid boolean integer payload field")
        if key in _RATING_FIELDS and not 0 <= value <= 10:
            raise SyncError("invalid rating payload field")
        if key == "available_minutes" and not 1 <= value <= 1440:
            raise SyncError("invalid available minutes payload field")


def validate_change_batch(batch: dict) -> dict:
    if not isinstance(batch, dict) or set(batch) != {
        "kind", "version", "sender_device_id", "after_cursor", "cursor",
        "ack_cursor", "has_more", "records",
    }:
        raise SyncError("invalid sync batch shape")
    if batch["kind"] != BATCH_KIND or batch["version"] != BATCH_VERSION:
        raise SyncError("unsupported sync batch")
    _validate_device_id(batch["sender_device_id"])
    if type(batch["after_cursor"]) is not int or batch["after_cursor"] < 0:
        raise SyncError("invalid batch cursor")
    if type(batch["cursor"]) is not int or (
            batch["cursor"] < batch["after_cursor"]):
        raise SyncError("invalid batch cursor")
    if type(batch["ack_cursor"]) is not int or batch["ack_cursor"] < 0:
        raise SyncError("invalid acknowledgement cursor")
    if type(batch["has_more"]) is not bool:
        raise SyncError("invalid continuation flag")
    if not isinstance(batch["records"], list) or (
            len(batch["records"]) > MAX_BATCH_LIMIT):
        raise SyncError("invalid record list")
    if len(_canonical_json(batch).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise SyncError("sync batch is too large")
    for record in batch["records"]:
        if not isinstance(record, dict) or set(record) != {
            "record_type", "public_id", "revision", "origin_device_id",
            "parent_origin_device_id", "parent_revision", "updated_at",
            "deleted_at", "payload",
        }:
            raise SyncError("invalid sync record shape")
        record_type = record["record_type"]
        if record_type not in RECORD_TYPES:
            raise SyncError("record type is not syncable")
        _validate_public_id(record["public_id"])
        _validate_device_id(record["origin_device_id"])
        parent_origin = record["parent_origin_device_id"]
        parent_revision = record["parent_revision"]
        if (parent_origin is None) != (parent_revision is None):
            raise SyncError("incomplete parent version")
        if parent_origin is not None:
            _validate_device_id(parent_origin)
        if type(record["revision"]) is not int or record["revision"] < 1:
            raise SyncError("invalid revision")
        if parent_revision is not None and (
                type(parent_revision) is not int or parent_revision < 1):
            raise SyncError("invalid parent revision")
        if (not isinstance(record["updated_at"], str)
                or not record["updated_at"]
                or "\x00" in record["updated_at"]
                or _text_size(record["updated_at"]) > 64):
            raise SyncError("invalid update time")
        if record["deleted_at"] is not None and (
                not isinstance(record["deleted_at"], str)
                or not record["deleted_at"]
                or "\x00" in record["deleted_at"]
                or _text_size(record["deleted_at"]) > 64):
            raise SyncError("invalid deletion time")
        if record["deleted_at"] is not None:
            if record["payload"] is not None:
                raise SyncError("tombstone payload must be null")
        else:
            _validate_payload(record_type, record["payload"])
    return batch


def _find_local_id(
        conn: sqlite3.Connection, record_type: str, public_id: str
) -> Optional[int]:
    row = conn.execute(
        "SELECT local_id FROM sync_records "
        "WHERE record_type=? AND public_id=?",
        (record_type, public_id),
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0])
    spec = RECORD_TYPES[record_type]
    if spec.native_public_id and _table_exists(conn, spec.table):
        native = conn.execute(
            "SELECT {} FROM {} WHERE public_id=?".format(
                spec.primary_key, spec.table),
            (public_id,),
        ).fetchone()
        return int(native[0]) if native else None
    return None


def _payload_to_columns(
        conn: sqlite3.Connection, record_type: str, payload: dict
) -> dict:
    spec = RECORD_TYPES[record_type]
    table_columns = _columns(conn, spec.table)
    values = {
        key: value for key, value in payload.items()
        if key in spec.fields and key in table_columns
    }
    for payload_name, column, target_type in spec.references:
        if column not in table_columns or payload_name not in payload:
            continue
        reference = payload[payload_name]
        if reference is None:
            values[column] = None
            continue
        reference_id = _find_local_id(conn, target_type, reference)
        if reference_id is None:
            raise _MissingDependency(
                "{} {}".format(target_type, reference))
        values[column] = reference_id
    return values


def _write_payload(
        conn: sqlite3.Connection,
        record_type: str,
        public_id: str,
        payload: dict,
        local_id: Optional[int],
) -> int:
    spec = RECORD_TYPES[record_type]
    if not _table_exists(conn, spec.table):
        raise SyncError("target database lacks a required record table")
    values = _payload_to_columns(conn, record_type, payload)
    columns = _columns(conn, spec.table)
    if spec.native_public_id and "public_id" in columns:
        values["public_id"] = public_id
    if local_id is None:
        if not values:
            raise SyncError("record has no fields supported by target schema")
        names = list(values)
        cursor = conn.execute(
            "INSERT INTO {}({}) VALUES({})".format(
                spec.table, ",".join(names),
                ",".join("?" for _ in names)),
            [values[name] for name in names],
        )
        return int(cursor.lastrowid)
    if values:
        names = list(values)
        conn.execute(
            "UPDATE {} SET {} WHERE {}=?".format(
                spec.table,
                ",".join("{}=?".format(name) for name in names),
                spec.primary_key),
            [values[name] for name in names] + [local_id],
        )
    return local_id


def _record_from_meta(
        conn: sqlite3.Connection, meta: dict
) -> dict:
    payload = None
    if meta["deleted_at"] is None and meta["local_id"] is not None:
        _, payload = _serialize_row(
            conn, meta["record_type"], int(meta["local_id"]))
    return {
        "record_type": meta["record_type"],
        "public_id": meta["public_id"],
        "revision": meta["revision"],
        "origin_device_id": meta["origin_device_id"],
        "parent_origin_device_id": meta["parent_origin_device_id"],
        "parent_revision": meta["parent_revision"],
        "updated_at": meta["updated_at"],
        "deleted_at": meta["deleted_at"],
        "payload": payload,
    }


def _is_direct_child(incoming: dict, local: dict) -> bool:
    return (
        incoming["parent_origin_device_id"] == local["origin_device_id"]
        and incoming["parent_revision"] == local["revision"]
    )


def _is_known_ancestor(incoming: dict, local: dict) -> bool:
    return (
        local["parent_origin_device_id"] == incoming["origin_device_id"]
        and local["parent_revision"] == incoming["revision"]
    ) or (
        local["origin_device_id"] == incoming["origin_device_id"]
        and int(local["revision"]) >= int(incoming["revision"])
    )


def _queue_conflict(
        conn: sqlite3.Connection,
        local: dict,
        incoming: dict,
        reason: str,
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO sync_conflicts("
        "record_type,public_id,reason,local_json,incoming_json,"
        "incoming_event_id,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            incoming["record_type"], incoming["public_id"], reason,
            _canonical_json(local), _canonical_json(incoming),
            _event_id(incoming), _utcnow(),
        ),
    )
    return cursor.rowcount > 0


def _install_incoming(
        conn: sqlite3.Connection,
        incoming: dict,
        local_meta: Optional[dict],
) -> None:
    record_type = incoming["record_type"]
    public_id = incoming["public_id"]
    local_id = int(local_meta["local_id"]) if (
        local_meta and local_meta["local_id"] is not None) else None
    if incoming["deleted_at"] is not None:
        if local_id is not None:
            conn.execute(
                "DELETE FROM {} WHERE {}=?".format(
                    RECORD_TYPES[record_type].table,
                    RECORD_TYPES[record_type].primary_key),
                (local_id,),
            )
        local_id = None
    else:
        local_id = _write_payload(
            conn, record_type, public_id, incoming["payload"], local_id)
    conn.execute(
        "INSERT INTO sync_records("
        "record_type,local_id,public_id,revision,origin_device_id,"
        "parent_origin_device_id,parent_revision,updated_at,deleted_at,"
        "payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(record_type,public_id) DO UPDATE SET "
        "local_id=excluded.local_id,revision=excluded.revision,"
        "origin_device_id=excluded.origin_device_id,"
        "parent_origin_device_id=excluded.parent_origin_device_id,"
        "parent_revision=excluded.parent_revision,"
        "updated_at=excluded.updated_at,deleted_at=excluded.deleted_at,"
        "payload_hash=excluded.payload_hash",
        (
            record_type, local_id, public_id, incoming["revision"],
            incoming["origin_device_id"],
            incoming["parent_origin_device_id"],
            incoming["parent_revision"], incoming["updated_at"],
            incoming["deleted_at"],
            _payload_hash(incoming["payload"], incoming["deleted_at"]),
        ),
    )
    _mark_seen(conn, incoming)
    _append_change(conn, incoming)
    if incoming["deleted_at"] is not None:
        _scrub_deleted_record_history(conn, record_type, public_id)


def _apply_one(conn: sqlite3.Connection, incoming: dict) -> str:
    seen = conn.execute(
        "SELECT 1 FROM sync_seen_versions WHERE record_type=? "
        "AND public_id=? AND origin_device_id=? AND revision=?",
        (
            incoming["record_type"], incoming["public_id"],
            incoming["origin_device_id"], incoming["revision"],
        ),
    ).fetchone()
    if seen:
        return "ignored"
    raw_meta = conn.execute(
        "SELECT * FROM sync_records WHERE record_type=? AND public_id=?",
        (incoming["record_type"], incoming["public_id"]),
    ).fetchone()
    if raw_meta is None:
        _install_incoming(conn, incoming, None)
        return "applied"
    meta = _row_dict(raw_meta)
    local = _record_from_meta(conn, meta)
    same_content = meta["payload_hash"] == _payload_hash(
        incoming["payload"], incoming["deleted_at"])
    if _is_known_ancestor(incoming, local):
        _mark_seen(conn, incoming)
        _append_change(conn, incoming)
        return "ignored"
    direct = _is_direct_child(incoming, local)
    causal_newer = direct or (
        incoming["origin_device_id"] == local["origin_device_id"]
        and int(incoming["revision"]) > int(local["revision"])
    )
    spec = RECORD_TYPES[incoming["record_type"]]

    if same_content:
        # Identical concurrent snapshots are safe to coalesce.  Keep a
        # deterministic head so all peers eventually choose the same one.
        if causal_newer or (
            incoming["updated_at"], incoming["origin_device_id"],
            incoming["revision"],
        ) > (
            local["updated_at"], local["origin_device_id"], local["revision"],
        ):
            _install_incoming(conn, incoming, meta)
            return "applied"
        _mark_seen(conn, incoming)
        _append_change(conn, incoming)
        return "ignored"

    if spec.immutable and (
            incoming["deleted_at"] is None and local["deleted_at"] is None):
        created = _queue_conflict(
            conn, local, incoming, "immutable_record_mismatch")
        _mark_seen(conn, incoming)
        _append_change(conn, incoming)
        return "conflict" if created else "ignored"

    if causal_newer:
        _install_incoming(conn, incoming, meta)
        return "applied"

    if spec.clinical_editable:
        created = _queue_conflict(
            conn, local, incoming, "concurrent_clinical_edit")
        _mark_seen(conn, incoming)
        _append_change(conn, incoming)
        return "conflict" if created else "ignored"

    incoming_key = (
        incoming["updated_at"], incoming["origin_device_id"],
        incoming["revision"],
    )
    local_key = (
        local["updated_at"], local["origin_device_id"], local["revision"],
    )
    if incoming_key > local_key:
        _install_incoming(conn, incoming, meta)
        return "applied"
    _mark_seen(conn, incoming)
    _append_change(conn, incoming)
    return "ignored"


def apply_change_batch(
        conn: sqlite3.Connection,
        batch: dict,
        device_id: str,
) -> dict:
    """Merge a validated batch; user-editable clinical races are queued."""
    _validate_device_id(device_id)
    validate_change_batch(batch)
    _sync_tables(conn)
    if batch["ack_cursor"] > local_cursor_high_water(conn):
        raise SyncError("peer acknowledged an unknown local cursor")
    summary = {
        "applied": 0,
        "ignored": 0,
        "conflicts": 0,
        "deferred": 0,
        "cursor": batch["cursor"],
        "ack_cursor": batch["ack_cursor"],
    }
    records = sorted(
        batch["records"],
        key=lambda item: (
            1 if item["deleted_at"] is not None else 0,
            (
                -_DEPENDENCY_ORDER[item["record_type"]]
                if item["deleted_at"] is not None
                else _DEPENDENCY_ORDER[item["record_type"]]
            ),
        ),
    )
    pending = list(records)
    while pending:
        next_pending = []
        progressed = False
        for record in pending:
            try:
                result = _apply_one(conn, record)
            except _MissingDependency:
                next_pending.append(record)
                continue
            progressed = True
            if result == "applied":
                summary["applied"] += 1
            elif result == "conflict":
                summary["conflicts"] += 1
            else:
                summary["ignored"] += 1
        if not next_pending or not progressed:
            pending = next_pending
            break
        pending = next_pending
    for record in pending:
        local = {
            "record_type": record["record_type"],
            "public_id": record["public_id"],
            "missing_dependency": True,
        }
        if _queue_conflict(
                conn, local, record, "missing_dependency"):
            summary["conflicts"] += 1
        else:
            summary["ignored"] += 1
        _mark_seen(conn, record)
        _append_change(conn, record)
        summary["deferred"] += 1
    conn.execute(
        "INSERT INTO sync_peer_cursors("
        "peer_device_id,remote_cursor,acknowledged_local_cursor,updated_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(peer_device_id) DO UPDATE SET "
        "remote_cursor=MAX(remote_cursor,excluded.remote_cursor),"
        "acknowledged_local_cursor=MAX("
        "acknowledged_local_cursor,excluded.acknowledged_local_cursor),"
        "updated_at=excluded.updated_at",
        (
            batch["sender_device_id"], batch["cursor"],
            batch["ack_cursor"], _utcnow(),
        ),
    )
    return summary


def local_cursor_high_water(conn: sqlite3.Connection) -> int:
    """Return the greatest cursor ever allocated by this change log."""
    _sync_tables(conn)
    current = conn.execute(
        "SELECT COALESCE(MAX(cursor),0) FROM sync_changes").fetchone()[0]
    allocated = 0
    if _table_exists(conn, "sqlite_sequence"):
        row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='sync_changes'"
        ).fetchone()
        allocated = int(row[0]) if row else 0
    return max(int(current or 0), allocated)


def peer_cursor(conn: sqlite3.Connection, peer_device_id: str) -> int:
    """Return the highest accepted cursor advertised by one peer."""
    _validate_device_id(peer_device_id)
    _sync_tables(conn)
    row = conn.execute(
        "SELECT remote_cursor FROM sync_peer_cursors WHERE peer_device_id=?",
        (peer_device_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def peer_ack_cursor(conn: sqlite3.Connection, peer_device_id: str) -> int:
    """Return the local cursor which this peer explicitly acknowledged."""
    _validate_device_id(peer_device_id)
    _sync_tables(conn)
    row = conn.execute(
        "SELECT acknowledged_local_cursor FROM sync_peer_cursors "
        "WHERE peer_device_id=?",
        (peer_device_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def list_conflicts(
        conn: sqlite3.Connection, *, status: str = "open"
) -> list[dict]:
    if status not in ("open", "resolved"):
        raise SyncError("invalid conflict status")
    _sync_tables(conn)
    return [
        _row_dict(row) for row in conn.execute(
            "SELECT * FROM sync_conflicts WHERE status=? ORDER BY id",
            (status,),
        ).fetchall()
    ]


def resolve_conflict(
        conn: sqlite3.Connection,
        conflict_id: int,
        resolution: str,
) -> None:
    """Close a conflict after the application performs explicit UI review.

    ``resolution`` is audit text (for example ``keep_local`` or
    ``manual_merge``).  If the user chooses incoming/merged content, the
    application should write that content to the real row first and call
    ``record_local_change``; this produces a new causal version instead of
    silently replacing the clinical record here.
    """
    if type(conflict_id) is not int or conflict_id < 1:
        raise SyncError("invalid conflict id")
    if not isinstance(resolution, str) or not resolution.strip():
        raise SyncError("resolution is required")
    cursor = conn.execute(
        "UPDATE sync_conflicts SET status='resolved',resolved_at=?,"
        "resolution=? WHERE id=? AND status='open'",
        (_utcnow(), resolution.strip()[:120], conflict_id),
    )
    if cursor.rowcount != 1:
        raise SyncError("open conflict not found")


__all__ = [
    "BATCH_KIND", "BATCH_VERSION", "RECORD_TYPES", "SyncError",
    "initialize_sync", "refresh_local_changes",
    "record_local_change", "record_local_delete",
    "scrub_deleted_record_history", "scrub_all_deleted_history",
    "reset_sync_state",
    "export_change_batch", "validate_change_batch", "apply_change_batch",
    "local_cursor_high_water", "peer_cursor", "peer_ack_cursor",
    "list_conflicts", "resolve_conflict",
]
