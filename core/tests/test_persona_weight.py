from unittest import mock

from support import HTTPTestCase, app


class PersonaWeightArchitectureTests(HTTPTestCase):

    def test_every_therapist_has_one_nonempty_distinct_fingerprint(self):
        self.assertEqual(
            set(app.THERAPY_FINGERPRINTS),
            set(app.THERAPISTS),
        )

        fingerprints = []
        for therapist in app.THERAPISTS:
            with self.subTest(therapist=therapist):
                raw_fingerprint = app.THERAPY_FINGERPRINTS[therapist]
                fingerprint = app.therapy_fingerprint(therapist)
                self.assertIsInstance(fingerprint, str)
                self.assertTrue(raw_fingerprint.strip())
                self.assertTrue(fingerprint.strip())
                # Ortak çıpalar (yorum cesareti, ekol üçgeni) ham parmak
                # izinin ardına eklenir; koruyucu satır her zaman sonda kalır.
                expected_prefix = raw_fingerprint
                if expected_prefix.endswith(
                        app.THERAPY_FINGERPRINT_GUARDRAIL):
                    expected_prefix = expected_prefix[
                        :-len(app.THERAPY_FINGERPRINT_GUARDRAIL)].rstrip()
                self.assertTrue(fingerprint.startswith(expected_prefix))
                self.assertTrue(
                    fingerprint.endswith(
                        app.THERAPY_FINGERPRINT_GUARDRAIL))
                fingerprints.append(fingerprint.strip())

        self.assertEqual(len(fingerprints), len(app.THERAPISTS))
        self.assertEqual(len(set(fingerprints)), len(app.THERAPISTS))

    def test_each_therapy_prompt_ends_with_its_fingerprint_after_context(self):
        previous = self.conversation(
            therapist="freud", title="Paylaşılan önceki seans")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(therapist,kind,content,approved,scope,"
                "sensitive,created,updated) VALUES("
                "'freud','fact','ORTAK-FINGERPRINT-HAFIZASI',1,'shared',"
                "0,?,?)",
                (app.now(), app.now()),
            )
            conn.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,"
                "approved,scope,sensitive,updated) VALUES("
                "?,'terapi','freud','ORTAK-FINGERPRINT-NOTU',?,"
                "1,'shared',0,?)",
                (previous, app.now(), app.now()),
            )

        for therapist in app.THERAPISTS:
            with self.subTest(therapist=therapist):
                conv_id = self.conversation(
                    therapist=therapist,
                    title="{} fingerprint seansı".format(therapist),
                )
                prompt = self.system_prompt(conv_id)
                fingerprint = app.therapy_fingerprint(therapist)

                self.assertEqual(prompt.count(fingerprint), 1)
                self.assertTrue(prompt.endswith(fingerprint))
                self.assertLess(
                    prompt.index("ORTAK-FINGERPRINT-HAFIZASI"),
                    prompt.index(fingerprint),
                )
                self.assertLess(
                    prompt.index("ORTAK-FINGERPRINT-NOTU"),
                    prompt.index(fingerprint),
                )
                self.assertIn(app.METHOD_SAFETY, prompt)
                self.assertIn(app.COLLABORATIVE_DISCOVERY, prompt)

    def test_fingerprints_apply_only_to_their_therapy_prompt(self):
        freud_therapy = self.system_prompt(
            self.conversation(therapist="freud"))
        freud_lesson = self.system_prompt(
            self.conversation(
                mode="ders",
                therapist="freud",
                title="Freud fingerprint dersi",
            ))

        self.assertIn(app.therapy_fingerprint("freud"), freud_therapy)
        for therapist, fingerprint in app.THERAPY_FINGERPRINTS.items():
            with self.subTest(therapist=therapist):
                if therapist != "freud":
                    self.assertNotIn(fingerprint, freud_therapy)
                self.assertNotIn(fingerprint, freud_lesson)

    def test_freud_late_anchor_keeps_azizim_as_an_occasional_signature(self):
        fingerprint = app.therapy_fingerprint("freud")
        prompt = self.system_prompt(
            self.conversation(therapist="freud"))

        self.assertIn(
            'Hitap: "Azizim" senin doğal imza hitabındır.',
            fingerprint,
        )
        self.assertIn("İlk karşılıkta kullan", fingerprint)
        self.assertIn("ara sıra yeniden kullan", fingerprint)
        self.assertIn("Arka arkaya tekrarlama", fingerprint)
        self.assertNotIn('her yanıtta "azizim" kullanma', fingerprint)
        self.assertTrue(prompt.endswith(fingerprint))

    def test_shared_therapy_contract_is_modality_neutral(self):
        prompt = app.THERAPY_PROMPT

        self.assertNotIn("Ton örneği (psikodinamik", prompt)
        self.assertNotIn("Yine, diyorsunuz", prompt)
        self.assertNotIn(
            "Hayır kelimesi dilinizin ucuna geldiği o anda",
            prompt,
        )
        self.assertIn("kendi ekol", prompt.casefold())


