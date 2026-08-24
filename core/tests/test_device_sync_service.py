import copy
import json
from pathlib import Path
from unittest import mock

from support import DatabaseTestCase, HTTPTestCase, PROJECT_DIR, app

import sync_engine
import sync_service


REMOTE_DEVICE = "b" * 32


class DeviceSyncServiceTests(DatabaseTestCase):

    def test_packaged_engine_transport_version_drift_fails_closed(self):
        with mock.patch.object(
                sync_service.transport, "SYNC_PROTOCOL_VERSION", 7), \
                mock.patch.object(
                    sync_service, "_snapshot_callback") as snapshot, \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare:
            with self.assertRaises(sync_service.SyncServiceError) as raised:
                sync_service.start_host(advertised_host="127.0.0.1")
        self.assertEqual(
            raised.exception.code,
            sync_service.transport.SYNC_PROTOCOL_ERROR_CODE)
        snapshot.assert_not_called()
        prepare.assert_not_called()

    def test_join_snapshot_precedes_refresh_and_merge_preparation(self):
        order = []

        def snapshot():
            order.append("snapshot")

        def prepare(*, refresh):
            self.assertTrue(refresh)
            order.append("prepare")
            raise sync_engine.SyncError("legacy merge failed")

        class PairedClient:
            def close(self):
                pass

        with mock.patch.object(
                sync_service, "_snapshot_callback", snapshot), \
                mock.patch.object(
                    sync_service, "_prepare_database", side_effect=prepare), \
                mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    return_value={"desktop_device_id": REMOTE_DEVICE}), \
                mock.patch.object(
                    sync_service.transport, "pair_with_invitation",
                    return_value=(PairedClient(), {"ok": True})):
            with self.assertRaises(sync_service.SyncServiceError):
                sync_service.join("compatible-code")

        self.assertEqual(order, ["snapshot", "prepare"])
        self.assertFalse(sync_service.is_busy())

    def test_host_snapshot_precedes_refresh_and_merge_preparation(self):
        order = []

        def snapshot():
            order.append("snapshot")

        def prepare(*, refresh):
            self.assertTrue(refresh)
            order.append("prepare")
            raise sync_engine.SyncError("legacy merge failed")

        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE, fingerprint="c" * 64,
            name="Telefon", platform="android", address="127.0.0.1")
        with mock.patch.object(
                sync_service, "_snapshot_callback", snapshot), \
                mock.patch.object(
                    sync_service, "_prepare_database", side_effect=prepare):
            sync_service.start_host(advertised_host="127.0.0.1")
            try:
                self.assertEqual(order, [])
                with self.assertRaises(sync_service.SyncServiceError):
                    sync_service._host_on_batch([], peer)
            finally:
                sync_service.stop_host()

        self.assertEqual(order, ["snapshot", "prepare"])
        self.assertFalse(sync_service.is_busy())

    def test_host_rejects_mismatched_peer_before_snapshot_or_database(self):
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE, fingerprint="c" * 64,
            name="Eski telefon", platform="android", address="127.0.0.1",
            protocol_version=6, capabilities=())
        with mock.patch.object(
                sync_service, "_snapshot_callback") as snapshot, \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare:
            with self.assertRaises(sync_service.SyncServiceError) as raised:
                sync_service._host_on_batch([], peer)
        self.assertEqual(
            raised.exception.code,
            sync_service.transport.SYNC_PROTOCOL_ERROR_CODE)
        snapshot.assert_not_called()
        prepare.assert_not_called()

    def test_host_rejects_v6_batch_before_snapshot_or_database(self):
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE, fingerprint="c" * 64,
            name="Telefon", platform="android", address="127.0.0.1")
        old_batch = {
            "kind": sync_engine.BATCH_KIND,
            "version": 6,
            "sender_device_id": REMOTE_DEVICE,
            "after_cursor": 0,
            "cursor": 0,
            "ack_cursor": 0,
            "has_more": False,
            "records": [],
        }
        with mock.patch.object(
                sync_service, "_snapshot_callback") as snapshot, \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare:
            with self.assertRaisesRegex(
                    sync_engine.SyncError, "protocol v8 required"):
                sync_service._host_on_batch([old_batch], peer)
        snapshot.assert_not_called()
        prepare.assert_not_called()

    def test_host_rejects_v7_batch_before_snapshot_or_database(self):
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE, fingerprint="c" * 64,
            name="Telefon", platform="android", address="127.0.0.1")
        legacy_batch = {
            "kind": sync_engine.BATCH_KIND,
            "version": 7,
            "sender_device_id": REMOTE_DEVICE,
            "after_cursor": 0,
            "cursor": 0,
            "ack_cursor": 0,
            "has_more": False,
            "records": [],
        }
        with mock.patch.object(
                sync_service, "_snapshot_callback") as snapshot, \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare:
            with self.assertRaisesRegex(
                    sync_engine.SyncError, "protocol v8 required"):
                sync_service._host_on_batch([legacy_batch], peer)
        snapshot.assert_not_called()
        prepare.assert_not_called()

    def test_snapshot_failure_aborts_before_any_local_refresh(self):
        class PairedClient:
            def close(self):
                pass

        with mock.patch.object(
                sync_service, "_snapshot_callback",
                side_effect=OSError("private path detail")), \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare, \
                mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    return_value={"desktop_device_id": REMOTE_DEVICE}), \
                mock.patch.object(
                    sync_service.transport, "pair_with_invitation",
                    return_value=(PairedClient(), {"ok": True})):
            with self.assertRaisesRegex(
                    sync_service.SyncServiceError,
                    "güvenli geri dönüş noktası"):
                sync_service.join("unused-code")
        prepare.assert_not_called()
        self.assertFalse(sync_service.is_busy())

    def test_protocol_mismatch_aborts_before_snapshot_refresh_or_pairing(self):
        with mock.patch.object(
                sync_service, "_snapshot_callback") as snapshot, \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare, \
                mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    side_effect=sync_service.transport.
                    SyncProtocolMismatchError(
                        sync_service.transport.SYNC_PROTOCOL_ERROR_COPY)), \
                mock.patch.object(
                    sync_service.transport, "pair_with_invitation") as pair:
            with self.assertRaises(sync_service.SyncServiceError) as raised:
                sync_service.join("v6-code")
        self.assertEqual(
            raised.exception.code,
            sync_service.transport.SYNC_PROTOCOL_ERROR_CODE)
        self.assertEqual(
            str(raised.exception),
            sync_service.transport.SYNC_PROTOCOL_ERROR_COPY)
        snapshot.assert_not_called()
        prepare.assert_not_called()
        pair.assert_not_called()
        self.assertFalse(sync_service.is_busy())

    def test_invalid_invitation_does_not_create_snapshot_or_refresh(self):
        with mock.patch.object(
                sync_service, "_snapshot_callback") as snapshot, \
                mock.patch.object(
                    sync_service, "_prepare_database") as prepare, \
                mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    side_effect=ValueError("expired")):
            with self.assertRaises(sync_service.SyncServiceError):
                sync_service.join("expired-code")
        snapshot.assert_not_called()
        prepare.assert_not_called()
        self.assertFalse(sync_service.is_busy())

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

    def test_join_wraps_local_projection_error_without_exposing_detail(self):
        class PairedClient:
            def close(self):
                pass

        with mock.patch.object(
                sync_service, "_prepare_database",
                side_effect=sync_engine.SyncError(
                    "referenced conversation row has no sync identity")), \
                mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    return_value={"desktop_device_id": REMOTE_DEVICE}), \
                mock.patch.object(
                    sync_service.transport, "pair_with_invitation",
                    return_value=(PairedClient(), {"ok": True})):
            with self.assertRaises(sync_service.SyncServiceError) as raised:
                sync_service.join("scanned-code")

        message = str(raised.exception)
        self.assertIn("Yerel eşitleme kayıtlarından biri", message)
        self.assertNotIn("conversation", message)
        self.assertFalse(sync_service.is_busy())

    def test_host_wraps_local_projection_error_after_compatible_pair(self):
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE, fingerprint="c" * 64,
            name="Telefon", platform="android", address="127.0.0.1")
        with mock.patch.object(
                sync_service, "_prepare_database",
                side_effect=sync_engine.SyncError(
                    "referenced message row has no sync identity")):
            sync_service.start_host(advertised_host="127.0.0.1")
            try:
                with self.assertRaises(
                        sync_service.SyncServiceError) as raised:
                    sync_service._host_on_batch([], peer)
            finally:
                sync_service.stop_host()

        message = str(raised.exception)
        self.assertIn("Yerel eşitleme kayıtlarından biri", message)
        self.assertNotIn("message", message)
        self.assertFalse(sync_service.is_busy())
        state = sync_service.status()
        self.assertFalse(state["host_running"])
        self.assertFalse(state["busy"])
        self.assertEqual(state["seconds_remaining"], 0)

    def test_join_maps_invitation_expiry_during_pairing_to_stable_error(self):
        invitation = {
            "desktop_device_id": REMOTE_DEVICE,
        }
        with mock.patch.object(
                sync_service.transport, "parse_invitation",
                return_value=invitation), mock.patch.object(
                sync_service.transport, "pair_with_invitation",
                side_effect=ValueError("invitation has expired")):
            with self.assertRaises(sync_service.SyncServiceError) as raised:
                sync_service.join("almost-expired-code")

        self.assertEqual(
            str(raised.exception),
            "Eşleme kodu geçersiz veya süresi dolmuş.")
        self.assertFalse(sync_service.is_busy())

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
                first_result = {
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
                    "more": True,
                    "apply": {
                        "records": len(local_batch["records"]),
                        "conflicts": 0,
                    },
                    "confirmation_required": True,
                    "exact_equal": False,
                    "projection": None,
                    "live_count": None,
                }
                apply_result(first_result)
                final_items, final_done = next_batch(first_result)
                assert final_done is True
                assert len(final_items) == 2
                confirmation = final_items[1]
                apply_result({
                    "batch": {
                        "kind": sync_engine.BATCH_KIND,
                        "version": sync_engine.BATCH_VERSION,
                        "sender_device_id": REMOTE_DEVICE,
                        "after_cursor": 0,
                        "cursor": 0,
                        "ack_cursor": final_items[0]["cursor"],
                        "has_more": False,
                        "records": [],
                    },
                    "more": False,
                    "apply": {
                        "records": 0,
                        "conflicts": 0,
                        "auto_merged": 0,
                    },
                    "confirmation_required": False,
                    "exact_equal": True,
                    "projection": confirmation["projection"],
                    "live_count": confirmation["projection"]["live_count"],
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

        # A cursor becomes durable only after the peer proves the complete
        # live projection, not merely by echoing a high-water number.
        with app.db() as connection:
            proof = sync_engine.projection_summary(connection)
        confirmed = sync_service._host_on_batch([
            peer_batch(first_cursor),
            {
                "kind": sync_service.PROJECTION_CONFIRM_KIND,
                "sender_device_id": REMOTE_DEVICE,
                "projection": proof,
            },
        ], peer)
        self.assertTrue(confirmed["exact_equal"])

        sync_service.reset_runtime_state()
        second = sync_service._host_on_batch(
            [peer_batch(first_cursor)], peer)

        self.assertEqual(second["batch"]["records"], [])
        self.assertEqual(second["batch"]["cursor"], first_cursor)

    def test_host_accepts_previously_offered_cursor_after_lost_response(self):
        self.addCleanup(sync_service.reset_runtime_state)
        self.conversation(title="Yarım kalan aktarım")
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

        offered = sync_service._host_on_batch([peer_batch(0)], peer)
        offered_cursor = offered["batch"]["cursor"]
        self.assertGreater(offered_cursor, 0)
        sync_service.reset_runtime_state()

        resumed = sync_service._host_on_batch(
            [peer_batch(offered_cursor)], peer)
        self.assertEqual(resumed["batch"]["records"], [])
        self.assertEqual(resumed["batch"]["cursor"], offered_cursor)
        # The acknowledgement remains provisional until projection proof.
        with app.db() as connection:
            self.assertEqual(
                sync_engine.peer_ack_cursor(connection, REMOTE_DEVICE), 0)
            self.assertEqual(
                sync_engine.peer_offered_cursor(connection, REMOTE_DEVICE),
                offered_cursor)

    def test_host_requires_and_verifies_final_projection_confirmation(self):
        self.addCleanup(sync_service.reset_runtime_state)
        sync_service.reset_runtime_state()
        self.conversation(title="Eşitlik kanıtı")
        local_device = sync_service._device_id()
        sync_service._prepare_database(refresh=True)
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
        self.assertTrue(first["confirmation_required"])
        self.assertTrue(first["more"])
        self.assertFalse(first["exact_equal"])
        with app.db() as connection:
            proof = sync_engine.projection_summary(connection)
        confirmation = {
            "kind": sync_service.PROJECTION_CONFIRM_KIND,
            "sender_device_id": REMOTE_DEVICE,
            "projection": proof,
        }
        final = sync_service._host_on_batch(
            [peer_batch(first["batch"]["cursor"]), confirmation], peer)

        self.assertEqual(final["batch"]["records"], [])
        self.assertFalse(final["more"])
        self.assertTrue(final["exact_equal"])
        self.assertEqual(final["live_count"], proof["live_count"])
        status = sync_service.status()
        self.assertTrue(status["last_summary"]["exact_equal"])
        self.assertEqual(
            status["last_summary"]["live_count"], proof["live_count"])

    def test_projection_mismatch_completes_without_false_equal_label(self):
        self.addCleanup(sync_service.reset_runtime_state)
        sync_service.reset_runtime_state()
        self.conversation(title="Farklı eşitlik özeti")
        sync_service._prepare_database(refresh=True)
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE,
            fingerprint="f" * 64,
            name="Telefon",
            platform="android",
            address="192.168.1.20",
        )
        empty = {
            "kind": sync_engine.BATCH_KIND,
            "version": sync_engine.BATCH_VERSION,
            "sender_device_id": REMOTE_DEVICE,
            "after_cursor": 0,
            "cursor": 0,
            "ack_cursor": 0,
            "has_more": False,
            "records": [],
        }
        first = sync_service._host_on_batch([empty], peer)
        with app.db() as connection:
            proof = sync_engine.projection_summary(connection)
        proof["digest"] = "0" * 64
        mismatch = sync_service._host_on_batch([
            {**empty, "ack_cursor": first["batch"]["cursor"]},
            {
                "kind": sync_service.PROJECTION_CONFIRM_KIND,
                "sender_device_id": REMOTE_DEVICE,
                "projection": proof,
            },
        ], peer)
        self.assertFalse(mismatch["more"])
        self.assertFalse(mismatch["exact_equal"])

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
        self.assertFalse(Path(app.DB_PATH + ".device-id").exists())

    def test_status_is_read_only_before_protocol_preflight(self):
        with mock.patch.object(
                sync_service, "_prepare_database") as prepare:
            state = sync_service.status()
        prepare.assert_not_called()
        self.assertFalse(state["host_running"])
        self.assertFalse(Path(app.DB_PATH + ".device-id").exists())

    def test_latest_remote_version_applies_without_manual_conflict_queue(
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
                "updated_at": "2099-07-30T11:00:00+00:00",
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
            content = connection.execute(
                "SELECT content FROM notes WHERE id=?", (note_id,)
            ).fetchone()[0]
            conflicts = sync_engine.list_conflicts(connection)
        self.assertEqual(merged["conflicts"], 0)
        self.assertEqual(content, "Diğer cihazdaki not")
        self.assertEqual(conflicts, [])


class DeviceSyncAPITests(HTTPTestCase):

    def test_status_route_is_local_and_secret_free(self):
        status, body, _ = self.request("GET", "/api/sync/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["secrets_excluded"])
        self.assertIn("messages", body["scope"])
        self.assertIn("adhd_habits", body["scope"])
        self.assertIn(
            "shared_non_sensitive_adhd_journal_entries", body["scope"])
        self.assertIn(
            "explicitly_consented_schema_path_v4_v5_projection",
            body["scope"])
        self.assertIn(
            "schema_prompt_plans_and_results", body["device_local"])
        self.assertIn("reminders", body["device_local"])
        self.assertIn(
            "schema_raw_observations_and_claims", body["device_local"])
        self.assertIn("schema_provider_consent", body["device_local"])
        self.assertIn(
            "schema_technique_transcripts", body["device_local"])

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

    def test_protocol_update_error_code_and_copy_reach_the_local_ui(self):
        error = sync_service.SyncServiceError(
            sync_service.transport.SYNC_PROTOCOL_ERROR_COPY,
            sync_service.transport.SYNC_PROTOCOL_ERROR_CODE,
        )
        with mock.patch.object(
                app.sync_service, "join", side_effect=error):
            status, body, _ = self.request(
                "POST", "/api/sync/join", {
                    "code": "DV1-old-peer",
                    "device_name": "Android telefon",
                    "platform": "android",
                })
        self.assertEqual(status, 409)
        self.assertEqual(
            body["error_code"],
            sync_service.transport.SYNC_PROTOCOL_ERROR_CODE)
        self.assertEqual(
            body["error"], sync_service.transport.SYNC_PROTOCOL_ERROR_COPY)

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

    def test_latest_merge_is_automatic_and_exactness_is_proven(self):
        start = self.html.index("function deviceSyncMergeResult")
        end = self.html.index("function applyDeviceSyncStatus", start)
        source = self.html[start:end]
        self.assertIn("source.auto_merged", source)
        self.assertIn("source.exact_equal===true", source)
        self.assertIn("Eşitlik kanıtlanamadı", source)
        self.assertIn("'/api/sync/conflict'", self.html)
        self.assertIn(
            "normal kayıtların en güncel güvenli sürümünün otomatik",
            self.html)
        self.assertIn("Normal kayıtlar otomatik birleşir", self.html)
        self.assertIn("Bu cihazdaki", self.html)
        self.assertIn("Diğer cihazdaki", self.html)
        self.assertIn(
            "Silme ve gizlilik kararı her zaman", self.html)

    def test_clinical_pause_and_conflict_ui_are_content_free(self):
        for marker in (
                "clinical_confirmation_required",
                "clinical_confirmation_device",
                "pending_clinical_confirmation_conv_ids",
                "clinical_safety_pause", "clinical_safety_device",
                "Güvenlik beklemesi kapandıktan sonra yeni bir QR",
                "syncClinicalApprove", "syncClinicalDecline",
                "normalizeDeviceSyncConflicts",
                "deviceSyncState.conflictBusy.has"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        conflict = self.html[
            self.html.index("function normalizeDeviceSyncConflicts"):
            self.html.index("function renderDeviceSyncConflicts")]
        for safe_key in ("title", "summary", "reason"):
            self.assertIn(safe_key, conflict)
        for sensitive_key in ("incoming_json", "local_json", "payload_json"):
            self.assertNotIn(sensitive_key, conflict)

    def test_last_sync_status_uses_the_existing_timestamp_formatter(self):
        start = self.html.index("function applyDeviceSyncStatus")
        end = self.html.index("async function loadDeviceSyncStatus", start)
        source = self.html[start:end]
        self.assertIn(
            "mobileMasterHistoryStamp(status.last_sync_at)", source)
        self.assertNotIn("formatMessageClock", source)

    def test_protocol_update_pause_clears_local_join_state_without_refresh(self):
        start = self.html.index("async function joinDeviceSync()")
        end = self.html.index("function closeDeviceSync()", start)
        source = self.html[start:end]
        branch_start = source.index("const updateRequired=")
        branch_end = source.index(
            "$('syncJoinResult').textContent=\n"
            "      'Eşitleme tamamlanamadı", branch_start)
        branch = source[branch_start:branch_end]
        self.assertIn("sync_protocol_update_required", branch)
        self.assertIn(
            "Her iki cihazdaki Divan’ı güncelleyin; sonra yeni QR oluşturun.",
            branch,
        )
        self.assertIn("resetDeviceSyncInvitation()", branch)
        self.assertIn("deviceSyncState.pollTimer=null", branch)
        self.assertIn("$('syncJoinCode').value=''", branch)
        self.assertIn("$('syncConsent').checked=false", branch)
        self.assertIn("hiçbir veri aktarılmadı", branch)
        self.assertIn("return;", branch)
        self.assertNotIn("refreshConversationLists", branch)
        self.assertNotIn("openConv", branch)
        self.assertNotIn("loadDeviceSyncStatus", branch)

        api_start = self.html.index(
            "async function api(path, body, {quiet=false}={})")
        api_end = self.html.index("const API_GET_RETRY_DELAYS", api_start)
        self.assertIn(
            "err.code=String(data&&data.error_code||'')",
            self.html[api_start:api_end],
        )
