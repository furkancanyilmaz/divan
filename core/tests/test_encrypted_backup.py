import subprocess
import unittest

from support import HTTPTestCase, app


class EncryptedBackupTests(HTTPTestCase):

    def test_encrypted_backup_roundtrip(self):
        status, payload, headers = self.request(
            "POST", "/api/backup/encrypted",
            {"passphrase": "dogru-at-gunluk-sifre"})
        self.assertEqual(status, 200)
        self.assertTrue(payload.startswith(b"Salted__"))
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            enc = os.path.join(tmp, "yedek.enc")
            dec = os.path.join(tmp, "yedek.db")
            with open(enc, "wb") as fh:
                fh.write(payload)
            result = subprocess.run(
                ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
                 "-iter", "200000", "-pass",
                 "pass:dogru-at-gunluk-sifre", "-in", enc, "-out", dec],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(dec, "rb") as fh:
                header = fh.read(16)
            self.assertEqual(header, b"SQLite format 3\x00")

    def test_encrypted_backup_rejects_short_passphrase(self):
        status, body, _ = self.request(
            "POST", "/api/backup/encrypted", {"passphrase": "kisa"})
        self.assertEqual(status, 400)

    def test_wrong_passphrase_cannot_open_backup(self):
        status, payload, _ = self.request(
            "POST", "/api/backup/encrypted",
            {"passphrase": "dogru-at-gunluk-sifre"})
        self.assertEqual(status, 200)
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            enc = os.path.join(tmp, "yedek.enc")
            dec = os.path.join(tmp, "yedek.db")
            with open(enc, "wb") as fh:
                fh.write(payload)
            result = subprocess.run(
                ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
                 "-iter", "200000", "-pass",
                 "pass:yanlis-sifre-123", "-in", enc, "-out", dec],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
