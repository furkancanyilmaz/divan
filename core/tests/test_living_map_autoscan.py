import json
import threading
import time
from unittest import mock

from support import HTTPTestCase, app


class _ProviderStream:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class LivingMapAutoscanTests(HTTPTestCase):
    stamp = "2026-08-17 10:00"

    def fresh_conversation(self, **kwargs):
        conv_id = self.conversation(**kwargs)
        with app.db() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?", (conv_id,)
            ).fetchone()
            if app.living_map_autoscan_conversation_eligible(conv):
                app.initialize_living_map_autoscan_state(conn, conv_id)
        return conv_id

    def completed_turn(self, conv_id, content, *, safety=False):
        with app.db() as conn:
            user_id = conn.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'user',?,?,'completed')",
                (conv_id, content, self.stamp),
            ).lastrowid
            assistant_id = conn.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',?,"
                "'completed')", (conv_id, self.stamp),
            ).lastrowid
            job_id = conn.execute(
                "INSERT INTO jobs(kind,conv,status,stage,progress,created,"
                "updated) VALUES('chat_response',?,'succeeded','tamamlandı',"
                "100,?,?)", (conv_id, self.stamp, self.stamp),
            ).lastrowid
            conn.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,provider,model,created,updated) "
                "VALUES(?,?,?,?,?,'completed','deepseek','test-model',?,?)",
                ("autoscan-chat-{:012d}".format(user_id), job_id, conv_id,
                 user_id, assistant_id, self.stamp, self.stamp),
            )
            if safety:
                conn.execute(
                    "INSERT INTO safety_events(conv,source_message,kind,"
                    "detector_context,created) VALUES(?,?,'crisis',"
                    "'conversation',?)", (conv_id, user_id, self.stamp))
        return user_id

    def candidate_json(self, source_ids, *, existing_claim_id=None,
                       title="Geri çekilme döngüsü"):
        return json.dumps({"insights": [{
            "existing_claim_id": existing_claim_id,
            "claim_type": "pattern",
            "title": title,
            "statement": "Eleştiri beklediğimde geri çekilebilirim",
            "trigger": "Eleştiri beklentisi",
            "experience": "Gerilim",
            "response": "Sessizleşme",
            "short_term_effect": "Çatışmadan korunma",
            "long_term_effect": "İhtiyacı anlatamama",
            "need": "Güvenle duyulma",
            "context": "İş ortamı",
            "counterexample": "",
            "supporting_message_ids": list(source_ids),
            "counterexample_message_ids": [],
        }]}, ensure_ascii=False)

    def due_and_claim(self, job_id):
        with app.db() as conn:
            conv_id = conn.execute(
                "SELECT conv FROM jobs WHERE id=?", (job_id,)
            ).fetchone()["conv"]
            conn.execute(
                "UPDATE living_map_auto_state SET next_attempt_at=0 "
                "WHERE conv=?", (conv_id,))
        return app.claim_queued_job(job_id)

    @staticmethod
    def prompt_source_ids(messages):
        payload = json.loads(messages[-1]["content"].split("\n\n", 1)[1])
        return [row["id"] for row in payload["USER_MESSAGES"]]

    def test_fresh_conversation_analyzes_each_completed_turn_separately(self):
        conv_id = self.fresh_conversation()
        first = self.completed_turn(conv_id, "yeni-bir")
        job_id, created, _ = app.create_living_map_autoscan_job(first)
        self.assertTrue(created)
        second = self.completed_turn(conv_id, "yeni-iki")
        self.assertEqual(app.create_living_map_autoscan_job(second)[0], job_id)
        third = self.completed_turn(conv_id, "yeni-üç")
        self.assertEqual(app.create_living_map_autoscan_job(third)[0], job_id)

        captured = []

        def complete(messages, **_kwargs):
            captured.append(self.prompt_source_ids(messages))
            return self.candidate_json(captured[-1])

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            for _ in range(3):
                self.assertIsNotNone(self.due_and_claim(job_id))
                app.run_living_map_autoscan_job(job_id)

        self.assertEqual(captured, [[first], [second], [third]])
        state = self.row(
            "SELECT * FROM living_map_auto_state WHERE conv=?", (conv_id,))
        self.assertEqual(state["through_message_id"], third)
        self.assertEqual(state["target_message_id"], third)
        self.assertEqual(state["status"], "succeeded")
        self.assertIsNone(self.row(
            "SELECT * FROM insight_generation_runs WHERE conv=?", (conv_id,)))
        evidence = self.rows(
            "SELECT review_status FROM psych_claim_evidence")
        self.assertTrue(evidence)
        self.assertEqual({row["review_status"] for row in evidence}, {"pending"})

    def test_auto_persists_only_one_when_model_returns_three_candidates(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        base = json.loads(self.candidate_json(ids))["insights"][0]
        payload = {"insights": [
            {**base, "title": "Aday {}".format(index)}
            for index in range(1, 4)]}
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": [
                    {**item, "supporting_message_ids": [ids[0]]}
                    for item in payload["insights"]]},
                    ensure_ascii=False)) as call:
            app.run_living_map_autoscan_job(job_id)
        call.assert_called_once()
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM psych_claims")["n"], 1)
        self.assertEqual(
            self.row("SELECT title FROM psych_claims")["title"], "Aday 1")

    def test_legacy_enrollment_never_sends_old_history(self):
        conv_id = self.conversation()
        old_ids = [
            self.completed_turn(conv_id, "ESKI-GECMIS-{}".format(index))
            for index in range(3)]
        with app.db() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?", (conv_id,)
            ).fetchone()
            state = app.enroll_legacy_living_map_autoscan_state(conn, conv)
        self.assertEqual(state["through_message_id"], old_ids[-1])

        new_ids = []
        for index in range(3):
            new_ids.append(self.completed_turn(
                conv_id, "YENI-TUR-{}".format(index)))
            result = app.create_living_map_autoscan_job(new_ids[-1])
            if index == 0:
                self.assertIsNotNone(result[0])
        job_id = result[0]
        captured = []

        def complete(messages, **_kwargs):
            captured.append(messages[-1]["content"])
            return self.candidate_json(self.prompt_source_ids(messages))

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            for _ in range(3):
                self.assertIsNotNone(self.due_and_claim(job_id))
                app.run_living_map_autoscan_job(job_id)

        self.assertEqual(len(captured), 3)
        self.assertTrue(all("ESKI-GECMIS" not in item for item in captured))
        self.assertTrue(all("YENI-TUR" in item for item in captured))
        self.assertEqual(
            self.row("SELECT through_message_id FROM living_map_auto_state "
                     "WHERE conv=?", (conv_id,))["through_message_id"],
            new_ids[-1])

    def test_unfinished_next_user_is_outside_target_snapshot(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tamam-0")]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        pending, _ = app.begin_chat_request(
            conv_id, "HENUZ-YANITI-YOK",
            request_id="autoscan-pending-turn-0001")
        self.assertIsNotNone(self.due_and_claim(job_id))
        captured = []

        def complete(messages, **_kwargs):
            captured.append(messages[-1]["content"])
            return json.dumps({"insights": []})

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            app.run_living_map_autoscan_job(job_id)

        self.assertNotIn("HENUZ-YANITI-YOK", captured[0])
        self.assertEqual(
            self.row("SELECT through_message_id FROM living_map_auto_state "
                     "WHERE conv=?", (conv_id,))["through_message_id"],
            ids[-1])
        self.assertEqual(pending["status"], "queued")

    def test_running_job_coalesces_new_turn_and_requeues_same_id(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-0")]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        fourth = self.completed_turn(conv_id, "tur-dört")
        same_job, created, _ = app.create_living_map_autoscan_job(fourth)
        self.assertEqual(same_job, job_id)
        self.assertFalse(created)

        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})), \
                mock.patch.object(
                    app, "LIVING_MAP_AUTOSCAN_DEBOUNCE_SECONDS", 0):
            result = app.generate_living_map_candidates(
                conv_id, provider_id="deepseek", model_id="test-model",
                source_after_message_id=0,
                source_through_message_id=ids[-1], candidate_limit=1,
                auto_job_id=job_id, raise_errors=True)

        self.assertTrue(result["requeue"])
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        state = self.row(
            "SELECT * FROM living_map_auto_state WHERE conv=?", (conv_id,))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(state["through_message_id"], ids[-1])
        self.assertEqual(state["target_message_id"], fourth)
        self.assertEqual(len(self.rows(
            "SELECT id FROM jobs WHERE kind=? AND conv=?",
            (app.LIVING_MAP_AUTOSCAN_JOB_KIND, conv_id))), 1)

        self.assertIsNotNone(self.due_and_claim(job_id))
        captured = []

        def complete(messages, **_kwargs):
            captured.append(self.prompt_source_ids(messages))
            return json.dumps({"insights": []})

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            app.run_living_map_autoscan_job(job_id)
        self.assertEqual(captured, [[fourth]])
        self.assertEqual(
            self.row("SELECT through_message_id FROM living_map_auto_state "
                     "WHERE conv=?", (conv_id,))["through_message_id"],
            fourth)

    def test_completion_after_terminal_scan_creates_a_new_job(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-0")]
        first_job = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(first_job))
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})):
            app.run_living_map_autoscan_job(first_job)
        fourth = self.completed_turn(conv_id, "sonraki-tur")
        second_job, created, _ = app.create_living_map_autoscan_job(fourth)
        self.assertTrue(created)
        self.assertNotEqual(first_job, second_job)

    def test_active_claim_gets_pending_evidence_without_high_water_change(self):
        conv_id = self.fresh_conversation()
        old_source = self.completed_turn(conv_id, "önceki kaynak")
        with app.db() as conn:
            observation = conn.execute(
                "INSERT INTO psych_observations(conv,source_message,therapist,"
                "dimension,content,source_created,created) VALUES(?,?,"
                "'freud','user_report','önceki kaynak',?,?)",
                (conv_id, old_source, self.stamp, self.stamp),
            ).lastrowid
            claim_id = conn.execute(
                "INSERT INTO psych_claims(public_id,source_conv,therapist,"
                "lens,claim_type,title,statement,status,scope,first_seen,"
                "last_seen,created,updated) VALUES('auto-existing',?,"
                "'freud','neutral','pattern','Eski onaylı not','Eski onaylı "
                "not','confirmed','therapist',?,?,?,?)",
                (conv_id, self.stamp, self.stamp, self.stamp, self.stamp),
            ).lastrowid
            evidence_id = conn.execute(
                "INSERT INTO psych_claim_evidence(claim,observation,relation,"
                "review_status,created) VALUES(?,?,'supports','accepted',?)",
                (claim_id, observation, self.stamp),
            ).lastrowid
            conn.execute(
                "UPDATE psych_claims SET reviewed_evidence_id=?,reviewed_at=? "
                "WHERE id=?", (evidence_id, self.stamp, claim_id))
            conn.execute(
                "UPDATE living_map_auto_state SET through_message_id=?,"
                "target_message_id=? WHERE conv=?",
                (old_source, old_source, conv_id))
        new_ids = [self.completed_turn(conv_id, "yeni-0")]
        target = new_ids[-1]
        job_id = app.create_living_map_autoscan_job(target)[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.candidate_json(
                    new_ids, existing_claim_id=claim_id)):
            app.run_living_map_autoscan_job(job_id)
        claim = self.row(
            "SELECT * FROM psych_claims WHERE id=?", (claim_id,))
        self.assertEqual(claim["reviewed_evidence_id"], evidence_id)
        pending = self.rows(
            "SELECT review_status FROM psych_claim_evidence WHERE claim=? "
            "AND id>?", (claim_id, evidence_id))
        self.assertTrue(pending)
        self.assertEqual({row["review_status"] for row in pending}, {"pending"})
        context = app.context_living_map_claims(
            self.conversation_row(conv_id))
        self.assertEqual(context[0]["support_count"], 1)

    def test_generated_candidate_enters_therapy_prompt_only_after_review(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-0")]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.candidate_json(ids)):
            app.run_living_map_autoscan_job(job_id)
        claim = self.row("SELECT * FROM psych_claims")
        self.assertEqual(claim["status"], "candidate")
        self.assertNotIn(
            claim["statement"], self.system_prompt(conv_id))

        reviewed = app.review_living_map_claim({
            "claim_id": claim["id"], "action": "confirm"})
        self.assertEqual(reviewed["claim"]["status"], "confirmed")
        self.assertIn(claim["statement"], self.system_prompt(conv_id))

    def test_due_guard_and_restart_reconstruct_queued_and_waiting_jobs(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNone(app.claim_queued_job(job_id))
        future = time.time() + 90
        with app.db() as conn:
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            conn.execute(
                "UPDATE living_map_auto_state SET status='running',"
                "next_attempt_at=NULL WHERE conv=?", (conv_id,))
        scheduled = []
        with mock.patch.object(
                app, "recover_stale_chat_requests", return_value={}), \
                mock.patch.object(
                    app, "recover_living_map_autoscan_triggers",
                    return_value=0), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan_job",
                    side_effect=lambda jid, _generation, delay=0:
                    scheduled.append((jid, delay))):
            app.resume_jobs()
        self.assertEqual(scheduled[0][0], job_id)
        self.assertGreater(scheduled[0][1], 0)
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                "status"], "queued")

        with app.db() as conn:
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (job_id,))
            conn.execute(
                "UPDATE living_map_auto_state SET status='waiting_provider',"
                "next_attempt_at=? WHERE conv=?", (future, conv_id))
        scheduled.clear()
        with mock.patch.object(
                app, "recover_stale_chat_requests", return_value={}), \
                mock.patch.object(
                    app, "recover_living_map_autoscan_triggers",
                    return_value=0), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan_job",
                    side_effect=lambda jid, _generation, delay=0:
                    scheduled.append((jid, delay))):
            app.resume_jobs()
        self.assertEqual(scheduled[0][0], job_id)
        self.assertGreater(scheduled[0][1], 80)

        with app.db() as conn:
            conn.execute(
                "UPDATE living_map_auto_state SET next_attempt_at=0 "
                "WHERE conv=?", (conv_id,))
        scheduled.clear()
        with mock.patch.object(
                app, "recover_stale_chat_requests", return_value={}), \
                mock.patch.object(
                    app, "recover_living_map_autoscan_triggers",
                    return_value=0), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan_job",
                    side_effect=lambda jid, _generation, delay=0:
                    scheduled.append((jid, delay))):
            app.resume_jobs()
        self.assertEqual(scheduled[0][0], job_id)
        self.assertGreater(scheduled[0][1], 0)
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                "status"], "waiting_provider")

    def test_ineligible_and_safety_conversations_never_create_auto_job(self):
        cases = [
            self.conversation(mode="ders"),
            self.conversation(submode="supervizyon"),
            self.conversation(submode="konsey"),
            self.conversation(ended=1),
            self.conversation(
                mode="terapi", therapist=next(iter(app.PHILOSOPHERS))),
        ]
        archived = self.conversation()
        guest = self.conversation()
        held = self.conversation()
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                (self.stamp, archived))
            conn.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?", (guest,))
            conn.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?", (held,))
        cases.extend([archived, guest, held])
        for conv_id in cases:
            target = self.completed_turn(conv_id, "kapsam dışı")
            self.assertIsNone(app.create_living_map_autoscan_job(target)[0])
        safe_conv = self.fresh_conversation()
        safe_ids = [self.completed_turn(
            safe_conv, "güvenlik", safety=True) for _ in range(3)]
        self.assertIsNone(app.create_living_map_autoscan_job(safe_ids[-1])[0])

    def test_successful_chat_hook_only_runs_after_normal_completion(self):
        conv_id = self.fresh_conversation()
        row, _ = app.begin_chat_request(
            conv_id, "normal yanıt",
            request_id="autoscan-normal-hook-0001")
        scheduled = []

        def delta(_event, raw, _provider):
            return ("done", "") if raw == "done" else ("text", "yanıt")

        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False})), \
                mock.patch.object(
                    app, "open_provider_url", return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", return_value=iter([
                        ("message", "text"), ("message", "done")])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan",
                    side_effect=scheduled.append), \
                mock.patch.object(app.threading, "Thread"):
            result = app.run_chat_request(
                row["request_id"], automatic_retries=False)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(scheduled, [row["user_message"]])

        failed, _ = app.begin_chat_request(
            conv_id, "başarısız yanıt",
            request_id="autoscan-failed-hook-0001")
        scheduled.clear()
        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False})), \
                mock.patch.object(
                    app, "open_provider_url",
                    side_effect=app.ProviderError("auth_failed", "reddedildi")), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan",
                    side_effect=scheduled.append):
            app.run_chat_request(
                failed["request_id"], automatic_retries=False)
        self.assertEqual(scheduled, [])

    def test_deterministic_safety_completion_never_schedules_autoscan(self):
        conv_id = self.fresh_conversation()
        row, _ = app.begin_chat_request(
            conv_id, "güvenlik kapsamına giren mesaj",
            request_id="autoscan-safety-hook-0001")
        with mock.patch.object(
                app, "schedule_living_map_autoscan") as schedule:
            completed, _ = app.complete_safety_chat_request(
                row["request_id"], {"message": "Güvenlik yanıtı"})
        self.assertEqual(completed["status"], "completed")
        schedule.assert_not_called()
        self.assertIsNone(app.create_living_map_autoscan_job(
            row["user_message"])[0])

    def test_status_export_and_delete_forget_auto_state(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        status, body, _ = self.request(
            "GET", "/api/living-map/auto-status?conv_id={}".format(conv_id))
        self.assertEqual(status, 200)
        self.assertTrue(body["processing"])
        self.assertEqual(body["target_message_id"], ids[-1])
        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200)
        self.assertEqual(
            exported["data"]["living_map_auto_state"][0]["conv"], conv_id)
        status, deleted, _ = self.request(
            "POST", "/api/delete", {"id": conv_id})
        self.assertEqual(status, 200, deleted)
        self.assertIsNone(self.row(
            "SELECT 1 FROM living_map_auto_state WHERE conv=?", (conv_id,)))
        self.assertIsNone(self.row("SELECT 1 FROM jobs WHERE id=?", (job_id,)))

    def test_local_unavailable_waits_without_advancing_and_coalesces(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        with app.db() as conn:
            conn.execute(
                "UPDATE jobs SET provider='lmstudio',model='local-model' "
                "WHERE id=?", (job_id,))
        self.assertIsNotNone(self.due_and_claim(job_id))
        scheduled = []
        with mock.patch.object(
                app, "generate_living_map_candidates",
                side_effect=app.ProviderError(
                    "local_unavailable", "yerel model kapalı")), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan_job",
                    side_effect=lambda jid, _generation, delay=0:
                    scheduled.append((jid, delay))):
            app.run_living_map_autoscan_job(job_id)
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        state = self.row(
            "SELECT * FROM living_map_auto_state WHERE conv=?", (conv_id,))
        self.assertEqual(job["status"], "waiting_provider")
        self.assertEqual(state["through_message_id"], 0)
        self.assertTrue(scheduled)

        fourth = self.completed_turn(conv_id, "yerel beklerken yeni tur")
        same_job, created, _ = app.create_living_map_autoscan_job(fourth)
        self.assertEqual(same_job, job_id)
        self.assertFalse(created)
        self.assertEqual(
            self.row("SELECT target_message_id FROM living_map_auto_state "
                     "WHERE conv=?", (conv_id,))["target_message_id"], fourth)

    def test_job_persists_only_non_secret_provider_snapshot(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        with mock.patch.object(
                app, "_new_postprocess_provider_snapshot",
                return_value=("deepseek", "pinned-model")):
            job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        job = dict(self.row("SELECT * FROM jobs WHERE id=?", (job_id,)))
        self.assertEqual(job["provider"], "deepseek")
        self.assertEqual(job["model"], "pinned-model")
        self.assertFalse(any(
            token in json.dumps(job, ensure_ascii=False).lower()
            for token in ("api_key", "sk-proj", "secret", "base_url")))
        with mock.patch.object(
                app, "_new_postprocess_provider_snapshot",
                return_value=("openai", "different-model")):
            claimed = app.claim_postprocess_provider_snapshot(job_id)
        self.assertEqual(claimed, ("deepseek", "pinned-model"))

    def test_cloud_retry_is_bounded_and_next_turn_can_create_new_job(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        for attempt in range(app.LIVING_MAP_AUTOSCAN_MAX_ATTEMPTS):
            self.assertIsNotNone(self.due_and_claim(job_id))
            with mock.patch.object(
                    app, "generate_living_map_candidates",
                    side_effect=app.ProviderError(
                        "provider_timeout", "zaman aşımı")), \
                    mock.patch.object(
                        app, "schedule_living_map_autoscan_job"):
                app.run_living_map_autoscan_job(job_id)
            if attempt < app.LIVING_MAP_AUTOSCAN_MAX_ATTEMPTS - 1:
                self.assertEqual(
                    self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                        "status"], "queued")
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                "status"], "failed")
        self.assertEqual(
            self.row("SELECT through_message_id FROM living_map_auto_state "
                     "WHERE conv=?", (conv_id,))["through_message_id"], 0)
        fourth = self.completed_turn(conv_id, "başarısızlıktan sonraki tur")
        new_job, created, _ = app.create_living_map_autoscan_job(fourth)
        self.assertTrue(created)
        self.assertNotEqual(new_job, job_id)

    def test_restart_recovers_completion_that_crashed_before_scheduler(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        recovered = []
        with mock.patch.object(
                app, "schedule_living_map_autoscan",
                side_effect=recovered.append):
            count = app.recover_living_map_autoscan_triggers()
        self.assertEqual(count, 1)
        self.assertEqual(recovered, [ids[-1]])

    def test_empty_stale_window_requeues_without_skipping_newer_sources(self):
        conv_id = self.fresh_conversation()
        stale = [self.completed_turn(conv_id, "eski-{}".format(i))
                 for i in range(3)]
        job_id = app.create_living_map_autoscan_job(stale[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        newer = [self.completed_turn(conv_id, "yeni-{}".format(i))
                 for i in range(3)]
        with app.db() as conn:
            conn.execute(
                "DELETE FROM chat_requests WHERE user_message IN (?,?,?)",
                stale)
        scheduled = []
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("boş pencere model çağırmamalı")), \
                mock.patch.object(
                    app, "schedule_living_map_autoscan_job",
                    side_effect=lambda jid, _generation, delay=0:
                    scheduled.append((jid, delay))):
            app.run_living_map_autoscan_job(job_id)
        state = self.row(
            "SELECT * FROM living_map_auto_state WHERE conv=?", (conv_id,))
        self.assertEqual(state["through_message_id"], stale[-1])
        self.assertEqual(state["target_message_id"], newer[-1])
        self.assertEqual(state["status"], "queued")
        self.assertEqual(scheduled[0][0], job_id)

        self.assertIsNotNone(self.due_and_claim(job_id))
        captured = []

        def complete(messages, **_kwargs):
            captured.append(self.prompt_source_ids(messages))
            return json.dumps({"insights": []})

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            app.run_living_map_autoscan_job(job_id)
        self.assertEqual(captured, [[newer[0]]])
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                "status"], "queued")

    def test_legacy_whole_coverage_does_not_mask_turn_ledger(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-0")]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        app.LIVING_MAP_GENERATION_LOCK.acquire()
        errors = []

        def run_auto():
            try:
                app.run_living_map_autoscan_job(job_id)
            except Exception as exc:  # pragma: no cover - diagnostic guard
                errors.append(exc)

        worker = threading.Thread(target=run_auto)
        try:
            with mock.patch.object(
                    app, "ds_complete",
                    return_value=json.dumps({"insights": []})) as call:
                worker.start()
                deadline = time.time() + 2
                while time.time() < deadline:
                    state = self.row(
                        "SELECT status FROM living_map_auto_state "
                        "WHERE conv=?", (conv_id,))
                    if state and state["status"] == "running":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("otomatik iş üretim kilidine ulaşmadı")
                with app.db() as conn:
                    conn.execute(
                        "INSERT INTO insight_generation_runs("
                        "conv,status,candidate_count,through_message_id,"
                        "error_code,created,finished,updated) "
                        "VALUES(?,'succeeded',0,?,'',?,?,?)",
                        (conv_id, ids[-1], self.stamp, self.stamp,
                         self.stamp))
                app.LIVING_MAP_GENERATION_LOCK.release()
                worker.join(2)
                call.assert_called_once()
        finally:
            if app.LIVING_MAP_GENERATION_LOCK.locked():
                app.LIVING_MAP_GENERATION_LOCK.release()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                "status"], "succeeded")
        self.assertEqual(
            self.row("SELECT through_message_id FROM living_map_auto_state "
                     "WHERE conv=?", (conv_id,))["through_message_id"],
            ids[-1])

    def test_manual_whole_success_does_not_advance_turn_cursor(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})) as manual_call:
            result = app.generate_living_map_candidates(
                conv_id, force=True)
        self.assertEqual(result["status"], "succeeded")
        manual_call.assert_called_once()
        state = self.row(
            "SELECT * FROM living_map_auto_state WHERE conv=?", (conv_id,))
        self.assertEqual(state["through_message_id"], 0)
        self.assertEqual(state["target_message_id"], ids[-1])

        self.assertIsNotNone(self.due_and_claim(job_id))
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})) as call:
            app.run_living_map_autoscan_job(job_id)
        call.assert_called_once()
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))[
                "status"], "queued")

        legacy_id = self.conversation()
        for index in range(3):
            self.completed_turn(legacy_id, "legacy-{}".format(index))
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})):
            app.generate_living_map_candidates(legacy_id, force=True)
        self.assertIsNone(self.row(
            "SELECT 1 FROM living_map_auto_state WHERE conv=?", (legacy_id,)))

    def test_delete_while_provider_is_blocked_cannot_restore_derived_rows(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "SILINECEK-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        entered = threading.Event()
        release = threading.Event()

        def complete(_messages, **_kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.candidate_json(ids)

        worker = threading.Thread(
            target=app.run_living_map_autoscan_job, args=(job_id,))
        with mock.patch.object(app, "ds_complete", side_effect=complete):
            worker.start()
            self.assertTrue(entered.wait(2))
            status, body, _ = self.request(
                "POST", "/api/delete", {"id": conv_id})
            self.assertEqual(status, 200, body)
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        for table in (
                "conversations", "messages", "jobs",
                "living_map_auto_state", "psych_claims",
                "psych_observations", "psych_claim_evidence",
                "psych_claim_history"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM " + table)["n"], 0, table)
        with app.db() as conn:
            self.assertEqual(conn.execute(
                "PRAGMA foreign_key_check").fetchall(), [])

    def test_timer_generation_replacement_and_stale_callback_identity(self):
        created = []

        class FakeTimer:
            def __init__(self, delay, callback, args=()):
                self.delay = delay
                self.callback = callback
                self.args = args
                self.cancelled = False
                self.divan_generation = None
                created.append(self)

            def start(self):
                return None

            def cancel(self):
                self.cancelled = True

            def is_alive(self):
                return not self.cancelled

        with mock.patch.object(app.threading, "Timer", FakeTimer):
            app.schedule_living_map_autoscan_job(71, generation=1, delay=10)
            old_timer = created[-1]
            app.schedule_living_map_autoscan_job(71, generation=2, delay=10)
            new_timer = created[-1]
        self.assertIsNot(old_timer, new_timer)
        self.assertTrue(old_timer.cancelled)
        self.assertIs(app.LIVING_MAP_AUTOSCAN_TIMERS[71], new_timer)
        with mock.patch.object(
                app.threading, "current_thread", return_value=old_timer):
            app._living_map_autoscan_timer_fired(71, 1)
        self.assertIs(app.LIVING_MAP_AUTOSCAN_TIMERS[71], new_timer)
        with mock.patch.object(app, "enqueue_job") as enqueue:
            app.schedule_living_map_autoscan_job(
                71, generation=2, delay=0)
        self.assertTrue(new_timer.cancelled)
        self.assertNotIn(71, app.LIVING_MAP_AUTOSCAN_TIMERS)
        enqueue.assert_called_once_with(71, 2)

    def test_delete_all_forgets_auto_cursor_job_and_pending_graph(self):
        conv_id = self.fresh_conversation()
        ids = [self.completed_turn(conv_id, "tur-{}".format(i))
               for i in range(3)]
        job_id = app.create_living_map_autoscan_job(ids[-1])[0]
        self.assertIsNotNone(self.due_and_claim(job_id))
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.candidate_json(ids)):
            app.run_living_map_autoscan_job(job_id)
        status, body, _ = self.request(
            "POST", "/api/delete-all", {"confirm": "TÜM VERİLERİ SİL"})
        self.assertEqual(status, 200, body)
        for table in (
                "living_map_auto_state", "jobs", "psych_claims",
                "psych_observations", "psych_claim_evidence",
                "psych_claim_history", "conversations", "messages"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM " + table)["n"], 0, table)

    def test_manual_generation_keeps_three_call_budget(self):
        conv_id = self.conversation()
        with app.db() as conn:
            source_ids = [conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user',?,?)",
                (conv_id, "manuel-{}".format(index), self.stamp),
            ).lastrowid for index in range(3)]
        calls = []

        def complete(_messages, **_kwargs):
            calls.append(len(calls))
            return self.candidate_json(
                source_ids, title="Manuel aday {}".format(len(calls)))

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            result = app.generate_living_map_candidates(conv_id, force=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(calls), app.LIVING_MAP_CANDIDATE_LIMIT)
        self.assertEqual(result["candidate_count"], 3)

    def test_init_db_does_not_enroll_legacy_history_or_mark_backfill_covered(self):
        conv_id = self.conversation()
        for index in range(3):
            self.completed_turn(conv_id, "legacy-{}".format(index))
        with app.db() as conn:
            conn.execute("DROP TABLE living_map_auto_state")
        app.init_db()
        app.init_db()
        self.assertIsNone(self.row(
            "SELECT * FROM living_map_auto_state WHERE conv=?", (conv_id,)))
        with app.db() as conn:
            analysis = app.living_map_analysis_status(conn)
        self.assertEqual(analysis["remaining_count"], 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
