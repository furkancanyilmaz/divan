import json
import unittest
from unittest import mock

from support import HTTPTestCase, app


class ConceptCatalogTests(unittest.TestCase):

    def test_catalog_covers_first_wave_schools(self):
        for therapist in ("freud", "jung", "beck", "perls",
                          "rogers", "young", "ferenczi", "linehan"):
            self.assertIn(therapist, app.THERAPY_CONCEPTS)

    def test_catalog_covers_every_therapist(self):
        self.assertEqual(
            set(app.THERAPY_CONCEPTS), set(app.THERAPISTS))

    def test_every_concept_has_valid_shape_and_method_bridges(self):
        for therapist, concepts in app.THERAPY_CONCEPTS.items():
            method_keys = {
                method["key"] for method in app.method_records(therapist)}
            keys = set()
            for item in concepts:
                self.assertIsInstance(item, dict)
                for field in ("key", "name", "cue", "plain", "depth"):
                    self.assertIn(field, item)
                    self.assertTrue(item[field], (therapist, item.get("key")))
                self.assertIn("opens", item)
                self.assertIn(item["depth"], (1, 2, 3))
                self.assertNotIn(item["key"], keys)
                keys.add(item["key"])
                for bridge in item["opens"]:
                    self.assertIn(
                        bridge, method_keys,
                        "{} için {} yöntem köprüsü geçersiz".format(
                            therapist, bridge))
            # İlk dalga 8, ikinci dalga 6 kavram taşır; sözleşme aynı.
            self.assertGreaterEqual(len(concepts), 6)

    def test_key_names_are_unique_across_catalog(self):
        seen = set()
        for concepts in app.THERAPY_CONCEPTS.values():
            for item in concepts:
                self.assertNotIn(item["key"], seen)
                seen.add(item["key"])


class ConceptScanTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="freud")
        with app.db() as c:
            for content in (
                    "Yine aynı duvara çarpıyorum; her seferinde aynı şey "
                    "oluyor.",
                    "Sanki herkesten aynı tepkiyi alıyorum.",
                    "Bilmiyorum, boş ver.",
            ):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (self.conv, "user", content, app.now()))

    def test_parse_keeps_only_known_keys_with_verbatim_evidence(self):
        raw = json.dumps({
            "candidates": [
                {"key": "transference",
                 "evidence": "Yine aynı duvara çarpıyorum",
                 "strength": 0.8},
                {"key": "ucube-kavram",
                 "evidence": "Yine aynı duvara çarpıyorum",
                 "strength": 0.9},
                {"key": "defense",
                 "evidence": "uydurulmuş bir kanıt cümlesi",
                 "strength": 0.9},
                {"key": "resistance_to_change",
                 "evidence": "Sanki herkesten aynı tepkiyi alıyorum",
                 "strength": 0.2},
            ],
        }, ensure_ascii=False)
        with app.db() as c:
            rows = c.execute(
                "SELECT id,content FROM messages WHERE conv=? AND role='user'",
                (self.conv,)).fetchall()
        checked = app.parse_concept_scan(raw, "freud", list(rows))
        self.assertEqual(
            [item["key"] for item in checked], ["transference"])
        self.assertEqual(
            checked[0]["evidence"], "Yine aynı duvara çarpıyorum")

    def test_scan_writes_candidates_and_picks_single_focus(self):
        raw = json.dumps({
            "candidates": [
                {"key": "transference",
                 "evidence": "Yine aynı duvara çarpıyorum",
                 "strength": 0.7},
                {"key": "defense",
                 "evidence": "Bilmiyorum, boş ver.",
                 "strength": 0.6},
            ],
        }, ensure_ascii=False)
        with mock.patch.object(app, "ds_complete", return_value=raw):
            added = app.scan_concepts(self.conv)
        self.assertEqual(added, 2)
        with app.db() as c:
            proposed = c.execute(
                "SELECT * FROM concept_observations WHERE conv=? AND "
                "status='proposed'", (self.conv,)).fetchall()
            parked = c.execute(
                "SELECT * FROM concept_observations WHERE conv=? AND "
                "status='parked'", (self.conv,)).fetchall()
        # Algoritma yalnız teklif eder; odak kullanıcı kabulüyle olur.
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["concept_key"], "transference")
        self.assertEqual(len(parked), 1)
        self.assertEqual(parked[0]["concept_key"], "defense")

    def test_scan_silently_skips_on_safety_hold(self):
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv,))
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("krizde tarama yapılmamalı")):
            self.assertEqual(app.scan_concepts(self.conv), 0)

    def test_scan_never_fails_chat_on_provider_error(self):
        with mock.patch.object(
                app, "ds_complete",
                side_effect=app.ProviderError(
                    "provider_output_truncated", "kesildi")):
            self.assertEqual(app.scan_concepts(self.conv), 0)

    def test_focus_prefers_repetition_with_hysteresis(self):
        with app.db() as c:
            stamp = app.now()
            rows = [
                ("transference", "kanıt A", 0.6, "candidate"),
                ("transference", "kanıt B", 0.6, "candidate"),
                ("defense", "kanıt C", 0.8, "candidate"),
            ]
            for key, evidence, strength, status in rows:
                c.execute(
                    "INSERT INTO concept_observations("
                    "conv,therapist,concept_key,evidence_quote,strength,"
                    "status,created,updated) VALUES(?,'freud',?,?,?,?,?,?)",
                    (self.conv, key, evidence, strength, status,
                     stamp, stamp))
        app.refresh_concept_focus(self.conv)
        with app.db() as c:
            proposed = c.execute(
                "SELECT concept_key FROM concept_observations WHERE conv=? "
                "AND status='proposed'", (self.conv,)).fetchone()
        # Tekrar (2 gözlem) tek seferlik güçten ağır basar.
        self.assertEqual(proposed["concept_key"], "transference")


