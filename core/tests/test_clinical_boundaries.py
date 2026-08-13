import json
import unittest
from unittest import mock

from support import HTTPTestCase, app


class UserTextSafetyGateTests(unittest.TestCase):

    def test_direct_self_harm_and_reported_risk_are_distinguished(self):
        direct = app.user_text_safety_gate(
            "Bu gece kendimi öldüreceğim.")
        reported = app.user_text_safety_gate(
            "Arkadaşım bu gece intihar edeceğini söylüyor.")

        self.assertTrue(direct["detected"])
        self.assertEqual(direct["kind"], "self_harm")
        self.assertTrue(reported["detected"])
        self.assertEqual(reported["kind"], "other_person_self_harm")

    def test_academic_topic_words_do_not_trigger_a_crisis_response(self):
        examples = (
            "Camus'nün intihar hakkındaki görüşünü tartışalım.",
            "Bir akademik makalede intihar oranları nasıl ölçülür?",
            "Bir film karakterinin ölüm düşüncesi nasıl yorumlanır?",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertFalse(
                    app.user_text_safety_gate(text)["detected"])

    def test_academic_word_does_not_hide_a_concrete_reported_risk(self):
        examples = (
            "Annem intihar edeceğini söylüyor; bu konuda bir makale de okudum.",
            "Arkadaşımın intihar hakkında bir kitabı var ve bu gece "
            "öleceğini söylüyor.",
        )
        for text in examples:
            with self.subTest(text=text):
                decision = app.user_text_safety_gate(text)
                self.assertTrue(decision["detected"])
                self.assertEqual(
                    decision["kind"], "other_person_self_harm")

    def test_direct_violence_intent_is_detected_without_the_word_kill(self):
        examples = (
            "Onu bıçaklayacağım.",
            "Seni vurmak istiyorum.",
            "Birine saldıracağım.",
        )
        for text in examples:
            with self.subTest(text=text):
                decision = app.user_text_safety_gate(text)
                self.assertTrue(decision["detected"])
                self.assertEqual(decision["kind"], "harm_to_others")

    def test_direct_self_harm_methods_and_more_close_relations_are_detected(self):
        self_examples = (
            "Bu gece kendimi bıçaklayacağım.",
            "Bileklerimi keseceğim.",
            "Bütün ilaçları içip öleceğim.",
            "Köprüden atlayacağım.",
            "Silahı kafama dayayacağım.",
            "Damarlarımı keseceğim.",
        )
        for text in self_examples:
            with self.subTest(text=text):
                decision = app.user_text_safety_gate(text)
                self.assertTrue(decision["detected"])
                self.assertEqual(decision["kind"], "self_harm")
        for text in (
                "Sevgilim intihar edeceğini söyledi.",
                "Partnerim kendini asacağını söyledi.",
                "Oğlum artık yaşamak istemediğini söylüyor.",
                "Kız arkadaşım bu gece canına kıyacak.",
                "Annem keşke ölsem diyor.",
                "Arkadaşım ölmek istiyorum dedi."):
            with self.subTest(text=text):
                reported = app.user_text_safety_gate(text)
                self.assertTrue(reported["detected"])
                self.assertEqual(
                    reported["kind"], "other_person_self_harm")

    def test_more_natural_explicit_turkish_risk_phrases_are_detected(self):
        self_harm = (
            "Kafama sıkacağım.",
            "Tüm hapları yutacağım.",
            "Kendimi trenin önüne atacağım.",
            "İntihar planım hazır.",
            "Keşke ölsem.",
            "Doktorun verdiği tüm ilaçları şimdi birden alacağım.",
        )
        violence = (
            "Karımı öldüreceğim.",
            "Patronumu vuracağım.",
            "Okula gidip hepsini vuracağım.",
            "Çocuğumu döveceğim.",
            "Seni geberteceğim.",
            "Babamı öldüreceğim.",
        )
        for text in self_harm:
            with self.subTest(text=text):
                self.assertEqual(
                    app.user_text_safety_gate(text)["kind"], "self_harm")
        for text in violence:
            with self.subTest(text=text):
                self.assertEqual(
                    app.user_text_safety_gate(text)["kind"],
                    "harm_to_others")

    def test_violence_words_in_titles_and_unrelated_verbs_do_not_trigger(self):
        examples = (
            "Onu seviyorum; dövüş filmleri hakkında konuşmak istiyorum.",
            "Onu öldüren film hakkında bir makale yazıyorum.",
            "Seni Vuran Kadın adlı romanı inceliyorum.",
            "Onu yakından tanımak istiyorum.",
            "Kendimi keskin bir gözlemci olarak görüyorum.",
            "Köprüden atlayacağım sahneyi yazıyorum.",
            "Bütün ilaçları içeceğim diye bir film repliği var.",
            "Onu döveceğim demedim.",
            "Doktorun verdiği tüm ilaçları alacağım.",
            "Okçulukta hedeflerin hepsini vuracağım.",
            "Bahçedeki sineklerin hepsini öldüreceğim.",
            "Camus'nün kitabındaki “ölmek istiyorum” cümlesini açıkla.",
            "Romanda “intihar planım hazır” cümlesi ne anlatıyor?",
            "Bir karakter “keşke ölsem” diyor; bunu analiz et.",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertFalse(
                    app.user_text_safety_gate(text)["detected"])

    def test_dream_only_language_is_contextual_but_current_risk_is_not(self):
        dream_only = app.user_text_safety_gate(
            "🌙 [Rüya] Rüyamda ölmek istiyorum.",
            context="dream_analysis")
        current = app.user_text_safety_gate(
            "🌙 [Rüya] Uyandığımda da ölmek istiyorum.",
            context="dream_analysis")

        self.assertFalse(dream_only["detected"])
        self.assertTrue(current["detected"])


class ClinicalPromptBoundaryTests(unittest.TestCase):

    def test_therapy_prompt_names_diagnosis_medication_and_memory_limits(self):
        prompt = app._safety_fold(app.THERAPY_PROMPT)
        for marker in ("tani", "ilac", "doz", "tibbi", "ani",
                       "tarihsel kanit"):
            with self.subTest(marker=marker):
                self.assertIn(marker, prompt)

    def test_direct_identity_question_requires_truthful_disclosure(self):
        shared = app._safety_fold(app.SHARED_TAIL)

        self.assertIn("dogrudan sorarsa", shared)
        self.assertIn("bir yapay zeka oldugunu soyle", shared)
        self.assertNotIn(
            'Asla "ben bir yapay zekâyım" deme', app.SHARED_TAIL)

    def test_approach_discovery_is_not_clinical_matching(self):
        prompt = app._safety_fold(app.TRIAGE_PROMPT)

        self.assertIn("yaklasim rehberisin", prompt)
        self.assertIn("klinik sevk", prompt)
        self.assertIn("gercek klinisyen eslestirmesi", prompt)


class DirectModelEndpointSafetyTests(HTTPTestCase):

    def test_triage_crisis_is_model_independent(self):
        with mock.patch.object(app, "ds_complete") as complete:
            status, body, _ = self.request(
                "POST", "/api/triage",
                {"text": "Bu gece kendimi öldüreceğim."})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["crisis"])
        self.assertEqual(body["safety"]["kind"], "self_harm")
        self.assertIn("112", body["message"])
        complete.assert_not_called()

    def test_triage_academic_question_reaches_the_model(self):
        with mock.patch.object(
                app, "ds_complete",
                return_value="Üç düşünsel mercek.") as complete:
            status, body, _ = self.request(
                "POST", "/api/triage",
                {"text": "Camus'nün intihar hakkındaki görüşü nedir?"})

        self.assertEqual(status, 200, body)
        self.assertEqual(body["answer"], "Üç düşünsel mercek.")
        complete.assert_called_once()

    def test_duet_crisis_does_not_start_either_model_call(self):
        with mock.patch.object(app, "ds_complete") as complete:
            status, body, _ = self.request(
                "POST", "/api/duet", {
                    "members": ["freud", "young"],
                    "text": "Şimdi kendime zarar vermek istiyorum.",
                })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["crisis"])
        self.assertEqual(body["answers"], [])
        complete.assert_not_called()

    def test_dream_analysis_stops_on_risk_that_continues_after_waking(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user",
                 "🌙 [Rüya] Uyandığımda da ölmek istiyorum.",
                 "2026-07-30 12:00"))

        with mock.patch.object(app, "ds_complete") as complete:
            status, body, _ = self.request(
                "POST", "/api/dreams/analyze",
                {"therapist": "freud"})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["crisis"])
        complete.assert_not_called()

    def test_historical_dream_language_can_still_be_analyzed(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user",
                 "🌙 [Rüya] Rüyamda ölmek istiyorum ama sonra uyandım.",
                 "2026-07-30 12:00"))

        with mock.patch.object(
                app, "ds_complete",
                return_value="Temkinli bir motif yorumu.") as complete:
            status, body, _ = self.request(
                "POST", "/api/dreams/analyze",
                {"therapist": "freud"})

        self.assertEqual(status, 200, body)
        self.assertEqual(body["answer"], "Temkinli bir motif yorumu.")
        complete.assert_called_once()

    def test_practice_feedback_crisis_does_not_reach_the_model(self):
        conv_id = self.conversation(therapist="beck")
        method = next(
            item for item in app.method_records("beck")
            if item["node_id"] == "beck:method:socratic-questioning")
        status, created, _ = self.request(
            "POST", "/api/practice-lab", {
                "action": "create", "conv_id": conv_id,
                "therapist": "beck", "method_key": method["key"],
            })
        self.assertEqual(status, 200, created)
        run_id = created["practice"]["id"]
        status, recorded, _ = self.request(
            "POST", "/api/practice-lab", {
                "action": "record", "conv_id": conv_id, "id": run_id,
                "content": (
                    "Bu pratik bir yana, şimdi kendime zarar vermek "
                    "istiyorum."),
            })
        self.assertEqual(status, 200, recorded)

        with mock.patch.object(app, "ds_complete") as complete:
            status, body, _ = self.request(
                "POST", "/api/practice-lab", {
                    "action": "feedback", "conv_id": conv_id, "id": run_id,
                })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["crisis"])
        self.assertIn("112", body["feedback"])
        complete.assert_not_called()
        saved = self.row(
            "SELECT * FROM practice_steps WHERE practice_run=? "
            "AND step_kind='feedback' ORDER BY id DESC LIMIT 1",
            (run_id,))
        self.assertEqual(saved["source"], "safety")
        self.assertEqual(saved["authored_by"], "server")


