import json
from urllib.parse import urlencode

from support import HTTPTestCase, app


class GuidanceFeatureTests(HTTPTestCase):

    def test_new_session_precheck_is_clamped_stored_and_added_to_prompt(self):
        status, body, _ = self.request(
            "POST", "/api/new",
            {"mode": "terapi", "therapist": "young",
             "precheck": {
                 "focus": "  iç eleştirmen  ",
                 "mood_start": -4,
                 "energy_start": 99,
                 "anxiety_start": 8,
                 "available_minutes": 0,
                 "intensity_limit": -2,
                 "avoid_topics": "travma ayrıntısı",
                 "preferred_pace": "yavaş",
                 "safety_ok": True,
             }})
        self.assertEqual(status, 200)
        conv_id = body["id"]
        meta = self.row("SELECT * FROM session_meta WHERE conv=?", (conv_id,))
        self.assertEqual(meta["precheck_done"], 1)
        self.assertEqual(meta["focus"], "iç eleştirmen")
        self.assertEqual(meta["mood_start"], 1)
        self.assertEqual(meta["energy_start"], 10)
        self.assertEqual(meta["available_minutes"], 1)
        self.assertEqual(meta["intensity_limit"], 0)
        prompt = self.system_prompt(conv_id)
        self.assertIn("Kullanıcının seans öncesi çerçevesi", prompt)
        self.assertIn("iç eleştirmen", prompt)
        self.assertIn("travma ayrıntısı", prompt)
        self.assertIn("Sınır ve tempoya uy", prompt)

        status, _, _ = self.request(
            "POST", "/api/session-meta",
            {"conv_id": conv_id, "anxiety_start": "sayı değil"})
        self.assertEqual(status, 400)

    def test_recommendations_follow_conversation_cues_and_high_intensity_safety(self):
        conv_id = self.conversation(therapist="young")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user','Çocukluk ve eleştirel ebeveyn şemam',?)",
                (conv_id, app.now()))

        rows = app.recommend_methods("young", conv_id)
        recommended = [row for row in rows if row["recommended"]]
        self.assertGreaterEqual(len(recommended), 1)
        self.assertLessEqual(len(recommended), 2)
        self.assertTrue(any(
            token in (row["name"] + " " + row["description"]).casefold()
            for row in recommended
            for token in ("mod", "ebeveyn", "imgelem", "sandalye")))

        app.update_session_meta(
            conv_id, {"precheck_done": True, "safety_ok": False,
                      "anxiety_start": 9, "intensity_limit": 2})
        safe_rows = app.recommend_methods("young", conv_id)
        experiential = app.EXPERIENTIAL_TERMS
        for row in safe_rows:
            haystack = (row["name"] + " " + row["description"]).casefold()
            if any(term in haystack for term in experiential):
                self.assertFalse(row["recommended"])
                self.assertTrue(row["caution"])

    def test_case_source_packs_are_complete_and_source_mode_enters_prompt(self):
        self.assertEqual(
            {case["id"] for case in app.CASE_LIBRARY},
            set(app.CASE_SOURCE_PACKS))
        for case in app.CASE_LIBRARY:
            self.assertIn(case["therapist"], app.THERAPISTS)
            sources = app.CASE_SOURCE_PACKS[case["id"]]
            self.assertGreater(len(sources), 0)
            for source in sources:
                self.assertTrue(source["title"].strip())
                self.assertTrue(source["publisher"].strip())
                self.assertTrue(source["note"].strip())
                self.assertTrue(source["url"].startswith("https://"))

        status, cases, _ = self.request(
            "GET", "/api/cases?" + urlencode({"therapist": "young"}))
        self.assertEqual(status, 200)
        schema_case = cases["cases"][0]
        self.assertEqual(schema_case["id"], "schema-modes")
        self.assertGreater(len(schema_case["sources"]), 0)

        status, body, _ = self.request(
            "POST", "/api/new",
            {"case_id": "schema-modes", "source_mode": True})
        self.assertEqual(status, 200)
        conv = self.conversation_row(body["id"])
        self.assertEqual((conv["mode"], conv["submode"], conv["therapist"]),
                         ("ders", "vaka", "young"))
        prompt = self.system_prompt(body["id"])
        self.assertIn("Kaynaklı ders modu", prompt)
        self.assertIn("[S1]", prompt)
        self.assertIn("https://www.schematherapysociety.org/Techniques",
                      prompt)
        self.assertIn("kaynakta olmayan", prompt)
        self.assertIn("ayrıntı uydurma", prompt)

        status, _, _ = self.request(
            "POST", "/api/new",
            {"case_id": "olmayan-vaka", "source_mode": True})
        self.assertEqual(status, 400)

    def test_diagnostics_reports_components_but_redacts_all_content_and_secrets(self):
        old_conv = self.conversation(title="Önceki")
        conv_id = self.conversation(
            therapist="freud", source_mode=1, case_id="anna-o")
        app.set_setting("api_key", "API-SIR-987")
        pin = "PIN-SIR-654"
        app.set_setting("pin_hash", app.pin_hash(pin))
        app.set_setting("profile", "PROFIL-SIR-321")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(therapist,kind,content,approved,scope,"
                "sensitive,created,updated) VALUES("
                "'freud','fact','HAFIZA-SIR-111',1,'therapist',0,?,?)",
                (app.now(), app.now()))
            conn.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,"
                "approved,scope,sensitive,updated) VALUES("
                "?,'terapi','freud','NOT-SIR-222',?,1,'therapist',0,?)",
                (old_conv, app.now(), app.now()))
            conn.execute(
                "INSERT INTO session_meta(conv,focus,precheck_done,updated) "
                "VALUES(?,'ODAK-SIR-333',1,?)",
                (conv_id, app.now()))
        self.messages(conv_id, 35, prefix="GECMIS-SIR")

        status, diagnostics, _ = self.request(
            "GET", "/api/diagnostics?" + urlencode({"id": conv_id}),
            headers={"Cookie": self.unlock_cookie(pin)})
        self.assertEqual(status, 200)
        rendered = json.dumps(diagnostics, ensure_ascii=False)
        for secret in (
            "API-SIR-987", "PIN-SIR-654", "PROFIL-SIR-321",
            "HAFIZA-SIR-111", "NOT-SIR-222", "ODAK-SIR-333",
            "GECMIS-SIR",
        ):
            self.assertNotIn(secret, rendered)
        self.assertTrue(diagnostics["content_redacted"])
        self.assertEqual(diagnostics["history"]["stored"], 35)
        self.assertEqual(diagnostics["history"]["included"],
                         app.HISTORY_LIMIT)
        self.assertIn("profile", diagnostics["components"])
        self.assertIn("approved_memories", diagnostics["components"])
        self.assertIn("approved_notes", diagnostics["components"])
        self.assertIn("precheck", diagnostics["components"])
        self.assertIn("source_pack", diagnostics["components"])
        self.assertGreater(diagnostics["system_chars"], 0)
        self.assertGreater(diagnostics["estimated_tokens"], 0)

    def test_simple_mode_setting_round_trips_without_changing_data(self):
        conv_id = self.conversation(title="korunacak")
        status, _, _ = self.request(
            "POST", "/api/settings", {"simple_mode": True})
        self.assertEqual(status, 200)
        status, settings, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertTrue(settings["simple_mode"])
        self.assertIsNotNone(self.conversation_row(conv_id))

        self.request("POST", "/api/settings", {"simple_mode": False})
        _, settings, _ = self.request("GET", "/api/settings")
        self.assertFalse(settings["simple_mode"])
