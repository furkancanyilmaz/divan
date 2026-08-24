"""Seansı ustanın yürütmesi: faz geçişi + teknik işaretleri.

Terapi butonlarla değil konuşmayla ilerlemeli. Ama model kendi klinik
kapısını AÇAMAMALI: geçiş koşulları sunucuda, butondakiyle aynı kalır.
"""

from support import HTTPTestCase, app


class SchemaMarkerSplitTests(HTTPTestCase):
    def test_all_markers_are_stripped_from_visible_text(self):
        raw = ("Anlıyorum.\n"
               "[[TEKNIK]] moda ses verme | korungan yan öne çıktı\n"
               "[[FAZ]] focus | duvar örüyorum\n"
               "[[MOD]] detached_protector | duvar örüyorum")
        text, suggestions, phase, technique, _, _ = app.split_schema_markers(raw)
        self.assertEqual(text, "Anlıyorum.")
        for mark in app.SCHEMA_ALL_MARKS:
            self.assertNotIn(mark, text)
        # Öneri artık bir listedir: bir mesajda birden çok yan olabilir.
        self.assertEqual(suggestions[0]["mode_key"], "detached_protector")
        self.assertEqual(phase["to_phase"], "focus")
        self.assertEqual(technique["technique"], "moda ses verme")

    def test_technique_marker_alone_is_still_stripped(self):
        # Regresyon: yalnız [[MOD]] arandığı için diğer işaretler
        # metinde kalıyordu.
        text, _, _, technique, _, _ = app.split_schema_markers(
            "Merhaba.\n[[TEKNIK]] yansıtma | duyduğumu yansıttım")
        self.assertEqual(text, "Merhaba.")
        self.assertEqual(technique["technique"], "yansıtma")

    def test_unknown_phase_target_is_ignored_but_stripped(self):
        text, _, phase, _, _, _ = app.split_schema_markers(
            "Merhaba.\n[[FAZ]] uydurma_faz | gerekçe")
        self.assertEqual(text, "Merhaba.")
        self.assertIsNone(phase)

    def test_streaming_holds_back_every_marker_prefix(self):
        for mark in app.SCHEMA_ALL_MARKS:
            for size in range(1, len(mark) + 1):
                self.assertTrue(
                    app.suggestion_tail_started("merhaba " + mark[:size]),
                    mark[:size])
        self.assertFalse(app.suggestion_tail_started("düz metin"))


