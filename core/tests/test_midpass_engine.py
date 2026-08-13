import json
import unittest
from unittest import mock

from support import HTTPTestCase, app


class MidpassScheduleTests(HTTPTestCase):

    def test_midpass_scheduled_after_enough_new_messages(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            for index in range(4):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "user", "mesaj {}".format(index), app.now()))
        app.maybe_schedule_midpass(conv_id)
        with app.db() as c:
            job = c.execute(
                "SELECT * FROM jobs WHERE conv=? AND kind='session_midpass'",
                (conv_id,)).fetchone()
        self.assertIsNone(job)

        with app.db() as c:
            for index in range(8):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "user", "mesaj {}".format(index), app.now()))
        app.maybe_schedule_midpass(conv_id)
        with app.db() as c:
            job = c.execute(
                "SELECT * FROM jobs WHERE conv=? AND kind='session_midpass'",
                (conv_id,)).fetchone()
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "queued")

    def test_midpass_silent_on_safety_hold(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))
            for index in range(12):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "user", "mesaj {}".format(index), app.now()))
        app.maybe_schedule_midpass(conv_id)
        with app.db() as c:
            job = c.execute(
                "SELECT * FROM jobs WHERE conv=? AND kind='session_midpass'",
                (conv_id,)).fetchone()
        self.assertIsNone(job)


