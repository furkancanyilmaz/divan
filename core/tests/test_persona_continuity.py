from support import HTTPTestCase, app


class LateTurnContinuityTests(HTTPTestCase):

    def _conversation_row(self, conv_id):
        with app.db() as conn:
            return conn.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,),
            ).fetchone()

    @staticmethod
    def _anchor_text(payload):
        messages = payload["messages"]
        return next(
            item["content"] for item in reversed(messages)
            if "Son tur süreklilik kilidi" in item["content"])

    def test_every_therapist_has_a_specific_late_turn_anchor(self):
        anchors = []
        for therapist in app.THERAPISTS:
            with self.subTest(therapist=therapist):
                conv_id = self.conversation(therapist=therapist)
                conv = self._conversation_row(conv_id)
                anchor = app.late_turn_anchor(conv)

                self.assertIn("Son tur süreklilik kilidi", anchor)
                self.assertIn(app.THERAPISTS[therapist]["name"], anchor)
                self.assertIn(
                    app.therapy_fingerprint_compact(therapist), anchor)
                self.assertIn("başka ekolleri", anchor)
                self.assertIn("başka bir ustaya da aynen uyuyor mu", anchor)
                anchors.append(anchor)

        self.assertEqual(len(anchors), len(set(anchors)))

    def test_long_generic_history_is_followed_by_lock_then_latest_user(self):
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "auto")
        conv_id = self.conversation(therapist="ferenczi")
        with app.db() as conn:
            for index in range(24):
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (
                        conv_id,
                        "user" if index % 2 == 0 else "assistant",
                        (
                            "KULLANICI-{}".format(index)
                            if index % 2 == 0
                            else "GENEL-AI-TERAPİSTİ-SESLENİŞİ-{}".format(
                                index)
                        ),
                        app.now(),
                    ),
                )
        row, created = app.begin_chat_request(
            conv_id,
            "Beni yine genel bir terapist gibi karşılama.",
            request_id="persona-continuity-long-001",
        )
        self.assertTrue(created)

        _conv, payload = app._chat_prompt_payload(row)
        messages = payload["messages"]

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(
            [item["role"] for item in messages].count("system"), 1)
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn(
            app.therapy_fingerprint("ferenczi"),
            messages[0]["content"],
        )
        self.assertEqual(
            messages[-1]["content"],
            "Beni yine genel bir terapist gibi karşılama.",
        )
        self.assertLessEqual(len(messages) - 1, app.LOCAL_HISTORY_LIMIT)
        roles = [item["role"] for item in messages[1:]]
        self.assertTrue(roles)
        self.assertEqual(roles[0], "user")
        self.assertEqual(roles[-1], "user")
        self.assertTrue(all(
            left != right for left, right in zip(roles, roles[1:])))
        self.assertLessEqual(
            sum(len(item["content"]) for item in messages[1:]),
            app.CHAT_HISTORY_CHAR_LIMIT,
        )

    def test_requested_method_is_reasserted_without_implicit_consent(self):
        therapist = "beck"
        method = app.method_records(therapist)[1]
        conv_id = self.conversation(therapist=therapist)
        row, _ = app.begin_chat_request(
            conv_id,
            "Bu yönteme bakalım.",
            request_id="persona-method-lock-001",
            method_key=method["key"],
        )

        _conv, payload = app._chat_prompt_payload(row)
        anchor = self._anchor_text(payload)

        self.assertIn(method["name"], anchor)
        self.assertIn("Durum: requested", anchor)
        self.assertIn("açık onay iste", anchor)
        for other in app.method_records(therapist):
            if other["key"] != method["key"]:
                self.assertNotIn(other["description"], anchor)

    def test_philosopher_gets_thought_anchor_not_therapy_anchor(self):
        conv_id = self.conversation(
            mode="ders",
            submode="serbest",
            therapist="vaclav_smil",
            title="Smil ile ders",
        )
        row, _ = app.begin_chat_request(
            conv_id,
            "Enerji dönüşümleri neden yavaş olur?",
            request_id="persona-philosophy-lock-001",
        )

        _conv, payload = app._chat_prompt_payload(row)
        anchor = self._anchor_text(payload)

        self.assertIn("Volkan Sayılar", anchor)
        self.assertIn(
            app.philosophy_fingerprint("vaclav_smil"), anchor)
        self.assertIn("Birim ve büyüklük mertebesi", anchor)
        self.assertIn("Psikoterapiye", anchor)
        self.assertNotIn("klinik parmak izin", anchor)

    def test_therapist_lesson_gets_master_specific_late_anchor(self):
        anchors = []
        for therapist in app.THERAPISTS:
            with self.subTest(therapist=therapist):
                conv_id = self.conversation(
                    mode="ders",
                    submode="serbest",
                    therapist=therapist,
                    title="{} dersi".format(therapist),
                )
                conv = self._conversation_row(conv_id)
                anchor = app.late_turn_anchor(conv)

                self.assertIn(app.THERAPISTS[therapist]["name"], anchor)
                self.assertIn(app.THERAPISTS[therapist]["school"], anchor)
                self.assertIn("Nötr ansiklopedi", anchor)
                for method in app.method_records(therapist):
                    self.assertIn(method["name"], anchor)
                self.assertNotIn(
                    app.therapy_fingerprint(therapist), anchor)
                anchors.append(anchor)

        self.assertEqual(len(anchors), len(set(anchors)))

    def test_provider_adapters_keep_continuity_instruction_and_latest_user(self):
        conv_id = self.conversation(therapist="rogers")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "assistant", "Eski model yanıtı", app.now()),
            )
        row, _ = app.begin_chat_request(
            conv_id,
            "Şimdi beni doğru anlamaya çalış.",
            request_id="persona-provider-lock-001",
        )
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET provider='openai',model='gpt-test' "
                "WHERE request_id=?",
                (row["request_id"],),
            )
            row = app.chat_request_row(row["request_id"], conn)
        _conv, payload = app._chat_prompt_payload(row)

        anthropic_system, anthropic_turns = app.anthropic_messages(
            payload["messages"])
        openai_instructions, openai_turns = app.openai_response_input(
            payload["messages"])

        for instructions in (anthropic_system, openai_instructions):
            self.assertIn("Son tur süreklilik kilidi", instructions)
            self.assertIn(app.therapy_fingerprint("rogers"), instructions)
        self.assertEqual(
            anthropic_turns[-1]["content"],
            "Şimdi beni doğru anlamaya çalış.",
        )
        self.assertEqual(
            openai_turns[-1]["content"],
            "Şimdi beni doğru anlamaya çalış.",
        )

    def test_local_payload_uses_one_system_and_preserves_raw_database_turn(self):
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_model", "auto")
        conv_id = self.conversation(therapist="beck")
        raw = "O anda aklımdan başarısız olacağım geçti."
        row, _ = app.begin_chat_request(
            conv_id,
            raw,
            request_id="persona-local-envelope-001",
        )

        _conv, payload = app._chat_prompt_payload(row)
        messages = payload["messages"]

        self.assertEqual(
            [item["role"] for item in messages].count("system"), 1)
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn(app.therapy_fingerprint("beck"),
                      messages[0]["content"])
        self.assertEqual(raw, messages[-1]["content"])
        with app.db() as conn:
            stored = conn.execute(
                "SELECT content FROM messages WHERE id=?",
                (row["user_message"],),
            ).fetchone()["content"]
        self.assertEqual(stored, raw)
