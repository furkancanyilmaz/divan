from unittest import mock

from support import HTTPTestCase, app


class MemoryAndSummaryTests(HTTPTestCase):

    def test_memory_requires_approval_and_respects_scope_and_sensitivity(self):
        freud_conv = self.conversation(therapist="freud")
        jung_conv = self.conversation(therapist="jung")

        status, created, _ = self.request(
            "POST", "/api/memory",
            {"therapist": "freud", "content": "yalnız onaydan sonra",
             "approved": False})
        self.assertEqual(status, 200)
        memory_id = created["memory"]["id"]
        self.assertNotIn("yalnız onaydan sonra",
                         self.system_prompt(freud_conv))

        status, approved, _ = self.request(
            "POST", "/api/memory",
            {"id": memory_id, "approved": True})
        self.assertEqual(status, 200)
        self.assertEqual(approved["memory"]["approved"], 1)
        self.assertIn("yalnız onaydan sonra",
                      self.system_prompt(freud_conv))
        self.assertNotIn("yalnız onaydan sonra",
                         self.system_prompt(jung_conv))

        status, shared, _ = self.request(
            "POST", "/api/memory",
            {"therapist": "freud", "content": "paylaşmayı onayladım",
             "approved": True, "scope": "shared"})
        self.assertEqual(status, 200)
        self.assertEqual(shared["memory"]["scope"], "shared")
        self.assertIn("paylaşmayı onayladım", self.system_prompt(jung_conv))

        status, sensitive, _ = self.request(
            "POST", "/api/memory",
            {"therapist": "freud", "content": "çok hassas bilgi",
             "approved": True, "scope": "shared", "sensitive": True})
        self.assertEqual(status, 200)
        self.assertEqual(sensitive["memory"]["scope"], "therapist")
        self.assertNotIn("çok hassas bilgi", self.system_prompt(jung_conv))

        status, excluded, _ = self.request(
            "POST", "/api/memory",
            {"therapist": "freud", "content": "promptta görünmemeli",
             "approved": True, "scope": "excluded"})
        self.assertEqual(status, 200)
        self.assertNotIn("promptta görünmemeli",
                         self.system_prompt(freud_conv))

    def test_memory_edit_and_forget_change_context_immediately(self):
        conv_id = self.conversation()
        _, created, _ = self.request(
            "POST", "/api/memory",
            {"content": "ilk sürüm", "approved": True})
        memory_id = created["memory"]["id"]

        status, edited, _ = self.request(
            "POST", "/api/memory",
            {"id": memory_id, "content": "düzeltilmiş sürüm"})
        self.assertEqual(status, 200)
        self.assertEqual(edited["memory"]["content"], "düzeltilmiş sürüm")
        prompt = self.system_prompt(conv_id)
        self.assertIn("düzeltilmiş sürüm", prompt)
        self.assertNotIn("ilk sürüm", prompt)

        status, _, _ = self.request(
            "POST", "/api/memory/delete", {"id": memory_id})
        self.assertEqual(status, 200)
        self.assertNotIn("düzeltilmiş sürüm",
                         self.system_prompt(conv_id))
        status, _, _ = self.request(
            "POST", "/api/memory/delete", {"id": memory_id})
        self.assertEqual(status, 404)

    def test_note_control_prevents_unapproved_or_sensitive_cross_therapist_context(self):
        source = self.conversation(therapist="freud", title="Kaynak")
        jung_conv = self.conversation(therapist="jung")
        with app.db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes(conv,mode,therapist,content,created,"
                "approved,scope,sensitive,updated) VALUES("
                "?,'terapi','freud','paylaşılan not','2026-07-20',"
                "1,'shared',0,'2026-07-20')", (source,)).lastrowid
        self.assertIn("paylaşılan not", self.system_prompt(jung_conv))

        status, body, _ = self.request(
            "POST", "/api/note-control",
            {"id": note_id, "sensitive": True, "scope": "shared"})
        self.assertEqual(status, 200)
        self.assertEqual(body["note"]["scope"], "therapist")
        self.assertNotIn("paylaşılan not", self.system_prompt(jung_conv))

        status, _, _ = self.request(
            "POST", "/api/note-control",
            {"id": note_id, "approved": False})
        self.assertEqual(status, 200)
        freud_new = self.conversation(therapist="freud")
        self.assertNotIn("paylaşılan not", self.system_prompt(freud_new))

    def test_summary_is_not_injected_until_user_approves_edited_text(self):
        old_conv = self.conversation(title="Önceki seans")
        new_conv = self.conversation(title="Yeni seans 2")
        self.messages(old_conv, 4)
        with mock.patch.object(app, "ds_complete_continued",
                               return_value="model taslağı"):
            self.assertEqual(app.make_summary(old_conv), "model taslağı")

        self.assertNotIn("model taslağı", self.system_prompt(new_conv))
        status, body, _ = self.request(
            "POST", "/api/session-summary",
            {"conv_id": old_conv, "action": "approve",
             "content": "kullanıcının düzelttiği özet"})
        self.assertEqual(status, 200)
        self.assertEqual(body["summary"]["status"], "approved")
        prompt = self.system_prompt(new_conv)
        self.assertIn("kullanıcının düzelttiği özet", prompt)
        self.assertNotIn("model taslağı", prompt)

        status, _, _ = self.request(
            "POST", "/api/session-summary",
            {"conv_id": old_conv, "action": "reject"})
        self.assertEqual(status, 200)
        self.assertNotIn("kullanıcının düzelttiği özet",
                         self.system_prompt(new_conv))

    def test_manual_session_summary_is_approved_and_shared_only_with_same_context(self):
        therapy_freud = self.conversation(
            mode="terapi", therapist="freud", title="Özetli")
        therapy_freud_next = self.conversation(
            mode="terapi", therapist="freud")
        lesson_freud = self.conversation(
            mode="ders", therapist="freud")
        therapy_jung = self.conversation(
            mode="terapi", therapist="jung")

        status, _, _ = self.request(
            "POST", "/api/session-meta",
            {"conv_id": therapy_freud, "summary": "benim onaylı özetim"})
        self.assertEqual(status, 200)
        saved = self.row(
            "SELECT * FROM session_summaries WHERE conv=?",
            (therapy_freud,))
        self.assertEqual(saved["status"], "approved")
        self.assertIn("benim onaylı özetim",
                      self.system_prompt(therapy_freud_next))
        self.assertNotIn("benim onaylı özetim",
                         self.system_prompt(lesson_freud))
        self.assertNotIn("benim onaylı özetim",
                         self.system_prompt(therapy_jung))