class SessionExitGroundingTests(HTTPTestCase):

    def active_technique(self, grounding_requested):
        conv_id = self.conversation(therapist="young")
        method = app.method_records("young")[0]
        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id, "action": "propose",
                "method_key": method["key"], "intensity": 3,
            })
        self.assertEqual(status, 200, proposed)
        run_id = proposed["run"]["id"]
        status, consented, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id, "id": run_id, "action": "consent",
                "confirmed": True,
            })
        self.assertEqual(status, 200, consented)
        status, ended, _ = self.request(
            "POST", "/api/end", {
                "conv_id": conv_id,
                "grounding_requested": grounding_requested,
            })
        self.assertEqual(status, 200, ended)
        return conv_id, run_id, ended

    def test_selected_grounding_is_fixed_persisted_and_nonblocking(self):
        conv_id, run_id, ended = self.active_technique(True)

        self.assertEqual(
            ended["grounding"], app.SESSION_EXIT_GROUNDING_MESSAGE)
        self.assertFalse(ended["grounding_carryover"])
        messages = self.rows(
            "SELECT content FROM messages WHERE conv=? ORDER BY id",
            (conv_id,))
        self.assertEqual(
            [row["content"] for row in messages],
            [app.SESSION_EXIT_GROUNDING_MESSAGE, ended["closing"]])
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        state = json.loads(run["state_json"])
        self.assertEqual(
            state["session_end_grounding"]["status"], "selected")
        self.assertFalse(
            state["session_end_grounding"]["completed"])
        self.assertEqual((run["status"], run["phase"]),
                         ("stopped", "end"))

    def test_immediate_close_records_open_work_as_carryover(self):
        _, run_id, ended = self.active_technique(False)

        self.assertTrue(ended["grounding_carryover"])
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        state = json.loads(run["state_json"])
        self.assertEqual(
            state["session_end_grounding"]["status"], "carryover")
        self.assertFalse(
            state["session_end_grounding"]["completed"])

    def test_unconsented_proposal_does_not_create_grounding_record(self):
        conv_id = self.conversation(therapist="young")
        method = app.method_records("young")[0]
        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id, "action": "propose",
                "method_key": method["key"], "intensity": 3,
            })
        self.assertEqual(status, 200, proposed)

        status, ended, _ = self.request(
            "POST", "/api/end", {
                "conv_id": conv_id, "grounding_requested": True,
            })

        self.assertEqual(status, 200, ended)
        self.assertIsNone(ended["grounding"])
        self.assertFalse(ended["grounding_carryover"])
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?",
            (proposed["run"]["id"],))
        self.assertNotIn(
            "session_end_grounding",
            json.loads(run["state_json"] or "{}"))
