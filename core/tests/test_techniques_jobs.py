import queue
from unittest import mock

from support import HTTPTestCase, app


class TechniqueLifecycleTests(HTTPTestCase):

    def test_full_technique_lifecycle_and_single_active_constraint(self):
        conv_id = self.conversation(therapist="young")
        method = app.method_records("young")[0]

        status, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose",
             "method_key": method["key"], "intensity": 4})
        self.assertEqual(status, 200)
        run_id = proposed["run"]["id"]
        self.assertEqual(proposed["run"]["status"], "proposed")
        self.assertEqual(proposed["run"]["phase"], "consent")
        self.assertIn("Danışan henüz başlamayı seçmedi; çalışmayı başlatma.",
                     self.system_prompt(conv_id))

        status, _, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose", "method_id": 1})
        self.assertEqual(status, 409)

        status, rejected, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "consent"})
        self.assertEqual(status, 409, rejected)
        self.assertIn("açık onay", rejected["error"])
        self.assertEqual(
            self.row(
                "SELECT status FROM technique_runs WHERE id=?", (run_id,)
            )["status"],
            "proposed",
        )

        status, consented, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "consent",
             "confirmed": True})
        self.assertEqual(status, 200)
        self.assertEqual(consented["run"]["status"], "active")
        self.assertEqual(consented["run"]["phase"], "prepare")

        status, advanced, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "advance",
             "checkpoint_confirmed": True,
             "checkpoint_note": "Hazırlık adımını yaptım."})
        self.assertEqual(status, 200)
        self.assertEqual(advanced["run"]["phase"], "work")
        checkpoint = self.row(
            "SELECT * FROM technique_checkpoints WHERE technique_run=?",
            (run_id,))
        self.assertEqual(checkpoint["from_phase"], "prepare")
        self.assertEqual(checkpoint["to_phase"], "work")
        self.assertEqual(checkpoint["note"], "Hazırlık adımını yaptım.")
        self.assertEqual(checkpoint["user_confirmed"], 1)

        status, paused, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "pause"})
        self.assertEqual(status, 200)
        self.assertEqual(paused["run"]["status"], "paused")

        status, resumed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "resume"})
        self.assertEqual(status, 200)
        self.assertEqual(resumed["run"]["status"], "active")

        status, intense, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "intensity",
             "intensity": 8})
        self.assertEqual(status, 200)
        self.assertEqual(intense["run"]["status"], "paused")
        self.assertEqual(intense["run"]["phase"], "grounding")
        prompt = self.system_prompt(conv_id)
        self.assertIn("şimdiye dönme", prompt)
        self.assertIn("durabileceğini", prompt)

        status, _, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "resume"})
        self.assertEqual(status, 409)
        status, stopped, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "stop"})
        self.assertEqual(status, 200)
        self.assertEqual(stopped["run"]["status"], "stopped")
        self.assertEqual(stopped["run"]["phase"], "end")
        self.assertIsNone(app.current_technique_run(conv_id))

    def test_generic_method_phase_does_not_advance_without_user_checkpoint(self):
        conv_id = self.conversation(therapist="young")
        method = next(
            row for row in app.method_records("young")
            if row["interaction_mode"] == "chat")
        self.assertEqual(method["workflow_kind"], "user_confirmed_checkpoints")
        _, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose",
             "method_key": method["key"], "intensity": 3})
        run_id = proposed["run"]["id"]
        self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "consent",
             "confirmed": True})

        status, body, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "advance"})

        self.assertEqual(status, 409, body)
        self.assertIn("açık doğrulama", body["error"])
        run = self.row("SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual(run["phase"], "prepare")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM technique_checkpoints "
                "WHERE technique_run=?", (run_id,))["n"], 0)

    def test_experiential_technique_cannot_start_when_precheck_is_unsafe(self):
        conv_id = self.conversation(therapist="young")
        status, _, _ = self.request(
            "POST", "/api/session-meta",
            {"conv_id": conv_id, "precheck_done": True,
             "safety_ok": False, "anxiety_start": 9,
             "intensity_limit": 2})
        self.assertEqual(status, 200)

        status, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose", "method_id": 2,
             "intensity": 3})
        self.assertEqual(status, 409)
        self.assertIn("sınır", proposed["error"])

        status, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose", "method_id": 2,
             "intensity": 2})
        self.assertEqual(status, 200)
        status, body, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": proposed["run"]["id"],
             "action": "consent", "confirmed": True})
        self.assertEqual(status, 409)
        self.assertIn("güvenlik", body["error"])
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?",
            (proposed["run"]["id"],))
        self.assertEqual(run["status"], "proposed")

    def test_crisis_pauses_active_technique_in_grounding_phase(self):
        conv_id = self.conversation(therapist="young")
        _, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose", "method_id": 0,
             "intensity": 3})
        self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": proposed["run"]["id"],
             "action": "consent", "confirmed": True})

        status, body, _ = self.request(
            "POST", "/api/chat",
            {"conv_id": conv_id, "message": "Kendime zarar vermek istiyorum"})
        self.assertEqual(status, 200)
        self.assertTrue(body["crisis"])
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?",
            (proposed["run"]["id"],))
        self.assertEqual((run["status"], run["phase"]),
                         ("paused", "grounding"))

    def test_high_intensity_before_consent_does_not_advance_or_complete_work(self):
        conv_id = self.conversation(therapist="young")
        _, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose", "method_id": 0,
             "intensity": 4})
        run_id = proposed["run"]["id"]

        status, updated, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "intensity",
             "intensity": 9})

        self.assertEqual(status, 200)
        self.assertEqual(updated["run"]["intensity_current"], 9)
        self.assertEqual(updated["run"]["status"], "proposed")
        self.assertEqual(updated["run"]["phase"], "consent")
        self.assertIsNone(updated["run"]["consent_at"])
        status, _, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "complete"})
        self.assertEqual(status, 409)


