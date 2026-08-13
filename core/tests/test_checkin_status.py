import sqlite3
from pathlib import Path

from support import DatabaseTestCase, HTTPTestCase, app


class CheckinStatusAPITests(HTTPTestCase):

    def post_checkin(self, **payload):
        return self.request("POST", "/api/checkin", payload)

    def test_each_status_value_is_independently_optional(self):
        conv_id = self.conversation()

        for field, value in (
                ("mood", 3), ("energy", 6), ("happiness", 8)):
            with self.subTest(field=field):
                status, body, _ = self.post_checkin(
                    conv_id=conv_id, **{field: value})
                self.assertEqual(status, 200, body)
                self.assertTrue(body["ok"])
                record = body["checkin"]
                self.assertEqual(record["conv_id"], conv_id)
                self.assertEqual(record[field], value)
                for other in {"mood", "energy", "happiness"} - {field}:
                    self.assertIsNone(record[other])

    def test_empty_records_and_out_of_range_or_ambiguous_values_are_rejected(self):
        for payload in ({}, {"note": ""}, {
                "mood": None, "energy": "", "happiness": " "}):
            with self.subTest(empty=payload):
                status, body, _ = self.post_checkin(**payload)
                self.assertEqual(status, 400, body)
                self.assertIn("en az bir", body["error"])

        for field in ("mood", "energy", "happiness", "anxiety"):
            for invalid in (0, 11, True, 4.5, "4.5", [], {}):
                with self.subTest(field=field, invalid=invalid):
                    status, body, _ = self.post_checkin(
                        **{field: invalid})
                    self.assertEqual(status, 400, body)
                    self.assertIn("1-10", body["error"])

        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM checkins")["n"], 0)

    def test_legacy_post_shape_and_numeric_mood_string_still_work(self):
        status, body, _ = self.post_checkin(
            mood="7", energy="4", anxiety="2", note="  eski istemci  ")

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        record = body["checkin"]
        self.assertIsNone(record["conv_id"])
        self.assertEqual(record["mood"], 7)
        self.assertEqual(record["energy"], 4)
        self.assertEqual(record["anxiety"], 2)
        self.assertEqual(record["note"], "eski istemci")
        self.assertIsNone(record["happiness"])

    def test_latest_get_supports_conversation_and_general_scopes(self):
        first = self.conversation(title="Birinci")
        second = self.conversation(title="İkinci")
        _, first_old, _ = self.post_checkin(conv_id=first, mood=2)
        _, first_new, _ = self.post_checkin(conv_id=first, energy=7)
        _, second_new, _ = self.post_checkin(
            conv_id=second, happiness=9)

        status, body, _ = self.request(
            "GET", "/api/checkin?conv_id={}".format(first))
        self.assertEqual(status, 200, body)
        self.assertEqual(body["scope"], "conversation")
        self.assertEqual(body["conv_id"], first)
        self.assertEqual(
            body["checkin"]["id"], first_new["checkin"]["id"])
        self.assertNotEqual(
            body["checkin"]["id"], first_old["checkin"]["id"])

        status, body, _ = self.request("GET", "/api/checkin")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["scope"], "general")
        self.assertIsNone(body["conv_id"])
        self.assertEqual(
            body["checkin"]["id"], second_new["checkin"]["id"])
        self.assertEqual(body["checkin"]["conv_id"], second)

    def test_latest_get_without_a_record_is_explicitly_empty(self):
        conv_id = self.conversation()

        status, body, _ = self.request(
            "GET", "/api/checkin?conv_id={}".format(conv_id))

        self.assertEqual(status, 200, body)
        self.assertEqual(body["scope"], "conversation")
        self.assertIsNone(body["checkin"])

    def test_invalid_or_missing_conversation_does_not_create_a_record(self):
        for conv_id, expected in (
                (0, 400), (True, 400), ("not-a-number", 400), (999999, 404)):
            with self.subTest(conv_id=conv_id):
                status, _, _ = self.post_checkin(
                    conv_id=conv_id, mood=5)
                self.assertEqual(status, expected)

        for path, expected in (
                ("/api/checkin?conv_id=0", 400),
                ("/api/checkin?conv_id=not-a-number", 400),
                ("/api/checkin?conv_id=999999", 404)):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertEqual(status, expected)

        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM checkins")["n"], 0)

    def test_deleting_conversation_keeps_status_as_an_unscoped_history_record(self):
        conv_id = self.conversation()
        status, body, _ = self.post_checkin(
            conv_id=conv_id, mood=5, happiness=6)
        self.assertEqual(status, 200, body)

        with app.db() as conn:
            conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))

        row = self.row("SELECT * FROM checkins")
        self.assertIsNone(row["conv"])
        self.assertEqual(row["mood"], 5)
        self.assertEqual(row["happiness"], 6)


class CheckinStatusMigrationTests(DatabaseTestCase):

    def test_legacy_required_mood_table_migrates_without_data_loss(self):
        legacy_path = Path(self._tmp.name) / "legacy-checkins.db"
        app.DB_PATH = str(legacy_path)
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript("""
                CREATE TABLE checkins(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mood INTEGER NOT NULL, energy INTEGER, anxiety INTEGER,
                    note TEXT DEFAULT '', created TEXT);
                INSERT INTO checkins(
                    id,mood,energy,anxiety,note,created)
                VALUES(12,7,3,4,'korunacak not','2026-01-02 03:04');
            """)

        app.init_db()

        columns = {
            row["name"]: row for row in self.rows(
                "SELECT * FROM pragma_table_info('checkins')")}
        self.assertTrue({
            "conv", "mood", "energy", "happiness", "anxiety",
            "note", "created",
        }.issubset(columns))
        self.assertEqual(columns["mood"]["notnull"], 0)
        migrated = self.row("SELECT * FROM checkins WHERE id=12")
        self.assertIsNone(migrated["conv"])
        self.assertEqual(migrated["mood"], 7)
        self.assertEqual(migrated["energy"], 3)
        self.assertIsNone(migrated["happiness"])
        self.assertEqual(migrated["anxiety"], 4)
        self.assertEqual(migrated["note"], "korunacak not")
        self.assertEqual(migrated["created"], "2026-01-02 03:04")

        # Migration can safely run again during restore/startup.
        app.init_db()
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM checkins")["n"], 1)
