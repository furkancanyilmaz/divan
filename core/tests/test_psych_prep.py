import unittest

from support import HTTPTestCase, app


class PsychPrepTests(HTTPTestCase):

    def test_prep_roundtrip_and_summary_marks_unfilled(self):
        status, body, _ = self.request("GET", "/api/psych-prep")
        self.assertEqual(status, 200)
        self.assertEqual(body["sections"], {})
        self.assertGreaterEqual(len(body["unevaluable"]), 4)

        status, body, _ = self.request(
            "POST", "/api/psych-prep",
            {"sections": {
                "reason": "Üç aydır süren yorgunluk ve isteksizlik.",
                "sleep": "Günde 5 saat; eskiden 7-8 uyurdum.",
            }})
        self.assertEqual(status, 200)

        status, body, _ = self.request("GET", "/api/psych-prep")
        self.assertEqual(
            body["sections"]["reason"],
            "Üç aydır süren yorgunluk ve isteksizlik.")

        status, body, _ = self.request("GET", "/api/psych-prep/summary")
        self.assertEqual(status, 200)
        summary = body["summary"]
        self.assertIn("PSİKİYATRİ GÖRÜŞMESİNE HAZIRLIK ÖZETİ", summary)
        self.assertIn("Üç aydır süren yorgunluk", summary)
        self.assertIn("değerlendirilemedi", summary)
        self.assertIn("Klinik yargı ve tanı", summary)
        self.assertNotIn("tanı öner", summary.splitlines()[1])

    def test_prep_ignores_unknown_sections(self):
        status, body, _ = self.request(
            "POST", "/api/psych-prep",
            {"sections": {"reason": "X", "tani": "Y"}})
        self.assertEqual(status, 200)
        status, body, _ = self.request("GET", "/api/psych-prep")
        self.assertNotIn("tani", body["sections"])
        self.assertEqual(body["sections"]["reason"], "X")

    def test_encrypted_summary_requires_passphrase(self):
        status, body, _ = self.request(
            "POST", "/api/psych-prep/encrypted",
            {"passphrase": "kisa"})
        self.assertEqual(status, 400)

        status, payload, _ = self.request(
            "POST", "/api/psych-prep/encrypted",
            {"passphrase": "dogru-at-gunluk-sifre"})
        self.assertEqual(status, 200)
        self.assertTrue(payload.startswith(b"Salted__"))


if __name__ == "__main__":
    unittest.main()
