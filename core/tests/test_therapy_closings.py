import unittest
from unittest import mock

from support import HTTPTestCase, app


class DeterministicTherapyClosingTests(unittest.TestCase):

    def test_catalog_exactly_covers_all_therapists_with_unique_signatures(self):
        self.assertEqual(
            set(app.THERAPY_CLOSING_SIGNATURES),
            set(app.THERAPISTS),
        )
        self.assertEqual(len(app.THERAPY_CLOSING_SIGNATURES), 34)
        signatures = list(app.THERAPY_CLOSING_SIGNATURES.values())
        self.assertEqual(len(signatures), len(set(signatures)))
        for therapist_id, signature in app.THERAPY_CLOSING_SIGNATURES.items():
            with self.subTest(therapist=therapist_id):
                self.assertIsInstance(signature, str)
                self.assertEqual(signature, signature.strip())
                self.assertTrue(signature)
                self.assertLessEqual(len(signature), 360)

    def test_each_closing_carries_target_outcome_and_unique_school_voice(self):
        outcome_markers = {
            "reached": "bugün varmak istediğiniz yere vardınız",
            "partial": "bir kısmını birlikte açtık",
            "paused": "çalışmayı bugün duraklattınız",
            "unchanged": "sonuca varmak zorunda değilsiniz",
        }
        for therapist_id, signature in app.THERAPY_CLOSING_SIGNATURES.items():
            for outcome, marker in outcome_markers.items():
                with self.subTest(
                        therapist=therapist_id, outcome=outcome):
                    target = "{} özgün hedefi".format(therapist_id)
                    closing = app.therapy_session_closing(
                        therapist_id, target, outcome)
                    self.assertIn("“{}”".format(target), closing)
                    self.assertIn(marker, closing)
                    self.assertTrue(closing.endswith(signature))
                    self.assertEqual(closing.count(signature), 1)

    def test_closings_make_no_clinical_or_dependency_claim(self):
        unsafe_claims = (
            "iyileştiniz",
            "iyileşeceksiniz",
            "artık düzeldiniz",
            "başardınız",
            "tanınız",
            "seni özledim",
            "yalnız ben",
            "her zaman buradayım",
            "bana ihtiyacın",
            "sana söz veriyorum",
            "işaretlediniz",
            "harita kaydı",
        )
        for therapist_id in app.THERAPISTS:
            with self.subTest(therapist=therapist_id):
                closing = app.therapy_session_closing(
                    therapist_id, "Seans hedefi", "reached").casefold()
                for claim in unsafe_claims:
                    self.assertNotIn(claim, closing)
                self.assertIn(
                    "kesin bir yargı değil", closing)

    def test_shapiro_close_stays_inside_present_orientation_boundary(self):
        signature = app.THERAPY_CLOSING_SIGNATURES["shapiro"].casefold()
        for phrase in (
                "kapanış yalnız şimdiye yönelimle sınırlı",
                "bulunduğunuz yer",
                "bugünün tarihi",
                "güvenli destek"):
            self.assertIn(phrase, signature)
        for prohibited_procedure in (
                "hedef anı",
                "göz hareketi",
                "çift yönlü uyarım",
                "beden taraması",
                "maruz bırakma"):
            self.assertNotIn(prohibited_procedure, signature)
        self.assertIn("uygulanmış veya tamamlanmış sayılmaz", signature)

    def test_unknown_input_has_safe_deterministic_fallback(self):
        expected = app.therapy_session_closing(
            "bilinmeyen", "", "geçersiz")
        self.assertEqual(
            expected,
            app.therapy_session_closing("bilinmeyen", None, None),
        )
        self.assertIn("“bugünkü çalışma”", expected)
        self.assertIn("sonuca varmak zorunda değilsiniz", expected)
        self.assertIn("sonuç vaadine", expected)


class TherapyClosingAPITests(HTTPTestCase):

    def test_api_end_uses_targeted_voice_close_without_model_call(self):
        status, created, _ = self.request(
            "POST", "/api/new", {
                "mode": "terapi",
                "therapist": "perls",
                "map_node_id": "perls:method:two-chair-conflict",
            })
        self.assertEqual(status, 200, created)
        target_name = created["map"]["target"]["node_name"]

        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("kapanış model çağrısı yapmamalı")
        ) as model_call:
            status, ended, _ = self.request(
                "POST", "/api/end", {
                    "conv_id": created["id"],
                    "map_outcome": "partial",
                    "map_fit": "unclear",
                })

        self.assertEqual(status, 200, ended)
        self.assertFalse(model_call.called)
        expected = app.therapy_session_closing(
            "perls", target_name, "partial")
        self.assertEqual(ended["closing"], expected)
        stored = self.row(
            "SELECT content FROM messages WHERE conv=? AND role='assistant' "
            "ORDER BY id DESC LIMIT 1",
            (created["id"],),
        )
        self.assertEqual(stored["content"], expected)

