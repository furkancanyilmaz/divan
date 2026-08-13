import unittest

from support import HTTPTestCase, app


class TherapyVoiceContractCatalogTests(unittest.TestCase):

    def test_contract_catalog_exactly_covers_every_therapist(self):
        self.assertEqual(
            set(app.THERAPY_VOICE_CONTRACTS),
            set(app.THERAPISTS),
        )
        self.assertEqual(len(app.THERAPY_VOICE_CONTRACTS), 34)

    def test_every_contract_has_only_the_required_nonempty_short_fields(self):
        required = set(app.THERAPY_VOICE_CONTRACT_FIELDS)
        self.assertEqual(
            required,
            {
                "analysis_unit",
                "attention_order",
                "change_mechanism",
                "response_shape",
                "question_policy",
                "repair_style",
                "closing_style",
                "forbidden_borrowing",
            },
        )

        for therapist_id, contract in app.THERAPY_VOICE_CONTRACTS.items():
            with self.subTest(therapist=therapist_id):
                self.assertEqual(set(contract), required)
                for field in app.THERAPY_VOICE_CONTRACT_FIELDS:
                    value = contract[field]
                    self.assertIsInstance(value, str)
                    self.assertEqual(value, value.strip())
                    self.assertTrue(value)
                    self.assertLessEqual(len(value), 420)

    def test_contracts_and_each_behavioral_field_are_unique(self):
        fields = app.THERAPY_VOICE_CONTRACT_FIELDS
        signatures = [
            tuple(contract[field] for field in fields)
            for contract in app.THERAPY_VOICE_CONTRACTS.values()
        ]
        self.assertEqual(len(signatures), len(set(signatures)))

        for field in fields:
            with self.subTest(field=field):
                values = [
                    contract[field]
                    for contract in app.THERAPY_VOICE_CONTRACTS.values()
                ]
                self.assertEqual(
                    len(values),
                    len(set(values)),
                    "{} alanı ustalar arasında özgün olmalı".format(field),
                )

    def test_every_contract_explicitly_blocks_unrequested_school_mixing(self):
        shared_rule = app.THERAPY_VOICE_BORROWING_RULE
        self.assertIn("açıkça karşılaştırma istemedikçe", shared_rule)
        self.assertIn("başka ekolün kavramını", shared_rule)
        self.assertIn("soru biçimini", shared_rule)
        self.assertIn("müdahalesini", shared_rule)

        unsafe_mixing_phrases = (
            "ekollerin en iyi yönlerini birleştir",
            "başka ekolleri serbestçe harmanla",
            "gerektiğinde başka ekole geç",
            "bütün ekolleri sentezle",
        )
        for therapist_id, contract in app.THERAPY_VOICE_CONTRACTS.items():
            with self.subTest(therapist=therapist_id):
                boundary = contract["forbidden_borrowing"]
                self.assertTrue(boundary.startswith(shared_rule + " "))
                self.assertGreater(len(boundary), len(shared_rule) + 20)
                folded = " ".join(boundary.casefold().split())
                for phrase in unsafe_mixing_phrases:
                    self.assertNotIn(phrase, folded)

    def test_helpers_are_safe_complete_and_do_not_expose_mutable_catalog(self):
        labels = (
            "Analiz birimi:",
            "Dikkat sırası:",
            "Değişim mekanizması:",
            "Yanıt biçimi:",
            "Soru politikası:",
            "Onarım biçimi:",
            "Kapanış biçimi:",
            "Ekol sınırı:",
        )

        for therapist_id in app.THERAPISTS:
            with self.subTest(therapist=therapist_id):
                stored = app.THERAPY_VOICE_CONTRACTS[therapist_id]
                returned = app.therapy_voice_contract(therapist_id)
                prompt = app.therapy_voice_prompt(therapist_id)

                self.assertEqual(returned, stored)
                self.assertIsNot(returned, stored)
                self.assertIn(app.THERAPISTS[therapist_id]["name"], prompt)
                for label in labels:
                    self.assertEqual(prompt.count(label), 1)
                for field in app.THERAPY_VOICE_CONTRACT_FIELDS:
                    self.assertEqual(prompt.count(stored[field]), 1)

                returned["analysis_unit"] = "değiştirildi"
                self.assertNotEqual(
                    app.THERAPY_VOICE_CONTRACTS[therapist_id][
                        "analysis_unit"],
                    "değiştirildi",
                )

        self.assertEqual(app.therapy_voice_contract("bilinmeyen"), {})
        self.assertEqual(app.therapy_voice_prompt("bilinmeyen"), "")


class TherapyVoicePromptPlacementTests(HTTPTestCase):

    def test_voice_contract_is_once_near_end_before_existing_fingerprint(self):
        for therapist_id in app.THERAPISTS:
            with self.subTest(therapist=therapist_id):
                conv_id = self.conversation(therapist=therapist_id)
                prompt = self.system_prompt(conv_id)
                voice = app.therapy_voice_prompt(therapist_id)
                fingerprint = app.therapy_fingerprint(therapist_id)

                self.assertEqual(prompt.count(voice), 1)
                self.assertLess(prompt.index(voice), prompt.index(fingerprint))
                self.assertTrue(prompt.endswith(fingerprint))
                self.assertLess(
                    prompt.index(fingerprint) - prompt.index(voice),
                    len(voice) + 10,
                )

    def test_voice_contract_is_not_in_lesson_mode(self):
        conv_id = self.conversation(
            mode="ders",
            therapist="freud",
            submode="serbest",
        )
        prompt = self.system_prompt(conv_id)

        self.assertNotIn(app.therapy_voice_prompt("freud"), prompt)
        self.assertNotIn("## Sigmund Freud için yapılandırılmış klinik ses",
                         prompt)


if __name__ == "__main__":
    unittest.main()