class ActiveMethodSalienceTests(HTTPTestCase):

    def _propose_and_consent(self, conv_id, method):
        status, proposed, _ = self.request(
            "POST",
            "/api/technique-run",
            {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 4,
            },
        )
        self.assertEqual(status, 200, proposed)
        status, consented, _ = self.request(
            "POST",
            "/api/technique-run",
            {
                "conv_id": conv_id,
                "id": proposed["run"]["id"],
                "action": "consent",
                "confirmed": True,
            },
        )
        self.assertEqual(status, 200, consented)
        return consented["run"]

    def test_selected_map_method_is_salient_near_the_prompt_end(self):
        therapist = "beck"
        method = app.method_records(therapist)[2]
        unselected = [
            row for row in app.method_records(therapist)
            if row["key"] != method["key"]
        ]
        status, created, _ = self.request(
            "POST",
            "/api/new",
            {
                "mode": "terapi",
                "therapist": therapist,
                "map_node_id": method["node_id"],
            },
        )
        self.assertEqual(status, 200, created)

        prompt = self.system_prompt(created["id"])
        fingerprint = app.therapy_fingerprint(therapist)
        selected = prompt.rfind(method["description"])

        self.assertGreater(selected, prompt.index(app.METHOD_SAFETY))
        self.assertLess(selected, prompt.index(fingerprint))
        self.assertTrue(prompt.endswith(fingerprint))
        for other in unselected:
            with self.subTest(unselected=other["key"]):
                self.assertNotIn(other["description"], prompt)

    def test_active_method_is_the_only_detailed_method_and_precedes_fingerprint(self):
        therapist = "beck"
        method = app.method_records(therapist)[2]
        unselected = [
            row for row in app.method_records(therapist)
            if row["key"] != method["key"]
        ]
        conv_id = self.conversation(therapist=therapist)
        self._propose_and_consent(conv_id, method)

        prompt = self.system_prompt(conv_id)
        active_at = prompt.rfind(method["description"])
        fingerprint_at = prompt.index(app.therapy_fingerprint(therapist))

        self.assertIn("## Bu yanıtta baskın aktif yöntem", prompt)
        self.assertGreater(
            active_at,
            prompt.index("## Bu yanıtta baskın aktif yöntem"),
        )
        self.assertLess(active_at, fingerprint_at)
        self.assertIn("Devam eden teknik çalışması", prompt)
        self.assertLess(fingerprint_at - active_at, 1600)
        for other in unselected:
            with self.subTest(unselected=other["key"]):
                self.assertNotIn(other["description"], prompt)

    def test_unstructured_therapy_gets_method_names_without_descriptions(self):
        for therapist in app.THERAPISTS:
            with self.subTest(therapist=therapist):
                conv_id = self.conversation(therapist=therapist)
                prompt = self.system_prompt(conv_id)
                for method in app.method_records(therapist):
                    self.assertIn(method["name"], prompt)
                    self.assertNotIn(method["description"], prompt)

    def test_menu_selected_method_precedes_the_final_fingerprint_sent_to_model(self):
        therapist = "beck"
        method = app.method_records(therapist)[1]
        conv_id = self.conversation(therapist=therapist)
        captured = {}

        def capture_request(payload):
            captured.update(payload)
            raise app.ProviderError(
                "test_capture",
                "İstek yalnızca prompt sırasını sınamak için durduruldu.",
            )

        with mock.patch.object(
                app, "provider_request", side_effect=capture_request):
            status, _, _ = self.request(
                "POST",
                "/api/chat",
                {
                    "conv_id": conv_id,
                    "message": "Bu yöntemle çalışmayı değerlendirelim.",
                    "method_key": method["key"],
                },
            )

        self.assertEqual(status, 200)
        self.assertIn("messages", captured)
        system = captured["messages"][0]["content"]
        fingerprint = app.therapy_fingerprint(therapist)
        selected_at = system.rfind(method["description"])

        self.assertEqual(captured["messages"][0]["role"], "system")
        self.assertGreater(selected_at, system.index(app.METHOD_SAFETY))
        self.assertLess(selected_at, system.index(fingerprint))
        # Sistem isteminin sonunda tur çıpası durur; onun kuyruğu da
        # koruyucu satırla biten kompakt parmak izidir.
        self.assertTrue(system.endswith(
            app.therapy_fingerprint_compact(therapist)))


