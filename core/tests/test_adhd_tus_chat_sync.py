"""Conversational TUS messages remain local with their planner provenance."""

import json

from support import DatabaseTestCase, app

import sync_engine as sync


DEVICE = "tus-chat-device-0001"


class ADHDTUSChatSyncTests(DatabaseTestCase):

    def add_planner(self, connection, conv_id, revision=2):
        stamp = "2026-08-24 12:00"
        return connection.execute(
            "INSERT INTO adhd_tus_planners(public_id,conv,protocol,enabled,"
            "phase,answers_json,revision,current_plan,catalog_fingerprint,"
            "created,updated) VALUES(?,?,?,1,'lesson','{}',?,NULL,'test',?,?)",
            ("a" * 32, conv_id, app.ADHD_TUS_PROTOCOL, revision,
             stamp, stamp),
        ).lastrowid

    def add_message(self, connection, conv_id, public_id, role, content,
                    *, reply_to=None, pair=""):
        return connection.execute(
            "INSERT INTO messages(public_id,conv,role,content,created,"
            "reply_to,turn_pair_public_id,delivery_status) "
            "VALUES(?,?,?,?,?,?,?,'completed')",
            (public_id, conv_id, role, content, "2026-08-24 12:00",
             reply_to, pair),
        ).lastrowid

    def add_turn(self, connection, conv_id, planner_id, prompt_id, *,
                 answer_id=None, suffix="1", status="open", revision=2):
        stamp = "2026-08-24 12:00"
        connection.execute(
            "INSERT INTO adhd_tus_chat_turns(public_id,conv,planner,plan,"
            "step,revision,kind,question_id,prompt_message,answer_message,"
            "status,provenance,created_request_id,answered_request_id,"
            "created,updated) VALUES(?,?,?,NULL,NULL,?,'question','lesson',"
            "?,?,?,'deterministic_metadata_v1',?,?,?,?)",
            (suffix * 32, conv_id, planner_id, revision, prompt_id,
             answer_id, status, "create-request-{}-0001".format(suffix),
             ("answer-request-{}-0001".format(suffix)
              if answer_id is not None else None), stamp, stamp),
        )

    def test_refresh_excludes_tus_bubbles_reply_descendants_and_pair(self):
        conv_id = self.conversation(therapist="adhd")
        sentinels = {
            "TUS-PROMPT-LOCAL-5e9b", "TUS-ANSWER-LOCAL-96c1",
            "TUS-NEXT-LOCAL-54f0", "TUS-REPLY-LOCAL-c2d7",
            "TUS-REPLY-PAIR-LOCAL-a1b3",
        }
        ordinary = "ORDINARY-SYNC-MESSAGE-5a81"
        with app.db() as connection:
            planner = self.add_planner(connection, conv_id)
            prompt = self.add_message(
                connection, conv_id, "1" * 32, "assistant",
                "TUS-PROMPT-LOCAL-5e9b")
            answer = self.add_message(
                connection, conv_id, "2" * 32, "user",
                "TUS-ANSWER-LOCAL-96c1", pair="3" * 32)
            next_prompt = self.add_message(
                connection, conv_id, "4" * 32, "assistant",
                "TUS-NEXT-LOCAL-54f0", pair="3" * 32)
            self.add_turn(
                connection, conv_id, planner, prompt, answer_id=answer,
                suffix="5", status="answered", revision=1)
            self.add_turn(
                connection, conv_id, planner, next_prompt, suffix="6")

            # A normal composer reply explicitly attached to a local TUS
            # prompt cannot cross without its parent.  Its assistant pair is
            # excluded transitively even though it has no reply_to itself.
            reply = self.add_message(
                connection, conv_id, "7" * 32, "user",
                "TUS-REPLY-LOCAL-c2d7", reply_to=next_prompt,
                pair="8" * 32)
            paired = self.add_message(
                connection, conv_id, "9" * 32, "assistant",
                "TUS-REPLY-PAIR-LOCAL-a1b3", pair="8" * 32)
            ordinary_id = self.add_message(
                connection, conv_id, "b" * 32, "user", ordinary)

            initialized = sync.initialize_sync(connection, DEVICE)
            batch = sync.export_change_batch(connection, DEVICE)
            shadows = {
                int(row[0]) for row in connection.execute(
                    "SELECT local_id FROM sync_records WHERE "
                    "record_type='message' AND local_id IS NOT NULL")
            }
            with self.assertRaises(sync.SyncError):
                sync.record_local_change(
                    connection, "message", prompt, DEVICE)

        wire = json.dumps(batch, ensure_ascii=False)
        self.assertIn(ordinary, wire)
        for sentinel in sentinels:
            self.assertNotIn(sentinel, wire)
        self.assertEqual(shadows, {ordinary_id})
        self.assertGreaterEqual(initialized["policy_excluded"], 5)
        self.assertNotIn(prompt, shadows)
        self.assertNotIn(answer, shadows)
        self.assertNotIn(next_prompt, shadows)
        self.assertNotIn(reply, shadows)
        self.assertNotIn(paired, shadows)

    def test_existing_message_projection_is_withdrawn_when_tus_ledger_appears(self):
        conv_id = self.conversation(therapist="adhd")
        sentinel = "LATE-TUS-PROVENANCE-MUST-BE-SCRUBBED-0f4c"
        with app.db() as connection:
            prompt = self.add_message(
                connection, conv_id, "c" * 32, "assistant", sentinel)
            sync.initialize_sync(connection, DEVICE)
            before = sync.export_change_batch(connection, DEVICE)["cursor"]
            planner = self.add_planner(connection, conv_id, revision=1)
            self.add_turn(
                connection, conv_id, planner, prompt, suffix="d", revision=1)

            refreshed = sync.refresh_local_changes(connection, DEVICE)
            delta = sync.export_change_batch(
                connection, DEVICE, after_cursor=before)
            full = sync.export_change_batch(connection, DEVICE)
            shadow = connection.execute(
                "SELECT local_id,deleted_at FROM sync_records WHERE "
                "record_type='message' AND public_id=?", ("c" * 32,)
            ).fetchone()
            stored_payloads = " ".join(
                str(row[0] or "") for row in connection.execute(
                    "SELECT payload_json FROM sync_changes WHERE "
                    "record_type='message' AND public_id=?", ("c" * 32,)))

        self.assertGreaterEqual(refreshed["policy_redacted"], 1)
        self.assertIsNone(shadow["local_id"])
        self.assertIsNotNone(shadow["deleted_at"])
        records = [row for row in delta["records"]
                   if row["record_type"] == "message"
                   and row["public_id"] == "c" * 32]
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["payload"])
        self.assertIsNotNone(records[0]["deleted_at"])
        self.assertNotIn(sentinel, json.dumps(full, ensure_ascii=False))
        self.assertNotIn(sentinel, stored_payloads)
