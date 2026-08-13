import unittest

from support import HTTPTestCase, app


class SafetyPlanTests(HTTPTestCase):

    def test_safety_plan_roundtrip(self):
        status, body, _ = self.request("GET", "/api/safety-plan")
        self.assertEqual(status, 200)
        self.assertEqual(body["plan"]["warning_signs"], "")
        self.assertGreaterEqual(len(body["resources"]), 3)

        status, body, _ = self.request(
            "POST", "/api/safety-plan",
            {
                "warning_signs": "Uykusuzluk, içe kapanma.",
                "coping_steps": "Yürüyüş, arkadaşı aramak.",
                "people": "Eşim, yakın arkadaşım.",
            })
        self.assertEqual(status, 200)

        status, body, _ = self.request("GET", "/api/safety-plan")
        self.assertEqual(body["plan"]["warning_signs"],
                         "Uykusuzluk, içe kapanma.")
        self.assertEqual(body["plan"]["people"], "Eşim, yakın arkadaşım.")

    def test_safety_hold_prompt_carries_plan_and_resources(self):
        status, plan_body, _ = self.request(
            "POST", "/api/safety-plan",
            {
                "warning_signs": "İçe kapanma ve uykusuzluk.",
                "coping_steps": "Nefes ve yürüyüş.",
                "people": "Ablam.",
            })
        self.assertEqual(status, 200)
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))
        prompt = self.system_prompt(conv_id)
        self.assertIn("Etkin güvenlik desteği", prompt)
        self.assertIn("İçe kapanma ve uykusuzluk", prompt)
        self.assertIn("ALO 182", prompt)
        self.assertIn("112", prompt)
        # Asla söz verme kuralı
        self.assertIn("sözü verme", prompt)

    def test_checkin_and_progress_flow(self):
        conv_id = self.conversation(therapist="freud")
        status, body, _ = self.request(
            "POST", "/api/checkin",
            {"conv_id": conv_id, "mood": 6, "energy": 7, "anxiety": 4,
             "note": "Bugün daha iyi."})
        self.assertEqual(status, 200)
        status, body, _ = self.request("GET", "/api/progress")
        self.assertEqual(status, 200)
        self.assertTrue(body["checkins"])
        latest = body["checkins"][0]
        self.assertEqual(latest["conv"], conv_id)
        self.assertEqual(latest["mood"], 6)
        self.assertEqual(latest["note"], "Bugün daha iyi.")

    def test_safety_hold_silences_concept_layer_but_not_checkin(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))
        self.assertEqual(app.scan_concepts(conv_id), 0)
        self.assertEqual(app.record_rupture(conv_id), None)
        status, _, _ = self.request(
            "POST", "/api/checkin",
            {"conv_id": conv_id, "mood": 5})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
