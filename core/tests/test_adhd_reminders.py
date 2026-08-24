"""ADHD koç hatırlatıcıları için testler.

Kullanıcı "1 saat sonra X yapacağım" der; görev hatırlatıcısı kurulur,
süresi gelince 'due' olur, yanıtlanır, ertelenir, düzenlenir veya silinir.
"""

import time
from unittest import mock

from support import HTTPTestCase, app


class ADHDReminderTests(HTTPTestCase):

    def request_post(self, path, payload):
        return self.request("POST", path, payload)

    def native_post(self, path, payload):
        if not app.EMBEDDED_SESSION_TOKEN:
            app.EMBEDDED_SESSION_TOKEN = "native-reminder-test-session"
        cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        return self.request(
            "POST", path, payload, headers={"Cookie": cookie})

    def completed_notification_source(
            self, conv_id, request_id="notification-source-0001"):
        request, created = app.begin_chat_request(
            conv_id, "Bildirim kaynağı", request_id=request_id)
        self.assertTrue(created)
        with app.db() as c:
            assistant = c.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,?,?,?,'completed')",
                (conv_id, "assistant", "Tamamlanmış yanıt", app.now()))
            c.execute(
                "UPDATE chat_requests SET status='completed',"
                "assistant_message=?,finished=?,updated=? WHERE request_id=?",
                (assistant.lastrowid, app.now(), app.now(), request_id))
            c.execute(
                "UPDATE jobs SET status='succeeded',finished=?,updated=? "
                "WHERE id=?", (app.now(), app.now(), request["job"]))
        return request_id, assistant.lastrowid

    def create(self, task="Ödev teslimi", offset_seconds=3600):
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create",
            "task": task,
            "due_at": time.time() + offset_seconds,
        })
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        return body["reminder"]

    def test_adhd_persona_has_deepened_coaching_structure(self):
        """Koç promptu diğer ustalar gibi parmak izi + sınır taşımalı."""
        persona = app.COACHES["adhd"]["persona"]
        for heading in (
                "## Bu koçlukta senin parmak izin",
                "## Takılmanın yerini ayırt et",
                "## Nörobiyolojik dürüstlük",
                "## Utanç onarımı",
                "## Dışsallaştırma ilkesi",
                "## Küçük adım sözleşmesi"):
            self.assertIn(heading, persona)
        # Terapist parmak izlerindeki dört bölüm burada da olmalı.
        for label in ("Hamle:", "Ritim:", "İmza soru türü:", "Kaçın:"):
            self.assertIn(label, persona)
        # Koç tanı koymaz; klinik sınır korunmalı.
        self.assertIn("tanı", persona)
        self.assertIn("terapist veya doktor değilsin", persona)

    def test_adhd_persona_block_still_carries_shared_safety_tail(self):
        """Zenginleştirme ortak güvenlik kuyruğunu kaldırmamalı."""
        block = app.persona_block("adhd")
        self.assertIn(app.COACHES["adhd"]["persona"], block)
        self.assertIn(app.SHARED_TAIL, block)

    def test_adhd_coach_is_in_coach_catalog_not_clinical_catalog(self):
        status, body, _ = self.request("GET", "/api/coaches")
        self.assertEqual(status, 200)
        by_id = {row["id"]: row for row in body}
        self.assertIn("adhd", by_id)
        coach = by_id["adhd"]
        self.assertEqual(coach["name"], "ADHD Koçu")
        self.assertEqual(coach["kind"], "coach")
        self.assertEqual(coach["modes"], ["terapi", "ders"])
        self.assertNotIn("persona", coach)

        # Klinik kurucu kataloğuna karışmaz.
        status, therapists, _ = self.request("GET", "/api/therapists")
        self.assertEqual(status, 200)
        self.assertNotIn(
            "adhd", {row["id"] for row in therapists})
        self.assertTrue(app.is_coach("adhd"))
        self.assertTrue(app.known_master("adhd"))
        self.assertNotIn("adhd", app.ALL_MASTERS)
        self.assertNotIn("adhd", app.THERAPISTS)
        self.assertEqual(
            app.master_record("adhd", fallback=False)["name"], "ADHD Koçu")

    def test_reminders_reported_in_native_capabilities(self):
        status, body, _ = self.request("GET", "/api/v1/bootstrap")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["capabilities"].get("reminders"))
        self.assertEqual(
            body["capabilities"].get("notification_reply", {}).get(
                "version"), 1)

    def test_create_and_list_reminder(self):
        reminder = self.create("Raporu bitir", 7200)
        self.assertEqual(reminder["task"], "Raporu bitir")
        self.assertEqual(reminder["status"], "pending")
        self.assertFalse(reminder["notified"])

        status, body, _ = self.request("GET", "/api/reminders")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["reminders"]), 1)
        self.assertEqual(body["reminders"][0]["id"], reminder["id"])
        self.assertGreater(body["now"], 0)

    def test_overdue_reminder_becomes_due(self):
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Erken iş",
            "due_at": time.time() + 3600,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute("UPDATE reminders SET due_at=? WHERE id=?",
                      (time.time() - 5, rid))

        status, body, _ = self.request("GET", "/api/reminders")
        self.assertEqual(body["reminders"][0]["status"], "due")

        status, body, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual(len(body["due"]), 1)
        self.assertEqual(body["due"][0]["id"], rid)
        self.assertFalse(body["due"][0]["notified"])

    def test_notified_flag_removes_from_status_poll(self):
        reminder = self.create("Kontrol işi", 1800)
        rid = reminder["id"]
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET status='due',due_at=? WHERE id=?",
                (time.time() - 1, rid))

        status, body, _ = self.request_post("/api/reminders", {
            "action": "notified", "id": rid})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["reminder"]["notified"])

        status, body, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual(body["due"], [])

    def test_answer_yes_marks_done(self):
        reminder = self.create("Kısa iş", 900)
        status, body, _ = self.request_post("/api/reminders", {
            "action": "answer", "id": reminder["id"], "answer": "yes"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["reminder"]["status"], "done")
        self.assertEqual(body["reminder"]["answer"], "yes")
        self.assertTrue(body["reminder"]["notified"])

    def test_answer_no_marks_skipped(self):
        reminder = self.create("Ertelenen iş", 900)
        status, body, _ = self.request_post("/api/reminders", {
            "action": "answer", "id": reminder["id"], "answer": "no"})
        self.assertEqual(status, 200)
        self.assertEqual(body["reminder"]["status"], "skipped")
        self.assertEqual(body["reminder"]["answer"], "no")

    def test_answer_later_snoozes_within_bounds(self):
        reminder = self.create("Yarım kalan iş", 1200)
        before = time.time()
        status, body, _ = self.request_post("/api/reminders", {
            "action": "answer", "id": reminder["id"], "answer": "later",
            "snooze_minutes": 30})
        self.assertEqual(status, 200, body)
        value = body["reminder"]
        self.assertEqual(value["status"], "pending")
        self.assertEqual(value["answer"], "later")
        self.assertFalse(value["notified"])
        self.assertAlmostEqual(value["due_at"], before + 1800, delta=10)

        status, body, _ = self.request_post("/api/reminders", {
            "action": "answer", "id": reminder["id"], "answer": "later",
            "snooze_minutes": 1})
        self.assertEqual(status, 400)
        self.assertIn("erteleme", body["error"])

        status, body, _ = self.request_post("/api/reminders", {
            "action": "answer", "id": reminder["id"], "answer": "belki"})
        self.assertEqual(status, 400)

    def test_update_reschedules_and_resets_state(self):
        reminder = self.create("Eski görev", 3600)
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET status='due',notified=1 WHERE id=?",
                (reminder["id"],))
        status, body, _ = self.request_post("/api/reminders", {
            "action": "update", "id": reminder["id"], "task": "Yeni görev",
            "due_at": time.time() + 5400})
        self.assertEqual(status, 200, body)
        value = body["reminder"]
        self.assertEqual(value["task"], "Yeni görev")
        self.assertEqual(value["status"], "pending")
        self.assertFalse(value["notified"])
        self.assertEqual(value["answer"], "")

    def test_delete_removes_reminder(self):
        reminder = self.create("Silinecek iş", 1800)
        status, body, _ = self.request_post("/api/reminders", {
            "action": "delete", "id": reminder["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted"], reminder["id"])

        status, body, _ = self.request("GET", "/api/reminders")
        self.assertEqual(body["reminders"], [])

    def test_invalid_inputs_are_rejected(self):
        now = time.time()
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "   ", "due_at": now + 60})
        self.assertEqual(status, 400)

        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "x", "due_at": now + 5})
        self.assertEqual(status, 400)
        self.assertIn("20 saniye", body["error"])

        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "x",
            "due_at": now + app.REMINDER_MAX_HORIZON_SECONDS * 2})
        self.assertEqual(status, 400)

        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "u" * 301, "due_at": now + 60})
        self.assertEqual(status, 400)

        status, body, _ = self.request_post("/api/reminders", {
            "action": "update", "id": 9999, "task": "x", "due_at": now + 60})
        self.assertEqual(status, 404)

    def test_reminders_are_scoped_to_guest_mode(self):
        main_reminder = self.create("Ana hatırlatıcı", 3600)
        self.request_post("/api/guest-mode", {"active": True})

        status, body, _ = self.request("GET", "/api/reminders")
        self.assertEqual(status, 200)
        self.assertEqual(body["reminders"], [])

        guest_reminder = self.create("Misafir hatırlatıcı", 7200)

        # Misafir kapanınca yalnız misafir hatırlatıcıları silinir.
        status, body, _ = self.request_post(
            "/api/guest-mode", {"active": False})
        self.assertEqual(status, 200)

        status, body, _ = self.request("GET", "/api/reminders")
        ids = [row["id"] for row in body["reminders"]]
        self.assertIn(main_reminder["id"], ids)
        self.assertNotIn(guest_reminder["id"], ids)

    def test_coach_time_commitment_parser(self):
        cases = [
            ("5 dk sonra yazmayı hatırlat", "yazmayı", 300),
            ("1 saat sonra derse başlamayı zamanla", "derse başlamayı", 3600),
            ("yarım saat sonra mola için alarm kur", "mola için", 1800),
            ("2 saat sonra sporu hatırlat", "sporu", 7200),
            ("2 saat sonra ne olur?", None, None),
            ("5 dk sonra yazacağım", None, None),
            ("bugün hava güzel", None, None),
            ("nasılsın", None, None),
            ("3 saniye sonra denemeyi hatırlat", "denemeyi",
             int(app.REMINDER_MIN_HORIZON_SECONDS)),
        ]
        for text, task, seconds in cases:
            with self.subTest(text=text):
                result = app.coach_time_commitment(text)
                if task is None:
                    self.assertIsNone(result)
                else:
                    self.assertIsNotNone(result)
                    parsed_task, parsed_seconds = result
                    self.assertEqual(parsed_task, task)
                    self.assertEqual(parsed_seconds, seconds)

    def test_coach_chat_message_auto_creates_reminder(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]

        status, body, _ = self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "5 dk sonra yazmayı hatırlat",
            "request_id": "adhd-commit-request-0001",
        })
        self.assertEqual(status, 200, body)

        status, reminders, _ = self.request("GET", "/api/reminders")
        self.assertEqual(status, 200)
        self.assertEqual(len(reminders["reminders"]), 1)
        reminder = reminders["reminders"][0]
        self.assertEqual(reminder["task"], "yazmayı")
        self.assertEqual(reminder["source_conv"], cid)
        self.assertAlmostEqual(
            reminder["due_at"], time.time() + 300, delta=10)

        # İstem de koça kurulan hatırlatıcıyı bildirir.
        with app.db() as c:
            latest = c.execute(
                "SELECT id FROM messages WHERE conv=? AND role='user' "
                "ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
        _, payload = app._chat_prompt_payload({
            "conv": cid,
            "user_message": latest["id"],
            "reply_to": None,
            "guidance": "",
            "method_key": None,
            "method_id": None,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "fast": 0,
            "attempt_count": 1,
        })
        joined = "\n".join(str(item["content"]) for item in payload["messages"])
        self.assertIn("hatırlatıcı kurdu", joined)

    def test_panel_reminder_can_reference_source_conversation(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kaynaklı görev",
            "due_at": time.time() + 600, "source_conv": cid,
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["reminder"]["source_conv"], cid)

        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kötü kaynak",
            "due_at": time.time() + 600, "source_conv": 999999,
        })
        self.assertEqual(status, 400)

    def test_notification_context_returns_latest_completed_reply(self):
        status, empty, _ = self.request(
            "GET", "/api/notification-context")
        self.assertEqual(status, 200)
        self.assertEqual(empty, {})

        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "merhaba koç",
            "request_id": "adhd-notify-request-0001",
        })
        self.assertEqual(status, 200)
        with app.db() as c:
            assistant = c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (cid, "assistant", "Selam! Hadi başlayalım.", app.now()))
            c.execute(
                "UPDATE chat_requests SET status='completed',"
                "best_partial_content='Selam! Hadi başlayalım.',"
                "partial_content='Selam! Hadi başlayalım.',"
                "assistant_message=?,finished=?,updated=? WHERE request_id=?",
                (assistant.lastrowid, app.now(), app.now(),
                 "adhd-notify-request-0001"))

        status, context, _ = self.request(
            "GET", "/api/notification-context")
        self.assertEqual(status, 200, context)
        self.assertEqual(context["conversation_id"], cid)
        self.assertEqual(context["master_name"], "ADHD Koçu")
        self.assertEqual(context["status"], "completed")
        self.assertEqual(context["content"], "Selam! Hadi başlayalım.")
        self.assertEqual(context["user_content"], "merhaba koç")

    def test_notification_context_scopes_to_requested_conversation(self):
        """Bildirimden yazılan yanıt kendi görüşmesinin cevabını almalı.

        Kapsam olmazsa başka bir görüşmede daha yeni tamamlanan istek
        bildirime taşınır: kullanıcı koça yazar, felsefecinin cevabını
        bildirimde görür.
        """
        conversations = {}
        for master, request_id, reply in (
                ("adhd", "scope-adhd-0001", "Koçun cevabı."),
                ("freud", "scope-freud-0001", "Freud'un cevabı.")):
            _, created, _ = self.request("POST", "/api/new", {
                "therapist": master, "mode": "terapi",
            })
            conversations[master] = created["id"]
            status, _, _ = self.request_post("/api/chat", {
                "conv_id": created["id"],
                "message": "soru {}".format(master),
                "request_id": request_id,
            })
            self.assertEqual(status, 200)
            with app.db() as c:
                assistant = c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (created["id"], "assistant", reply, app.now()))
                c.execute(
                    "UPDATE chat_requests SET status='completed',"
                    "best_partial_content=?,partial_content=?,"
                    "assistant_message=?,finished=?,updated=? "
                    "WHERE request_id=?",
                    (reply, reply, assistant.lastrowid,
                     app.now(), app.now(), request_id))

        # Kapsamsız çağrı en son tamamlananı verir (eski davranış).
        _, latest, _ = self.request("GET", "/api/notification-context")
        self.assertEqual(latest["conversation_id"], conversations["freud"])

        # Kapsamlı çağrı yalnız o görüşmenin yanıtını verir.
        _, scoped, _ = self.request(
            "GET", "/api/notification-context?conv_id={}".format(
                conversations["adhd"]))
        self.assertEqual(scoped["conversation_id"], conversations["adhd"])
        self.assertEqual(scoped["master_name"], "ADHD Koçu")
        self.assertEqual(scoped["content"], "Koçun cevabı.")

    def test_notification_context_carries_master_portrait(self):
        """Bildirimdeki kişi simgesi için portre yolu dönmeli."""
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        cid = created["id"]
        status, _, _ = self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "portre testi",
            "request_id": "portrait-notify-0001",
        })
        self.assertEqual(status, 200)
        with app.db() as c:
            assistant = c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (cid, "assistant", "Buyurun.", app.now()))
            c.execute(
                "UPDATE chat_requests SET status='completed',"
                "best_partial_content='Buyurun.',partial_content='Buyurun.',"
                "assistant_message=?,finished=?,updated=? WHERE request_id=?",
                (assistant.lastrowid, app.now(), app.now(),
                 "portrait-notify-0001"))

        _, context, _ = self.request(
            "GET", "/api/notification-context?conv_id={}".format(cid))
        self.assertEqual(context["master_id"], "freud")
        if app.PORTRAIT_CATALOG.get("freud"):
            self.assertTrue(
                str(context["portrait"]).startswith("/assets/portraits/"),
                context["portrait"])

    def test_notification_outbox_keeps_multiple_terminal_requests(self):
        rows = []
        full_reply = "**Freud** " + ("uzun yanıt bölümü " * 320)
        for master, request_id, reply in (
                ("adhd", "outbox-adhd-0001", "Koç yanıtı."),
                ("freud", "outbox-freud-0001", full_reply)):
            _, created, _ = self.request("POST", "/api/new", {
                "therapist": master, "mode": "terapi",
            })
            cid = created["id"]
            status, _, _ = self.request_post("/api/chat", {
                "conv_id": cid, "message": "outbox sorusu",
                "request_id": request_id,
            })
            self.assertEqual(status, 200)
            with app.db() as c:
                assistant = c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)", (cid, "assistant", reply, app.now()))
                c.execute(
                    "UPDATE chat_requests SET status='completed',"
                    "assistant_message=?,finished=?,updated=? "
                    "WHERE request_id=?",
                    (assistant.lastrowid, app.now(), app.now(), request_id))
            rows.append((request_id, reply))

        # Native açık tercih göndermedikçe güvenli bir ana profil bile içerik
        # alamaz; reply capability bundan bağımsız kalır.
        status, redacted, _ = self.request(
            "GET", "/api/notification-contexts?after_sequence=0&limit=10")
        self.assertEqual(status, 200, redacted)
        self.assertTrue(all(item["content"] == ""
                            for item in redacted["contexts"]))
        self.assertTrue(all(not item["preview_allowed"]
                            for item in redacted["contexts"]))
        self.assertTrue(all(item["reply_allowed"]
                            for item in redacted["contexts"]))

        status, payload, _ = self.request(
            "GET", "/api/notification-contexts?after_sequence=0&limit=10"
            "&allow_preview=1")
        self.assertEqual(status, 200, payload)
        contexts = payload["contexts"]
        self.assertEqual([item["request_id"] for item in contexts],
                         [row[0] for row in rows])
        self.assertEqual([item["content"] for item in contexts],
                         [row[1] for row in rows])
        self.assertTrue(all(isinstance(item["message_id"], int)
                            for item in contexts))
        self.assertTrue(all(item["preview_allowed"] for item in contexts))
        self.assertTrue(all(item["reply_allowed"] for item in contexts))
        self.assertGreater(len(contexts[-1]["content"]), 4000)

        cursor = contexts[0]["sequence"]
        _, later, _ = self.request(
            "GET", ("/api/notification-contexts?after_sequence={}"
                    "&allow_preview=1").format(cursor))
        self.assertEqual([item["request_id"] for item in later["contexts"]],
                         [rows[1][0]])

    def test_notification_outbox_redacts_pin_safety_and_failed_content(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        cid = created["id"]
        status, _, _ = self.request_post("/api/chat", {
            "conv_id": cid, "message": "özel içerik",
            "request_id": "outbox-private-0001",
        })
        self.assertEqual(status, 200)
        with app.db() as c:
            assistant = c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (cid, "assistant", "Bildirimde görünmemeli.", app.now()))
            c.execute(
                "UPDATE chat_requests SET status='completed',"
                "assistant_message=?,finished=?,updated=? WHERE request_id=?",
                (assistant.lastrowid, app.now(), app.now(),
                 "outbox-private-0001"))

        app.set_setting("pin_hash", app.pin_hash("1234"))
        status, locked, _ = self.request(
            "GET", "/api/notification-contexts?after_sequence=0"
            "&allow_preview=1")
        self.assertEqual(status, 200, locked)
        item = locked["contexts"][0]
        self.assertFalse(item["preview_allowed"])
        self.assertFalse(item["reply_allowed"])
        self.assertEqual(item["content"], "")
        self.assertEqual(item["master_name"], "")

        app.set_setting("pin_hash", "")
        with app.db() as c:
            c.execute("UPDATE conversations SET safety_hold=1 WHERE id=?",
                      (cid,))
        _, held, _ = self.request(
            "GET", "/api/notification-contexts?after_sequence=0"
            "&allow_preview=1")
        self.assertFalse(held["contexts"][0]["preview_allowed"])
        self.assertFalse(held["contexts"][0]["reply_allowed"])
        self.assertEqual(held["contexts"][0]["content"], "")

        with app.db() as c:
            c.execute("UPDATE conversations SET safety_hold=0 WHERE id=?",
                      (cid,))
            c.execute(
                "UPDATE chat_requests SET status='failed',"
                "best_partial_content='yarım ve güvensiz' WHERE request_id=?",
                ("outbox-private-0001",))
        _, failed, _ = self.request(
            "GET", "/api/notification-contexts?after_sequence=0"
            "&allow_preview=1")
        self.assertEqual(failed["contexts"][0]["status"], "failed")
        self.assertFalse(failed["contexts"][0]["preview_allowed"])
        self.assertFalse(failed["contexts"][0]["reply_allowed"])
        self.assertEqual(failed["contexts"][0]["content"], "")

    def test_notification_reply_capability_is_content_free_and_lock_exempt(self):
        status, capability, _ = self.request(
            "GET", "/api/notification-reply-capability")
        self.assertEqual(status, 200, capability)
        self.assertEqual(capability, {
            "allowed": True, "pin_enabled": False, "scope": "main",
        })

        app.set_setting("pin_hash", app.pin_hash("1234"))
        # This policy probe remains available while the app is locked, but it
        # never leaks conversation or provider content.
        status, locked, _ = self.request(
            "GET", "/api/notification-reply-capability")
        self.assertEqual(status, 200, locked)
        self.assertEqual(locked, {
            "allowed": False, "pin_enabled": True, "scope": "main",
        })

    def test_notification_reply_persists_and_queues_without_running_model(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        cid = created["id"]
        source_request_id, source_id = self.completed_notification_source(
            cid, "notification-source-reply-0001")
        payload = {
            "conversation_id": cid,
            "message": "Bunu biraz daha açabilir misin?",
            "request_id": "native-inline-reply-0001",
            "source_id": source_request_id,
            "reply_to": source_id,
        }
        with mock.patch.object(
                app, "run_chat_request",
                side_effect=AssertionError("request thread ran the model")):
            status, accepted, _ = self.request_post(
                "/api/notification-reply", payload)
        self.assertEqual(status, 202, accepted)
        self.assertTrue(accepted["accepted"])
        self.assertFalse(accepted["duplicate"])
        self.assertEqual(accepted["status"], "queued")
        self.assertEqual(accepted["request_id"], payload["request_id"])
        self.assertIsInstance(accepted["job_id"], int)
        with app.db() as c:
            request = c.execute(
                "SELECT * FROM chat_requests WHERE request_id=?",
                (payload["request_id"],)).fetchone()
            message = c.execute(
                "SELECT * FROM messages WHERE client_event_id=?",
                (payload["request_id"],)).fetchone()
        self.assertEqual(request["status"], "queued")
        self.assertEqual(request["job"], accepted["job_id"])
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"], payload["message"])
        self.assertEqual(message["reply_to"], source_id)
        self.assertEqual(accepted["reply_to"], source_id)
        self.assertEqual(self.queued_job_id(), accepted["job_id"])

        # A transport retry binds to the same durable rows and does not enqueue
        # or append them a second time.
        status, duplicate, _ = self.request_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 202, duplicate)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["job_id"], accepted["job_id"])
        self.assertTrue(app.JOB_QUEUE.empty())
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE client_event_id=?",
                (payload["request_id"],)).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_notification_reply_conflicts_on_reused_request_binding(self):
        first = self.conversation(therapist="freud")
        second = self.conversation(therapist="jung")
        source_request_id, source_message_id = (
            self.completed_notification_source(
                first, "notification-source-conflict-0001"))
        payload = {
            "conversation_id": first, "message": "İlk metin",
            "request_id": "native-inline-conflict-0001",
            "source_id": source_request_id,
            "reply_to": source_message_id,
        }
        status, _, _ = self.request_post("/api/notification-reply", payload)
        self.assertEqual(status, 202)
        payload["message"] = "Başka metin"
        status, body, _ = self.request_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 409, body)
        payload.update({"conversation_id": second, "message": "İlk metin"})
        status, body, _ = self.request_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 409, body)

    def test_notification_reply_rejects_pin_guest_and_unsafe_states(self):
        cid = self.conversation(therapist="freud")
        source_request_id, source_message_id = (
            self.completed_notification_source(
                cid, "notification-source-policy-0001"))
        base = {
            "conversation_id": cid, "message": "Devam edelim",
            "request_id": "native-inline-policy-0001",
            "source_id": source_request_id,
            "reply_to": source_message_id,
        }

        app.set_setting("pin_hash", app.pin_hash("1234"))
        cookie = self.unlock_cookie("1234")
        status, body, _ = self.request(
            "POST", "/api/notification-reply", base,
            headers={"Cookie": cookie})
        self.assertEqual(status, 403, body)
        app.set_setting("pin_hash", "")

        app.set_setting("guest_mode", "1")
        status, body, _ = self.request_post(
            "/api/notification-reply", base)
        self.assertEqual(status, 403, body)
        app.set_setting("guest_mode", "")

        for field, value in (
                ("safety_hold", 1), ("ended", 1),
                ("archived_at", app.now())):
            with self.subTest(field=field):
                with app.db() as c:
                    c.execute(
                        "UPDATE conversations SET safety_hold=0,ended=0,"
                        "archived_at=NULL WHERE id=?", (cid,))
                    c.execute(
                        "UPDATE conversations SET {}=? WHERE id=?".format(
                            field), (value, cid))
                attempt = dict(base)
                attempt["request_id"] = "native-inline-{}-0001".format(field)
                status, body, _ = self.request_post(
                    "/api/notification-reply", attempt)
                self.assertEqual(status, 409, body)

        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=0,ended=0,"
                "archived_at=NULL WHERE id=?", (cid,))
        danger = dict(base)
        danger["message"] = "Şu anda kendimi öldürmek istiyorum."
        danger["request_id"] = "native-inline-safety-text-0001"
        status, body, _ = self.request_post(
            "/api/notification-reply", danger)
        self.assertEqual(status, 409, body)
        with app.db() as c:
            self.assertIsNone(c.execute(
                "SELECT 1 FROM chat_requests WHERE request_id=?",
                (danger["request_id"],)).fetchone())

    def test_notification_reply_requires_embedded_session_cookie(self):
        cid = self.conversation(therapist="freud")
        source_request_id, source_message_id = (
            self.completed_notification_source(
                cid, "notification-source-session-0001"))
        payload = {
            "conversation_id": cid, "message": "Kısa yanıt",
            "request_id": "native-inline-session-0001",
            "source_id": source_request_id,
            "reply_to": source_message_id,
        }
        app.EMBEDDED_SESSION_TOKEN = "native-test-session"
        status, body, _ = self.request_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 403, body)
        cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        status, body, _ = self.request(
            "POST", "/api/notification-reply", payload,
            headers={"Cookie": cookie})
        self.assertEqual(status, 202, body)

    def test_notification_reply_rejects_stale_or_unbound_source(self):
        cid = self.conversation(therapist="freud")
        source_request_id, source_message_id = (
            self.completed_notification_source(
                cid, "notification-source-stale-0001"))
        with app.db() as c:
            c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)", (cid, "user", "Daha yeni söz", app.now()))
        payload = {
            "conversation_id": cid, "message": "Bayat eylem",
            "request_id": "native-inline-stale-0001",
            "source_id": source_request_id,
            "reply_to": source_message_id,
        }
        status, body, _ = self.request_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 409, body)
        with app.db() as c:
            self.assertIsNone(c.execute(
                "SELECT 1 FROM chat_requests WHERE request_id=?",
                (payload["request_id"],)).fetchone())

        payload["request_id"] = "native-inline-unbound-0001"
        payload["source_id"] = "notification-source-does-not-exist"
        status, body, _ = self.request_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 409, body)

    def test_notification_reply_accepts_completed_scheduled_source(self):
        cid = self.conversation(therapist="adhd")
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kısa görev",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE reminder_id=?", ("Nasıl geçti?", rid))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        status, delivered, _ = self.native_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 200, delivered)
        payload = {
            "conversation_id": cid, "message": "İyi geçti.",
            "request_id": "native-inline-scheduled-0001",
            "source_id": delivered["source_id"],
            "reply_to": delivered["message_id"],
        }
        status, accepted, _ = self.native_post(
            "/api/notification-reply", payload)
        self.assertEqual(status, 202, accepted)
        self.assertEqual(accepted["source_id"], delivered["source_id"])
        self.assertEqual(accepted["reply_to"], delivered["message_id"])

    def test_plain_future_tense_does_not_create_alarm_without_consent(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        status, _, _ = self.request_post("/api/chat", {
            "conv_id": created["id"],
            "message": "2 saat sonra ne olur?",
            "request_id": "no-implied-alarm-0001",
        })
        self.assertEqual(status, 200)
        _, reminders, _ = self.request("GET", "/api/reminders")
        self.assertEqual(reminders["reminders"], [])

    def test_scheduled_message_created_with_source_conversation(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        self.assertEqual(status, 200, body)
        rid = body["reminder"]["id"]
        with app.db() as c:
            rows = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "generating")
        self.assertEqual(rows[0]["conv"], cid)
        self.assertEqual(rows[0]["therapist"], "adhd")

    def test_scheduled_message_job_generates_hidden_content(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
        job = {
            "id": 999001, "kind": "scheduled_message", "conv": cid,
        }
        with mock.patch.object(
                app, "ds_complete",
                return_value="Kitap okumak istiyordun; şimdi 5 dakika "
                             "yeter mi?"):
            app.run_scheduled_message_job(job, app.data_generation())
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE id=?",
                (sched["id"],)).fetchone()
            visible = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE client_event_id=?",
                ("scheduled-{}".format(sched["id"]),)).fetchone()["n"]
        self.assertEqual(sched["status"], "ready")
        self.assertIn("Kitap okumak istiyordun", sched["content"])
        # Sohbette henüz görünmez.
        self.assertEqual(visible, 0)

    def test_reveal_appends_message_to_chat_once(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?", ("Şimdi 5 dakika ayırır mısın?", sched["id"]))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))

        status, revealed, _ = self.request_post(
            "/api/reminders/reveal", {"id": rid})
        self.assertEqual(status, 200, revealed)
        self.assertTrue(revealed["revealed_now"])
        self.assertEqual(revealed["message"], "Şimdi 5 dakika ayırır mısın?")
        self.assertEqual(revealed["conversation_id"], cid)
        self.assertEqual(revealed["master_name"], "ADHD Koçu")
        self.assertIsNotNone(revealed["message_id"])

        # İkinci çağrı aynı sonucu verir; mesaj bir kez eklenir.
        status, again, _ = self.request_post(
            "/api/reminders/reveal", {"id": rid})
        self.assertEqual(status, 200, again)
        self.assertFalse(again["revealed_now"])
        self.assertEqual(again["message"], "Şimdi 5 dakika ayırır mısın?")
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE "
                "client_event_id=?", ("scheduled-{}".format(sched["id"]),)
            ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_deleted_conversation_clears_all_direct_reminder_rows(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        reminder_ids = []
        for task in ("Hazır kontrol", "Açılmış kontrol"):
            _, body, _ = self.request_post("/api/reminders", {
                "action": "create", "task": task,
                "due_at": time.time() + 3600, "source_conv": cid,
            })
            reminder_ids.append(body["reminder"]["id"])
        with app.db() as c:
            c.execute(
                "UPDATE scheduled_messages SET content='Kontrol',"
                "status=CASE WHEN reminder_id=? THEN 'ready' "
                "ELSE 'revealed' END WHERE conv=?",
                (reminder_ids[0], cid),
            )
            app.delete_conversation_data(c, cid)
            first = app.materialize_due_scheduled_messages(
                c, time.time() + 7200)
            second = app.materialize_due_scheduled_messages(
                c, time.time() + 7200)
            counts = {
                "reminders": c.execute(
                    "SELECT COUNT(*) FROM reminders WHERE source_conv=?",
                    (cid,),
                ).fetchone()[0],
                "scheduled": c.execute(
                    "SELECT COUNT(*) FROM scheduled_messages WHERE conv=?",
                    (cid,),
                ).fetchone()[0],
                "messages": c.execute(
                    "SELECT COUNT(*) FROM messages WHERE conv=?",
                    (cid,),
                ).fetchone()[0],
                "memories": c.execute(
                    "SELECT COUNT(*) FROM memories WHERE source_conv=?",
                    (cid,),
                ).fetchone()[0],
            }

        self.assertEqual(first, {})
        self.assertEqual(second, {})
        self.assertEqual(counts, {
            "reminders": 0, "scheduled": 0,
            "messages": 0, "memories": 0,
        })

    def test_legacy_orphan_scheduled_message_is_silently_cancelled(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Eski kontrol",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute("PRAGMA foreign_keys=OFF")
            sched = c.execute(
                "SELECT id FROM scheduled_messages WHERE reminder_id=?",
                (rid,),
            ).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?", ("Yeniden doğmamalı", sched["id"]),
            )
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid),
            )
            c.execute("DELETE FROM conversations WHERE id=?", (cid,))

        status, first, _ = self.native_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 200, first)
        self.assertEqual(first["state"], "suppressed")
        self.assertIsNone(first["conversation_id"])

        status, second, _ = self.native_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 200, second)
        self.assertEqual(second["state"], "suppressed")
        with app.db() as c:
            reminder = c.execute(
                "SELECT status,task,source_conv FROM reminders WHERE id=?",
                (rid,)
            ).fetchone()
            scheduled = c.execute(
                "SELECT status,message_id,content FROM scheduled_messages "
                "WHERE id=?", (sched["id"],)
            ).fetchone()
            messages = c.execute(
                "SELECT COUNT(*) FROM messages WHERE client_event_id=?",
                ("scheduled-{}".format(sched["id"]),),
            ).fetchone()[0]
            memories = c.execute(
                "SELECT COUNT(*) FROM memories WHERE source_conv=?",
                (cid,),
            ).fetchone()[0]

        self.assertEqual(reminder["status"], "cancelled_user")
        self.assertEqual(reminder["task"], "")
        self.assertIsNone(reminder["source_conv"])
        self.assertEqual(scheduled["status"], "discarded")
        self.assertIsNone(scheduled["message_id"])
        self.assertEqual(scheduled["content"], "")
        self.assertEqual(messages, 0)
        self.assertEqual(memories, 0)

    def test_due_status_durably_materializes_ready_message_once(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?", ("Nasıl geçti?", sched["id"]))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))

        status, first, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual(status, 200, first)
        delivery = first["due"][0]
        event_id = "scheduled-{}".format(sched["id"])
        self.assertEqual(delivery["request_id"], event_id)
        self.assertEqual(delivery["delivery_status"], "completed")
        self.assertIsInstance(delivery["message_id"], int)

        # Status polling, app relaunch and reveal all converge on the same
        # assistant row instead of appending another one.
        self.request("GET", "/api/reminders/status")
        app.resume_jobs()
        app.resume_jobs()
        status, revealed, _ = self.request_post(
            "/api/reminders/reveal", {"id": rid})
        self.assertEqual(status, 200, revealed)
        self.assertEqual(revealed["request_id"], event_id)
        self.assertEqual(revealed["message_id"], delivery["message_id"])
        with app.db() as c:
            messages = c.execute(
                "SELECT * FROM messages WHERE client_event_id=?",
                (event_id,)).fetchall()
            stored = c.execute(
                "SELECT * FROM scheduled_messages WHERE id=?",
                (sched["id"],)).fetchone()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "assistant")
        self.assertEqual(messages[0]["content"], "Nasıl geçti?")
        self.assertEqual(stored["message_id"], messages[0]["id"])
        self.assertEqual(stored["status"], "revealed")

    def test_due_generation_completion_materializes_without_reveal_call(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Su iç",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        job = {"id": 991701, "kind": "scheduled_message", "conv": cid}
        with mock.patch.object(
                app, "ds_complete", return_value="Su zamanı; nasıl gitti?"):
            app.run_scheduled_message_job(job, app.data_generation())
        with app.db() as c:
            rows = c.execute(
                "SELECT * FROM messages WHERE client_event_id=?",
                ("scheduled-{}".format(sched["id"]),)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "Su zamanı; nasıl gitti?")

    def test_native_deliver_is_content_free_exactly_once_and_pin_safe(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Gizli görev metni",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?", ("Gizli AI kontrol mesajı", sched["id"]))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        # PIN olsa bile kilit ekranına içerik dönmeden teslim dayanıklı olur;
        # yalnız doğrudan yanıt kesin olarak kapalıdır.
        app.set_setting("pin_hash", app.pin_hash("1234"))
        status, first, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": True,
            })
        self.assertEqual(status, 200, first)
        self.assertEqual(first["state"], "completed")
        self.assertEqual(first["source_id"],
                         "scheduled-{}".format(sched["id"]))
        self.assertIsInstance(first["message_id"], int)
        self.assertFalse(first["reply_allowed"])
        self.assertFalse(first["preview_allowed"])
        self.assertEqual(first["master_name"], "")
        self.assertTrue(first["revealed_now"])
        self.assertNotIn("preview", first)
        self.assertNotIn("message", first)
        self.assertNotIn("content", first)
        self.assertNotIn("task", first)

        status, second, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": True,
            })
        self.assertEqual(status, 200, second)
        self.assertEqual(second["message_id"], first["message_id"])
        self.assertEqual(second["source_id"], first["source_id"])
        self.assertFalse(second["revealed_now"])
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE client_event_id=?",
                (first["source_id"],)).fetchone()["n"], 1)
            # Delivery and OS-notification acknowledgement are separate.
            reminder = c.execute(
                "SELECT notified FROM reminders WHERE id=?", (rid,)
            ).fetchone()
        self.assertEqual(reminder["notified"], 0)

        status, mismatch, _ = self.native_post(
            "/api/reminders/deliver-ack", {
                "id": rid, "source_id": "scheduled-wrong",
                "message_id": first["message_id"],
            })
        self.assertEqual(status, 409, mismatch)
        status, acknowledged, _ = self.native_post(
            "/api/reminders/deliver-ack", {
                "id": rid, "source_id": first["source_id"],
                "message_id": first["message_id"],
            })
        self.assertEqual(status, 200, acknowledged)
        self.assertEqual(acknowledged, {
            "ok": True, "id": rid, "notified": True,
        })
        # Ack itself is exactly-once/idempotent too.
        status, again, _ = self.native_post(
            "/api/reminders/deliver-ack", {
                "id": rid, "source_id": first["source_id"],
                "message_id": first["message_id"],
            })
        self.assertEqual(status, 200, again)
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT notified FROM reminders WHERE id=?", (rid,)
            ).fetchone()["notified"], 1)

    def test_native_deliver_full_preview_requires_safe_explicit_opt_in(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Gizli kullanıcı görevi",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        full = "## **Kontrol**\n\n" + ("[görünen](https://example.com) " * 240)
        with app.db() as c:
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE reminder_id=?", (full, rid))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))

        # Varsayılan delivery içeriksiz kalır.
        status, neutral_preview, _ = self.native_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 200, neutral_preview)
        self.assertFalse(neutral_preview["preview_allowed"])
        self.assertEqual(neutral_preview["master_name"], "")
        self.assertNotIn("preview", neutral_preview)

        status, shown, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": True,
            })
        self.assertEqual(status, 200, shown)
        self.assertTrue(shown["preview_allowed"])
        self.assertTrue(shown["reply_allowed"])
        self.assertEqual(shown["master_name"], "ADHD Koçu")
        self.assertEqual(shown["preview"], full)
        self.assertGreater(len(shown["preview"]), 4000)
        for forbidden in ("task", "message", "user_content", "history"):
            self.assertNotIn(forbidden, shown)

        # Aynı materialized mesaj güvenlik tutuşunda artık dışarı çıkmaz.
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?", (cid,))
        status, held, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": True,
            })
        self.assertEqual(status, 200, held)
        self.assertFalse(held["preview_allowed"])
        self.assertFalse(held["reply_allowed"])
        self.assertEqual(held["master_name"], "")
        self.assertNotIn("preview", held)

        status, invalid, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": "true",
            })
        self.assertEqual(status, 400, invalid)

        status, _, _ = self.native_post(
            "/api/guest-mode", {"active": True})
        self.assertEqual(status, 200)
        _, guest_created, _ = self.native_post("/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        guest_cid = guest_created["id"]
        _, guest_body, _ = self.native_post("/api/reminders", {
            "action": "create", "task": "Misafir görevi",
            "due_at": time.time() + 3600, "source_conv": guest_cid,
        })
        guest_id = guest_body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE reminder_id=?", ("Misafir AI metni", guest_id))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, guest_id))
        status, guest, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": guest_id, "allow_preview": True,
            })
        self.assertEqual(status, 200, guest)
        self.assertEqual(guest["state"], "completed")
        self.assertFalse(guest["preview_allowed"])
        self.assertFalse(guest["reply_allowed"])
        self.assertEqual(guest["master_name"], "")
        self.assertNotIn("preview", guest)

    def test_native_deliver_generating_and_failed_never_leak_or_write(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Görev",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        status, generating, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": True,
            })
        self.assertEqual(status, 202, generating)
        self.assertEqual(generating["state"], "generating")
        self.assertIsNone(generating["message_id"])
        self.assertFalse(generating["reply_allowed"])
        self.assertFalse(generating["preview_allowed"])
        self.assertEqual(generating["master_name"], "")
        self.assertNotIn("preview", generating)

        with app.db() as c:
            c.execute(
                "UPDATE scheduled_messages SET status='failed',content=? "
                "WHERE reminder_id=?", ("yarım/güvensiz metin", rid))
        status, neutral, _ = self.native_post(
            "/api/reminders/deliver", {
                "id": rid, "allow_preview": True,
            })
        self.assertEqual(status, 200, neutral)
        self.assertEqual(neutral["state"], "neutral")
        self.assertIsNone(neutral["message_id"])
        self.assertFalse(neutral["preview_allowed"])
        self.assertEqual(neutral["master_name"], "")
        self.assertNotIn("preview", neutral)
        self.assertNotIn("yarım", str(neutral))
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE "
                "client_event_id LIKE 'scheduled-%'").fetchone()["n"], 0)

    def test_native_deliver_requires_embedded_session_but_not_unlock_cookie(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Görev",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        status, desktop_denied, _ = self.request_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 403, desktop_denied)
        app.EMBEDDED_SESSION_TOKEN = "native-reminder-session"
        app.set_setting("pin_hash", app.pin_hash("1234"))
        status, denied, _ = self.request_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 403, denied)
        cookie = "{}={}".format(
            app.EMBEDDED_SESSION_COOKIE, app.EMBEDDED_SESSION_TOKEN)
        status, accepted, _ = self.request(
            "POST", "/api/reminders/deliver", {"id": rid},
            headers={"Cookie": cookie})
        # Future reminder: accepted for background delivery but not exposed.
        self.assertEqual(status, 202, accepted)
        self.assertEqual(accepted["state"], "pending")

    def test_native_delivery_preserves_other_scope_and_neutral_ack(self):
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Ana kapsam görevi",
            "due_at": time.time() + 3600,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        app.set_setting("guest_mode", "1")
        status, mismatch, _ = self.native_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 409, mismatch)
        self.assertEqual(mismatch, {"state": "scope_mismatch"})
        status, mismatch, _ = self.native_post(
            "/api/reminders/deliver-ack", {
                "id": rid, "source_id": "reminder-{}".format(rid),
            })
        self.assertEqual(status, 409, mismatch)
        with app.db() as c:
            self.assertIsNotNone(c.execute(
                "SELECT 1 FROM reminders WHERE id=?", (rid,)).fetchone())

        app.set_setting("guest_mode", "")
        status, neutral, _ = self.native_post(
            "/api/reminders/deliver", {"id": rid})
        self.assertEqual(status, 200, neutral)
        self.assertEqual(neutral["state"], "neutral")
        self.assertEqual(neutral["source_id"], "reminder-{}".format(rid))
        self.assertIsNone(neutral["message_id"])
        status, acknowledged, _ = self.native_post(
            "/api/reminders/deliver-ack", {
                "id": rid, "source_id": neutral["source_id"],
            })
        self.assertEqual(status, 200, acknowledged)
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT notified FROM reminders WHERE id=?", (rid,)
            ).fetchone()["notified"], 1)

    def test_incomplete_failed_and_neutral_reminders_never_write_ai_bubble(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kaynaklı iş",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        _, generating, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual(generating["due"][0]["delivery_status"],
                         "generating")
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE "
                "client_event_id LIKE 'scheduled-%'").fetchone()["n"], 0)
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='failed' "
                "WHERE reminder_id=?", ("yarım model metni", rid))
        _, failed, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual(failed["due"][0]["delivery_status"], "failed")

        _, neutral_body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Nötr panel görevi",
            "due_at": time.time() + 3600,
        })
        neutral_id = neutral_body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, neutral_id))
        _, due, _ = self.request("GET", "/api/reminders/status")
        neutral = next(row for row in due["due"] if row["id"] == neutral_id)
        self.assertEqual(neutral["delivery_status"], "neutral")
        self.assertIsNone(neutral["request_id"])
        self.assertIsNone(neutral["message_id"])
        with app.db() as c:
            self.assertEqual(c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE "
                "client_event_id LIKE 'scheduled-%'").fetchone()["n"], 0)

    def test_ready_scheduled_message_is_not_delivered_before_due_time(self):
        _, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        _, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Henüz değil",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?", ("Erken görünmemeli.", sched["id"]))
        status, revealed, _ = self.request_post(
            "/api/reminders/reveal", {"id": rid})
        self.assertEqual(status, 200, revealed)
        self.assertIsNone(revealed["message_id"])
        self.assertEqual(revealed["delivery_status"], "ready")
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE client_event_id=?",
                ("scheduled-{}".format(sched["id"]),)).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_reveal_writes_checkin_memory_once(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?",
                ("Nasıl geçti? Neler yaptın?", sched["id"]))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))

        status, revealed, _ = self.request_post(
            "/api/reminders/reveal", {"id": rid})
        self.assertEqual(status, 200, revealed)
        self.assertTrue(revealed["revealed_now"])
        with app.db() as c:
            checkins = c.execute(
                "SELECT * FROM memories WHERE kind='checkin' AND "
                "source_conv=?", (cid,)).fetchall()
        self.assertEqual(len(checkins), 1)
        self.assertIn("Kitap oku", checkins[0]["content"])
        self.assertIn("[hatırlatıcı:{}]".format(rid), checkins[0]["content"])
        self.assertIn("Nasıl geçti?", checkins[0]["content"])

        # İkinci reveal yeni hafıza kaydı üretmez.
        self.request_post("/api/reminders/reveal", {"id": rid})
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE kind='checkin' "
                "AND source_conv=?", (cid,)).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_first_reply_after_reveal_writes_checkin_answer_memory(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
            c.execute(
                "UPDATE scheduled_messages SET content=?,status='ready' "
                "WHERE id=?", ("Nasıl geçti?", sched["id"]))
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))
        self.request_post("/api/reminders/reveal", {"id": rid})

        status, chat, _ = self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "İlk sayfayı okudum, iyi geldi.",
            "request_id": "checkin-answer-0001",
        })
        self.assertEqual(status, 200, chat)
        with app.db() as c:
            answers = c.execute(
                "SELECT * FROM memories WHERE kind='checkin_answer' AND "
                "source_conv=?", (cid,)).fetchall()
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
        self.assertEqual(len(answers), 1)
        self.assertIn("İlk sayfayı okudum", answers[0]["content"])
        self.assertEqual(sched["answered"], 1)

        # Aynı görüşmedeki sonraki mesajlar yeni check-in kaydı üretmez.
        self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "Başka bir şey söyleyeyim mi?",
            "request_id": "checkin-answer-0002",
        })
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE "
                "kind='checkin_answer' AND source_conv=?", (cid,)
            ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_panel_answer_yes_writes_checkin_answer_memory(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]

        status, body, _ = self.request_post("/api/reminders", {
            "action": "answer", "id": rid, "answer": "yes"})
        self.assertEqual(status, 200, body)
        with app.db() as c:
            answers = c.execute(
                "SELECT * FROM memories WHERE kind='checkin_answer' AND "
                "source_conv=?", (cid,)).fetchall()
        self.assertEqual(len(answers), 1)
        self.assertIn("yapıldı", answers[0]["content"])

        # Yinelenen yanıt ikinci kayıt üretmez.
        self.request_post("/api/reminders", {
            "action": "answer", "id": rid, "answer": "yes"})
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM memories WHERE "
                "kind='checkin_answer' AND source_conv=?", (cid,)
            ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_scheduled_message_prompt_asks_how_it_went(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        with app.db() as c:
            c.execute(
                "INSERT INTO scheduled_messages(reminder_id,conv,therapist,"
                "content,status,due_at,is_guest,created,updated) "
                "VALUES(0,?,'adhd','','generating',?,0,'','')",
                (cid, time.time() + 3600))
            sched = c.execute(
                "SELECT * FROM scheduled_messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
        conv = {"id": cid, "therapist": "adhd"}
        reminder = {"task": "Kitap oku", "id": 1}
        system, _ = app.scheduled_message_prompt(conv, reminder, sched)
        self.assertIn("Nasıl geçti?", system)
        self.assertIn("süre sonu kontrolü", system.lower())
        self.assertIn("hafızaya", system.lower())

    def test_reveal_without_generated_message_uses_fallback(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Kitap oku",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, rid))

        status, revealed, _ = self.request_post(
            "/api/reminders/reveal", {"id": rid})
        self.assertEqual(status, 200, revealed)
        self.assertIn("Kitap oku", revealed["message"])
        self.assertTrue(revealed["generating"])
        self.assertIsNone(revealed["message_id"])

    def test_answer_or_delete_discards_pending_scheduled_message(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/reminders", {
            "action": "create", "task": "Silinecek görev",
            "due_at": time.time() + 3600, "source_conv": cid,
        })
        rid = body["reminder"]["id"]

        status, body, _ = self.request_post("/api/reminders", {
            "action": "delete", "id": rid})
        self.assertEqual(status, 200)
        with app.db() as c:
            sched = c.execute(
                "SELECT * FROM scheduled_messages WHERE reminder_id=?",
                (rid,)).fetchone()
        self.assertEqual(sched["status"], "discarded")

    def test_coach_chat_creates_hidden_scheduled_message(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        cid = created["id"]
        status, body, _ = self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "5 dk sonra kitap okumayı hatırlat",
            "request_id": "adhd-sched-request-0001",
        })
        self.assertEqual(status, 200, body)
        with app.db() as c:
            rows = c.execute(
                "SELECT s.* FROM scheduled_messages s "
                "JOIN reminders r ON r.id=s.reminder_id "
                "WHERE r.source_conv=?", (cid,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "generating")
        with app.db() as c:
            visible = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE "
                "client_event_id LIKE 'scheduled-%'").fetchone()["n"]
        self.assertEqual(visible, 0)

    def test_guest_reminders_are_due_scoped_too(self):
        self.request_post("/api/guest-mode", {"active": True})
        reminder = self.create("Misafir iş", 1800)
        with app.db() as c:
            c.execute(
                "UPDATE reminders SET due_at=? WHERE id=?",
                (time.time() - 5, reminder["id"]))

        status, body, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual([row["id"] for row in body["due"]],
                         [reminder["id"]])

        self.request_post("/api/guest-mode", {"active": False})
        status, body, _ = self.request("GET", "/api/reminders/status")
        self.assertEqual(body["due"], [])

    def test_coach_conversation_opens_chats_and_ends_without_map(self):
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "adhd", "mode": "terapi",
        })
        self.assertEqual(status, 200, created)
        cid = created["id"]

        with app.db() as c:
            conv = c.execute(
                "SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            self.assertEqual(conv["therapist"], "adhd")
            self.assertEqual(conv["mode"], "terapi")
            maps = c.execute(
                "SELECT COUNT(*) AS n FROM session_map_targets WHERE conv=?",
                (cid,)).fetchone()["n"]
            self.assertEqual(maps, 0)

        status, body, _ = self.request_post("/api/chat", {
            "conv_id": cid,
            "message": "1 saat sonra bana raporu bitireceğimi hatırlat",
            "request_id": "adhd-test-request-0001",
        })
        self.assertEqual(status, 200, body)
        with app.db() as c:
            latest = c.execute(
                "SELECT id FROM messages WHERE conv=? AND role='user' "
                "ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
        _, payload = app._chat_prompt_payload({
            "conv": cid,
            "user_message": latest["id"],
            "reply_to": None,
            "guidance": "",
            "method_key": None,
            "method_id": None,
            "provider": "deepseek",
            "model": "deepseek-chat",
            "fast": 0,
            "attempt_count": 1,
        })
        joined = "\n".join(str(item["content"]) for item in payload["messages"])
        self.assertIn("KOÇLUK MODU", joined)
        self.assertNotIn("TERAPİ MODU", joined)
        self.assertIn("Hatırlatıcı", joined)

        status, ended, _ = self.request_post(
            "/api/end", {"conv_id": cid})
        self.assertEqual(status, 200, ended)
        self.assertFalse(ended.get("processing"))
        self.assertIsNone(ended.get("job_id"))
        self.assertIn("Hatırlatıcı", ended.get("closing", ""))
        with app.db() as c:
            row = c.execute(
                "SELECT ended FROM conversations WHERE id=?", (cid,)
            ).fetchone()
        self.assertEqual(row["ended"], 1)
