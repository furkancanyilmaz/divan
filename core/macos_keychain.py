"""Small macOS Keychain adapter for Divan provider credentials.

Writes use ``security -i`` and feed a single, strictly constructed command on
standard input.  The password (represented as UTF-8 hex for ``-X``) therefore
never appears in a process argument or process listing.  A successful command
is not enough: every mutation is read back before this adapter acknowledges it.
"""

import hmac
import os
import re
import subprocess


SECURITY_TOOL = "/usr/bin/security"
DEFAULT_SERVICE = "com.furkancanyilmaz.divan.provider-credentials"
KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
SERVICE_RE = re.compile(r"[A-Za-z0-9._-]{1,200}\Z")


class KeychainError(RuntimeError):
    """Raised when Keychain is unavailable, locked, or denies access."""


def _service():
    value = (os.environ.get("DIVAN_KEYCHAIN_SERVICE") or
             DEFAULT_SERVICE).strip()
    # The service is embedded in security(1)'s stdin command, so only a small
    # shell/parser-neutral alphabet is accepted.  Account names are validated
    # independently below.
    if not SERVICE_RE.fullmatch(value):
        raise KeychainError("geçersiz Anahtar Zinciri hizmet adı")
    return value


def _validated_key(key):
    value = str(key or "").strip()
    if not KEY_RE.fullmatch(value):
        raise KeychainError("geçersiz gizli anahtar adı")
    return value


def _run(arguments, *, input_text=None):
    try:
        return subprocess.run(
            [SECURITY_TOOL] + list(arguments),
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeychainError("macOS Anahtar Zinciri kullanılamadı") from exc


def read_secret(key):
    """Return a secret or an empty string when that account does not exist."""
    account = _validated_key(key)
    result = _run([
        "find-generic-password", "-s", _service(), "-a", account, "-w",
    ])
    if result.returncode == 0:
        return result.stdout.rstrip("\r\n")
    diagnostic = (result.stderr or "").casefold()
    if result.returncode == 44 or "could not be found" in diagnostic:
        return ""
    raise KeychainError("Anahtar Zinciri girdisi okunamadı")


def write_secret(key, value):
    """Create/update a secret, or delete it when ``value`` is empty."""
    account = _validated_key(key)
    secret = str(value or "")
    if not secret:
        result = _run([
            "delete-generic-password", "-s", _service(), "-a", account,
        ])
        diagnostic = (result.stderr or "").casefold()
        if (result.returncode not in (0, 44) and
                "could not be found" not in diagnostic):
            raise KeychainError("Anahtar Zinciri girdisi silinemedi")
        if read_secret(account):
            raise KeychainError("Anahtar Zinciri girdisi silinemedi")
        return
    if len(secret) > 2000 or any(ord(ch) < 32 or ord(ch) == 127
                                for ch in secret):
        raise KeychainError("API anahtarı geçersiz")
    # `security add-generic-password -w` expects a password argument; merely
    # placing -w last is not a reliable stdin contract.  Interactive mode does
    # provide a documented stdin channel.  `-X` accepts the raw password bytes
    # as hex, preserving Unicode without quoting the secret itself.
    command = (
        "add-generic-password -U -s {} -a {} -X {}\n".format(
            _service(), account, secret.encode("utf-8").hex())
    )
    result = _run(["-i"], input_text=command)
    if result.returncode != 0:
        raise KeychainError("Anahtar Zinciri girdisi kaydedilemedi")
    persisted = read_secret(account)
    if not hmac.compare_digest(
            persisted.encode("utf-8"), secret.encode("utf-8")):
        raise KeychainError("Anahtar Zinciri yazımı doğrulanamadı")
