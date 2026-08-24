"""ADHD haftalık ritimleri ve dış beyin defteri sözleşmesi."""

import time

from support import HTTPTestCase, app


class ADHDHabitTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self.conv_id = self.conversation(therapist="adhd")

    def post(self, path, **payload):
        return self.request("POST", path, payload)

    def create_habit(self, request_id="habit-create-0001", **changes):
        payload = {
            "action": "create", "conv_id": self.conv_id,
            "request_id": request_id, "title": "Deftere yaz",
        }
        payload.update(changes)
        status, body, _ = self.post("/api/adhd/habits", **payload)
        self.assertEqual(status, 200, body)
        return body

    def schedule(self, habit_id, request_id="habit-schedule-0001",
                 offset=3600):
        status, body, _ = self.post(
            "/api/adhd/habits", action="schedule", conv_id=self.conv_id,
            habit_id=habit_id, request_id=request_id,
            scheduled_for=time.time() + offset)
        self.assertEqual(status, 200, body)
        return body

    def test_schema_default_weekly_target_and_preferred_time_never_schedules(self):
        created = self.create_habit(
            cue="Kahveden sonra", tiny_action="İki satır yaz",
            preferred_days=[1, 4], reminder_local_time="09:30",
            timezone="Europe/Istanbul")
        habit = created["habit"]
        self.assertEqual(habit["target_per_week"], 2)
        self.assertEqual(habit["preferred_days"], [1, 4])
        self.assertEqual(habit["reminder_local_time"], "09:30")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM reminders")["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM adhd_habit_events")["n"], 0)

    def test_habit_create_and_review_are_idempotent_and_never_auto_increase(self):
        first = self.create_habit()
        duplicate = self.create_habit()
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["habit"]["id"], first["habit"]["id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM adhd_habits")["n"], 1)

        habit_id = first["habit"]["id"]
        payload = dict(
            action="review", conv_id=self.conv_id, habit_id=habit_id,
            request_id="habit-review-0001", decision="increase")
        status, reviewed, _ = self.post("/api/adhd/habits", **payload)
        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed["habit"]["target_per_week"], 3)
        status, retried, _ = self.post("/api/adhd/habits", **payload)
        self.assertEqual(status, 200, retried)
        self.assertTrue(retried["duplicate"])
        self.assertEqual(retried["habit"]["target_per_week"], 3)

        with app.db() as conn:
            conn.execute(
                "UPDATE adhd_habits SET review_after=? WHERE id=?",
                (time.time() - 1, habit_id))
        status, dashboard, _ = self.request(
            "GET", "/api/adhd/dashboard?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 200, dashboard)
        self.assertIn(habit_id, dashboard["review_due"])
        self.assertIn("seri tutulmaz", dashboard["notices"]["no_streak"])
        self.assertIn("tanı", dashboard["notices"]["not_diagnostic"])

    def test_schedule_is_explicit_idempotent_and_reuses_reminder_delivery(self):
        habit_id = self.create_habit(tiny_action="Defteri aç")["habit"]["id"]
        first = self.schedule(habit_id)
        self.assertEqual(first["event"]["status"], "scheduled")
        self.assertEqual(first["reminder"]["source_conv"], self.conv_id)
        duplicate = self.schedule(habit_id)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["event"]["id"], first["event"]["id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM adhd_habit_events")["n"], 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM reminders")["n"], 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM scheduled_messages")["n"], 1)

    def test_start_now_creates_a_local_attempt_without_any_reminder(self):
        habit_id = self.create_habit(tiny_action="Defteri aç")["habit"]["id"]
        payload = dict(
            action="start_now", conv_id=self.conv_id, habit_id=habit_id,
            request_id="habit-start-now-0001")
        status, first, _ = self.post("/api/adhd/habits", **payload)
        self.assertEqual(status, 200, first)
        self.assertEqual(first["event"]["status"], "started")
        self.assertIsNone(first["event"]["reminder_id"])
        status, duplicate, _ = self.post("/api/adhd/habits", **payload)
        self.assertEqual(status, 200, duplicate)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["event"]["id"], first["event"]["id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM reminders")["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM scheduled_messages")["n"], 0)

    def test_request_ids_conflict_when_normalized_payload_changes(self):
        first = self.create_habit(
            request_id="habit-payload-0001", cue="Kahveden sonra",
            tiny_action="Bir satır", target_per_week=2)
        status, body, _ = self.post(
            "/api/adhd/habits", action="create", conv_id=self.conv_id,
            request_id="habit-payload-0001", title="Deftere yaz",
            cue="Kahveden sonra", tiny_action="Üç satır",
            target_per_week=4)
        self.assertEqual(status, 409, body)

        habit_id = first["habit"]["id"]
        status, _, _ = self.post(
            "/api/adhd/habits", action="pause", conv_id=self.conv_id,
            habit_id=habit_id, request_id="habit-state-0001")
        self.assertEqual(status, 200)
        status, body, _ = self.post(
            "/api/adhd/habits", action="archive", conv_id=self.conv_id,
            habit_id=habit_id, request_id="habit-state-0001")
        self.assertEqual(status, 409, body)

    def test_event_completion_and_legacy_reminder_answers_share_domain_state(self):
        habit_id = self.create_habit()["habit"]["id"]
        scheduled = self.schedule(habit_id)
        event_id = scheduled["event"]["id"]
        reminder_id = scheduled["reminder"]["id"]
        status, body, _ = self.post(
            "/api/adhd/events", action="partial", conv_id=self.conv_id,
            event_id=event_id, request_id="habit-partial-0001",
            effort_minutes=8, friction="start", note="İki satır yazdım")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["event"]["status"], "partial")
        reminder = self.row("SELECT * FROM reminders WHERE id=?", (reminder_id,))
        self.assertEqual(reminder["status"], "done")
        status, conflict, _ = self.post(
            "/api/adhd/events", action="done", conv_id=self.conv_id,
            event_id=event_id, request_id="habit-partial-0001",
            effort_minutes=8, friction="start", note="İki satır yazdım")
        self.assertEqual(status, 409, conflict)

        second = self.schedule(
            habit_id, request_id="habit-schedule-0002", offset=7200)
        status, _, _ = self.post(
            "/api/reminders", action="answer", id=second["reminder"]["id"],
            answer="yes")
        self.assertEqual(status, 200)
        event = self.row(
            "SELECT * FROM adhd_habit_events WHERE id=?",
            (second["event"]["id"],))
        self.assertEqual(event["status"], "done")

        third = self.schedule(
            habit_id, request_id="habit-schedule-0003", offset=10800)
        before = time.time()
        status, _, _ = self.post(
            "/api/reminders", action="answer", id=third["reminder"]["id"],
            answer="later", snooze_minutes=30)
        self.assertEqual(status, 200)
        event = self.row(
            "SELECT * FROM adhd_habit_events WHERE id=?",
            (third["event"]["id"],))
        self.assertEqual(event["status"], "scheduled")
        self.assertAlmostEqual(event["scheduled_for"], before + 1800, delta=10)

    def test_pause_cancels_future_events_without_shaming_or_streaks(self):
        habit_id = self.create_habit()["habit"]["id"]
        scheduled = self.schedule(habit_id)
        status, body, _ = self.post(
            "/api/adhd/habits", action="pause", conv_id=self.conv_id,
            habit_id=habit_id, request_id="habit-pause-0001")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["habit"]["status"], "paused")
        self.assertIn("seri tutulmaz", body["notices"]["no_streak"])
        event = self.row(
            "SELECT * FROM adhd_habit_events WHERE id=?",
            (scheduled["event"]["id"],))
        reminder = self.row(
            "SELECT * FROM reminders WHERE id=?",
            (scheduled["reminder"]["id"],))
        self.assertEqual(event["status"], "cancelled_user")
        self.assertEqual(reminder["status"], "cancelled_user")

    def test_endpoints_fail_closed_outside_open_main_adhd_scope(self):
        cases = [
            self.conversation(therapist="freud"),
            self.conversation(therapist="adhd", ended=1),
        ]
        with app.db() as conn:
            held = self.conversation(therapist="adhd")
            conn.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?", (held,))
        cases.append(held)
        for index, conv_id in enumerate(cases):
            status, _, _ = self.post(
                "/api/adhd/habits", action="create", conv_id=conv_id,
                request_id="closed-scope-{:04d}".format(index), title="Olmaz")
            self.assertIn(status, (409, 403), conv_id)

        app.set_setting("guest_mode", "1")
        guest = self.conversation(therapist="adhd")
        with app.db() as conn:
            conn.execute("UPDATE conversations SET is_guest=1 WHERE id=?", (guest,))
        status, _, _ = self.request(
            "GET", "/api/adhd/dashboard?conv_id={}".format(guest))
        self.assertEqual(status, 403)