class SchemaPhaseGateTests(HTTPTestCase):
    """Kapılar butondakiyle AYNI kalmalı; model zorlayamamalı."""

    stamp = "2026-08-20 12:00"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        with app.db() as connection:
            claim = connection.execute(
                "INSERT INTO psych_claims(source_conv,therapist,claim_type,"
                "title,statement,status,scope,sensitive,created,updated) "
                "VALUES(?,'young','schema_hypothesis','b','i','confirmed',"
                "'session',0,?,?)",
                (self.conv, self.stamp, self.stamp)).lastrowid
            self.path = connection.execute(
                "INSERT INTO schema_paths(conv,therapist,claim,phase,status,"
                "revision,created,updated) "
                "VALUES(?,'young',?,'explore','active',1,?,?)",
                (self.conv, claim, self.stamp, self.stamp)).lastrowid

    def path_row(self, connection):
        return connection.execute(
            "SELECT * FROM schema_paths WHERE id=?", (self.path,)).fetchone()

    def record(self, connection, seq, kind, value):
        connection.execute(
            "INSERT INTO schema_path_events(path,conv,seq,action,kind,value,"
            "authored_by,request_id,request_hash,created) "
            "VALUES(?,?,?,'record',?,?,'user',?,?,?)",
            (self.path, self.conv, seq, kind, value,
             "req-{:012d}".format(seq), "h{}".format(seq), self.stamp))

    def test_explore_gate_needs_trigger_and_need(self):
        with app.db() as connection:
            self.assertEqual(
                app.schema_phase_gate_blocked(
                    connection, self.path_row(connection)),
                "trigger_need_missing")
            self.record(connection, 1, "current_trigger", "patron bağırdı")
            self.record(connection, 2, "need", "güvende hissetmek")
            self.assertIsNone(
                app.schema_phase_gate_blocked(
                    connection, self.path_row(connection)))

    def test_focus_gate_needs_user_chosen_mode(self):
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET phase='focus' WHERE id=?",
                (self.path,))
            self.assertEqual(
                app.schema_phase_gate_blocked(
                    connection, self.path_row(connection)),
                "focus_not_chosen")

    def test_work_gate_needs_chosen_method(self):
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET phase='work' WHERE id=?",
                (self.path,))
            self.assertEqual(
                app.schema_phase_gate_blocked(
                    connection, self.path_row(connection)),
                "method_not_chosen")

    def test_model_cannot_skip_a_phase(self):
        # explore'dan doğrudan work'e atlama denemesi reddedilmeli.
        with app.db() as connection:
            self.record(connection, 1, "current_trigger", "patron bağırdı")
            self.record(connection, 2, "need", "güvende hissetmek")
            result = app.apply_model_phase_advance(
                connection, self.conv, {"to_phase": "work"})
            self.assertIsNone(result)
            self.assertEqual(self.path_row(connection)["phase"], "explore")

    def test_model_cannot_force_a_closed_gate(self):
        # Tetikleyici/ihtiyaç yokken focus'a geçiş sessizce düşmeli.
        with app.db() as connection:
            result = app.apply_model_phase_advance(
                connection, self.conv, {"to_phase": "focus"})
            self.assertIsNone(result)
            self.assertEqual(self.path_row(connection)["phase"], "explore")


class ProModeTechniqueTests(HTTPTestCase):
    """Pro mod verisi saklanır ama kendiliğinden ekrana çıkmaz."""

    def test_pro_mode_is_off_by_default_in_ui(self):
        html = open("index.html", encoding="utf-8").read()
        # Varsayılan kapalı olmalı; açık gelirse teknik herkese görünür.
        self.assertIn("let proModeOn=false;", html)
        # Düğme yalnız şema terapisinde görünmeli.
        self.assertIn("convData.therapist==='young'", html)

    def test_technique_is_not_written_without_schema_mode(self):
        # Şema modu kapalıyken teknik kaydı oluşmamalı.
        conv = self.conversation(therapist="freud")
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',"
                "'2026-08-20 12:00','completed')", (conv,)).lastrowid
            app._record_message_technique(
                connection, conv, message_id,
                {"technique": "yansıtma", "rationale": "x"}, None)
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM message_techniques "
                "WHERE conv=?", (conv,)).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_pro_mode_uses_the_real_bubble_class(self):
        """Regresyon: `.msg.assistant` diye bir sınıf yok.

        Pro mod açıldığında mevcut balonlar bu seçiciyle taranıyordu ve
        hiçbiri eşleşmediği için rozet hiç görünmüyordu. Balon sınıfı
        `.bubble`.
        """
        html = open("index.html", encoding="utf-8").read()
        start = html.index("function toggleProMode(")
        body = html[start:start + 700]
        self.assertIn("querySelectorAll('.bubble')", body)
        self.assertNotIn(".msg.assistant", body)

    def test_technique_badge_is_hidden_until_the_bubble_opens(self):
        """Rozet tıklamadan görünmemeli; açılınca görünmeli."""
        html = open("index.html", encoding="utf-8").read()
        self.assertIn(".proTechnique{display:none", html)
        # Pro mod kapalıyken gizli, açıkken görünür.
        self.assertIn("body.proModeOn .proTechnique{display:flex}", html)