class StructuredObserverAndLessonVoiceTests(HTTPTestCase):

    def _consent_method(self, conv_id, method):
        status, proposed, _ = self.request(
            "POST",
            "/api/technique-run",
            {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 4,
            },
        )
        self.assertEqual(status, 200, proposed)
        status, consented, _ = self.request(
            "POST",
            "/api/technique-run",
            {
                "conv_id": conv_id,
                "id": proposed["run"]["id"],
                "action": "consent",
                "confirmed": True,
            },
        )
        self.assertEqual(status, 200, consented)
        return consented

    def test_chair_observers_keep_the_selected_school_voice_and_json_guard(self):
        cases = (
            ("perls", "perls:method:two-chair-conflict"),
            ("young", "young:method:chair-dialogue"),
            ("satir", "satir:method:parts-party"),
        )
        for therapist, node_id in cases:
            with self.subTest(therapist=therapist):
                conv_id = self.conversation(therapist=therapist)
                method = next(
                    row for row in app.method_records(therapist)
                    if row["node_id"] == node_id)
                consented = self._consent_method(conv_id, method)
                chair_id = consented["chairwork"]["id"]
                with app.db() as conn:
                    conv = conn.execute(
                        "SELECT * FROM conversations WHERE id=?",
                        (conv_id,),
                    ).fetchone()
                    chair = app.chair_run_row(
                        conn, conv_id, chair_id)
                    messages = app.build_chair_guidance_messages(
                        conn, conv, chair)
                system = messages[0]["content"]
                self.assertIn(method["description"], system)
                self.assertIn(app.therapy_fingerprint(therapist), system)
                self.assertIn("JSON sözleşmesi", system)
                self.assertTrue(system.endswith(
                    "yalnız istenen JSON nesnesini döndür ve anahtarlarını "
                    "değiştirme."))

    def test_imagery_observer_gets_youngs_selected_method_and_voice(self):
        therapist = "young"
        conv_id = self.conversation(therapist=therapist)
        method = next(
            row for row in app.method_records(therapist)
            if row["node_id"] == app.IMAGERY_METHOD_NODE_ID)
        consented = self._consent_method(conv_id, method)
        status, created, _ = self.request(
            "POST",
            "/api/imagery-work",
            {
                "conv_id": conv_id,
                "action": "create",
                "technique_run_id": consented["run"]["id"],
            },
        )
        self.assertEqual(status, 200, created)
        imagery_id = created["imagerywork"]["id"]
        with app.db() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,),
            ).fetchone()
            imagery = app.imagery_run_row(
                conn, conv_id, imagery_id)
            messages = app.build_imagery_guidance_messages(
                conn, conv, imagery)
        system = messages[0]["content"]
        self.assertIn("## Seçili yöntem", system)
        self.assertIn(method["description"], system)
        self.assertIn(app.therapy_fingerprint(therapist), system)
        self.assertIn("yalnız istenen JSON nesnesini döndür", system)

    def test_every_lesson_reasserts_voice_after_long_context(self):
        for therapist in app.THERAPISTS:
            with self.subTest(therapist=therapist):
                conv_id = self.conversation(
                    mode="ders",
                    therapist=therapist,
                    title="Uzun bağlamlı ders",
                )
                with app.db() as conn:
                    conn.execute(
                        "INSERT INTO memories(therapist,kind,content,approved,"
                        "scope,sensitive,created,updated) VALUES("
                        "?,'fact','DERS-SONU-BAĞLAMI',1,'private',0,?,?)",
                        (therapist, app.now(), app.now()),
                    )
                prompt = self.system_prompt(conv_id)
                self.assertIn("DERS-SONU-BAĞLAMI", prompt)
                self.assertTrue(prompt.endswith(app.LESSON_VOICE_CONTRACT))
                self.assertNotIn(
                    app.therapy_fingerprint(therapist), prompt)
