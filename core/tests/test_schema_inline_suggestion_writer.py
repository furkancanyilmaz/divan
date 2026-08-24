"""Mod önerisi gerçek asistan yazıcısından geçmeli.

Regresyon: ayrıştırma bir dönem yalnız kriz (safety) yolunda duruyordu.
Gerçek yanıtlar `_upsert_chat_assistant` üzerinden yazıldığı için işaret
metinde kalıyor, kart hiç oluşmuyordu.
"""

from support import HTTPTestCase, app


class SchemaInlineSuggestionWriterTests(HTTPTestCase):
    stamp = "2026-08-20 12:00"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        # Inline labels are intentionally unavailable during the first two
        # safe pairs.  The request under test is the third pair.
        with app.db() as connection:
            for index in range(2):
                stamp = "2026-08-20 11:{:02d}".format(index)
                user = connection.execute(
                    "INSERT INTO messages(conv,role,content,created,"
                    "delivery_status) VALUES(?,'user',?,?, 'completed')",
                    (self.conv, "önceki güvenli anlatım {}".format(index),
                     stamp)).lastrowid
                assistant = connection.execute(
                    "INSERT INTO messages(conv,role,content,created,"
                    "delivery_status) VALUES(?,'assistant',?,?, 'completed')",
                    (self.conv, "önceki yanıt {}".format(index),
                     stamp)).lastrowid
                job = connection.execute(
                    "INSERT INTO jobs(kind,conv,status,created,updated) "
                    "VALUES('chat_response',?,'succeeded',?,?)",
                    (self.conv, stamp, stamp)).lastrowid
                connection.execute(
                    "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                    "assistant_message,status,created,updated) "
                    "VALUES(?,?,?,?,?,'completed',?,?)",
                    ("schema-inline-prior-{}".format(index), job, self.conv,
                     user, assistant, stamp, stamp))

    def request_row(self, connection, suffix="000001"):
        user_id = connection.execute(
            "INSERT INTO messages(conv,role,content,created,"
            "delivery_status) VALUES(?,'user','sürekli duvar örüyorum',?,"
            "'completed')", (self.conv, self.stamp)).lastrowid
        job_id = connection.execute(
            "INSERT INTO jobs(kind,conv,status,created,updated) "
            "VALUES('chat_response',?,'running',?,?)",
            (self.conv, self.stamp, self.stamp)).lastrowid
        request_id = "schema-inline-{}".format(suffix)
        connection.execute(
            "INSERT INTO chat_requests(request_id,job,conv,user_message,"
            "status,created,updated) VALUES(?,?,?,?,'running',?,?)",
            (request_id, job_id, self.conv, user_id,
             self.stamp, self.stamp))
        return connection.execute(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (request_id,)).fetchone()

    def test_marker_is_stripped_and_stored_as_suggestion(self):
        reply = ("Anlıyorum, bu tanıdık geliyor.\n"
                 "[[MOD]] detached_protector | duvar örüyorum")
        with app.db() as connection:
            row = self.request_row(connection)
            message_id = app._upsert_chat_assistant(
                connection, row, reply, "completed")
            stored = connection.execute(
                "SELECT content FROM messages WHERE id=?",
                (message_id,)).fetchone()["content"]
            suggestion = connection.execute(
                "SELECT mode_key,evidence,assistant_message "
                "FROM schema_inline_suggestions WHERE conv=?",
                (self.conv,)).fetchone()
        # Kullanıcı ham işareti asla görmemeli.
        self.assertNotIn("[[MOD]]", stored)
        self.assertEqual(stored, "Anlıyorum, bu tanıdık geliyor.")
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion["mode_key"], "detached_protector")
        self.assertEqual(suggestion["evidence"], "duvar örüyorum")
        self.assertEqual(suggestion["assistant_message"], message_id)

    def test_retry_of_same_request_does_not_duplicate_suggestion(self):
        reply = ("Anlıyorum.\n"
                 "[[MOD]] detached_protector | duvar örüyorum")
        with app.db() as connection:
            row = self.request_row(connection)
            app._upsert_chat_assistant(connection, row, reply, "completed")
            app._upsert_chat_assistant(connection, row, reply, "completed")
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM schema_inline_suggestions "
                "WHERE conv=?", (self.conv,)).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_first_two_pairs_strip_but_never_store_early_label(self):
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        reply = ("Yanıt.\n"
                 "[[MOD]] detached_protector | duvar örüyorum")
        with app.db() as connection:
            for index in range(2):
                row = self.request_row(
                    connection, suffix="early-{}".format(index))
                assistant = app._upsert_chat_assistant(
                    connection, row, reply, "completed")
                connection.execute(
                    "UPDATE chat_requests SET status='completed',"
                    "assistant_message=? WHERE request_id=?",
                    (assistant, row["request_id"]))
                connection.execute(
                    "UPDATE jobs SET status='succeeded' WHERE id=?",
                    (row["job"],))
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM schema_inline_suggestions "
                "WHERE conv=?", (self.conv,)).fetchone()["n"]
            visible = connection.execute(
                "SELECT content FROM messages WHERE conv=? AND role='assistant'",
                (self.conv,)).fetchall()
        self.assertEqual(count, 0)
        self.assertTrue(all("[[MOD]]" not in row["content"] for row in visible))

    def test_unknown_mode_key_never_leaks_raw_marker(self):
        reply = "Anlıyorum.\n[[MOD]] uydurma_mod | bir şey"
        with app.db() as connection:
            row = self.request_row(connection)
            message_id = app._upsert_chat_assistant(
                connection, row, reply, "completed")
            stored = connection.execute(
                "SELECT content FROM messages WHERE id=?",
                (message_id,)).fetchone()["content"]
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM schema_inline_suggestions "
                "WHERE conv=?", (self.conv,)).fetchone()["n"]
        self.assertNotIn("[[MOD]]", stored)
        self.assertEqual(stored, "Anlıyorum.")
        self.assertEqual(count, 0)

    def test_reply_without_marker_is_untouched(self):
        with app.db() as connection:
            row = self.request_row(connection)
            message_id = app._upsert_chat_assistant(
                connection, row, "Düz bir yanıt.", "completed")
            stored = connection.execute(
                "SELECT content FROM messages WHERE id=?",
                (message_id,)).fetchone()["content"]
        self.assertEqual(stored, "Düz bir yanıt.")

    def test_streaming_holds_back_partial_marker(self):
        # Chunk sınırı işareti bölerse ham etiket bir an bile görünmemeli.
        for tail in ("[", "[[", "[[M", "[[MO", "[[MOD", "[[MOD]]"):
            self.assertTrue(
                app.suggestion_tail_started("merhaba " + tail), tail)
        self.assertFalse(app.suggestion_tail_started("merhaba"))
        self.assertFalse(app.suggestion_tail_started("bitti."))


