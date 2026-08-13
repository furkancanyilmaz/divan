import hmac
import importlib
import os
import subprocess
import sys
import unittest
import uuid
from unittest import mock

import macos_keychain


class MacOSKeychainTests(unittest.TestCase):

    def completed(self, code=0, stdout="", stderr=""):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    @mock.patch("macos_keychain.subprocess.run")
    def test_read_uses_system_keychain_without_secret_arguments(self, run):
        run.return_value = self.completed(stdout="secret-value\n")
        self.assertEqual(
            macos_keychain.read_secret("openai_api_key"), "secret-value")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[0], "/usr/bin/security")
        self.assertIn("find-generic-password", arguments)
        self.assertNotIn("secret-value", arguments)

    @mock.patch("macos_keychain.subprocess.run")
    def test_write_passes_secret_on_stdin_not_process_arguments(self, run):
        run.side_effect = [
            self.completed(),
            self.completed(stdout="very-secret\n"),
        ]
        macos_keychain.write_secret("deepseek_api_key", "very-secret")
        write_call = run.call_args_list[0]
        arguments = write_call.args[0]
        self.assertEqual(arguments, ["/usr/bin/security", "-i"])
        self.assertNotIn("very-secret", arguments)
        stdin_command = write_call.kwargs["input"]
        self.assertNotIn("very-secret", stdin_command)
        self.assertIn("766572792d736563726574", stdin_command)
        self.assertTrue(stdin_command.endswith("\n"))
        read_arguments = run.call_args_list[1].args[0]
        self.assertIn("find-generic-password", read_arguments)
        self.assertNotIn("very-secret", read_arguments)

    @mock.patch("macos_keychain.subprocess.run")
    def test_write_fails_when_keychain_does_not_read_back_exact_value(self,
                                                                     run):
        run.side_effect = [
            self.completed(),
            self.completed(stdout="different-value\n"),
        ]
        with self.assertRaises(macos_keychain.KeychainError):
            macos_keychain.write_secret("openai_api_key", "expected-value")

    @mock.patch("macos_keychain.subprocess.run")
    def test_missing_secret_is_empty_and_empty_write_deletes(self, run):
        missing = self.completed(
            code=44, stderr="The specified item could not be found")
        run.side_effect = [missing, missing, missing]
        self.assertEqual(macos_keychain.read_secret("anthropic_api_key"), "")
        macos_keychain.write_secret("anthropic_api_key", "")
        self.assertIn(
            "delete-generic-password", run.call_args_list[1].args[0])
        self.assertIn(
            "find-generic-password", run.call_args_list[2].args[0])

    def test_rejects_untrusted_account_names(self):
        with self.assertRaises(macos_keychain.KeychainError):
            macos_keychain.read_secret("--inject")

    @mock.patch.dict(
        "os.environ", {"DIVAN_KEYCHAIN_SERVICE": "bad service\nhelp"})
    def test_rejects_untrusted_service_names(self):
        with self.assertRaises(macos_keychain.KeychainError):
            macos_keychain.read_secret("openai_api_key")

    @unittest.skipUnless(
        sys.platform == "darwin"
        and os.environ.get("DIVAN_RUN_KEYCHAIN_INTEGRATION") == "1",
        "gerçek Anahtar Zinciri testi açıkça etkinleştirilmedi",
    )
    def test_real_keychain_round_trip_survives_adapter_restart(self):
        service = "com.furkancanyilmaz.divan.test." + uuid.uuid4().hex
        secret = ("integration-" + uuid.uuid4().hex).encode("utf-8")
        account = "openai_api_key"
        with mock.patch.dict(
                os.environ, {"DIVAN_KEYCHAIN_SERVICE": service}):
            try:
                macos_keychain.write_secret(account, secret.decode("utf-8"))
                restarted = importlib.reload(macos_keychain)
                persisted = restarted.read_secret(account).encode("utf-8")
                # Avoid an equality assertion whose failure renderer could
                # include the credential in test output.
                self.assertTrue(hmac.compare_digest(persisted, secret))
            finally:
                # The unique service keeps this test isolated; deletion plus
                # the adapter's empty read-back guarantees cleanup.
                macos_keychain.write_secret(account, "")


if __name__ == "__main__":
    unittest.main()
