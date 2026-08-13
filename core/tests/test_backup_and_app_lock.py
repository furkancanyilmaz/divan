import base64
import os
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, PROJECT_DIR, app


class AppLockInterfaceSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(encoding="utf-8")

    def test_locked_startup_does_not_load_conversations_before_unlock(self):
        locked_branch = self.html[
            self.html.index("if(settings.pin_set){"):
            self.html.index("}finally{setAppState('idle');}")
        ]
        self.assertIn("enterAppLockedState();", locked_branch)
        self.assertIn("await loadUnlockedShell();", locked_branch)
        self.assertIn("if(r.status===423)enterAppLockedState();", self.html)
        self.assertIn("await loadUnlockedShell();", self.html[
            self.html.index("$('unlockBtn').onclick"):])

    def test_backup_and_export_verify_unlock_before_browser_navigation(self):
        self.assertIn('id="backupDownloadBtn"', self.html)
        self.assertIn('id="jsonExportBtn"', self.html)
        self.assertIn("await api('/api/profile');", self.html)
        self.assertIn("beginPrivateDownload('/api/backup')", self.html)
        self.assertIn("beginPrivateDownload('/api/export-json')", self.html)

    def test_restore_undo_is_visible_only_when_server_reports_a_snapshot(self):
        self.assertIn('id="restoreUndoBtn"', self.html)
        self.assertIn(
            "$('restoreUndoBtn').hidden=!r.restore_undo_available;",
            self.html)
        self.assertIn("api('/api/restore-undo',{confirm:true})", self.html)

    def test_new_pin_is_explained_and_validated_before_settings_request(self):
        self.assertIn('pattern="[0-9]{4,12}"', self.html)
        self.assertIn('maxlength="12"', self.html)
        self.assertIn('id="pinHint"', self.html)
        self.assertIn('id="pinError" role="alert"', self.html)
        self.assertIn("function validateNewPinInput(", self.html)
        self.assertIn("/^[0-9]{4,12}$/.test(pin)", self.html)
        handler = self.html[self.html.index("$('settingsSave').onclick"):
                            self.html.index("$('clearPin').onclick")]
        self.assertIn("const pin=validateNewPinInput();", handler)
        self.assertIn("if(pin===null)return;", handler)
        self.assertIn("pin,simple_mode:", handler)
        self.assertIn(
            "veritabanı ile indirilen yedekleri şifrelemez", self.html)

    def test_expired_or_backgrounded_locked_screen_clears_rendered_data(self):
        self.assertIn("async function verifyAppUnlockSession()", self.html)
        self.assertIn(
            "setInterval(verifyAppUnlockSession,60000);", self.html)
        self.assertIn(
            "document.visibilityState==='hidden'&&DivanNative.embedded",
            self.html)
        self.assertIn("enterAppLockedState();", self.html)


