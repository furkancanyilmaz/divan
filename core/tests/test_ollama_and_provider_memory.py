"""Ollama desteği ve sağlayıcılar arası ayar belleği için testler.

Kullanıcı senaryosu: DeepSeek anahtarı/modeli kaydedilir, LM Studio'ya
geçilir, ertesi gün DeepSeek'e dönülür — değerler kaybolmamalı. Ollama da
sağlayıcı listesinde yer almalı ve açık yerel sunucular taranabilmeli.
"""

import json
from unittest import mock

from support import HTTPTestCase, app


LOCAL_ENV_KEYS = (
    "OLLAMA_API_KEY", "OLLAMA_MODEL", "OLLAMA_BASE_URL",
    "LMSTUDIO_API_KEY", "LMSTUDIO_MODEL", "LMSTUDIO_BASE_URL",
)


class OllamaProviderTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self._saved_env = {
            key: app.os.environ[key]
            for key in LOCAL_ENV_KEYS if key in app.os.environ
        }
        for key in LOCAL_ENV_KEYS:
            app.os.environ.pop(key, None)
        with app.LOCAL_MODEL_CACHE_LOCK:
            app.LOCAL_MODEL_CACHE.clear()

    def tearDown(self):
        for key in LOCAL_ENV_KEYS:
            app.os.environ.pop(key, None)
        app.os.environ.update(self._saved_env)
        with app.LOCAL_MODEL_CACHE_LOCK:
            app.LOCAL_MODEL_CACHE.clear()
        super().tearDown()

    def test_ollama_is_a_local_provider_with_its_own_default_address(self):
        self.assertIn("ollama", app.PROVIDERS)
        info = app.PROVIDERS["ollama"]
        self.assertTrue(info["local"])
        self.assertFalse(info["key_required"])
        self.assertEqual(info["default_base_url"], "http://127.0.0.1:11434/v1")
        self.assertTrue(app.is_local_provider("ollama"))
        self.assertTrue(app.is_local_provider("lmstudio"))
        self.assertFalse(app.is_local_provider("deepseek"))

    def test_ollama_config_resolves_model_auto_and_openai_endpoint(self):
        app.set_setting("llm_provider", "ollama")

        config = app.provider_config(resolve_local_model=False)

        self.assertEqual(config["id"], "ollama")
        self.assertEqual(config["model"], "auto")
        self.assertEqual(config["base_url"], "http://127.0.0.1:11434/v1")
        self.assertEqual(
            config["endpoint"], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertTrue(config["local"])

    def test_ollama_respects_stored_base_url_and_model(self):
        app.set_setting("llm_provider", "ollama")
        app.set_setting("ollama_model", "llama3.1")
        app.set_setting("ollama_base_url", "http://127.0.0.1:11434")

        config = app.provider_config(resolve_local_model=False)

        self.assertEqual(config["model"], "llama3.1")
        self.assertEqual(config["base_url"], "http://127.0.0.1:11434/v1")

    def test_normalize_local_base_url_uses_provider_default(self):
        self.assertEqual(
            app.normalize_local_base_url("", provider="ollama"),
            "http://127.0.0.1:11434/v1")
        self.assertEqual(
            app.normalize_local_base_url("", provider="lmstudio"),
            "http://127.0.0.1:1234/v1")

    def test_switching_to_local_provider_keeps_deepseek_credentials(self):
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("deepseek_model", "deepseek-chat")
        app.set_setting("deepseek_api_key", "derin-anahtar")

        status, body, _ = self.request("POST", "/api/settings", {
            "provider": "ollama",
            "ollama_model": "auto",
            "ollama_base_url": "http://127.0.0.1:11434/v1",
        })

        self.assertEqual(status, 200, body)
        self.assertEqual(app.get_setting("llm_provider"), "ollama")
        self.assertEqual(app.get_setting("deepseek_api_key"), "derin-anahtar")
        self.assertEqual(app.get_setting("deepseek_model"), "deepseek-chat")
        self.assertEqual(app.get_setting("ollama_base_url"),
                         "http://127.0.0.1:11434/v1")

    def test_settings_get_lists_ollama_with_its_own_row(self):
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("deepseek_model", "deepseek-chat")
        app.set_setting("deepseek_api_key", "derin-anahtar")
        app.set_setting("ollama_model", "auto")
        app.set_setting("ollama_base_url", "http://127.0.0.1:11434/v1")

        status, body, _ = self.request("GET", "/api/settings")

        self.assertEqual(status, 200)
        self.assertEqual(body["provider"], "deepseek")
        self.assertIn("ollama", body["providers"])
        ollama_row = body["providers"]["ollama"]
        self.assertEqual(ollama_row["model"], "auto")
        self.assertEqual(ollama_row["base_url"], "http://127.0.0.1:11434/v1")
        self.assertTrue(ollama_row["local"])
        self.assertTrue(body["providers"]["deepseek"]["key_set"])

    def test_provider_model_snapshot_allows_auto_for_ollama(self):
        app.set_setting("llm_provider", "ollama")
        provider, model = app._configured_provider_model_snapshot("ollama")
        self.assertEqual(provider, "ollama")
        self.assertEqual(model, "auto")
        self.assertEqual(
            app._validated_postprocess_provider_snapshot("ollama", "auto"),
            ("ollama", "auto"))

    def test_scan_all_reports_detected_server_provider_ids(self):
        def fake_discover(base_url, secret="", use_cache=True):
            if "11434" in str(base_url):
                return ["llama3.1"]
            if "1234" in str(base_url):
                return ["local-model"]
            return []

        with mock.patch.object(
                app, "discover_local_models", side_effect=fake_discover):
            status, body, _ = self.request(
                "POST", "/api/provider/models", {"scan_all": True})

        self.assertEqual(status, 200)
        servers = {row["provider"]: row for row in body["servers"]}
        self.assertIn("ollama", servers)
        self.assertEqual(servers["ollama"]["models"], ["llama3.1"])
        self.assertEqual(servers["ollama"]["base_url"],
                         "http://127.0.0.1:11434/v1")
        self.assertIn("lmstudio", servers)
        self.assertEqual(servers["lmstudio"]["models"], ["local-model"])
        self.assertEqual(servers["lmstudio"]["base_url"],
                         "http://127.0.0.1:1234/v1")
        # Model bulunamayan sunucular listede yer almaz.
        self.assertNotIn("", servers)

    def test_provider_models_endpoint_accepts_ollama_provider(self):
        def fake_discover(base_url, secret="", use_cache=True):
            self.assertIn("11434", str(base_url))
            return ["qwen2.5"]

        with mock.patch.object(
                app, "discover_local_models", side_effect=fake_discover):
            status, body, _ = self.request(
                "POST", "/api/provider/models", {"provider": "ollama"})

        self.assertEqual(status, 200)
        self.assertEqual(body["models"], ["qwen2.5"])
        self.assertEqual(body["servers"][0]["provider"], "ollama")

    def test_chat_prompt_uses_local_layout_for_ollama(self):
        conv_id = self.conversation()
        self.messages(conv_id, 4)
        with app.db() as conn:
            newest = conn.execute(
                "SELECT id FROM messages WHERE conv=? AND role='user' "
                "ORDER BY id DESC LIMIT 1", (conv_id,)).fetchone()

        def request_row(provider):
            return {
                "conv": conv_id,
                "user_message": newest["id"],
                "reply_to": None,
                "guidance": "",
                "method_key": None,
                "method_id": None,
                "provider": provider,
                "model": "auto" if provider == "ollama" else "local-model",
                "fast": 0,
                "attempt_count": 1,
            }

        _, ollama_payload = app._chat_prompt_payload(request_row("ollama"))
        _, lmstudio_payload = app._chat_prompt_payload(request_row("lmstudio"))

        # Yerel sağlayıcılarda sistem talimatı pozisyon sıfırda kalır ve
        # mesaj bütçesi aynı yerel kurallarla kesilir: ollama, lmstudio ile
        # birebir aynı istem düzenini üretir.
        self.assertEqual(
            ollama_payload["messages"], lmstudio_payload["messages"])
        self.assertEqual(ollama_payload["messages"][0]["role"], "system")
        self.assertNotEqual(
            ollama_payload["messages"][-1]["role"],
            "system")

    def test_local_delivery_notice_names_ollama(self):
        notice = app._chat_delivery_notice("ollama")
        self.assertIn("Ollama", notice)
        self.assertNotEqual(notice, app._chat_delivery_notice("deepseek"))
