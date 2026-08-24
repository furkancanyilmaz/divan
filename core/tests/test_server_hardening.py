import base64
import json
import sqlite3
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app

import sync_engine as sync


class FakeJSONResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.body


class ServerHardeningTests(HTTPTestCase):

    def test_external_credential_survives_logical_restart_as_presence_only(self):
        durable_vault = {}
        secret = "restart-secret-must-never-cross-http"

        def reader(key):
            return durable_vault.get(key, "")

        def writer(key, value):
            if value:
                durable_vault[key] = value
            else:
                durable_vault.pop(key, None)

        app.configure_secret_store(
            reader, writer, migrate=False, kind="test-keychain")
        status, saved, _ = self.request(
            "POST", "/api/settings", {
                "provider": "openai",
                "openai_api_key": secret,
            })

        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["credentials"], {"openai_api_key": True})
        self.assertEqual(saved["credential_storage"], "test-keychain")
        self.assertNotIn(secret, json.dumps(saved, ensure_ascii=False))
        self.assertIsNone(self.row(
            "SELECT value FROM settings WHERE key='openai_api_key'"))

        # Reinstall fresh callback objects, as a new server process would,
        # while leaving the durable platform store intact.
        app.configure_secret_store(
            lambda key: durable_vault.get(key, ""),
            lambda key, value: (
                durable_vault.__setitem__(key, value)
                if value else durable_vault.pop(key, None)),
            migrate=False,
            kind="test-keychain",
        )
        status, restarted, _ = self.request("GET", "/api/settings")

        self.assertEqual(status, 200, restarted)
        self.assertTrue(restarted["providers"]["openai"]["key_set"])
        self.assertEqual(restarted["credential_storage"], "test-keychain")
        self.assertNotIn(secret, json.dumps(restarted, ensure_ascii=False))

    def test_settings_reports_keychain_failure_without_partial_provider_switch(self):
        old_secret = "existing-secret-must-stay-private"
        vault = {"openai_api_key": old_secret}

        def writer(key, value):
            if value == "new-secret-must-stay-private":
                raise RuntimeError("simulated locked keychain")
            vault[key] = value

        app.configure_secret_store(
            lambda key: vault.get(key, ""), writer,
            migrate=False, kind="test-keychain")
        app.set_setting("llm_provider", "deepseek")

        status, body, _ = self.request(
            "POST", "/api/settings", {
                "provider": "openai",
                "openai_api_key": "new-secret-must-stay-private",
            })

        self.assertEqual(status, 503, body)
        self.assertEqual(body["error_code"],
                         "credential_store_unavailable")
        self.assertTrue(body["retryable"])
        serialized = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(old_secret, serialized)
        self.assertNotIn("new-secret-must-stay-private", serialized)
        self.assertEqual(app.get_setting("llm_provider"), "deepseek")
        self.assertEqual(app.get_setting("openai_api_key"), old_secret)

    def test_settings_rolls_back_a_secret_changed_before_readback_failure(self):
        old_secret = "old-value-never-returned"
        new_secret = "new-value-never-returned"
        vault = {"anthropic_api_key": old_secret}
        corrupt_once = {"enabled": True}

        def writer(key, value):
            if value == new_secret and corrupt_once["enabled"]:
                corrupt_once["enabled"] = False
                vault[key] = "corrupted-write-never-returned"
            else:
                vault[key] = value

        app.configure_secret_store(
            lambda key: vault.get(key, ""), writer,
            migrate=False, kind="test-keychain")
        app.set_setting("llm_provider", "deepseek")

        status, body, _ = self.request(
            "POST", "/api/settings", {
                "provider": "anthropic",
                "anthropic_api_key": new_secret,
            })

        self.assertEqual(status, 503, body)
        rendered = json.dumps(body, ensure_ascii=False)
        self.assertNotIn(old_secret, rendered)
        self.assertNotIn(new_secret, rendered)
        self.assertNotIn("corrupted-write-never-returned", rendered)
        self.assertEqual(vault["anthropic_api_key"], old_secret)
        self.assertEqual(app.get_setting("llm_provider"), "deepseek")

    def test_provider_test_success_uses_transient_secret_without_saving_it(self):
        secret = "provider-test-transient-secret"
        seen = {}

        def open_test_request(request, config, timeout):
            seen["authorization"] = request.get_header("Authorization")
            seen["provider"] = config["id"]
            seen["model"] = config["model"]
            seen["timeout"] = timeout
            return FakeJSONResponse({
                "choices": [{
                    "message": {"content": "TAMAM"},
                    "finish_reason": "stop",
                }],
            })

        with mock.patch.object(
                app, "open_provider_url", side_effect=open_test_request):
            status, body, _ = self.request(
                "POST", "/api/provider-test", {
                    "provider": "deepseek",
                    "model": "deepseek-test-model",
                    "api_key": secret,
                })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["provider"], "deepseek")
        self.assertEqual(body["model"], "deepseek-test-model")
        self.assertIsInstance(body["latency_ms"], int)
        self.assertEqual(seen["authorization"], "Bearer " + secret)
        self.assertEqual(seen["provider"], "deepseek")
        self.assertEqual(seen["model"], "deepseek-test-model")
        self.assertEqual(seen["timeout"], app.PROVIDER_TEST_TIMEOUT_SECONDS)
        self.assertEqual(app.get_setting("deepseek_api_key"), "")
        self.assertNotIn(secret, json.dumps(body, ensure_ascii=False))

    def test_provider_test_maps_expected_failures_to_safe_http_json(self):
        status, missing, _ = self.request(
            "POST", "/api/provider-test", {
                "provider": "openai", "model": "gpt-test",
            })
        self.assertEqual(status, 400, missing)
        self.assertEqual(missing["error_code"], "missing_api_key")

        cases = (
            ("auth_failed", 401, None),
            ("insufficient_permissions", 403, None),
            ("rate_limited", 429, 9),
            ("provider_timeout", 504, None),
            ("model_not_found", 502, None),
            ("quota_exhausted", 502, None),
        )
        for code, expected_status, retry_after in cases:
            with self.subTest(code=code):
                safe_message = "Güvenli sağlayıcı açıklaması: " + code
                error = app.ProviderError(
                    code, safe_message, retry_after=retry_after)
                with mock.patch.object(
                        app, "test_provider_connection",
                        side_effect=error):
                    status, body, headers = self.request(
                        "POST", "/api/provider-test", {
                            "provider": "deepseek",
                            "model": "deepseek-test-model",
                            "api_key": "response-body-must-not-contain-me",
                        })
                self.assertEqual(status, expected_status, body)
                self.assertEqual(body, {
                    "ok": False,
                    "error": safe_message,
                    "error_code": code,
                })
                self.assertNotIn(
                    "response-body-must-not-contain-me",
                    json.dumps(body, ensure_ascii=False))
                if retry_after:
                    self.assertEqual(headers.get("Retry-After"), "9")
                else:
                    self.assertNotIn("Retry-After", headers)

    def test_unexpected_handler_exception_returns_safe_json_with_error_id(self):
        sentinel = "UNEXPECTED-INTERNAL-DETAIL-MUST-STAY-LOCAL"
        with mock.patch.object(
                app.Handler, "api_provider_test",
                side_effect=RuntimeError(sentinel)), \
                mock.patch("builtins.print"):
            status, body, headers = self.request(
                "POST", "/api/provider-test", {
                    "provider": "deepseek",
                    "model": "deepseek-test-model",
                    "api_key": "temporary-key",
                })

        self.assertEqual(status, 500, body)
        self.assertEqual(body["error_code"], "internal_error")
        self.assertFalse(body["retryable"])
        self.assertRegex(body["error_id"], r"^[0-9a-f]{10}$")
        self.assertIn(body["error_id"], body["error"])
        self.assertNotIn(sentinel, json.dumps(body, ensure_ascii=False))
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(
            int(headers["Content-Length"]),
            len(json.dumps(body, ensure_ascii=False).encode("utf-8")))
        self.assertNotIn("Connection", headers)

        # A handler failure must not poison subsequent application requests.
        follow_status, follow_body, _ = self.request("GET", "/api/settings")
        self.assertEqual(follow_status, 200, follow_body)

    def test_http_conversation_delete_redacts_sync_changes_and_conflicts(self):
        sentinel = "DELETE-SYNC-SENSITIVE-f851c"
        conv_id = self.conversation(title=sentinel + "-title")
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", sentinel + "-message", app.now()),
            ).lastrowid
            sync.initialize_sync(connection, "hardening-device-a")
            records = connection.execute(
                "SELECT record_type,public_id FROM sync_records "
                "WHERE (record_type='conversation' AND local_id=?) OR "
                "(record_type='message' AND local_id=?) "
                "ORDER BY record_type",
                (conv_id, message_id),
            ).fetchall()
            self.assertEqual(len(records), 2)
            for index, record in enumerate(records):
                private_json = json.dumps({
                    "content": sentinel + "-history-" + str(index),
                })
                connection.execute(
                    "UPDATE sync_changes SET payload_json=? "
                    "WHERE record_type=? AND public_id=?",
                    (private_json, record["record_type"],
                     record["public_id"]),
                )
                connection.execute(
                    "INSERT INTO sync_conflicts("
                    "record_type,public_id,reason,local_json,incoming_json,"
                    "incoming_event_id,created_at,status) "
                    "VALUES(?,?,?,?,?,?,?,'open')",
                    (
                        record["record_type"], record["public_id"],
                        "concurrent_update", private_json,
                        json.dumps({"content": sentinel + "-remote"}),
                        "hardening-conflict-{}".format(index), app.now(),
                    ),
                )

        status, body, _ = self.request(
            "POST", "/api/delete", {"id": conv_id})

        self.assertEqual(status, 200, body)
        self.assertIsNone(self.conversation_row(conv_id))
        with app.db() as connection:
            changes = connection.execute(
                "SELECT payload_json FROM sync_changes").fetchall()
            conflicts = connection.execute(
                "SELECT local_json,incoming_json FROM sync_conflicts"
            ).fetchall()
            tombstones = connection.execute(
                "SELECT record_type,local_id,deleted_at FROM sync_records "
                "WHERE record_type IN ('conversation','message')"
            ).fetchall()
        serialized = json.dumps(
            [list(row) for row in changes + conflicts], ensure_ascii=False)
        self.assertNotIn(sentinel, serialized)
        self.assertTrue(changes)
        self.assertTrue(all(row["payload_json"] is None for row in changes))
        self.assertEqual(conflicts, [])
        self.assertEqual(len(tombstones), 2)
        self.assertTrue(all(
            row["local_id"] is None and row["deleted_at"]
            for row in tombstones))

    def test_delete_all_clears_sync_settings_external_secrets_and_pin_sessions(self):
        vault = {}

        def read_secret(key):
            return vault.get(key, "")

        def write_secret(key, value):
            vault[key] = value

        app.configure_secret_store(
            read_secret, write_secret, migrate=False, kind="test-vault")
        for key in app.API_SECRET_SETTING_KEYS:
            app.set_setting(key, "hardening-secret-" + key)
        app.set_setting("llm_provider", "openai")
        app.set_setting("openai_model", "gpt-test")
        pin = "246810"
        app.set_setting("pin_hash", app.pin_hash(pin))
        cookie = self.unlock_cookie(pin)
        self.assertTrue(app.APP_UNLOCK_SESSIONS)
        app.APP_UNLOCK_FAILURES["127.0.0.1"] = {
            "count": 1, "first": 1.0, "blocked_until": 0.0,
        }

        conv_id = self.conversation(title="Eşitleme durumu")
        with app.db() as connection:
            sync.initialize_sync(connection, "hardening-device-a")
            app.sync_service._status_schema(connection)
        app.sync_service.status()
        with app.db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO sync_peer_cursors("
                "peer_device_id,remote_cursor,acknowledged_local_cursor,"
                "updated_at) VALUES(?,?,?,?)",
                ("hardening-peer", 7, 4, app.now()),
            )
            connection.execute(
                "UPDATE sync_local_status SET last_sync_at=?,"
                "last_peer_device_id=?,last_peer_name=?,last_summary_json=? "
                "WHERE singleton=1",
                (app.now(), "hardening-peer", "Test cihazı", '{"sent":1}'),
            )
            before = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in (
                    "sync_records", "sync_changes", "sync_seen_versions",
                    "sync_peer_cursors")
            }
        self.assertTrue(all(value > 0 for value in before.values()))

        status, body, headers = self.request(
            "POST", "/api/delete-all",
            {"confirm": "TÜM VERİLERİ SİL"},
            headers={"Cookie": cookie})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertIn("Max-Age=0", headers.get("Set-Cookie", ""))
        self.assertFalse(app.APP_UNLOCK_SESSIONS)
        self.assertFalse(app.APP_UNLOCK_FAILURES)
        self.assertEqual(app.get_setting("pin_hash"), "")
        self.assertEqual(self.rows("SELECT * FROM settings"), [])
        for key in app.API_SECRET_SETTING_KEYS:
            self.assertEqual(vault.get(key), "", key)
            self.assertEqual(app.get_setting(key), "", key)
        for table in (
                "sync_conflicts", "sync_changes", "sync_seen_versions",
                "sync_records", "sync_peer_cursors"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM " + table)["n"], 0)
        status_row = self.row(
            "SELECT * FROM sync_local_status WHERE singleton=1")
        self.assertIsNotNone(status_row)
        self.assertIsNone(status_row["last_sync_at"])
        self.assertIsNone(status_row["last_peer_device_id"])
        self.assertIsNone(status_row["last_peer_name"])
        self.assertEqual(status_row["last_summary_json"], "{}")
        self.assertIsNone(self.conversation_row(conv_id))

        # The PIN is gone, so a fresh request no longer depends on the expired
        # pre-delete unlock cookie.
        fresh_status, fresh_body, _ = self.request(
            "GET", "/api/conversations")
        self.assertEqual(fresh_status, 200, fresh_body)
        self.assertEqual(fresh_body, [])

    def test_http_restore_resets_sync_runtime_state(self):
        conv_id = self.conversation(title="Yedekteki başlık")
        incoming = str(Path(self._tmp.name) / "hardening-restore.db")
        app.create_sqlite_snapshot(incoming)
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET title=? WHERE id=?",
                ("Canlı başlık", conv_id),
            )

        reset = app.sync_service.reset_runtime_state
        with mock.patch.object(
                app.sync_service, "reset_runtime_state", wraps=reset) as call:
            status, body, _ = self.request(
                "POST", "/api/restore", {
                    "database": base64.b64encode(
                        Path(incoming).read_bytes()).decode("ascii"),
                })

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(call.call_count, 1)
        self.assertEqual(
            self.conversation_row(conv_id)["title"], "Yedekteki başlık")

    def test_end_rolls_back_then_commits_closing_message_and_job_together(self):
        conv_id = self.conversation(title="Atomik kapanış")
        with mock.patch.object(
                app, "create_job",
                side_effect=sqlite3.OperationalError(
                    "forced hardening rollback")), \
                mock.patch.object(app, "enqueue_job") as enqueue, \
                mock.patch("builtins.print"):
            failed_status, failed, _ = self.request(
                "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(failed_status, 500, failed)
        self.assertEqual(failed["error_code"], "internal_error")
        enqueue.assert_not_called()
        self.assertEqual(self.conversation_row(conv_id)["ended"], 0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (conv_id,))["n"], 0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
                (conv_id,))["n"], 0)
        for table in (
                "session_map_runs", "session_map_targets",
                "session_map_events"):
            self.assertEqual(
                self.row(
                    "SELECT COUNT(*) AS n FROM {} WHERE conv=?".format(
                        table), (conv_id,))["n"], 0)

        status, body, _ = self.request(
            "POST", "/api/end", {"conv_id": conv_id})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["processing"])
        self.assertTrue(body["closing"])
        self.assertEqual(self.conversation_row(conv_id)["ended"], 1)
        closing_rows = self.rows(
            "SELECT * FROM messages WHERE conv=? AND role='assistant'",
            (conv_id,))
        self.assertEqual(len(closing_rows), 1)
        self.assertEqual(closing_rows[0]["content"], body["closing"])
        self.assertEqual(closing_rows[0]["created"], body["closing_created"])
        job = self.row("SELECT * FROM jobs WHERE id=?", (body["job_id"],))
        self.assertIsNotNone(job)
        self.assertEqual(job["conv"], conv_id)
        self.assertEqual(job["kind"], "session_postprocess")
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.queued_job_id(), body["job_id"])


if __name__ == "__main__":
    import unittest
    unittest.main()