class SchemaInlineSuggestionDecisionTests(HTTPTestCase):
    """Inline observation review is pathless; starting remains separate."""

    stamp = "2026-08-20 13:00"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)

    def pair(self, index, suggestion=False):
        text = ("sürekli duvar örüyorum" if suggestion else
                "önceki güvenli anlatım {}".format(index))
        with app.db() as connection:
            user = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'user',?,?,'completed')",
                (self.conv, text, self.stamp)).lastrowid
            assistant = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',?, 'completed')",
                (self.conv, self.stamp)).lastrowid
            job = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'succeeded',?,?)",
                (self.conv, self.stamp, self.stamp)).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,provider,model,created,updated) "
                "VALUES(?,?,?,?,?,'completed',?,?,?,?)",
                ("inline-decision-{}-{}".format(index, user), job, self.conv,
                 user, assistant, *app._configured_provider_model_snapshot(),
                 self.stamp, self.stamp))
            if suggestion:
                return user, assistant, connection.execute(
                    "INSERT INTO schema_inline_suggestions("
                    "conv,assistant_message,mode_key,evidence,status,created) "
                    "VALUES(?,?,'detached_protector','duvar örüyorum','open',?)",
                    (self.conv, assistant, self.stamp)).lastrowid
        return user, assistant, None

    def eligible_suggestion(self, index=2):
        for prior in range(2):
            self.pair(prior)
        return self.pair(index, suggestion=True)

    def post(self, action, suffix, **fields):
        return self.request("POST", "/api/schema-path", {
            "action": action, "conv_id": self.conv,
            "request_id": "inline-decision-{}-0001".format(suffix),
            **fields,
        })[:2]

    def test_accept_stays_pathless_then_only_chat_candidate_yes_starts_v5(self):
        _user, _assistant, suggestion = self.eligible_suggestion()
        before = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?", (self.conv,))["n"]
        status, body = self.post(
            "accept_suggestion", "accept", suggestion_id=suggestion)
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["active_path"])
        candidate = body["candidate"]
        self.assertTrue(candidate["approved_for_path"])
        self.assertIn("tanı değildir", candidate["statement"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?", (self.conv,))["n"],
            before)
        event = self.row(
            "SELECT * FROM schema_path_events WHERE action='accept_suggestion'")
        self.assertIsNone(event["path"])
        self.assertEqual(app.schema_accepted_suggestion_prompt(
            self.conversation_row(self.conv)), "")

        status, started = self.post(
            "start", "start", claim_id=candidate["id"])
        self.assertEqual(status, 409, started)
        self.assertEqual(started["error_code"],
                         "schema_v4_action_required")
        card = body["next_card"]
        self.assertEqual(card["kind"], "candidate_prompt")
        yes = next(item for item in card["actions"]
                   if item["action"] == "accept_candidate_chat")
        status, started = self.post(
            "accept_candidate_chat", "chat-yes", **yes["payload"])
        self.assertEqual(status, 200, started)
        self.assertIsNotNone(started["active_path"])
        self.assertEqual(started["active_path"]["claim_id"], candidate["id"])
        self.assertEqual(started["active_path"]["flow_version"], 5)
        self.assertEqual(started["presentation"], "chat_only")
        self.assertEqual(started["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(started["step"], "variable_explore")
        self.assertEqual(started["next_card"]["body"], "")
        self.assertEqual(started["next_card"]["actions"], [])
        self.assertIsNone(started["next_card"]["chat_binding"])
        self.assertEqual(
            started["next_card"]["prompt_delivery"]["status"], "queued")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?", (self.conv,))["n"],
            before + 1)

    def test_dismiss_is_pathless_idempotent_and_never_creates_claim(self):
        _user, _assistant, suggestion = self.eligible_suggestion()
        status, body = self.post(
            "dismiss_suggestion", "dismiss", suggestion_id=suggestion)
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["active_path"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_inline_suggestions WHERE id=?",
            (suggestion,))["status"], "dismissed")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)
        duplicate_status, _ = self.post(
            "dismiss_suggestion", "dismiss", suggestion_id=suggestion)
        self.assertEqual(duplicate_status, 200)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_events WHERE "
            "action='dismiss_suggestion'")["n"], 1)
        changed_status, _ = self.post(
            "dismiss_suggestion", "dismiss-again", suggestion_id=suggestion)
        self.assertEqual(changed_status, 409)

    def test_safety_invalidation_blocks_inline_accept(self):
        user, _assistant, suggestion = self.eligible_suggestion()
        with app.db() as connection:
            connection.execute(
                "INSERT INTO safety_events(conv,source_message,kind,created) "
                "VALUES(?,?,'crisis',?)", (self.conv, user, self.stamp))
        status, body = self.post(
            "accept_suggestion", "unsafe", suggestion_id=suggestion)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "suggestion_source_invalid")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)
        self.assertEqual(app.schema_path_payload(
            self.conv)["inline_suggestions"], [])


