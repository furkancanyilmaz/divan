import json
import sqlite3
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app


class ReferralProvenanceTests(HTTPTestCase):

    def add_note(self, therapist, content, *, approved=1,
                 scope="therapist", sensitive=0, created=None):
        created = created or "2026-08-01 10:00"
        conv_id = self.conversation(
            therapist=therapist, title=content[:80],
            created=created, updated=created)
        with app.db() as connection:
            note_id = connection.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES(?,'terapi',?,?,?,?,?,?,?)",
                (
                    conv_id, therapist, content, created, approved, scope,
                    sensitive, created,
                ),
            ).lastrowid
        return note_id, conv_id

    def add_formulation(self, therapist, content, note_ids, *,
                        status="approved", scope="therapist", sensitive=0,
                        base=None, revision=1):
        stamp = "2026-08-02 11:00"
        with app.db() as connection:
            formulation_id = connection.execute(
                "INSERT INTO formulations("
                "mode,therapist,content,note_count,through_note_id,created,"
                "status,approved_at,scope,sensitive,user_edited,"
                "base_formulation,revision,stale,stale_reason,updated) "
                "VALUES('terapi',?,?,?,?,?,?,?,?,?,0,?,?,0,'',?)",
                (
                    therapist, content, len(note_ids),
                    max(note_ids) if note_ids else None, stamp, status,
                    stamp if status == "approved" else None, scope,
                    sensitive, base, revision, stamp,
                ),
            ).lastrowid
            for note_id in note_ids:
                connection.execute(
                    "INSERT INTO formulation_evidence("
                    "formulation,note,created) VALUES(?,?,?)",
                    (formulation_id, note_id, stamp),
                )
        return formulation_id

    def refer(self, letter, from_t="freud", to_t="jung"):
        with mock.patch.object(app, "ds_complete", return_value=letter):
            return self.request(
                "POST", "/api/refer", {"from": from_t, "to": to_t})

    def test_referral_records_complete_active_source_lineage_and_public_audit(self):
        old_evidence, _ = self.add_note(
            "freud", "formülasyonun eski ama etkin kaynak notu",
            created="2026-07-01 09:00")
        formulation_id = self.add_formulation(
            "freud", "ONAYLI-FORMÜLASYON", [old_evidence])
        recent_ids = []
        for index in range(8):
            note_id, _ = self.add_note(
                "freud", "ETKİN-HAM-NOT-{}".format(index),
                created="2026-08-{:02d} 10:00".format(index + 1))
            recent_ids.append(note_id)
        excluded = {
            "PENDING-ASLA": {"approved": 0},
            "PRIVATE-ASLA": {"scope": "private"},
            "EXCLUDED-ASLA": {"scope": "excluded"},
            "SENSITIVE-ASLA": {"sensitive": 1},
        }
        for content, options in excluded.items():
            self.add_note("freud", content, **options)

        captured = []

        def referral_model(messages, **_kwargs):
            captured.append(messages[-1]["content"])
            return "İZLENEBİLİR-SEVK"

        with mock.patch.object(app, "ds_complete", side_effect=referral_model):
            status, body, _ = self.request(
                "POST", "/api/refer", {"from": "freud", "to": "jung"})

        self.assertEqual(status, 200, body)
        self.assertEqual(body["letter"], "İZLENEBİLİR-SEVK")
        self.assertEqual(len(captured), 1)
        self.assertIn("ONAYLI-FORMÜLASYON", captured[0])
        for index in range(8):
            self.assertIn("ETKİN-HAM-NOT-{}".format(index), captured[0])
        for forbidden in excluded:
            self.assertNotIn(forbidden, captured[0])

        referral = self.row(
            "SELECT * FROM referrals ORDER BY id DESC LIMIT 1")
        self.assertEqual(referral["status"], "active")
        sources = self.rows(
            "SELECT * FROM referral_sources WHERE referral=? "
            "ORDER BY source_type,source_id", (referral["id"],))
        source_keys = {
            (row["source_type"], row["source_id"]) for row in sources}
        self.assertIn(("formulation", formulation_id), source_keys)
        self.assertIn(("note", old_evidence), source_keys)
        self.assertTrue(all(
            ("note", note_id) in source_keys for note_id in recent_ids))
        self.assertEqual(len(sources), 10)
        self.assertTrue(all(len(row["source_fingerprint"]) == 64
                            for row in sources))
        event = self.row(
            "SELECT * FROM referral_events WHERE referral=? ORDER BY id",
            (referral["id"],))
        self.assertEqual(event["action"], "created")
        self.assertEqual(event["after_status"], "active")

        status, letters, _ = self.request(
            "GET", "/api/letters?therapist=jung")
        self.assertEqual(status, 200, letters)
        public = letters["referrals"][0]
        self.assertTrue(public["active"])
        self.assertEqual(public["source_count"], 10)
        self.assertEqual(
            {(item["source_type"], item["source_id"])
             for item in public["sources"]}, source_keys)
        self.assertNotIn("source_fingerprint", public["sources"][0])

    def test_every_note_privacy_or_review_transition_invalidates_old_letter(self):
        transitions = (
            ("private", {"scope": "private"}),
            ("excluded", {"scope": "excluded"}),
            ("sensitive", {"sensitive": True}),
            ("rejected", {"approved": False}),
            ("deleted", {"action": "delete"}),
        )
        for index, (label, mutation) in enumerate(transitions):
            with self.subTest(transition=label):
                note_id, _ = self.add_note(
                    "freud", "KAYNAK-{}".format(label),
                    created="2026-08-10 10:{:02d}".format(index))
                target = self.conversation(
                    therapist="jung", title="Hedef " + label)
                letter = "SEVK-ARTIK-GÖRÜNMEZ-" + label
                status, created, _ = self.refer(letter)
                self.assertEqual(status, 200, created)
                referral_id = created["referral"]["id"]
                self.assertIn(letter, self.system_prompt(target))

                status, changed, _ = self.request(
                    "POST", "/api/note-control",
                    {"id": note_id, **mutation})
                self.assertEqual(status, 200, changed)

                referral = self.row(
                    "SELECT * FROM referrals WHERE id=?", (referral_id,))
                self.assertEqual(referral["status"], "invalidated")
                self.assertTrue(referral["invalidated_at"])
                self.assertTrue(referral["invalidation_reason"])
                self.assertNotIn(letter, self.system_prompt(target))
                source = self.row(
                    "SELECT * FROM referral_sources WHERE referral=? "
                    "AND source_type='note' AND source_id=?",
                    (referral_id, note_id))
                self.assertIsNotNone(source)
                event = self.row(
                    "SELECT * FROM referral_events WHERE referral=? "
                    "AND action='invalidated' ORDER BY id DESC LIMIT 1",
                    (referral_id,))
                self.assertIsNotNone(event)
                self.assertEqual(event["source_type"], "note")
                self.assertEqual(event["source_id"], note_id)

    def test_prompt_revalidation_catches_out_of_band_source_change(self):
        note_id, _ = self.add_note("freud", "DEĞİŞMEDEN-ÖNCE")
        target = self.conversation(therapist="jung")
        status, body, _ = self.refer("PARMAK-İZLİ-SEVK")
        self.assertEqual(status, 200, body)
        referral_id = body["referral"]["id"]

        # Simulate an old client or manual SQLite edit which bypasses the
        # normal note-control invalidation hook.
        with app.db() as connection:
            connection.execute(
                "UPDATE notes SET content='DEĞİŞTİRİLMİŞ-KAYNAK' WHERE id=?",
                (note_id,))

        prompt = self.system_prompt(target)

        self.assertNotIn("PARMAK-İZLİ-SEVK", prompt)
        referral = self.row(
            "SELECT * FROM referrals WHERE id=?", (referral_id,))
        self.assertEqual(referral["status"], "invalidated")
        self.assertEqual(
            referral["invalidation_reason"], "source_note_changed")

    def test_source_change_during_generation_prevents_stale_letter_commit(self):
        note_id, _ = self.add_note("freud", "MODEL-ÖNCESİ-KAYNAK")

        def mutate_while_generating(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE notes SET scope='private' WHERE id=?", (note_id,))
            return "KAYDEDİLMEMESİ-GEREKEN-SEVK"

        with mock.patch.object(
                app, "ds_complete", side_effect=mutate_while_generating):
            status, body, _ = self.request(
                "POST", "/api/refer", {"from": "freud", "to": "jung"})

        self.assertEqual(status, 409, body)
        self.assertIn("kaynağı değişti", body["error"])
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM referrals")["n"], 0)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM referral_sources")["n"], 0)

    def test_formulation_privacy_and_supersession_invalidate_derived_referrals(self):
        source_note, _ = self.add_note("freud", "FORMÜLASYON-KANITI")
        formulation_id = self.add_formulation(
            "freud", "FORMÜLASYON-SÜRÜM-1", [source_note])
        target = self.conversation(therapist="jung")
        status, body, _ = self.refer("FORMÜLASYON-SEVKİ")
        self.assertEqual(status, 200, body)
        referral_id = body["referral"]["id"]
        self.assertIn("FORMÜLASYON-SEVKİ", self.system_prompt(target))

        status, changed, _ = self.request(
            "POST", "/api/formulation-control", {
                "id": formulation_id, "action": "private",
            })
        self.assertEqual(status, 200, changed)
        self.assertNotIn("FORMÜLASYON-SEVKİ", self.system_prompt(target))
        invalidated = self.row(
            "SELECT * FROM referrals WHERE id=?", (referral_id,))
        self.assertEqual(invalidated["status"], "invalidated")
        event = self.row(
            "SELECT * FROM referral_events WHERE referral=? "
            "AND action='invalidated' ORDER BY id DESC LIMIT 1",
            (referral_id,))
        self.assertEqual(event["source_type"], "formulation")
        self.assertEqual(event["source_id"], formulation_id)

        # A separate active source shows that approving a successor retires
        # and invalidates letters derived from the old approved version.
        second_note, _ = self.add_note("adler", "ESKİ-SÜRÜM-KANITI")
        old_id = self.add_formulation(
            "adler", "ADLER-SÜRÜM-1", [second_note])
        status, second, _ = self.refer(
            "EMEKLİ-OLACAK-SEVK", from_t="adler", to_t="rogers")
        self.assertEqual(status, 200, second)
        second_referral_id = second["referral"]["id"]
        new_note, _ = self.add_note("adler", "YENİ-SÜRÜM-KANITI")
        child_id = self.add_formulation(
            "adler", "ADLER-SÜRÜM-2", [new_note], status="pending",
            base=old_id, revision=2)

        status, approved, _ = self.request(
            "POST", "/api/formulation-control", {
                "id": child_id, "action": "approve",
            })
        self.assertEqual(status, 200, approved)
        self.assertEqual(
            self.row(
                "SELECT status FROM formulations WHERE id=?", (old_id,)
            )["status"], "retired")
        second_referral = self.row(
            "SELECT * FROM referrals WHERE id=?", (second_referral_id,))
        self.assertEqual(second_referral["status"], "invalidated")
        self.assertIn("yeni bir sürüm", second_referral["invalidation_reason"])

    def test_legacy_referral_migrates_as_archived_unverified_not_prompt_context(self):
        legacy_path = Path(self._tmp.name) / "legacy-referral.db"
        app.DB_PATH = str(legacy_path)
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript("""
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
                    VALUES(7,'terapi',NULL,'Eski hedef seans',
                           '2025-01-01','2025-01-02');
                INSERT INTO referrals
                    VALUES(5,'jung','freud','ESKİ-İZSİZ-SEVK','2025-01-01');
            """)

        app.init_db()

        referral = self.row("SELECT * FROM referrals WHERE id=5")
        self.assertEqual(referral["status"], "legacy_unverified")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM referral_sources WHERE referral=5"
            )["n"], 0)
        migration_event = self.row(
            "SELECT * FROM referral_events WHERE referral=5")
        self.assertEqual(migration_event["action"], "migration_unverified")
        self.assertEqual(
            migration_event["after_status"], "legacy_unverified")
        self.assertNotIn("ESKİ-İZSİZ-SEVK", self.system_prompt(7))

        status, body, _ = self.request(
            "GET", "/api/letters?therapist=freud")
        self.assertEqual(status, 200, body)
        public = body["referrals"][0]
        self.assertEqual(public["status"], "legacy_unverified")
        self.assertFalse(public["active"])
        self.assertEqual(public["source_count"], 0)

    def test_export_and_delete_all_cover_provenance_without_copying_source_text(self):
        note_id, _ = self.add_note(
            "freud", "BU-METİN-SOY-TABLOSUNDA-KOPYALANMAMALI")
        status, created, _ = self.refer("ARŞİVLENEN-SEVK")
        self.assertEqual(status, 200, created)

        status, exported, _ = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200, exported)
        self.assertEqual(len(exported["data"]["referral_sources"]), 1)
        self.assertEqual(len(exported["data"]["referral_events"]), 1)
        source_payload = json.dumps(
            exported["data"]["referral_sources"], ensure_ascii=False)
        self.assertNotIn(
            "BU-METİN-SOY-TABLOSUNDA-KOPYALANMAMALI", source_payload)
        self.assertIn(str(note_id), source_payload)

        status, deleted, _ = self.request(
            "POST", "/api/delete-all",
            {"confirm": "TÜM VERİLERİ SİL"})
        self.assertEqual(status, 200, deleted)
        for table in ("referral_sources", "referral_events", "referrals"):
            self.assertEqual(
                self.row(
                    "SELECT COUNT(*) AS n FROM " + table)["n"], 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
