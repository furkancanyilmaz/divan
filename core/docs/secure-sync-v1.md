# Divan secure LAN sync transport v1

This protocol is a separate, short-lived desktop listener. It must never be
implemented by changing the existing Divan chat server from loopback to a LAN
bind.

Desktop transport v1 advertises IPv4 LAN addresses only. IPv6 discovery and
scope-id handling are deferred rather than advertising an unreachable address.

## Lifecycle and trust

1. A visible user action creates a new listener for at most 300 seconds.
2. The desktop creates a new self-signed TLS certificate and a 256-bit pairing
   secret for that listener only.
3. The QR code carries the certificate SHA-256 fingerprint. The mobile client
   must compare that pin with the leaf certificate before sending any secret.
   System trust, hostname exceptions, cleartext fallback and "accept all"
   trust managers are forbidden.
4. One successful `/v1/pair` consumes and zeroes the pairing secret. A bearer
   token, stored only as a SHA-256 digest on desktop, is bound to the peer IP
   and device fingerprint for the remaining session.
5. Batch requests are sequential. Reused `request_id` values or any `seq`
   other than the exact next value are rejected.
6. `complete:true`, the deadline, or an explicit cancel closes the listener
   and removes its temporary certificate and key.

The QR code and manual code are credentials until they expire. They must not
be written to logs, analytics, crash reports, clipboard history, preferences,
or backups.

## Invitation schema

The QR may contain the compact JSON object directly or the `qr_uri` returned
by the desktop API. A manual fallback is the exact canonical JSON encoded as
unpadded base64url and prefixed with `DV1-`.

```json
{
  "v": 1,
  "scheme": "https",
  "host": "192.168.1.20",
  "port": 49152,
  "session_id": "<16 random bytes, base64url>",
  "pairing_secret": "<32 random bytes, base64url>",
  "cert_sha256": "<lowercase SHA-256 of leaf certificate DER>",
  "desktop_device_id": "<32 lowercase hex characters>",
  "expires_at": 1785400000,
  "path": "/v1"
}
```

## Pair

`POST https://host:port/v1/pair`, `Content-Type: application/json`, no
`Origin` header:

```json
{
  "session_id": "<from invitation>",
  "pairing_secret": "<from invitation>",
  "device": {
    "id": "<32 lowercase hex characters>",
    "public_key": "<Android Keystore public key DER, base64url>",
    "name": "<user-visible name, at most 64 characters>",
    "platform": "android"
  },
  "request_id": "<16-64 base64url characters>",
  "seq": 0
}
```

The response contains `session_token`, `peer_id`, `device_fingerprint`,
`expires_at`, `max_batch_bytes`, and `max_batch_items`. The public-key
fingerprint identifies the device but v1 does not claim hardware attestation.
The possession of the QR secret establishes the pairing.

## Batch

`POST /v1/batch` uses `Authorization: Bearer <session_token>`:

```json
{
  "request_id": "<new 16-64 base64url characters>",
  "seq": 1,
  "batch": [],
  "complete": false
}
```

The server accepts at most 100 items and 480 KiB of canonical batch JSON. The
outer HTTP request is capped at 512 KiB. The next request uses `seq:2`.
`complete:true` asks to close the listener after the response is sent. If the
host callback returns `{"more":true,...}`, the transport changes the response
to `complete:false` and stays open. A finished client must keep sending empty
batches until the host returns `more:false`; only then are both sides drained.

The `batch` contents and merge result are deliberately application-owned.
The transport calls `on_batch(batch, peer_identity)` and never imports into
SQLite itself. The application must run its existing strict transfer-bundle
validation before any write and must make its merge idempotent.

## Packaging

Python's standard `ssl` module can serve TLS but cannot create a certificate.
The implementation first uses `cryptography`, which desktop packages can
bundle so the end user installs nothing. It can alternatively use a system
`openssl` executable. If neither exists, secure sync fails closed; there is no
HTTP or custom-cryptography fallback. The current Windows portable runtime
must therefore bundle `cryptography` and its native wheel dependencies (or a
reviewed `openssl.exe`) before exposing the sync button.
