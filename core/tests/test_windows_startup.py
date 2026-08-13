import importlib.util
import json
import unittest
from pathlib import Path

from support import HTTPTestCase, PROJECT_DIR, app


class WindowsStartupSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")

    def test_direct_file_open_explains_how_to_start_divan(self):
        self.assertIn("location.protocol==='file:'", self.html)
        self.assertIn("DIVAN_BASLAT.bat", self.html)
        self.assertIn("Divan henüz başlatılmadı", self.html)

    def test_current_clean_windows_package_has_stable_private_data_directory(self):
        package = (
            Path(PROJECT_DIR).parent /
            "windows-package-2026.07.30.1" / "Divan"
        )
        launcher = (package / "DIVAN_BASLAT.bat").read_text(
            encoding="utf-8")
        packaged_server = (
            package / "Sistem_Dosyalari" / "server.py"
        ).read_text(encoding="utf-8")

        self.assertIn('set "APP_VERSION=2026.07.30.2"', launcher)
        self.assertIn(r"%LOCALAPPDATA%\Divan-Anne", launcher)
        self.assertNotIn(r"DATA_DIR=%LOCALAPPDATA%\Divan-Temiz-2026.07.30.1",
                         launcher)
        self.assertIn("s.backup(d)", launcher)
        self.assertIn(
            r'set "MIGRATION_TMP=%DATA_DIR%\freud-migration.tmp.db"',
            launcher,
        )
        self.assertIn(
            r'move /Y "%MIGRATION_TMP%" "%DIVAN_DB_PATH%"',
            launcher,
        )
        self.assertIn("PRAGMA integrity_check", launcher)
        self.assertIn("call :QUARANTINE_CORRUPT_DB", launcher)
        self.assertIn(r'set "QUARANTINE_DB=%DATA_DIR%\freud-',
                      launcher)
        self.assertIn("if errorlevel 1 exit /b 1", launcher)
        for provider in (
                "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY", "LMSTUDIO_API_KEY"):
            self.assertIn('set "{}="'.format(provider), launcher)
        self.assertIn('VERSION = "2026.07.30.2"', packaged_server)
        self.assertFalse(list(package.rglob("*.db")))

    def test_current_windows_package_contains_runtime_portrait_catalog(self):
        package = (
            Path(PROJECT_DIR).parent /
            "windows-package-2026.07.30.1" / "Divan"
        )
        portrait_dir = package / "Sistem_Dosyalari" / "assets" / "portraits"
        manifest_path = portrait_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for master_id in ("freud", "socrates"):
            with self.subTest(master=master_id):
                record = manifest["portraits"][master_id]
                self.assertTrue((portrait_dir / record["file"]).is_file())

        server_path = package / "Sistem_Dosyalari" / "server.py"
        spec = importlib.util.spec_from_file_location(
            "divan_packaged_server_test", server_path)
        packaged = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packaged)
        self.assertIn("freud", packaged.PORTRAIT_CATALOG)
        self.assertIn("socrates", packaged.PORTRAIT_CATALOG)
        self.assertTrue(
            packaged.PORTRAIT_CATALOG["freud"]["url"].startswith(
                "/assets/portraits/"))


class StartupResponseTests(HTTPTestCase):

    def test_index_is_not_cached_between_package_versions(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Divan", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(app.VERSION, "2026.08.13.2")

    def test_backups_follow_the_configured_database_directory(self):
        self.assertEqual(
            Path(app.data_dir()).resolve(),
            Path(app.DB_PATH).resolve().parent,
        )
        app.automatic_backup()
        backups = list(
            (Path(app.data_dir()) / "yedekler").glob("freud-*.db"))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
