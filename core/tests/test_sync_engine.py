import copy
import json
from pathlib import Path

from support import DatabaseTestCase, app

import sync_engine as sync


DEVICE_A = "device-a-0001"
DEVICE_B = "device-b-0001"


class SyncEngineTests(DatabaseTestCase):

    def _target_path(self):
        return str(Path(self._tmp.name) / "target.db")

    def _with_database(self, path, callback):
        original = app.DB_PATH
        app.DB_PATH = path
        try:
            app.init_db()
            with app.db() as connection:
                return callback(connection)
        finally:
            app.DB_PATH = original

    def _source_batch(self, after_cursor=0):
        with app.db() as connection:
            return sync.export_change_batch(
                connection, DEVICE_A, after_cursor=after_cursor)

    def test_roundtrip_preserves_logical_relations(self):
        conv_id = self.conversation(title="Eşitlenen seans")
        with app.db() as connection:
            first = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "İlk mesaj", "2026-07-30 10:01"),
            ).lastrowid
            connection.execute(
                "INSERT INTO messages(conv,role,content,created,reply_to) "
                "VALUES(?,?,?,?,?)",
                (conv_id, "assistant", "Yanıt", "2026-07-30 10:02", first),
            )
            connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (
                    conv_id, "terapi", "freud", "Kullanıcı notu",
                    "2026-07-30 10:03", "2026-07-30 10:03",
                ),
            )
            result = sync.initialize_sync(connection, DEVICE_A)
            self.assertGreaterEqual(result["bootstrapped"], 4)
        batch = self._source_batch()

        def apply_and_read(connection):
            result = sync.apply_change_batch(connection, batch, DEVICE_B)
            rows = connection.execute(
                "SELECT m.content,q.content AS reply_content "
                "FROM messages m LEFT JOIN messages q ON q.id=m.reply_to "
                "ORDER BY m.id"
            ).fetchall()
            note = connection.execute(
                "SELECT n.content,v.title FROM notes n "
                "JOIN conversations v ON v.id=n.conv"
            ).fetchone()
            return result, rows, note

        result, messages, note = self._with_database(
            self._target_path(), apply_and_read)
        self.assertEqual(result["applied"], len(batch["records"]))
        self.assertEqual([row["content"] for row in messages],
                         ["İlk mesaj", "Yanıt"])
        self.assertEqual(messages[1]["reply_content"], "İlk mesaj")
        self.assertEqual(note["content"], "Kullanıcı notu")
        self.assertEqual(note["title"], "Eşitlenen seans")

    def test_repeated_batch_is_idempotent(self):
        self.conversation(title="Tek kopya")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
        batch = self._source_batch()

        def apply_twice(connection):
            first = sync.apply_change_batch(connection, batch, DEVICE_B)
            second = sync.apply_change_batch(connection, batch, DEVICE_B)
            count = connection.execute(
                "SELECT COUNT(*) FROM conversations").fetchone()[0]
            cursor = sync.peer_cursor(connection, DEVICE_A)
            return first, second, count, cursor

        first, second, count, cursor = self._with_database(
            self._target_path(), apply_twice)
        self.assertEqual(first["applied"], 1)
        self.assertEqual(second["ignored"], 1)
        self.assertEqual(count, 1)
        self.assertEqual(cursor, batch["cursor"])

    def test_peer_ack_makes_next_unchanged_export_empty(self):
        self.conversation(title="Bir kez gönderilecek")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            first = sync.export_change_batch(connection, DEVICE_A)

        target = self._target_path()

        def accept_and_ack(connection):
            sync.apply_change_batch(connection, first, DEVICE_B)
            return sync.export_change_batch(
                connection, DEVICE_B,
                ack_cursor=sync.peer_cursor(connection, DEVICE_A),
            )

        acknowledgement = self._with_database(target, accept_and_ack)
        with app.db() as connection:
            sync.apply_change_batch(connection, acknowledgement, DEVICE_A)
            acknowledged = sync.peer_ack_cursor(connection, DEVICE_B)
            second = sync.export_change_batch(
                connection, DEVICE_A,
                after_cursor=acknowledged,
                ack_cursor=sync.peer_cursor(connection, DEVICE_B),
            )

        self.assertEqual(acknowledged, first["cursor"])
        self.assertEqual(second["records"], [])
        self.assertEqual(second["cursor"], first["cursor"])

    def test_peer_cannot_acknowledge_an_unallocated_local_cursor(self):
        self.conversation(title="ACK sınırı")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            high_water = sync.local_cursor_high_water(connection)
            incoming = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=high_water,
                ack_cursor=high_water + 1)
            incoming["sender_device_id"] = DEVICE_B
            with self.assertRaises(sync.SyncError):
                sync.apply_change_batch(connection, incoming, DEVICE_A)

    def test_refresh_discovers_unhooked_insert_and_update_once(self):
        conv_id = self.conversation(title="İlk başlık")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            before = sync.export_change_batch(connection, DEVICE_A)["cursor"]
            connection.execute(
                "UPDATE conversations SET title=?,updated=? WHERE id=?",
                ("Taranan başlık", "2026-07-30 11:00", conv_id),
            )
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "Taranan mesaj", "2026-07-30 11:01"),
            ).lastrowid

            first = sync.refresh_local_changes(connection, DEVICE_A)
            changed = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=before)
            after_first = changed["cursor"]
            second = sync.refresh_local_changes(connection, DEVICE_A)
            repeated = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=after_first)
            message_meta = connection.execute(
                "SELECT revision FROM sync_records "
                "WHERE record_type='message' AND local_id=?",
                (message_id,),
            ).fetchone()

        self.assertEqual(first["added"], 1)
        self.assertEqual(first["updated"], 1)
        self.assertEqual(first["deleted"], 0)
        self.assertEqual(
            [(row["record_type"], row["revision"])
             for row in changed["records"]],
            [("conversation", 2), ("message", 1)],
        )
        self.assertEqual(message_meta["revision"], 1)
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["deleted"], 0)
        self.assertEqual(second["unchanged"], 2)
        self.assertEqual(repeated["records"], [])
        self.assertEqual(repeated["cursor"], after_first)

    def test_refresh_keeps_record_when_optional_source_was_deleted(self):
        source_id = self.conversation(title="Sonradan silinen kaynak")
        derived_id = self.conversation(title="Kaynağı silinmiş süpervizyon")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET source=? WHERE id=?",
                (source_id, derived_id),
            )
            connection.execute(
                "DELETE FROM conversations WHERE id=?", (source_id,))

            result = sync.refresh_local_changes(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            derived_public_id = connection.execute(
                "SELECT public_id FROM conversations WHERE id=?",
                (derived_id,),
            ).fetchone()[0]

        derived = next(
            row for row in batch["records"]
            if row["record_type"] == "conversation"
            and row["public_id"] == derived_public_id
        )
        self.assertEqual(result["added"], 1)
        self.assertIsNone(derived["payload"]["source_public_id"])

    def test_refresh_turns_physical_deletes_into_idempotent_tombstones(self):
        conv_id = self.conversation(title="Doğrudan silinecek")
        self.messages(conv_id, 2)
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            before = sync.export_change_batch(connection, DEVICE_A)["cursor"]
            connection.execute(
                "DELETE FROM messages WHERE conv=?", (conv_id,))
            connection.execute(
                "DELETE FROM conversations WHERE id=?", (conv_id,))

            first = sync.refresh_local_changes(connection, DEVICE_A)
            deleted = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=before)
            after_first = deleted["cursor"]
            second = sync.refresh_local_changes(connection, DEVICE_A)
            repeated = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=after_first)
            tombstones = connection.execute(
                "SELECT record_type,revision,local_id,deleted_at "
                "FROM sync_records WHERE deleted_at IS NOT NULL "
                "ORDER BY record_type,public_id"
            ).fetchall()

        self.assertEqual(first["deleted"], 3)
        self.assertEqual(first["added"], 0)
        self.assertEqual(first["updated"], 0)
        self.assertEqual(len(deleted["records"]), 3)
        self.assertTrue(all(
            row["payload"] is None and row["deleted_at"]
            for row in deleted["records"]))
        self.assertEqual(len(tombstones), 3)
        self.assertTrue(all(row["revision"] == 2 for row in tombstones))
        self.assertTrue(all(row["local_id"] is None for row in tombstones))
        self.assertEqual(second["deleted"], 0)
        self.assertEqual(repeated["records"], [])

    def test_refresh_scrubs_payload_after_unhooked_physical_delete(self):
        sentinel = "REFRESH-DELETE-SENSITIVE-4c92"
        conv_id = self.conversation(title=sentinel + "-TITLE")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", sentinel, "2026-07-30 10:00"),
            )
            sync.initialize_sync(connection, DEVICE_A)
            connection.execute(
                "DELETE FROM messages WHERE conv=?", (conv_id,))
            connection.execute(
                "DELETE FROM conversations WHERE id=?", (conv_id,))

            result = sync.refresh_local_changes(connection, DEVICE_A)
            payloads = connection.execute(
                "SELECT payload_json FROM sync_changes").fetchall()
            conflicts = connection.execute(
                "SELECT local_json,incoming_json FROM sync_conflicts"
            ).fetchall()

        encoded = json.dumps(
            [list(row) for row in payloads + conflicts],
            ensure_ascii=False)
        self.assertEqual(result["deleted"], 2)
        self.assertNotIn(sentinel, encoded)
        self.assertTrue(all(row[0] is None for row in payloads))

    def test_refresh_does_not_echo_unchanged_remote_records(self):
        self.conversation(title="Uzak kayıt")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            source = sync.export_change_batch(connection, DEVICE_A)

        def import_and_refresh(connection):
            sync.apply_change_batch(connection, source, DEVICE_B)
            before = sync.export_change_batch(
                connection, DEVICE_B)["cursor"]
            result = sync.refresh_local_changes(connection, DEVICE_B)
            after = sync.export_change_batch(
                connection, DEVICE_B, after_cursor=before)
            return result, after

        result, after = self._with_database(
            self._target_path(), import_and_refresh)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(after["records"], [])

    def test_deletion_is_a_tombstone_and_removes_children(self):
        conv_id = self.conversation(title="Silinecek")
        self.messages(conv_id, 2)
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            deletion_cursor = initial["cursor"]

        def apply_initial(connection):
            sync.apply_change_batch(connection, initial, DEVICE_B)

        target = self._target_path()
        self._with_database(target, apply_initial)

        with app.db() as connection:
            tombstones = sync.record_local_delete(
                connection, "conversation", conv_id, DEVICE_A,
                physical=True)
            self.assertEqual(len(tombstones), 3)
            deletion = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=deletion_cursor)
            source_rows = connection.execute(
                "SELECT COUNT(*) FROM conversations").fetchone()[0]
            self.assertEqual(source_rows, 0)

        def apply_delete(connection):
            result = sync.apply_change_batch(connection, deletion, DEVICE_B)
            conversations = connection.execute(
                "SELECT COUNT(*) FROM conversations").fetchone()[0]
            messages = connection.execute(
                "SELECT COUNT(*) FROM messages").fetchone()[0]
            tombstone_count = connection.execute(
                "SELECT COUNT(*) FROM sync_records "
                "WHERE deleted_at IS NOT NULL").fetchone()[0]
            return result, conversations, messages, tombstone_count

        result, conversations, messages, tombstone_count = (
            self._with_database(target, apply_delete))
        self.assertEqual(result["applied"], 3)
        self.assertEqual((conversations, messages), (0, 0))
        self.assertEqual(tombstone_count, 3)

    def test_delete_scrubs_sensitive_change_and_conflict_payloads(self):
        sentinel = "AUDIT-SENSITIVE-SENTINEL-91e2"
        conv_id = self.conversation(title="Silinecek özel görüşme")
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", sentinel, "2026-07-30 10:00"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            local_message = next(
                row for row in initial["records"]
                if row["record_type"] == "message")
            incoming = copy.deepcopy(local_message)
            incoming.update({
                "origin_device_id": DEVICE_B,
                "revision": 1,
                "parent_origin_device_id": None,
                "parent_revision": None,
                "updated_at": "2026-07-30T10:05:00+00:00",
            })
            incoming["payload"]["content"] = sentinel + "-REMOTE"
            conflict_batch = {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_B,
                "after_cursor": 0,
                "cursor": 1,
                "ack_cursor": 0,
                "has_more": False,
                "records": [incoming],
            }
            merged = sync.apply_change_batch(
                connection, conflict_batch, DEVICE_A)
            self.assertEqual(merged["conflicts"], 1)

            sync.record_local_delete(
                connection, "conversation", conv_id, DEVICE_A,
                physical=True)

            sync_tables = [
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'sync_%' ORDER BY name")
            ]
            stored = {}
            for table in sync_tables:
                stored[table] = [
                    list(row) for row in connection.execute(
                        "SELECT * FROM {}".format(table)).fetchall()
                ]
            encoded = json.dumps(stored, ensure_ascii=False)
            remaining_changes = connection.execute(
                "SELECT record_type,payload_json,deleted_at "
                "FROM sync_changes ORDER BY record_type"
            ).fetchall()
            conflict_count = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]
            message_count = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE id=?", (message_id,)
            ).fetchone()[0]

        self.assertNotIn(sentinel, encoded)
        self.assertEqual(conflict_count, 0)
        self.assertEqual(message_count, 0)
        self.assertEqual(len(remaining_changes), 2)
        self.assertTrue(all(
            row["payload_json"] is None and row["deleted_at"]
            for row in remaining_changes))

    def test_reset_sync_state_clears_all_sync_metadata(self):
        self.conversation(title="Tam silme")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            before = sync.local_cursor_high_water(connection)
            result = sync.reset_sync_state(connection)
            counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "sync_conflicts", "sync_changes", "sync_seen_versions",
                    "sync_records", "sync_peer_cursors")
            }
            sync.refresh_local_changes(connection, DEVICE_A)
            after = sync.local_cursor_high_water(connection)

        self.assertTrue(all(value == 0 for value in counts.values()))
        self.assertIn("sync_changes", result)
        self.assertGreater(after, before)

    def test_concurrent_clinical_edit_enters_conflict_queue(self):
        conv_id = self.conversation()
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (
                    conv_id, "terapi", "freud", "Ortak sürüm",
                    "2026-07-30 10:00", "2026-07-30 10:00",
                ),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            initial_cursor = initial["cursor"]

        target = self._target_path()

        def import_and_edit(connection):
            sync.apply_change_batch(connection, initial, DEVICE_B)
            target_note = connection.execute(
                "SELECT id FROM notes").fetchone()[0]
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                ("B cihazı düzenlemesi", "2026-07-30 10:20", target_note),
            )
            sync.record_local_change(
                connection, "note", target_note, DEVICE_B,
                updated_at="2026-07-30T10:20:00+00:00")

        self._with_database(target, import_and_edit)
        with app.db() as connection:
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                ("A cihazı düzenlemesi", "2026-07-30 10:15", note_id),
            )
            sync.record_local_change(
                connection, "note", note_id, DEVICE_A,
                updated_at="2026-07-30T10:15:00+00:00")
            concurrent = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=initial_cursor)

        def merge(connection):
            result = sync.apply_change_batch(
                connection, concurrent, DEVICE_B)
            note = connection.execute(
                "SELECT content FROM notes").fetchone()[0]
            conflicts = sync.list_conflicts(connection)
            return result, note, conflicts

        result, note, conflicts = self._with_database(target, merge)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(note, "B cihazı düzenlemesi")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["reason"],
                         "concurrent_clinical_edit")

    def test_out_of_order_older_revision_cannot_overwrite_newer(self):
        conv_id = self.conversation(title="İlk başlık")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            connection.execute(
                "UPDATE conversations SET title=?,updated=? WHERE id=?",
                ("Yeni başlık", "2026-07-30 10:30", conv_id),
            )
            sync.record_local_change(
                connection, "conversation", conv_id, DEVICE_A,
                updated_at="2026-07-30T10:30:00+00:00")
            batch = sync.export_change_batch(connection, DEVICE_A)
        batch["records"] = list(reversed(batch["records"]))

        def merge(connection):
            result = sync.apply_change_batch(connection, batch, DEVICE_B)
            title = connection.execute(
                "SELECT title FROM conversations").fetchone()[0]
            return result, title

        result, title = self._with_database(self._target_path(), merge)
        self.assertEqual(title, "Yeni başlık")
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["ignored"], 1)

    def test_messages_are_immutable_on_identity_collision(self):
        conv_id = self.conversation()
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "Değişmez", "2026-07-30 10:00"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            cursor = initial["cursor"]

        target = self._target_path()
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, initial, DEVICE_B),
        )
        with app.db() as connection:
            connection.execute(
                "UPDATE messages SET content=? WHERE id=?",
                ("Değiştirilmeye çalışıldı", message_id),
            )
            sync.record_local_change(
                connection, "message", message_id, DEVICE_A)
            changed = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=cursor)

        def merge(connection):
            result = sync.apply_change_batch(connection, changed, DEVICE_B)
            content = connection.execute(
                "SELECT content FROM messages").fetchone()[0]
            return result, content

        result, content = self._with_database(target, merge)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(content, "Değişmez")

    def test_secret_and_runtime_tables_can_never_enter_payload(self):
        conv_id = self.conversation(title="Güvenli")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO settings(key,value) VALUES(?,?)",
                ("pin_hash", "pin-secret"),
            )
            connection.execute(
                "INSERT INTO settings(key,value) VALUES(?,?)",
                ("openai_api_key", "sk-secret"),
            )
            connection.execute(
                "INSERT INTO jobs(kind,conv,provider,model) VALUES(?,?,?,?)",
                ("chat_response", conv_id, "openai", "secret-model"),
            )
            sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
        serialized = json.dumps(batch, ensure_ascii=False)
        for forbidden in (
                "settings", "pin-secret", "sk-secret", "jobs",
                "chat_requests", "secret-model"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            {row["record_type"] for row in batch["records"]},
            {"conversation"},
        )

        malicious = copy.deepcopy(batch)
        malicious["records"][0]["payload"]["api_key"] = "must-not-pass"
        with self.assertRaises(sync.SyncError):
            sync.validate_change_batch(malicious)

    def test_critical_payload_types_enums_and_lengths_are_rejected(self):
        conv_id = self.conversation(title="Doğrulama")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "Geçerli", "2026-07-30 10:00"),
            )
            sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)

        message_index = next(
            index for index, row in enumerate(batch["records"])
            if row["record_type"] == "message")
        cases = []

        bad_role = copy.deepcopy(batch)
        bad_role["records"][message_index]["payload"]["role"] = "root"
        cases.append(bad_role)

        missing_parent = copy.deepcopy(batch)
        del missing_parent["records"][message_index]["payload"][
            "conversation_public_id"]
        cases.append(missing_parent)

        oversized = copy.deepcopy(batch)
        oversized["records"][message_index]["payload"]["content"] = (
            "x" * (sync.MAX_TEXT_FIELD_BYTES + 1))
        cases.append(oversized)

        invalid_boolean = copy.deepcopy(batch)
        conversation = next(
            row for row in invalid_boolean["records"]
            if row["record_type"] == "conversation")
        conversation["payload"]["ended"] = 7
        cases.append(invalid_boolean)

        numeric_content = copy.deepcopy(batch)
        numeric_content["records"][message_index]["payload"]["content"] = 42
        cases.append(numeric_content)

        for malicious in cases:
            with self.subTest(payload=malicious["records"][0]["record_type"]):
                with self.assertRaises(sync.SyncError):
                    sync.validate_change_batch(malicious)

    def test_migration_is_additive_on_legacy_minimal_database(self):
        connection = app.sqlite3.connect(":memory:")
        connection.row_factory = app.sqlite3.Row
        try:
            connection.executescript("""
                CREATE TABLE conversations(
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL,
                    title TEXT, created TEXT, updated TEXT);
                CREATE TABLE messages(
                    id INTEGER PRIMARY KEY, conv INTEGER NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, created TEXT);
                INSERT INTO conversations(
                    id,mode,title,created,updated)
                VALUES(1,'terapi','Eski kayıt','2026-07-01','2026-07-01');
                INSERT INTO messages(
                    id,conv,role,content,created)
                VALUES(1,1,'user','Eski mesaj','2026-07-01');
            """)
            result = sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            title = connection.execute(
                "SELECT title FROM conversations WHERE id=1").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(result["bootstrapped"], 2)
        self.assertEqual(len(batch["records"]), 2)
        self.assertEqual(title, "Eski kayıt")

    def test_existing_peer_cursor_table_gains_ack_column_additively(self):
        connection = app.sqlite3.connect(":memory:")
        connection.row_factory = app.sqlite3.Row
        try:
            connection.executescript("""
                CREATE TABLE sync_peer_cursors(
                    peer_device_id TEXT PRIMARY KEY,
                    remote_cursor INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO sync_peer_cursors(
                    peer_device_id,remote_cursor,updated_at)
                VALUES('device-b-0001',17,'2026-07-30');
            """)
            sync.initialize_sync(connection, DEVICE_A, bootstrap=False)
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(sync_peer_cursors)")
            }
            remote = sync.peer_cursor(connection, DEVICE_B)
            acknowledged = sync.peer_ack_cursor(connection, DEVICE_B)
        finally:
            connection.close()

        self.assertIn("acknowledged_local_cursor", columns)
        self.assertEqual(remote, 17)
        self.assertEqual(acknowledged, 0)