class BackgroundJobTests(HTTPTestCase):

    def test_job_creation_is_idempotent_until_terminal(self):
        conv_id = self.conversation()
        first = app.create_job("session_postprocess", conv_id)
        second = app.create_job("session_postprocess", conv_id)
        self.assertEqual(first, second)

        app.update_job(first, "succeeded", "tamamlandı", 100, "")
        third = app.create_job("session_postprocess", conv_id)
        self.assertNotEqual(first, third)

    def test_postprocess_job_reaches_success_and_missing_conversation_fails(self):
        short_conv = self.conversation()
        job_id = app.create_job("session_postprocess", short_conv)
        app.postprocess_ended_session(short_conv, job_id)
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["progress"], 100)
        self.assertEqual(job["stage"], "tamamlandı")

        missing_job = app.create_job("session_postprocess", 99999)
        with mock.patch("builtins.print"):
            app.postprocess_ended_session(99999, missing_job)
        failed = self.row("SELECT * FROM jobs WHERE id=?", (missing_job,))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "ValueError")

    def test_resume_and_retry_queue_jobs_without_starting_real_worker(self):
        conv_id = self.conversation()
        with app.db() as conn:
            running = conn.execute(
                "INSERT INTO jobs(kind,conv,status,stage,progress,created,updated)"
                " VALUES('session_postprocess',?,'running','x',20,'d','d')",
                (conv_id,)).lastrowid
        app.resume_jobs()
        resumed = self.row("SELECT * FROM jobs WHERE id=?", (running,))
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(resumed["stage"], "yeniden sırada")
        self.assertEqual(self.queued_job_id(), running)
        app.JOB_QUEUE.task_done()

        app.update_job(running, "failed", "hata", 30, "RuntimeError")
        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": running})
        self.assertEqual(status, 200)
        self.assertEqual(body["job_id"], running)
        retried = self.row("SELECT * FROM jobs WHERE id=?", (running,))
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(retried["progress"], 0)
        self.assertEqual(retried["error_code"], "")
        self.assertEqual(self.queued_job_id(), running)

    def test_end_returns_job_immediately_and_stops_active_technique(self):
        conv_id = self.conversation(therapist="young")
        _, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose", "method_id": 0})
        with mock.patch.object(
                app, "ds_complete",
                return_value="Bugünlük burada kalalım."), mock.patch.object(
                    app, "now", return_value="2026-07-28 14:37"):
            status, body, _ = self.request(
                "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(status, 200)
        self.assertTrue(body["processing"])
        self.assertEqual(body["closing_created"], "2026-07-28 14:37")
        self.assertIsInstance(body["job_id"], int)
        closing_row = self.row(
            "SELECT role,content,created FROM messages WHERE conv=? "
            "ORDER BY id DESC LIMIT 1", (conv_id,))
        self.assertEqual(closing_row["role"], "assistant")
        self.assertEqual(closing_row["content"], body["closing"])
        self.assertEqual(closing_row["created"], body["closing_created"])
        conv = self.conversation_row(conv_id)
        self.assertEqual(conv["ended"], 1)
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?",
            (proposed["run"]["id"],))
        self.assertEqual((run["status"], run["phase"]), ("stopped", "end"))
        job = self.row("SELECT * FROM jobs WHERE id=?", (body["job_id"],))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.queued_job_id(), body["job_id"])

        status, _, _ = self.request(
            "POST", "/api/end", {"conv_id": conv_id})
        self.assertEqual(status, 400)
