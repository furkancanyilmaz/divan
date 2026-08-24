import copy
import json
from pathlib import Path

from support import DatabaseTestCase, app

import sync_engine
import sync_service


DEVICE_A = "device-a-0001"
DEVICE_B = "device-b-0001"
SERVICE_REMOTE = "b" * 32
CONVERSATION_PUBLIC_ID = "shared-conversation-public-00000001"
STAMP = "2026-08-17T10:00:00+00:00"


class ConversationSingletonSyncTests(DatabaseTestCase):

    singleton_types = ("note", "session_summary", "session_meta")

    def _path(self, name):
        return str(Path(self._tmp.name) / "{}.db".format(name))

    def _open(self, path):
        app.DB_PATH = path
        app.init_db()

    def _seed(self, path, device_id, marker):
        self._open(path)
        with app.db() as connection:
            conversation_id = connection.execute(
                "INSERT INTO conversations("
                "public_id,mode,therapist,title,created,updated,ended,"
                "source_mode) VALUES(?,?,?,?,?,?,0,0)",
                (
                    CONVERSATION_PUBLIC_ID, "terapi", "freud",
                    "Ortak görüşme", STAMP, STAMP,
                ),
            ).lastrowid
            connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (
                    conversation_id, "terapi", "freud",
                    "not-{}".format(marker), STAMP, STAMP,
                ),
            )
            connection.execute(
                "INSERT INTO session_summaries("
                "conv,draft,approved_content,status,created,updated) "
                "VALUES(?,?,?,'approved',?,?)",
                (
                    conversation_id, "taslak-{}".format(marker),
                    "özet-{}".format(marker), STAMP, STAMP,
                ),
            )
            connection.execute(
                "INSERT INTO session_meta(conv,focus,summary,updated) "
                "VALUES(?,?,?,?)",
                (
                    conversation_id, "odak-{}".format(marker),
                    "çerçeve-{}".format(marker), STAMP,
                ),
            )
            sync_engine.initialize_sync(connection, device_id)
            return sync_engine.export_change_batch(
                connection, device_id, limit=64)

    def _rewrite_as_legacy(self, path, suffix):
        self._open(path)
        old_ids = {}
        canonical_ids = {}
        with app.db() as connection:
            for record_type in self.singleton_types:
                row = connection.execute(
                    "SELECT public_id FROM sync_records "
                    "WHERE record_type=? AND deleted_at IS NULL",
                    (record_type,),
                ).fetchone()
                canonical_ids[record_type] = str(row[0])
                old_id = "legacy-{}-{}-000000000001".format(
                    record_type, suffix)
                old_ids[record_type] = old_id
                connection.execute(
                    "UPDATE sync_records SET public_id=? "
                    "WHERE record_type=? AND public_id=?",
                    (old_id, record_type, canonical_ids[record_type]),
                )
                rows = connection.execute(
                    "SELECT cursor,origin_device_id,revision "
                    "FROM sync_changes WHERE record_type=? "
                    "AND public_id=?",
                    (record_type, canonical_ids[record_type]),
                ).fetchall()
                for change in rows:
                    event_id = "{}:{}:{}:{}".format(
                        change["origin_device_id"], record_type, old_id,
                        change["revision"],
                    )
                    connection.execute(
                        "UPDATE sync_changes SET public_id=?,event_id=? "
                        "WHERE cursor=?",
                        (old_id, event_id, change["cursor"]),
                    )
                connection.execute(
                    "UPDATE sync_seen_versions SET public_id=? "
                    "WHERE record_type=? AND public_id=?",
                    (old_id, record_type, canonical_ids[record_type]),
                )
        return old_ids, canonical_ids

    def _export(self, path, device_id, after_cursor=0):
        self._open(path)
        with app.db() as connection:
            return sync_engine.export_change_batch(
                connection, device_id, after_cursor=after_cursor, limit=64)

    @staticmethod
    def _batch(sender, record, cursor):
        return {
            "kind": sync_engine.BATCH_KIND,
            "version": sync_engine.BATCH_VERSION,
            "sender_device_id": sender,
            "after_cursor": cursor - 1,
            "cursor": cursor,
            "ack_cursor": 0,
            "has_more": False,
            "records": [record],
        }

    def _assert_single_physical_row(self, connection, record_type):
        table = sync_engine.RECORD_TYPES[record_type].table
        count = connection.execute(
            "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
        self.assertEqual(count, 1, record_type)

    def test_independent_legacy_singletons_migrate_to_same_natural_ids(self):
        paths = (self._path("legacy-a"), self._path("legacy-b"))
        canonical_by_device = []
        for path, device, suffix in zip(
                paths, (DEVICE_A, DEVICE_B), ("a", "b")):
            self._seed(path, device, "aynı")
            old_ids, expected = self._rewrite_as_legacy(path, suffix)
            self._open(path)
            with app.db() as connection:
                result = sync_engine.refresh_local_changes(
                    connection, device)
                self.assertEqual(result["identity_migrated"], 3)
                actual = {
                    row["record_type"]: row["public_id"]
                    for row in connection.execute(
                        "SELECT record_type,public_id FROM sync_records "
                        "WHERE record_type IN ('note','session_summary',"
                        "'session_meta') AND deleted_at IS NULL")
                }
                canonical_by_device.append(actual)
                self.assertEqual(actual, expected)
                for record_type, old_id in old_ids.items():
                    alias = connection.execute(
                        "SELECT canonical_public_id "
                        "FROM sync_identity_aliases WHERE record_type=? "
                        "AND alias_public_id=?",
                        (record_type, old_id),
                    ).fetchone()
                    self.assertEqual(alias[0], expected[record_type])
                    self.assertEqual(connection.execute(
                        "SELECT COUNT(*) FROM sync_changes "
                        "WHERE record_type=? AND public_id=?",
                        (record_type, old_id),
                    ).fetchone()[0], 0)
                    self._assert_single_physical_row(
                        connection, record_type)
        self.assertEqual(canonical_by_device[0], canonical_by_device[1])

    def test_two_way_legacy_roundtrip_same_content_has_no_conflict(self):
        path_a, path_b = self._path("same-a"), self._path("same-b")
        self._seed(path_a, DEVICE_A, "aynı")
        self._seed(path_b, DEVICE_B, "aynı")
        self._rewrite_as_legacy(path_a, "a")
        self._rewrite_as_legacy(path_b, "b")
        batch_a = self._export(path_a, DEVICE_A)
        batch_b = self._export(path_b, DEVICE_B)

        for path, batch, device in (
                (path_b, batch_a, DEVICE_B),
                (path_a, batch_b, DEVICE_A)):
            self._open(path)
            with app.db() as connection:
                merged = sync_engine.apply_change_batch(
                    connection, batch, device)
                self.assertEqual(merged["conflicts"], 0)
                for record_type in self.singleton_types:
                    self._assert_single_physical_row(
                        connection, record_type)
                count = connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts WHERE "
                    "record_type IN ('note','session_summary','session_meta')"
                ).fetchone()[0]
                self.assertEqual(count, 0)

    def test_two_way_legacy_roundtrip_different_content_auto_converges(self):
        path_a, path_b = self._path("different-a"), self._path("different-b")
        self._seed(path_a, DEVICE_A, "A")
        self._seed(path_b, DEVICE_B, "B")
        self._rewrite_as_legacy(path_a, "a")
        self._rewrite_as_legacy(path_b, "b")
        batch_a = self._export(path_a, DEVICE_A)
        batch_b = self._export(path_b, DEVICE_B)

        for path, batch, device in (
                (path_b, batch_a, DEVICE_B),
                (path_a, batch_b, DEVICE_A)):
            self._open(path)
            with app.db() as connection:
                merged = sync_engine.apply_change_batch(
                    connection, batch, device)
                self.assertEqual(merged["conflicts"], 0)
                for record_type in self.singleton_types:
                    self._assert_single_physical_row(
                        connection, record_type)
                conflict_types = {
                    row[0] for row in connection.execute(
                        "SELECT record_type FROM sync_conflicts "
                        "WHERE status='open'")
                }
                self.assertEqual(conflict_types, set())
                self.assertEqual(connection.execute(
                    "SELECT content FROM notes").fetchone()[0], "not-B")
                self.assertEqual(connection.execute(
                    "SELECT approved_content FROM session_summaries"
                ).fetchone()[0], "özet-B")
                self.assertEqual(connection.execute(
                    "SELECT focus FROM session_meta").fetchone()[0],
                    "odak-B")

    def test_direct_apply_without_refresh_migrates_local_legacy_head(self):
        local_path = self._path("direct-local")
        remote_path = self._path("direct-remote")
        self._seed(local_path, DEVICE_A, "yerel")
        old_ids, _ = self._rewrite_as_legacy(local_path, "local")
        remote_batch = self._seed(remote_path, DEVICE_B, "uzak")

        # Deliberately do not call refresh/initialize on the legacy DB here.
        self._open(local_path)
        with app.db() as connection:
            merged = sync_engine.apply_change_batch(
                connection, remote_batch, DEVICE_A)
            self.assertEqual(merged["conflicts"], 0)
            for record_type, old_id in old_ids.items():
                self._assert_single_physical_row(connection, record_type)
                alias = connection.execute(
                    "SELECT 1 FROM sync_identity_aliases "
                    "WHERE record_type=? AND alias_public_id=?",
                    (record_type, old_id),
                ).fetchone()
                self.assertIsNotNone(alias)

    def test_legacy_tombstone_first_then_live_snapshot_is_delete_wins(self):
        path = self._path("tombstone-first")
        batch = self._seed(path, DEVICE_B, "LOCAL-PRIVATE-SENTINEL")
        note = copy.deepcopy(next(
            row for row in batch["records"]
            if row["record_type"] == "note"))
        old_id = "legacy-note-tombstone-first-000001"
        note.update({
            "public_id": old_id,
            "origin_device_id": DEVICE_A,
            "revision": 1,
            "parent_origin_device_id": None,
            "parent_revision": None,
        })
        tombstone = copy.deepcopy(note)
        tombstone.update({
            "revision": 2,
            "parent_origin_device_id": DEVICE_A,
            "parent_revision": 1,
            "updated_at": "2026-08-17T11:00:00+00:00",
            "deleted_at": "2026-08-17T11:00:00+00:00",
            "payload": None,
        })

        self._open(path)
        with app.db() as connection:
            first = sync_engine.apply_change_batch(
                connection, self._batch(DEVICE_A, tombstone, 1), DEVICE_B)
            self.assertEqual(first["applied"], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
                1,
            )
            second = sync_engine.apply_change_batch(
                connection, self._batch(DEVICE_A, note, 2), DEVICE_B)
            self.assertEqual(second["conflicts"], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
                0,
            )
            canonical = connection.execute(
                "SELECT deleted_at FROM sync_records WHERE "
                "record_type='note' AND public_id LIKE 'singleton-note:%'"
            ).fetchone()
            self.assertIsNotNone(canonical[0])
            retained = json.dumps([
                list(row) for row in connection.execute(
                    "SELECT payload_json FROM sync_changes UNION ALL "
                    "SELECT local_json FROM sync_conflicts UNION ALL "
                    "SELECT incoming_json FROM sync_conflicts")
            ], ensure_ascii=False)
            self.assertNotIn("not-LOCAL-PRIVATE-SENTINEL", retained)

    def test_canonical_delete_blocks_old_live_replay_without_payload(self):
        path = self._path("canonical-delete")
        batch = self._seed(path, DEVICE_B, "DELETE-PRIVATE-SENTINEL")
        note = copy.deepcopy(next(
            row for row in batch["records"]
            if row["record_type"] == "note"))
        old_id = "legacy-note-stale-live-0000000001"
        note.update({
            "public_id": old_id,
            "origin_device_id": DEVICE_A,
            "revision": 1,
            "parent_origin_device_id": None,
            "parent_revision": None,
        })

        self._open(path)
        with app.db() as connection:
            note_id = connection.execute(
                "SELECT id FROM notes").fetchone()[0]
            sync_engine.record_local_delete(
                connection, "note", int(note_id), DEVICE_B,
                physical=True)
            merged = sync_engine.apply_change_batch(
                connection, self._batch(DEVICE_A, note, 1), DEVICE_B)
            self.assertEqual(merged["conflicts"], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
                0,
            )
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts "
                "WHERE record_type='note'"
            ).fetchone()[0], 0)
            retained = json.dumps([
                list(row) for row in connection.execute(
                    "SELECT payload_json FROM sync_changes UNION ALL "
                    "SELECT local_json FROM sync_conflicts UNION ALL "
                    "SELECT incoming_json FROM sync_conflicts")
            ], ensure_ascii=False)
            self.assertNotIn("not-DELETE-PRIVATE-SENTINEL", retained)

    def test_mismatched_canonical_singleton_id_cannot_become_alias(self):
        path = self._path("canonical-alias-poison")
        batch = self._seed(path, DEVICE_B, "ALIAS-GUARD")
        wrong_conversation = "other-conversation-public-00000002"

        self._open(path)
        with app.db() as connection:
            for cursor, record_type in enumerate(
                    self.singleton_types, start=1):
                incoming = copy.deepcopy(next(
                    row for row in batch["records"]
                    if row["record_type"] == record_type))
                wrong_public_id = (
                    sync_engine._conversation_singleton_public_id(
                        record_type, wrong_conversation))
                incoming.update({
                    "public_id": wrong_public_id,
                    "origin_device_id": DEVICE_A,
                    "revision": 1,
                    "parent_origin_device_id": None,
                    "parent_revision": None,
                })

                with self.assertRaises(sync_engine.SyncError):
                    sync_engine.apply_change_batch(
                        connection,
                        self._batch(DEVICE_A, incoming, cursor),
                        DEVICE_B,
                    )
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM sync_identity_aliases "
                    "WHERE record_type=? AND alias_public_id=?",
                    (record_type, wrong_public_id),
                ).fetchone()[0], 0)
                self._assert_single_physical_row(connection, record_type)

    def test_refresh_canonicalizes_unhooked_legacy_physical_delete(self):
        path = self._path("unhooked-legacy-delete")
        self._seed(path, DEVICE_A, "UNHOOKED-DELETE-SENTINEL")
        old_ids, canonical_ids = self._rewrite_as_legacy(path, "deleted")

        self._open(path)
        with app.db() as connection:
            note_id = connection.execute(
                "SELECT id FROM notes").fetchone()[0]
            # Legacy/unhooked application paths can remove the physical row
            # before the sync safety scan observes it.
            connection.execute("DELETE FROM notes WHERE id=?", (note_id,))
            sync_engine.refresh_local_changes(connection, DEVICE_A)

            canonical = connection.execute(
                "SELECT local_id,deleted_at FROM sync_records "
                "WHERE record_type='note' AND public_id=?",
                (canonical_ids["note"],),
            ).fetchone()
            self.assertIsNotNone(canonical)
            self.assertIsNone(canonical["local_id"])
            self.assertIsNotNone(canonical["deleted_at"])
            alias = connection.execute(
                "SELECT canonical_public_id FROM sync_identity_aliases "
                "WHERE record_type='note' AND alias_public_id=?",
                (old_ids["note"],),
            ).fetchone()
            self.assertIsNotNone(alias)
            self.assertEqual(alias[0], canonical_ids["note"])
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_changes WHERE "
                "record_type='note' AND public_id=? AND payload_json IS NOT NULL",
                (old_ids["note"],),
            ).fetchone()[0], 0)

    def test_service_prepare_uses_automatic_latest_merge(self):
        local_path = self._path("automatic-latest-local")
        remote_path = self._path("automatic-latest-remote")

        self._open(local_path)
        local_device = sync_service._device_id()
        self._seed(local_path, local_device, "LOCAL")
        remote_batch = self._seed(
            remote_path, SERVICE_REMOTE, "REMOTE")
        for record in remote_batch["records"]:
            if record["record_type"] in self.singleton_types:
                record["updated_at"] = "2026-08-17T11:00:00+00:00"
                record["payload"]["updated"] = (
                    "2026-08-17T11:00:00+00:00")

        self._open(local_path)
        with app.db() as connection:
            merged = sync_engine.apply_change_batch(
                connection, remote_batch, local_device)
            content = connection.execute(
                "SELECT content FROM notes").fetchone()[0]
            open_conflicts = sync_engine.list_conflicts(connection)
        self.assertEqual(merged["conflicts"], 0)
        self.assertEqual(content, "not-REMOTE")
        self.assertEqual(open_conflicts, [])

    def test_prepare_scrubs_fifteen_missing_dependency_payloads(self):
        sentinel = "MISSING-PARENT-PRIVATE-SENTINEL"
        path = self._path("hard-parent")
        self._open(path)
        local_device = sync_service._device_id()
        with app.db() as connection:
            conversation_id = connection.execute(
                "INSERT INTO conversations("
                "public_id,mode,therapist,title,created,updated,ended,"
                "source_mode) VALUES(?,?,?,?,?,?,0,0)",
                (
                    CONVERSATION_PUBLIC_ID, "terapi", "freud",
                    "Silinen görüşme", STAMP, STAMP,
                ),
            ).lastrowid
            sync_engine.initialize_sync(connection, local_device)
            sync_engine.record_local_delete(
                connection, "conversation", int(conversation_id),
                local_device, physical=True)
            for index in range(15):
                public_id = "missing-parent-message-{:04d}-00000001".format(
                    index)
                incoming = {
                    "record_type": "message",
                    "public_id": public_id,
                    "revision": 1,
                    "origin_device_id": SERVICE_REMOTE,
                    "parent_origin_device_id": None,
                    "parent_revision": None,
                    "updated_at": STAMP,
                    "deleted_at": None,
                    "payload": {
                        "role": "assistant",
                        "content": "{}-{:02d}".format(sentinel, index),
                        "created": STAMP,
                        "conversation_public_id": CONVERSATION_PUBLIC_ID,
                    },
                }
                incoming_json = json.dumps(
                    incoming, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"))
                connection.execute(
                    "INSERT INTO sync_conflicts("
                    "record_type,public_id,reason,local_json,incoming_json,"
                    "incoming_event_id,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        "message", public_id, "missing_dependency",
                        json.dumps({
                            "record_type": "message",
                            "public_id": public_id,
                            "missing_dependency": True,
                        }, sort_keys=True, separators=(",", ":")),
                        incoming_json,
                        "{}:message:{}:1".format(
                            SERVICE_REMOTE, public_id),
                        STAMP,
                    ),
                )
                connection.execute(
                    "INSERT INTO sync_changes("
                    "event_id,record_type,public_id,revision,"
                    "origin_device_id,parent_origin_device_id,"
                    "parent_revision,updated_at,deleted_at,payload_json) "
                    "VALUES(?,?,?,?,?,?,?,?,NULL,?)",
                    (
                        "queued:{}:1".format(public_id), "message",
                        public_id, 1, SERVICE_REMOTE, None, None, STAMP,
                        json.dumps(
                            incoming["payload"], ensure_ascii=False,
                            sort_keys=True, separators=(",", ":")),
                    ),
                )

        sync_service._prepare_database(refresh=False)

        with app.db() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "record_type='message'"
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_changes WHERE "
                "record_type='message'"
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM sync_excluded_records WHERE "
                "record_type='message' AND reason='orphan_parent'"
            ).fetchone()[0], 15)
            encoded = json.dumps([
                list(row) for row in connection.execute(
                    "SELECT payload_json FROM sync_changes UNION ALL "
                    "SELECT local_json FROM sync_conflicts UNION ALL "
                    "SELECT incoming_json FROM sync_conflicts")
            ], ensure_ascii=False)
            self.assertNotIn(sentinel, encoded)
