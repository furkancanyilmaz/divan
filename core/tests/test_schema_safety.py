import sqlite3
from pathlib import Path
from unittest import mock

from support import DatabaseTestCase, HTTPTestCase, app


class SchemaAndTextTests(DatabaseTestCase):

    def test_fresh_schema_has_all_feature_tables_and_every_therapist_has_methods(self):
        tables = {
            row["name"] for row in self.rows(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({
            "memories", "session_summaries", "technique_runs", "jobs",
            "session_meta", "referrals",
        }.issubset(tables))
        self.assertEqual(set(app.THERAPISTS), set(app.THERAPY_METHODS))
        self.assertGreater(len(app.method_records("truth")), 0)
        self.assertEqual(app.method_records("truth")[0]["key"],
                         "truth:felt-sense")

    def test_legacy_schema_migrates_without_losing_user_summary(self):
        legacy_path = Path(self._tmp.name) / "legacy.db"
        app.DB_PATH = str(legacy_path)
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript("""
                CREATE TABLE conversations(
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, submode TEXT,
                    title TEXT, created TEXT, updated TEXT);
                CREATE TABLE notes(
                    id INTEGER PRIMARY KEY, conv INTEGER UNIQUE NOT NULL,
                    mode TEXT NOT NULL, content TEXT NOT NULL, created TEXT);
                CREATE TABLE highlights(
                    id INTEGER PRIMARY KEY, conv INTEGER NOT NULL,
                    therapist TEXT NOT NULL, text TEXT NOT NULL, created TEXT);
                CREATE TABLE referrals(
                    id INTEGER PRIMARY KEY, from_t TEXT NOT NULL,
                    to_t TEXT NOT NULL, content TEXT NOT NULL, created TEXT);
                CREATE TABLE session_meta(
                    conv INTEGER PRIMARY KEY, focus TEXT DEFAULT '',
                    mood_start INTEGER, mood_end INTEGER,
                    summary TEXT DEFAULT '', helpful TEXT DEFAULT '',
                    next_step TEXT DEFAULT '', updated TEXT);
                INSERT INTO conversations
                    VALUES(7,'terapi',NULL,'Eski seans','2025-01-01','2025-01-02');
                INSERT INTO notes
                    VALUES(3,7,'terapi','eski not','2025-01-02');
                INSERT INTO session_meta
                    VALUES(7,'odak',4,6,'kullanıcı özeti','','','2025-01-02');
            """)

        app.init_db()

        conv_columns = {
            row["name"] for row in self.rows(
                "SELECT name FROM pragma_table_info('conversations')")
        }
        note_columns = {
            row["name"] for row in self.rows(
                "SELECT name FROM pragma_table_info('notes')")
        }
        meta_columns = {
            row["name"] for row in self.rows(
                "SELECT name FROM pragma_table_info('session_meta')")
        }
        self.assertTrue(
            {"therapist", "ended", "source", "members", "source_mode",
             "case_id", "archived_at"}.issubset(conv_columns))
        self.assertTrue(
            {"therapist", "approved", "scope", "sensitive",
             "updated"}.issubset(note_columns))
        self.assertTrue(
            {"energy_start", "anxiety_start", "available_minutes",
             "intensity_limit", "avoid_topics", "preferred_pace",
             "safety_ok", "precheck_done"}.issubset(meta_columns))
        migrated = self.row(
            "SELECT * FROM session_summaries WHERE conv=7")
        self.assertEqual(migrated["status"], "approved")
        self.assertEqual(migrated["approved_content"], "kullanıcı özeti")
        self.assertEqual(
            self.row("SELECT content FROM notes WHERE id=3")["content"],
            "eski not")

    def test_transcript_uses_only_last_forty_messages_in_original_order(self):
        conv_id = self.conversation()
        self.messages(conv_id, 45)

        transcript = app.transcript_of(conv_id, "terapi")

        self.assertNotIn("mesaj-04", transcript)
        self.assertIn("mesaj-05", transcript)
        self.assertIn("mesaj-44", transcript)
        self.assertLess(transcript.index("mesaj-05"),
                        transcript.index("mesaj-44"))
        self.assertEqual(transcript.count("\n\n") + 1, 40)

    def test_stage_direction_filter_removes_narration_but_keeps_real_sentences(self):
        unwanted = (
            "Yavaşça, o itirafın ağırlığını tartarak: Bunu duymak zor.",
            "*Yavaşça, o çocuğun açlığını tartarak:* Burada kalalım.",
            "**Bir an sessiz kalıyorum, sonra yumuşakça:** Seni duyuyorum.",
        )
        for text in unwanted:
            with self.subTest(text=text):
                cleaned = app.strip_stage_opening(text)
                self.assertNotIn("tartarak", cleaned)
                self.assertNotIn("sessiz kalıyorum", cleaned)
        for text in (
            "Yavaşça konuşmayı deneyebilir misin?",
            "Bir an durup bunu düşünmek ister misin?",
            "Sesimi duymakta zorlanıyor musun?",
        ):
            with self.subTest(text=text):
                self.assertEqual(app.strip_stage_opening(text), text)

    def test_boolean_is_not_accepted_as_a_method_number(self):
        self.assertIsNone(app.method_record("freud", method_id=True))
        self.assertIsNone(app.method_record("freud", method_id=False))
        self.assertEqual(app.method_record("freud", method_id=1)["id"], 1)

    def test_invalid_concept_json_is_ignored_without_partial_writes(self):
        conv_id = self.conversation(mode="ders", submode="serbest")
        self.messages(conv_id, 4)
        with mock.patch("builtins.print"):
            for bad in ("{}", '["metin", 4, null]', "not-json"):
                with self.subTest(raw=bad), mock.patch.object(
                        app, "ds_complete", return_value=bad):
                    self.assertEqual(app.extract_concepts(conv_id), 0)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM concepts")["n"], 0)


class CrisisValidationTests(HTTPTestCase):

    def test_crisis_rejects_missing_and_closed_conversations_without_orphans(self):
        status, _, _ = self.request(
            "POST", "/api/chat",
            {"conv_id": 999999, "message": "Kendimi öldürmek istiyorum"})
        self.assertEqual(status, 404)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM messages")["n"], 0)

        closed = self.conversation(ended=1)
        status, _, _ = self.request(
            "POST", "/api/chat",
            {"conv_id": closed, "message": "Yaşamak istemiyorum"})
        self.assertEqual(status, 400)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM messages")["n"], 0)

    def test_crisis_flow_saves_fixed_help_message_without_model_or_network(self):
        conv_id = self.conversation()
        with mock.patch.object(app, "ds_request") as model_request:
            status, body, _ = self.request(
                "POST", "/api/chat",
                {"conv_id": conv_id, "message": "Yaşamak istemiyorum"})

        self.assertEqual(status, 200)
        self.assertTrue(body["crisis"])
        self.assertIn("112", body["message"])
        model_request.assert_not_called()
        saved = self.rows(
            "SELECT role,content FROM messages WHERE conv=? ORDER BY id",
            (conv_id,))
        self.assertEqual([row["role"] for row in saved],
                         ["user", "assistant"])
        self.assertIn("112", saved[1]["content"])


class RequestGuardTests(HTTPTestCase):

    def test_post_requires_json_and_rejects_external_host_or_origin(self):
        payload = {"mode": "terapi", "therapist": "freud"}
        status, _, _ = self.request(
            "POST", "/api/new", payload,
            headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

        status, _, _ = self.request(
            "POST", "/api/new", payload,
            headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

        status, _, _ = self.request(
            "POST", "/api/new", payload,
            headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM conversations")["n"], 0)

        local_origin = "http://127.0.0.1:{}".format(app.PORT)
        status, _, _ = self.request(
            "POST", "/api/new", payload,
            headers={"Origin": local_origin})
        self.assertEqual(status, 200)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM conversations")["n"], 1)
