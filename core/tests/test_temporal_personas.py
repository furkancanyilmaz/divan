from unittest import mock

from support import HTTPTestCase, app


LEGACY_THERAPIST_PERSONA_FRAGMENTS = (
    "2026'ya döndün",
    "hayattasın; 2026'dasın",
    "mirasını temsil",
    "mirasını canlandır",
    "yaklaşımını canlandır",
)


class TemporalPersonaContractTests(HTTPTestCase):

    @staticmethod
    def _normalized(text):
        return " ".join(str(text or "").casefold().split())

    def test_temporal_contracts_cover_death_sources_uncertainty_and_layers(self):
        contracts = {
            "therapist": self._normalized(
                app.THERAPIST_TEMPORAL_KNOWLEDGE),
            "philosopher": self._normalized(
                app.PHILOSOPHER_TEMPORAL_KNOWLEDGE),
        }

        for kind, contract in contracts.items():
            with self.subTest(kind=kind):
                self.assertIn("yaşamının sona erdiği biliniyorsa", contract)
                self.assertIn("ölüm tarihini", contract)
                self.assertIn("sorulursa doğal ve doğrudan", contract)
                self.assertIn("yalnız saat bağlamıdır", contract)
                self.assertIn("güncelliğini doğrulamaz", contract)
                self.assertIn("kaynak paket", contract)
                self.assertIn("eksik ya da eskimiş", contract)
                self.assertNotIn("bilgi ufkun", contract)
                self.assertIn("tarihsel olarak senin", contract)
                self.assertRegex(contract, r"sonradan|senden sonra")
                self.assertRegex(contract, r"bugünkü (?:kanıt|bilgi) ışığında")
                self.assertIn("kişisel an", contract)
                self.assertIn("uydurma", contract)

    def test_every_therapist_prompt_receives_temporal_contract_once(self):
        for therapist_id in sorted(app.THERAPISTS):
            for mode in ("terapi", "ders"):
                with self.subTest(therapist=therapist_id, mode=mode):
                    conv_id = self.conversation(
                        mode=mode,
                        submode=None if mode == "terapi" else "serbest",
                        therapist=therapist_id,
                    )
                    with mock.patch.object(
                            app.time, "strftime",
                            return_value="02.08.2026"):
                        prompt = self.system_prompt(conv_id)

                    self.assertEqual(
                        prompt.count(app.THERAPIST_TEMPORAL_KNOWLEDGE), 1)
                    self.assertIn("Bugünün tarihi: 02.08.2026.", prompt)

    def test_every_philosopher_prompt_receives_temporal_contract_once(self):
        for philosopher_id in sorted(app.PHILOSOPHERS):
            with self.subTest(philosopher=philosopher_id):
                conv_id = self.conversation(
                    mode="ders",
                    submode="serbest",
                    therapist=philosopher_id,
                )
                with mock.patch.object(
                        app.time, "strftime", return_value="02.08.2026"):
                    prompt = self.system_prompt(conv_id)

                self.assertEqual(
                    prompt.count(app.PHILOSOPHER_TEMPORAL_KNOWLEDGE), 1)
                self.assertIn("Bugünün tarihi: 02.08.2026.", prompt)

    def test_raw_therapist_personas_drop_legacy_time_travel_and_representation(self):
        for therapist_id, therapist in app.THERAPISTS.items():
            with self.subTest(therapist=therapist_id):
                persona = self._normalized(therapist["persona"])
                for fragment in LEGACY_THERAPIST_PERSONA_FRAGMENTS:
                    self.assertNotIn(fragment, persona)

    def test_therapist_and_living_person_contracts_never_claim_real_identity(self):
        therapist = self._normalized(app.SHARED_TAIL)
        philosopher = self._normalized(app.PHILOSOPHER_TAIL)
        for kind, contract in (
                ("therapist", therapist), ("philosopher", philosopher)):
            with self.subTest(kind=kind):
                self.assertIn("ai canlandırması", contract)
                self.assertIn("gerçek", contract)
                self.assertIn("onay", contract)
                self.assertIn("özel erişim", contract)

    def test_late_turn_anchor_reasserts_posthumous_source_and_ai_boundary(self):
        conversations = (
            self.conversation(therapist="freud"),
            self.conversation(
                mode="ders", submode="serbest", therapist="nietzsche"),
        )

        for conv_id in conversations:
            conv = self.conversation_row(conv_id)
            with self.subTest(master=conv["therapist"]):
                anchor = self._normalized(app.late_turn_anchor(conv))

                self.assertIn("verilen bugünün tarihine sadık kal", anchor)
                self.assertIn("tarih güncellik kanıtı değildir", anchor)
                self.assertIn("ölmüşse bunu bilir", anchor)
                self.assertIn(
                    "ölümünden sonraki bir gelişmeyi yalnız sağlanan kaynak",
                    anchor,
                )
                self.assertIn("kişisel anısı", anchor)
                self.assertIn("bugünkü faaliyeti gibi sahiplenmez", anchor)
                self.assertIn("en yeni/güncel diye sunma", anchor)
                self.assertIn("bu bir ai canlandırmasıdır", anchor)
                self.assertIn("kişinin onayı", anchor)
