import copy
import json
from pathlib import Path

from support import DatabaseTestCase, app

import sync_engine as sync


DEVICE_A = "device-a-0001"
DEVICE_B = "device-b-0001"
DEVICE_C = "device-c-0001"


class SyncEngineTests(DatabaseTestCase):

    def test_schema_mode_syncs_without_copying_local_disclosure_cursor(self):
        conv_id = self.conversation(
            therapist="young", title="Şema modu eşitlemesi")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO session_meta("
                "conv,schema_mode_enabled,schema_mode_initialized,"
                "schema_mode_enrolled_after_message_id,schema_mode_provider,"
                "schema_mode_model,updated) VALUES(?,1,1,77,'openai',"
                "'gpt-example',?)",
                (conv_id, "2026-08-17 10:00"),
            )
            sync.initialize_sync(connection, DEVICE_A)
            first = sync.export_change_batch(connection, DEVICE_A)
        wire_meta = next(
            row for row in first["records"]
            if row["record_type"] == "session_meta")
        self.assertEqual(wire_meta["payload"]["schema_mode_enabled"], 1)
        self.assertNotIn("schema_mode_initialized", wire_meta["payload"])
        self.assertNotIn(
            "schema_mode_enrolled_after_message_id", wire_meta["payload"])
        self.assertNotIn("schema_mode_provider", wire_meta["payload"])
        self.assertNotIn("schema_mode_model", wire_meta["payload"])

        target = self._target_path()

        def apply_initial(connection):
            sync.apply_change_batch(connection, first, DEVICE_B)
            return connection.execute(
                "SELECT schema_mode_enabled,schema_mode_initialized,"
                "schema_mode_enrolled_after_message_id,"
                "schema_mode_provider,schema_mode_model FROM session_meta"
            ).fetchone()

        initial = self._with_database(target, apply_initial)
        self.assertEqual(tuple(initial), (1, 0, 0, "", ""))

        # A same-state metadata edit must preserve the receiving device's own
        # enrollment watermark.
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET focus=?,updated=? WHERE conv=?",
                ("Bugünkü odak", "2026-08-17 10:01", conv_id),
            )
            sync.record_local_change(
                connection, "session_meta", conv_id, DEVICE_A)
            same_state = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=first["cursor"])

        def apply_same_state(connection):
            connection.execute(
                "UPDATE session_meta SET schema_mode_initialized=1,"
                "schema_mode_enrolled_after_message_id=55,"
                "schema_mode_provider='lmstudio',schema_mode_model='local'")
            sync.apply_change_batch(connection, same_state, DEVICE_B)
            return connection.execute(
                "SELECT schema_mode_enabled,schema_mode_initialized,"
                "schema_mode_enrolled_after_message_id,"
                "schema_mode_provider,schema_mode_model FROM session_meta"
            ).fetchone()

        preserved = self._with_database(target, apply_same_state)
        self.assertEqual(tuple(preserved), (1, 1, 55, "lmstudio", "local"))

        # A remotely re-enabled mode must require a fresh local baseline;
        # otherwise messages written while it was off would be disclosed as
        # surprise historical analysis.
        source_cursor = same_state["cursor"]
        for enabled, expected in (
                (0, (0, 1, 55, "lmstudio", "local")),
                (1, (1, 0, 0, "", ""))):
            with app.db() as connection:
                connection.execute(
                    "UPDATE session_meta SET schema_mode_enabled=?,updated=? "
                    "WHERE conv=?",
                    (enabled, "2026-08-17 10:0{}".format(2 + enabled),
                     conv_id),
                )
                sync.record_local_change(
                    connection, "session_meta", conv_id, DEVICE_A)
                batch = sync.export_change_batch(
                    connection, DEVICE_A, after_cursor=source_cursor)
                source_cursor = batch["cursor"]

            def apply_toggle(connection, incoming=batch):
                sync.apply_change_batch(connection, incoming, DEVICE_B)
                return connection.execute(
                    "SELECT schema_mode_enabled,schema_mode_initialized,"
                    "schema_mode_enrolled_after_message_id,"
                    "schema_mode_provider,schema_mode_model FROM session_meta"
                ).fetchone()

            state = self._with_database(target, apply_toggle)
            self.assertEqual(tuple(state), expected)

    def test_timestamp_order_normalizes_offsets_before_lww_comparison(self):
        self.assertEqual(
            sync._timestamp_order_key("2026-08-17T15:00:00+03:00"),
            sync._timestamp_order_key("2026-08-17T12:00:00Z"),
        )
        self.assertGreater(
            sync._timestamp_order_key("2026-08-17 12:00:00.001"),
            sync._timestamp_order_key("2026-08-17T12:00:00+00:00"),
        )

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

    def test_refresh_quarantines_orphan_message_without_deleting_content(self):
        conv_id = self.conversation(title="Silinmiş görüşme")
        sentinel = "ORPHAN-MESSAGE-LOCAL-ONLY-7c91"
        public_id = "message:orphan-local-only-7c91"
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(public_id,conv,role,content,created) "
                "VALUES(?,?,?,?,?)",
                (
                    public_id, conv_id, "assistant", sentinel,
                    "2026-08-17 13:17",
                ),
            ).lastrowid
            # Reproduce a legacy asynchronous completion which outlived its
            # conversation. The authoritative row is retained locally, but
            # it has no valid parent graph to cross the sync wire.
            connection.execute(
                "DELETE FROM conversations WHERE id=?", (conv_id,))

            first = sync.refresh_local_changes(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            second = sync.refresh_local_changes(connection, DEVICE_A)
            physical = connection.execute(
                "SELECT content FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            exclusion = connection.execute(
                "SELECT reason FROM sync_excluded_records "
                "WHERE record_type='message' AND public_id=?",
                (public_id,),
            ).fetchone()
            shadow_count = connection.execute(
                "SELECT COUNT(*) FROM sync_records "
                "WHERE record_type='message' AND public_id=?",
                (public_id,),
            ).fetchone()[0]

        self.assertEqual(first["orphan_excluded"], 1)
        self.assertEqual(second["orphan_excluded"], 1)
        self.assertEqual(physical["content"], sentinel)
        self.assertEqual(exclusion["reason"], "orphan_parent")
        self.assertEqual(shadow_count, 0)
        self.assertFalse(any(
            record["record_type"] == "message"
            and record["public_id"] == public_id
            for record in batch["records"]
        ))
        self.assertNotIn(sentinel, json.dumps(batch, ensure_ascii=False))

    def test_refresh_excludes_transitive_orphan_adhd_graph(self):
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            habit_id = connection.execute(
                "INSERT INTO adhd_habits("
                "source_conv,title,target_per_week,preferred_days_json,"
                "status,review_after,is_guest,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    999999, "Yerel ritim", 2, "[]", "active",
                    1780000000.0, 0, "2026-08-17 09:00",
                    "2026-08-17 09:00",
                ),
            ).lastrowid
            event_id = connection.execute(
                "INSERT INTO adhd_habit_events("
                "habit,scheduled_for,status,created,updated) "
                "VALUES(?,?,'done',?,?)",
                (
                    habit_id, 1780000100.0, "2026-08-17 09:00",
                    "2026-08-17 09:10",
                ),
            ).lastrowid

            first = sync.refresh_local_changes(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            second = sync.refresh_local_changes(connection, DEVICE_A)
            physical = connection.execute(
                "SELECT (SELECT COUNT(*) FROM adhd_habits WHERE id=?),"
                "(SELECT COUNT(*) FROM adhd_habit_events WHERE id=?)",
                (habit_id, event_id),
            ).fetchone()

        self.assertEqual(first["orphan_excluded"], 2)
        self.assertEqual(second["orphan_excluded"], 2)
        self.assertEqual(list(physical), [1, 1])
        self.assertFalse(any(
            record["record_type"] in {"adhd_habit", "adhd_habit_event"}
            for record in batch["records"]
        ))

    def test_refresh_sends_tombstone_for_previously_synced_orphan(self):
        conv_id = self.conversation(title="Önceden eşitlenmiş görüşme")
        sentinel = "ORPHAN-TOMBSTONE-CONTENT-b832"
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "assistant", sentinel, "2026-08-17 13:17"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            initial_cursor = initial["cursor"]

        target = self._target_path()
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, initial, DEVICE_B),
        )

        with app.db() as connection:
            connection.execute(
                "DELETE FROM conversations WHERE id=?", (conv_id,))
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            deletion = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=initial_cursor)
            local_content = connection.execute(
                "SELECT content FROM messages WHERE id=?", (message_id,)
            ).fetchone()[0]
            deletion_cursor = deletion["cursor"]
            repeated_refresh = sync.refresh_local_changes(
                connection, DEVICE_A)
            repeated = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=deletion_cursor)

        def apply_deletion(connection):
            sync.apply_change_batch(connection, deletion, DEVICE_B)
            return (
                connection.execute(
                    "SELECT COUNT(*) FROM conversations").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM messages").fetchone()[0],
            )

        remote_counts = self._with_database(target, apply_deletion)
        tombstones = {
            record["record_type"] for record in deletion["records"]
            if record["deleted_at"] is not None
        }
        encoded = json.dumps(deletion, ensure_ascii=False)

        self.assertEqual(refreshed["orphan_excluded"], 1)
        self.assertEqual(refreshed["deleted"], 2)
        self.assertEqual(repeated_refresh["orphan_excluded"], 1)
        self.assertEqual(local_content, sentinel)
        self.assertEqual(tombstones, {"conversation", "message"})
        self.assertNotIn(sentinel, encoded)
        self.assertEqual(remote_counts, (0, 0))
        self.assertEqual(repeated["records"], [])

    def test_incoming_child_of_orphan_exclusion_is_ignored_content_free(self):
        parent_public_id = "adhd-habit:orphan-parent-001"
        child_public_id = "adhd-event:orphan-child-001"
        remote_device = "orphan-remote-device"
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A, bootstrap=False)
            connection.execute(
                "INSERT INTO sync_excluded_records("
                "record_type,public_id,reason,excluded_at) "
                "VALUES('adhd_habit',?,'orphan_parent',?)",
                (parent_public_id, "2026-08-17T13:17:00+00:00"),
            )
            batch = {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": remote_device,
                "after_cursor": 0,
                "cursor": 1,
                "ack_cursor": 0,
                "has_more": False,
                "records": [{
                    "record_type": "adhd_habit_event",
                    "public_id": child_public_id,
                    "revision": 1,
                    "origin_device_id": remote_device,
                    "parent_origin_device_id": None,
                    "parent_revision": None,
                    "updated_at": "2026-08-17T13:18:00+00:00",
                    "deleted_at": None,
                    "payload": {
                        "habit_public_id": parent_public_id,
                        "scheduled_for": 1780000100.0,
                        "status": "done",
                    },
                }],
            }

            result = sync.apply_change_batch(
                connection, batch, DEVICE_A)
            child_exclusion = connection.execute(
                "SELECT reason FROM sync_excluded_records "
                "WHERE record_type='adhd_habit_event' AND public_id=?",
                (child_public_id,),
            ).fetchone()
            retained = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {} WHERE record_type=? "
                    "AND public_id=?".format(table),
                    ("adhd_habit_event", child_public_id),
                ).fetchone()[0]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts",
                )
            }
            physical = connection.execute(
                "SELECT COUNT(*) FROM adhd_habit_events").fetchone()[0]
            peer_cursor = sync.peer_cursor(connection, remote_device)

        self.assertEqual(result["ignored"], 1)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(child_exclusion["reason"], "orphan_parent")
        self.assertEqual(retained, {
            "sync_records": 0,
            "sync_changes": 0,
            "sync_seen_versions": 0,
            "sync_conflicts": 0,
        })
        self.assertEqual(physical, 0)
        self.assertEqual(peer_cursor, 1)

    def test_orphan_tombstone_blocks_concurrent_live_replay_without_payload(self):
        conv_id = self.conversation(title="Silme üstün gelir")
        local_sentinel = "ORPHAN-LOCAL-CONTENT-46dd"
        replay_sentinel = "ORPHAN-REMOTE-REPLAY-9b61"
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "assistant", local_sentinel,
                 "2026-08-17 13:17"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            original = next(
                row for row in initial["records"]
                if row["record_type"] == "message")
            connection.execute(
                "DELETE FROM conversations WHERE id=?", (conv_id,))
            sync.refresh_local_changes(connection, DEVICE_A)

            replay = copy.deepcopy(original)
            replay.update({
                "origin_device_id": DEVICE_B,
                "revision": 1,
                "parent_origin_device_id": None,
                "parent_revision": None,
                "updated_at": "2026-08-17T13:18:00+00:00",
            })
            replay["payload"]["content"] = replay_sentinel
            batch = {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_B,
                "after_cursor": 0,
                "cursor": 1,
                "ack_cursor": 0,
                "has_more": False,
                "records": [replay],
            }
            merged = sync.apply_change_batch(
                connection, batch, DEVICE_A)
            physical = connection.execute(
                "SELECT content FROM messages WHERE id=?", (message_id,)
            ).fetchone()[0]
            tombstone = connection.execute(
                "SELECT deleted_at FROM sync_records WHERE "
                "record_type='message' AND public_id=?",
                (original["public_id"],),
            ).fetchone()
            metadata = {
                table: [list(row) for row in connection.execute(
                    "SELECT * FROM {}".format(table)).fetchall()]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts", "sync_excluded_records")
            }

        self.assertEqual(merged["ignored"], 1)
        self.assertEqual(merged["applied"], 0)
        self.assertEqual(merged["conflicts"], 0)
        self.assertEqual(physical, local_sentinel)
        self.assertIsNotNone(tombstone["deleted_at"])
        self.assertNotIn(replay_sentinel, json.dumps(
            metadata, ensure_ascii=False))

    def test_deleted_conversation_rejects_crafted_direct_child_revival(self):
        conv_id = self.conversation(title="Kalıcı silinecek")
        sentinel = "DELETED-CONVERSATION-MUST-NOT-REVIVE-12ce"
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            original = next(
                row for row in initial["records"]
                if row["record_type"] == "conversation")
            deleted = sync.record_local_delete(
                connection, "conversation", conv_id, DEVICE_A,
                physical=True)
            tombstone = next(
                row for row in deleted
                if row["record_type"] == "conversation")

            revival = copy.deepcopy(original)
            revival.update({
                "revision": tombstone["revision"] + 1,
                "origin_device_id": DEVICE_B,
                "parent_origin_device_id": tombstone["origin_device_id"],
                "parent_revision": tombstone["revision"],
                "updated_at": "2026-08-17T13:19:00+00:00",
            })
            revival["payload"]["title"] = sentinel
            batch = {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_B,
                "after_cursor": 0,
                "cursor": 1,
                "ack_cursor": 0,
                "has_more": False,
                "records": [revival],
            }
            result = sync.apply_change_batch(
                connection, batch, DEVICE_A)
            physical = connection.execute(
                "SELECT COUNT(*) FROM conversations WHERE public_id=?",
                (original["public_id"],),
            ).fetchone()[0]
            stored = {
                table: [list(row) for row in connection.execute(
                    "SELECT * FROM {}".format(table)).fetchall()]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts")
            }

        self.assertEqual(result["ignored"], 1)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(physical, 0)
        self.assertNotIn(sentinel, json.dumps(stored, ensure_ascii=False))

    def test_optional_reply_to_orphan_is_removed_from_wire_projection(self):
        conv_id = self.conversation(title="Sağlıklı görüşme")
        orphan_public_id = "message:optional-orphan-parent-91a7"
        child_sentinel = "VALID-CHILD-AFTER-ORPHAN-f28c"
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            orphan_id = connection.execute(
                "INSERT INTO messages(public_id,conv,role,content,created) "
                "VALUES(?,?,?,?,?)",
                (orphan_public_id, 999999, "assistant", "yerel yetim",
                 "2026-08-17 13:17"),
            ).lastrowid
            connection.execute(
                "INSERT INTO messages(conv,role,content,created,reply_to) "
                "VALUES(?,?,?,?,?)",
                (conv_id, "user", child_sentinel,
                 "2026-08-17 13:18", orphan_id),
            )
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)

        child = next(
            row for row in batch["records"]
            if row["record_type"] == "message"
            and row["payload"]["content"] == child_sentinel)
        self.assertGreaterEqual(refreshed["orphan_excluded"], 1)
        self.assertIsNone(child["payload"]["reply_to_public_id"])

        def apply_and_read(connection):
            merged = sync.apply_change_batch(connection, batch, DEVICE_B)
            conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]
            content = connection.execute(
                "SELECT content FROM messages WHERE content=?",
                (child_sentinel,),
            ).fetchone()
            return merged, conflicts, content

        merged, conflicts, content = self._with_database(
            self._target_path(), apply_and_read)
        self.assertEqual(merged["conflicts"], 0)
        self.assertEqual(conflicts, 0)
        self.assertIsNotNone(content)

    def test_malformed_required_local_reference_is_quarantined_not_raised(self):
        valid_id = self.conversation(title="Geçerli satır")
        sentinel = "MALFORMED-REFERENCE-LOCAL-ONLY-2af6"
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            bad_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                ("not-an-integer", "assistant", sentinel,
                 "2026-08-17 13:17"),
            ).lastrowid
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            physical = connection.execute(
                "SELECT content FROM messages WHERE id=?", (bad_id,)
            ).fetchone()[0]

        self.assertEqual(refreshed["orphan_excluded"], 1)
        self.assertEqual(physical, sentinel)
        self.assertNotIn(sentinel, json.dumps(batch, ensure_ascii=False))
        self.assertTrue(any(
            row["record_type"] == "conversation"
            and row["payload"]["title"] == "Geçerli satır"
            for row in batch["records"]))

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
            self.assertEqual(merged["conflicts"], 0)

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

    def test_concurrent_clinical_edit_automatically_keeps_latest(self):
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
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(note, "B cihazı düzenlemesi")
        self.assertEqual(conflicts, [])

    def test_concurrent_branch_uses_logical_edit_time_before_revision_depth(
            self):
        conv_id = self.conversation()
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (
                    conv_id, "terapi", "freud", "Ortak sürüm",
                    "2026-07-30 09:00", "2026-07-30 09:00",
                ),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            initial_cursor = initial["cursor"]

        target = self._target_path()

        def import_and_edit_twice(connection):
            sync.apply_change_batch(connection, initial, DEVICE_B)
            target_note = connection.execute(
                "SELECT id FROM notes").fetchone()[0]
            for minute, content in ((10, "Eski B-1"), (20, "Eski B-2")):
                stamp = "2026-07-30 10:{:02d}".format(minute)
                connection.execute(
                    "UPDATE notes SET content=?,updated=? WHERE id=?",
                    (content, stamp, target_note),
                )
                sync.record_local_change(
                    connection, "note", target_note, DEVICE_B,
                    updated_at=stamp)

        self._with_database(target, import_and_edit_twice)
        with app.db() as connection:
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                ("Gerçek en son A", "2026-07-30 11:00", note_id),
            )
            sync.record_local_change(
                connection, "note", note_id, DEVICE_A,
                updated_at="2026-07-30 11:00")
            newer = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=initial_cursor)

        def merge(connection):
            result = sync.apply_change_batch(connection, newer, DEVICE_B)
            row = connection.execute(
                "SELECT content,updated FROM notes").fetchone()
            return result, tuple(row), sync.list_conflicts(connection)

        result, note, conflicts = self._with_database(target, merge)
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(note, ("Gerçek en son A", "2026-07-30 11:00"))
        self.assertEqual(conflicts, [])

    def test_projection_summary_proves_live_data_not_device_local_history(
            self):
        conv_id = self.conversation(title="Ortak canlı görünüm")
        self.messages(conv_id, 2, prefix="ortak")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            source = sync.projection_summary(connection)

        target = self._target_path()

        def apply_and_add_local_tombstone(connection):
            sync.apply_change_batch(connection, batch, DEVICE_B)
            local_only = connection.execute(
                "INSERT INTO conversations("
                "mode,therapist,title,created,updated,ended) "
                "VALUES('terapi','freud','Geçici','2026-07-30 12:00',"
                "'2026-07-30 12:00',1)"
            ).lastrowid
            sync.record_local_change(
                connection, "conversation", int(local_only), DEVICE_B)
            sync.record_local_delete(
                connection, "conversation", int(local_only), DEVICE_B,
                physical=True)
            connection.execute(
                "INSERT OR REPLACE INTO settings(key,value) "
                "VALUES('theme','dark')")
            return sync.projection_summary(connection)

        target_summary = self._with_database(
            target, apply_and_add_local_tombstone)
        self.assertEqual(source, target_summary)
        self.assertEqual(source["pending"], 0)
        self.assertEqual(source["live_count"], 3)
        self.assertEqual(len(source["digest"]), 64)

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

    def test_direct_message_revision_automatically_keeps_latest(self):
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
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(content, "Değiştirilmeye çalışıldı")

    def test_direct_child_wins_when_the_child_device_clock_is_behind(self):
        conv_id = self.conversation()
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (conv_id, "terapi", "freud", "Temel", "2035-01-01 10:00",
                 "2035-01-01 10:00"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)

        target = self._target_path()

        def import_then_edit(connection):
            sync.apply_change_batch(connection, initial, DEVICE_B)
            base_cursor = sync.local_cursor_high_water(connection)
            remote_note = connection.execute("SELECT id FROM notes").fetchone()[0]
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                ("Saat gerideyken gerçek ardıl", "2001-01-01 09:00",
                 remote_note),
            )
            child = sync.record_local_change(
                connection, "note", int(remote_note), DEVICE_B,
                updated_at="2001-01-01T09:00:00+00:00")
            batch = sync.export_change_batch(
                connection, DEVICE_B, after_cursor=base_cursor)
            return child, batch

        child, child_batch = self._with_database(target, import_then_edit)
        self.assertEqual(child["parent_origin_device_id"], DEVICE_A)

        with app.db() as connection:
            result = sync.apply_change_batch(
                connection, child_batch, DEVICE_A)
            content = connection.execute(
                "SELECT content FROM notes WHERE id=?", (note_id,)
            ).fetchone()[0]
            head = connection.execute(
                "SELECT origin_device_id,revision FROM sync_records "
                "WHERE record_type='note' AND local_id=?", (note_id,)
            ).fetchone()
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(content, "Saat gerideyken gerçek ardıl")
        self.assertEqual(tuple(head), (DEVICE_B, child["revision"]))

    def test_causal_lamport_order_converges_independent_of_arrival_order(self):
        self.conversation(title="Temel")
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            exported = sync.export_change_batch(connection, DEVICE_A)
        base = copy.deepcopy(next(
            row for row in exported["records"]
            if row["record_type"] == "conversation"))
        base["updated_at"] = "2099-01-01T00:00:00+00:00"

        child = copy.deepcopy(base)
        child.update({
            "origin_device_id": DEVICE_B,
            "revision": 2,
            "parent_origin_device_id": DEVICE_A,
            "parent_revision": 1,
            "updated_at": "2000-01-01T00:00:00+00:00",
        })
        child["payload"]["title"] = "Nedensel çocuk"

        concurrent = copy.deepcopy(base)
        concurrent.update({
            "origin_device_id": DEVICE_C,
            "revision": 1,
            "parent_origin_device_id": None,
            "parent_revision": None,
            "updated_at": "2050-01-01T00:00:00+00:00",
        })
        concurrent["payload"]["title"] = "Bağımsız dal"

        def batch(records):
            return {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_A,
                "after_cursor": 0,
                "cursor": len(records),
                "ack_cursor": 0,
                "has_more": False,
                "records": records,
            }

        states = []
        for name, records in (
                ("causal-first", [base, child, concurrent]),
                ("concurrent-first", [base, concurrent, child])):
            path = str(Path(self._tmp.name) / "{}.db".format(name))

            def apply_and_read(connection):
                merged = sync.apply_change_batch(
                    connection, batch(records), DEVICE_C)
                title = connection.execute(
                    "SELECT title FROM conversations").fetchone()[0]
                head = tuple(connection.execute(
                    "SELECT revision,origin_device_id,updated_at,payload_hash "
                    "FROM sync_records WHERE record_type='conversation'"
                ).fetchone())
                return merged, title, head

            states.append(self._with_database(path, apply_and_read))

        self.assertEqual(states[0][1:], states[1][1:])
        self.assertEqual(states[0][1], "Nedensel çocuk")
        self.assertEqual(states[0][0]["conflicts"], 0)
        self.assertEqual(states[1][0]["conflicts"], 0)

    def test_equal_time_concurrent_edits_use_device_tie_break_and_converge(self):
        conv_id = self.conversation()
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (conv_id, "terapi", "freud", "Temel", "2026-01-01 10:00",
                 "2026-01-01 10:00"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            source_base = initial["cursor"]

        target = self._target_path()

        def seed_target(connection):
            sync.apply_change_batch(connection, initial, DEVICE_B)
            return sync.local_cursor_high_water(connection)

        target_base = self._with_database(target, seed_target)
        stamp = "2026-08-17T12:00:00+00:00"
        with app.db() as connection:
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                ("A dalı", stamp, note_id),
            )
            sync.record_local_change(
                connection, "note", note_id, DEVICE_A, updated_at=stamp)
            batch_a = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=source_base)

        def edit_target(connection):
            remote_id = int(connection.execute("SELECT id FROM notes").fetchone()[0])
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                ("B dalı", stamp, remote_id),
            )
            sync.record_local_change(
                connection, "note", remote_id, DEVICE_B, updated_at=stamp)
            return sync.export_change_batch(
                connection, DEVICE_B, after_cursor=target_base)

        batch_b = self._with_database(target, edit_target)
        with app.db() as connection:
            merged_a = sync.apply_change_batch(connection, batch_b, DEVICE_A)
        merged_b = self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, batch_a, DEVICE_B),
        )

        def snapshot(path):
            def read(connection):
                content = connection.execute(
                    "SELECT content FROM notes").fetchone()[0]
                head = tuple(connection.execute(
                    "SELECT public_id,revision,origin_device_id,"
                    "parent_origin_device_id,parent_revision,updated_at,"
                    "deleted_at,payload_hash FROM sync_records "
                    "WHERE record_type='note'").fetchone())
                conflicts = connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts "
                    "WHERE status='open'").fetchone()[0]
                return content, head, conflicts
            return self._with_database(path, read)

        source_state = snapshot(app.DB_PATH)
        target_state = snapshot(target)
        self.assertEqual(merged_a["conflicts"], 0)
        self.assertEqual(merged_b["conflicts"], 0)
        self.assertEqual(source_state, target_state)
        self.assertEqual(source_state[0], "B dalı")
        self.assertEqual(source_state[2], 0)

    def test_auto_merge_full_drain_converges_and_next_sync_is_empty(self):
        conv_id = self.conversation(title="Temel")
        source_path = app.DB_PATH
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)

        target = self._target_path()
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, initial, DEVICE_B),
        )
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET title=?,updated=? WHERE id=?",
                ("A dalı", "2026-08-17 12:00", conv_id),
            )
            sync.record_local_change(
                connection, "conversation", conv_id, DEVICE_A,
                updated_at="2026-08-17T12:00:00+00:00")

        def edit_target(connection):
            remote_id = int(connection.execute(
                "SELECT id FROM conversations").fetchone()[0])
            connection.execute(
                "UPDATE conversations SET title=?,updated=? WHERE id=?",
                ("B dalı", "2026-08-17 12:01", remote_id),
            )
            sync.record_local_change(
                connection, "conversation", remote_id, DEVICE_B,
                updated_at="2026-08-17T12:01:00+00:00")

        self._with_database(target, edit_target)

        def outbound(path, device, peer):
            def export(connection):
                return sync.export_change_batch(
                    connection, device,
                    after_cursor=sync.peer_ack_cursor(connection, peer),
                    ack_cursor=sync.peer_cursor(connection, peer),
                )
            return self._with_database(path, export)

        def accept(path, device, batch):
            return self._with_database(
                path,
                lambda connection: sync.apply_change_batch(
                    connection, batch, device),
            )

        drained = False
        for _ in range(8):
            batch_a = outbound(source_path, DEVICE_A, DEVICE_B)
            accept(target, DEVICE_B, batch_a)
            batch_b = outbound(target, DEVICE_B, DEVICE_A)
            accept(source_path, DEVICE_A, batch_b)
            if not batch_a["records"] and not batch_b["records"]:
                drained = True
                break
        self.assertTrue(drained)

        # A fresh QR session uses the durable acknowledgement cursors and has
        # no unchanged logical records to resend in either direction.
        second_a = outbound(source_path, DEVICE_A, DEVICE_B)
        accept(target, DEVICE_B, second_a)
        second_b = outbound(target, DEVICE_B, DEVICE_A)
        accept(source_path, DEVICE_A, second_b)
        self.assertEqual(second_a["records"], [])
        self.assertEqual(second_b["records"], [])

        def logical_state(path):
            def read(connection):
                row = connection.execute(
                    "SELECT title,public_id FROM conversations").fetchone()
                head = connection.execute(
                    "SELECT revision,origin_device_id,updated_at,payload_hash "
                    "FROM sync_records WHERE record_type='conversation'"
                ).fetchone()
                return tuple(row), tuple(head), len(sync.list_conflicts(connection))
            return self._with_database(path, read)

        self.assertEqual(logical_state(source_path), logical_state(target))
        self.assertEqual(logical_state(source_path)[0][0], "B dalı")

    def test_concurrent_tombstone_beats_newer_live_clock_and_never_resurrects(self):
        sentinel = "LIVE-MUST-NOT-RETURN-5d2c"
        conv_id = self.conversation()
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (conv_id, "terapi", "freud", "Temel", "2026-01-01 10:00",
                 "2026-01-01 10:00"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            source_base = initial["cursor"]

        target = self._target_path()

        def seed_and_delete(connection):
            sync.apply_change_batch(connection, initial, DEVICE_B)
            target_base = sync.local_cursor_high_water(connection)
            remote_id = int(connection.execute("SELECT id FROM notes").fetchone()[0])
            sync.record_local_delete(
                connection, "note", remote_id, DEVICE_B,
                deleted_at="2000-01-01T00:00:00+00:00", physical=True)
            return sync.export_change_batch(
                connection, DEVICE_B, after_cursor=target_base)

        tombstone_batch = self._with_database(target, seed_and_delete)
        with app.db() as connection:
            connection.execute(
                "UPDATE notes SET content=?,updated=? WHERE id=?",
                (sentinel, "2099-01-01 00:00", note_id),
            )
            sync.record_local_change(
                connection, "note", note_id, DEVICE_A,
                updated_at="2099-01-01T00:00:00+00:00")
            live_batch = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=source_base)
            sync.apply_change_batch(connection, tombstone_batch, DEVICE_A)

        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, live_batch, DEVICE_B),
        )

        for path in (app.DB_PATH, target):
            def assert_deleted(connection):
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM notes").fetchone()[0], 0)
                retained = json.dumps([
                    list(row) for row in connection.execute(
                        "SELECT payload_json FROM sync_changes UNION ALL "
                        "SELECT local_json FROM sync_conflicts UNION ALL "
                        "SELECT incoming_json FROM sync_conflicts")
                ], ensure_ascii=False)
                self.assertNotIn(sentinel, retained)
            self._with_database(path, assert_deleted)

    def test_child_arriving_before_parent_is_applied_automatically_later(self):
        conv_id = self.conversation(title="Ebeveyn sonra gelecek")
        with app.db() as connection:
            connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "Çocuk mesaj", "2026-08-17 13:00"),
            )
            sync.initialize_sync(connection, DEVICE_A)
            exported = sync.export_change_batch(connection, DEVICE_A)
        parent = next(
            row for row in exported["records"]
            if row["record_type"] == "conversation")
        child = next(
            row for row in exported["records"]
            if row["record_type"] == "message")

        def batch(record, after_cursor, cursor):
            return {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_A,
                "after_cursor": after_cursor,
                "cursor": cursor,
                "ack_cursor": 0,
                "has_more": False,
                "records": [record],
            }

        target = self._target_path()

        def apply_reordered(connection):
            first = sync.apply_change_batch(
                connection, batch(child, 0, 1), DEVICE_B)
            before = (
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts "
                    "WHERE reason='missing_dependency'").fetchone()[0],
            )
            second = sync.apply_change_batch(
                connection, batch(parent, 1, 2), DEVICE_B)
            linked = connection.execute(
                "SELECT m.content,c.title FROM messages m "
                "JOIN conversations c ON c.id=m.conv").fetchone()
            remaining = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts "
                "WHERE status='open'").fetchone()[0]
            return first, before, second, linked, remaining

        first, before, second, linked, remaining = self._with_database(
            target, apply_reordered)
        self.assertEqual(first["deferred"], 1)
        self.assertEqual(first["conflicts"], 0)
        self.assertEqual(before, (0, 1))
        self.assertEqual(second["deferred_applied"], 1)
        self.assertEqual(tuple(linked), ("Çocuk mesaj", "Ebeveyn sonra gelecek"))
        self.assertEqual(remaining, 0)

    def test_v3_conflict_rows_are_auto_merged_and_removed(self):
        conv_id = self.conversation()
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (conv_id, "terapi", "freud", "Eski yerel", "2026-01-01 10:00",
                 "2026-01-01 10:00"),
            ).lastrowid
            sync.initialize_sync(connection, DEVICE_A)
            exported = sync.export_change_batch(connection, DEVICE_A)
            local = next(
                row for row in exported["records"]
                if row["record_type"] == "note")
            incoming = copy.deepcopy(local)
            incoming.update({
                "origin_device_id": DEVICE_B,
                "revision": 1,
                "parent_origin_device_id": None,
                "parent_revision": None,
                "updated_at": "2099-01-01T00:00:00+00:00",
            })
            incoming["payload"]["content"] = "Eski kuyruktaki son sürüm"
            self.assertTrue(sync._queue_conflict(
                connection, local, incoming, "concurrent_clinical_edit"))
            sync._mark_seen(connection, incoming)
            sync._append_change(connection, incoming)
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            content = connection.execute(
                "SELECT content FROM notes WHERE id=?", (note_id,)
            ).fetchone()[0]
            conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]
        self.assertEqual(refreshed["auto_merged"], 1)
        self.assertEqual(content, "Eski kuyruktaki son sürüm")
        self.assertEqual(conflicts, 0)

    def test_mixed_main_and_guest_rows_export_only_main_scope(self):
        main_sentinel = "MAIN-SYNC-SENTINEL-80af"
        guest_sentinel = "GUEST-NEVER-SYNC-SENTINEL-27be"
        main_id = self.conversation(title=main_sentinel)
        guest_id = self.conversation(title=guest_sentinel)
        derived_id = self.conversation(
            title=guest_sentinel + "-DERIVED")
        main_public_id = "main-conversation-000000000001"
        guest_public_id = "guest-conversation-0000000001"
        derived_public_id = "guest-derived-conversation-00001"

        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET public_id=? WHERE id=?",
                (main_public_id, main_id),
            )
            connection.execute(
                "UPDATE conversations SET public_id=?,is_guest=1 "
                "WHERE id=?",
                (guest_public_id, guest_id),
            )
            # Fail closed if an old derived/supervision row forgot to copy the
            # guest bit from its source conversation.
            connection.execute(
                "UPDATE conversations SET public_id=?,source=?,is_guest=0 "
                "WHERE id=?",
                (derived_public_id, guest_id, derived_id),
            )
            local_ids = {}
            for label, conv_id, sentinel in (
                    ("main", main_id, main_sentinel),
                    ("guest", guest_id, guest_sentinel)):
                local_ids[(label, "message")] = connection.execute(
                    "INSERT INTO messages("
                    "public_id,conv,role,content,created) "
                    "VALUES(?,?,?,?,?)",
                    (
                        "{}-message-000000000001".format(label), conv_id,
                        "user", sentinel + "-MESSAGE", "2026-07-30 10:01",
                    ),
                ).lastrowid
                local_ids[(label, "note")] = connection.execute(
                    "INSERT INTO notes("
                    "conv,mode,therapist,content,created,updated) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        conv_id, "terapi", "freud", sentinel + "-NOTE",
                        "2026-07-30 10:02", "2026-07-30 10:02",
                    ),
                ).lastrowid
                local_ids[(label, "checkin")] = connection.execute(
                    "INSERT INTO checkins(conv,note,created) VALUES(?,?,?)",
                    (conv_id, sentinel + "-CHECKIN", "2026-07-30 10:03"),
                ).lastrowid
                local_ids[(label, "memory")] = connection.execute(
                    "INSERT INTO memories("
                    "source_conv,therapist,content,created,updated) "
                    "VALUES(?,?,?,?,?)",
                    (
                        conv_id, "freud", sentinel + "-MEMORY",
                        "2026-07-30 10:04", "2026-07-30 10:04",
                    ),
                ).lastrowid
                connection.execute(
                    "INSERT INTO session_summaries("
                    "conv,draft,status,created,updated) VALUES(?,?,?,?,?)",
                    (
                        conv_id, sentinel + "-SUMMARY", "pending",
                        "2026-07-30 10:05", "2026-07-30 10:05",
                    ),
                )
                connection.execute(
                    "INSERT INTO session_meta(conv,focus,updated) "
                    "VALUES(?,?,?)",
                    (conv_id, sentinel + "-META", "2026-07-30 10:06"),
                )
            derived_message_id = connection.execute(
                "INSERT INTO messages("
                "public_id,conv,role,content,created) VALUES(?,?,?,?,?)",
                (
                    "guest-derived-message-000000001", derived_id,
                    "assistant", guest_sentinel + "-DERIVED-MESSAGE",
                    "2026-07-30 10:07",
                ),
            ).lastrowid

            initialized = sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            guest_shadow_rows = []
            for record_type in (
                    "message", "note", "checkin", "memory"):
                guest_shadow_rows.extend(connection.execute(
                    "SELECT record_type,local_id FROM sync_records "
                    "WHERE record_type=? AND local_id=?",
                    (record_type, local_ids[("guest", record_type)]),
                ).fetchall())
            guest_shadow_rows.extend(connection.execute(
                "SELECT record_type,local_id FROM sync_records "
                "WHERE (record_type='conversation' AND local_id=?) "
                "OR (record_type IN ('session_summary','session_meta') "
                "AND local_id=?)",
                (guest_id, guest_id),
            ).fetchall())
            guest_shadow_rows.extend(connection.execute(
                "SELECT record_type,local_id FROM sync_records "
                "WHERE (record_type='conversation' AND local_id=?) "
                "OR (record_type='message' AND local_id=?)",
                (derived_id, derived_message_id),
            ).fetchall())
            stored = {
                table: [list(row) for row in connection.execute(
                    "SELECT * FROM {}".format(table)).fetchall()]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts")
            }

        wire = json.dumps(batch, ensure_ascii=False)
        stored_json = json.dumps(stored, ensure_ascii=False)
        self.assertIn(main_sentinel, wire)
        self.assertNotIn(guest_sentinel, wire)
        self.assertNotIn(guest_sentinel, stored_json)
        self.assertEqual(guest_shadow_rows, [])
        self.assertGreaterEqual(initialized["bootstrapped"], 7)
        self.assertGreaterEqual(initialized["guest_excluded"], 9)
        self.assertEqual(
            {row["payload"].get("conversation_public_id")
             for row in batch["records"]
             if isinstance(row.get("payload"), dict)
             and "conversation_public_id" in row["payload"]},
            {main_public_id},
        )

    def test_legacy_guest_shadow_change_and_conflict_content_is_scrubbed(self):
        main_sentinel = "LEGACY-MAIN-STAYS-2d91"
        guest_sentinel = "LEGACY-GUEST-SCRUB-71c4"
        main_id = self.conversation(title=main_sentinel)
        guest_id = self.conversation(title=guest_sentinel)

        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (
                    guest_id, "terapi", "freud", guest_sentinel + "-NOTE",
                    "2026-07-30 11:00", "2026-07-30 11:00",
                ),
            ).lastrowid
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (
                    guest_id, "user", guest_sentinel + "-MESSAGE",
                    "2026-07-30 11:01",
                ),
            ).lastrowid
            connection.execute(
                "INSERT INTO checkins(conv,note,created) VALUES(?,?,?)",
                (guest_id, guest_sentinel + "-CHECKIN", "2026-07-30 11:02"),
            )
            connection.execute(
                "INSERT INTO memories("
                "source_conv,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?)",
                (
                    guest_id, "freud", guest_sentinel + "-MEMORY",
                    "2026-07-30 11:03", "2026-07-30 11:03",
                ),
            )
            connection.execute(
                "INSERT INTO session_summaries("
                "conv,draft,status,created,updated) VALUES(?,?,?,?,?)",
                (
                    guest_id, guest_sentinel + "-SUMMARY", "pending",
                    "2026-07-30 11:04", "2026-07-30 11:04",
                ),
            )
            connection.execute(
                "INSERT INTO session_meta(conv,focus,updated) VALUES(?,?,?)",
                (guest_id, guest_sentinel + "-META", "2026-07-30 11:05"),
            )

            # Simulate an older build which enrolled the row before it knew
            # this was guest scope and even retained a concurrent edit.
            sync.initialize_sync(connection, DEVICE_A)
            legacy_batch = sync.export_change_batch(connection, DEVICE_A)
            local_note = next(
                row for row in legacy_batch["records"]
                if row["record_type"] == "note")
            incoming = copy.deepcopy(local_note)
            incoming.update({
                "origin_device_id": DEVICE_B,
                "revision": 1,
                "parent_origin_device_id": None,
                "parent_revision": None,
                "updated_at": "2026-07-30T11:10:00+00:00",
            })
            incoming["payload"]["content"] = guest_sentinel + "-REMOTE"
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
            self.assertEqual(sync.apply_change_batch(
                connection, conflict_batch, DEVICE_A)["conflicts"], 0)
            guest_identities = {
                (row["record_type"], row["public_id"])
                for row in connection.execute(
                    "SELECT record_type,public_id FROM sync_records "
                    "WHERE (record_type='conversation' AND local_id=?) "
                    "OR (record_type='message' AND local_id=?) "
                    "OR (record_type='note' AND local_id=?) "
                    "OR (record_type IN ('checkin','memory',"
                    "'session_summary','session_meta') AND ("
                    "local_id=? OR local_id IN ("
                    "SELECT id FROM checkins WHERE conv=? UNION "
                    "SELECT id FROM memories WHERE source_conv=?)))",
                    (
                        guest_id, message_id, note_id, guest_id,
                        guest_id, guest_id,
                    ),
                ).fetchall()
            }
            self.assertGreaterEqual(len(guest_identities), 7)
            connection.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?",
                (guest_id,),
            )

            # Export itself performs the repair: callers cannot accidentally
            # bypass privacy cleanup by skipping initialize/refresh.
            repaired_batch = sync.export_change_batch(connection, DEVICE_A)
            refresh = sync.refresh_local_changes(connection, DEVICE_A)
            repeated_batch = sync.export_change_batch(connection, DEVICE_A)
            excluded = {
                (row[0], row[1]) for row in connection.execute(
                    "SELECT record_type,public_id "
                    "FROM sync_excluded_records WHERE reason='guest_scope'")
            }
            remaining_guest_metadata = {}
            for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts"):
                count = 0
                for record_type, public_id in guest_identities:
                    count += connection.execute(
                        "SELECT COUNT(*) FROM {} WHERE "
                        "record_type=? AND public_id=?".format(table),
                        (record_type, public_id),
                    ).fetchone()[0]
                remaining_guest_metadata[table] = count
            stored = {
                table: [list(row) for row in connection.execute(
                    "SELECT * FROM {}".format(table)).fetchall()]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts", "sync_excluded_records")
            }

        self.assertIn(main_sentinel, json.dumps(
            repaired_batch, ensure_ascii=False))
        self.assertNotIn(guest_sentinel, json.dumps(
            repaired_batch, ensure_ascii=False))
        self.assertNotIn(guest_sentinel, json.dumps(
            repeated_batch, ensure_ascii=False))
        self.assertNotIn(guest_sentinel, json.dumps(stored, ensure_ascii=False))
        self.assertEqual(set(remaining_guest_metadata.values()), {0})
        self.assertTrue(guest_identities.issubset(excluded))
        self.assertGreaterEqual(refresh["guest_excluded"], 7)

    def test_deleted_guest_exclusions_block_stale_peer_replay(self):
        guest_public_id = "deleted-guest-conversation-0001"
        guest_message_public_id = "deleted-guest-message-00000001"
        guest_id = self.conversation(title="Silinen misafir")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET public_id=?,is_guest=1 "
                "WHERE id=?", (guest_public_id, guest_id))
            connection.execute(
                "INSERT INTO messages("
                "public_id,conv,role,content,created) VALUES(?,?,?,?,?)",
                (
                    guest_message_public_id, guest_id, "user",
                    "YEREL-MISAFIR-ICERIGI", "2026-07-30 12:00",
                ),
            )
            sync.initialize_sync(connection, DEVICE_A)
            with self.assertRaises(sync.SyncError):
                sync.record_local_change(
                    connection, "conversation", guest_id, DEVICE_A)
            removed = sync.record_local_delete(
                connection, "conversation", guest_id, DEVICE_A,
                physical=True)
            self.assertEqual(removed, [])

            stale_note_id = "stale-guest-note-000000000001"
            stale_batch = {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_B,
                "after_cursor": 0,
                "cursor": 2,
                "ack_cursor": 0,
                "has_more": False,
                "records": [
                    {
                        "record_type": "conversation",
                        "public_id": guest_public_id,
                        "revision": 1,
                        "origin_device_id": DEVICE_B,
                        "parent_origin_device_id": None,
                        "parent_revision": None,
                        "updated_at": "2026-07-30T12:10:00+00:00",
                        "deleted_at": None,
                        "payload": {
                            "mode": "terapi", "title": "STALE-GUEST-TITLE",
                            "created": "2026-07-30 12:00",
                            "updated": "2026-07-30 12:10",
                        },
                    },
                    {
                        "record_type": "note",
                        "public_id": stale_note_id,
                        "revision": 1,
                        "origin_device_id": DEVICE_B,
                        "parent_origin_device_id": None,
                        "parent_revision": None,
                        "updated_at": "2026-07-30T12:11:00+00:00",
                        "deleted_at": None,
                        "payload": {
                            "mode": "terapi", "therapist": "freud",
                            "content": "STALE-GUEST-NOTE-CONTENT",
                            "conversation_public_id": guest_public_id,
                            "created": "2026-07-30 12:11",
                            "updated": "2026-07-30 12:11",
                        },
                    },
                ],
            }
            merged = sync.apply_change_batch(
                connection, stale_batch, DEVICE_A)
            conversations = connection.execute(
                "SELECT COUNT(*) FROM conversations").fetchone()[0]
            notes = connection.execute(
                "SELECT COUNT(*) FROM notes").fetchone()[0]
            conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]
            peer_cursor = sync.peer_cursor(connection, DEVICE_B)
            stored = {
                table: [list(row) for row in connection.execute(
                    "SELECT * FROM {}".format(table)).fetchall()]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_conflicts", "sync_excluded_records")
            }
            excluded = {
                (row[0], row[1]) for row in connection.execute(
                    "SELECT record_type,public_id FROM sync_excluded_records")
            }

        encoded = json.dumps(stored, ensure_ascii=False)
        self.assertEqual(merged["ignored"], 2)
        self.assertEqual(merged["applied"], 0)
        self.assertEqual(merged["conflicts"], 0)
        self.assertEqual((conversations, notes, conflicts), (0, 0, 0))
        self.assertEqual(peer_cursor, 2)
        self.assertNotIn("STALE-GUEST", encoded)
        self.assertIn(("conversation", guest_public_id), excluded)
        self.assertIn(("note", stale_note_id), excluded)

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

        non_advancing_child = copy.deepcopy(batch)
        non_advancing_child["records"][message_index][
            "parent_origin_device_id"] = DEVICE_A
        non_advancing_child["records"][message_index]["parent_revision"] = 1
        cases.append(non_advancing_child)

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

    def test_v7_queued_pre_pair_revisions_migrate_and_converge(self):
        conv_id = self.conversation(title="Dönüş kimliği yükseltmesi")
        stamp = "2026-08-22 12:20:00"
        request_id = "queued-pre-pair-request-0001"
        canonical_pair = app._chat_turn_pair_public_id(request_id)
        with app.db() as connection:
            user_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user','Eski kullanıcı',?)",
                (conv_id, stamp),
            ).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'assistant','Eski yardımcı',?)",
                (conv_id, stamp),
            ).lastrowid
            unpaired_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'system','Eşleşmemiş sistem satırı',?)",
                (conv_id, stamp),
            ).lastrowid
            missing_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'system','Silinmiş eski satır',?)",
                (conv_id, stamp),
            ).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat',?,'done',?,?)",
                (conv_id, stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO chat_requests("
                "request_id,job,conv,user_message,assistant_message,status,"
                "created,updated) VALUES(?,?,?,?,?,'completed',?,?)",
                (request_id, job_id, conv_id, user_id, assistant_id,
                 stamp, stamp),
            )
            sync.initialize_sync(connection, DEVICE_A)
            message_public = {
                int(row[0]): str(row[1])
                for row in connection.execute(
                    "SELECT id,public_id FROM messages ORDER BY id")
            }
            legacy_rows = connection.execute(
                "SELECT cursor,event_id,public_id,revision,origin_device_id,"
                "parent_origin_device_id,parent_revision,updated_at,"
                "deleted_at,payload_json FROM sync_changes "
                "WHERE record_type='message' ORDER BY cursor"
            ).fetchall()
            legacy_metadata = {
                str(row[2]): tuple(row[:9]) for row in legacy_rows
            }
            for row in legacy_rows:
                payload = json.loads(row[9])
                payload.pop("turn_pair_public_id")
                connection.execute(
                    "UPDATE sync_changes SET payload_json=? WHERE cursor=?",
                    (sync._canonical_json(payload), int(row[0])),
                )
                connection.execute(
                    "UPDATE sync_records SET payload_hash=? "
                    "WHERE record_type='message' AND public_id=?",
                    (sync._payload_hash(payload), str(row[2])),
                )
            connection.execute(
                "DELETE FROM messages WHERE id=?", (missing_id,))

        # App migration backfills only the exact completed request pair.
        app.init_db()
        with app.db() as connection:
            self.assertEqual({
                str(row[0]) for row in connection.execute(
                    "SELECT turn_pair_public_id FROM messages "
                    "WHERE id IN (?,?)", (user_id, assistant_id))
            }, {canonical_pair})
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            migrated_rows = connection.execute(
                "SELECT cursor,event_id,public_id,revision,origin_device_id,"
                "parent_origin_device_id,parent_revision,updated_at,"
                "deleted_at,payload_json FROM sync_changes "
                "WHERE record_type='message' AND revision=1 "
                "ORDER BY cursor"
            ).fetchall()
            for row in migrated_rows:
                self.assertEqual(tuple(row[:9]), legacy_metadata[str(row[2])])
                payload = json.loads(row[9])
                expected_pair = (
                    canonical_pair if str(row[2]) in {
                        message_public[user_id], message_public[assistant_id]
                    } else ""
                )
                self.assertEqual(
                    payload["turn_pair_public_id"], expected_pair)
            missing_records = [
                row for row in batch["records"]
                if row["record_type"] == "message"
                and row["public_id"] == message_public[missing_id]
            ]

        self.assertGreaterEqual(refreshed["updated"], 3)
        self.assertEqual(len(missing_records), 1)
        self.assertIsNone(missing_records[0]["payload"])
        self.assertIsNotNone(missing_records[0]["deleted_at"])

        def final_state(connection):
            pairs = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT public_id,turn_pair_public_id FROM messages")
            }
            revisions = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT public_id,revision FROM sync_records "
                    "WHERE record_type='message'")
            }
            return pairs, revisions, sync.peer_cursor(connection, DEVICE_A), \
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]

        fresh = self._target_path()

        def apply_fresh_twice(connection):
            first = sync.apply_change_batch(connection, batch, DEVICE_B)
            before_count = connection.execute(
                "SELECT COUNT(*) FROM messages").fetchone()[0]
            second = sync.apply_change_batch(connection, batch, DEVICE_B)
            after_count = connection.execute(
                "SELECT COUNT(*) FROM messages").fetchone()[0]
            return first, second, before_count, after_count, \
                final_state(connection)

        first, second, before_count, after_count, fresh_state = \
            self._with_database(fresh, apply_fresh_twice)
        self.assertGreater(first["applied"], 0)
        self.assertEqual(second["conflicts"], 0)
        self.assertEqual(before_count, after_count)
        self.assertEqual(fresh_state[0][message_public[user_id]],
                         canonical_pair)
        self.assertEqual(fresh_state[0][message_public[assistant_id]],
                         canonical_pair)
        self.assertEqual(fresh_state[0][message_public[unpaired_id]], "")
        self.assertNotIn(message_public[missing_id], fresh_state[0])
        self.assertEqual(fresh_state[3], 0)

        with app.db() as connection:
            limit_one_batches = []
            cursor = 0
            while True:
                one = sync.export_change_batch(
                    connection, DEVICE_A, after_cursor=cursor, limit=1)
                if one["records"]:
                    limit_one_batches.append(one)
                cursor = one["cursor"]
                if not one["has_more"]:
                    break
        self.assertTrue(limit_one_batches)
        self.assertTrue(all(
            len(one["records"]) == 1 for one in limit_one_batches))

        limit_one_target = str(Path(self._tmp.name) / "pair-limit-one.db")

        def apply_limit_one_twice(connection):
            for one in limit_one_batches:
                sync.apply_change_batch(connection, one, DEVICE_B)
            first_state = final_state(connection)
            for one in limit_one_batches:
                replay = sync.apply_change_batch(connection, one, DEVICE_B)
                self.assertEqual(replay["conflicts"], 0)
            return first_state, final_state(connection)

        limit_first, limit_replay = self._with_database(
            limit_one_target, apply_limit_one_twice)
        self.assertEqual(limit_first, fresh_state)
        self.assertEqual(limit_replay, fresh_state)

        # A v6 receiver may already have acknowledged the empty revision-one
        # pair before upgrading.  Only its direct causal child may fill it.
        earliest_message_revision = {}
        legacy_receiver_records = []
        for record in batch["records"]:
            if record["record_type"] != "message":
                legacy_receiver_records.append(copy.deepcopy(record))
                continue
            current = earliest_message_revision.get(record["public_id"])
            if current is None or record["revision"] < current["revision"]:
                earliest_message_revision[record["public_id"]] = \
                    copy.deepcopy(record)
        for record in earliest_message_revision.values():
            if record["deleted_at"] is None:
                record["payload"]["turn_pair_public_id"] = ""
            legacy_receiver_records.append(record)
        legacy_receiver_batch = copy.deepcopy(batch)
        legacy_receiver_batch["records"] = legacy_receiver_records
        legacy_receiver_batch["cursor"] = max(1, batch["after_cursor"] + 1)
        legacy_receiver_batch["has_more"] = True
        preexisting = str(Path(self._tmp.name) / "pre-pair-receiver.db")

        def apply_preexisting(connection):
            sync.apply_change_batch(
                connection, legacy_receiver_batch, DEVICE_B)
            before = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT public_id,turn_pair_public_id FROM messages")
            }
            upgraded = sync.apply_change_batch(connection, batch, DEVICE_B)
            replay = sync.apply_change_batch(connection, batch, DEVICE_B)
            return before, upgraded, replay, final_state(connection)

        before_upgrade, upgraded, replay, preexisting_state = \
            self._with_database(preexisting, apply_preexisting)
        self.assertEqual(before_upgrade[message_public[user_id]], "")
        self.assertEqual(before_upgrade[message_public[assistant_id]], "")
        self.assertGreater(upgraded["applied"], 0)
        self.assertEqual(upgraded["conflicts"], 0)
        self.assertEqual(replay["conflicts"], 0)
        self.assertEqual(preexisting_state, fresh_state)

        paired_head = max(
            (row for row in batch["records"]
             if row["record_type"] == "message"
             and row["public_id"] == message_public[user_id]
             and row["deleted_at"] is None),
            key=lambda row: row["revision"],
        )
        for tampered_pair in ("f" * 32, ""):
            tampered_record = copy.deepcopy(paired_head)
            tampered_record["parent_origin_device_id"] = \
                paired_head["origin_device_id"]
            tampered_record["parent_revision"] = paired_head["revision"]
            tampered_record["revision"] = paired_head["revision"] + 1
            tampered_record["updated_at"] = "2026-08-22T12:21:00+00:00"
            tampered_record["payload"][
                "turn_pair_public_id"] = tampered_pair
            tampered = copy.deepcopy(batch)
            tampered["after_cursor"] = batch["cursor"]
            tampered["cursor"] = batch["cursor"] + 1
            tampered["records"] = [tampered_record]
            with self.subTest(tampered_pair=tampered_pair):
                with self.assertRaisesRegex(
                        sync.SyncError,
                        "immutable message turn-pair identity"):
                    self._with_database(
                        fresh,
                        lambda connection: sync.apply_change_batch(
                            connection, tampered, DEVICE_B),
                    )
                self.assertEqual(
                    self._with_database(fresh, final_state), fresh_state)

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
