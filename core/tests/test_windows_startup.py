import importlib.util
import hashlib
import json
import re
import struct
import unittest
from pathlib import Path

from support import HTTPTestCase, PROJECT_DIR, app


SHARED_FILES = (
    "server.py", "index.html", "sync_engine.py", "sync_service.py",
    "secure_sync_transport.py", "sync_qr.py", "qrcodegen.py",
)
SECRET_RE = re.compile(
    rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


def strict_lossy_webp_size(raw):
    """Validate this deck's single-chunk WebP and return its dimensions."""
    if (len(raw) < 30 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP"
            or struct.unpack("<I", raw[4:8])[0] + 8 != len(raw)
            or raw[12:16] != b"VP8 "):
        raise AssertionError("not a strict lossy WebP container")
    chunk_length = struct.unpack("<I", raw[16:20])[0]
    if chunk_length < 10 or 20 + chunk_length + (chunk_length & 1) != len(raw):
        raise AssertionError("invalid WebP chunk length")
    frame = raw[20:20 + chunk_length]
    if frame[3:6] != b"\x9d\x01\x2a":
        raise AssertionError("invalid VP8 key frame")
    return (
        struct.unpack("<H", frame[6:8])[0] & 0x3FFF,
        struct.unpack("<H", frame[8:10])[0] & 0x3FFF,
    )


class WindowsStartupSourceTests(unittest.TestCase):

    PACKAGE_VERSION = "2026.08.17.5"

    @classmethod
    def package(cls):
        return (
            Path(PROJECT_DIR).parent /
            "windows-package-{}".format(cls.PACKAGE_VERSION) / "Divan"
        )

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")

    def test_direct_file_open_explains_how_to_start_divan(self):
        self.assertIn("location.protocol==='file:'", self.html)
        self.assertIn("DIVAN_BASLAT.bat", self.html)
        self.assertIn("Divan henüz başlatılmadı", self.html)

    def test_current_clean_windows_package_has_stable_private_data_directory(self):
        package = self.package()
        launcher = (package / "DIVAN_BASLAT.bat").read_text(
            encoding="utf-8")
        packaged_server = (
            package / "Sistem_Dosyalari" / "server.py"
        ).read_text(encoding="utf-8")
        readme = (package / "OKU_BENI.txt").read_text(encoding="utf-8")

        self.assertIn('set "APP_VERSION=2026.08.17.5"', launcher)
        self.assertIn("Sürüm 2026.08.17.5", readme)
        self.assertIn('set "CORE_VERSION=2026.08.15.1"', launcher)
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
        self.assertIn('VERSION = "2026.08.15.1"', packaged_server)
        self.assertIn('/api/adhd/dashboard', packaged_server)
        self.assertIn('/api/schema-path', packaged_server)
        forbidden_names = []
        for path in package.rglob("*"):
            if not path.is_file():
                continue
            folded = path.name.lower()
            if (folded.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm"))
                    or ".db-" in folded or folded.endswith(".device-id")
                    or folded in {"server.log", ".ds_store"}):
                forbidden_names.append(str(path.relative_to(package)))
        self.assertEqual(forbidden_names, [])

        for path in package.rglob("*"):
            if (path.is_file() and "python" not in path.parts
                    and path.suffix.lower() in {
                        ".py", ".html", ".json", ".txt", ".bat", ".md",
                    }):
                self.assertIsNone(
                    SECRET_RE.search(path.read_bytes()),
                    "secret-like material in {}".format(path),
                )

    def test_current_windows_package_is_exact_shared_source_snapshot(self):
        package_root = self.package() / "Sistem_Dosyalari"
        for name in SHARED_FILES:
            with self.subTest(name=name):
                self.assertEqual(
                    (package_root / name).read_bytes(),
                    Path(PROJECT_DIR, name).read_bytes(),
                )
        self.assertIn(
            'id="adhdWorkspaceOverlay"',
            (package_root / "index.html").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'id="schemaPathOverlay"',
            (package_root / "index.html").read_text(encoding="utf-8"),
        )

    def test_current_windows_package_contains_runtime_portrait_catalog(self):
        package = self.package()
        portrait_dir = package / "Sistem_Dosyalari" / "assets" / "portraits"
        source_dir = Path(PROJECT_DIR, "assets", "portraits")
        manifest_path = portrait_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        packaged_files = {
            path.name: path.read_bytes() for path in portrait_dir.iterdir()
            if path.is_file()
        }
        source_files = {
            path.name: path.read_bytes() for path in source_dir.iterdir()
            if path.is_file()
        }
        self.assertEqual(packaged_files, source_files)
        self.assertFalse(any(
            path.is_symlink() or path.is_dir() for path in portrait_dir.iterdir()
        ))
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

    def test_current_windows_package_contains_exact_bounded_imagery_deck(self):
        package_root = self.package() / "Sistem_Dosyalari"
        imagery_dir = package_root / "assets" / "imagery"
        source_dir = Path(PROJECT_DIR, "assets", "imagery")
        manifest_path = imagery_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        self.assertFalse(any(
            path.is_symlink() or path.is_dir() for path in imagery_dir.iterdir()
        ))

        packaged_files = {
            path.name: path.read_bytes() for path in imagery_dir.iterdir()
            if path.is_file()
        }
        source_files = {
            path.name: path.read_bytes() for path in source_dir.iterdir()
            if path.is_file()
        }
        self.assertEqual(packaged_files, source_files)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cards = manifest["cards"]
        self.assertEqual(manifest["card_count"], 24)
        self.assertEqual(len(cards), 24)
        self.assertEqual(manifest["therapist_allowlist"], ["freud"])
        self.assertEqual(manifest["presentation_policy"], {
            "descriptions_are_literal": True,
            "psychological_labels": False,
            "max_model_suggestions": 3,
            "suggestions_are_never_selected": True,
            "explicit_user_selection_required": True,
        })

        expected_files = {"manifest.json"}
        seen_ids = set()
        total_bytes = 0
        for card in cards:
            with self.subTest(card=card["id"]):
                card_id = card["id"]
                filename = card["file"]
                self.assertRegex(card_id, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertNotIn(card_id, seen_ids)
                seen_ids.add(card_id)
                self.assertEqual(filename, card_id + ".webp")
                self.assertEqual(Path(filename).name, filename)
                self.assertEqual(card["mime"], "image/webp")
                self.assertEqual((card["width"], card["height"]), (768, 512))
                self.assertRegex(card["sha256"], r"^[0-9a-f]{64}$")

                raw = packaged_files[filename]
                self.assertEqual(len(raw), card["bytes"])
                self.assertGreater(card["bytes"], 1000)
                self.assertLessEqual(card["bytes"], 500 * 1024)
                self.assertEqual(
                    hashlib.sha256(raw).hexdigest(), card["sha256"])
                self.assertEqual(strict_lossy_webp_size(raw), (768, 512))
                expected_files.add(filename)
                total_bytes += len(raw)

        self.assertEqual(set(packaged_files), expected_files)
        self.assertLessEqual(total_bytes, 8 * 1024 * 1024)

        server_path = package_root / "server.py"
        spec = importlib.util.spec_from_file_location(
            "divan_packaged_imagery_server_test", server_path)
        packaged = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packaged)
        self.assertEqual(set(packaged.IMAGERY_CATALOG), seen_ids)
        self.assertTrue(all(
            card["url"].startswith("/assets/imagery/")
            for card in packaged.IMAGERY_CATALOG.values()
        ))


class StartupResponseTests(HTTPTestCase):

    def test_index_is_not_cached_between_package_versions(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Divan", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(app.VERSION, "2026.08.15.1")

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