class ConceptPromptTests(HTTPTestCase):

    def test_focused_concept_block_enters_prompt(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "created,updated) VALUES(?,'freud','transference',?,0.7,"
                "'focused',?,?)",
                (conv_id, "Yine aynı duvara çarpıyorum",
                 app.now(), app.now()))
        prompt = self.system_prompt(conv_id)
        self.assertIn("Şu an çalıştığın kavram: Aktarım", prompt)
        self.assertIn("Yine aynı duvara çarpıyorum", prompt)
        self.assertIn("Kavram bir teşhis değildir", prompt)

    def test_concept_block_stays_out_on_safety_hold(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "created,updated) VALUES(?,'freud','transference',?,0.7,"
                "'focused',?,?)",
                (conv_id, "kanıt", app.now(), app.now()))
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))
        prompt = self.system_prompt(conv_id)
        self.assertNotIn("Şu an çalıştığın kavram", prompt)

    def test_concept_block_stays_out_for_philosophers(self):
        conv_id = self.conversation(
            mode="ders", therapist="socrates", title="Ders")
        with app.db() as c:
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "created,updated) VALUES(?,'socrates','shadow',?,0.7,"
                "'focused',?,?)",
                (conv_id, "kanıt", app.now(), app.now()))
        prompt = self.system_prompt(conv_id)
        self.assertNotIn("Şu an çalıştığın kavram", prompt)

    def test_secondary_provider_pin_falls_back_to_primary(self):
        app.set_setting("secondary_provider", "")
        app.set_setting("secondary_model", "")
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("deepseek_model", "deepseek-v4-pro")
        provider, model = app._concept_provider_pin()
        self.assertEqual((provider, model), ("deepseek", "deepseek-v4-pro"))

        # İkincil sağlayıcı için anahtar görünür durumdaysa (test deposu)
        # flash model seçilir.
        app.set_setting("deepseek_api_key", "test-key")
        app.set_setting("secondary_provider", "deepseek")
        app.set_setting("secondary_model", "deepseek-v4-flash")
        provider, model = app._concept_provider_pin()
        self.assertEqual((provider, model), ("deepseek", "deepseek-v4-flash"))


