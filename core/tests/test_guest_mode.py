"""Misafir modu testleri.

Misafir oturumu açıkken:
- Yalnız misafir görüşmeleri listelenir/açılır.
- Normal kullanıcının görüşmeleri görünmez ve açılamaz.
- Kişisel yüzeyler (defter, mektuplar, rüyalar, profil, arama) gizlenir.
Misafir modu kapanınca:
- Yalnız misafir görüşmeleri ve türevleri silinir.
- Normal kullanıcının görüşmeleri olduğu gibi kalır.
"""

from support import HTTPTestCase, app


class GuestModeTests(HTTPTestCase):

    def request_post(self, path, payload):
        return self.request("POST", path, payload)

    def make_conversation(self, role="main"):
        status, body, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        self.assertEqual(status, 200, body)
        conv_id = body["id"]
        with app.db() as c:
            c.execute(
                "UPDATE conversations SET is_guest=? WHERE id=?",
                (1 if role == "guest" else 0, conv_id))
            c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (conv_id, "user", "{} mesajı".format(role), app.now()))
        return conv_id

    def test_guest_mode_off_by_default_and_reported_in_settings(self):
        status, body, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertFalse(body["guest_mode"])

        status, bootstrap, _ = self.request("GET", "/api/v1/bootstrap")
        self.assertEqual(status, 200, bootstrap)
        self.assertFalse(bootstrap["settings"]["guest_mode"])

    def test_enter_guest_mode_shows_only_guest_conversations(self):
        main_id = self.make_conversation("main")

        status, body, _ = self.request_post(
            "/api/guest-mode", {"active": True})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["guest_mode"])
        self.assertEqual(body["deleted_guest_conversations"], 0)
        self.assertTrue(app.guest_mode_enabled())

        status, rows, _ = self.request("GET", "/api/conversations")
        self.assertEqual(status, 200)
        self.assertEqual(rows, [])

        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        self.assertEqual(status, 200, created)
        guest_id = created["id"]
        with app.db() as c:
            row = c.execute(
                "SELECT is_guest FROM conversations WHERE id=?",
                (guest_id,)).fetchone()
        self.assertEqual(row["is_guest"], 1)

        status, rows, _ = self.request("GET", "/api/conversations")
        self.assertEqual(status, 200)
        self.assertEqual([r["id"] for r in rows], [guest_id])

        # Normal kullanıcının görüşmesi misafire yokmuş gibi davranmalı.
        status, detail, _ = self.request(
            "GET", "/api/conversation?id={}".format(main_id))
        self.assertEqual(status, 404)
        status, detail, _ = self.request(
            "GET", "/api/conversation?id={}".format(guest_id))
        self.assertEqual(status, 200, detail)

    def test_guest_cannot_write_or_mutate_main_conversations(self):
        main_id = self.make_conversation("main")
        self.request_post("/api/guest-mode", {"active": True})

        status, body, _ = self.request_post("/api/chat", {
            "conv_id": main_id,
            "message": "misafirden mesaj",
            "request_id": "guest-test-request-0001",
        })
        self.assertEqual(status, 404)

        status, body, _ = self.request_post(
            "/api/archive", {"id": main_id, "archived": True})
        self.assertEqual(status, 404)

        status, body, _ = self.request_post(
            "/api/delete", {"id": main_id})
        self.assertEqual(status, 404)

    def test_exit_guest_mode_deletes_only_guest_conversations(self):
        main_id = self.make_conversation("main")
        self.request_post("/api/guest-mode", {"active": True})
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        guest_id = created["id"]
        with app.db() as c:
            c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (guest_id, "user", "misafir notu", app.now()))

        status, body, _ = self.request_post(
            "/api/guest-mode", {"active": False})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["guest_mode"])
        self.assertEqual(body["deleted_guest_conversations"], 1)
        self.assertFalse(app.guest_mode_enabled())

        with app.db() as c:
            main_row = c.execute(
                "SELECT id FROM conversations WHERE id=?", (main_id,)
            ).fetchone()
            guest_row = c.execute(
                "SELECT id FROM conversations WHERE id=?", (guest_id,)
            ).fetchone()
            main_messages = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (main_id,)).fetchone()["n"]
            guest_messages = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (guest_id,)).fetchone()["n"]
        self.assertIsNotNone(main_row)
        self.assertIsNone(guest_row)
        self.assertEqual(main_messages, 1)
        self.assertEqual(guest_messages, 0)

        status, rows, _ = self.request("GET", "/api/conversations")
        self.assertEqual(status, 200)
        self.assertEqual([r["id"] for r in rows], [main_id])

    def test_guest_mode_persists_across_restart_until_closed(self):
        self.request_post("/api/guest-mode", {"active": True})
        self.assertTrue(app.guest_mode_enabled())
        # Ayar tablosunda durur; yeniden başlatma simülasyonu için yalnız
        # ayar değerini oku.
        self.assertEqual(app.get_setting("guest_mode"), "1")

    def test_personal_surfaces_are_empty_for_guest(self):
        main_id = self.make_conversation("main")
        app.set_setting("profile", "kullanıcının özel profili")
        with app.db() as c:
            c.execute(
                "INSERT INTO notes(conv,mode,content,created) "
                "VALUES(?,?,?,?)",
                (main_id, "terapi", "özel defter notu", app.now()))

        self.request_post("/api/guest-mode", {"active": True})

        status, profile, _ = self.request("GET", "/api/profile")
        self.assertEqual(status, 200)
        self.assertEqual(profile["profile"], "")

        status, notes, _ = self.request(
            "GET", "/api/notes?mode=terapi&therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(notes["notes"], [])
        self.assertEqual(notes["formulations"], [])

        status, letters, _ = self.request(
            "GET", "/api/letters?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(letters["letters"], [])
        self.assertEqual(letters["referrals"], [])

        status, dreams, _ = self.request(
            "GET", "/api/dreams?therapist=freud")
        self.assertEqual(status, 200)
        self.assertEqual(dreams["dreams"], [])
        self.assertIsNone(dreams["analysis"])

        status, search, _ = self.request(
            "GET", "/api/search?q=mesajı")
        self.assertEqual(status, 200)
        self.assertEqual(search["results"], [])

    def test_guest_search_finds_only_guest_messages(self):
        self.make_conversation("main")
        self.request_post("/api/guest-mode", {"active": True})
        status, created, _ = self.request("POST", "/api/new", {
            "therapist": "freud", "mode": "terapi",
        })
        guest_id = created["id"]
        with app.db() as c:
            c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (guest_id, "user", "misafire özel sır", app.now()))

        status, search, _ = self.request(
            "GET", "/api/search?q=misafire özel")
        self.assertEqual(status, 200)
        self.assertEqual(len(search["results"]), 1)
        self.assertEqual(search["results"][0]["conv"], guest_id)

    def test_invalid_guest_mode_payload_is_rejected(self):
        status, body, _ = self.request_post(
            "/api/guest-mode", {"active": "belki"})
        self.assertEqual(status, 400)

    def test_idempotent_toggle_does_not_delete(self):
        main_id = self.make_conversation("main")
        self.request_post("/api/guest-mode", {"active": True})
        status, body, _ = self.request_post(
            "/api/guest-mode", {"active": True})
        self.assertEqual(status, 200, body)
        with app.db() as c:
            row = c.execute(
                "SELECT id FROM conversations WHERE id=?", (main_id,)
            ).fetchone()
        self.assertIsNotNone(row)
