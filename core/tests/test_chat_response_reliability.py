import time
import socket
import urllib.error
from unittest import mock

from support import HTTPTestCase, app


class _ProviderStream:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ChatResponseReliabilityTests(HTTPTestCase):

    def successful_stream(self, text="Tam ve kalıcı yanıt"):
        def delta(_event_name, raw, _provider):
            if raw == "done":
                return "done", ""
            return "text", text

        return (
            mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False})),
            mock.patch.object(
                app, "open_provider_url",
                return_value=_ProviderStream()),
            mock.patch.object(
                app, "iter_sse_events",
                return_value=iter([
                    ("message", "text"), ("message", "done")])),
            mock.patch.object(
                app, "provider_stream_delta", side_effect=delta),
        )

    def test_first_safe_text_is_emitted_before_stream_completion(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Hızlı görünür yanıt",
            request_id="chat-first-visible-delta-1")
        events = []

        def delta(_event, raw, _provider):
            return ("done", "") if raw == "done" else ("text", raw)

        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False})), \
                mock.patch.object(
                    app, "open_provider_url", return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", return_value=iter([
                        ("message", "Bu"),
                        ("message", " gerçekten"),
                        ("message", " hızlı."),
                        ("message", "done"),
                    ])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta):
            result = app.run_chat_request(
                row["request_id"], emit=events.append,
                automatic_retries=False)

        deltas = [event for event in events if event["type"] == "delta"]
        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(deltas[0]["text"], "Bu")
        self.assertEqual("".join(event["text"] for event in deltas), result["content"])
        self.assertLess(
            next(i for i, event in enumerate(events) if event["type"] == "delta"),
            next(i for i, event in enumerate(events) if event["type"] == "done"))

    def test_stage_opening_is_removed_without_hiding_real_first_sentence(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Anlatıcı açılışını çıkar",
            request_id="chat-stage-opening-stream-1")
        events = []

        def delta(_event, raw, _provider):
            return ("done", "") if raw == "done" else ("text", raw)

        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False})), \
                mock.patch.object(
                    app, "open_provider_url", return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", return_value=iter([
                        ("message", "Yavaşça, "),
                        ("message", "o itirafın ağırlığını tartarak:"),
                        ("message", "Gerçek "),
                        ("message", "yanıt."),
                        ("message", "done"),
                    ])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta):
            result = app.run_chat_request(
                row["request_id"], emit=events.append,
                automatic_retries=False)

        visible = "".join(
            event["text"] for event in events if event["type"] == "delta")
        self.assertEqual(visible, "Gerçek yanıt.")
        self.assertEqual(result["content"], visible)
        self.assertNotIn("Yavaşça", visible)

    def test_fast_tiny_provider_chunks_are_coalesced_without_content_loss(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Küçük parçaları birleştir",
            request_id="chat-delta-coalesce-1")
        expected = "B" + ("çokhızlıyerelmodel" * 10)
        events = []

        def delta(_event, raw, _provider):
            return ("done", "") if raw == "done" else ("text", raw)

        chunks = [("message", character) for character in expected]
        chunks.append(("message", "done"))
        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "lmstudio", "local": True})), \
                mock.patch.object(
                    app, "open_provider_url", return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", return_value=iter(chunks)), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta):
            result = app.run_chat_request(
                row["request_id"], emit=events.append,
                automatic_retries=False)

        deltas = [event["text"] for event in events if event["type"] == "delta"]
        self.assertEqual("".join(deltas), expected)
        self.assertEqual(result["content"], expected)
        self.assertLess(len(deltas), len(expected) // 4)

    def test_stage_opening_stream_guard_is_bounded(self):
        prefix = "Yavaşça, " + ("uzun bir anlatıcı betimi " * 8)
        self.assertGreaterEqual(
            len(prefix), app.STAGE_OPENING_STREAM_BUFFER_LIMIT)
        self.assertFalse(app.stage_opening_should_wait(prefix))

    def test_init_db_migrates_legacy_chat_requests_without_data_loss(self):
        conv_id = self.conversation()
        with app.db() as conn:
            user_message = conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "Eski kalıcı mesaj", "2026-07-30 10:00"),
            ).lastrowid
            job_id = conn.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'failed','d','d')",
                (conv_id,)).lastrowid
            conn.execute("DROP INDEX chat_requests_one_active")
            conn.execute("DROP TABLE chat_requests")
            conn.execute("""
                CREATE TABLE chat_requests(
                    request_id TEXT PRIMARY KEY, job INTEGER UNIQUE NOT NULL,
                    conv INTEGER NOT NULL, user_message INTEGER NOT NULL,
                    assistant_message INTEGER, reply_to INTEGER,
                    status TEXT NOT NULL DEFAULT 'queued',
                    guidance TEXT NOT NULL DEFAULT '', method_id INTEGER,
                    method_key TEXT, provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    partial_content TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    created TEXT, started TEXT, finished TEXT, updated TEXT)
            """)
            conn.execute(
                "INSERT INTO chat_requests("
                "request_id,job,conv,user_message,status,provider,model,"
                "created,updated) VALUES(?,?,?,?,'failed','deepseek',"
                "'legacy-model','d','d')",
                ("chat-legacy-migrate-1", job_id, conv_id, user_message))

        app.init_db()

        columns = {
            row["name"] for row in self.rows(
                "PRAGMA table_info(chat_requests)")}
        self.assertTrue({
            "best_partial_content", "attempt_count", "max_attempts",
            "provider_wait_count", "next_attempt_at", "heartbeat_at",
            "lease_token",
        }.issubset(columns))
        legacy = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            ("chat-legacy-migrate-1",))
        self.assertEqual(legacy["model"], "legacy-model")
        self.assertEqual(legacy["attempt_count"], 0)
        index_sql = self.row(
            "SELECT sql FROM sqlite_master WHERE "
            "name='chat_requests_one_active'")["sql"]
        self.assertIn("waiting_provider", index_sql)

    def test_transient_failure_is_durably_scheduled_then_completes_once(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Kaybolmaması gereken mesaj",
            request_id="chat-auto-retry-0001")

        with mock.patch.object(
                app, "provider_request",
                side_effect=app.ProviderError(
                    "provider_unavailable", "Geçici hata.")), \
                mock.patch.object(
                    app, "schedule_chat_request") as schedule:
            first = app.run_chat_request(
                row["request_id"], automatic_retries=True)

        self.assertEqual(first["status"], "queued")
        self.assertEqual(first["attempt"], 1)
        self.assertEqual(first["max_attempts"], app.CHAT_MAX_ATTEMPTS)
        self.assertTrue(first["automatic_retry"])
        self.assertTrue(first["pending"])
        self.assertFalse(first["retryable"])
        self.assertIsNotNone(first["next_retry_at"])
        schedule.assert_called_once()
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET next_attempt_at=0 "
                "WHERE request_id=?", (row["request_id"],))

        patches = self.successful_stream()
        with patches[0], patches[1], patches[2], patches[3]:
            completed = app.run_chat_request(
                row["request_id"], automatic_retries=True)

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["attempt"], 2)
        self.assertEqual(completed["content"], "Tam ve kalıcı yanıt")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=? "
                "AND role='user'", (conv_id,))["n"],
            1)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=? "
                "AND role='assistant'", (conv_id,))["n"],
            1)

    def test_stream_failure_uses_replace_event_and_nonstream_fallback(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Akış uyumsuzluğu",
            request_id="chat-stream-fallback-1")
        events = []

        with mock.patch.object(
                app, "provider_request",
                return_value=(
                    object(), {"id": "lmstudio", "local": True})), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events",
                    return_value=iter([("message", "partial")])), \
                mock.patch.object(
                    app, "provider_stream_delta",
                    return_value=("text", "Yarım metin")), \
                mock.patch.object(
                    app, "_chat_nonstream_fallback",
                    return_value="Baştan sona tam yanıt"), \
                mock.patch.object(app, "schedule_chat_request"):
            result = app.run_chat_request(
                row["request_id"], emit=events.append,
                automatic_retries=True)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["content"], "Baştan sona tam yanıt")
        replacement = next(
            event for event in events if event["type"] == "replace")
        self.assertEqual(replacement["text"], "Baştan sona tam yanıt")
        self.assertEqual(replacement["fallback"], "non_stream")
        fallback_status = next(
            event for event in events
            if event["type"] == "status"
            and event.get("status") == "fallback_nonstream")
        self.assertLess(events.index(fallback_status), events.index(replacement))
        self.assertEqual(
            self.row(
                "SELECT content FROM messages WHERE conv=? "
                "AND role='assistant'", (conv_id,))["content"],
            "Baştan sona tam yanıt")

    def test_real_openai_compatible_null_finish_chunks_complete_normally(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Normal SSE biçimi",
            request_id="chat-null-finish-e2e-1")
        chunks = [
            ("message", app.json.dumps({
                "choices": [{
                    "delta": {"reasoning_content": "düşünüyor"},
                    "finish_reason": None,
                }],
            })),
            ("message", app.json.dumps({
                "choices": [{
                    "delta": {"content": "Gerçek "},
                    "finish_reason": None,
                }],
            })),
            ("message", app.json.dumps({
                "choices": [{
                    "delta": {"content": "yanıt."},
                    "finish_reason": None,
                }],
            })),
            ("message", app.json.dumps({
                "choices": [{
                    "delta": {},
                    "finish_reason": "stop",
                }],
            })),
        ]

        with mock.patch.object(
                app, "provider_request",
                return_value=(
                    object(), {
                        "id": "deepseek",
                        "protocol": "openai_chat",
                        "local": False,
                    })), mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events",
                    return_value=iter(chunks)):
            result = app.run_chat_request(
                row["request_id"], automatic_retries=False)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["content"], "Gerçek yanıt.")
        self.assertEqual(
            self.row(
                "SELECT content FROM messages WHERE conv=? "
                "AND role='assistant'", (conv_id,))["content"],
            "Gerçek yanıt.")

    def test_retry_exhaustion_keeps_request_visible_without_fake_turn(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Bu mesaj görünür kalmalı",
            request_id="chat-exhausted-00001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET max_attempts=1 "
                "WHERE request_id=?", (row["request_id"],))

        with mock.patch.object(
                app, "provider_request",
                side_effect=app.ProviderError(
                    "provider_unavailable", "Geçici hata.")), \
                mock.patch.object(app, "schedule_chat_request") as schedule:
            result = app.run_chat_request(
                row["request_id"], automatic_retries=True)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["retryable"])
        self.assertFalse(result["pending"])
        self.assertIn("Mesajın kaydedildi", result["content"])
        schedule.assert_not_called()
        # Bir ağ hatası ustanın ağzından uydurma bir assistant turu değildir.
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=? "
                "AND role='assistant'", (conv_id,))["n"],
            0)

    def test_offline_local_provider_waits_without_terminal_failure(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "yerel-model")
        row, _ = app.begin_chat_request(
            conv_id, "LM Studio açılınca yanıtla",
            request_id="chat-local-wait-0001")

        with mock.patch.object(
                app, "provider_request",
                side_effect=app.ProviderError(
                    "local_unavailable", "Yerel sunucu kapalı.")), \
                mock.patch.object(
                    app, "schedule_local_provider_probe") as probe:
            result = app.run_chat_request(
                row["request_id"], automatic_retries=True)

        self.assertEqual(result["status"], "waiting_provider")
        self.assertTrue(result["waiting_for_provider"])
        self.assertTrue(result["automatic_retry"])
        self.assertTrue(result["pending"])
        self.assertFalse(result["retryable"])
        self.assertEqual(result["attempt"], 1)
        probe.assert_called_once()
        job = self.row("SELECT status FROM jobs WHERE id=?", (row["job"],))
        self.assertEqual(job["status"], "waiting_provider")
        with self.assertRaises(app.RequestInputError) as caught:
            app.begin_chat_request(
                conv_id, "İkinci aktif mesaj",
                request_id="chat-local-wait-0002")
        self.assertEqual(caught.exception.status, 409)

    def test_local_health_probe_does_not_consume_generation_attempts(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "yerel-model")
        row, _ = app.begin_chat_request(
            conv_id, "Bekle",
            request_id="chat-local-probe-001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='waiting_provider',"
                "attempt_count=1,provider_wait_count=1,next_attempt_at=0 "
                "WHERE request_id=?", (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (row["job"],))

        with mock.patch.object(
                app, "provider_config",
                return_value={
                    "base_url": "http://127.0.0.1:1234/v1",
                    "secret": "",
                }), mock.patch.object(
                    app, "discover_local_models",
                    side_effect=app.ProviderError(
                        "local_unavailable", "Kapalı.")), \
                mock.patch.object(
                    app, "schedule_local_provider_probe") as schedule:
            app._probe_waiting_local_provider(
                row["request_id"], row["job"], app.data_generation())

        waiting = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        self.assertEqual(waiting["status"], "waiting_provider")
        self.assertEqual(waiting["attempt_count"], 1)
        self.assertEqual(waiting["provider_wait_count"], 2)
        self.assertGreater(waiting["next_attempt_at"], time.time())
        schedule.assert_called_once()

    def test_local_health_probe_wakes_same_durable_request(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "yerel-model")
        row, _ = app.begin_chat_request(
            conv_id, "Açılınca devam",
            request_id="chat-local-wake-0001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='waiting_provider',"
                "attempt_count=1,provider_wait_count=3,next_attempt_at=0 "
                "WHERE request_id=?", (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (row["job"],))

        with mock.patch.object(
                app, "provider_config",
                return_value={
                    "base_url": "http://127.0.0.1:1234/v1",
                    "secret": "",
                }), mock.patch.object(
                    app, "discover_local_models",
                    return_value=["yerel-model"]), \
                mock.patch.object(app, "enqueue_job") as enqueue:
            app._probe_waiting_local_provider(
                row["request_id"], row["job"], app.data_generation())

        awakened = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        self.assertEqual(awakened["status"], "queued")
        self.assertEqual(awakened["attempt_count"], 1)
        self.assertEqual(awakened["provider_wait_count"], 0)
        self.assertIsNone(awakened["next_attempt_at"])
        enqueue.assert_called_once_with(
            row["job"], app.data_generation())

    def test_waiting_provider_can_be_cancelled_and_session_can_close(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        row, _ = app.begin_chat_request(
            conv_id, "Bekleyen mesaj",
            request_id="chat-wait-cancel-001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='waiting_provider',"
                "next_attempt_at=? WHERE request_id=?",
                (time.time() + 60, row["request_id"]))
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (row["job"],))

        cancelled, changed = app.cancel_chat_request(row["request_id"])

        self.assertTrue(changed)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(cancelled["next_attempt_at"])
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?",
                     (row["job"],))["status"],
            "interrupted")

        second, _ = app.begin_chat_request(
            conv_id, "Seans kapanırken bekleyen",
            request_id="chat-wait-end-000001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='waiting_provider',"
                "next_attempt_at=? WHERE request_id=?",
                (time.time() + 60, second["request_id"]))
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (second["job"],))
        with mock.patch.object(
                app, "ds_complete",
                return_value="Bugünlük burada kalalım."):
            status, body, _ = self.request(
                "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(status, 200, body)
        ended = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (second["request_id"],))
        self.assertEqual(ended["status"], "cancelled")
        self.assertEqual(ended["error_code"], "session_ended")
        self.assertIsNone(ended["next_attempt_at"])

    def test_resume_rebuilds_waiting_provider_probe(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        row, _ = app.begin_chat_request(
            conv_id, "Yeniden başlatınca bekle",
            request_id="chat-wait-resume-001")
        due = time.time() + 25
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='waiting_provider',"
                "next_attempt_at=? WHERE request_id=?",
                (due, row["request_id"]))
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (row["job"],))
        app.JOB_WORKER_STARTED = True

        with mock.patch.object(
                app, "schedule_local_provider_probe") as probe, \
                mock.patch.object(app, "schedule_chat_request"), \
                mock.patch.object(app, "enqueue_job"):
            app.resume_jobs()

        probe.assert_called_once()
        args = probe.call_args.args
        self.assertEqual(args[:3], (
            row["request_id"], row["job"], app.data_generation()))
        self.assertGreater(args[3], 0)
        self.assertLessEqual(args[3], 25)

    def test_restart_reclaims_running_lease_and_rebuilds_schedule(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Yeniden başlatma",
            request_id="chat-restart-recover-1")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running',"
                "attempt_count=2,lease_token='old-process',heartbeat_at=? "
                "WHERE request_id=?",
                (time.time(), row["request_id"]))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?",
                (row["job"],))
        app.JOB_WORKER_STARTED = True

        with mock.patch.object(
                app, "schedule_chat_request") as schedule, \
                mock.patch.object(app, "enqueue_job"):
            app.resume_jobs()

        recovered = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(recovered["attempt_count"], 2)
        self.assertEqual(recovered["lease_token"], "")
        self.assertEqual(recovered["error_code"], "restarted")
        schedule.assert_called_once()

    def test_resume_prioritizes_chat_before_long_postprocess_jobs(self):
        first_conv = self.conversation(title="Eski kapanış bir")
        second_conv = self.conversation(title="Eski kapanış iki")
        first_job = app.create_job("session_postprocess", first_conv)
        second_job = app.create_job("session_postprocess", second_conv)
        chat_conv = self.conversation(title="Yarım kalan sohbet")
        chat, _ = app.begin_chat_request(
            chat_conv, "Önce beni sürdür",
            request_id="chat-priority-resume-1")
        with app.db() as conn:
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id IN (?,?,?)",
                (first_job, second_job, chat["job"]))
            conn.execute(
                "UPDATE chat_requests SET status='running',"
                "attempt_count=1,lease_token='dead-process',"
                "heartbeat_at=? WHERE request_id=?",
                (time.time(), chat["request_id"]))

        app.resume_jobs()

        queued = [app.JOB_QUEUE.get_nowait() for _ in range(3)]
        queued_ids = [item[1] for item in queued]
        self.assertEqual(queued_ids[0], chat["job"])
        self.assertEqual(queued_ids[1:], [first_job, second_job])
        for _item in queued:
            app.JOB_QUEUE.task_done()

    def test_live_recovery_reclaims_stale_running_job(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Takılı kalan worker",
            request_id="chat-stale-recover-01")
        old_event = app.chat_cancel_event(
            row["request_id"], create=True)
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running',"
                "attempt_count=1,lease_token='stale-lease',heartbeat_at=? "
                "WHERE request_id=?",
                (time.time() - app.CHAT_STALE_AFTER_SECONDS - 10,
                 row["request_id"]))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?",
                (row["job"],))
        app.JOB_WORKER_STARTED = True

        with mock.patch.object(
                app, "schedule_chat_request") as schedule:
            summary = app.recover_stale_chat_requests()

        self.assertEqual(summary["stale"], 1)
        self.assertTrue(old_event.is_set())
        recovered = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(
            recovered["error_code"], "stale_worker_recovered")
        self.assertEqual(recovered["lease_token"], "")
        schedule.assert_called_once()

    def test_old_lease_cannot_commit_after_recovery_claim(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Tek yanıt üret",
            request_id="chat-lease-fence-001")

        def events(_response):
            with app.db() as conn:
                conn.execute(
                    "UPDATE chat_requests SET status='queued',"
                    "lease_token='new-lease',next_attempt_at=? "
                    "WHERE request_id=?",
                    (time.time() + 60, row["request_id"]))
                conn.execute(
                    "UPDATE jobs SET status='queued' WHERE id=?",
                    (row["job"],))
            yield "message", "text"
            yield "message", "done"

        def delta(_event, raw, _provider):
            return (
                ("done", "") if raw == "done"
                else ("text", "Eski soketin geç yanıtı"))

        with mock.patch.object(
                app, "provider_request",
                return_value=(
                    object(), {"id": "deepseek", "local": False})), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", side_effect=events), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta):
            result = app.run_chat_request(
                row["request_id"], automatic_retries=False)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=? "
                "AND role='assistant'", (conv_id,))["n"],
            0)

    def test_http_chat_exception_enters_same_durable_recovery_path(self):
        conv_id = self.conversation()
        with mock.patch.object(
                app, "run_chat_request",
                side_effect=RuntimeError("unexpected DB failure")), \
                mock.patch.object(
                    app, "schedule_chat_request") as schedule, \
                mock.patch("builtins.print"):
            status, stream, headers = self.request(
                "POST", "/api/chat", {
                    "conv_id": conv_id,
                    "message": "HTTP thread'inde kaybolma",
                    "request_id": "chat-http-recovery-01",
                })

        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["Content-Type"])
        self.assertIn('"type": "retrying"', stream)
        self.assertIn('"status": "queued"', stream)
        recovered = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            ("chat-http-recovery-01",))
        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(recovered["error_code"], "worker_exception")
        self.assertIsNotNone(recovered["next_attempt_at"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=? "
                "AND role='user'", (conv_id,))["n"],
            1)
        schedule.assert_called_once()

    def test_new_lease_cannot_be_cleared_or_overwritten_by_old_socket(self):
        request_id = "chat-event-lease-0001"
        old_event = app.renew_chat_cancel_event(request_id)
        new_event = app.renew_chat_cancel_event(request_id)
        self.assertTrue(old_event.is_set())
        self.assertFalse(new_event.is_set())

        app.release_chat_cancel_event(request_id, old_event)
        self.assertIs(
            app.chat_cancel_event(request_id, create=False), new_event)

        class Response:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        old_response = Response()
        new_response = Response()
        self.assertFalse(app.register_chat_response(
            request_id, old_response, old_event))
        self.assertTrue(old_response.closed)
        self.assertTrue(app.register_chat_response(
            request_id, new_response, new_event))
        with app.CHAT_CANCEL_LOCK:
            self.assertIs(
                app.CHAT_ACTIVE_RESPONSES[request_id], new_response)

    def test_provider_timeout_is_distinct_and_bounded_retryable(self):
        timeout = app.provider_error(
            urllib.error.URLError(socket.timeout("timed out")),
            local=True)

        self.assertEqual(timeout.code, "provider_timeout")
        self.assertTrue(app.chat_error_is_retryable(timeout.code))
        self.assertNotIn(
            timeout.code, app.CHAT_LOCAL_WAIT_ERROR_CODES)
        self.assertEqual(
            [app._chat_retry_delay(value) for value in (1, 2, 3, 99)],
            [1.0, 3.0, 8.0, 8.0])

    def test_rate_limit_retry_after_controls_durable_next_attempt(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Kota penceresini bekle",
            request_id="chat-retry-after-0001")
        before = time.time()
        with mock.patch.object(
                app, "provider_request",
                side_effect=app.ProviderError(
                    "rate_limited", "Sınır.", retry_after=45)), \
                mock.patch.object(
                    app, "schedule_chat_request") as schedule:
            result = app.run_chat_request(
                row["request_id"], automatic_retries=True)

        self.assertEqual(result["status"], "queued")
        durable = self.row(
            "SELECT next_attempt_at FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        self.assertGreaterEqual(durable["next_attempt_at"], before + 44.5)
        self.assertEqual(schedule.call_args.args[3], 45.0)

    def test_create_server_binds_before_any_database_or_worker_work(self):
        calls = []
        fake_server = mock.Mock()

        def record(name, result=None):
            def invoke(*_args, **_kwargs):
                calls.append(name)
                return result
            return invoke

        with mock.patch.object(
                app, "ThreadingHTTPServer",
                side_effect=record("bind", fake_server)) as server_factory, \
                mock.patch.object(
                    app, "init_db", side_effect=record("init")), \
                mock.patch.object(
                    app, "migrate_api_secrets_to_external_store",
                    side_effect=record("secrets")), \
                mock.patch.object(
                    app, "enforce_retention_policy",
                    side_effect=record("retention")), \
                mock.patch.object(
                    app, "automatic_backup",
                    side_effect=record("backup")), \
                mock.patch.object(
                    app, "resume_jobs", side_effect=record("resume")), \
                mock.patch.object(
                    app, "start_job_worker",
                    side_effect=record("worker")):
            created = app.create_server(
                host="127.0.0.1", port=0,
                db_path=app.DB_PATH, session_token="embedded-token")

        self.assertIs(created, fake_server)
        self.assertEqual(calls, [
            "bind", "init", "secrets", "retention", "backup",
            "resume", "worker",
        ])
        server_factory.assert_called_once_with(
            ("127.0.0.1", 0), app.Handler)
        fake_server.server_close.assert_not_called()

    def test_failed_bind_cannot_requeue_or_mutate_database(self):
        with mock.patch.object(
                app, "ThreadingHTTPServer",
                side_effect=OSError("address already in use")), \
                mock.patch.object(app, "init_db") as init_db, \
                mock.patch.object(
                    app, "migrate_api_secrets_to_external_store") as secrets, \
                mock.patch.object(
                    app, "enforce_retention_policy") as retention, \
                mock.patch.object(app, "automatic_backup") as backup, \
                mock.patch.object(app, "resume_jobs") as resume, \
                mock.patch.object(app, "start_job_worker") as worker:
            with self.assertRaises(OSError):
                app.create_server(port=app.PORT)

        init_db.assert_not_called()
        secrets.assert_not_called()
        retention.assert_not_called()
        backup.assert_not_called()
        resume.assert_not_called()
        worker.assert_not_called()

    def test_create_server_closes_bound_socket_if_initialization_fails(self):
        fake_server = mock.Mock()
        with mock.patch.object(
                app, "ThreadingHTTPServer",
                return_value=fake_server), \
                mock.patch.object(
                    app, "init_db",
                    side_effect=RuntimeError("migration failed")), \
                mock.patch.object(app, "resume_jobs") as resume, \
                mock.patch.object(app, "start_job_worker") as worker:
            with self.assertRaises(RuntimeError):
                app.create_server(port=0)

        fake_server.server_close.assert_called_once_with()
        resume.assert_not_called()
        worker.assert_not_called()

    def test_public_status_exposes_recovery_contract(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Durum",
            request_id="chat-status-contract-1")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='waiting_provider',"
                "attempt_count=1,max_attempts=4,next_attempt_at=? "
                "WHERE request_id=?",
                (time.time() + 30, row["request_id"]))
            conn.execute(
                "UPDATE jobs SET status='waiting_provider' WHERE id=?",
                (row["job"],))

        status, body, _ = self.request(
            "GET", "/api/chat-status?request_id={}".format(
                row["request_id"]))

        self.assertEqual(status, 200)
        chat = body["chat"]
        self.assertEqual(chat["status"], "waiting_provider")
        self.assertEqual(chat["attempt"], 1)
        self.assertEqual(chat["max_attempts"], 4)
        self.assertTrue(chat["automatic_retry"])
        self.assertTrue(chat["pending"])
        self.assertTrue(chat["waiting_for_provider"])
        self.assertFalse(chat["retryable"])
        self.assertIsNotNone(chat["next_retry_at"])

    def test_chat_status_recovery_sweep_is_throttled(self):
        previous = app.CHAT_STATUS_LAST_RECOVERY_SCAN
        app.CHAT_STATUS_LAST_RECOVERY_SCAN = float("-inf")
        try:
            with mock.patch.object(
                    app, "recover_stale_chat_requests") as recover:
                self.assertTrue(app.recover_stale_chat_requests_for_status())
                self.assertFalse(app.recover_stale_chat_requests_for_status())
            recover.assert_called_once_with()
        finally:
            app.CHAT_STATUS_LAST_RECOVERY_SCAN = previous