class ConceptStateMachineTests(HTTPTestCase):

    def test_stage_progresses_with_evidence_and_naming(self):
        self.assertEqual(app._concept_stage_for(1, False), "noticed")
        self.assertEqual(app._concept_stage_for(2, False), "tracking")
        self.assertEqual(app._concept_stage_for(4, False), "naming")
        self.assertEqual(app._concept_stage_for(4, True), "working")

    def test_prompt_grammar_follows_stage(self):
        conv_id = self.conversation(therapist="freud")
        stamp = app.now()
        with app.db() as c:
            for _ in range(app.CONCEPT_NAMING_EVIDENCE):
                c.execute(
                    "INSERT INTO concept_observations("
                    "conv,therapist,concept_key,evidence_quote,strength,"
                    "status,stage,created,updated) "
                    "VALUES(?,'freud','transference','kanıt',0.6,"
                    "'candidate','noticed',?,?)", (conv_id, stamp, stamp))
            c.execute(
                "UPDATE concept_observations SET status='focused',"
                "stage='naming' WHERE id=(SELECT MAX(id) FROM "
                "concept_observations WHERE conv=?)", (conv_id,))
        prompt = self.system_prompt(conv_id)
        # naming aşamasında ad tanıtılır
        self.assertIn("jargonsuz tek cümleyle tanıt", prompt)
        # noticed aşamasında ad hiç söylenmez
        with app.db() as c:
            c.execute(
                "UPDATE concept_observations SET stage='noticed' "
                "WHERE conv=?", (conv_id,))
        prompt = self.system_prompt(conv_id)
        self.assertIn("yalnız İZLE", prompt)
        self.assertIn("adını da kavramı da söyleme", prompt)

    def test_focus_api_switches_and_demotes(self):
        conv_id = self.conversation(therapist="freud")
        stamp = app.now()
        with app.db() as c:
            for key, status in (("transference", "focused"),
                                ("defense", "parked")):
                c.execute(
                    "INSERT INTO concept_observations("
                    "conv,therapist,concept_key,evidence_quote,strength,"
                    "status,stage,created,updated) "
                    "VALUES(?,'freud',?,'kanıt',0.6,?,?,?,?)",
                    (conv_id, key, status,
                     "working" if status == "focused" else "noticed",
                     stamp, stamp))
        status, body, _ = self.request(
            "GET", "/api/concepts/focus?conv_id={}".format(conv_id))
        self.assertEqual(status, 200)
        self.assertEqual(body["focus"]["concept_key"], "transference")
        self.assertEqual(len(body["parked"]), 1)
        self.assertEqual(body["catalog"][0]["key"], "transference")

        status, body, _ = self.request(
            "POST", "/api/concepts/focus",
            {"conv_id": conv_id, "concept_key": "defense"})
        self.assertEqual(status, 200)
        status, body, _ = self.request(
            "GET", "/api/concepts/focus?conv_id={}".format(conv_id))
        self.assertEqual(body["focus"]["concept_key"], "defense")
        self.assertEqual(body["parked"][0]["concept_key"], "transference")

    def test_state_api_marks_worked_and_named(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "stage,created,updated) VALUES(?,'freud','transference',"
                "'kanıt',0.6,'focused','naming',?,?)",
                (conv_id, app.now(), app.now()))
        status, body, _ = self.request(
            "POST", "/api/concepts/state",
            {"conv_id": conv_id, "concept_key": "transference",
             "action": "worked"})
        self.assertEqual(status, 200)
        with app.db() as c:
            row = c.execute(
                "SELECT status,stage,named_at FROM concept_observations "
                "WHERE conv=?", (conv_id,)).fetchone()
        self.assertEqual(row["status"], "worked")
        self.assertEqual(row["stage"], "resting")
        self.assertTrue(row["named_at"])


class ConceptSessionEndTests(HTTPTestCase):

    def test_closing_carries_concept_bridge_when_observations_exist(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "stage,created,updated) VALUES(?,'freud','transference',"
                "'kanıt',0.6,'focused','working',?,?)",
                (conv_id, app.now(), app.now()))
            c.execute(
                "INSERT INTO concept_observations("
                "conv,therapist,concept_key,evidence_quote,strength,status,"
                "stage,created,updated) VALUES(?,'freud','secondary_gain',"
                "'kanıt',0.5,'parked','noticed',?,?)",
                (conv_id, app.now(), app.now()))
            conv = c.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,)).fetchone()
            closing = app.append_concept_bridge(c, conv, "Kapanış.")
        self.assertTrue(closing.startswith("Kapanış."))
        self.assertIn("Aktarım üzerinde durduk", closing)
        self.assertIn("İkincil kazanç", closing)

    def test_closing_unchanged_without_observations(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            conv = c.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,)).fetchone()
            closing = app.append_concept_bridge(c, conv, "Kapanış.")
        self.assertEqual(closing, "Kapanış.")


class ConceptSettingsTests(HTTPTestCase):

    def test_settings_roundtrip_secondary_model(self):
        status, body, _ = self.request(
            "POST", "/api/settings",
            {"secondary_provider": "deepseek",
             "secondary_model": "deepseek-v4-flash"})
        self.assertEqual(status, 200)
        self.assertEqual(body["secondary_provider"], "deepseek")
        self.assertEqual(body["secondary_model"], "deepseek-v4-flash")
        with app.db() as c:
            provider = c.execute(
                "SELECT value FROM settings WHERE key='secondary_provider'"
            ).fetchone()
            model = c.execute(
                "SELECT value FROM settings WHERE key='secondary_model'"
            ).fetchone()
        self.assertEqual(provider["value"], "deepseek")
        self.assertEqual(model["value"], "deepseek-v4-flash")

    def test_settings_rejects_unknown_secondary_provider(self):
        status, body, _ = self.request(
            "POST", "/api/settings",
            {"secondary_provider": "bilinmeyen"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