class MultipleSchemaSuggestionTests(HTTPTestCase):
    """Bir mesajda birden çok yan tetiklenebilir; kullanıcı seçer."""

    def test_every_trigger_is_collected(self):
        raw = ("Burada iki şey duyuyorum.\n"
               "[[MOD]] detached_protector | duvar örüyorum\n"
               "[[MOD]] punitive_parent | hep kendimi suçlu hissediyorum")
        text, suggestions, _, _, _, _ = app.split_schema_markers(raw)
        self.assertEqual(text, "Burada iki şey duyuyorum.")
        self.assertEqual(
            [s["mode_key"] for s in suggestions],
            ["detached_protector", "punitive_parent"])

    def test_same_mode_twice_counts_once(self):
        suggestions = app.collect_schema_suggestions(
            "[[MOD]] detached_protector | a\n"
            "[[MOD]] detached_protector | b")
        self.assertEqual(len(suggestions), 1)

    def test_suggestion_count_is_capped(self):
        keys = list(app.SCHEMA_MODE_CANDIDATE_CATALOG)[:6]
        suggestions = app.collect_schema_suggestions(
            "\n".join("[[MOD]] {} | kanıt".format(k) for k in keys))
        self.assertEqual(len(suggestions), app.SCHEMA_SUGGESTION_MAX)

    def test_unknown_keys_are_skipped_not_leaked(self):
        text, suggestions, _, _, _, _ = app.split_schema_markers(
            "Merhaba.\n[[MOD]] uydurma_mod | x\n"
            "[[MOD]] punitive_parent | kendimi suçluyorum")
        self.assertEqual(text, "Merhaba.")
        self.assertEqual(
            [s["mode_key"] for s in suggestions], ["punitive_parent"])

    def test_prompt_routes_multiple_triggers_to_separate_cards(self):
        # Aday seçimi görünür model metninde yönlendirilmez. Her olasılık
        # kaynak-alıntılı kart olur; kullanıcı kartta sırayla karar verir.
        source = open("server.py", encoding="utf-8").read()
        self.assertIn("BİRDEN ÇOK yan tetiklendiyse", source)
        self.assertIn("aday listesini ya da adaylar arasında seçim", source)
        self.assertIn("sorusunu konuşmaya", source)
        self.assertNotIn("Hangisiyle başlamak istersin?", source)

    def test_migration_widens_the_unique_constraint(self):
        # Mesaj başına tek öneri kısıtı, çoklu öneriyi engelliyordu.
        with app.db() as connection:
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE "
                "name='schema_inline_suggestions'").fetchone()[0]
        self.assertIn("UNIQUE(assistant_message,mode_key)", sql)


class TechniquePromptWithoutPathTests(HTTPTestCase):
    """Teknik bildirimi etkin çalışma yolu olmadan da istenmeli.

    Regresyon: prompt `if not path_row: return ""` ile kesiliyordu.
    Sıradan bir Kerem sohbetinde yol olmadığı için model [[TEKNIK]]
    satırını hiç üretmiyor, Pro modda gösterilecek veri oluşmuyordu.
    """

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

    def test_technique_is_requested_without_an_active_path(self):
        with app.db() as connection:
            self.assertIsNone(
                app.schema_active_path_row(connection, self.conv))
        prompt = app.schema_flow_marker_prompt(
            self.conversation_row(self.conv))
        self.assertIn("[[TEKNIK]]", prompt)
        # Yol yokken faz geçişi istenmemeli.
        self.assertNotIn("[[FAZ]]", prompt)

    def test_technique_is_stored_with_empty_phase(self):
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',?,"
                "'completed')", (self.conv, self.stamp)).lastrowid
            app._record_message_technique(
                connection, self.conv, message_id,
                {"technique": "yansıtma", "rationale": "duyduğumu yansıttım"},
                None)
            row = connection.execute(
                "SELECT technique,phase FROM message_techniques "
                "WHERE message=?", (message_id,)).fetchone()
        self.assertEqual(row["technique"], "yansıtma")
        self.assertEqual(row["phase"], "")

    def test_safety_hold_silences_the_technique_prompt(self):
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv,))
        self.assertEqual(
            app.schema_flow_marker_prompt(
                self.conversation_row(self.conv)), "")


