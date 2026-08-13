#!/usr/bin/env python3
"""Short-lived, pinned-TLS LAN transport for explicit Divan sync.

This module is deliberately independent from server.py's loopback HTTP server.
Creating an object does not bind a socket; callers must explicitly call start().
The payload merge/export policy belongs to the supplied callback.
"""

from __future__ import annotations

import base64
import collections
import datetime
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional


PROTOCOL_VERSION = 1
DEFAULT_TTL_SECONDS = 5 * 60
MAX_TTL_SECONDS = 5 * 60
MAX_REQUEST_BYTES = 512 * 1024
MAX_BATCH_BYTES = 480 * 1024
MAX_BATCH_ITEMS = 100
MAX_ACTIVE_REQUESTS = 4
PAIR_ATTEMPTS_PER_MINUTE = 6
REQUESTS_PER_MINUTE = 60
MANUAL_CODE_PREFIX = "DV1-"

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class SecureSyncError(RuntimeError):
    """Base error safe to display without transport secrets."""


class TLSUnavailableError(SecureSyncError):
    """No secure ephemeral-certificate backend is available."""


class CertificatePinError(SecureSyncError):
    """The listener certificate does not match the out-of-band invitation."""


class TransportInputError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str, *, maximum: int) -> bytes:
    if (not isinstance(value, str) or not value or
            len(value) > maximum * 2 or not _B64URL_RE.fullmatch(value)):
        raise ValueError("invalid base64url value")
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(
            padded, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise ValueError("invalid base64url value")
    if len(decoded) > maximum:
        raise ValueError("base64url value is too large")
    return decoded


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_host(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 253:
        raise ValueError("advertised host is required")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if not re.fullmatch(
                r"(?=.{1,253}\Z)(?:[A-Za-z0-9]"
                r"(?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
                value):
            raise ValueError("advertised host is invalid")
        return value.lower()


def _host_header(host: str, port: int) -> str:
    try:
        if ipaddress.ip_address(host).version == 6:
            return "[{}]:{}".format(host, port)
    except ValueError:
        pass
    return "{}:{}".format(host, port)


def discover_lan_addresses() -> list[str]:
    """Return non-loopback local addresses without contacting a remote host."""
    found: Dict[str, int] = {}

    def add(raw: str, priority: int) -> None:
        raw = str(raw or "").strip().split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return
        if (address.version != 4 or address.is_unspecified or
                address.is_loopback or address.is_multicast):
            return
        if not (address.is_private or address.is_link_local):
            return
        value = str(address)
        found[value] = min(priority, found.get(value, priority))

    try:
        records = socket.getaddrinfo(socket.gethostname(), None)
    except OSError:
        records = []
    for record in records:
        add(record[4][0], 50)

    # macOS frequently maps its hostname only to loopback.  Read the local
    # interface table as a fallback; this never contacts an external host.
    # Commands and arguments are fixed, output is bounded, and no shell is
    # involved.
    ifconfig = shutil.which("ifconfig")
    if ifconfig:
        try:
            result = subprocess.run(
                [ifconfig], check=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=3)
            output = result.stdout[:1024 * 1024]
        except (OSError, subprocess.SubprocessError):
            output = ""
        matches = list(re.finditer(r"(?m)^([A-Za-z0-9_.-]+):", output))
        skipped_prefixes = (
            "lo", "utun", "awdl", "llw", "bridge", "docker", "veth",
            "virbr", "tailscale", "gif", "stf", "anpi",
        )
        for index, match in enumerate(matches):
            interface = match.group(1).lower()
            if interface.startswith(skipped_prefixes):
                continue
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches) else len(output))
            block = output[match.start():end]
            if re.search(r"(?m)^\s*status:\s*inactive\s*$", block):
                continue
            if interface in ("en0", "wlan0", "wifi0"):
                priority = 0
            elif interface.startswith(("en", "wl", "eth")):
                priority = 10
            else:
                priority = 30
            for value in re.findall(
                    r"(?m)^\s*inet\s+(\d{1,3}(?:\.\d{1,3}){3})\b",
                    block):
                add(value, priority)

    # Linux desktop packages may provide `ip` but not `ifconfig`.
    ip_command = shutil.which("ip")
    if ip_command:
        try:
            result = subprocess.run(
                [ip_command, "-o", "-4", "addr", "show", "up"],
                check=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=3)
            output = result.stdout[:1024 * 1024]
        except (OSError, subprocess.SubprocessError):
            output = ""
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            interface = parts[1].rstrip(":").lower()
            if interface.startswith((
                    "lo", "docker", "veth", "virbr", "tailscale", "tun")):
                continue
            try:
                inet_index = parts.index("inet")
                value = parts[inet_index + 1].split("/", 1)[0]
            except (ValueError, IndexError):
                continue
            priority = (
                0 if interface.startswith(("wl", "en"))
                else 10 if interface.startswith("eth") else 30)
            add(value, priority)

    return [
        value for value, _ in sorted(
            found.items(), key=lambda item: (item[1], item[0]))
    ]


