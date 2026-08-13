import unittest
from unittest import mock

from support import HTTPTestCase, app


class FastTurnRoutingTests(HTTPTestCase):

    def _enable_secondary(self):
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("deepseek_model", "deepseek-v4-pro")
        app.set_setting("deepseek_api_key", "test-key")
        app.set_setting("secondary_provider", "deepseek")
        app.set_setting("secondary_model", "deepseek-v4-flash")

    def test_snapshot_requires_tempo_mode_short_message_and_no_technique(self):
        self._enable_secondary()
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            conv = c.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,)).fetchone()
            self.assertIsNotNone(app._fast_turn_snapshot(
                c, conv, "kısa bir mesaj", None))

        # Tempo modu kapalıyken hızlı tur yok
        app.set_setting("fast_chat_enabled", "0")
        with app.db() as c:
            self.assertIsNone(app._fast_turn_snapshot(
                c, conv, "kısa bir mesaj", None))
        app.set_setting("fast_chat_enabled", "1")

        # Uzun mesaj derin modele kalır
        with app.db() as c:
            self.assertIsNone(app._fast_turn_snapshot(
                c, conv, "x" * 300, None))

        # Yöntem isteği derin modele kalır
        with app.db() as c:
            self.assertIsNone(app._fast_turn_snapshot(
                c, conv, "kısa", "freud:aktarm-oruntusu"))

        # Etkin teknik çalışması derin modele kalır
        with app.db() as c:
            c.execute(
                "INSERT INTO technique_runs(conv,therapist,method_key,"
                "method_name,status,phase,created,updated) "
                "VALUES(?,'freud','freud:aktarm-oruntusu','Aktarım',"
                "'active','work',?,?)",
                (conv_id, app.now(), app.now()))
            self.assertIsNone(app._fast_turn_snapshot(
                c, conv, "kısa", None))

    def test_begin_chat_request_persists_fast_snapshot(self):
        self._enable_secondary()
        conv_id = self.conversation(therapist="freud")
        rid = "f" * 32
        row, created = app.begin_chat_request(
            conv_id, "kısa mesaj", request_id=rid)
        self.assertTrue(created)
        self.assertEqual(row["fast"], 1)
        self.assertEqual(row["provider"], "deepseek")
        self.assertEqual(row["model"], "deepseek-v4-flash")

    def test_long_message_stays_on_primary(self):
        self._enable_secondary()
        conv_id = self.conversation(therapist="freud")
        rid = "e" * 32
        row, created = app.begin_chat_request(
            conv_id, "x" * 400, request_id=rid)
        self.assertTrue(created)
        self.assertEqual(row["fast"], 0)
        self.assertEqual(row["model"], "deepseek-v4-pro")

    def test_fast_payload_caps_output_budget(self):
        self._enable_secondary()
        conv_id = self.conversation(therapist="freud")
        rid = "d" * 32
        row, created = app.begin_chat_request(
            conv_id, "kısa", request_id=rid)
        self.assertTrue(created)
        with app.db() as c:
            c.execute(
                "UPDATE chat_requests SET provider='deepseek',"
                "model='deepseek-v4-flash' WHERE request_id=?", (rid,))
            row = app.chat_request_row(rid, c)
        _, payload = app._chat_prompt_payload(row)
        self.assertEqual(payload["max_tokens"],
                         app.FAST_TURN_OUTPUT_TOKENS)

    def test_crisis_message_never_routes_to_fast(self):
        self._enable_secondary()
        conv_id = self.conversation(therapist="freud")
        rid = "c" * 32
        row, created = app.begin_chat_request(
            conv_id, "kendime zarar vermek istiyorum", request_id=rid)
        self.assertTrue(created)
        self.assertEqual(row["fast"], 0)
        self.assertEqual(row["model"], "deepseek-v4-pro")

    def test_chat_format_rule_forbids_markdown(self):
        folded = app.THERAPY_PROMPT.casefold()
        self.assertIn("madde işareti", folded)
        self.assertIn("markdown biçimi", folded)


if __name__ == "__main__":
    unittest.main()
