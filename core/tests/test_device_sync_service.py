import copy
import json
from pathlib import Path
from unittest import mock

from support import DatabaseTestCase, HTTPTestCase, PROJECT_DIR, app

import sync_engine
import sync_service


REMOTE_DEVICE = "b" * 32


class DeviceSyncServiceTests(DatabaseTestCase):

    def test_external_identity_store_is_device_bound_and_avoids_sidecar(self):
        values = {}
        sync_service.configure_identity_store(
            lambda key: values.get(key, ""),
            lambda key, value: values.__setitem__(key, value),
        )
        try:
            first = sync_service._device_id()
            second = sync_service._device_id()
        finally:
            sync_service.configure_identity_store(None, None)

        self.assertEqual(first, second)
        self.assertEqual(values["device_sync_installation_id"], first)
        self.assertFalse(Path(app.DB_PATH + ".device-id").exists())

    def test_identity_store_callbacks_must_be_paired(self):
        with self.assertRaises(TypeError):
            sync_service.configure_identity_store(lambda key: "", None)

    def _remote_batch(self):
        client_path = app.DB_PATH
        remote_path = str(Path(self._tmp.name) / "remote.db")
        app.DB_PATH = remote_path
        try:
            app.init_db()
            with app.db() as connection:
                conv_id = connection.execute(
                    "INSERT INTO conversations("
                    "mode,therapist,title,created,updated,ended) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        "terapi", "ferenczi", "Telefondaki görüşme",
                        "2026-07-30 12:00", "2026-07-30 12:00", 1,
                    ),
                ).lastrowid
                connection.execute(
                    "INSERT INTO messages("
                    "conv,role,content,created) VALUES(?,?,?,?)",
                    (
                        conv_id, "user", "Telefondaki mesaj",
                        "2026-07-30 12:01",
                    ),
                )
                sync_engine.refresh_local_changes(
                    connection, REMOTE_DEVICE)
                return sync_engine.export_change_batch(
                    connection, REMOTE_DEVICE, limit=64)
        finally:
            app.DB_PATH = client_path
            app.init_db()

    def test_mocked_join_exchanges_allowlisted_records_both_directions(self):
        local_id = self.conversation(
            title="Bilgisayardaki görüşme", ended=1)
        self.messages(local_id, 1, prefix="bilgisayar")
        remote_batch = self._remote_batch()
        sent_batches = []

        class FakeClient:
            def run_batches(
                    self, next_batch, apply_result, *, max_rounds):
                items, done = next_batch(None)
                sent_batches.extend(items)
                assert done
                apply_result({
                    "batch": remote_batch,
                    "more": False,
                    "apply": {"records": len(items[0]["records"]),
                              "conflicts": 0},
                })

        invitation = {
            "v": 1,
            "scheme": "https",
            "host": "192.168.1.10",
            "port": 44321,
            "session_id": "unused",
            "pairing_secret": "unused",
            "cert_sha256": "a" * 64,
            "desktop_device_id": REMOTE_DEVICE,
            "expires_at": 4102444800,
            "path": "/v1",
        }
        with mock.patch.object(
                sync_service.transport, "parse_invitation",
                return_value=invitation), mock.patch.object(
                sync_service.transport, "pair_with_invitation",
                return_value=(FakeClient(), {"ok": True})):
            result = sync_service.join(
                "scanned-code", device_name="Android telefon",
                platform_name="android")

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["summary"]["sent"], 2)
        self.assertEqual(
            result["summary"]["received"],
            len(remote_batch["records"]),
        )
        with app.db() as connection:
            titles = {
                row[0] for row in connection.execute(
                    "SELECT title FROM conversations")}
            contents = {
                row[0] for row in connection.execute(
                    "SELECT content FROM messages")}
            secret_tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('settings','jobs','chat_requests')")}
        self.assertIn("Bilgisayardaki görüşme", titles)
        self.assertIn("Telefondaki görüşme", titles)
        self.assertIn("Telefondaki mesaj", contents)
        self.assertEqual(
            secret_tables, {"settings", "jobs", "chat_requests"})
        wire = json.dumps(sent_batches, ensure_ascii=False)
        self.assertNotIn("api_key", wire)
        self.assertNotIn("pin_hash", wire)

    def test_second_qr_sync_sends_zero_unchanged_records_after_ack(self):
        self.conversation(title="Yalnız bir kez gönder")
        sent_counts = []

        class AckingClient:
            def run_batches(
                    self, next_batch, apply_result, *, max_rounds):
                items, done = next_batch(None)
                self.assert_batch(items, done)
                local_batch = items[0]
                sent_counts.append(len(local_batch["records"]))
                apply_result({
                    "batch": {
                        "kind": sync_engine.BATCH_KIND,
                        "version": sync_engine.BATCH_VERSION,
                        "sender_device_id": REMOTE_DEVICE,
                        "after_cursor": 0,
                        "cursor": 0,
                        "ack_cursor": local_batch["cursor"],
                        "has_more": False,
                        "records": [],
                    },
                    "more": False,
                    "apply": {
                        "records": len(local_batch["records"]),
                        "conflicts": 0,
                    },
                })

            @staticmethod
            def assert_batch(items, done):
                assert len(items) == 1
                assert done is True

            def close(self):
                pass

        invitation = {
            "v": 1,
            "scheme": "https",
            "host": "192.168.1.10",
            "port": 44321,
            "session_id": "unused",
            "pairing_secret": "unused",
            "cert_sha256": "a" * 64,
            "desktop_device_id": REMOTE_DEVICE,
            "expires_at": 4102444800,
            "path": "/v1",
        }
        with mock.patch.object(
                sync_service.transport, "parse_invitation",
                return_value=invitation), mock.patch.object(
                sync_service.transport, "pair_with_invitation",
                side_effect=lambda *args, **kwargs: (
                    AckingClient(), {"ok": True})):
            first = sync_service.join("first-code")
            second = sync_service.join("second-code")

        self.assertGreater(first["summary"]["sent"], 0)
        self.assertEqual(second["summary"]["sent"], 0)
        self.assertEqual(sent_counts[1], 0)

    def test_host_resumes_from_ack_after_runtime_session_reset(self):
        self.addCleanup(sync_service.reset_runtime_state)
        self.conversation(title="Masaüstünden bir kez")
        local_device = sync_service._device_id()
        with app.db() as connection:
            sync_engine.refresh_local_changes(connection, local_device)
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE,
            fingerprint="f" * 64,
            name="Telefon",
            platform="android",
            address="192.168.1.20",
        )

        def peer_batch(ack_cursor):
            return {
                "kind": sync_engine.BATCH_KIND,
                "version": sync_engine.BATCH_VERSION,
                "sender_device_id": REMOTE_DEVICE,
                "after_cursor": 0,
                "cursor": 0,
                "ack_cursor": ack_cursor,
                "has_more": False,
                "records": [],
            }

        first = sync_service._host_on_batch([peer_batch(0)], peer)
        first_cursor = first["batch"]["cursor"]
        self.assertGreater(len(first["batch"]["records"]), 0)

        sync_service.reset_runtime_state()
        second = sync_service._host_on_batch(
            [peer_batch(first_cursor)], peer)

        self.assertEqual(second["batch"]["records"], [])
        self.assertEqual(second["batch"]["cursor"], first_cursor)

    def test_clear_sync_state_resets_runtime_and_persistent_metadata(self):
        self.conversation(title="Eşitleme durumu silinecek")
        sync_service._prepare_database(refresh=True)

        result = sync_service.clear_sync_state()

        with app.db() as connection:
            counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "sync_conflicts", "sync_changes", "sync_seen_versions",
                    "sync_records", "sync_peer_cursors")
            }
            status = connection.execute(
                "SELECT last_sync_at,last_peer_device_id,last_peer_name,"
                "last_summary_json FROM sync_local_status WHERE singleton=1"
            ).fetchone()

        self.assertTrue(result["ok"])
        self.assertTrue(all(value == 0 for value in counts.values()))
        self.assertEqual(list(status), [None, None, None, "{}"])
        self.assertFalse(sync_service.is_busy())

    def test_service_delete_wrapper_uses_install_identity_and_redacts(self):
        sentinel = "SERVICE-DELETE-PRIVATE-7a1c"
        conv_id = self.conversation(title=sentinel)
        with app.db() as connection:
            sync_engine.refresh_local_changes(
                connection, sync_service._device_id())
            records = sync_service.record_local_delete(
                connection, "conversation", conv_id, physical=True)
            encoded = json.dumps([
                list(row) for row in connection.execute(
                    "SELECT payload_json FROM sync_changes")
            ], ensure_ascii=False)
            tombstones = connection.execute(
                "SELECT COUNT(*) FROM sync_records "
                "WHERE deleted_at IS NOT NULL").fetchone()[0]

        self.assertEqual(len(records), 1)
        self.assertNotIn(sentinel, encoded)
        self.assertEqual(tombstones, 1)

    def test_status_never_returns_pairing_or_provider_secrets(self):
        app.set_setting("openai_api_key", "sk-must-stay-local")
        status = sync_service.status()
        encoded = json.dumps(status, ensure_ascii=False)
        self.assertFalse(status["host_running"])
        self.assertTrue(status["secrets_excluded"])
        self.assertNotIn("sk-must-stay-local", encoded)
        self.assertNotIn("pairing_secret", encoded)
        self.assertTrue(Path(app.DB_PATH + ".device-id").is_file())

    def test_remote_conflict_choice_applies_that_version_and_closes_queue(
            self):
        conv_id = self.conversation(title="Ortak seans", ended=1)
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (
                    conv_id, "terapi", "freud", "Bu cihazdaki not",
                    "2026-07-30 10:00", "2026-07-30 10:00",
                ),
            ).lastrowid
            sync_engine.refresh_local_changes(connection, "a" * 32)
            initial = sync_engine.export_change_batch(
                connection, "a" * 32)
            local_note = next(
                row for row in initial["records"]
                if row["record_type"] == "note")
            incoming = copy.deepcopy(local_note)
            incoming.update({
                "origin_device_id": REMOTE_DEVICE,
                "revision": 1,
                "parent_origin_device_id": None,
                "parent_revision": None,
                "updated_at": "2026-07-30T11:00:00+00:00",
            })
            incoming["payload"]["content"] = "Diğer cihazdaki not"
            batch = {
                "kind": sync_engine.BATCH_KIND,
                "version": sync_engine.BATCH_VERSION,
                "sender_device_id": REMOTE_DEVICE,
                "after_cursor": 0,
                "cursor": 1,
                "ack_cursor": 0,
                "has_more": False,
                "records": [incoming],
            }
            merged = sync_engine.apply_change_batch(
                connection, batch, "a" * 32)
            conflict = sync_engine.list_conflicts(connection)[0]
        self.assertEqual(merged["conflicts"], 1)

        result = sync_service.resolve_conflict(
            int(conflict["id"]), "remote")
        self.assertTrue(result["ok"])
        self.assertEqual(result["conflicts"], [])
        with app.db() as connection:
            content = connection.execute(
                "SELECT content FROM notes WHERE id=?", (note_id,)
            ).fetchone()[0]
            resolved = sync_engine.list_conflicts(
                connection, status="resolved")
        self.assertEqual(content, "Diğer cihazdaki not")
        self.assertEqual(resolved[0]["resolution"], "keep_remote")