@dataclass(frozen=True, repr=False)
class PairingInvitation:
    """A sensitive invitation. Its repr intentionally never includes secrets."""

    payload: Dict[str, Any]
    manual_code: str
    qr_uri: str

    @property
    def pairing_uri(self) -> str:
        return self.qr_uri

    @property
    def cert_sha256(self) -> str:
        return str(self.payload["cert_sha256"])

    def __repr__(self) -> str:
        return (
            "PairingInvitation(session_id=<redacted>, "
            "pairing_secret=<redacted>, cert_sha256={!r}, expires_at={!r})"
        ).format(
            self.payload.get("cert_sha256"),
            self.payload.get("expires_at"),
        )


@dataclass(frozen=True)
class PeerIdentity:
    device_id: str
    fingerprint: str
    name: str
    platform: str
    address: str


class _WindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = int(limit)
        self.window = float(window_seconds)
        self._events: Dict[str, collections.deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            values = self._events.setdefault(key, collections.deque())
            while values and values[0] <= now - self.window:
                values.popleft()
            if len(values) >= self.limit:
                return False
            values.append(now)
            if len(self._events) > 1024:
                self._events = {
                    item_key: item_values
                    for item_key, item_values in self._events.items()
                    if item_values and item_values[-1] > now - self.window
                }
            return True


def _write_private_file(path: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _generate_with_cryptography(
        cert_path: str, key_path: str, advertised_host: str) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Divan temporary sync"),
    ])
    try:
        san = x509.IPAddress(ipaddress.ip_address(advertised_host))
    except ValueError:
        san = x509.DNSName(advertised_host)
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(minutes=10))
        .add_extension(
            x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True)
        .sign(key, hashes.SHA256())
    )
    _write_private_file(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write_private_file(
        cert_path, certificate.public_bytes(serialization.Encoding.PEM))


def _openssl_config(advertised_host: str) -> str:
    try:
        ipaddress.ip_address(advertised_host)
        san = "IP.1 = {}".format(advertised_host)
    except ValueError:
        san = "DNS.1 = {}".format(advertised_host)
    return """[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = Divan temporary sync
[ext]
basicConstraints = critical,CA:FALSE
subjectAltName = @alt
[alt]
{}
""".format(san)


def _generate_with_openssl(
        cert_path: str, key_path: str, advertised_host: str,
        temp_dir: str) -> None:
    executable = shutil.which("openssl")
    if not executable:
        raise TLSUnavailableError(
            "Güvenli eşitleme için sertifika üreticisi bulunamadı.")
    config_path = os.path.join(temp_dir, "openssl.cnf")
    _write_private_file(
        config_path, _openssl_config(advertised_host).encode("utf-8"))
    try:
        subprocess.run([
            executable, "req", "-x509", "-newkey", "rsa:2048",
            "-sha256", "-nodes", "-days", "1",
            "-keyout", key_path, "-out", cert_path,
            "-config", config_path,
        ], check=True, stdin=subprocess.DEVNULL,
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
           timeout=30)
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o600)
    except (OSError, subprocess.SubprocessError) as error:
        raise TLSUnavailableError(
            "Güvenli eşitleme sertifikası üretilemedi.") from error


