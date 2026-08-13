import unittest
from unittest import mock

from support import HTTPTestCase, app


class DeterministicHistoricalClosingTests(unittest.TestCase):

    def test_philosophy_closings_cover_all_thinkers_and_are_distinct(self):
        self.assertEqual(
            set(app.PHILOSOPHY_DIALOGUE_CLOSINGS),
            set(app.PHILOSOPHERS),
        )
        self.assertEqual(len(app.PHILOSOPHY_DIALOGUE_CLOSINGS), 41)
        signatures = tuple(app.PHILOSOPHY_DIALOGUE_CLOSINGS.values())
        self.assertEqual(len(signatures), len(set(signatures)))
        for philosopher_id, signature in (
                app.PHILOSOPHY_DIALOGUE_CLOSINGS.items()):
            with self.subTest(philosopher=philosopher_id):
                self.assertEqual(signature, signature.strip())
                self.assertGreaterEqual(len(signature.split()), 12)
                self.assertLessEqual(len(signature), 360)
                closing = app.philosophy_dialogue_closing(philosopher_id)
                self.assertTrue(closing.endswith(signature))
                self.assertEqual(closing.count(signature), 1)
                self.assertNotIn("?", closing)

    def test_therapy_lesson_closings_cover_all_founders_and_are_distinct(self):
        self.assertEqual(
            set(app.THERAPY_LESSON_CLOSINGS),
            set(app.THERAPISTS),
        )
        self.assertEqual(len(app.THERAPY_LESSON_CLOSINGS), 34)
        signatures = tuple(app.THERAPY_LESSON_CLOSINGS.values())
        self.assertEqual(len(signatures), len(set(signatures)))
        for therapist_id, signature in app.THERAPY_LESSON_CLOSINGS.items():
            with self.subTest(therapist=therapist_id):
                self.assertEqual(signature, signature.strip())
                self.assertGreaterEqual(len(signature.split()), 12)
                self.assertLessEqual(len(signature), 360)
                closing = app.therapy_lesson_closing(therapist_id)
                self.assertTrue(closing.endswith(signature))
                self.assertEqual(closing.count(signature), 1)
                self.assertNotIn("?", closing)

    def test_closings_show_no_prompt_contract_or_false_relationship_claim(self):
        prohibited = (
            "fingerprint",
            "persona",
            "yapılandırılmış ses",
            "kapanış biçimi",
            "seni özledim",
            "yalnız ben",
            "her zaman buradayım",
            "bana ihtiyacın",
            "sana söz veriyorum",
            "aramızdaki özel",
        )
        closings = [
            app.philosophy_dialogue_closing(master_id)
            for master_id in app.PHILOSOPHERS
        ] + [
            app.therapy_lesson_closing(master_id)
            for master_id in app.THERAPISTS
        ]
        for closing in closings:
            folded = closing.casefold()
            for fragment in prohibited:
                self.assertNotIn(fragment, folded)
            self.assertNotIn('"', closing)
            self.assertNotIn("“", closing)
            self.assertNotIn("”", closing)

    def test_representative_closings_retain_specific_thought_movements(self):
        markers = {
            "socrates": ("tanımlamış", "çelişkinin"),
            "spinoza": ("duygulanımı", "nedenlerle"),
            "wittgenstein": ("dil oyunu", "yaşam biçimi"),
            "arendt": ("emek, iş ve eylem", "çoğul"),
            "vaclav_smil": ("büyüklük mertebesini", "stok–akış"),
            "david_christian": ("karmaşıklık eşiğinin", "kırılganlıklar"),
            "steve_jobs": ("gereksizi çıkaralım", "prototipte"),
        }
        for thinker, expected in markers.items():
            closing = app.philosophy_dialogue_closing(thinker).casefold()
            for marker in expected:
                self.assertIn(marker.casefold(), closing)

        lesson_markers = {
            "freud": ("çağrışımın", "çatışmayı"),
            "ferenczi": ("güç", "sınırların"),
            "perls": ("şimdi-burada", "temas"),
            "young": ("sağlıklı yetişkin", "yeniden ebeveynlik"),
            "linehan": ("kabul ve değişimi", "zincir analizini"),
            "shapiro": ("sekiz aşamalı", "güvenliği"),
        }
        for teacher, expected in lesson_markers.items():
            closing = app.therapy_lesson_closing(teacher).casefold()
            for marker in expected:
                self.assertIn(marker.casefold(), closing)

    def test_unknown_ids_have_short_deterministic_fallbacks(self):
        philosophy = app.philosophy_dialogue_closing("bilinmeyen")
        lesson = app.therapy_lesson_closing("bilinmeyen")
        self.assertEqual(
            philosophy,
            app.philosophy_dialogue_closing(None),
        )
        self.assertEqual(lesson, app.therapy_lesson_closing(None))
        self.assertIn("kesin bir sonuca zorlamadan", philosophy)
        self.assertIn("kesin bir sonuca zorlamadan", lesson)


class HistoricalClosingAPITests(HTTPTestCase):

    def assert_api_close(self, master_id, expected):
        conv_id = self.conversation(
            mode="ders",
            submode="serbest",
            therapist=master_id,
            title="Kapanış sınaması",
        )
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("kapanış model çağrısı yapmamalı")
        ) as model_call:
            status, body, _ = self.request(
                "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(status, 200, body)
        self.assertFalse(model_call.called)
        self.assertEqual(body["closing"], expected)
        stored = self.row(
            "SELECT content FROM messages WHERE conv=? AND role='assistant' "
            "ORDER BY id DESC LIMIT 1",
            (conv_id,),
        )
        self.assertEqual(stored["content"], expected)

    def test_api_end_uses_thinker_specific_deterministic_close(self):
        self.assert_api_close(
            "vaclav_smil",
            app.philosophy_dialogue_closing("vaclav_smil"),
        )

    def test_api_end_uses_therapy_founder_specific_lesson_close(self):
        self.assert_api_close(
            "ferenczi",
            app.therapy_lesson_closing("ferenczi"),
        )


if __name__ == "__main__":
    unittest.main()
