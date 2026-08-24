import copy
import json
from pathlib import Path

from support import DatabaseTestCase, app

import sync_engine as sync


DEVICE_A = "structured-device-a"
DEVICE_B = "structured-device-b"


class StructuredModuleSyncTests(DatabaseTestCase):

    def _target_path(self):
        return str(Path(self._tmp.name) / "structured-target.db")

    def _with_database(self, path, callback):
        original = app.DB_PATH
        app.DB_PATH = path
        try:
            app.init_db()
            with app.db() as connection:
                return callback(connection)
        finally:
            app.DB_PATH = original

    def _insert_adhd_graph(self, *, extra_private=True):
        conv_id = self.conversation(
            therapist="adhd", title="ADHD yürütücü işlev desteği")
        with app.db() as connection:
            habit_id = connection.execute(
                "INSERT INTO adhd_habits("
                "source_conv,title,cue,tiny_action,target_per_week,"
                "preferred_days_json,reminder_local_time,timezone,status,"
                "review_after,is_guest,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    conv_id, "Defteri aç", "Kahveden sonra", "Bir satır",
                    3, "[4, 1]", "09:15", "Europe/Istanbul", "active",
                    1780000000.0, 0, "2026-08-17 09:00",
                    "2026-08-17 09:00",
                ),
            ).lastrowid
            reminder_id = connection.execute(
                "INSERT INTO reminders(task,due_at,status,answer,"
                "notified,is_guest,source_conv,created,updated) "
                "VALUES(?,?,'pending','',0,0,?,?,?)",
                (
                    "Cihazda kalacak alarm", 1780000100.0, conv_id,
                    "2026-08-17 09:00", "2026-08-17 09:00",
                ),
            ).lastrowid
            event_id = connection.execute(
                "INSERT INTO adhd_habit_events("
                "habit,scheduled_for,status,reminder_id,effort_minutes,"
                "friction,note,started_at,completed_at,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    habit_id, 1780000100.0, "done", reminder_id, 7,
                    "start", "EVENT-NOTE-NEVER-WIRE-9ca1",
                    "2026-08-17 09:01", "2026-08-17 09:08",
                    "2026-08-17 09:00", "2026-08-17 09:08",
                ),
            ).lastrowid
            scheduled_event_id = connection.execute(
                "INSERT INTO adhd_habit_events("
                "habit,scheduled_for,status,reminder_id,note,created,updated) "
                "VALUES(?,?,'scheduled',?, ?,?,?)",
                (
                    habit_id, 1780086500.0, reminder_id,
                    "SCHEDULED-LOCAL-ONLY-37b4", "2026-08-17 09:00",
                    "2026-08-17 09:00",
                ),
            ).lastrowid
            journal_id = connection.execute(
                "INSERT INTO adhd_journal_entries("
                "conv,habit,event,entry_type,content,share_with_coach,"
                "sensitive,is_guest,created,updated) "
                "VALUES(?,?,?,?,?,1,0,0,?,?)",
                (
                    conv_id, habit_id, event_id, "daily_page",
                    "SHARED-JOURNAL-56e2", "2026-08-17 09:09",
                    "2026-08-17 09:09",
                ),
            ).lastrowid
            private_ids = []
            if extra_private:
                for content, shared, sensitive in (
                        ("UNSHARED-JOURNAL-f870", 0, 0),
                        ("SENSITIVE-JOURNAL-6da5", 0, 1)):
                    private_ids.append(connection.execute(
                        "INSERT INTO adhd_journal_entries("
                        "conv,habit,event,entry_type,content,"
                        "share_with_coach,sensitive,is_guest,created,updated) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            conv_id, habit_id, scheduled_event_id,
                            "freewrite", content, shared, sensitive, 0,
                            "2026-08-17 09:10", "2026-08-17 09:10",
                        ),
                    ).lastrowid)
        return {
            "conv": conv_id,
            "habit": habit_id,
            "event": event_id,
            "scheduled_event": scheduled_event_id,
            "journal": journal_id,
            "private_journals": private_ids,
            "reminder": reminder_id,
        }

    @staticmethod
    def _stored_sync_json(connection):
        result = {}
        for table in (
                "sync_records", "sync_changes", "sync_seen_versions",
                "sync_conflicts", "sync_excluded_records"):
            result[table] = [
                list(row) for row in connection.execute(
                    "SELECT * FROM {}".format(table)).fetchall()
            ]
        return json.dumps(result, ensure_ascii=False)

    def test_v7_adhd_projection_roundtrip_is_safe_and_relational(self):
        ids = self._insert_adhd_graph()
        with app.db() as connection:
            initialized = sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            wire = json.dumps(batch, ensure_ascii=False)
            stored = self._stored_sync_json(connection)
            excluded_shadow_count = connection.execute(
                "SELECT COUNT(*) FROM sync_records WHERE "
                "(record_type='adhd_habit_event' AND local_id=?) OR "
                "(record_type='adhd_journal' AND local_id IN (?,?))",
                (
                    ids["scheduled_event"],
                    ids["private_journals"][0],
                    ids["private_journals"][1],
                ),
            ).fetchone()[0]

        types = [row["record_type"] for row in batch["records"]]
        self.assertEqual(batch["version"], 8)
        self.assertEqual(types.count("adhd_habit"), 1)
        self.assertEqual(types.count("adhd_habit_event"), 1)
        self.assertEqual(types.count("adhd_journal"), 1)
        self.assertGreaterEqual(initialized["policy_excluded"], 3)
        self.assertEqual(excluded_shadow_count, 0)
        self.assertIn("SHARED-JOURNAL-56e2", wire)
        for forbidden in (
                "EVENT-NOTE-NEVER-WIRE-9ca1", "SCHEDULED-LOCAL-ONLY-37b4",
                "UNSHARED-JOURNAL-f870", "SENSITIVE-JOURNAL-6da5",
                "reminder_id", "client_event_id", "last_request_id"):
            self.assertNotIn(forbidden, wire)
            self.assertNotIn(forbidden, stored)
        habit = next(
            row for row in batch["records"]
            if row["record_type"] == "adhd_habit")
        self.assertEqual(habit["payload"]["preferred_days_json"], "[1,4]")

        def apply_and_read(connection):
            result = sync.apply_change_batch(connection, batch, DEVICE_B)
            habit_row = connection.execute(
                "SELECT * FROM adhd_habits").fetchone()
            event_row = connection.execute(
                "SELECT * FROM adhd_habit_events").fetchone()
            journal_row = connection.execute(
                "SELECT * FROM adhd_journal_entries").fetchone()
            counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in ("reminders", "scheduled_messages", "jobs")
            }
            return result, habit_row, event_row, journal_row, counts

        result, habit, event, journal, local_state = self._with_database(
            self._target_path(), apply_and_read)
        self.assertEqual(result["applied"], len(batch["records"]))
        self.assertEqual(event["habit"], habit["id"])
        self.assertEqual(event["status"], "done")
        self.assertIsNone(event["reminder_id"])
        self.assertEqual(event["note"], "")
        self.assertEqual(journal["habit"], habit["id"])
        self.assertEqual(journal["event"], event["id"])
        self.assertEqual(set(local_state.values()), {0})

    def test_revoked_eligibility_scrubs_text_and_is_reversible(self):
        ids = self._insert_adhd_graph(extra_private=False)
        target = self._target_path()
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            cursor = initial["cursor"]
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, initial, DEVICE_B),
        )

        with app.db() as connection:
            journal_meta = dict(connection.execute(
                "SELECT * FROM sync_records WHERE record_type='adhd_journal' "
                "AND local_id=?", (ids["journal"],)).fetchone())
            revoked_journal_public_id = journal_meta["public_id"]
            connection.execute(
                "INSERT INTO sync_conflicts("
                "record_type,public_id,reason,local_json,incoming_json,"
                "incoming_event_id,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    "adhd_journal", journal_meta["public_id"],
                    "concurrent_clinical_edit",
                    json.dumps({"payload": {"content": "SHARED-JOURNAL-56e2"}}),
                    json.dumps({"payload": {"content": "REMOTE-PRIVATE-c2d1"}}),
                    "conflict-event-private-0001", "2026-08-17 10:00",
                ),
            )
            connection.execute(
                "UPDATE adhd_journal_entries SET share_with_coach=0,"
                "sensitive=1,updated=? WHERE id=?",
                ("2026-08-17 10:01", ids["journal"]),
            )
            connection.execute(
                "UPDATE adhd_habit_events SET status='scheduled',updated=? "
                "WHERE id=?",
                ("2026-08-17 10:01", ids["event"]),
            )
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            withdrawn = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=cursor)
            stored = self._stored_sync_json(connection)

        self.assertEqual(refreshed["policy_redacted"], 2)
        self.assertEqual(
            {row["record_type"] for row in withdrawn["records"]},
            {"adhd_habit_event", "adhd_journal"},
        )
        self.assertTrue(all(
            row["payload"] is None and row["deleted_at"]
            for row in withdrawn["records"]))
        self.assertNotIn("SHARED-JOURNAL-56e2", stored)
        self.assertNotIn("REMOTE-PRIVATE-c2d1", stored)

        # A stale peer must not re-introduce text after consent withdrawal.
        stale = copy.deepcopy(next(
            row for row in initial["records"]
            if row["record_type"] == "adhd_journal"))
        stale.update({
            "origin_device_id": DEVICE_B,
            "revision": 2,
            "parent_origin_device_id": None,
            "parent_revision": None,
            "updated_at": "2026-08-17T10:02:00+00:00",
        })
        stale["payload"]["content"] = "REVOKED-REPLAY-MUST-DROP-18f3"
        stale_batch = {
            "kind": sync.BATCH_KIND,
            "version": sync.BATCH_VERSION,
            "sender_device_id": DEVICE_B,
            "after_cursor": 0,
            "cursor": 1,
            "ack_cursor": 0,
            "has_more": False,
            "records": [stale],
        }
        with app.db() as connection:
            stale_result = sync.apply_change_batch(
                connection, stale_batch, DEVICE_A)
            after_replay = self._stored_sync_json(connection)
        self.assertEqual(stale_result["ignored"], 1)
        self.assertEqual(stale_result["applied"], 0)
        self.assertEqual(stale_result["conflicts"], 0)
        self.assertNotIn("REVOKED-REPLAY-MUST-DROP-18f3", after_replay)

        def apply_withdrawal(connection):
            result = sync.apply_change_batch(connection, withdrawn, DEVICE_B)
            counts = (
                connection.execute(
                    "SELECT COUNT(*) FROM adhd_habit_events").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM adhd_journal_entries").fetchone()[0],
            )
            return result, counts

        result, counts = self._with_database(target, apply_withdrawal)
        self.assertEqual(result["applied"], 2)
        self.assertEqual(counts, (0, 0))

        # Explicitly opting in again is reversible. It creates live heads while
        # keeping the revoked journal identity as a content-free tombstone.
        with app.db() as connection:
            before = sync.local_cursor_high_water(connection)
            connection.execute(
                "UPDATE adhd_journal_entries SET share_with_coach=1,"
                "sensitive=0,updated=? WHERE id=?",
                ("2026-08-17 10:05", ids["journal"]),
            )
            connection.execute(
                "UPDATE adhd_habit_events SET status='done',updated=? "
                "WHERE id=?",
                ("2026-08-17 10:05", ids["event"]),
            )
            sync.refresh_local_changes(connection, DEVICE_A)
            reenabled = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=before)
        self.assertEqual(
            {row["record_type"] for row in reenabled["records"]},
            {"adhd_habit_event", "adhd_journal"},
        )
        self.assertTrue(all(row["deleted_at"] is None
                            for row in reenabled["records"]))
        self.assertNotIn(
            revoked_journal_public_id,
            {row["public_id"] for row in reenabled["records"]
             if row["record_type"] == "adhd_journal"},
        )

        def apply_reenabled(connection):
            result = sync.apply_change_batch(
                connection, reenabled, DEVICE_B)
            return result, (
                connection.execute(
                    "SELECT COUNT(*) FROM adhd_habit_events").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM adhd_journal_entries").fetchone()[0],
            )

        reenabled_result, reenabled_counts = self._with_database(
            target, apply_reenabled)
        self.assertEqual(reenabled_result["applied"], 2)
        self.assertEqual(reenabled_counts, (1, 1))

    def test_optional_policy_withdrawn_event_does_not_drop_shared_journal(self):
        ids = self._insert_adhd_graph(extra_private=False)
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            initial = sync.export_change_batch(connection, DEVICE_A)
            cursor = initial["cursor"]
            event_record = next(
                row for row in initial["records"]
                if row["record_type"] == "adhd_habit_event")
            journal_template = copy.deepcopy(next(
                row for row in initial["records"]
                if row["record_type"] == "adhd_journal"))

        target = self._target_path()
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, initial, DEVICE_B),
        )
        with app.db() as connection:
            connection.execute(
                "UPDATE adhd_habit_events SET status='scheduled',updated=? "
                "WHERE id=?",
                ("2026-08-17 10:10", ids["event"]),
            )
            sync.refresh_local_changes(connection, DEVICE_A)
            withdrawal = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=cursor)
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, withdrawal, DEVICE_B),
        )

        sentinel = "SHARED-JOURNAL-WITH-OPTIONAL-REVOKED-EVENT-9c2a"
        journal_template.update({
            "public_id": "adhd-journal:optional-revoked-event-01",
            "revision": 1,
            "origin_device_id": "structured-device-c",
            "parent_origin_device_id": None,
            "parent_revision": None,
            "updated_at": "2026-08-17T10:11:00+00:00",
        })
        journal_template["payload"]["content"] = sentinel
        journal_template["payload"]["event_public_id"] = (
            event_record["public_id"])
        incoming = {
            "kind": sync.BATCH_KIND,
            "version": sync.BATCH_VERSION,
            "sender_device_id": "structured-device-c",
            "after_cursor": 0,
            "cursor": 1,
            "ack_cursor": 0,
            "has_more": False,
            "records": [journal_template],
        }

        def apply_journal(connection):
            result = sync.apply_change_batch(
                connection, incoming, DEVICE_B)
            row = connection.execute(
                "SELECT j.content,j.event FROM sync_records s "
                "JOIN adhd_journal_entries j ON j.id=s.local_id "
                "WHERE s.record_type='adhd_journal' AND s.public_id=?",
                (journal_template["public_id"],),
            ).fetchone()
            conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]
            excluded = connection.execute(
                "SELECT COUNT(*) FROM sync_excluded_records WHERE "
                "record_type='adhd_journal' AND public_id=?",
                (journal_template["public_id"],),
            ).fetchone()[0]
            return result, row, conflicts, excluded

        result, row, conflicts, excluded = self._with_database(
            target, apply_journal)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(row["content"], sentinel)
        self.assertIsNone(row["event"])
        self.assertEqual(conflicts, 0)
        self.assertEqual(excluded, 0)

    def test_guest_quarantine_closes_habit_event_journal_graph(self):
        ids = self._insert_adhd_graph(extra_private=False)
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            identities = {
                (row["record_type"], row["public_id"])
                for row in connection.execute(
                    "SELECT record_type,public_id FROM sync_records")
            }
            connection.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?",
                (ids["conv"],),
            )
            repaired = sync.export_change_batch(connection, DEVICE_A)
            stored = self._stored_sync_json(connection)
            excluded = {
                (row[0], row[1]) for row in connection.execute(
                    "SELECT record_type,public_id FROM sync_excluded_records "
                    "WHERE reason='guest_scope'")
            }
            remaining = connection.execute(
                "SELECT COUNT(*) FROM sync_records").fetchone()[0]
        self.assertEqual(repaired["records"], [])
        self.assertEqual(remaining, 0)
        self.assertTrue(identities.issubset(excluded))
        for sentinel in (
                "SHARED-JOURNAL-56e2", "Defteri aç", "Kahveden sonra"):
            self.assertNotIn(sentinel, stored)

    def test_stale_guest_replay_is_blocked_across_typed_references(self):
        conv_public = "guest-structured-conversation-001"
        habit_public = "guest-structured-habit-00000001"
        event_public = "guest-structured-event-00000001"
        journal_public = "guest-structured-journal-000001"
        conv_id = self.conversation(title="Misafir yapılandırılmış alan")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET public_id=?,is_guest=1 WHERE id=?",
                (conv_public, conv_id),
            )
            sync.initialize_sync(connection, DEVICE_A)
            sync.record_local_delete(
                connection, "conversation", conv_id, DEVICE_A,
                physical=True)
            batch = {
                "kind": sync.BATCH_KIND,
                "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_B,
                "after_cursor": 0,
                "cursor": 4,
                "ack_cursor": 0,
                "has_more": False,
                "records": [
                    self._wire_record("adhd_journal", journal_public, {
                        "conversation_public_id": conv_public,
                        "habit_public_id": habit_public,
                        "event_public_id": event_public,
                        "entry_type": "freewrite",
                        "content": "STALE-GUEST-JOURNAL-719e",
                        "share_with_coach": 1, "sensitive": 0,
                        "created": "2026-08-17 11:03",
                        "updated": "2026-08-17 11:03",
                    }),
                    self._wire_record("adhd_habit_event", event_public, {
                        "habit_public_id": habit_public,
                        "scheduled_for": 1780000100.0,
                        "status": "done", "effort_minutes": 4,
                        "friction": "start",
                        "created": "2026-08-17 11:02",
                        "updated": "2026-08-17 11:02",
                    }),
                    self._wire_record("adhd_habit", habit_public, {
                        "conversation_public_id": conv_public,
                        "title": "STALE-GUEST-HABIT-1db7", "cue": "",
                        "tiny_action": "", "target_per_week": 2,
                        "preferred_days_json": "[]",
                        "reminder_local_time": "", "timezone": "",
                        "status": "active", "review_after": 1780000200.0,
                        "created": "2026-08-17 11:01",
                        "updated": "2026-08-17 11:01",
                    }),
                    self._wire_record("conversation", conv_public, {
                        "mode": "terapi", "therapist": "adhd",
                        "title": "STALE-GUEST-CONVERSATION-98d0",
                        "created": "2026-08-17 11:00",
                        "updated": "2026-08-17 11:00",
                    }),
                ],
            }
            result = sync.apply_change_batch(connection, batch, DEVICE_A)
            stored = self._stored_sync_json(connection)
            app_counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "conversations", "adhd_habits", "adhd_habit_events",
                    "adhd_journal_entries")
            }
        self.assertEqual(result["ignored"], 4)
        self.assertEqual(set(app_counts.values()), {0})
        self.assertNotIn("STALE-GUEST", stored)

    @staticmethod
    def _wire_record(record_type, public_id, payload):
        return {
            "record_type": record_type,
            "public_id": public_id,
            "revision": 1,
            "origin_device_id": DEVICE_B,
            "parent_origin_device_id": None,
            "parent_revision": None,
            "updated_at": "2026-08-17T11:10:00+00:00",
            "deleted_at": None,
            "payload": payload,
        }

    def test_legacy_protocol_and_unsafe_incoming_records_are_rejected_without_mutation(self):
        empty = {
            "kind": sync.BATCH_KIND,
            "version": sync.BATCH_VERSION,
            "sender_device_id": DEVICE_B,
            "after_cursor": 0,
            "cursor": 0,
            "ack_cursor": 0,
            "has_more": False,
            "records": [],
        }
        v3 = copy.deepcopy(empty)
        v3["version"] = 3
        with app.db() as connection:
            before_tables = list(connection.execute(
                "SELECT name,sql FROM sqlite_master ORDER BY name"))
            with self.assertRaisesRegex(
                    sync.SyncError, "protocol v8 required"):
                sync.validate_change_batch(v3)
            with self.assertRaisesRegex(
                    sync.SyncError, "protocol v8 required"):
                sync.apply_change_batch(connection, v3, DEVICE_A)
            after_tables = list(connection.execute(
                "SELECT name,sql FROM sqlite_master ORDER BY name"))
        self.assertEqual(before_tables, after_tables)

        unsafe_journal = copy.deepcopy(empty)
        unsafe_journal["cursor"] = 1
        unsafe_journal["records"] = [self._wire_record(
            "adhd_journal", "unsafe-private-journal-000001", {
                "conversation_public_id": "safe-parent-conversation-00001",
                "entry_type": "freewrite", "content": "PRIVATE-WIRE",
                "share_with_coach": 0, "sensitive": 1,
                "created": "2026-08-17 12:00",
                "updated": "2026-08-17 12:00",
            })]
        with self.assertRaisesRegex(sync.SyncError, "excluded by sync policy"):
            sync.validate_change_batch(unsafe_journal)

        unsafe_event = copy.deepcopy(empty)
        unsafe_event["cursor"] = 1
        unsafe_event["records"] = [self._wire_record(
            "adhd_habit_event", "unsafe-active-event-000000001", {
                "habit_public_id": "safe-parent-habit-0000000001",
                "scheduled_for": 1780000100.0, "status": "scheduled",
                "created": "2026-08-17 12:00",
                "updated": "2026-08-17 12:00",
            })]
        with self.assertRaisesRegex(sync.SyncError, "excluded by sync policy"):
            sync.validate_change_batch(unsafe_event)

    def test_raw_and_legacy_schema_graph_remains_device_local(self):
        conv_id = self.conversation(
            therapist="young", title="Şema yolu yerel kalır")
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "Tarafsız kaynak", "2026-08-17 13:00"),
            ).lastrowid
            observation_id = connection.execute(
                "INSERT INTO psych_observations("
                "conv,source_message,therapist,dimension,content,created) "
                "VALUES(?,?,?,?,?,?)",
                (
                    conv_id, message_id, "young", "user_report",
                    "SCHEMA-OBSERVATION-LOCAL-b146", "2026-08-17 13:01",
                ),
            ).lastrowid
            claim_id = connection.execute(
                "INSERT INTO psych_claims("
                "public_id,source_conv,therapist,lens,claim_type,title,"
                "statement,status,scope,sensitive,user_edited,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,0,1,?,?)",
                (
                    "schema-approved-claim-00000001", conv_id, "young",
                    "schema", "schema", "SCHEMA-CLAIM-TITLE-782d",
                    "SCHEMA-CLAIM-STATEMENT-74cf", "approved", "shared",
                    "2026-08-17 13:02", "2026-08-17 13:02",
                ),
            ).lastrowid
            evidence_id = connection.execute(
                "INSERT INTO psych_claim_evidence("
                "claim,observation,relation,review_status,created) "
                "VALUES(?,?,'supports','accepted',?)",
                (claim_id, observation_id, "2026-08-17 13:03"),
            ).lastrowid
            connection.execute(
                "UPDATE psych_claims SET reviewed_evidence_id=? WHERE id=?",
                (evidence_id, claim_id),
            )
            path_id = connection.execute(
                "INSERT INTO schema_paths("
                "conv,therapist,claim,phase,status,practice_json,"
                "revision,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    conv_id, "young", claim_id, "practice", "active",
                    json.dumps({"private": "SCHEMA-PRACTICE-LOCAL-e91c"}),
                    2, "2026-08-17 13:04", "2026-08-17 13:04",
                ),
            ).lastrowid
            connection.execute(
                "INSERT INTO schema_path_events("
                "path,conv,seq,action,kind,value,payload_json,authored_by,"
                "request_id,request_hash,response_json,created) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    path_id, conv_id, 1, "practice", "private_text",
                    "SCHEMA-EVENT-VALUE-LOCAL-11ac",
                    json.dumps({"hypothesis": "UNCONFIRMED-SCHEMA-2d77"}),
                    "user", "schema-request-local-0001", "hash-local",
                    "{}", "2026-08-17 13:05",
                ),
            )
            sync.initialize_sync(connection, DEVICE_A)
            batch = sync.export_change_batch(connection, DEVICE_A)
            before = batch["cursor"]
            wire = json.dumps(batch, ensure_ascii=False)
            connection.execute(
                "UPDATE schema_paths SET practice_json=?,updated=? WHERE id=?",
                (
                    json.dumps({"private": "SCHEMA-PRACTICE-UPDATED-9ee1"}),
                    "2026-08-17 13:10", path_id,
                ),
            )
            sync.refresh_local_changes(connection, DEVICE_A)
            later = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=before)

        for sentinel in (
                "SCHEMA-OBSERVATION-LOCAL-b146",
                "SCHEMA-CLAIM-TITLE-782d", "SCHEMA-CLAIM-STATEMENT-74cf",
                "SCHEMA-PRACTICE-LOCAL-e91c",
                "SCHEMA-EVENT-VALUE-LOCAL-11ac", "UNCONFIRMED-SCHEMA-2d77"):
            self.assertNotIn(sentinel, wire)
        self.assertEqual(later["records"], [])

        def apply_and_count(connection):
            sync.apply_change_batch(connection, batch, DEVICE_B)
            return {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in sync.DEVICE_LOCAL_CLINICAL_TABLES
                if table not in {"technique_runs"}
            }

        counts = self._with_database(self._target_path(), apply_and_count)
        self.assertEqual(set(counts.values()), {0})

    def test_conversation_delete_tombstones_full_adhd_graph(self):
        ids = self._insert_adhd_graph(extra_private=False)
        with app.db() as connection:
            sync.initialize_sync(connection, DEVICE_A)
            before = sync.local_cursor_high_water(connection)
            deleted = sync.record_local_delete(
                connection, "conversation", ids["conv"], DEVICE_A,
                physical=True)
            batch = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=before)
            physical_counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "conversations", "adhd_habits", "adhd_habit_events",
                    "adhd_journal_entries")
            }
        expected = {
            "conversation", "adhd_habit", "adhd_habit_event", "adhd_journal",
        }
        self.assertEqual({row["record_type"] for row in deleted}, expected)
        self.assertEqual({row["record_type"] for row in batch["records"]}, expected)
        self.assertTrue(all(
            row["payload"] is None and row["deleted_at"]
            for row in batch["records"]))
        self.assertEqual(set(physical_counts.values()), {0})