class ADHDJournalTests(ADHDHabitTests):

    def test_journal_defaults_sensitive_private_and_rejects_unsafe_share(self):
        status, body, _ = self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-create-0001", content="Bugün iki satır yazdım")
        self.assertEqual(status, 200, body)
        entry = body["journal_entry"]
        self.assertTrue(entry["sensitive"])
        self.assertFalse(entry["share_with_coach"])
        self.assertIn("izlenmez", body["monitoring_notice"])

        status, rejected, _ = self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-create-0002", content="Paylaşılmamalı",
            sensitive=True, share_with_coach=True)
        self.assertEqual(status, 409, rejected)

    def test_journal_retry_rejects_changed_privacy_contract(self):
        payload = dict(
            action="create", conv_id=self.conv_id,
            request_id="journal-privacy-0001", content="Paylaşılan not",
            sensitive=False, share_with_coach=True)
        status, first, _ = self.post("/api/adhd/journal", **payload)
        self.assertEqual(status, 200, first)
        payload.update(sensitive=True, share_with_coach=False)
        status, body, _ = self.post("/api/adhd/journal", **payload)
        self.assertEqual(status, 409, body)

    def test_only_explicit_non_sensitive_journal_text_enters_coach_prompt(self):
        private_text = "ÖZEL-DEFTER-7788"
        shared_text = "PAYLASILAN-DEFTER-9911"
        self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-private-0001", content=private_text)
        status, _, _ = self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-shared-0001", content=shared_text,
            sensitive=False, share_with_coach=True)
        self.assertEqual(status, 200)
        prompt = self.system_prompt(self.conv_id)
        self.assertNotIn(private_text, prompt)
        self.assertIn(shared_text, prompt)
        self.assertIn("yalnız BAĞLAM VERİSİ", prompt)
        self.assertIn("acil olarak izlendiği anlamına gelmez", prompt)

    def test_journal_safety_gate_saves_entry_sets_hold_and_returns_real_support(self):
        habit_id = self.create_habit(
            request_id="habit-before-safety-0001")["habit"]["id"]
        scheduled = self.schedule(
            habit_id, request_id="schedule-before-safety-0001")
        status, body, _ = self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-safety-0001",
            content="Şu anda kendimi öldürmek istiyorum")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["safety"]["detected"])
        self.assertTrue(body["activities_paused"])
        self.assertEqual(
            body["paused_reminder_ids"], [scheduled["reminder"]["id"]])
        self.assertIn("112", body["safety"]["message"])
        self.assertIsNotNone(self.row(
            "SELECT * FROM adhd_journal_entries WHERE conv=?", (self.conv_id,)))
        self.assertEqual(self.conversation_row(self.conv_id)["safety_hold"], 1)
        self.assertEqual(self.row(
            "SELECT status FROM adhd_habits WHERE id=?", (habit_id,)
        )["status"], "paused")
        self.assertEqual(self.row(
            "SELECT status FROM adhd_habit_events WHERE id=?",
            (scheduled["event"]["id"],))["status"], "suppressed_safety")
        self.assertEqual(self.row(
            "SELECT status FROM reminders WHERE id=?",
            (scheduled["reminder"]["id"],))["status"], "suppressed_safety")

        status, retried, _ = self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-safety-0001",
            content="Şu anda kendimi öldürmek istiyorum")
        self.assertEqual(status, 200, retried)
        self.assertTrue(retried["duplicate"])
        status, deleted, _ = self.post(
            "/api/adhd/journal", action="delete", conv_id=self.conv_id,
            entry_id=body["journal_entry"]["id"],
            request_id="journal-safety-delete-0001")
        self.assertEqual(status, 200, deleted)
        status, _, _ = self.request(
            "GET", "/api/adhd/dashboard?conv_id={}".format(self.conv_id))
        self.assertEqual(status, 409)

    def test_safety_hold_suppresses_all_conversation_reminders(self):
        stamp = app.now()
        with app.db() as conn:
            reminder_id = conn.execute(
                "INSERT INTO reminders(task,due_at,status,answer,notified,"
                "is_guest,source_conv,created,updated) "
                "VALUES(?,?,'pending','',0,0,?,?,?)",
                ("zararlı olabilecek eski hatırlatıcı", time.time() - 5,
                 self.conv_id, stamp, stamp)).lastrowid
            app.record_safety_event(
                conn, self.conv_id,
                app.user_text_safety_gate(
                    "Şu anda kendimi öldürmek istiyorum"),
                detector_context="test")
        row = self.row("SELECT * FROM reminders WHERE id=?", (reminder_id,))
        self.assertEqual(row["status"], "suppressed_safety")
        self.assertEqual(row["answer"], "")

        app.EMBEDDED_SESSION_TOKEN = "native-adhd-safety"
        cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        status, response, _ = self.request(
            "POST", "/api/reminders/deliver", {"id": reminder_id},
            headers={"Cookie": cookie})
        self.assertEqual(status, 200, response)
        self.assertEqual(response["state"], "suppressed")
        self.assertFalse(response["reply_allowed"])
        self.assertFalse(response["preview_allowed"])
        self.assertNotIn("preview", response)

    def test_adhd_memory_is_user_visible_but_automatic_checkins_are_private(self):
        with app.db() as conn:
            conn.execute(
                "INSERT INTO memories(source_conv,therapist,kind,content,"
                "approved,scope,sensitive,created,updated) "
                "VALUES(?,'adhd','checkin_answer','sonuç',0,'therapist',1,?,?)",
                (self.conv_id, app.now(), app.now()))
        status, body, _ = self.request("GET", "/api/memories?therapist=adhd")
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["memories"]), 1)
        memory = body["memories"][0]
        self.assertFalse(memory["approved"])
        self.assertTrue(memory["sensitive"])

        reminder = self.schedule(
            self.create_habit(
                request_id="habit-memory-0001")["habit"]["id"],
            request_id="habit-memory-schedule-0001")
        with app.db() as conn:
            scheduled = conn.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (reminder["reminder"]["id"],)).fetchone()
            conn.execute(
                "UPDATE scheduled_messages SET content='Nasıl geçti?',"
                "status='ready' WHERE id=?", (scheduled["id"],))
            row = conn.execute(
                "SELECT * FROM reminders WHERE id=?",
                (reminder["reminder"]["id"],)).fetchone()
            app._insert_scheduled_checkin_memory(
                conn, scheduled, row, app.now())
        automatic = self.row(
            "SELECT * FROM memories WHERE kind='checkin' AND source_conv=?",
            (self.conv_id,))
        self.assertEqual(automatic["approved"], 0)
        self.assertEqual(automatic["sensitive"], 1)

    def test_conversation_and_delete_all_remove_module_and_linked_reminders(self):
        habit_id = self.create_habit()["habit"]["id"]
        self.schedule(habit_id)
        self.post(
            "/api/adhd/journal", action="create", conv_id=self.conv_id,
            request_id="journal-delete-0001", content="Silinecek")
        with app.db() as conn:
            app.delete_conversation_data(conn, self.conv_id)
        for table in (
                "adhd_habits", "adhd_habit_events", "adhd_journal_entries",
                "reminders", "scheduled_messages"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM " + table)["n"], 0, table)

        other = self.conversation(therapist="adhd")
        self.conv_id = other
        self.create_habit(request_id="habit-deleteall-0001")
        status, body, _ = self.post(
            "/api/delete-all", confirm="TÜM VERİLERİ SİL")
        self.assertEqual(status, 200, body)
        for table in (
                "adhd_habits", "adhd_habit_events", "adhd_journal_entries"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM " + table)["n"], 0, table)
