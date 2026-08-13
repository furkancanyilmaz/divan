import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import PROJECT_DIR


NATIVE_PROJECT = Path(PROJECT_DIR).parent / "divan-macos-native"
VERIFY = NATIVE_PROJECT / "scripts" / "verify_package.sh"
PREPARE = NATIVE_PROJECT / "scripts" / "prepare_core.sh"
RUNTIME_FILES = (
    "server.py",
    "index.html",
    "secure_sync_transport.py",
    "sync_engine.py",
    "sync_service.py",
    "sync_qr.py",
    "qrcodegen.py",
    "macos_keychain.py",
)


@unittest.skipUnless(os.uname().sysname == "Darwin", "macOS package gate")
class NativeMacOSPackagingSecurityTests(unittest.TestCase):

    def run_script(self, script, *arguments, cwd=None):
        return subprocess.run(
            ["/bin/zsh", str(script), *map(str, arguments)],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_verifier_rejects_database_next_to_the_app_at_zip_root(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging"
            (staging / "Divan.app").mkdir(parents=True)
            (staging / "freud.db").write_bytes(b"SQLite format 3\x00")
            archive = root / "unsafe.zip"
            subprocess.run(
                ["/usr/bin/ditto", "-c", "-k", ".", str(archive)],
                cwd=staging,
                check=True,
            )

            result = self.run_script(VERIFY, archive)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("yalnızca tek bir Divan.app", result.stdout)

    def test_prepare_core_rejects_sqlite_content_masquerading_as_jpeg(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            portraits = source / "assets" / "portraits"
            portraits.mkdir(parents=True)
            for name in RUNTIME_FILES:
                (source / name).write_text("# test\n", encoding="utf-8")
            (portraits / "manifest.json").write_text("{}", encoding="utf-8")
            (portraits / "conversation-history.jpg").write_bytes(
                b"SQLite format 3\x00" + b"\x00" * 256
            )

            result = self.run_script(PREPARE, source, root / "prepared")

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("uzantısı ve içeriği uyuşmuyor", result.stdout)
            self.assertFalse((root / "prepared").exists())

    def test_verifier_rejects_sqlite_content_masquerading_as_jpeg(self):
        with tempfile.TemporaryDirectory() as raw:
            app = Path(raw) / "Divan.app"
            executable = app / "Contents" / "MacOS" / "Divan"
            core = app / "Contents" / "Resources" / "Divan"
            portraits = core / "assets" / "portraits"
            executable.parent.mkdir(parents=True)
            portraits.mkdir(parents=True)
            executable.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            (core / "server.py").write_text("# test\n", encoding="utf-8")
            (core / "macos_keychain.py").write_text("# test\n", encoding="utf-8")
            (portraits / "manifest.json").write_text("{}", encoding="utf-8")
            (portraits / "conversation-history.jpg").write_bytes(
                b"SQLite format 3\x00" + b"\x00" * 256
            )

            result = self.run_script(VERIFY, app)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("uzantısı ve içeriği uyuşmuyor", result.stdout)


if __name__ == "__main__":
    unittest.main()
