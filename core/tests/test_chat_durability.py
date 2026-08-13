import threading
from unittest import mock

from support import HTTPTestCase, app


class _ProviderStream:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class DurableChatRequestTests(HTTPTestCase):

    def test_message_length_is_enforced_before_any_turn_is_saved(self):
        conv_id = self.conversation()

        with self.assertRaises(app.RequestInputError) as caught:
            app.begin_chat_request(
                conv_id, "x" * (app.CHAT_MESSAGE_CHAR_LIMIT + 1),
                request_id="chat-too-long-00001")

        self.assertEqual(caught.exception.status, 400)
        self.assertIn("karakter", str(caught.exception))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            0,
        )

    def test_prompt_history_is_newest_first_selected_and_char_bounded(self):
        conv_id = self.conversation()
        with app.db() as conn:
            for index in range(app.HISTORY_LIMIT):
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "assistant" if index % 2 else "user",
                     "OLD-{:02d}-".format(index) + ("x" * 9990),
                     "2026-07-30 10:{:02d}".format(index % 60)))
        row, _ = app.begin_chat_request(
            conv_id, "EN-YENİ-MESAJ",
            request_id="chat-history-budget-1")

        _conv, payload = app._chat_prompt_payload(row)
        turns = payload["messages"][1:]

        self.assertLessEqual(
            sum(len(turn["content"]) for turn in turns),
            app.CHAT_HISTORY_CHAR_LIMIT)
        self.assertEqual(turns[-1]["content"], "EN-YENİ-MESAJ")
        self.assertNotIn(
            "OLD-00-", "\n".join(turn["content"] for turn in turns))

    def test_request_id_is_idempotent_and_only_one_turn_can_be_active(self):
        conv_id = self.conversation()
        request_id = "chat-idempotent-0001"

        first, created = app.begin_chat_request(
            conv_id, "İlk kalıcı mesaj", request_id=request_id)
        second, created_again = app.begin_chat_request(
            conv_id, "İlk kalıcı mesaj", request_id=request_id)

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["user_message"], second["user_message"])
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM messages")["n"], 1)
        with self.assertRaises(app.RequestInputError) as caught:
            app.begin_chat_request(
                conv_id, "İkinci mesaj",
                request_id="chat-idempotent-0002")
        self.assertEqual(caught.exception.status, 409)

    def test_lm_studio_auto_does_not_delay_persisting_the_user_turn(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "auto")

        with mock.patch.object(app, "discover_local_models") as discover:
            row, created = app.begin_chat_request(
                conv_id, "Önce beni kaydet",
                request_id="chat-local-auto-001")

        self.assertTrue(created)
        self.assertEqual(row["provider"], "lmstudio")
        self.assertEqual(row["model"], "auto")
        discover.assert_not_called()
        saved = self.row(
            "SELECT content FROM messages WHERE id=?",
            (row["user_message"],))
        self.assertEqual(saved["content"], "Önce beni kaydet")

    def test_completed_response_is_stored_once_with_provider_snapshot(self):
        conv_id = self.conversation()
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "yerel-test-modeli")
        row, _ = app.begin_chat_request(
            conv_id, "Yanıtla", request_id="chat-complete-0001")
        emitted = []

        def delta(_event_name, chunk, _provider):
            if chunk == "a":
                return "text", "Kalıcı "
            if chunk == "b":
                return "text", "yanıt."
            return "done", ""

        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "lmstudio"})), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events",
                    return_value=iter([
                        ("message", "a"), ("message", "b"),
                        ("message", "done")])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta):
            result = app.run_chat_request(
                row["request_id"], emit=emitted.append)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["content"], "Kalıcı yanıt.")
        self.assertEqual(result["provider"], "lmstudio")
        self.assertEqual(result["model"], "yerel-test-modeli")
        self.assertEqual(
            [(item["role"], item["content"]) for item in self.rows(
                "SELECT role,content FROM messages WHERE conv=? ORDER BY id",
                (conv_id,))],
            [("user", "Yanıtla"), ("assistant", "Kalıcı yanıt.")],
        )
        app.run_chat_request(row["request_id"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            2,
        )
        self.assertEqual(emitted[-1]["type"], "done")

    def test_failed_response_can_retry_without_repeating_user_message(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Aynı mesaj", request_id="chat-retry-000001")

        with mock.patch.object(
                app, "provider_request",
                side_effect=app.ProviderError("offline", "Ulaşılamadı.")):
            result = app.run_chat_request(row["request_id"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            1,
        )
        retried, queued = app.retry_chat_request(row["request_id"])
        self.assertTrue(queued)
        self.assertEqual(retried["status"], "queued")
        self.assertEqual(self.queued_job_id(), row["job"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            1,
        )

    def test_eof_without_terminal_event_keeps_partial_as_interrupted(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Tamamla", request_id="chat-eof-partial-001")

        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "lmstudio"})), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events",
                    return_value=iter([("message", "only")])), \
                mock.patch.object(
                    app, "provider_stream_delta",
                    return_value=("text", "Yarım cevap")):
            result = app.run_chat_request(row["request_id"])

        self.assertEqual(result["status"], "interrupted")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["content"], "Yarım cevap")
        self.assertEqual(
            result["error_code"], "provider_stream_interrupted")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"],
            1,
        )

    def test_context_change_interrupts_chat_without_requeueing_it(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Eski bağlam", request_id="chat-context-00001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running' "
                "WHERE request_id=?", (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?", (row["job"],))
        cancel_event = app.chat_cancel_event(
            row["request_id"], create=True)
        app.JOB_WORKER_STARTED = True
        handler = object.__new__(app.Handler)

        handler.context_mutation(lambda: None)

        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        job = self.row("SELECT * FROM jobs WHERE id=?", (row["job"],))
        self.assertEqual(request["status"], "interrupted")
        self.assertEqual(request["error_code"], "context_changed")
        self.assertEqual(job["status"], "interrupted")
        self.assertTrue(cancel_event.is_set())
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_chat_uses_generation_observed_after_user_turn_is_persisted(self):
        conv_id = self.conversation()
        original_begin = app.begin_chat_request

        def begin_then_change_generation(*args, **kwargs):
            result = original_begin(*args, **kwargs)
            app.bump_data_generation()
            return result

        def delta(_event_name, chunk, _provider):
            return ("done", "") if chunk == "done" else ("text", "Yanıt")

        with mock.patch.object(
                app, "begin_chat_request",
                side_effect=begin_then_change_generation), \
                mock.patch.object(
                    app, "provider_request",
                    return_value=(object(), {"id": "lmstudio"})), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events",
                    return_value=iter([
                        ("message", "text"), ("message", "done")])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta):
            status, _, _ = self.request(
                "POST", "/api/chat", {
                    "conv_id": conv_id,
                    "message": "Yeni generation",
                    "request_id": "chat-generation-001",
                })

        self.assertEqual(status, 200)
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            ("chat-generation-001",))
        self.assertEqual(request["status"], "completed")
        self.assertIsNotNone(request["assistant_message"])

    def test_cancelled_request_keeps_partial_text_and_can_be_retried(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Durdur", request_id="chat-cancel-00001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running',"
                "partial_content='Yarım yanıt' WHERE request_id=?",
                (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?", (row["job"],))

        cancelled, changed = app.cancel_chat_request(row["request_id"])

        self.assertTrue(changed)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["partial_content"], "Yarım yanıt")
        retried, queued = app.retry_chat_request(row["request_id"])
        self.assertTrue(queued)
        self.assertEqual(retried["partial_content"], "")

    def test_retry_waits_for_previous_physical_stream_to_release(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Yeniden dene",
            request_id="chat-retry-overlap-1")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='interrupted' "
                "WHERE request_id=?", (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='interrupted' WHERE id=?",
                (row["job"],))
        app.chat_cancel_event(row["request_id"], create=True).set()

        with self.assertRaises(app.RequestInputError) as caught:
            app.retry_chat_request(row["request_id"])
        self.assertEqual(caught.exception.status, 409)

        app.release_chat_cancel_event(row["request_id"])
        retried, queued = app.retry_chat_request(row["request_id"])
        self.assertTrue(queued)
        self.assertEqual(retried["status"], "queued")

    def test_deleting_other_conversation_interrupts_chat_without_requeue(self):
        active_conv = self.conversation(title="Yanıt süren")
        delete_conv = self.conversation(title="Silinecek başka görüşme")
        row, _ = app.begin_chat_request(
            active_conv, "Bağlamı koru",
            request_id="chat-delete-context-1")
        app.JOB_WORKER_STARTED = True

        status, body, _ = self.request(
            "POST", "/api/delete", {"id": delete_conv})

        self.assertEqual(status, 200, body)
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        job = self.row("SELECT * FROM jobs WHERE id=?", (row["job"],))
        self.assertEqual(request["status"], "interrupted")
        self.assertEqual(request["error_code"], "context_changed")
        self.assertEqual(job["status"], "interrupted")
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_deleting_active_conversation_closes_stream_and_releases_handles(self):
        conv_id = self.conversation(title="Silinirken üreten")
        request, _ = app.begin_chat_request(
            conv_id, "Uzun yanıt",
            request_id="chat-delete-stream-1")
        entered = threading.Event()
        closed = threading.Event()
        result = []

        class BlockingResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def close(self):
                closed.set()

        response = BlockingResponse()

        def events(_response):
            entered.set()
            closed.wait(2)
            return
            yield  # pragma: no cover

        worker = threading.Thread(
            target=lambda: result.append(
                app.run_chat_request(request["request_id"])))
        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "lmstudio"})), \
                mock.patch.object(
                    app, "open_provider_url", return_value=response), \
                mock.patch.object(app, "iter_sse_events", side_effect=events):
            worker.start()
            self.assertTrue(entered.wait(1))
            status, body, _ = self.request(
                "POST", "/api/delete", {"id": conv_id})
            self.assertEqual(status, 200, body)
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(closed.is_set())
        self.assertEqual(result, [None])
        self.assertIsNone(
            app.chat_cancel_event(request["request_id"], create=False))
        with app.CHAT_CANCEL_LOCK:
            self.assertNotIn(
                request["request_id"], app.CHAT_ACTIVE_RESPONSES)

    def test_ending_session_cancels_an_active_chat_request(self):
        conv_id = self.conversation()
        row, _ = app.begin_chat_request(
            conv_id, "Yanıt sürüyor", request_id="chat-end-000000001")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running' "
                "WHERE request_id=?", (row["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?", (row["job"],))

        status, body, _ = self.request(
            "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(status, 200, body)
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (row["request_id"],))
        self.assertEqual(request["status"], "cancelled")
        self.assertEqual(request["error_code"], "session_ended")
        job = self.row("SELECT * FROM jobs WHERE id=?", (row["job"],))
        self.assertEqual(job["status"], "interrupted")

    def test_conversation_and_search_expose_stable_message_targets(self):
        conv_id = self.conversation()
        with app.db() as conn:
            quoted = conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "assistant", "Önceki özgün cümle",
                 "2026-07-30 09:00")).lastrowid

        status, crisis, _ = self.request(
            "POST", "/api/chat", {
                "conv_id": conv_id,
                "message": "Yaşamak istemiyorum",
                "request_id": "chat-safety-000001",
                "reply_to": quoted,
            })
        self.assertEqual(status, 200)
        self.assertTrue(crisis["crisis"])

        status, body, _ = self.request(
            "GET", "/api/conversation?id={}".format(conv_id))
        self.assertEqual(status, 200)
        user = next(
            item for item in body["messages"] if item["role"] == "user")
        self.assertEqual(user["reply_to"], quoted)
        self.assertEqual(user["reply_preview_content"], "Önceki özgün cümle")
        self.assertEqual(
            body["chat_request"]["request_id"], "chat-safety-000001")

        status, found, _ = self.request(
            "GET", "/api/search?q=%C3%B6zg%C3%BCn")
        self.assertEqual(status, 200)
        self.assertEqual(found["results"][0]["message_id"], quoted)
