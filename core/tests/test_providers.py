import io
import json
from unittest import mock

from support import HTTPTestCase, app


PROVIDER_ENV_KEYS = (
    "DIVAN_LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "LMSTUDIO_API_KEY",
    "LMSTUDIO_MODEL",
    "LMSTUDIO_BASE_URL",
)


def request_headers(request):
    return {key.lower(): value for key, value in request.header_items()}


def request_json(request):
    return json.loads(request.data.decode("utf-8"))


class FakeJSONResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.body


class ProviderTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self._saved_provider_env = {
            key: app.os.environ[key]
            for key in PROVIDER_ENV_KEYS
            if key in app.os.environ
        }
        for key in PROVIDER_ENV_KEYS:
            app.os.environ.pop(key, None)
        with app.LOCAL_MODEL_CACHE_LOCK:
            app.LOCAL_MODEL_CACHE.clear()

    def tearDown(self):
        for key in PROVIDER_ENV_KEYS:
            app.os.environ.pop(key, None)
        app.os.environ.update(self._saved_provider_env)
        with app.LOCAL_MODEL_CACHE_LOCK:
            app.LOCAL_MODEL_CACHE.clear()
        super().tearDown()

    def test_default_provider_uses_legacy_deepseek_key(self):
        app.set_setting("api_key", "legacy-deepseek-secret")

        request, config = app.provider_request({
            "messages": [{"role": "user", "content": "Merhaba"}],
            "max_tokens": 321,
            "stream": False,
        })

        self.assertEqual(app.selected_provider(), "deepseek")
        self.assertEqual(config["id"], "deepseek")
        self.assertEqual(config["endpoint"], app.API_URL)
        self.assertEqual(config["model"], app.MODEL)
        self.assertEqual(
            request_headers(request)["authorization"],
            "Bearer legacy-deepseek-secret",
        )
        body = request_json(request)
        self.assertEqual(body["model"], app.MODEL)
        self.assertEqual(body["max_tokens"], 321)
        self.assertNotIn("max_completion_tokens", body)

    def test_environment_overrides_stored_provider_key_and_model(self):
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("openai_api_key", "stored-openai-secret")
        app.set_setting("openai_model", "stored-openai-model")
        app.os.environ.update({
            "DIVAN_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "environment-openai-secret",
            "OPENAI_MODEL": "environment-openai-model",
        })

        config = app.provider_config()

        self.assertEqual(config["id"], "openai")
        self.assertEqual(config["secret"], "environment-openai-secret")
        self.assertEqual(config["model"], "environment-openai-model")

    def test_openai_request_uses_responses_api_shape_and_bearer_header(self):
        app.set_setting("llm_provider", "openai")
        app.set_setting("openai_api_key", "openai-secret")
        app.set_setting("openai_model", "gpt-test")
        messages = [
            {"role": "system", "content": "Sistem"},
            {"role": "developer", "content": "Geliştirici kuralı"},
            {"role": "user", "content": "Soru"},
            {"role": "assistant", "content": "Önceki yanıt"},
        ]

        request, config = app.provider_request({
            "messages": messages, "max_tokens": 456, "stream": True,
        })

        self.assertEqual(request.full_url,
                         "https://api.openai.com/v1/responses")
        self.assertEqual(config["protocol"], "openai_responses")
        headers = request_headers(request)
        self.assertEqual(headers["authorization"], "Bearer openai-secret")
        self.assertEqual(headers["accept"], "text/event-stream")
        body = request_json(request)
        self.assertEqual(body, {
            "model": "gpt-test",
            "input": [
                {"role": "user", "content": "Soru"},
                {"role": "assistant", "content": "Önceki yanıt"},
            ],
            "stream": True,
            "max_output_tokens": 456,
            "store": False,
            "instructions": "Sistem\n\nGeliştirici kuralı",
        })

    def test_openai_nonstream_response_collects_visible_text_and_refusal(self):
        config = {"id": "openai", "protocol": "openai_responses"}
        response = app.parse_provider_response({
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text",
                                 "text": "gizli akıl yürütme"}],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "İlk "},
                        {"type": "refusal", "refusal": "güvenli ret: "},
                        {"type": "output_text", "text": "yanıt"},
                    ],
                },
            ],
        }, config)

        self.assertEqual(response, "İlk güvenli ret: yanıt")

    def test_openai_responses_stream_deltas_and_completion(self):
        config = {"id": "openai", "protocol": "openai_responses"}

        self.assertEqual(
            app.provider_stream_delta(
                "response.output_text.delta",
                json.dumps({
                    "type": "response.output_text.delta",
                    "delta": "metin parçası",
                }),
                config,
            ),
            ("text", "metin parçası"),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "response.reasoning_summary_text.delta",
                json.dumps({
                    "type": "response.reasoning_summary_text.delta",
                    "delta": "gizli düşünme parçası",
                }),
                config,
            ),
            ("thinking", ""),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "response.completed",
                json.dumps({"type": "response.completed"}),
                config,
            ),
            ("done", ""),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "response.incomplete",
                json.dumps({"type": "response.incomplete"}),
                config,
            ),
            ("incomplete", "OpenAI yanıtı tamamlanmadan kesildi."),
        )

    def test_openai_insufficient_permission_is_not_reported_as_bad_key(self):
        permission_error = app.urllib.error.HTTPError(
            "https://api.openai.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "code": "insufficient_permissions",
                    "message": "Missing scopes: model.request",
                    "type": "invalid_request_error",
                },
            }).encode("utf-8")),
        )

        safe = app.provider_error(permission_error)

        self.assertEqual(safe.code, "insufficient_permissions")
        self.assertIn("gerekli izni yok", str(safe))
        self.assertNotIn("kabul edilmedi", str(safe))
        self.assertNotIn("model.request", str(safe))

        invalid_key_error = app.urllib.error.HTTPError(
            "https://api.openai.com/v1/responses",
            401,
            "Unauthorized",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "code": "invalid_api_key",
                    "message": "Incorrect API key provided",
                },
            }).encode("utf-8")),
        )
        invalid_key = app.provider_error(invalid_key_error)
        self.assertEqual(invalid_key.code, "auth_failed")
        self.assertIn("API anahtarı kabul edilmedi", str(invalid_key))

    def test_retry_after_is_bounded_and_invalid_model_400_is_specific(self):
        limited_error = app.urllib.error.HTTPError(
            "https://api.example.test/chat",
            429,
            "Too Many Requests",
            {"Retry-After": "120"},
            io.BytesIO(json.dumps({
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Rate limit reached",
                },
            }).encode("utf-8")),
        )
        limited = app.provider_error(limited_error)
        self.assertEqual(limited.code, "rate_limited")
        self.assertEqual(limited.retry_after, 120.0)
        self.assertEqual(
            app.bounded_retry_after("99999"),
            float(app.CHAT_MAX_RETRY_AFTER_SECONDS))
        self.assertIsNone(app.bounded_retry_after("-5"))

        missing_model_error = app.urllib.error.HTTPError(
            "http://127.0.0.1:1234/v1/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "type": "invalid_request_error",
                    "message": "The selected model is not loaded",
                },
            }).encode("utf-8")),
        )
        missing = app.provider_error(missing_model_error, local=True)
        self.assertEqual(missing.code, "model_not_found")
        self.assertIn("bulunamadı", str(missing))

        other_bad_request = app.urllib.error.HTTPError(
            "https://api.example.test/chat",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({
                "error": {"message": "messages must be an array"},
            }).encode("utf-8")),
        )
        invalid = app.provider_error(other_bad_request)
        self.assertEqual(invalid.code, "invalid_provider_request")
        self.assertFalse(app.chat_error_is_retryable(invalid.code))

    def test_anthropic_request_converts_messages_and_headers(self):
        app.set_setting("llm_provider", "anthropic")
        app.set_setting("anthropic_api_key", "anthropic-secret")
        app.set_setting("anthropic_model", "claude-test")
        messages = [
            {"role": "system", "content": "Birinci sistem"},
            {"role": "system", "content": "İkinci sistem"},
            {"role": "user", "content": "İlk"},
            {"role": "user", "content": "İkinci"},
            {"role": "assistant", "content": "Yanıt"},
        ]

        request, config = app.provider_request({
            "messages": messages, "max_tokens": 789, "stream": False,
        })

        self.assertEqual(request.full_url,
                         "https://api.anthropic.com/v1/messages")
        self.assertEqual(config["protocol"], "anthropic_messages")
        headers = request_headers(request)
        self.assertEqual(headers["x-api-key"], "anthropic-secret")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("authorization", headers)
        body = request_json(request)
        self.assertEqual(body["model"], "claude-test")
        self.assertEqual(body["max_tokens"], 789)
        self.assertFalse(body["stream"])
        self.assertEqual(body["system"], "Birinci sistem\n\nİkinci sistem")
        self.assertEqual(body["messages"], [
            {"role": "user", "content": "İlk\n\nİkinci"},
            {"role": "assistant", "content": "Yanıt"},
        ])

    def test_lmstudio_request_is_openai_compatible_and_local(self):
        app.set_setting("llm_provider", "lmstudio")
        app.set_setting("lmstudio_base_url", "http://localhost:1234")
        app.set_setting("lmstudio_model", "local-model")
        app.set_setting("lmstudio_api_key", "optional-local-secret")
        messages = [{"role": "user", "content": "Yerel soru"}]

        request, config = app.provider_request({
            "messages": messages, "max_tokens": 222, "stream": False,
        })

        self.assertTrue(config["local"])
        self.assertEqual(config["base_url"], "http://localhost:1234/v1")
        self.assertEqual(
            request.full_url,
            "http://localhost:1234/v1/chat/completions",
        )
        self.assertEqual(
            request_headers(request)["authorization"],
            "Bearer optional-local-secret",
        )
        self.assertEqual(request_json(request), {
            "model": "local-model",
            "messages": messages,
            "stream": False,
            "max_tokens": 222,
        })

    def test_deepseek_provider_specific_key_beats_legacy_key(self):
        app.set_setting("api_key", "legacy-secret")
        app.set_setting("deepseek_api_key", "new-deepseek-secret")
        app.set_setting("deepseek_model", "deepseek-test")

        request, config = app.provider_request({
            "messages": [{"role": "user", "content": "Soru"}],
            "max_tokens": 100,
        })

        self.assertEqual(config["model"], "deepseek-test")
        self.assertEqual(
            request_headers(request)["authorization"],
            "Bearer new-deepseek-secret",
        )

    def test_anthropic_conversion_response_and_stream_deltas(self):
        system, turns = app.anthropic_messages([
            {"role": "system", "content": "Kural"},
            {"role": "tool", "content": "yok say"},
            {"role": "user", "content": "A"},
            {"role": "user", "content": "B"},
            {"role": "assistant", "content": "C"},
            {"role": "assistant", "content": "D"},
        ])
        self.assertEqual(system, "Kural")
        self.assertEqual(turns, [
            {"role": "user", "content": "A\n\nB"},
            {"role": "assistant", "content": "C\n\nD"},
        ])

        config = {"protocol": "anthropic_messages"}
        response = app.parse_provider_response({
            "content": [
                {"type": "thinking", "thinking": "gizli"},
                {"type": "text", "text": "İlk "},
                {"type": "tool_use", "name": "ara"},
                {"type": "text", "text": "yanıt"},
            ],
        }, config)
        self.assertEqual(response, "İlk yanıt")

        self.assertEqual(
            app.provider_stream_delta(
                "content_block_delta",
                json.dumps({
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "parça"},
                }),
                config,
            ),
            ("text", "parça"),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "content_block_delta",
                json.dumps({
                    "type": "content_block_delta",
                    "delta": {
                        "type": "thinking_delta",
                        "thinking": "gizli düşünce",
                    },
                }),
                config,
            ),
            ("thinking", ""),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "message_stop",
                json.dumps({"type": "message_stop"}),
                config,
            ),
            ("done", ""),
        )

    def test_stream_completion_limits_are_not_accepted_as_finished_answers(self):
        chat_config = {"protocol": "openai_chat"}
        # DeepSeek, LM Studio ve başka OpenAI-uyumlu sunucular normal ara
        # parçalarda finish_reason alanını JSON null olarak yollar. Bu bir
        # bitiş nedeni veya hata değildir.
        self.assertEqual(
            app.provider_stream_delta(
                "",
                json.dumps({
                    "choices": [{
                        "delta": {"content": "normal parça"},
                        "finish_reason": None,
                    }],
                }),
                chat_config,
            ),
            ("text", "normal parça"),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "",
                json.dumps({
                    "choices": [{
                        "delta": {"reasoning_content": "gizli düşünme"},
                        "finish_reason": None,
                    }],
                }),
                chat_config,
            ),
            ("thinking", ""),
        )
        self.assertEqual(
            app.provider_completion_limit_reason(
                {
                    "choices": [{
                        "message": {"content": "tam"},
                        "finish_reason": None,
                    }],
                },
                chat_config,
            ),
            "",
        )
        self.assertEqual(
            app.provider_stream_delta(
                "",
                json.dumps({
                    "choices": [{"delta": {}, "finish_reason": "length"}],
                }),
                chat_config,
            ),
            (
                "incomplete",
                "Yanıt seçili çıktı sınırına ulaştığı için yarım kaldı.",
            ),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "",
                json.dumps({
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                }),
                chat_config,
            ),
            ("done", ""),
        )
        self.assertEqual(
            app.provider_stream_delta(
                "message_delta",
                json.dumps({
                    "type": "message_delta",
                    "delta": {"stop_reason": "max_tokens"},
                }),
                {"protocol": "anthropic_messages"},
            ),
            (
                "incomplete",
                "Yanıt seçili çıktı sınırına ulaştığı için yarım kaldı.",
            ),
        )

    def test_nonstream_completion_limit_raises_instead_of_saving_partial(self):
        config = {"id": "lmstudio", "protocol": "openai_chat"}
        response = FakeJSONResponse({
            "choices": [{
                "message": {"content": "Yarım yanıt"},
                "finish_reason": "length",
            }],
        })
        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), config)), \
                mock.patch.object(
                    app, "open_provider_url",
                    return_value=response):
            with self.assertRaises(app.ProviderError) as caught:
                app.ds_complete([
                    {"role": "user", "content": "Yanıtla"},
                ])
        self.assertEqual(
            caught.exception.code, "provider_output_truncated")

    def test_local_base_url_accepts_only_loopback_http(self):
        accepted = {
            "http://localhost:1234": "http://localhost:1234/v1",
            "http://127.0.0.1:11434/v1/": "http://127.0.0.1:11434/v1",
            "http://[::1]:8080/v1": "http://[::1]:8080/v1",
        }
        for raw, normalized in accepted.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    app.normalize_local_base_url(raw), normalized)

        rejected = (
            "https://localhost:1234/v1",
            "http://example.com:1234/v1",
            "http://localhost.evil:1234/v1",
            "http://0.0.0.0:1234/v1",
            "http://user:pass@localhost:1234/v1",
            "http://localhost:1234/v1?token=secret",
            "http://localhost:1234/v1#fragment",
            "http://localhost:1234/api/v1",
            "file:///tmp/model",
        )
        for raw in rejected:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    app.normalize_local_base_url(raw)

    def test_local_model_discovery_is_bounded_filtered_and_authorized(self):
        payload = {
            "data": [
                {"id": "model-a"},
                {"id": "model-a"},
                {"id": "model-b:latest"},
                {"id": "qwen3-embedding-0.6b"},
                {"id": "bge-reranker-v2"},
                {"id": "cross-encoder/ms-marco"},
                {"id": "whisper-large-v3"},
                {"id": "boşluklu model"},
                {"not_id": "ignored"},
                "ignored",
            ],
        }
        with mock.patch.object(
                app, "open_provider_url",
                return_value=FakeJSONResponse(payload)) as open_url:
            models = app.discover_local_models(
                "http://localhost:1234", "local-secret", use_cache=False)

        self.assertEqual(models, ["model-a", "model-b:latest"])
        request, config = open_url.call_args.args[:2]
        self.assertEqual(request.full_url,
                         "http://localhost:1234/v1/models")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request_headers(request)["authorization"],
            "Bearer local-secret",
        )
        self.assertTrue(config["local"])
        self.assertEqual(open_url.call_args.kwargs["timeout"], 2.5)

    def test_provider_models_endpoint_returns_mocked_local_models(self):
        with mock.patch.object(
                app, "discover_local_models",
                return_value=["local-a", "local-b"]) as discover:
            status, body, _ = self.request(
                "POST", "/api/provider/models",
                {
                    "base_url": "http://127.0.0.1:1234",
                    "lmstudio_api_key": "scan-secret",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["models"], ["local-a", "local-b"])
        self.assertEqual(body["base_url"], "http://127.0.0.1:1234/v1")
        discover.assert_called_once_with(
            "http://127.0.0.1:1234/v1",
            "scan-secret",
            use_cache=False,
        )

    def test_settings_get_reveals_only_key_presence(self):
        secrets = {
            "api_key": "legacy-secret-value",
            "deepseek_api_key": "deepseek-secret-value",
            "openai_api_key": "openai-secret-value",
            "anthropic_api_key": "anthropic-secret-value",
            "gemini_api_key": "gemini-secret-value",
            "lmstudio_api_key": "local-secret-value",
            "ollama_api_key": "ollama-secret-value",
            "pin_hash": "pin-secret-value",
        }
        for key, value in secrets.items():
            app.set_setting(key, value)

        status, body, _ = self.request("GET", "/api/settings")

        self.assertEqual(status, 200)
        rendered = json.dumps(body, ensure_ascii=False)
        for value in secrets.values():
            self.assertNotIn(value, rendered)
        self.assertTrue(body["api_key_set"])
        for provider in app.PROVIDERS:
            self.assertTrue(body["providers"][provider]["key_set"])
            self.assertNotIn("secret", body["providers"][provider])
            self.assertNotIn("api_key", body["providers"][provider])

    def test_export_excludes_every_provider_secret(self):
        pin = "export-pin-secret"
        secrets = {
            "api_key": "export-legacy-secret",
            "deepseek_api_key": "export-deepseek-secret",
            "openai_api_key": "export-openai-secret",
            "anthropic_api_key": "export-anthropic-secret",
            "gemini_api_key": "export-gemini-secret",
            "lmstudio_api_key": "export-local-secret",
            "pin_hash": app.pin_hash(pin),
        }
        for key, value in secrets.items():
            app.set_setting(key, value)
        app.set_setting("llm_provider", "anthropic")
        app.set_setting("anthropic_model", "claude-test")
        cookie = self.unlock_cookie(pin)

        status, body, _ = self.request(
            "GET", "/api/export-json", headers={"Cookie": cookie})

        self.assertEqual(status, 200)
        rendered = json.dumps(body, ensure_ascii=False)
        for value in secrets.values():
            self.assertNotIn(value, rendered)
        setting_keys = {
            row["key"] for row in body["data"]["settings"]
        }
        self.assertTrue(app.SECRET_SETTING_KEYS.isdisjoint(setting_keys))
        self.assertIn("llm_provider", setting_keys)
        self.assertIn("anthropic_model", setting_keys)

    def test_invalid_provider_settings_are_rejected_atomically(self):
        app.set_setting("llm_provider", "deepseek")
        app.set_setting("openai_model", "old-openai-model")
        app.set_setting("openai_api_key", "old-openai-secret")

        status, body, _ = self.request(
            "POST", "/api/settings",
            {
                "provider": "openai",
                "openai_model": "new-openai-model",
                "openai_api_key": "new-openai-secret",
                "lmstudio_model": "new-local-model",
                "lmstudio_base_url": "http://remote.example/v1",
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("yalnız bu bilgisayarı", body["error"])
        self.assertEqual(app.get_setting("llm_provider"), "deepseek")
        self.assertEqual(app.get_setting("openai_model"), "old-openai-model")
        self.assertEqual(app.get_setting("openai_api_key"),
                         "old-openai-secret")
        self.assertEqual(app.get_setting("lmstudio_model"), "")
        self.assertEqual(app.get_setting("lmstudio_base_url"), "")