class BackupAndRestoreTests(HTTPTestCase):

    def test_snapshot_is_integrity_checked_and_contains_committed_wal_data(self):
        conv_id = self.conversation(title="WAL içindeki görüşme")
        self.messages(conv_id, 3, prefix="yedek")
        target = str(Path(self._tmp.name) / "snapshot.db")

        app.create_sqlite_snapshot(target)

        self.assertTrue(app.sqlite_integrity_ok(target))
        with sqlite3.connect(target) as copied:
            self.assertEqual(
                copied.execute(
                    "SELECT title FROM conversations WHERE id=?",
                    (conv_id,)).fetchone()[0],
                "WAL içindeki görüşme",
            )
            self.assertEqual(
                copied.execute(
                    "SELECT COUNT(*) FROM messages WHERE conv=?",
                    (conv_id,)).fetchone()[0],
                3,
            )

    def test_automatic_backup_is_best_effort(self):
        with mock.patch.object(
                app, "create_sqlite_snapshot",
                side_effect=OSError("disk dolu")):
            self.assertIsNone(app.automatic_backup())

    def test_session_refresh_can_update_an_existing_same_day_backup(self):
        conv_id = self.conversation(title="Aynı gün güncellenecek")
        target = app.automatic_backup()
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "İlk kopyadan sonraki mesaj", app.now()))

        refreshed = app.automatic_backup(refresh=True)

        self.assertEqual(refreshed, target)
        with sqlite3.connect(refreshed) as copied:
            self.assertEqual(
                copied.execute(
                    "SELECT content FROM messages WHERE conv=?",
                    (conv_id,)).fetchone()[0],
                "İlk kopyadan sonraki mesaj",
            )

    def test_downloaded_backup_is_a_complete_sqlite_database(self):
        conv_id = self.conversation(title="İndirilen yedek")
        self.messages(conv_id, 2)

        status, body, headers = self.request("GET", "/api/backup")

        self.assertEqual(status, 200)
        self.assertIsInstance(body, bytes)
        self.assertIn("attachment", headers["Content-Disposition"])
        downloaded = str(Path(self._tmp.name) / "downloaded.db")
        Path(downloaded).write_bytes(body)
        self.assertTrue(app.sqlite_integrity_ok(downloaded))
        with sqlite3.connect(downloaded) as copied:
            self.assertEqual(
                copied.execute(
                    "SELECT title FROM conversations WHERE id=?",
                    (conv_id,)).fetchone()[0],
                "İndirilen yedek",
            )

    def test_restore_keeps_persistent_undo_and_undo_restores_previous_data(self):
        conv_id = self.conversation(title="Yüklemeden önce")
        incoming = str(Path(self._tmp.name) / "incoming.db")
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET title='Yedekteki sürüm' WHERE id=?",
                (conv_id,),
            )
        app.create_sqlite_snapshot(incoming)
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET title='Yüklemeden önce' WHERE id=?",
                (conv_id,),
            )

        status, body, _ = self.request(
            "POST", "/api/restore",
            {"database": base64.b64encode(
                Path(incoming).read_bytes()).decode("ascii")},
        )

        self.assertEqual(status, 200, body)
        self.assertTrue(body["restore_undo_available"])
        undo = app.latest_restore_snapshot()
        self.assertTrue(undo)
        self.assertTrue(os.path.isfile(undo))
        self.assertTrue(app.sqlite_integrity_ok(undo))
        self.assertEqual(
            self.conversation_row(conv_id)["title"], "Yedekteki sürüm")

        status, body, _ = self.request(
            "POST", "/api/restore-undo", {"confirm": True})

        self.assertEqual(status, 200, body)
        self.assertEqual(
            self.conversation_row(conv_id)["title"], "Yüklemeden önce")

    def test_restore_interrupts_chat_jobs_and_closes_old_physical_stream(self):
        conv_id = self.conversation(title="Akışlı yedek")
        request, _ = app.begin_chat_request(
            conv_id, "Eski akış",
            request_id="chat-restore-active-1")
        with app.db() as conn:
            conn.execute(
                "UPDATE chat_requests SET status='running' "
                "WHERE request_id=?", (request["request_id"],))
            conn.execute(
                "UPDATE jobs SET status='running' WHERE id=?",
                (request["job"],))
        incoming = str(Path(self._tmp.name) / "running-incoming.db")
        app.create_sqlite_snapshot(incoming)

        class Response:
            closed = False

            def close(self):
                self.closed = True

        response = Response()
        event = app.chat_cancel_event(request["request_id"], create=True)
        app.register_chat_response(request["request_id"], response)

        app.restore_database_file(incoming)

        restored = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (request["request_id"],))
        job = self.row("SELECT * FROM jobs WHERE id=?", (request["job"],))
        self.assertTrue(event.is_set())
        self.assertTrue(response.closed)
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["error_code"], "database_restored")
        self.assertEqual(job["status"], "interrupted")
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_restore_rejects_non_divan_sqlite_without_touching_live_data(self):
        conv_id = self.conversation(title="Korunacak")
        other = str(Path(self._tmp.name) / "other.db")
        with sqlite3.connect(other) as conn:
            conn.execute("CREATE TABLE unrelated(value TEXT)")

        status, body, _ = self.request(
            "POST", "/api/restore",
            {"database": base64.b64encode(
                Path(other).read_bytes()).decode("ascii")},
        )

        self.assertEqual(status, 400)
        self.assertIn("Divan yedeği", body["error"])
        self.assertEqual(self.conversation_row(conv_id)["title"], "Korunacak")
        self.assertIsNone(app.latest_restore_snapshot())

    def test_multiple_restore_snapshots_in_one_second_keep_true_latest_order(self):
        conv_id = self.conversation(title="ilk")
        with mock.patch.object(
                app.time, "strftime", return_value="20260730-120000"):
            paths = []
            for title in ("bir", "iki", "üç"):
                with app.db() as conn:
                    conn.execute(
                        "UPDATE conversations SET title=? WHERE id=?",
                        (title, conv_id),
                    )
                paths.append(app.create_restore_snapshot())

        self.assertTrue(paths[0].endswith("-00.db"))
        self.assertTrue(paths[2].endswith("-02.db"))
        self.assertEqual(app.latest_restore_snapshot(), paths[2])
        with sqlite3.connect(paths[2]) as copied:
            self.assertEqual(
                copied.execute(
                    "SELECT title FROM conversations WHERE id=?",
                    (conv_id,)).fetchone()[0],
                "üç",
            )

    def test_retention_removes_backups_that_could_restore_expired_chats(self):
        conv_id = self.conversation(
            title="Süresi dolmuş",
            created="2020-01-01 10:00",
            updated="2020-01-01 10:00",
        )
        restore_snapshot = app.create_restore_snapshot()
        automatic = app.automatic_backup()
        self.assertTrue(os.path.isfile(restore_snapshot))
        self.assertTrue(os.path.isfile(automatic))
        app.set_setting("retention_days", "1")

        removed = app.enforce_retention_policy()

        self.assertEqual(removed, 1)
        self.assertIsNone(self.conversation_row(conv_id))
        self.assertIsNone(app.latest_restore_snapshot())
        self.assertFalse(os.path.exists(restore_snapshot))
        self.assertFalse(os.path.exists(automatic))


class AppLockTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self.pin = "2468"
        app.set_setting("pin_hash", app.pin_hash(self.pin))

    def test_lock_blocks_data_routes_but_leaves_catalog_and_unlock_public(self):
        for path in (
                "/api/conversations", "/api/profile", "/api/backup"):
            with self.subTest(path=path):
                status, body, _ = self.request("GET", path)
                self.assertEqual(status, 423)
                self.assertIn("kilitli", body["error"])

        status, settings, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertTrue(settings["pin_set"])
        for path in ("/api/therapists", "/api/philosophers", "/api/cases"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertEqual(status, 200)

        status, _, _ = self.request(
            "POST", "/api/settings", {"simple_mode": True})
        self.assertEqual(status, 423)

    def test_new_pin_requires_four_to_twelve_ascii_digits(self):
        cookie = self.unlock_cookie(self.pin)
        invalid = ("1", "123", "1234567890123", "12ab", "１２３４")
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                status, body, _ = self.request(
                    "POST", "/api/settings", {"pin": candidate},
                    headers={"Cookie": cookie})
                self.assertEqual(status, 400)
                self.assertIn("4–12", body["error"])

        status, body, _ = self.request(
            "POST", "/api/settings", {"pin": "123456"},
            headers={"Cookie": cookie})
        self.assertEqual(status, 200, body)
        self.assertTrue(
            app.pin_matches("123456", app.get_setting("pin_hash")))

    def test_unlock_cookie_opens_protected_routes_and_has_safe_attributes(self):
        cookie = self.unlock_cookie(self.pin)
        status, _, headers = self.request(
            "POST", "/api/unlock", {"pin": self.pin})

        self.assertEqual(status, 200)
        set_cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/", set_cookie)

        status, conversations, _ = self.request(
            "GET", "/api/conversations", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIsInstance(conversations, list)

    def test_unlock_is_rate_limited_after_five_failures(self):
        for attempt in range(1, app.APP_UNLOCK_MAX_FAILURES + 1):
            status, body, headers = self.request(
                "POST", "/api/unlock", {"pin": "yanlış"})
            if attempt < app.APP_UNLOCK_MAX_FAILURES:
                self.assertEqual(status, 200)
                self.assertFalse(body["ok"])
            else:
                self.assertEqual(status, 429)
                self.assertGreater(body["retry_after"], 0)
                self.assertIn("Retry-After", headers)

        status, body, _ = self.request(
            "POST", "/api/unlock", {"pin": self.pin})
        self.assertEqual(status, 429)
        self.assertFalse(body["ok"])

    def test_android_embedded_cookie_and_app_unlock_cookie_work_together(self):
        app.EMBEDDED_SESSION_TOKEN = "embedded-test-token"
        embedded = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)

        status, body, headers = self.request(
            "POST", "/api/unlock", {"pin": self.pin},
            headers={"Cookie": embedded})

        self.assertEqual(status, 200, body)
        unlocked = headers["Set-Cookie"].split(";", 1)[0]
        status, conversations, _ = self.request(
            "GET", "/api/conversations",
            headers={"Cookie": embedded + "; " + unlocked})
        self.assertEqual(status, 200)
        self.assertIsInstance(conversations, list)

    def test_authorized_restore_keeps_this_session_open_for_restored_pin(self):
        incoming = str(Path(self._tmp.name) / "locked-incoming.db")
        app.set_setting("pin_hash", app.pin_hash("restored-pin"))
        app.create_sqlite_snapshot(incoming)
        app.set_setting("pin_hash", app.pin_hash(self.pin))
        old_cookie = self.unlock_cookie(self.pin)

        status, body, headers = self.request(
            "POST", "/api/restore",
            {"database": base64.b64encode(
                Path(incoming).read_bytes()).decode("ascii")},
            headers={"Cookie": old_cookie},
        )

        self.assertEqual(status, 200, body)
        restored_cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, _ = self.request(
            "GET", "/api/conversations",
            headers={"Cookie": restored_cookie})
        self.assertEqual(status, 200)
        status, _, _ = self.request(
            "GET", "/api/conversations", headers={"Cookie": old_cookie})
        self.assertEqual(status, 423)