class DeviceSyncAPITests(HTTPTestCase):

    def test_status_route_is_local_and_secret_free(self):
        status, body, _ = self.request("GET", "/api/sync/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["secrets_excluded"])
        self.assertIn("messages", body["scope"])

    def test_join_route_passes_explicit_device_identity(self):
        expected = {
            "ok": True,
            "summary": {"sent": 1, "received": 2, "conflicts": 0},
            "conflict_rows": [],
        }
        with mock.patch.object(
                app.sync_service, "join", return_value=expected
        ) as join:
            status, body, _ = self.request(
                "POST", "/api/sync/join", {
                    "code": "DV1-safe",
                    "device_name": "Android telefon",
                    "platform": "android",
                })
        self.assertEqual(status, 200)
        self.assertEqual(body, expected)
        join.assert_called_once_with(
            "DV1-safe", device_name="Android telefon",
            platform_name="android")

    def test_unknown_sync_fields_are_rejected(self):
        status, body, _ = self.request(
            "POST", "/api/sync/join",
            {"code": "DV1-safe", "api_key": "must-not-pass"})
        self.assertEqual(status, 400)
        self.assertIn("bilinmeyen", body["error"])


class DeviceSyncInterfaceTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")

    def test_settings_exposes_explicit_secret_free_sync_flow(self):
        for marker in (
                'id="syncOpenBtn"',
                'id="syncOverlay"',
                'id="syncStartBtn"',
                'id="syncScanBtn"',
                'id="syncConsent"',
                "window.onDivanSyncCode",
                "window.onDivanSyncScanError",
                "'/api/sync/start'",
                "'/api/sync/join'",
                "API anahtarları, PIN",
                "Ham veritabanı"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_mobile_uses_scanner_only_view_and_hidden_buttons_stay_hidden(
            self):
        self.assertIn(".syncModal [hidden]{display:none!important}",
                      self.html)
        self.assertIn("$('syncHostCard').hidden=canScan;", self.html)
        self.assertIn("$('syncScanBtn').hidden=!canScan;", self.html)
        self.assertIn(
            "showOverlay('syncOverlay',canScan?"
            "'syncScanBtn':'syncStartBtn')",
            self.html,
        )

    def test_conflicts_require_an_explicit_local_or_remote_choice(self):
        start = self.html.index("function renderDeviceSyncConflicts")
        end = self.html.index("function applyDeviceSyncStatus", start)
        source = self.html[start:end]
        self.assertIn("['Bu cihazdaki','local']", source)
        self.assertIn("['Diğer cihazdaki','remote']", source)
        self.assertNotIn("'both'", source)
