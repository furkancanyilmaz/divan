from support import HTTPTestCase, app


class ChatContextBudgetTests(HTTPTestCase):

    @staticmethod
    def _payload_chars(payload):
        return sum(
            len(str(message.get("content") or ""))
            for message in payload["messages"]
        )

    def _insert_history(self, conv_id, count, chars_per_message=1800,
                        prefix="ESKI"):
        with app.db() as conn:
            for index in range(count):
                marker = "{}-{:02d}|".format(prefix, index)
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (
                        conv_id,
                        "user" if index % 2 == 0 else "assistant",
                        marker + ("x" * chars_per_message),
                        "2026-07-20 10:{:02d}".format(index % 60),
                    ),
                )

    def _payload(self, conv_id, provider, message, request_id):
        app.set_setting("llm_provider", provider)
        row, created = app.begin_chat_request(
            conv_id,
            message,
            request_id=request_id,
        )
        self.assertTrue(created)
        # Ortam değişkeni sağlayıcı ayarını gölgelerse bile test edilen durable
        # istek anlık sağlayıcı seçimini açıkça taşısın.
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET provider=?,model=? "
                "WHERE request_id=?",
                (provider, "test-model", request_id),
            )
            row = app.chat_request_row(request_id, conn)
        return app._chat_prompt_payload(row)[1]

    def test_payload_respects_each_provider_input_and_output_budget(self):
        app.set_setting("context_window_tokens", "8192")
        for index, provider in enumerate(app.PROVIDERS):
            with self.subTest(provider=provider):
                conv_id = self.conversation(therapist="freud")
                self._insert_history(
                    conv_id, 10, chars_per_message=1500,
                    prefix="{}-TARIH".format(provider.upper()))
                latest = "SON-{}|{}".format(provider, "ğ" * 240)
                payload = self._payload(
                    conv_id,
                    provider,
                    latest,
                    "context-budget-provider-{:02d}".format(index),
                )

                self.assertLessEqual(
                    self._payload_chars(payload),
                    app.chat_input_char_budget(provider, 8192),
                )
                self.assertEqual(
                    payload["max_tokens"],
                    app.chat_output_token_budget(provider, 8192),
                )
                self.assertEqual(payload["messages"][-1]["role"], "user")
                self.assertEqual(
                    payload["messages"][-1]["content"], latest)

    def test_latest_user_message_is_last_and_never_truncated(self):
        app.set_setting("context_window_tokens", "8192")
        conv_id = self.conversation(therapist="ferenczi")
        self._insert_history(
            conv_id, 12, chars_per_message=2400, prefix="UZUN-GECMIS")
        latest = "KESILMEMELI|" + "".join(
            str(index % 10) for index in range(1200))

        payload = self._payload(
            conv_id,
            "lmstudio",
            latest,
            "context-budget-latest-user",
        )

        self.assertEqual(payload["messages"][-1], {
            "role": "user",
            "content": latest,
        })
        self.assertLessEqual(
            self._payload_chars(payload),
            app.chat_input_char_budget("lmstudio", 8192),
        )

    def test_lmstudio_has_one_system_message_and_strict_alternation(self):
        app.set_setting("context_window_tokens", "32768")
        conv_id = self.conversation(therapist="beck")
        irregular_roles = (
            "assistant", "assistant", "user", "user", "assistant",
            "user", "assistant", "assistant", "user",
        )
        with app.db() as conn:
            for index, role in enumerate(irregular_roles):
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (
                        conv_id,
                        role,
                        "{}-{}".format(role, index),
                        "2026-07-20 10:{:02d}".format(index),
                    ),
                )
        latest = "Şu anki otomatik düşünceme dönelim."

        payload = self._payload(
            conv_id,
            "lmstudio",
            latest,
            "context-budget-local-roles",
        )
        messages = payload["messages"]
        roles = [message["role"] for message in messages]

        self.assertEqual(roles[0], "system")
        self.assertEqual(roles.count("system"), 1)
        local_roles = roles[1:]
        self.assertTrue(local_roles)
        self.assertEqual(local_roles[0], "user")
        self.assertEqual(local_roles[-1], "user")
        self.assertTrue(all(
            left != right
            for left, right in zip(local_roles, local_roles[1:])
        ))
        self.assertEqual(messages[-1]["content"], latest)

    def test_8k_window_discards_long_old_history(self):
        app.set_setting("context_window_tokens", "8192")
        conv_id = self.conversation(therapist="rogers")
        self._insert_history(
            conv_id, 10, chars_per_message=3000, prefix="SEKIZ-K-ESKI")
        latest = "SEKIZ-K-SON|" + ("y" * 400)

        payload = self._payload(
            conv_id,
            "lmstudio",
            latest,
            "context-budget-prunes-old",
        )
        joined = "\n".join(
            message["content"] for message in payload["messages"])
        non_system = [
            message for message in payload["messages"]
            if message["role"] != "system"
        ]

        self.assertNotIn("SEKIZ-K-ESKI-00|", joined)
        self.assertLess(len(non_system), 11)
        self.assertEqual(non_system[-1]["content"], latest)
        self.assertLessEqual(
            self._payload_chars(payload),
            app.chat_input_char_budget("lmstudio", 8192),
        )

    def test_local_budget_keeps_a_clipped_complete_pair_not_assistant_alone(self):
        app.set_setting("context_window_tokens", "8192")
        conv_id = self.conversation(therapist="beck")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?, 'user', ?, ?)",
                (conv_id, "SON-ESKI-KULLANICI|" + ("u" * 7000), app.now()))
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?, 'assistant', ?, ?)",
                (conv_id, "SON-ESKI-ASISTAN|" + ("a" * 7000), app.now()))

        payload = self._payload(
            conv_id,
            "lmstudio",
            "YENI-KULLANICI",
            "context-budget-local-pair",
        )
        live = payload["messages"][1:]
        roles = [item["role"] for item in live]
        joined = "\n".join(item["content"] for item in live)

        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertIn("SON-ESKI-KULLANICI|", joined)
        self.assertIn("SON-ESKI-ASISTAN|", joined)
        self.assertEqual(live[-1]["content"], "YENI-KULLANICI")

    def test_small_window_keeps_approved_context_and_live_pair(self):
        app.set_setting("context_window_tokens", "8192")
        app.set_setting("profile", "PROFIL-KAPSUL|" + ("p" * 4600))
        conv_id = self.conversation(therapist="bowen")
        with app.db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES("
                "?,'terapi','bowen','FORMULASYON-KAYNAGI',?,"
                "1,'therapist',0,?)",
                (conv_id, app.now(), app.now()),
            ).lastrowid
            formulation_id = conn.execute(
                "INSERT INTO formulations("
                "mode,therapist,content,note_count,through_note_id,created) "
                "VALUES('terapi','bowen',?,1,?,?)",
                ("FORMULASYON-KAPSUL|" + ("f" * 8400),
                 note_id, app.now()),
            ).lastrowid
            conn.execute(
                "INSERT INTO formulation_evidence("
                "formulation,note,created) VALUES(?,?,?)",
                (formulation_id, note_id, app.now()),
            )
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?, 'user', ?, ?)",
                (conv_id, "YAKIN-KULLANICI|" + ("u" * 1200), app.now()))
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?, 'assistant', ?, ?)",
                (conv_id, "YAKIN-ASISTAN|" + ("a" * 1200), app.now()))

        payload = self._payload(
            conv_id,
            "lmstudio",
            "Şimdiki sözüm.",
            "context-budget-lean-capsule",
        )
        system = payload["messages"][0]["content"]
        joined = "\n".join(
            item["content"] for item in payload["messages"][1:])

        # Kırpılmış tam kayıt zaten canlı çifte ayrılan rezervin yanına
        # sığıyorsa onu gereksiz yere düşürme; aksi halde lean kapsül kullan.
        self.assertIn(payload["_context_level"], ("full", "lean"))
        self.assertIn("FORMULASYON-KAPSUL|", system)
        self.assertIn("YAKIN-KULLANICI|", joined)
        self.assertIn("YAKIN-ASISTAN|", joined)
        self.assertLessEqual(
            self._payload_chars(payload),
            app.chat_input_char_budget("lmstudio", 8192),
        )

    def test_single_user_message_larger_than_window_raises_clear_error(self):
        app.set_setting("context_window_tokens", "8192")
        app.set_setting("llm_provider", "lmstudio")
        conv_id = self.conversation(therapist="freud")
        latest = "TEK-COK-BUYUK-MESAJ|" + ("z" * 49000)
        row, created = app.begin_chat_request(
            conv_id,
            latest,
            request_id="context-budget-too-large",
        )
        self.assertTrue(created)

        with self.assertRaises(app.ProviderError) as caught:
            app._chat_prompt_payload(row)

        self.assertEqual(
            caught.exception.code, "context_window_too_small")
        self.assertIn("bağlam", str(caught.exception).casefold())


if __name__ == "__main__":
    import unittest
    unittest.main()
