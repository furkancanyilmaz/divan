import base64
import hashlib
import json
import os
import shutil
import socket
import ssl
import tempfile
import time
import unittest
from unittest import mock

import secure_sync_transport as sync


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def request_id(number):
    return b64url(hashlib.sha256(str(number).encode()).digest()[:18])


class SecureSyncTransportTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        self.session = sync.SecureSyncSession(
            "127.0.0.1",
            "a" * 32,
            self.merge,
            ttl_seconds=10,
        )
        self.invitation = self.session.start()

    def tearDown(self):
        self.session.stop()

    def merge(self, batch, peer):
        self.received.append((batch, peer))
        return {"accepted": len(batch)}

    def pair(self, **changes):
        payload = self.invitation.payload
        public_key = b64url(b"test-public-key-material-" * 4)
        value = {
            "session_id": payload["session_id"],
            "pairing_secret": payload["pairing_secret"],
            "protocol_version": sync.SYNC_PROTOCOL_VERSION,
            "capabilities": list(sync.SYNC_CAPABILITIES),
            "device": {
                "id": "b" * 32,
                "public_key": public_key,
                "name": "Test telefonu",
                "platform": "android",
            },
            "request_id": request_id(0),
            "seq": 0,
        }
        value.update(changes)
        return sync.pinned_json_post(
            payload["host"], payload["port"], "/v1/pair",
            payload["cert_sha256"], value)

    def batch(self, token, seq=1, batch=None, complete=False,
              request_number=1):
        payload = self.invitation.payload
        return sync.pinned_json_post(
            payload["host"], payload["port"], "/v1/batch",
            payload["cert_sha256"], {
                "request_id": request_id(request_number),
                "seq": seq,
                "batch": batch if batch is not None else [{"id": "1"}],
                "complete": complete,
            },
            headers={"Authorization": "Bearer " + token},
        )

    def test_invitation_schema_manual_roundtrip_and_redacted_repr(self):
        payload = self.invitation.payload
        self.assertEqual(sync.SYNC_PROTOCOL_VERSION, 8)
        self.assertEqual(sync.SYNC_CAPABILITIES, (
            "schema_checkpoint_v1", "schema_path_chat_v5"))
        self.assertEqual(payload["scheme"], "https")
        self.assertEqual(payload["path"], "/v1")
        self.assertEqual(
            payload["protocol_version"], sync.SYNC_PROTOCOL_VERSION)
        self.assertEqual(
            payload["capabilities"], list(sync.SYNC_CAPABILITIES))
        self.assertIn(
            sync.SCHEMA_PATH_V5_SYNC_CAPABILITY,
            payload["capabilities"])
        self.assertRegex(payload["cert_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            sync.decode_manual_code(self.invitation.manual_code), payload)
        self.assertTrue(self.invitation.qr_uri.startswith(
            "divan://sync?data=DV1-"))
        self.assertEqual(
            self.invitation.pairing_uri, self.invitation.qr_uri)
        self.assertEqual(
            self.invitation.cert_sha256, payload["cert_sha256"])
        representation = repr(self.invitation)
        self.assertNotIn(payload["pairing_secret"], representation)
        self.assertNotIn(payload["session_id"], representation)
        self.assertEqual(
            sync.parse_invitation(self.invitation.pairing_uri), payload)
        self.assertEqual(
            sync.parse_invitation(json.dumps(payload)), payload)

    def test_pinned_pair_batch_and_complete_close_listener(self):
        status, paired = self.pair()
        self.assertEqual(status, 200)
        self.assertTrue(paired["ok"])
        self.assertEqual(
            paired["protocol_version"], sync.SYNC_PROTOCOL_VERSION)
        self.assertEqual(
            paired["capabilities"], list(sync.SYNC_CAPABILITIES))
        self.assertNotIn(
            self.invitation.payload["pairing_secret"],
            json.dumps(paired))

        status, result = self.batch(
            paired["session_token"], complete=True)
        self.assertEqual(status, 200)
        self.assertEqual(result["result"], {"accepted": 1})
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0][1].device_id, "b" * 32)
        deadline = time.time() + 2
        while self.session.running and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.session.running)

    def test_wrong_certificate_pin_fails_before_pair_secret_is_sent(self):
        payload = self.invitation.payload
        with self.assertRaises(sync.CertificatePinError):
            sync.pinned_json_post(
                payload["host"], payload["port"], "/v1/pair",
                "0" * 64, {
                    "pairing_secret": payload["pairing_secret"],
                })
        status, paired = self.pair()
        self.assertEqual(status, 200)
        self.assertTrue(paired["ok"])

    def test_pairing_secret_is_one_time(self):
        status, _ = self.pair()
        self.assertEqual(status, 200)
        status, body = self.pair(
            request_id=request_id(99))
        self.assertEqual(status, 409)
        self.assertIn("kullanıldı", body["error"])

    def test_protocol_mismatch_is_stable_and_does_not_consume_secret(self):
        status, body = self.pair(protocol_version=7)
        self.assertEqual(status, 409)
        self.assertEqual(
            body["error_code"], sync.SYNC_PROTOCOL_ERROR_CODE)
        self.assertEqual(body["error"], sync.SYNC_PROTOCOL_ERROR_COPY)

        status, paired = self.pair(request_id=request_id(99))
        self.assertEqual(status, 200)
        self.assertTrue(paired["ok"])

    def test_legacy_invitation_fails_before_network_or_pairing(self):
        legacy = dict(self.invitation.payload)
        legacy.pop("protocol_version")
        legacy.pop("capabilities")
        with self.assertRaises(sync.SyncProtocolMismatchError) as raised:
            sync.parse_invitation(legacy)
        self.assertEqual(str(raised.exception), sync.SYNC_PROTOCOL_ERROR_COPY)

    def test_capability_allowlist_is_exact(self):
        # A v7 peer knows only the legacy checkpoint capability and cannot
        # consume a v5 path, even if it lies about the numeric protocol.
        status, body = self.pair(
            capabilities=[sync.SYNC_CAPABILITY])
        self.assertEqual(status, 409)
        self.assertEqual(
            body["error_code"], sync.SYNC_PROTOCOL_ERROR_CODE)
        status, body = self.pair(
            capabilities=list(sync.SYNC_CAPABILITIES) + [
                "future_capability"])
        self.assertEqual(status, 409)
        self.assertEqual(
            body["error_code"], sync.SYNC_PROTOCOL_ERROR_CODE)
        status, paired = self.pair(request_id=request_id(98))
        self.assertEqual(status, 200)
        self.assertTrue(paired["ok"])

    def test_failed_pair_helper_discards_local_secret_and_session(self):
        client = sync.PinnedSyncClient(self.invitation)
        with mock.patch.object(
                client, "pair",
                side_effect=sync.SyncProtocolMismatchError(
                    sync.SYNC_PROTOCOL_ERROR_COPY)), \
                mock.patch.object(
                    sync, "PinnedSyncClient", return_value=client):
            with self.assertRaises(sync.SyncProtocolMismatchError):
                sync.pair_with_invitation(
                    self.invitation, device_id="b" * 32,
                    public_key=b"test-public-key-material-" * 4,
                    name="Telefon", platform="android")
        self.assertEqual(
            client._invitation["pairing_secret"], "<discarded>")
        self.assertIsNone(client._session_token)

    def test_pair_attempt_rate_limit(self):
        payload = self.invitation.payload
        public_key = b64url(b"test-public-key-material-" * 4)
        for number in range(sync.PAIR_ATTEMPTS_PER_MINUTE + 1):
            status, _ = sync.pinned_json_post(
                payload["host"], payload["port"], "/v1/pair",
                payload["cert_sha256"], {
                    "session_id": payload["session_id"],
                    "pairing_secret": b64url(b"\x00" * 32),
                    "protocol_version": sync.SYNC_PROTOCOL_VERSION,
                    "capabilities": list(sync.SYNC_CAPABILITIES),
                    "device": {
                        "id": "b" * 32,
                        "public_key": public_key,
                        "name": "Test",
                        "platform": "android",
                    },
                    "request_id": request_id(number),
                    "seq": 0,
                })
            if number < sync.PAIR_ATTEMPTS_PER_MINUTE:
                self.assertEqual(status, 401)
            else:
                self.assertEqual(status, 429)

    def test_replay_and_out_of_order_batches_are_rejected(self):
        _, paired = self.pair()
        token = paired["session_token"]
        status, _ = self.batch(token, seq=1, request_number=1)
        self.assertEqual(status, 200)
        status, _ = self.batch(token, seq=1, request_number=1)
        self.assertEqual(status, 409)
        status, _ = self.batch(token, seq=3, request_number=3)
        self.assertEqual(status, 409)
        status, _ = self.batch(token, seq=2, request_number=2)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.received), 2)

    def test_batch_item_and_byte_limits_are_applied_before_callback(self):
        _, paired = self.pair()
        token = paired["session_token"]
        status, body = self.batch(
            token, batch=[{}] * (sync.MAX_BATCH_ITEMS + 1))
        self.assertEqual(status, 413)
        self.assertIn("çok fazla", body["error"])
        self.assertEqual(self.received, [])

        status, body = self.batch(
            token, batch=["x" * sync.MAX_BATCH_BYTES])
        self.assertEqual(status, 413)
        self.assertIn("çok büyük", body["error"])
        self.assertEqual(self.received, [])

    def test_expiry_closes_listener(self):
        self.session.stop()
        session = sync.SecureSyncSession(
            "127.0.0.1", "a" * 32, self.merge, ttl_seconds=1)
        session.start()
        try:
            deadline = time.time() + 3
            while session.running and time.time() < deadline:
                time.sleep(0.03)
            self.assertFalse(session.running)
        finally:
            session.stop()

    def test_generic_client_drains_host_after_client_is_done(self):
        self.session.stop()
        host_rounds = []

        def exchange(batch, peer):
            host_rounds.append(batch)
            if len(host_rounds) == 1:
                return {"items": [{"side": "host", "n": 1}], "more": True}
            return {"items": [{"side": "host", "n": 2}], "more": False}

        session = sync.SecureSyncSession(
            "127.0.0.1", "a" * 32, exchange, ttl_seconds=10)
        invitation = session.start()
        try:
            client, paired = sync.pair_with_invitation(
                invitation,
                device_id="b" * 32,
                public_key=b"test-public-key-material-" * 4,
                name="Test telefonu",
                platform="android",
            )
            self.assertNotIn(
                invitation.payload["pairing_secret"], repr(client))
            self.assertEqual(paired["peer_id"], "a" * 32)
            outgoing = [[{"side": "client"}], []]
            applied = []

            def next_batch(peer_result):
                return outgoing.pop(0), True

            client.run_batches(next_batch, applied.append)

            self.assertEqual(
                host_rounds, [[{"side": "client"}], []])
            self.assertEqual(
                [item["more"] for item in applied], [True, False])
            deadline = time.time() + 2
            while session.running and time.time() < deadline:
                time.sleep(0.02)
            self.assertFalse(session.running)
        finally:
            session.stop()

    def test_no_secure_certificate_backend_fails_closed(self):
        self.session.stop()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(
                    sync, "_generate_with_cryptography",
                    side_effect=ImportError), \
                mock.patch.object(sync.shutil, "which", return_value=None):
            with self.assertRaises(sync.TLSUnavailableError):
                sync.generate_ephemeral_certificate(
                    directory, "127.0.0.1")
        session = sync.SecureSyncSession(
            "127.0.0.1", "a" * 32, self.merge,
            certificate_factory=lambda *_: (_ for _ in ()).throw(
                sync.TLSUnavailableError("unavailable")),
        )
        with self.assertRaises(sync.TLSUnavailableError):
            session.start()
        self.assertFalse(session.running)

    @unittest.skipUnless(
        shutil.which("openssl"), "system openssl is unavailable")
    def test_system_openssl_is_a_working_certificate_fallback(self):
        self.session.stop()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(
                    sync, "_generate_with_cryptography",
                    side_effect=ImportError):
            cert_path, key_path, fingerprint = (
                sync.generate_ephemeral_certificate(
                    directory, "127.0.0.1"))
            self.assertTrue(os.path.isfile(cert_path))
            self.assertTrue(os.path.isfile(key_path))
            self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")

    def test_origin_and_wrong_host_are_rejected(self):
        payload = self.invitation.payload
        public_key = b64url(b"test-public-key-material-" * 4)
        pair = {
            "session_id": payload["session_id"],
            "pairing_secret": payload["pairing_secret"],
            "device": {
                "id": "b" * 32,
                "public_key": public_key,
                "name": "Test",
                "platform": "android",
            },
            "request_id": request_id(0),
            "seq": 0,
        }
        status, _ = sync.pinned_json_post(
            payload["host"], payload["port"], "/v1/pair",
            payload["cert_sha256"], pair,
            headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection(
            (payload["host"], payload["port"]), timeout=3)
        wrapped = context.wrap_socket(raw)
        try:
            body = json.dumps(pair).encode()
            wrapped.sendall(
                b"POST /v1/pair HTTP/1.1\r\n"
                b"Host: evil.example\r\n"
                b"Content-Type: application/json\r\n"
                + "Content-Length: {}\r\n".format(len(body)).encode()
                + b"Connection: close\r\n\r\n" + body
            )
            response = wrapped.recv(256)
        finally:
            wrapped.close()
        self.assertIn(b" 403 ", response)


class LanDiscoveryTests(unittest.TestCase):
    def test_macos_interface_fallback_finds_active_wifi_without_network_probe(
            self):
        output = """lo0: flags=8049<UP,LOOPBACK>
    inet 127.0.0.1 netmask 0xff000000
utun0: flags=8051<UP,POINTOPOINT>
    inet 10.200.0.4 netmask 0xffffffff
en1: flags=8863<UP,RUNNING>
    inet 192.168.50.8 netmask 0xffffff00
    status: inactive
en0: flags=8863<UP,RUNNING>
    inet 192.168.50.23 netmask 0xffffff00
    status: active
"""
        with mock.patch.object(
                sync.socket, "getaddrinfo", return_value=[]), \
                mock.patch.object(
                    sync.shutil, "which",
                    side_effect=lambda name: (
                        "/sbin/ifconfig" if name == "ifconfig" else None)), \
                mock.patch.object(
                    sync.subprocess, "run",
                    return_value=mock.Mock(stdout=output)):
            values = sync.discover_lan_addresses()
        self.assertEqual(values, ["192.168.50.23"])


if __name__ == "__main__":
    unittest.main()