class MidpassRunTests(HTTPTestCase):

    def _seed_messages(self, conv_id, count):
        with app.db() as c:
            for index in range(count):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id,
                     "user" if index % 2 == 0 else "assistant",
                     "Yine aynı duvara çarpıyorum. {}".format(index),
                     app.now()))

    def test_run_distills_hypotheses_with_verbatim_evidence(self):
        conv_id = self.conversation(therapist="freud")
        self._seed_messages(conv_id, 12)
        raw = json.dumps({
            "hypotheses": [{"text": "Başarı = sevilme koşulu olabilir."}],
            "evidence": [],
        }, ensure_ascii=False)
        with mock.patch.object(app, "ds_complete", return_value=raw):
            app.run_session_midpass(conv_id)
        with app.db() as c:
            rows = c.execute(
                "SELECT * FROM hypotheses WHERE conv=?", (conv_id,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "active")
        self.assertEqual(rows[0]["user_decision"], "")

    def test_evidence_quotes_must_be_verbatim(self):
        conv_id = self.conversation(therapist="freud")
        self._seed_messages(conv_id, 12)
        with app.db() as c:
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) "
                "VALUES(?,'freud','Eski hipotez','active',1,?,?)",
                (conv_id, app.now(), app.now()))
        raw = json.dumps({
            "hypotheses": [],
            "evidence": [{
                "hypothesis_id": 1,
                "supports": ["Yine aynı duvara çarpıyorum.",
                             "uydurulmuş bir cümle böyle olur"],
                "against": ["birebir geçmeyen karşı örnek"],
                "alternatives": ["Birinci alternatif açıklama.",
                                 "İkinci alternatif açıklama."],
                "falsification": "Bir hafta boyunca aynı örüntü "
                                 "gözlenmezse çürür.",
                "context_note": "Yalnızca iş bağlamında.",
            }],
        }, ensure_ascii=False)
        with mock.patch.object(app, "ds_complete", return_value=raw):
            app.run_session_midpass(conv_id)
        with app.db() as c:
            evidence = c.execute(
                "SELECT * FROM hypothesis_evidence WHERE hypothesis=1 "
                "ORDER BY id").fetchall()
            row = c.execute(
                "SELECT * FROM hypotheses WHERE id=1").fetchone()
        # Yalnız birebir alıntılar kaydedilir.
        self.assertEqual(
            [e["quote"] for e in evidence],
            ["Yine aynı duvara çarpıyorum."])
        self.assertEqual(evidence[0]["kind"], "supports")
        # Alıntının kaynak mesaj kimliği doğru kaydedilir (user mesajı).
        self.assertGreater(evidence[0]["message_id"], 0)
        self.assertIn("Birinci alternatif açıklama.", row["alternatives"])
        self.assertIn("İkinci alternatif açıklama.", row["alternatives"])
        self.assertIn("çürür", row["falsification"])
        self.assertIn("iş bağlamında", row["context_note"])
        self.assertEqual(row["user_decision"], "")

    def test_user_decision_controls_context_entry(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) "
                "VALUES(?,'freud','Doğrulanacak örüntü','active',1,?,?)",
                (conv_id, app.now(), app.now()))
        status, body, _ = self.request(
            "POST", "/api/hypothesis/decision",
            {"id": 1, "decision": "uyuyor"})
        self.assertEqual(status, 200)
        prompt = self.system_prompt(conv_id)
        self.assertIn("Kullanıcıca doğrulanan örüntüler", prompt)
        self.assertIn("Doğrulanacak örüntü", prompt)

        status, _, _ = self.request(
            "POST", "/api/hypothesis/decision",
            {"id": 1, "decision": "ozel"})
        self.assertEqual(status, 200)
        prompt = self.system_prompt(conv_id)
        self.assertNotIn("Doğrulanacak örüntü", prompt)

    def test_unverified_hypothesis_never_enters_context(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) "
                "VALUES(?,'freud','Doğrulanmamış örüntü','active',1,?,?)",
                (conv_id, app.now(), app.now()))
        prompt = self.system_prompt(conv_id)
        self.assertNotIn("Doğrulanmamış örüntü", prompt)
        self.assertNotIn("Kullanıcıca doğrulanan örüntüler", prompt)

    def test_invalid_decision_rejected(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) "
                "VALUES(?,'freud','X','active',1,?,?)",
                (conv_id, app.now(), app.now()))
        status, _, _ = self.request(
            "POST", "/api/hypothesis/decision",
            {"id": 1, "decision": "kabul"})
        self.assertEqual(status, 400)

    def test_micro_note_written_once_after_threshold(self):
        conv_id = self.conversation(therapist="freud")
        self._seed_messages(conv_id, 26)
        raw = json.dumps({"hypotheses": [], "evidence": []},
                         ensure_ascii=False)
        with mock.patch.object(app, "ds_complete", return_value=raw), \
                mock.patch.object(
                    app, "ds_complete_continued",
                    return_value="Kısa olgusal ara not."):
            app.run_session_midpass(conv_id)
            with app.db() as c:
                micro = c.execute(
                    "SELECT * FROM notes WHERE conv=? AND kind='micro'",
                    (conv_id,)).fetchone()
        self.assertIsNotNone(micro)
        # Ara-not sessiz yazılır ama kullanıcı onayına kadar belleğe
        # girmez; onaylı hafıza yalnız açık kullanıcı kararıdır.
        self.assertEqual(micro["approved"], 0)
        self.assertEqual(micro["content"], "Kısa olgusal ara not.")

    def test_lexicon_updated_from_recurring_terms(self):
        conv_id = self.conversation(therapist="freud")
        self._seed_messages(conv_id, 12)
        raw_mid = json.dumps({"hypotheses": [], "evidence": []},
                             ensure_ascii=False)
        raw_lex = json.dumps({"terms": [{"term": "duvar", "count": 4}]},
                             ensure_ascii=False)
        with mock.patch.object(
                app, "ds_complete", side_effect=[raw_mid, raw_lex]):
            app.run_session_midpass(conv_id)
        with app.db() as c:
            row = c.execute(
                "SELECT * FROM client_lexicon WHERE therapist='freud' AND "
                "term='duvar'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["frequency"], 4)


class ProcessSignalAndRuptureTests(HTTPTestCase):

    def test_process_signals_detect_shortening(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            for content in ("x" * 200, "y" * 220, "z" * 180,
                            "kısa", "tamam", "evet"):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)", (conv_id, "user", content, app.now()))
        text = app.process_signals_prompt(conv_id)
        self.assertIn("belirgin kısa yazıyor", text)

    def test_process_signals_absent_when_steady(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            for content in ("x" * 80, "y" * 90, "z" * 85):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)", (conv_id, "user", content, app.now()))
        self.assertEqual(app.process_signals_prompt(conv_id), "")

    def test_rupture_detected_and_injected(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            for content in ("uzun bir mesaj içeriği burada duruyor",
                            "kısa", "tamam", "neyse boşver"):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)", (conv_id, "user", content, app.now()))
        line = app.record_rupture(conv_id)
        self.assertIsNotNone(line)
        self.assertIn("İlişki sinyali", line)
        with app.db() as c:
            event = c.execute(
                "SELECT * FROM repair_events WHERE conv=?",
                (conv_id,)).fetchone()
        self.assertIsNotNone(event)
        prompt = self.system_prompt(conv_id)
        self.assertIn("İlişki sinyali", prompt)

    def test_rupture_silent_on_safety_hold(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))
            for content in ("kısa", "tamam", "neyse boşver"):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)", (conv_id, "user", content, app.now()))
        self.assertIsNone(app.record_rupture(conv_id))


class DepthInjectionTests(HTTPTestCase):

    def test_verified_pattern_and_lexicon_enter_prompt(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "user_decision,decision_at,through_message_id,created,updated) "
                "VALUES(?,'freud','Başarı = sevilme koşulu olabilir.',"
                "'verified','uyuyor',?,1,?,?)",
                (conv_id, app.now(), app.now(), app.now()))
            c.execute(
                "INSERT INTO client_lexicon(therapist,term,first_context,"
                "frequency,created,updated) VALUES('freud','duvar','x',4,?,?)",
                (app.now(), app.now()))
        prompt = self.system_prompt(conv_id)
        self.assertIn("Kullanıcıca doğrulanan örüntüler", prompt)
        self.assertIn("Başarı = sevilme koşulu olabilir", prompt)
        self.assertIn("Danışanın kendi imgeleri", prompt)
        self.assertIn("duvar (4)", prompt)

    def test_formulation_threshold_is_lowered_for_micro_notes(self):
        self.assertEqual(app.FORMULATE_EVERY, 3)


if __name__ == "__main__":
    unittest.main()
