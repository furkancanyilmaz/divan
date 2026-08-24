import re
import struct
import unittest
from pathlib import Path

from support import PROJECT_DIR, app


class MacOSPackagingSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project = Path(PROJECT_DIR)
        cls.build_script = (
            cls.project / "tools" / "build_macos_package.sh"
        ).read_text(encoding="utf-8")
        cls.launcher = (
            cls.project / "tools" / "macos" / "DivanLauncher.swift"
        ).read_text(encoding="utf-8")

    def test_release_and_server_versions_match(self):
        self.assertEqual(app.VERSION, "2026.08.15.1")
        self.assertIn('VERSION="2026.08.15.1"', self.build_script)

    def test_package_uses_an_explicit_runtime_allowlist(self):
        match = re.search(
            r"RUNTIME_FILES=\((?P<files>.*?)\n\)",
            self.build_script,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        files = set(re.findall(r"^\s+([A-Za-z0-9_.-]+)$",
                               match.group("files"), flags=re.MULTILINE))
        self.assertEqual(files, {
            "server.py", "index.html", "secure_sync_transport.py",
            "sync_engine.py", "sync_service.py", "sync_qr.py",
            "qrcodegen.py", "macos_keychain.py",
        })
        self.assertNotIn("freud.db", self.build_script)
        self.assertNotIn("yedekler/", self.build_script)
        self.assertIn('assets/imagery/manifest.json', self.build_script)
        self.assertIn('manifest.get("card_count") != 24', self.build_script)
        self.assertIn(
            'cp -R "${ROOT_DIR}/assets/imagery" '
            '"${RESOURCE_DIR}/assets/imagery"',
            self.build_script,
        )

    def test_launcher_keeps_mutable_data_outside_the_app_bundle(self):
        self.assertIn(".applicationSupportDirectory", self.launcher)
        self.assertIn('appendingPathComponent("Divan"', self.launcher)
        self.assertIn('environment["DIVAN_DB_PATH"]', self.launcher)
        self.assertIn('environment["DIVAN_NO_BROWSER"] = "1"', self.launcher)
        self.assertIn('processEnvironment["DIVAN_MAC_DATA_DIR"]',
                      self.launcher)
        self.assertIn('processEnvironment["DIVAN_MAC_PORT"]', self.launcher)
        self.assertIn('processEnvironment["DIVAN_MAC_NO_OPEN"]',
                      self.launcher)
        self.assertNotIn("Contents/Resources/Divan/freud.db", self.launcher)

    def test_launcher_authenticates_its_own_dynamic_server(self):
        self.assertIn('environment["DIVAN_SESSION_TOKEN"]', self.launcher)
        self.assertIn('environment["DIVAN_USE_KEYCHAIN"]', self.launcher)
        self.assertIn('environment["DIVAN_PRIVATE_FILES"]', self.launcher)
        self.assertIn('URLQueryItem(name: "_divan_session"', self.launcher)
        self.assertIn('Int.random(in: 49152...65535)', self.launcher)
        self.assertIn('RuntimeMetadata', self.launcher)
        self.assertIn('prior.version == version', self.launcher)
        self.assertIn('flock(lockDescriptor, LOCK_EX)', self.launcher)
        self.assertNotIn('return "8768"', self.launcher)

    def test_launcher_hardens_local_files_and_rotates_logs(self):
        self.assertGreaterEqual(self.launcher.count("0o700"), 2)
        self.assertGreaterEqual(self.launcher.count("0o600"), 3)
        self.assertIn("umask(0o077)", self.launcher)
        self.assertIn('5 * 1024 * 1024', self.launcher)
        self.assertIn('server.log.1', self.launcher)

    def test_build_creates_a_signed_app_zip_without_dmg(self):
        self.assertIn("xcrun swiftc", self.build_script)
        self.assertIn("lipo -create", self.build_script)
        self.assertIn("-verify_arch arm64 x86_64", self.build_script)
        self.assertIn("codesign --force --deep --sign -", self.build_script)
        self.assertIn("--options runtime --timestamp", self.build_script)
        self.assertIn("notarytool submit", self.build_script)
        self.assertIn("stapler staple", self.build_script)
        self.assertIn("codesign --verify --deep --strict", self.build_script)
        self.assertIn("ditto -c -k", self.build_script)
        self.assertNotIn("hdiutil", self.build_script)
        self.assertNotIn("DMG_PATH", self.build_script)
        self.assertIn("shasum -a 256", self.build_script)
        self.assertIn("API anahtarına benzeyen", self.build_script)

    def test_mac_icon_is_a_real_1024_pixel_png(self):
        icon = self.project / "assets" / "DivanAppIcon-1024.png"
        raw = icon.read_bytes()
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", raw[16:24])
        self.assertEqual((width, height), (1024, 1024))

    def test_server_can_suppress_browser_for_native_launcher(self):
        source = (self.project / "server.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("DIVAN_NO_BROWSER"', source)


if __name__ == "__main__":
    unittest.main()
