import threading
from pathlib import Path

from support import HTTPTestCase, app


class JobRetryRoutingTests(HTTPTestCase):

    def fail_chat(self, conv_id, request_id):
        row, _ = app.begin_chat_request(
            conv_id, "Kalıcı kullanıcı mesajı", request_id=request_id)
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='failed',"
                "partial_content='yarım',error_code='offline',"
                "finished='2026-07-30 10:01' WHERE request_id=?",
                (request_id,))
            conn.execute(
                "UPDATE jobs SET status='failed',stage='yanıt alınamadı',"
                "progress=100,error_code='offline',"
                "finished='2026-07-30 10:01' WHERE id=?",
                (row["job"],))
        return row

    def test_job_retry_routes_chat_through_durable_request_once(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("deepseek_model", "deepseek-pinned-a")
        row = self.fail_chat(conv_id, "chat-job-route-0001")
        app.set_setting("llm_provider", "openai")
        app.set_setting("openai_model", "gpt-later-b")

        status, first, _ = self.request(
            "POST", "/api/job/retry", {"id": row["job"]})
        status_again, second, _ = self.request(
            "POST", "/api/job/retry", {"job_id": row["job"]})

        self.assertEqual(status, 200)
        self.assertTrue(first["queued"])
        self.assertEqual(first["kind"], "chat_response")
        self.assertEqual(first["request_id"], row["request_id"])
        self.assertEqual(status_again, 200)
        self.assertFalse(second["queued"])
        self.assertEqual(second["status"], "queued")
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        job = self.row("SELECT * FROM jobs WHERE id=?", (row["job"],))
        self.assertEqual(request["status"], "queued")
        self.assertEqual(request["partial_content"], "")
        self.assertEqual(
            (request["provider"], request["model"]),
            ("deepseek", "deepseek-pinned-a"))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(app.JOB_QUEUE.qsize(), 1)
        self.assertEqual(self.queued_job_id(), row["job"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            1)

    def test_chat_retry_rejects_closed_or_archived_conversation(self):
        for suffix, update in (
                ("closed", "ended=1"),
                ("archived", "archived_at='2026-07-30 10:02'")):
            with self.subTest(state=suffix):
                conv_id = self.conversation(title=suffix)
                row = self.fail_chat(
                    conv_id, "chat-job-{}-0001".format(suffix))
                with app.db() as conn:
                    conn.execute(
                        "UPDATE conversations SET {} WHERE id=?".format(
                            update),
                        (conv_id,))

                status, body, _ = self.request(
                    "POST", "/api/job/retry", {"id": row["job"]})

                self.assertEqual(status, 409)
                self.assertIn("seans kapandı", body["error"])
                self.assertEqual(
                    self.row(
                        "SELECT status FROM chat_requests "
                        "WHERE request_id=?", (row["request_id"],)
                    )["status"],
                    "failed")
                self.assertEqual(
                    self.row(
                        "SELECT status FROM jobs WHERE id=?", (row["job"],)
                    )["status"],
                    "failed")
                self.assertTrue(app.JOB_QUEUE.empty())

    def test_chat_retry_does_not_displace_another_active_reply(self):
        conv_id = self.conversation()
        failed = self.fail_chat(conv_id, "chat-job-old-000001")
        active, _ = app.begin_chat_request(
            conv_id, "Daha yeni mesaj",
            request_id="chat-job-active-0001")

        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": failed["job"]})

        self.assertEqual(status, 409)
        self.assertIn("başka bir yanıt", body["error"])
        self.assertEqual(
            self.row(
                "SELECT status FROM chat_requests WHERE request_id=?",
                (failed["request_id"],))["status"],
            "failed")
        self.assertEqual(
            self.row(
                "SELECT status FROM chat_requests WHERE request_id=?",
                (active["request_id"],))["status"],
            "queued")
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_completed_chat_race_is_a_successful_noop(self):
        conv_id = self.conversation()
        row = self.fail_chat(conv_id, "chat-job-complete-01")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='completed',"
                "error_code='',finished='2026-07-30 10:03' "
                "WHERE request_id=?", (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='succeeded',stage='tamamlandı',"
                "progress=100,error_code='',finished='2026-07-30 10:03' "
                "WHERE id=?", (row["job"],))

        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": row["job"]})

        self.assertEqual(status, 200)
        self.assertFalse(body["queued"])
        self.assertEqual(body["status"], "completed")
        self.assertIn("zaten tamamlandı", body["message"])
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_missing_durable_chat_request_is_not_blindly_queued(self):
        conv_id = self.conversation()
        with app.db() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs("
                "kind,conv,status,stage,progress,created,updated"
                ") VALUES('chat_response',?,'failed','hata',100,'d','d')",
                (conv_id,)).lastrowid

        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": job_id})

        self.assertEqual(status, 409)
        self.assertIn("kalıcı mesaj isteği", body["error"])
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,)
                     )["status"],
            "failed")
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_postprocess_retry_is_atomic_and_keeps_snapshot(self):
        conv_id = self.conversation(ended=1)
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("deepseek_model", "deepseek-snapshot-a")
        job_id = app.create_job("session_postprocess", conv_id)
        app.update_job(job_id, "failed", "hata", 42, "offline")
        app.set_setting("llm_provider", "anthropic")
        app.set_setting("anthropic_model", "claude-later-b")
        barrier = threading.Barrier(3)
        results = []

        def retry():
            barrier.wait()
            results.append(app.retry_session_postprocess_job(job_id))

        workers = [threading.Thread(target=retry) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sorted(queued for _row, queued in results),
                         [False, True])
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(
            (job["provider"], job["model"]),
            ("deepseek", "deepseek-snapshot-a"))
        self.assertEqual(app.JOB_QUEUE.qsize(), 1)
        self.assertEqual(self.queued_job_id(), job_id)

    def test_completed_postprocess_retry_is_a_successful_noop(self):
        conv_id = self.conversation(ended=1)
        job_id = app.create_job("session_postprocess", conv_id)
        app.update_job(job_id, "succeeded", "tamamlandı", 100, "")

        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": job_id})

        self.assertEqual(status, 200)
        self.assertFalse(body["queued"])
        self.assertEqual(body["status"], "succeeded")
        self.assertIn("zaten tamamlandı", body["message"])
        self.assertTrue(app.JOB_QUEUE.empty())


class JobRetryUiContractTests(HTTPTestCase):

    def test_jobs_ui_uses_server_retry_outcome(self):
        source = (Path(app.DIR) / "index.html").read_text(encoding="utf-8")

        self.assertIn("chat_response:'Sohbet yanıtı'", source)
        self.assertIn("showToast(result.message||", source)
        self.assertIn("if(result.queued){", source)