class SchemaAcceptedSuggestionPromptTests(HTTPTestCase):
    """Kabul, sahte kullanıcı turu veya gizli çalışma başlangıcı üretmemeli."""

    stamp = "2026-08-20 12:00"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        provider, model = app._configured_provider_model_snapshot()
        with app.db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO session_meta("
                "conv,schema_mode_enabled,schema_mode_initialized,"
                "schema_mode_provider,schema_mode_model,updated) "
                "VALUES(?,1,1,?,?,?)",
                (self.conv, provider, model, self.stamp))

    def seed(self, status="accepted", mode_key="detached_protector"):
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',?,"
                "'completed')", (self.conv, self.stamp)).lastrowid
            connection.execute(
                "INSERT INTO schema_inline_suggestions("
                "conv,assistant_message,mode_key,evidence,status,created) "
                "VALUES(?,?,?,'duvar örüyorum',?,?)",
                (self.conv, message_id, mode_key, status, self.stamp))

    def test_accepted_card_never_injects_a_work_start_prompt(self):
        self.seed()
        row = self.conversation_row(self.conv)
        self.assertEqual(app.schema_accepted_suggestion_prompt(row), "")
        self.assertEqual(app.schema_accepted_suggestion_prompt(row), "")
        with app.db() as connection:
            status = connection.execute(
                "SELECT status FROM schema_inline_suggestions WHERE conv=?",
                (self.conv,)).fetchone()["status"]
        self.assertEqual(status, "accepted")

    def test_open_card_does_not_open_the_work(self):
        # Henüz kabul edilmemiş kart açılış yaptırmamalı.
        self.seed(status="open")
        self.assertEqual(
            app.schema_accepted_suggestion_prompt(
                self.conversation_row(self.conv)), "")

    def test_dismissed_card_does_not_open_the_work(self):
        self.seed(status="dismissed")
        self.assertEqual(
            app.schema_accepted_suggestion_prompt(
                self.conversation_row(self.conv)), "")

    def test_safety_hold_silences_the_opening(self):
        # Kriz önceliği: güvenlik tutmasında bu katman susar.
        self.seed()
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv,))
        self.assertEqual(
            app.schema_accepted_suggestion_prompt(
                self.conversation_row(self.conv)), "")
