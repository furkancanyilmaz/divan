import json
from unittest import mock

from support import HTTPTestCase, app


class NativeBootstrapContractTests(HTTPTestCase):

    def test_v1_bootstrap_has_stable_shape_and_reuses_public_catalogs(self):
        app.set_setting("privacy_seen", "1")
        app.set_setting("retention_days", "30")
        app.set_setting("simple_mode", "1")
        app.set_setting("context_window_tokens", "65536")
        secret = "native-bootstrap-secret-must-not-leak"
        environment = {
            "DIVAN_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": secret,
            "OPENAI_MODEL": "gpt-native-contract",
        }

        with mock.patch.dict(app.os.environ, environment):
            status, payload, headers = self.request(
                "GET", "/api/v1/bootstrap")
            therapist_status, therapists, _ = self.request(
                "GET", "/api/therapists")
            philosopher_status, philosophers, _ = self.request(
                "GET", "/api/philosophers")
            provider_id, public_providers = app.public_provider_settings()

        self.assertEqual(status, 200, payload)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(set(payload), {
            "api_contract_version", "app_version", "capabilities",
            "provider", "therapists", "philosophers", "settings",
        })
        self.assertEqual(
            payload["api_contract_version"], app.API_CONTRACT_VERSION)
        self.assertEqual(payload["app_version"], app.VERSION)

        self.assertEqual(therapist_status, 200)
        self.assertEqual(philosopher_status, 200)
        self.assertEqual(payload["therapists"], therapists)
        self.assertEqual(payload["philosophers"], philosophers)
        self.assertTrue(therapists)
        self.assertTrue(philosophers)
        for persona in therapists + philosophers:
            self.assertNotIn("persona", persona)
            self.assertIn("id", persona)
            self.assertIn("kind", persona)
            self.assertIn("modes", persona)
            self.assertIn("portrait", persona)

        expected_provider = dict(public_providers[provider_id])
        expected_provider["id"] = provider_id
        self.assertEqual(payload["provider"], expected_provider)
        self.assertEqual(payload["provider"]["id"], "openai")
        self.assertEqual(
            payload["provider"]["model"], "gpt-native-contract")
        self.assertTrue(payload["provider"]["key_set"])
        self.assertNotIn("secret", payload["provider"])
        self.assertNotIn("endpoint", payload["provider"])
        self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))

        self.assertEqual(set(payload["settings"]), {
            "context_window_tokens", "context_window_options",
            "privacy_seen", "pin_set", "retention_days", "simple_mode",
            "credential_storage",
        })
        self.assertEqual(payload["settings"]["context_window_tokens"], 65536)
        self.assertEqual(
            payload["settings"]["context_window_options"],
            list(app.CONTEXT_WINDOW_TOKEN_OPTIONS))
        self.assertTrue(payload["settings"]["privacy_seen"])
        self.assertFalse(payload["settings"]["pin_set"])
        self.assertEqual(payload["settings"]["retention_days"], 30)
        self.assertTrue(payload["settings"]["simple_mode"])

    def test_capabilities_are_versioned_from_backend_protocol_constants(self):
        status, payload, _ = self.request("GET", "/api/v1/bootstrap")

        self.assertEqual(status, 200, payload)
        capabilities = payload["capabilities"]
        self.assertEqual(set(capabilities), {
            "app_lock", "backup_restore", "background_chat", "chair_work",
            "conversation_batch_actions", "conversation_message_paging",
            "device_sync", "imagery_work", "living_map",
            "provider_connection_test", "session_lifecycle", "therapy_map",
        })
        self.assertEqual(capabilities["chair_work"], {
            "protocol_version": app.CHAIR_PROTOCOL_VERSION,
        })
        self.assertEqual(capabilities["imagery_work"], {
            "protocol_version": app.IMAGERY_PROTOCOL_VERSION,
        })
        self.assertEqual(capabilities["living_map"], {
            "version": app.LIVING_MAP_VERSION,
        })
        self.assertEqual(capabilities["therapy_map"], {
            "version": app.THERAPY_MAP_VERSION,
        })
        self.assertEqual(capabilities["device_sync"], {
            "batch_version": app.sync_engine.BATCH_VERSION,
        })
        self.assertEqual(capabilities["conversation_message_paging"], {
            "recommended_limit":
                app.CONVERSATION_MESSAGE_PAGE_RECOMMENDED_LIMIT,
            "max_limit": app.CONVERSATION_MESSAGE_PAGE_MAX,
        })

    def test_bootstrap_matches_existing_app_lock_exempt_public_information(self):
        app.set_setting("pin_hash", app.pin_hash("2468"))

        status, payload, _ = self.request("GET", "/api/v1/bootstrap")
        protected_status, protected, _ = self.request(
            "GET", "/api/conversations")

        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["settings"]["pin_set"])
        self.assertNotIn("conversations", payload)
        self.assertNotIn("profile", payload)
        self.assertEqual(protected_status, 423)
        self.assertIn("kilitli", protected["error"])

    def test_bootstrap_keeps_embedded_session_and_local_host_protection(self):
        app.EMBEDDED_SESSION_TOKEN = "native-bootstrap-session-token"

        status, body, _ = self.request("GET", "/api/v1/bootstrap")
        self.assertEqual(status, 403, body)

        cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        status, body, _ = self.request(
            "GET", "/api/v1/bootstrap", headers={"Cookie": cookie})
        self.assertEqual(status, 200, body)

        status, body, _ = self.request(
            "GET", "/api/v1/bootstrap",
            headers={"Cookie": cookie, "Host": "example.com"})
        self.assertEqual(status, 403, body)
        self.assertIn("yerel", body["error"])

    def test_bootstrap_respects_maintenance_and_unknown_contract_versions(self):
        app.MAINTENANCE_ACTIVE.set()
        try:
            status, body, _ = self.request("GET", "/api/v1/bootstrap")
        finally:
            app.MAINTENANCE_ACTIVE.clear()

        self.assertEqual(status, 503, body)
        self.assertIn("bakım", body["error"])

        status, body, _ = self.request("GET", "/api/v2/bootstrap")
        self.assertEqual(status, 404, body)
        self.assertEqual(body, {"error": "yok"})


if __name__ == "__main__":
    import unittest
    unittest.main()
