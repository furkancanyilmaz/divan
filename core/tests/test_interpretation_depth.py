import unittest

from support import DatabaseTestCase, app


class InterpretationDepthPromptTests(DatabaseTestCase):

    def test_every_therapist_fingerprint_carries_courage_anchor(self):
        for therapist_id in app.THERAPISTS:
            fingerprint = app.therapy_fingerprint(therapist_id)
            self.assertIn(app.INTERPRETATION_COURAGE_ANCHOR, fingerprint)
            self.assertTrue(fingerprint.rstrip().endswith(
                app.THERAPY_FINGERPRINT_GUARDRAIL))

    def test_psychodynamic_masters_carry_malan_triangle(self):
        for therapist_id in app.PSYCHODYNAMIC_MASTERS:
            fingerprint = app.therapy_fingerprint(therapist_id)
            self.assertIn(
                app.MALAN_TRIANGLE_ANCHOR, fingerprint,
                therapist_id + " üçgen çıpasını taşımalı")
        for therapist_id in ("beck", "linehan", "rogers"):
            self.assertNotIn(
                app.MALAN_TRIANGLE_ANCHOR,
                app.therapy_fingerprint(therapist_id))

    def test_closing_templates_speak_relational_language(self):
        banned = (
            "işaretlediniz", "işaretlemediniz", "harita kaydı",
            "durum=", "aşama=", "kayıt",
        )
        for template in app.THERAPY_CLOSING_OUTCOME_TEMPLATES.values():
            rendered = template.format(label="bugünkü çalışma")
            for term in banned:
                self.assertNotIn(term, rendered)

    def test_therapy_map_prompt_has_no_app_jargon(self):
        with app.db() as c:
            c.execute(
                "INSERT INTO conversations(id,mode,title,therapist,ended,"
                "created,updated) VALUES(1,'terapi','t','rogers',0,'','')")
            c.execute(
                "INSERT INTO session_map_runs(id,conv,therapist,map_version,"
                "created,updated) VALUES(1,1,'rogers',1,'','')")
            c.execute(
                "INSERT INTO session_map_targets("
                "map_run,conv,therapist,node_id,node_name,node_kind,status,"
                "phase,is_current,created,updated) "
                "VALUES(1,1,'rogers','rogers:entry','Başlangıç','entry',"
                "'selected','selected',1,'','')")
        conv = {"id": 1, "mode": "terapi", "therapist": "rogers"}
        text = app.therapy_map_prompt(conv)
        self.assertTrue(text)
        for term in ("Harita sürümü", "durum=", "aşama=", "onay kapısı"):
            self.assertNotIn(term, text)

    def test_technique_run_context_speaks_relational_language(self):
        self.assertIsNotNone(app.THERAPY_PROMPT)
        # Devam eden teknik çalışması bloğunun jargon taşımadığını doğrudan
        # şablon parçası üzerinden değil, kaynak dize üzerinden kontrol et.
        source = __import__("pathlib").Path(app.__file__).read_text(
            encoding="utf-8")
        self.assertNotIn('"Durum: {status}\\nAşama: {phase}"', source)
        self.assertNotIn('"Açık onay kaydı yok; tekniği başlatma."', source)


if __name__ == "__main__":
    unittest.main()