def generate_ephemeral_certificate(
        temp_dir: str, advertised_host: str) -> tuple[str, str, str]:
    """Create a per-session cert/key and return paths plus SHA-256 DER pin.

    cryptography is preferred and can be bundled with desktop distributions.
    A system openssl executable is the installation-free fallback. There is no
    plaintext or home-grown-AEAD fallback.
    """
    cert_path = os.path.join(temp_dir, "session-cert.pem")
    key_path = os.path.join(temp_dir, "session-key.pem")
    try:
        _generate_with_cryptography(cert_path, key_path, advertised_host)
    except ImportError:
        _generate_with_openssl(
            cert_path, key_path, advertised_host, temp_dir)
    try:
        with open(cert_path, "rt", encoding="ascii") as certificate_file:
            pem = certificate_file.read()
        der = ssl.PEM_cert_to_DER_cert(pem)
    except (OSError, ValueError) as error:
        raise TLSUnavailableError(
            "Güvenli eşitleme sertifikası doğrulanamadı.") from error
    return cert_path, key_path, hashlib.sha256(der).hexdigest()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that validates its leaf pin before HTTP bytes."""

    def __init__(
            self, host: str, port: int, cert_sha256: str,
            timeout: float):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # The per-session self-signed leaf is authenticated by its QR pin,
        # not by a public CA. Never use this context without the check below.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self._expected_pin = bytes.fromhex(cert_sha256)
        super().__init__(
            host, port=port, timeout=timeout, context=context)

    def connect(self):
        super().connect()
        try:
            certificate = self.sock.getpeercert(binary_form=True)
            supplied_pin = hashlib.sha256(certificate or b"").digest()
            if not hmac.compare_digest(
                    supplied_pin, self._expected_pin):
                raise CertificatePinError(
                    "Eşitleme sertifikası QR koduyla uyuşmuyor.")
        except Exception:
            self.close()
            raise


def pinned_json_post(
        host: str, port: int, path: str, cert_sha256: str,
        value: Dict[str, Any], *, headers: Optional[Dict[str, str]] = None,
        timeout: float = 8.0,
        max_response_bytes: int = MAX_REQUEST_BYTES
        ) -> tuple[int, Dict[str, Any]]:
    """POST JSON after pinning the peer certificate, never before.

    This is also a reference for native clients: a generic "trust all"
    connection followed by an application check is unsafe if it can send the
    request first. Here `_PinnedHTTPSConnection.connect()` finishes and pins
    before `HTTPSConnection.request()` writes the request line or body.
    """
    safe_host = _safe_host(host)
    if (not isinstance(port, int) or isinstance(port, bool) or
            not 1 <= port <= 65535):
        raise ValueError("port is invalid")
    if (not isinstance(path, str) or
            not path.startswith("/") or len(path) > 128):
        raise ValueError("path is invalid")
    if not isinstance(cert_sha256, str) or not _HEX64_RE.fullmatch(
            cert_sha256):
        raise ValueError("certificate pin is invalid")
    body = _canonical_json(value)
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("request is too large")
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Content-Length": str(len(body)),
        "Host": _host_header(safe_host, port),
        "Connection": "close",
    }
    for key, item in (headers or {}).items():
        if "\r" in key or "\n" in key or "\r" in item or "\n" in item:
            raise ValueError("header is invalid")
        request_headers[str(key)] = str(item)
    connection = _PinnedHTTPSConnection(
        safe_host, port, cert_sha256, float(timeout))
    try:
        connection.request(
            "POST", path, body=body, headers=request_headers)
        response = connection.getresponse()
        length_header = response.getheader("Content-Length")
        if length_header:
            try:
                if int(length_header) > max_response_bytes:
                    raise SecureSyncError(
                        "Eşitleme yanıtı boyut sınırını aştı.")
            except ValueError:
                raise SecureSyncError(
                    "Eşitleme yanıt uzunluğu geçersiz.")
        raw = response.read(max_response_bytes + 1)
        if len(raw) > max_response_bytes:
            raise SecureSyncError(
                "Eşitleme yanıtı boyut sınırını aştı.")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SecureSyncError("Eşitleme yanıtı geçersiz.")
        if not isinstance(decoded, dict):
            raise SecureSyncError("Eşitleme yanıtı geçersiz.")
        return response.status, decoded
    finally:
        connection.close()


def _validated_invitation_payload(payload: Any) -> Dict[str, Any]:
    expected = {
        "v", "scheme", "host", "port", "session_id",
        "pairing_secret", "cert_sha256", "desktop_device_id",
        "expires_at", "path",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("invitation fields are invalid")
    if payload["v"] != 1 or payload["scheme"] != "https":
        raise ValueError("invitation protocol is unsupported")
    host = _safe_host(payload["host"])
    if (not isinstance(payload["port"], int) or
            isinstance(payload["port"], bool) or
            not 1 <= payload["port"] <= 65535):
        raise ValueError("invitation port is invalid")
    if payload["path"] != "/v1":
        raise ValueError("invitation path is invalid")
    if not _HEX64_RE.fullmatch(str(payload["cert_sha256"])):
        raise ValueError("invitation certificate pin is invalid")
    if not _HEX32_RE.fullmatch(str(payload["desktop_device_id"])):
        raise ValueError("invitation device id is invalid")
    if (not isinstance(payload["expires_at"], int) or
            isinstance(payload["expires_at"], bool)):
        raise ValueError("invitation expiry is invalid")
    if len(_b64url_decode(payload["session_id"], maximum=16)) != 16:
        raise ValueError("invitation session id is invalid")
    if len(_b64url_decode(payload["pairing_secret"], maximum=32)) != 32:
        raise ValueError("invitation pairing secret is invalid")
    validated = dict(payload)
    validated["host"] = host
    return validated


def parse_invitation(value: Any, *, require_unexpired: bool = True
                     ) -> Dict[str, Any]:
    """Parse a PairingInvitation, dict, DV1 code, URI or direct QR JSON."""
    if isinstance(value, PairingInvitation):
        payload = value.payload
    elif isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        compact = value.strip()
        if compact.startswith("divan://"):
            parsed = urllib.parse.urlsplit(compact)
            if parsed.scheme != "divan" or parsed.netloc != "sync":
                raise ValueError("pairing URI is invalid")
            parameters = urllib.parse.parse_qs(
                parsed.query, strict_parsing=True)
            if set(parameters) != {"data"} or len(parameters["data"]) != 1:
                raise ValueError("pairing URI is invalid")
            payload = decode_manual_code(parameters["data"][0])
        elif re.sub(r"\s+", "", compact).startswith(MANUAL_CODE_PREFIX):
            payload = decode_manual_code(compact)
        else:
            try:
                payload = json.loads(compact)
            except json.JSONDecodeError:
                raise ValueError("invitation is invalid")
    else:
        raise ValueError("invitation is invalid")
    validated = _validated_invitation_payload(payload)
    if require_unexpired and validated["expires_at"] <= int(time.time()):
        raise ValueError("invitation has expired")
    return validated


class PinnedSyncClient:
    """Generic client driver for the secure v1 transport.

    It keeps credentials only in memory. Its repr is intentionally redacted.
    Native clients should mirror these semantics rather than disabling TLS
    verification in a general-purpose HTTP stack.
    """

    def __init__(self, invitation: Any, *, timeout: float = 8.0):
        self._invitation = parse_invitation(invitation)
        self.timeout = max(1.0, min(float(timeout), 30.0))
        self._session_token: Optional[str] = None
        self._next_sequence = 1
        self._max_batch_bytes = MAX_BATCH_BYTES
        self._max_batch_items = MAX_BATCH_ITEMS
        self._paired = False

    def __repr__(self) -> str:
        return (
            "PinnedSyncClient(host={!r}, port={!r}, "
            "credentials=<redacted>)"
        ).format(
            self._invitation["host"], self._invitation["port"])

    @property
    def peer_id(self) -> str:
        return str(self._invitation["desktop_device_id"])

    def _post(
            self, endpoint: str, value: Dict[str, Any], *,
            authenticated: bool = False) -> Dict[str, Any]:
        headers = {}
        if authenticated:
            if not self._session_token:
                raise SecureSyncError("Eşitleme oturumu henüz eşlenmedi.")
            headers["Authorization"] = "Bearer " + self._session_token
        status, response = pinned_json_post(
            self._invitation["host"],
            self._invitation["port"],
            self._invitation["path"] + endpoint,
            self._invitation["cert_sha256"],
            value,
            headers=headers,
            timeout=self.timeout,
        )
        if not 200 <= status < 300:
            message = response.get("error")
            if not isinstance(message, str) or len(message) > 160:
                message = "Eşitleme isteği reddedildi."
            raise SecureSyncError(message)
        return response

    def pair(
            self, *, device_id: str, public_key: bytes,
            name: str, platform: str) -> Dict[str, Any]:
        if self._paired:
            raise SecureSyncError("Eşitleme daveti zaten kullanıldı.")
        if not isinstance(public_key, bytes):
            raise TypeError("public_key must be bytes")
        response = self._post("/pair", {
            "session_id": self._invitation["session_id"],
            "pairing_secret": self._invitation["pairing_secret"],
            "device": {
                "id": device_id,
                "public_key": _b64url_encode(public_key),
                "name": name,
                "platform": platform,
            },
            "request_id": _b64url_encode(secrets.token_bytes(18)),
            "seq": 0,
        })
        token = response.get("session_token")
        if (not isinstance(token, str) or
                len(_b64url_decode(token, maximum=32)) != 32):
            raise SecureSyncError("Eşitleme oturum yanıtı geçersiz.")
        maximum_bytes = response.get("max_batch_bytes")
        maximum_items = response.get("max_batch_items")
        if (not isinstance(maximum_bytes, int) or
                isinstance(maximum_bytes, bool) or
                not 1 <= maximum_bytes <= MAX_BATCH_BYTES or
                not isinstance(maximum_items, int) or
                isinstance(maximum_items, bool) or
                not 1 <= maximum_items <= MAX_BATCH_ITEMS):
            raise SecureSyncError("Eşitleme sınırları geçersiz.")
        self._session_token = token
        self._max_batch_bytes = maximum_bytes
        self._max_batch_items = maximum_items
        self._paired = True
        # The one-time QR secret is no longer needed by the client.
        self._invitation["pairing_secret"] = "<consumed>"
        return response

    def post_batch(
            self, items: list, *, done: bool = False) -> Dict[str, Any]:
        if not self._paired or not self._session_token:
            raise SecureSyncError("Eşitleme oturumu henüz eşlenmedi.")
        if not isinstance(items, list):
            raise TypeError("items must be a list")
        if len(items) > self._max_batch_items:
            raise ValueError("batch has too many items")
        if len(_canonical_json(items)) > self._max_batch_bytes:
            raise ValueError("batch is too large")
        sequence = self._next_sequence
        response = self._post("/batch", {
            "request_id": _b64url_encode(secrets.token_bytes(18)),
            "seq": sequence,
            "batch": items,
            "complete": bool(done),
        }, authenticated=True)
        self._next_sequence += 1
        if response.get("complete") is True:
            self.close()
        return response

    def run_batches(
            self,
            client_next_batch: Callable[[Optional[Dict[str, Any]]],
                                        tuple[list, bool]],
            apply_result: Callable[[Dict[str, Any]], None], *,
            max_rounds: int = 10000) -> None:
        """Drain both peers, sending empty chunks while the host has more."""
        if not callable(client_next_batch) or not callable(apply_result):
            raise TypeError("batch callbacks must be callable")
        peer_result = None
        for _ in range(max(1, min(int(max_rounds), 10000))):
            items, client_done = client_next_batch(peer_result)
            if not isinstance(client_done, bool):
                raise TypeError("client done flag must be boolean")
            response = self.post_batch(items, done=client_done)
            result = response.get("result")
            if not isinstance(result, dict):
                raise SecureSyncError("Eşitleme batch yanıtı geçersiz.")
            apply_result(result)
            if response.get("complete") is True:
                return
            peer_result = result
        raise SecureSyncError("Eşitleme tur sınırını aştı.")

    def close(self) -> None:
        self._session_token = None


def pair_with_invitation(
        invitation: Any, *, device_id: str, public_key: bytes,
        name: str, platform: str, timeout: float = 8.0
        ) -> tuple[PinnedSyncClient, Dict[str, Any]]:
    client = PinnedSyncClient(invitation, timeout=timeout)
    response = client.pair(
        device_id=device_id, public_key=public_key,
        name=name, platform=platform)
    return client, response


class _SecureSyncHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, handler, transport):
        self.transport = transport
        self.tls_context = None
        super().__init__(address, handler, bind_and_activate=True)

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(10.0)
        return request, client_address

    def process_request(self, request, client_address):
        if not self.transport._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.transport._connection_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, client_address):
        secured_request = None
        try:
            if self.tls_context is None:
                return
            secured_request = self.tls_context.wrap_socket(
                request, server_side=True)
            self.finish_request(secured_request, client_address)
        except Exception:
            # TLS/HTTP parsing failures may contain attacker-controlled bytes.
            # Close without socketserver's default stderr traceback.
            pass
        finally:
            self.shutdown_request(secured_request or request)
            self.transport._connection_slots.release()


class _SecureSyncHandler(BaseHTTPRequestHandler):
    server_version = "DivanSecureSync/1"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Request lines, headers and failures can contain pairing material.
        return

    @property
    def transport(self):
        return self.server.transport

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        super().end_headers()

    def _json(self, value: Dict[str, Any], status: int = 200):
        body = _canonical_json(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int):
        self._json({"error": message}, status)

    def _read_json(self) -> Dict[str, Any]:
        content_type = (
            self.headers.get("Content-Type") or ""
        ).split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise TransportInputError(
                "yalnızca application/json kabul edilir", 415)
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except (TypeError, ValueError):
            raise TransportInputError("geçersiz içerik uzunluğu")
        if length <= 0:
            raise TransportInputError("boş istek gövdesi")
        if length > MAX_REQUEST_BYTES:
            raise TransportInputError("istek gövdesi çok büyük", 413)
        try:
            body = self.rfile.read(length)
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TransportInputError("geçersiz JSON")
        if not isinstance(value, dict):
            raise TransportInputError("JSON nesnesi bekleniyor")
        return value

    def _validate_envelope(self):
        if self.headers.get("Origin"):
            raise TransportInputError(
                "tarayıcı kaynaklı istek kabul edilmez", 403)
        expected = self.transport.expected_host_header
        supplied = (self.headers.get("Host") or "").strip().lower()
        if supplied != expected.lower():
            raise TransportInputError("sunucu adresi doğrulanamadı", 403)
        address = str(self.client_address[0]).split("%", 1)[0]
        try:
            peer = ipaddress.ip_address(address)
        except ValueError:
            raise TransportInputError("istemci adresi doğrulanamadı", 403)
        if not (peer.is_private or peer.is_link_local or peer.is_loopback):
            raise TransportInputError("yalnızca yerel ağ kabul edilir", 403)
        if time.monotonic() >= self.transport.deadline:
            raise TransportInputError("eşitleme daveti sona erdi", 410)

    def do_GET(self):
        self._error("bulunamadı", 404)

    def do_POST(self):
        try:
            self._validate_envelope()
            ip = str(self.client_address[0])
            if not self.transport._request_limiter.allow(ip):
                raise TransportInputError("çok fazla istek", 429)
            path = urllib.parse.urlsplit(self.path).path
            if path == "/v1/pair":
                if not self.transport._pair_limiter.allow(ip):
                    raise TransportInputError(
                        "çok fazla eşleme denemesi", 429)
                response = self.transport._pair(
                    self._read_json(), ip)
                self._json(response)
            elif path == "/v1/batch":
                response, complete = self.transport._batch(
                    self._read_json(),
                    self.headers.get("Authorization") or "",
                    ip,
                )
                self._json(response)
                if complete:
                    self.transport._schedule_stop()
            else:
                self._error("bulunamadı", 404)
        except TransportInputError as error:
            self._error(str(error), error.status)
        except Exception:
            # Callback and TLS internals must never disclose details or payloads.
            self._error("eşitleme isteği işlenemedi", 500)


class SecureSyncSession:
    """One peer, one secret and one five-minute TLS listener."""

    def __init__(
            self, advertised_host: str, desktop_device_id: str,
            on_batch: Callable[[list, PeerIdentity], Any], *,
            bind_host: str = "0.0.0.0", port: int = 0,
            ttl_seconds: int = DEFAULT_TTL_SECONDS,
            max_batch_bytes: int = MAX_BATCH_BYTES,
            max_batch_items: int = MAX_BATCH_ITEMS,
            certificate_factory: Callable[
                [str, str], tuple[str, str, str]
            ] = generate_ephemeral_certificate):
        self.advertised_host = _safe_host(advertised_host)
        try:
            advertised_address = ipaddress.ip_address(
                self.advertised_host)
        except ValueError:
            advertised_address = None
        if advertised_address is not None and advertised_address.version != 4:
            raise ValueError(
                "desktop secure sync v1 supports IPv4 addresses only")
        if not _HEX32_RE.fullmatch(str(desktop_device_id or "")):
            raise ValueError("desktop_device_id must be 32 lowercase hex chars")
        if not callable(on_batch):
            raise TypeError("on_batch must be callable")
        ttl_seconds = int(ttl_seconds)
        if ttl_seconds < 1 or ttl_seconds > MAX_TTL_SECONDS:
            raise ValueError("ttl_seconds must be between 1 and 300")
        self.desktop_device_id = desktop_device_id
        self.on_batch = on_batch
        self.bind_host = str(bind_host)
        self.requested_port = int(port)
        self.ttl_seconds = ttl_seconds
        self.max_batch_bytes = min(
            MAX_BATCH_BYTES, max(1, int(max_batch_bytes)))
        self.max_batch_items = min(
            MAX_BATCH_ITEMS, max(1, int(max_batch_items)))
        self.certificate_factory = certificate_factory
        self._lock = threading.RLock()
        self._connection_slots = threading.BoundedSemaphore(
            MAX_ACTIVE_REQUESTS)
        self._pair_limiter = _WindowRateLimiter(
            PAIR_ATTEMPTS_PER_MINUTE)
        self._request_limiter = _WindowRateLimiter(REQUESTS_PER_MINUTE)
        self._pairing_secret = bytearray(secrets.token_bytes(32))
        self._session_id = _b64url_encode(secrets.token_bytes(16))
        self._token_digest: Optional[bytes] = None
        self._peer: Optional[PeerIdentity] = None
        self._next_sequence = 1
        self._request_ids = set()
        self._server = None
        self._thread = None
        self._timer = None
        self._temporary_directory = None
        self._certificate_sha256 = None
        self._port = None
        self.deadline = float("inf")
        self.expires_at = None

    @property
    def running(self) -> bool:
        return self._server is not None and time.monotonic() < self.deadline

    @property
    def expected_host_header(self) -> str:
        if self._port is None:
            raise SecureSyncError("eşitleme dinleyicisi henüz açılmadı")
        return _host_header(self.advertised_host, self._port)

    def start(self) -> PairingInvitation:
        """Bind the separate LAN socket and return sensitive QR/manual data."""
        with self._lock:
            if self._server is not None:
                raise SecureSyncError("eşitleme dinleyicisi zaten açık")
            temporary_directory = tempfile.TemporaryDirectory(
                prefix="divan-sync-")
            try:
                cert_path, key_path, fingerprint = self.certificate_factory(
                    temporary_directory.name, self.advertised_host)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(cert_path, key_path)
                server = _SecureSyncHTTPServer(
                    (self.bind_host, self.requested_port),
                    _SecureSyncHandler, self)
                server.tls_context = context
            except Exception:
                temporary_directory.cleanup()
                raise
            self._temporary_directory = temporary_directory
            self._certificate_sha256 = fingerprint
            self._server = server
            self._port = int(server.server_address[1])
            self.deadline = time.monotonic() + self.ttl_seconds
            self.expires_at = int(time.time()) + self.ttl_seconds
            self._thread = threading.Thread(
                target=server.serve_forever,
                name="divan-secure-sync",
                daemon=True,
            )
            self._thread.start()
            self._timer = threading.Timer(self.ttl_seconds, self.stop)
            self._timer.daemon = True
            self._timer.start()
            return self.invitation()

    def invitation(self) -> PairingInvitation:
        with self._lock:
            if self._server is None or self._certificate_sha256 is None:
                raise SecureSyncError("eşitleme dinleyicisi açık değil")
            if self._peer is not None:
                raise SecureSyncError("eşleme daveti kullanıldı")
            payload = {
                "v": PROTOCOL_VERSION,
                "scheme": "https",
                "host": self.advertised_host,
                "port": self._port,
                "session_id": self._session_id,
                "pairing_secret": _b64url_encode(bytes(
                    self._pairing_secret)),
                "cert_sha256": self._certificate_sha256,
                "desktop_device_id": self.desktop_device_id,
                "expires_at": self.expires_at,
                "path": "/v1",
            }
            encoded = _b64url_encode(_canonical_json(payload))
            manual = MANUAL_CODE_PREFIX + encoded
            uri = "divan://sync?data=" + urllib.parse.quote(
                manual, safe="-_")
            return PairingInvitation(payload, manual, uri)

    def _pair(self, value: Dict[str, Any], address: str) -> Dict[str, Any]:
        expected = {
            "session_id", "pairing_secret", "device",
            "request_id", "seq",
        }
        if set(value) != expected:
            raise TransportInputError("eşleme isteği alanları geçersiz")
        if value.get("seq") != 0:
            raise TransportInputError("eşleme sırası geçersiz", 409)
        request_id = value.get("request_id")
        if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(
                request_id):
            raise TransportInputError("istek kimliği geçersiz")
        device = value.get("device")
        if not isinstance(device, dict) or set(device) != {
                "id", "public_key", "name", "platform"}:
            raise TransportInputError("cihaz kimliği geçersiz")
        device_id = device.get("id")
        if not isinstance(device_id, str) or not _HEX32_RE.fullmatch(
                device_id):
            raise TransportInputError("cihaz kimliği geçersiz")
        try:
            public_key = _b64url_decode(
                device.get("public_key"), maximum=2048)
        except ValueError:
            raise TransportInputError("cihaz anahtarı geçersiz")
        if len(public_key) < 32:
            raise TransportInputError("cihaz anahtarı geçersiz")
        name = device.get("name")
        platform = device.get("platform")
        if (not isinstance(name, str) or not name.strip() or
                len(name) > 64 or
                not isinstance(platform, str) or not platform.strip() or
                len(platform) > 32):
            raise TransportInputError("cihaz açıklaması geçersiz")
        try:
            supplied_secret = _b64url_decode(
                value.get("pairing_secret"), maximum=32)
        except ValueError:
            supplied_secret = b""
        supplied_session = value.get("session_id")
        with self._lock:
            if self._peer is not None:
                raise TransportInputError("eşleme daveti kullanıldı", 409)
            if (not isinstance(supplied_session, str) or
                    not hmac.compare_digest(
                        supplied_session, self._session_id) or
                    len(supplied_secret) != 32 or
                    not hmac.compare_digest(
                        supplied_secret, bytes(self._pairing_secret))):
                raise TransportInputError("eşleme doğrulanamadı", 401)
            fingerprint = hashlib.sha256(public_key).hexdigest()
            self._peer = PeerIdentity(
                device_id=device_id,
                fingerprint=fingerprint,
                name=name.strip(),
                platform=platform.strip(),
                address=address,
            )
            self._request_ids.add(request_id)
            for index in range(len(self._pairing_secret)):
                self._pairing_secret[index] = 0
            token = _b64url_encode(secrets.token_bytes(32))
            self._token_digest = hashlib.sha256(
                token.encode("ascii")).digest()
        return {
            "ok": True,
            "peer_id": self.desktop_device_id,
            "device_fingerprint": fingerprint,
            "session_token": token,
            "expires_at": self.expires_at,
            "max_batch_bytes": self.max_batch_bytes,
            "max_batch_items": self.max_batch_items,
        }

    def _batch(
            self, value: Dict[str, Any], authorization: str,
            address: str) -> tuple[Dict[str, Any], bool]:
        if set(value) != {"request_id", "seq", "batch", "complete"}:
            raise TransportInputError("batch isteği alanları geçersiz")
        if not authorization.startswith("Bearer "):
            raise TransportInputError("eşitleme oturumu doğrulanamadı", 401)
        token = authorization[7:]
        if len(token) > 128:
            raise TransportInputError("eşitleme oturumu doğrulanamadı", 401)
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        request_id = value.get("request_id")
        sequence = value.get("seq")
        batch = value.get("batch")
        complete = value.get("complete")
        if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(
                request_id):
            raise TransportInputError("istek kimliği geçersiz")
        if (not isinstance(sequence, int) or isinstance(sequence, bool) or
                sequence < 1):
            raise TransportInputError("batch sırası geçersiz")
        if not isinstance(batch, list):
            raise TransportInputError("batch liste olmalı")
        if len(batch) > self.max_batch_items:
            raise TransportInputError("batch çok fazla öğe içeriyor", 413)
        if not isinstance(complete, bool):
            raise TransportInputError("complete boolean olmalı")
        try:
            encoded_batch = _canonical_json(batch)
        except (TypeError, ValueError):
            raise TransportInputError("batch JSON olarak kodlanamıyor")
        if len(encoded_batch) > self.max_batch_bytes:
            raise TransportInputError("batch çok büyük", 413)
        with self._lock:
            if self._peer is None or self._token_digest is None:
                raise TransportInputError(
                    "eşitleme oturumu doğrulanamadı", 401)
            if (not hmac.compare_digest(digest, self._token_digest) or
                    not hmac.compare_digest(address, self._peer.address)):
                raise TransportInputError(
                    "eşitleme oturumu doğrulanamadı", 401)
            if (request_id in self._request_ids or
                    sequence != self._next_sequence):
                raise TransportInputError(
                    "tekrarlanan veya sırasız istek", 409)
            self._request_ids.add(request_id)
            self._next_sequence += 1
            peer = self._peer
        result = self.on_batch(batch, peer)
        try:
            encoded_result = _canonical_json(result)
        except (TypeError, ValueError):
            raise SecureSyncError("merge callback returned invalid JSON")
        if len(encoded_result) > self.max_batch_bytes:
            raise SecureSyncError("merge callback response is too large")
        host_has_more = (
            isinstance(result, dict) and result.get("more") is True)
        accepted_complete = complete and not host_has_more
        return {
            "ok": True,
            "result": result,
            "complete": accepted_complete,
        }, accepted_complete

    def _schedule_stop(self):
        timer = threading.Timer(0.1, self.stop)
        timer.daemon = True
        timer.start()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            timer = self._timer
            temporary_directory = self._temporary_directory
            self._server = None
            self._timer = None
            self._temporary_directory = None
            self.deadline = 0
            self._token_digest = None
            for index in range(len(self._pairing_secret)):
                self._pairing_secret[index] = 0
        if timer is not None and timer is not threading.current_thread():
            timer.cancel()
        if server is not None:
            server.shutdown()
            server.server_close()
        if temporary_directory is not None:
            temporary_directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()


def decode_manual_code(value: str) -> Dict[str, Any]:
    """Decode and strictly validate a DV1 manual invitation."""
    if not isinstance(value, str):
        raise ValueError("manual code must be text")
    compact = re.sub(r"\s+", "", value)
    if not compact.startswith(MANUAL_CODE_PREFIX):
        raise ValueError("manual code prefix is invalid")
    raw = _b64url_decode(
        compact[len(MANUAL_CODE_PREFIX):], maximum=2048)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("manual code payload is invalid")
    try:
        return _validated_invitation_payload(payload)
    except ValueError as error:
        raise ValueError("manual code payload is invalid") from error
