import json
import sqlite3
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app


class ConversationPinningTests(HTTPTestCase):

    def pin(self, conv_id, pinned=True, headers=None):
        return self.request(
            "POST", "/api/pin", {"id": conv_id, "pinned": pinned},
            headers=headers)

    def conversation_ids(self):
        status, rows, _ = self.request("GET", "/api/conversations")
        self.assertEqual(status, 200, rows)
        return [row["id"] for row in rows], rows

    def test_legacy_schema_backfills_pin_column_and_repairs_archived_pin(self):
        legacy_path = Path(self._tmp.name) / "legacy-pin.db"
        app.DB_PATH = str(legacy_path)
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript("""
                CREATE TABLE conversations(
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, submode TEXT,
                    title TEXT, created TEXT, updated TEXT);
                INSERT INTO conversations
                    VALUES(7,'terapi',NULL,'Eski sohbet',
                           '2025-01-01 10:00','2025-01-01 10:10');
            """)

        app.init_db()

        columns = {
            row["name"] for row in self.rows(
                "PRAGMA table_info(conversations)")
        }
        self.assertIn("pinned_at", columns)
        self.assertIsNone(self.conversation_row(7)["pinned_at"])

        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET archived_at=?,pinned_at=? "
                "WHERE id=7",
                ("2026-08-16 10:00", "2026-08-16 09:00"))
        app.init_db()
        self.assertIsNone(self.conversation_row(7)["pinned_at"])

    def test_pin_is_idempotent_and_active_list_is_stably_ordered(self):
        ended = self.conversation(
            ended=1, title="Bitmiş", updated="2026-08-16 13:00")
        active = self.conversation(
            ended=0, title="Açık", updated="2026-08-16 12:00")
        first_pin = self.conversation(
            ended=0, title="İlk sabit", updated="2026-08-16 09:00")
        second_pin = self.conversation(
            ended=1, title="Son sabit", updated="2026-08-16 08:00")

        with mock.patch.object(
                app, "now",
                side_effect=("2026-08-16 14:01", "2026-08-16 14:02")):
            status, first, _ = self.pin(first_pin)
            self.assertEqual(status, 200, first)
            status, second, _ = self.pin(second_pin)
            self.assertEqual(status, 200, second)

        self.assertTrue(first["pinned"])
        self.assertEqual(first["pinned_at"], "2026-08-16 14:01")
        self.assertEqual(second["pinned_at"], "2026-08-16 14:02")
        self.assertEqual(
            self.conversation_row(first_pin)["updated"],
            "2026-08-16 09:00")

        ids, rows = self.conversation_ids()
        self.assertEqual(ids, [first_pin, active, second_pin, ended])
        listed = {row["id"]: row for row in rows}
        self.assertEqual(
            listed[first_pin]["pinned_at"], "2026-08-16 14:01")

        status, repeated, _ = self.pin(first_pin)
        self.assertEqual(status, 200, repeated)
        self.assertEqual(repeated["pinned_at"], first["pinned_at"])

        status, unpinned, _ = self.pin(first_pin, False)
        self.assertEqual(status, 200, unpinned)
        self.assertFalse(unpinned["pinned"])
        self.assertIsNone(unpinned["pinned_at"])
        status, repeated_unpin, _ = self.pin(first_pin, False)
        self.assertEqual(status, 200, repeated_unpin)
        self.assertIsNone(repeated_unpin["pinned_at"])

    def test_archive_single_and_batch_clear_pins_atomically(self):
        first = self.conversation(title="Tekli")
        second = self.conversation(title="Toplu bir")
        third = self.conversation(title="Toplu iki")
        for conv_id in (first, second, third):
            status, body, _ = self.pin(conv_id)
            self.assertEqual(status, 200, body)

        status, body, _ = self.request(
            "POST", "/api/archive", {"id": first, "archived": True})
        self.assertEqual(status, 200, body)
        self.assertIsNone(self.conversation_row(first)["pinned_at"])

        status, body, _ = self.request(
            "POST", "/api/conversations/batch",
            {"action": "archive", "ids": [second, third]})
        self.assertEqual(status, 200, body)
        self.assertIsNone(self.conversation_row(second)["pinned_at"])
        self.assertIsNone(self.conversation_row(third)["pinned_at"])

        for conv_id in (first, second, third):
            status, body, _ = self.pin(conv_id)
            self.assertEqual(status, 409, body)
            self.assertIn("Arşivlenmiş", body["error"])

    def test_batch_pin_and_unpin_are_idempotent_and_all_or_nothing(self):
        first = self.conversation(title="Birinci")
        second = self.conversation(title="İkinci")
        archived = self.conversation(title="Arşiv")
        status, _, _ = self.request(
            "POST", "/api/archive", {"id": archived, "archived": True})
        self.assertEqual(status, 200)

        with mock.patch.object(app, "now", return_value="2026-08-16 15:00"):
            status, body, _ = self.request(
                "POST", "/api/conversations/batch",
                {"action": "pin", "ids": [first, second]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["action"], "pin")
        self.assertEqual(body["ids"], [first, second])
        self.assertTrue(body["pinned"])
        self.assertIsNone(body["archived"])
        self.assertEqual(
            self.conversation_row(first)["pinned_at"],
            "2026-08-16 15:00")
        self.assertEqual(
            self.conversation_row(second)["pinned_at"],
            "2026-08-16 15:00")

        status, body, _ = self.request(
            "POST", "/api/conversations/batch",
            {"action": "pin", "ids": [first, archived]})
        self.assertEqual(status, 409, body)
        self.assertEqual(
            self.conversation_row(first)["pinned_at"],
            "2026-08-16 15:00")
        self.assertIsNone(self.conversation_row(archived)["pinned_at"])

        status, body, _ = self.request(
            "POST", "/api/conversations/batch",
            {"action": "unpin", "ids": [second, first]})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["pinned"])
        self.assertIsNone(self.conversation_row(first)["pinned_at"])
        self.assertIsNone(self.conversation_row(second)["pinned_at"])

        status, repeated, _ = self.request(
            "POST", "/api/conversations/batch",
            {"action": "unpin", "ids": [first, second]})
        self.assertEqual(status, 200, repeated)
        self.assertFalse(repeated["pinned"])

    def test_pin_validates_shape_scope_lock_embedded_session_and_origin(self):
        normal = self.conversation(title="Normal")
        invalid_payloads = (
            {},
            {"id": normal},
            {"id": normal, "pinned": True, "extra": 1},
            {"id": True, "pinned": True},
            {"id": 0, "pinned": True},
            {"id": str(normal), "pinned": True},
            {"id": normal, "pinned": 1},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                status, _, _ = self.request("POST", "/api/pin", payload)
                self.assertEqual(status, 400)
        status, _, _ = self.pin(999999)
        self.assertEqual(status, 404)

        with app.db() as connection:
            guest = connection.execute(
                "INSERT INTO conversations("
                "mode,therapist,title,created,updated,is_guest) "
                "VALUES('terapi','freud','Misafir',?,?,1)",
                (app.now(), app.now())).lastrowid
        status, _, _ = self.pin(guest)
        self.assertEqual(status, 404)
        app.set_setting("guest_mode", "1")
        status, body, _ = self.pin(guest)
        self.assertEqual(status, 200, body)
        status, _, _ = self.pin(normal)
        self.assertEqual(status, 404)
        app.set_setting("guest_mode", "0")

        app.set_setting("pin_hash", app.pin_hash("1234"))
        status, _, _ = self.pin(normal)
        self.assertEqual(status, 423)
        cookie = self.unlock_cookie("1234")
        status, body, _ = self.pin(normal, headers={"Cookie": cookie})
        self.assertEqual(status, 200, body)
        app.set_setting("pin_hash", "")

        app.EMBEDDED_SESSION_TOKEN = "embedded-pin-test"
        status, _, _ = self.pin(normal, False)
        self.assertEqual(status, 403)
        embedded_cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        status, body, _ = self.pin(
            normal, False, headers={"Cookie": embedded_cookie})
        self.assertEqual(status, 200, body)
        status, _, _ = self.pin(normal, headers={
            "Cookie": embedded_cookie,
            "Origin": "https://example.invalid",
        })
        self.assertEqual(status, 403)

    def test_database_error_rolls_back_pin_and_returns_safe_failure(self):
        conv_id = self.conversation(title="Değişmeyecek")
        with app.db() as connection:
            connection.execute("""
                CREATE TRIGGER reject_pin BEFORE UPDATE OF pinned_at
                ON conversations WHEN NEW.id={}
                BEGIN SELECT RAISE(ABORT, 'private trigger detail'); END;
            """.format(conv_id))

        status, body, _ = self.pin(conv_id)

        self.assertEqual(status, 500, body)
        self.assertEqual(body["error"], "Raptiye durumu güncellenemedi.")
        self.assertNotIn("private trigger detail", json.dumps(body))
        self.assertIsNone(self.conversation_row(conv_id)["pinned_at"])

    def test_full_backup_preserves_pin_selective_transfer_does_not_and_delete_forgets(self):
        conv_id = self.conversation(title="Yaşam döngüsü")
        status, pinned, _ = self.pin(conv_id)
        self.assertEqual(status, 200, pinned)
        stamp = pinned["pinned_at"]

        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200, exported)
        exported_row = next(
            row for row in exported["data"]["conversations"]
            if row["id"] == conv_id)
        self.assertEqual(exported_row["pinned_at"], stamp)

        status, transfer, _ = self.request(
            "POST", "/api/transfer/export", {"ids": [conv_id]})
        self.assertEqual(status, 200, transfer)
        self.assertNotIn("pinned_at", transfer["conversations"][0])

        snapshot = str(Path(self._tmp.name) / "pinned-backup.db")
        app.create_sqlite_snapshot(snapshot)
        status, _, _ = self.pin(conv_id, False)
        self.assertEqual(status, 200)
        app.restore_database_file(snapshot)
        self.assertEqual(self.conversation_row(conv_id)["pinned_at"], stamp)

        status, body, _ = self.request(
            "POST", "/api/delete", {"id": conv_id})
        self.assertEqual(status, 200, body)
        self.assertIsNone(self.conversation_row(conv_id))
        status, rows, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200, rows)
        self.assertFalse(any(
            row["id"] == conv_id
            for row in rows["data"]["conversations"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
