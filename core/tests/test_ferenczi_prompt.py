from support import HTTPTestCase, app


class FerencziPromptRegressionTests(HTTPTestCase):

    def test_therapy_anchor_is_short_unique_and_last_after_memory_and_notes(self):
        previous = self.conversation(
            therapist="ferenczi", title="Önceki Ferenczi seansı")
        current = self.conversation(
            therapist="ferenczi", title="Bugünkü Ferenczi seansı")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(therapist,kind,content,approved,scope,"
                "sensitive,created,updated) VALUES("
                "'ferenczi','fact','FERENCZI-HAFIZA-BLOĞU',1,'therapist',"
                "0,?,?)",
                (app.now(), app.now()),
            )
            conn.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,"
                "approved,scope,sensitive,updated) VALUES("
                "?,'terapi','ferenczi','FERENCZI-NOT-BLOĞU',?,"
                "1,'therapist',0,?)",
                (previous, app.now(), app.now()),
            )

        prompt = self.system_prompt(current)
        anchor = app.therapy_fingerprint("ferenczi")

        self.assertTrue(anchor.strip())
        self.assertLessEqual(len(app.FERENCZI_THERAPY_ANCHOR), 800)
        self.assertLessEqual(len(anchor), 1600)
        self.assertEqual(prompt.count(anchor), 1)
        self.assertIn("FERENCZI-HAFIZA-BLOĞU", prompt)
        self.assertIn("FERENCZI-NOT-BLOĞU", prompt)
        self.assertLess(prompt.index("FERENCZI-HAFIZA-BLOĞU"),
                        prompt.index(anchor))
        self.assertLess(prompt.index("FERENCZI-NOT-BLOĞU"),
                        prompt.index(anchor))
        self.assertTrue(prompt.endswith(anchor))

        # Son öncelik çıpası eklenirken Ferenczi'nin mevcut terapi
        # kimliği, güvenlik çerçevesi ve yöntem repertuvarı kaybolmamalı.
        self.assertIn(app.persona_block("ferenczi"), prompt)
        self.assertIn(app.THERAPY_PROMPT, prompt)
        self.assertIn(app.METHOD_SAFETY, prompt)
        self.assertIn(app.methods_prompt("ferenczi"), prompt)

    def test_anchor_does_not_leak_to_other_therapists_or_lesson_mode(self):
        anchor = app.FERENCZI_THERAPY_ANCHOR
        freud = self.conversation(therapist="freud")
        ferenczi_lesson = self.conversation(
            mode="ders", therapist="ferenczi", title="Ferenczi dersi")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(therapist,kind,content,approved,scope,"
                "sensitive,created,updated) VALUES("
                "'ferenczi','fact','PAYLAŞILAN-HAFIZA',1,'shared',0,?,?)",
                (app.now(), app.now()),
            )

        freud_prompt = self.system_prompt(freud)
        lesson_prompt = self.system_prompt(ferenczi_lesson)

        self.assertIn("PAYLAŞILAN-HAFIZA", freud_prompt)
        self.assertNotIn(anchor, freud_prompt)
        self.assertIn(app.persona_block("freud"), freud_prompt)
        self.assertIn(app.THERAPY_PROMPT, freud_prompt)

        self.assertIn("PAYLAŞILAN-HAFIZA", lesson_prompt)
        self.assertNotIn(anchor, lesson_prompt)
        self.assertIn(app.persona_block("ferenczi"), lesson_prompt)
        self.assertIn(app.TEACHER_COMMON, lesson_prompt)