class ProModeBadgeOrderTests(HTTPTestCase):
    """Teknik rozeti yanıt araçlarının ÜSTÜNDE durmalı.

    Regresyon: rozet balonun en sonuna ekleniyordu. Balona dokununca
    önce "Yanıtla / Daha sade / …" menüsü doluyor, teknik ekranın
    aşağısında kalıp görülmüyordu.
    """

    def test_badge_is_visible_without_tapping(self):
        """Pro mod açıkken teknik DOKUNMADAN, mesajın altında görünmeli.

        Menüye gömülüyken kullanıcı bulamıyordu: menü kapalıyken rozet
        de gizli kalıyordu.
        """
        html = open("index.html", encoding="utf-8").read()
        # Pro mod açıkken rozet dokunmaya gerek kalmadan görünür.
        self.assertIn("body.proModeOn .proTechnique{display:flex}", html)
        # Rozet balonun içinde, menünün üstünde durur.
        self.assertIn("bubble.insertBefore(kutu,araclar)", html)
        self.assertIn("bubble.insertBefore(rozet,tools)", html)


class MarkerOnSameLineTests(HTTPTestCase):
    """İşaret cümleyle aynı satırdaysa YANIT SİLİNMEMELİ.

    Gerçek hata: satırın tamamı atılıyordu. Model işareti cümlenin
    sonuna eklediğinde kısa yanıtlar tamamen boşalıyor, kullanıcı boş
    balon görüyordu.
    """

    def test_text_before_the_marker_is_kept(self):
        text, _, _, technique, _, _ = app.split_schema_markers(
            "Bu sesi söylediniz. [[TEKNIK]] moda ses verme | gerekçe")
        self.assertEqual(text, "Bu sesi söylediniz.")
        self.assertEqual(technique["technique"], "moda ses verme")

    def test_reply_never_becomes_empty(self):
        for raw in (
            "Anlıyorum. [[MOD]] punitive_parent | kanıt",
            "Devam edelim. [[FAZ]] focus | gerekçe",
            "Merhaba. [[TEKNIK]] a | b [[MOD]] punitive_parent | c",
            "Tek satır. [[TEKNIK]] yansıtma | neden",
        ):
            text, _, _, _, _, _ = app.split_schema_markers(raw)
            self.assertTrue(text.strip(), raw)
            for mark in app.SCHEMA_ALL_MARKS:
                self.assertNotIn(mark, text)

    def test_marker_only_line_is_removed_entirely(self):
        # Satırda işaretten başka bir şey yoksa satır tümüyle gider.
        text, _, _, _, _, _ = app.split_schema_markers(
            "Anlıyorum.\n[[TEKNIK]] moda ses verme | gerekçe")
        self.assertEqual(text, "Anlıyorum.")

    def test_marker_at_line_start_does_not_eat_next_line(self):
        text, _, _, _, _, _ = app.split_schema_markers(
            "[[TEKNIK]] moda ses verme | gerekçe\nBu sesi söylediniz.")
        self.assertEqual(text, "Bu sesi söylediniz.")


class ProModeReachableTests(HTTPTestCase):
    """Pro mod, üst şerit kapalıyken de erişilebilir olmalı.

    Gerçek hata: düğme `topbarContents` içindeydi ve o şerit varsayılan
    olarak `display:none`. Kullanıcı Pro modu hiç bulamıyordu.
    """

    def test_message_menu_has_a_pro_mode_toggle(self):
        html = open("index.html", encoding="utf-8").read()
        self.assertIn("Hangi tekniği kullandı? (Pro mod)", html)
        self.assertIn("Tekniği gizle (Pro mod)", html)
        # Yalnız şema terapisinde görünmeli.
        self.assertIn("if(proModeAvailable()){", html)
