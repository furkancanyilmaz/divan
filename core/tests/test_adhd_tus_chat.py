"""Durable, deterministic main-chat surface for the local TUS planner."""

import json
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app
from test_adhd_tus_planner import catalog_document


class ADHDTUSChatTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self.old_catalog_path = app.TUS_CATALOG_PATH
        self.catalog_path = Path(self._tmp.name) / "catalog-v1.json"
        self.catalog_path.write_text(json.dumps(
            catalog_document(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":")), encoding="utf-8")
        app.TUS_CATALOG_PATH = str(self.catalog_path)
        self.conv_id = self.conversation(therapist="adhd")
        self.revision = 0
        self.serial = 0
        self.prompt = None

    def tearDown(self):
        app.TUS_CATALOG_PATH = self.old_catalog_path
        super().tearDown()

    def chat(self, action, *, conv_id=None, expected_revision=None,
             request_id=None, update=True, **extra):
        self.serial += 1
        payload = {
            "protocol": app.ADHD_TUS_CHAT_PROTOCOL,
            "conv_id": self.conv_id if conv_id is None else conv_id,
            "action": action,
            "expected_revision": (
                self.revision if expected_revision is None else
                expected_revision),
            "request_id": request_id or
            "tus-chat-test-{:08d}".format(self.serial),
        }
        payload.update(extra)
        status, body, headers = self.request(
            "POST", "/api/adhd/tus/chat", payload)
        if status == 200 and update and (
                conv_id is None or conv_id == self.conv_id):
            self.revision = body["revision"]
            self.prompt = body["chat_surface"]["prompt"]
        return status, body, headers, payload

    def enter(self, **extra):
        status, body, _, _ = self.chat("enter", **extra)
        self.assertEqual(status, 200, body)
        return body

    def answer(self, option_id, *, custom_minutes=None, **extra):
        question_id = self.prompt["question_id"]
        fields = {
            "prompt_message_public_id": self.prompt["message_public_id"],
            "question_id": question_id,
            "option_id": option_id,
        }
        if custom_minutes is not None:
            fields["custom_minutes"] = custom_minutes
        fields.update(extra)
        status, body, _, _ = self.chat("answer", **fields)
        self.assertEqual(status, 200, body)
        return body

    def ready_plan(self):
        body = self.enter()
        for question_id, option_id in (
                ("activity", "mixed"),
                ("lesson", "lesson:farmakoloji:test00000001"),
                ("reading_area", "reading-area:test:0001"),
                ("question_area", "question-area:test:0000"),
                ("available_time", "25"),
                ("start_friction", "hard")):
            self.assertEqual(self.prompt["question_id"], question_id)
            body = self.answer(option_id)
        self.assertEqual(body["state"], "plan_ready")
        self.assertEqual(self.prompt["kind"], "plan_ready")
        return body

    def action(self, action, **extra):
        fields = {
            "prompt_message_public_id": self.prompt["message_public_id"],
        }
        fields.update(extra)
        status, body, _, _ = self.chat(action, **fields)
        self.assertEqual(status, 200, body)
        return body

    def counts(self):
        with app.db() as connection:
            return {
                "messages": connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE conv=?",
                    (self.conv_id,)).fetchone()[0],
                "turns": connection.execute(
                    "SELECT COUNT(*) FROM adhd_tus_chat_turns WHERE conv=?",
                    (self.conv_id,)).fetchone()[0],
                "planners": connection.execute(
                    "SELECT COUNT(*) FROM adhd_tus_planners WHERE conv=?",
                    (self.conv_id,)).fetchone()[0],
                "mutations": connection.execute(
                    "SELECT COUNT(*) FROM adhd_mutations WHERE conv=?",
                    (self.conv_id,)).fetchone()[0],
            }

    def test_get_is_read_only_and_enter_is_durable_reusable_idempotent(self):
        before = self.counts()
        status, initial, _ = self.request(
            "GET", "/api/adhd/tus/chat?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, initial)
        self.assertEqual(initial["protocol"], app.ADHD_TUS_CHAT_PROTOCOL)
        self.assertEqual(initial["planner_protocol"], app.ADHD_TUS_PROTOCOL)
        self.assertEqual(initial["allowed_actions"], ["enter"])
        self.assertTrue(initial["chat_surface"]["requires_enter"])
        self.assertIsNone(initial["chat_surface"]["prompt"])
        self.assertEqual(initial["new_messages"], [])
        self.assertEqual(self.counts(), before)

        request_id = "tus-chat-enter-idempotent-0001"
        status, entered, _, original = self.chat(
            "enter", request_id=request_id)
        self.assertEqual(status, 200, entered)
        self.assertEqual(entered["revision"], 1)
        self.assertEqual(entered["state"], "question")
        self.assertEqual(entered["question"]["id"], "activity")
        self.assertEqual(entered["allowed_actions"], ["answer", "cancel"])
        self.assertEqual(len(entered["new_messages"]), 1)
        visible = entered["new_messages"][0]
        self.assertEqual(visible["role"], "assistant")
        self.assertEqual(
            visible["content"], app.ADHD_TUS_QUESTION_LABELS["activity"])
        prompt = entered["chat_surface"]["prompt"]
        self.assertEqual(prompt["message_public_id"], visible["public_id"])
        self.assertEqual(prompt["kind"], "question")
        self.assertEqual(prompt["planner_revision"], 1)
        self.assertEqual(prompt["ledger_revision"], 1)
        self.assertFalse(prompt["safety_cancel_only"])
        self.assertEqual(self.counts(), {
            "messages": 1, "turns": 1, "planners": 1, "mutations": 1,
        })

        # An exact replay returns the originally committed response and does
        # not create a second chat bubble.
        status, duplicate, _ = self.request(
            "POST", "/api/adhd/tus/chat", original)
        self.assertEqual(status, 200, duplicate)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(
            duplicate["new_messages"][0]["public_id"], visible["public_id"])
        self.assertEqual(self.counts(), {
            "messages": 1, "turns": 1, "planners": 1, "mutations": 1,
        })

        # A distinct enter operation reuses the already-current prompt.  This
        # is the process-death/relaunch contract: GET and enter never duplicate
        # a pending question.
        status, reused, _, _ = self.chat("enter")
        self.assertEqual(status, 200, reused)
        self.assertEqual(reused["revision"], 1)
        self.assertEqual(reused["new_messages"], [])
        self.assertEqual(
            reused["chat_surface"]["prompt"]["message_public_id"],
            visible["public_id"])
        persisted = self.counts()
        status, reloaded, _ = self.request(
            "GET", "/api/adhd/tus/chat?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, reloaded)
        self.assertEqual(self.counts(), persisted)
        self.assertEqual(
            reloaded["chat_surface"]["prompt"]["message_public_id"],
            visible["public_id"])

    def test_answer_writes_canonical_user_and_next_assistant_pair_atomically(self):
        entered = self.enter()
        old_prompt = entered["chat_surface"]["prompt"]
        body = self.answer("mixed")
        self.assertEqual(body["revision"], 2)
        self.assertEqual(body["question"]["id"], "lesson")
        self.assertEqual(len(body["new_messages"]), 2)
        self.assertEqual(
            [(item["role"], item["content"])
             for item in body["new_messages"]],
            [("user", "Karma ilerleyelim"),
             ("assistant", app.ADHD_TUS_QUESTION_LABELS["lesson"])],
        )
        with app.db() as connection:
            messages = connection.execute(
                "SELECT id,public_id,role,content,turn_pair_public_id "
                "FROM messages WHERE conv=? ORDER BY id", (self.conv_id,)
            ).fetchall()
            turns = connection.execute(
                "SELECT t.*,p.content AS prompt_content,a.content AS "
                "answer_content FROM adhd_tus_chat_turns t JOIN messages p "
                "ON p.id=t.prompt_message LEFT JOIN messages a "
                "ON a.id=t.answer_message WHERE t.conv=? ORDER BY t.id",
                (self.conv_id,),
            ).fetchall()
        self.assertEqual(len(messages), 3)
        self.assertRegex(str(messages[0]["public_id"]), r"^[0-9a-f]{32}$")
        self.assertEqual(messages[1]["turn_pair_public_id"],
                         messages[2]["turn_pair_public_id"])
        self.assertRegex(
            messages[1]["turn_pair_public_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(turns[0]["status"], "answered")
        self.assertEqual(turns[0]["answer_content"], "Karma ilerleyelim")
        self.assertEqual(turns[0]["provenance"],
                         "deterministic_metadata_v1")
        self.assertEqual(turns[1]["status"], "open")
        self.assertEqual(turns[1]["kind"], "question")
        self.assertEqual(turns[1]["question_id"], "lesson")
        self.assertEqual(turns[1]["prompt_content"],
                         app.ADHD_TUS_QUESTION_LABELS["lesson"])
        self.assertNotEqual(
            old_prompt["message_public_id"],
            body["chat_surface"]["prompt"]["message_public_id"])

    def test_fail_closed_validation_and_stale_requests_have_zero_writes(self):
        body = self.enter()
        prompt_id = body["chat_surface"]["prompt"]["message_public_id"]
        baseline = self.counts()
        base_payload = {
            "protocol": app.ADHD_TUS_CHAT_PROTOCOL,
            "conv_id": self.conv_id,
            "action": "answer",
            "expected_revision": self.revision,
            "request_id": "tus-chat-client-copy-0001",
            "prompt_message_public_id": prompt_id,
            "question_id": "activity",
            "option_id": "mixed",
            "content": "İstemcinin uydurduğu görünür metin",
        }
        status, rejected, _ = self.request(
            "POST", "/api/adhd/tus/chat", base_payload)
        self.assertEqual(status, 400, rejected)
        self.assertEqual(self.counts(), baseline)

        for changes, error_code in (
                ({"request_id": "tus-chat-stale-rev-0001",
                  "expected_revision": 0}, "tus_stale_revision"),
                ({"request_id": "tus-chat-stale-prompt-0001",
                  "prompt_message_public_id": "f" * 32},
                 "tus_chat_prompt_stale"),
                ({"request_id": "tus-chat-wrong-question-0001",
                  "question_id": "lesson"}, "tus_question_mismatch")):
            payload = dict(base_payload)
            payload.pop("content")
            payload.update(changes)
            status, rejected, _ = self.request(
                "POST", "/api/adhd/tus/chat", payload)
            self.assertEqual(status, 409, rejected)
            self.assertEqual(rejected["error_code"], error_code)
            self.assertEqual(self.counts(), baseline)

        # The request id is bound to every normalized field, including the
        # canonical option.  A changed replay is rejected before any write.
        request_id = "tus-chat-bound-replay-0001"
        status, accepted, _, first = self.chat(
            "answer", request_id=request_id,
            prompt_message_public_id=prompt_id, question_id="activity",
            option_id="mixed")
        self.assertEqual(status, 200, accepted)
        committed = self.counts()
        first["option_id"] = "questions"
        status, conflict, _ = self.request(
            "POST", "/api/adhd/tus/chat", first)
        self.assertEqual(status, 409, conflict)
        self.assertEqual(self.counts(), committed)

    def test_user_and_assistant_pair_roll_back_together_on_prompt_failure(self):
        entered = self.enter()
        prompt = entered["chat_surface"]["prompt"]
        baseline = self.counts()
        with mock.patch.object(
                app, "_tus_chat_create_prompt",
                side_effect=app.RequestInputError(
                    "sonraki istem oluşturulamadı", 409,
                    "tus_chat_state_invalid")):
            status, rejected, _, _ = self.chat(
                "answer", update=False,
                prompt_message_public_id=prompt["message_public_id"],
                question_id="activity", option_id="mixed")
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error_code"], "tus_chat_state_invalid")
        self.assertEqual(self.counts(), baseline)
        with app.db() as connection:
            planner = connection.execute(
                "SELECT revision,phase,answers_json FROM adhd_tus_planners "
                "WHERE conv=?", (self.conv_id,)).fetchone()
            turn = connection.execute(
                "SELECT status,answer_message,answered_request_id FROM "
                "adhd_tus_chat_turns WHERE conv=?", (self.conv_id,)
            ).fetchone()
        self.assertEqual(tuple(planner), (1, "activity", "{}"))
        self.assertEqual(tuple(turn), ("open", None, None))

    def test_full_flow_and_lifecycle_use_only_deterministic_chat_bubbles(self):
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("TUS chat must not call a model")), \
                mock.patch.object(
                    app, "provider_request",
                    side_effect=AssertionError(
                        "TUS chat must not build a provider request")):
            ready = self.ready_plan()
            serialized = json.dumps(ready, ensure_ascii=False)
            self.assertNotIn("question_text", serialized)
            self.assertNotIn("sentence_text", serialized)
            self.assertNotIn("RAW-", serialized)
            self.assertIn("Farmakoloji", ready["new_messages"][1]["content"])
            self.assertNotIn("KATALOG-GİZLİ-DERS",
                             ready["new_messages"][1]["content"])

            plan_id = ready["plan"]["id"]
            active = self.action("start", plan_id=plan_id)
            self.assertEqual(active["state"], "active")
            self.assertEqual(active["new_messages"][0]["content"],
                             "Planı başlat")
            self.assertEqual(self.prompt["kind"], "active_step")

            paused = self.action("pause")
            self.assertEqual(paused["state"], "paused")
            self.assertEqual(paused["new_messages"][0]["content"],
                             "Burada duralım")
            self.assertEqual(self.prompt["kind"], "paused")

            resumed = self.action("resume")
            self.assertEqual(resumed["state"], "active")
            self.assertEqual(resumed["new_messages"][0]["content"],
                             "Devam edelim")
            current_step = resumed["plan"]["current_step"]["id"]

            advanced = self.action(
                "complete_step", plan_id=plan_id, step_id=current_step)
            self.assertEqual(advanced["new_messages"][0]["content"],
                             "Bu adımı tamamladım")
            self.assertIn(advanced["state"], ("active", "completed"))

            if advanced["state"] != "completed":
                finished = self.action("finish", plan_id=plan_id)
                self.assertEqual(finished["new_messages"][0]["content"],
                                 "Bugünlük bitirelim")
            else:
                finished = advanced
            self.assertEqual(finished["state"], "completed")
            self.assertEqual(self.prompt["kind"], "completed")
            self.assertEqual(self.prompt["status"], "closed")
            self.assertEqual(finished["allowed_actions"], ["enter"])

            restarted = self.enter()
            self.assertEqual(restarted["state"], "question")
            cancelled = self.action("cancel")
            self.assertEqual(cancelled["state"], "disabled")
            self.assertFalse(cancelled["enabled"])
            self.assertEqual(cancelled["new_messages"][0]["content"],
                             "TUS çalışmasını bırak")
            self.assertEqual(self.prompt["kind"], "cancelled")
            self.assertEqual(self.prompt["status"], "closed")
            self.assertEqual(cancelled["allowed_actions"], ["enter"])

        with app.db() as connection:
            invalid = connection.execute(
                "SELECT COUNT(*) FROM adhd_tus_chat_turns WHERE "
                "kind NOT IN ('question','plan_ready','active_step','paused',"
                "'completed','cancelled') OR provenance<>"
                "'deterministic_metadata_v1'"
            ).fetchone()[0]
            open_count = connection.execute(
                "SELECT COUNT(*) FROM adhd_tus_chat_turns WHERE conv=? "
                "AND status='open'", (self.conv_id,)).fetchone()[0]
        self.assertEqual(invalid, 0)
        self.assertEqual(open_count, 0)

    def test_safety_hold_allows_only_cancel_for_question_and_stale_active_prompt(self):
        entered = self.enter()
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv_id,))
        status, held, _ = self.request(
            "GET", "/api/adhd/tus/chat?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, held)
        self.assertEqual(held["allowed_actions"], ["cancel"])
        prompt = held["chat_surface"]["prompt"]
        self.assertTrue(prompt["safety_cancel_only"])
        self.assertEqual(prompt["planner_revision"], held["revision"])
        self.assertEqual(prompt["ledger_revision"], entered["revision"])
        self.revision = held["revision"]
        self.prompt = prompt
        cancelled = self.action("cancel")
        self.assertEqual(cancelled["state"], "disabled")

        # Recreate an active plan, then reproduce the real safety transition:
        # pausing advances the planner while the visible prompt ledger remains
        # immutable.  Projection authorizes that exact old prompt only for a
        # cancel using the current top-level revision.
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=0 WHERE id=?",
                (self.conv_id,))
        ready = self.ready_plan()
        active = self.action("start", plan_id=ready["plan"]["id"])
        old_prompt = dict(self.prompt)
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv_id,))
            self.assertTrue(app.pause_adhd_tus_plan(
                connection, self.conv_id))
        status, held, _ = self.request(
            "GET", "/api/adhd/tus/chat?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, held)
        self.assertEqual(held["state"], "paused")
        self.assertEqual(held["allowed_actions"], ["cancel"])
        prompt = held["chat_surface"]["prompt"]
        self.assertEqual(prompt["message_public_id"],
                         old_prompt["message_public_id"])
        self.assertTrue(prompt["safety_cancel_only"])
        self.assertEqual(prompt["ledger_revision"],
                         old_prompt["ledger_revision"])
        self.assertEqual(prompt["planner_revision"], held["revision"])
        self.assertNotEqual(prompt["planner_revision"],
                            prompt["ledger_revision"])
        self.revision = held["revision"]
        self.prompt = prompt
        cancelled = self.action(
            "cancel", plan_id=active["plan"]["id"])
        self.assertEqual(cancelled["state"], "disabled")

    def test_busy_normal_chat_rejects_tus_without_partial_writes(self):
        with app.db() as connection:
            user_message = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user','normal mesaj','2026-08-24 10:00')",
                (self.conv_id,),
            ).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'queued','d','d')",
                (self.conv_id,),
            ).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "status,created,updated) VALUES(?,?,?,?,'queued','d','d')",
                ("normal-chat-busy-0001", job_id, self.conv_id,
                 user_message),
            )
        baseline = self.counts()
        status, rejected, _, _ = self.chat("enter", update=False)
        self.assertEqual(status, 409, rejected)
        self.assertEqual(rejected["error_code"], "chat_busy")
        self.assertEqual(self.counts(), baseline)

    def test_scope_archive_end_guest_and_deletion_privacy_boundaries(self):
        for conv_id, expected in (
                (self.conversation(therapist="freud"), 409),
                (self.conversation(therapist="adhd", ended=1), 409)):
            status, _, _, _ = self.chat(
                "enter", conv_id=conv_id, expected_revision=0,
                update=False)
            self.assertEqual(status, expected)

        archived = self.conversation(therapist="adhd")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET archived_at='2026-08-24' "
                "WHERE id=?", (archived,))
        status, _, _, _ = self.chat(
            "enter", conv_id=archived, expected_revision=0, update=False)
        self.assertEqual(status, 409)

        guest = self.conversation(therapist="adhd")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?", (guest,))
        app.set_setting("guest_mode", "1")
        try:
            status, _, _, _ = self.chat(
                "enter", conv_id=guest, expected_revision=0, update=False)
            self.assertEqual(status, 403)
        finally:
            app.set_setting("guest_mode", "0")

        entered = self.enter()
        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200, exported)
        self.assertIn("adhd_tus_chat_turns", exported["data"])
        self.assertEqual(len(exported["data"]["adhd_tus_chat_turns"]), 1)
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            app.delete_conversation_data(connection, self.conv_id)
            for table in (
                    "adhd_tus_chat_turns", "adhd_tus_plan_steps",
                    "adhd_tus_plans", "adhd_tus_planners", "messages"):
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM {} WHERE conv=?".format(table),
                    (self.conv_id,)).fetchone()[0], 0, table)
        self.assertIsNotNone(entered["chat_surface"]["prompt"])
