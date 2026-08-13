import sqlite3
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app


class MemoryCompactionTests(HTTPTestCase):

    def test_legacy_database_migrates_version_lineage_and_hold_audit_additively(self):
        legacy_path = Path(self._tmp.name) / "legacy-clinical.db"
        connection = sqlite3.connect(str(legacy_path))
        connection.executescript("""
            CREATE TABLE conversations(
                id INTEGER PRIMARY KEY, mode TEXT NOT NULL,
                title TEXT, created TEXT, updated TEXT,
                safety_hold INTEGER DEFAULT 0);
            CREATE TABLE messages(
                id INTEGER PRIMARY KEY, conv INTEGER, role TEXT,
                content TEXT, created TEXT);
            CREATE TABLE notes(
                id INTEGER PRIMARY KEY, conv INTEGER UNIQUE, mode TEXT,
                content TEXT, created TEXT);
            CREATE TABLE formulations(
                id INTEGER PRIMARY KEY, mode TEXT, therapist TEXT,
                content TEXT, note_count INTEGER, created TEXT);
            INSERT INTO conversations(
                id,mode,title,created,updated,safety_hold)
                VALUES(1,'terapi','Eski kayıt','2026-01-01','2026-01-01',1);
            INSERT INTO notes(id,conv,mode,content,created)
                VALUES(1,1,'terapi','Eski onaylı not','2026-01-01');
            INSERT INTO formulations(
                id,mode,therapist,content,note_count,created)
                VALUES(1,'terapi','freud','Eski formülasyon',1,'2026-01-01');
        """)
        connection.commit()
        connection.close()

        current_path = app.DB_PATH
        try:
            app.DB_PATH = str(legacy_path)
            app.init_db()
            with app.db() as conn:
                columns = {
                    row["name"] for row in conn.execute(
                        "PRAGMA table_info(formulations)")}
                event = conn.execute(
                    "SELECT * FROM safety_events WHERE conv=1").fetchone()
                evidence = conn.execute(
                    "SELECT * FROM formulation_evidence WHERE formulation=1"
                ).fetchone()
                conn.execute(
                    "DELETE FROM formulation_evidence WHERE formulation=1")
                preserved = conn.execute(
                    "SELECT * FROM formulations WHERE id=1").fetchone()
        finally:
            app.DB_PATH = current_path

        self.assertTrue({
            "base_formulation", "revision", "stale", "stale_reason",
            "superseded_at",
        }.issubset(columns))
        self.assertIsNotNone(event)
        self.assertEqual(event["kind"], "legacy_hold")
        self.assertEqual(event["status"], "active")
        self.assertIsNotNone(evidence)
        self.assertIsNotNone(preserved)

    def _approved_note(self, therapist, content, scope="therapist"):
        conv_id = self.conversation(
            mode="terapi", therapist=therapist, title=content)
        with app.db() as conn:
            return conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES("
                "?,'terapi',?,?,?,1,?,0,?)",
                (conv_id, therapist, content, app.now(), scope, app.now()),
            ).lastrowid

    def _first_formulation_over_thirteen_notes(self):
        note_ids = [
            self._approved_note("freud", "NOT-{:02d}".format(index))
            for index in range(1, 14)
        ]
        with mock.patch.object(
                app, "ds_complete", return_value="İLK-FORMÜLASYON") as model:
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        model.assert_called_once()
        return note_ids

    def test_formulation_covers_only_bounded_batch_and_keeps_remainder_in_context(self):
        note_ids = self._first_formulation_over_thirteen_notes()

        formulation = app.latest_formulation("terapi", "freud")
        self.assertEqual(formulation["note_count"], 12)
        self.assertEqual(formulation["through_note_id"], note_ids[11])

        current_id = self.conversation(
            mode="terapi", therapist="freud", title="Yeni seans")
        current = self.conversation_row(current_id)
        notes = app.context_notes(current, exclude_conv=current_id)

        # Taslak formülasyon sessizce hafıza sınırı olamaz; onay verilene
        # kadar ham, onaylı notların son bağlam penceresi görünür kalır.
        self.assertEqual(
            [row["id"] for row in notes], note_ids[-app.NOTES_LIMIT:])

        app.review_formulation({
            "id": formulation["id"], "action": "approve"})
        notes = app.context_notes(current, exclude_conv=current_id)
        self.assertEqual([row["id"] for row in notes], [note_ids[12]])
        self.assertEqual(notes[0]["content"], "NOT-13")

    def test_next_formulation_waits_until_a_complete_pending_batch_exists(self):
        note_ids = self._first_formulation_over_thirteen_notes()
        first = app.latest_formulation("terapi", "freud")
        app.review_formulation({"id": first["id"], "action": "approve"})

        with mock.patch.object(app, "ds_complete") as model:
            self.assertFalse(app.maybe_formulate("terapi", "freud"))
        model.assert_not_called()

        # FORMULATE_EVERY=3: ikinci formülasyon için 3 yeni onaylı not gerekir.
        for index in range(14, 15):
            self._approved_note("freud", "NOT-{:02d}".format(index))
            with mock.patch.object(app, "ds_complete") as model:
                self.assertFalse(app.maybe_formulate("terapi", "freud"))
            model.assert_not_called()

        final_note_id = self._approved_note("freud", "NOT-15")
        with mock.patch.object(
                app, "ds_complete", return_value="İKİNCİ-FORMÜLASYON") as model:
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        model.assert_called_once()

        formulation = app.latest_formulation("terapi", "freud")
        self.assertEqual(formulation["note_count"], 15)
        self.assertEqual(formulation["through_note_id"], final_note_id)
        self.assertGreater(formulation["through_note_id"], note_ids[11])

    def test_clip_context_text_preserves_opening_conclusion_and_limit(self):
        limit = 240
        original = "BAŞLANGIÇ-" + ("a" * 700) + "-SONUÇ"

        clipped = app.clip_context_text(original, limit)

        self.assertLessEqual(len(clipped), limit)
        self.assertTrue(clipped.startswith("BAŞLANGIÇ-"))
        self.assertTrue(clipped.endswith("-SONUÇ"))
        self.assertIn("kayıt bağlam için kısaltıldı", clipped)
        self.assertNotEqual(clipped, original)

    def test_transcript_keeps_newest_messages_inside_total_character_limit(self):
        conv_id = self.conversation(
            mode="ders", therapist="freud", title="Uzun ders")
        with app.db() as conn:
            for index in range(1, 9):
                content = (
                    "MESAJ-{:02d}-BAŞ ".format(index)
                    + (str(index) * 8990)
                    + " MESAJ-{:02d}-SON".format(index)
                )
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "user" if index % 2 else "assistant",
                     content, "2026-07-20 10:{:02d}".format(index)),
                )

        transcript = app.transcript_of(conv_id, "ders")

        self.assertLessEqual(len(transcript), app.TRANSCRIPT_CHAR_LIMIT)
        self.assertIn("MESAJ-08-BAŞ", transcript)
        self.assertIn("MESAJ-08-SON", transcript)
        self.assertNotIn("MESAJ-01-BAŞ", transcript)

    def test_other_masters_shared_note_survives_own_formulation_boundary(self):
        shared_id = self._approved_note(
            "freud", "FREUD-ORTAK-BAĞLAM", scope="shared")
        covered_own_id = self._approved_note(
            "jung", "JUNG-FORMÜLASYONDA-KAPSANDI")
        with app.db() as conn:
            formulation_id = conn.execute(
                "INSERT INTO formulations("
                "mode,therapist,content,note_count,through_note_id,created) "
                "VALUES('terapi','jung','Jung formülasyonu',1,?,?)",
                (covered_own_id, app.now()),
            ).lastrowid
            conn.execute(
                "INSERT INTO formulation_evidence("
                "formulation,note,created) VALUES(?,?,?)",
                (formulation_id, covered_own_id, app.now()),
            )

        current_id = self.conversation(
            mode="terapi", therapist="jung", title="Jung yeni seans")
        current = self.conversation_row(current_id)
        notes = app.context_notes(current, exclude_conv=current_id)

        self.assertEqual([row["id"] for row in notes], [shared_id])
        self.assertEqual(notes[0]["therapist"], "freud")
        self.assertEqual(notes[0]["scope"], "shared")
        self.assertEqual(notes[0]["content"], "FREUD-ORTAK-BAĞLAM")

    def test_pending_and_rejected_drafts_never_advance_approved_cursor(self):
        first_ids = [
            self._approved_note("freud", "İLK-{}".format(index))
            for index in range(app.FORMULATE_EVERY)
        ]
        with mock.patch.object(
                app, "ds_complete", return_value="REDDEDİLECEK-TASLAK"):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        rejected = app.latest_formulation("terapi", "freud")

        for index in range(app.FORMULATE_EVERY):
            self._approved_note("freud", "SONRAKİ-{}".format(index))
        with mock.patch.object(app, "ds_complete") as blocked:
            self.assertFalse(app.maybe_formulate("terapi", "freud"))
        blocked.assert_not_called()

        app.review_formulation({"id": rejected["id"], "action": "reject"})
        captured = []

        def complete(messages, **_kwargs):
            captured.extend(message["content"] for message in messages)
            return "YENİ-TASLAK"

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))

        corpus = "\n".join(captured)
        self.assertIn("İLK-0", corpus)
        self.assertIn("SONRAKİ-0", corpus)
        latest = app.latest_formulation("terapi", "freud")
        self.assertEqual(latest["note_count"], app.FORMULATE_EVERY * 2)
        self.assertGreaterEqual(latest["through_note_id"], first_ids[-1])
        self.assertIsNone(latest["base_formulation"])

    def test_approved_version_stays_active_until_successor_is_approved(self):
        for index in range(app.FORMULATE_EVERY):
            self._approved_note("freud", "TEMEL-{}".format(index))
        with mock.patch.object(app, "ds_complete", return_value="TEMEL-SÜRÜM"):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        base = app.latest_formulation("terapi", "freud")
        app.review_formulation({"id": base["id"], "action": "approve"})

        new_note_ids = [
            self._approved_note("freud", "YENİ-{}".format(index))
            for index in range(app.FORMULATE_EVERY)
        ]
        with mock.patch.object(app, "ds_complete", return_value="ADAY-SÜRÜM"):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        candidate = app.latest_formulation("terapi", "freud")

        self.assertEqual(
            app.latest_approved_formulation("terapi", "freud")["id"],
            base["id"])
        self.assertEqual(candidate["base_formulation"], base["id"])
        self.assertEqual(candidate["revision"], base["revision"] + 1)

        app.review_formulation({"id": candidate["id"], "action": "approve"})
        self.assertEqual(
            app.latest_approved_formulation("terapi", "freud")["id"],
            candidate["id"])
        with app.db() as conn:
            retired = conn.execute(
                "SELECT * FROM formulations WHERE id=?", (base["id"],)
            ).fetchone()
            evidence = conn.execute(
                "SELECT note FROM formulation_evidence WHERE formulation=? "
                "ORDER BY note", (candidate["id"],)).fetchall()
        self.assertEqual(retired["status"], "retired")
        self.assertIsNotNone(retired["superseded_at"])
        self.assertEqual([row["note"] for row in evidence], new_note_ids)

    def test_note_edit_marks_only_evidence_lineage_stale_without_deleting_it(self):
        base_note_ids = [
            self._approved_note("freud", "KANIT-{}".format(index))
            for index in range(app.FORMULATE_EVERY)
        ]
        with mock.patch.object(app, "ds_complete", return_value="TEMEL"):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        base = app.latest_formulation("terapi", "freud")
        app.review_formulation({"id": base["id"], "action": "approve"})
        for index in range(app.FORMULATE_EVERY):
            self._approved_note("freud", "EK-{}".format(index))
        with mock.patch.object(app, "ds_complete", return_value="ÇOCUK"):
            self.assertTrue(app.maybe_formulate("terapi", "freud"))
        child = app.latest_formulation("terapi", "freud")

        with (mock.patch.object(app, "start_job_worker"),
              mock.patch.object(app, "enqueue_job")):
            status, body, _ = self.request(
                "POST", "/api/note-control",
                {"id": base_note_ids[0], "content": "DÜZELTİLMİŞ-KANIT"})
        self.assertEqual(status, 200, body)

        with app.db() as conn:
            versions = conn.execute(
                "SELECT * FROM formulations WHERE id IN (?,?) ORDER BY id",
                (base["id"], child["id"])).fetchall()
        self.assertEqual(len(versions), 2)
        self.assertTrue(all(row["stale"] for row in versions))
        self.assertTrue(all(row["stale_reason"] for row in versions))
        self.assertIsNone(app.latest_approved_formulation("terapi", "freud"))
