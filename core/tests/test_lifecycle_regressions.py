import json
import threading
from unittest import mock

from support import HTTPTestCase, app


class LifecycleRegressionTests(HTTPTestCase):

    def _note(self, therapist, content, created="2026-07-20 10:00"):
        conv_id = self.conversation(
            therapist=therapist, title=content, created=created,
            updated=created)
        with app.db() as conn:
            conn.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,"
                "approved,scope,sensitive,updated) VALUES("
                "?,'terapi',?,?,?,1,'therapist',0,?)",
                (conv_id, therapist, content, created, created))
        return conv_id

    def test_referral_expires_after_two_notes_created_relative_to_referral_baseline(self):
        self._note("freud", "gönderen notu")
        for index in range(3):
            self._note("jung", "eski jung notu {}".format(index))
        current = self.conversation(therapist="jung", title="Sevk sonrası")

        with mock.patch.object(app, "ds_complete",
                               return_value="SEVK-MEKTUBU-ÖZEL"):
            status, body, _ = self.request(
                "POST", "/api/refer", {"from": "freud", "to": "jung"})
        self.assertEqual(status, 200)
        self.assertEqual(body["letter"], "SEVK-MEKTUBU-ÖZEL")
        referral = self.row("SELECT * FROM referrals ORDER BY id DESC LIMIT 1")
        self.assertEqual(referral["baseline_count"], 3)
        self.assertIn("SEVK-MEKTUBU-ÖZEL", self.system_prompt(current))

        self._note("jung", "sevk sonrası ilk not")
        self.assertIn("SEVK-MEKTUBU-ÖZEL", self.system_prompt(current))
        diagnostic = app.prompt_diagnostics(current)
        self.assertEqual(diagnostic["referral"]["notes_since"], 1)
        self.assertTrue(diagnostic["referral"]["active"])

        self._note("jung", "sevk sonrası ikinci not")
        self.assertNotIn("SEVK-MEKTUBU-ÖZEL", self.system_prompt(current))
        diagnostic = app.prompt_diagnostics(current)
        self.assertEqual(diagnostic["referral"]["notes_since"], 2)
        self.assertFalse(diagnostic["referral"]["active"])

    def test_retention_deletes_old_conversation_graph_but_keeps_recent_data(self):
        old = self.conversation(
            created="2000-01-01 00:00", updated="2000-01-02 00:00")
        recent = self.conversation(
            created="2999-01-01 00:00", updated="2999-01-02 00:00")
        stamp = "2000-01-02 00:00"
        with app.db() as conn:
            conn.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user','eski mesaj',?)", (old, stamp))
            conn.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,"
                "approved,scope,sensitive,updated) VALUES("
                "?,'terapi','freud','eski not',?,1,'therapist',0,?)",
                (old, stamp, stamp))
            conn.execute(
                "INSERT INTO letters(conv,therapist,content,created) "
                "VALUES(?,'freud','eski mektup',?)", (old, stamp))
            conn.execute(
                "INSERT INTO highlights(conv,therapist,text,context,created) "
                "VALUES(?,'freud','eski alıntı','seans',?)", (old, stamp))
            conn.execute(
                "INSERT INTO session_meta(conv,focus,updated) "
                "VALUES(?,'eski odak',?)", (old, stamp))
            conn.execute(
                "INSERT INTO session_summaries("
                "conv,draft,status,created,updated) "
                "VALUES(?,'eski taslak','pending',?,?)",
                (old, stamp, stamp))
            conn.execute(
                "INSERT INTO memories(source_conv,therapist,content,created,"
                "updated) VALUES(?,'freud','eski hafıza',?,?)",
                (old, stamp, stamp))
            conn.execute(
                "INSERT INTO technique_runs("
                "conv,therapist,method_key,method_name,status,created,updated) "
                "VALUES(?,'freud','freud:test','Test','stopped',?,?)",
                (old, stamp, stamp))
            conn.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('session_postprocess',?,'succeeded',?,?)",
                (old, stamp, stamp))
            conn.execute(
                "INSERT INTO referrals(from_t,to_t,content,created) "
                "VALUES('freud','jung','eski sevk',?)", (stamp,))
            conn.execute(
                "INSERT INTO checkins(mood,created) VALUES(5,?)", (stamp,))
        app.set_setting("retention_days", "30")

        deleted = app.enforce_retention_policy()

        self.assertEqual(deleted, 1)
        self.assertIsNone(self.conversation_row(old))
        self.assertIsNotNone(self.conversation_row(recent))
        for table, column in (
            ("messages", "conv"), ("notes", "conv"), ("letters", "conv"),
            ("highlights", "conv"), ("session_meta", "conv"),
            ("session_summaries", "conv"), ("technique_runs", "conv"),
            ("jobs", "conv"), ("memories", "source_conv"),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM {} WHERE {}=?".format(
                            table, column), (old,))["n"],
                    0)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM referrals")["n"], 0)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM checkins")["n"], 0)

        app.set_setting("retention_days", "bozuk")
        self.assertEqual(app.enforce_retention_policy(), 0)
        self.assertIsNotNone(self.conversation_row(recent))

    def test_export_contains_new_feature_data_but_never_credentials(self):
        app.set_setting("api_key", "DIŞARI-ÇIKMAMALI-API")
        pin = "DIŞARI-ÇIKMAMALI-PIN"
        app.set_setting("pin_hash", app.pin_hash(pin))
        app.set_setting("simple_mode", "1")
        conv_id = self.conversation()
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(therapist,content,created,updated) "
                "VALUES('freud','aktarılabilir hafıza',?,?)",
                (app.now(), app.now()))
            conn.execute(
                "INSERT INTO session_summaries(conv,draft,status,created,updated)"
                " VALUES(?,'taslak','pending',?,?)",
                (conv_id, app.now(), app.now()))

        status, body, headers = self.request(
            "GET", "/api/export-json",
            headers={"Cookie": self.unlock_cookie(pin)})

        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Pragma"], "no-cache")
        exported = body
        self.assertEqual(exported["version"], 6)
        self.assertIn("memories", exported["data"])
        self.assertIn("session_summaries", exported["data"])
        self.assertIn("technique_runs", exported["data"])
        self.assertIn("jobs", exported["data"])
        rendered = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("DIŞARI-ÇIKMAMALI-API", rendered)
        self.assertNotIn("DIŞARI-ÇIKMAMALI-PIN", rendered)
        setting_keys = {
            row["key"] for row in exported["data"]["settings"]}
        self.assertIn("simple_mode", setting_keys)
        self.assertNotIn("api_key", setting_keys)
        self.assertNotIn("pin_hash", setting_keys)

    def test_generated_note_waits_for_user_approval_before_entering_context(self):
        old_conv = self.conversation(title="Otomatik not kaynağı")
        self.messages(old_conv, app.NOTE_MIN_MESSAGES)
        with mock.patch.object(app, "ds_complete_continued",
                               return_value="ONAY-BEKLEYEN-OTOMATİK-NOT"):
            result = app.make_note(old_conv)
        self.assertEqual(result, "ONAY-BEKLEYEN-OTOMATİK-NOT")
        note = self.row("SELECT * FROM notes WHERE conv=?", (old_conv,))
        self.assertEqual(note["approved"], 0)

        next_conv = self.conversation(title="Sonraki seans")
        self.assertNotIn("ONAY-BEKLEYEN-OTOMATİK-NOT",
                         self.system_prompt(next_conv))

    def test_deleting_conversation_while_note_model_is_blocked_creates_no_orphan(self):
        conv_id = self.conversation(title="Silinecek")
        self.messages(conv_id, app.NOTE_MIN_MESSAGES)
        model_started = threading.Event()
        release_model = threading.Event()
        result = []

        def delayed_model(*_args, **_kwargs):
            model_started.set()
            self.assertTrue(release_model.wait(timeout=3))
            return "GEÇ-KALAN-NOT"

        with mock.patch.object(app, "ds_complete_continued",
                               side_effect=delayed_model):
            worker = threading.Thread(
                target=lambda: result.append(app.make_note(conv_id)))
            worker.start()
            self.assertTrue(model_started.wait(timeout=2))
            status, _, _ = self.request(
                "POST", "/api/delete", {"id": conv_id})
            self.assertEqual(status, 200)
            release_model.set()
            worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.conversation_row(conv_id))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM notes WHERE conv=?",
                (conv_id,))["n"],
            0)
        self.assertEqual(result, [None])

    def test_sensitive_records_never_enter_context_formulation_or_referral(self):
        secret = "HASSAS-KAYIT-ASLA-GÖNDERİLMEZ"
        safe = "gönderilebilir güvenli not"
        for index in range(app.FORMULATE_EVERY):
            conv_id = self.conversation(
                therapist="freud", title="Hassas {}".format(index))
            with app.db() as conn:
                conn.execute(
                    "INSERT INTO notes(conv,mode,therapist,content,created,"
                    "approved,scope,sensitive,updated) VALUES("
                    "?,'terapi','freud',?,?,1,'therapist',1,?)",
                    (conv_id, "{}-{}".format(secret, index),
                     "2026-07-20 10:00", "2026-07-20 10:00"))
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(therapist,content,approved,scope,"
                "sensitive,created,updated) VALUES("
                "'freud',?,1,'therapist',1,?,?)",
                (secret, app.now(), app.now()))

        current = self.conversation(therapist="freud")
        prompt = self.system_prompt(current)
        self.assertNotIn(secret, prompt)
        with mock.patch.object(app, "ds_complete") as formulate_model:
            self.assertFalse(app.maybe_formulate("terapi", "freud"))
        formulate_model.assert_not_called()

        safe_conv = self._note("freud", safe)
        captured = []

        def referral_model(messages, **_kwargs):
            captured.append(messages[-1]["content"])
            return "temiz sevk"

        with mock.patch.object(app, "ds_complete",
                               side_effect=referral_model):
            status, _, _ = self.request(
                "POST", "/api/refer", {"from": "freud", "to": "jung"})
        self.assertEqual(status, 200)
        self.assertEqual(len(captured), 1)
        self.assertIn(safe, captured[0])
        self.assertNotIn(secret, captured[0])
        self.assertIsNotNone(self.conversation_row(safe_conv))

    def test_deleting_conversation_also_removes_derived_concepts(self):
        conv_id = self.conversation(mode="ders", therapist="freud")
        with app.db() as conn:
            conn.execute(
                "INSERT INTO concepts(term,therapist,definition,conv,created) "
                "VALUES('Aktarım','freud','tanım',?,?)",
                (conv_id, app.now()))
        status, _, _ = self.request(
            "POST", "/api/delete", {"id": conv_id})
        self.assertEqual(status, 200)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM concepts WHERE conv=?",
                (conv_id,))["n"],
            0)
