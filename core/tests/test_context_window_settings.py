import unittest
from pathlib import Path

from support import HTTPTestCase, PROJECT_DIR, app


class ContextWindowHelperTests(HTTPTestCase):

    def test_default_and_validation_boundaries(self):
        self.assertEqual(
            app.context_window_tokens(),
            app.DEFAULT_CONTEXT_WINDOW_TOKENS,
        )
        self.assertEqual(app.clean_context_window_tokens(8192), 8192)
        self.assertEqual(app.clean_context_window_tokens(20000), 20000)
        self.assertEqual(
            app.clean_context_window_tokens("262144"), 262144)
        self.assertEqual(app.clean_context_window_tokens(32768.0), 32768)

        for value in (8191, 262145, True, 8192.5, "çok"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    app.clean_context_window_tokens(value)

    def test_budgets_are_provider_aware_and_conservative(self):
        window = 32768
        cloud_output = app.chat_output_token_budget(
            "deepseek", window)
        local_output = app.chat_output_token_budget(
            "lmstudio", window)
        self.assertEqual(cloud_output, app.MAX_TOKENS_CHAT)
        self.assertEqual(local_output, 4096)
        self.assertLess(local_output, cloud_output)

        cloud_chars = app.chat_input_char_budget("deepseek", window)
        local_chars = app.chat_input_char_budget("lmstudio", window)
        self.assertEqual(
            cloud_chars,
            (window - cloud_output - window // 16) *
            app.CONSERVATIVE_INPUT_CHARS_PER_TOKEN,
        )
        self.assertEqual(
            local_chars,
            (window - local_output - window // 16) *
            app.CONSERVATIVE_INPUT_CHARS_PER_TOKEN,
        )
        self.assertLess(
            cloud_chars,
            window * app.CONSERVATIVE_INPUT_CHARS_PER_TOKEN,
        )

    def test_settings_api_round_trip_and_reports_active_budgets(self):
        status, initial, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(initial["context_window_tokens"], 32768)
        self.assertEqual(
            initial["context_window_options"],
            list(app.CONTEXT_WINDOW_TOKEN_OPTIONS),
        )

        status, body, _ = self.request(
            "POST", "/api/settings",
            {"provider": "lmstudio", "context_window_tokens": 65536},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        status, saved, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(saved["context_window_tokens"], 65536)
        self.assertEqual(
            saved["chat_output_token_budget"],
            app.chat_output_token_budget("lmstudio", 65536),
        )
        self.assertEqual(
            saved["chat_input_char_budget"],
            app.chat_input_char_budget("lmstudio", 65536),
        )

    def test_invalid_api_value_is_rejected_without_overwriting_setting(self):
        app.set_setting("context_window_tokens", "32768")
        for value in (8191, 262145, "geçersiz"):
            with self.subTest(value=value):
                status, body, _ = self.request(
                    "POST", "/api/settings",
                    {"context_window_tokens": value},
                )
                self.assertEqual(status, 400)
                self.assertIn("bağlam penceresi", body["error"])
                self.assertEqual(
                    app.get_setting("context_window_tokens"), "32768")

    def test_bad_legacy_value_falls_back_without_mutating_database(self):
        app.set_setting("context_window_tokens", "999999")
        self.assertEqual(
            app.context_window_tokens(),
            app.DEFAULT_CONTEXT_WINDOW_TOKENS,
        )
        self.assertEqual(
            app.get_setting("context_window_tokens"), "999999")


class ContextWindowSettingsUISourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")

    def test_settings_has_all_context_window_choices(self):
        self.assertIn('id="contextWindowTokens"', self.html)
        for value in app.CONTEXT_WINDOW_TOKEN_OPTIONS:
            with self.subTest(value=value):
                self.assertIn(
                    '<option value="{}"'.format(value), self.html)
        self.assertIn("32K · önerilen", self.html)

    def test_context_window_loads_and_saves_with_settings(self):
        self.assertIn(
            "r.context_window_tokens", self.html)
        self.assertIn(
            "context_window_tokens:+$('contextWindowTokens').value",
            self.html)


if __name__ == "__main__":
    unittest.main()
