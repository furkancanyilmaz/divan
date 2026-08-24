import json
from pathlib import Path
from urllib.parse import urlencode

from support import HTTPTestCase, app


class SafetyReviewUISourceTests(HTTPTestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = Path(app.DIR, "index.html").read_text(encoding="utf-8")

    def test_banner_offers_calm_explicit_reassessment(self):
        self.assertIn('id="safetyReviewOpen"', self.source)
        self.assertIn('id="safetyReviewOverlay"', self.source)
        for status in ("safe_now", "false_alarm", "not_sure", "unsafe_now"):
            self.assertIn(f'value="{status}"', self.source)
        overlay_start = self.source.index('id="safetyReviewOverlay"')
        overlay_end = self.source.index('</div></div>', overlay_start)
        overlay = self.source[overlay_start:overlay_end]
        self.assertIn("Önceki kayıt silinmez", overlay)
        self.assertNotIn("olay silindi", overlay.casefold())

    def test_review_payload_is_user_confirmed_and_updates_open_conversation(self):
        start = self.source.index("async function submitSafetyReview()")
        end = self.source.index("function updateTopButtons()", start)
        body = self.source[start:end]
        self.assertIn("conv_id:Number(convId),action:'reassess'", body)
        self.assertIn("current_status:currentStatus,confirmed:true", body)
        self.assertIn("if(note)payload.note=note", body)
        self.assertIn("await api('/api/safety-hold/review',payload)", body)
        self.assertIn("setConversationSafetyHold(hold)", body)
        self.assertIn("['not_sure','unsafe_now'].includes(currentStatus)", body)
        self.assertIn("önceki olay kaydı korunarak", body)

    def test_safety_hold_does_not_gate_session_closure(self):
        start = self.source.index("function canEndCurrentConversation()")
        end = self.source.index("function syncComposerQuickMenu()", start)
        self.assertNotIn("safety_hold", self.source[start:end])


class SafetyBoundaryHTTPTests(HTTPTestCase):

    def test_clause_level_negation_time_and_person_boundaries(self):
        safe_statements = (
            "Şu anda kendime zarar vermeyeceğim.",
            "Kendime zarar vermek istemiyorum.",
            "Şu anda kendime zarar vermeyi düşünmüyorum.",
            "Kendime zarar vermeye niyetim yok.",
            "Dün keşke ölsem dedim ama şimdi daha iyiyim.",
        )
        for statement in safe_statements:
            with self.subTest(statement=statement):
                self.assertFalse(
                    app.user_text_safety_gate(statement)["detected"])

        mixed = app.user_text_safety_gate(
            "İntihar etmeyeceğim, sadece keşke ölsem")
        self.assertTrue(mixed["detected"])
        self.assertEqual(mixed["kind"], "self_harm")
        self.assertEqual(mixed["clause_index"], 1)

        inherited = app.user_text_safety_gate(
            "Dün kendime zarar vermeyi düşünüyordum ama şimdi yine istiyorum.")
        self.assertTrue(inherited["detected"])
        self.assertTrue(inherited["inherited_topic"])

        other = app.user_text_safety_gate("Annem 'keşke ölsem' diyor")
        self.assertTrue(other["detected"])
        self.assertEqual(other["kind"], "other_person_self_harm")

    def test_declared_intensity_limit_is_a_hard_boundary(self):
        conv_id = self.conversation(therapist="young")
        status, _, _ = self.request(
            "POST", "/api/session-meta",
            {"conv_id": conv_id, "precheck_done": True,
             "intensity_limit": 5})
        self.assertEqual(status, 200)
        method = app.method_records("young")[0]

        status, body, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose",
             "method_key": method["key"], "intensity": 6})
        self.assertEqual(status, 409)
        self.assertIn("sınır", body["error"].casefold())
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
                (conv_id,))["n"],
            0)

        status, proposed, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose",
             "method_key": method["key"], "intensity": 5})
        self.assertEqual(status, 200)
        run_id = proposed["run"]["id"]
        status, _, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "consent",
             "confirmed": True})
        self.assertEqual(status, 200)

        status, body, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "id": run_id, "action": "intensity",
             "intensity": 6})
        self.assertEqual(status, 409)
        self.assertIn("sınır", body["error"].casefold())
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual(run["intensity_current"], 5)

    def test_crisis_sets_persistent_safety_hold_and_blocks_new_techniques(self):
        conv_id = self.conversation(therapist="young")
        status, crisis, _ = self.request(
            "POST", "/api/chat",
            {"conv_id": conv_id,
             "message": "Kendime zarar vermek istiyorum"})
        self.assertEqual(status, 200)
        self.assertTrue(crisis["crisis"])
        self.assertTrue(crisis["safety_hold"])

        status, opened, _ = self.request(
            "GET", "/api/conversation?" + urlencode({"id": conv_id}))
        self.assertEqual(status, 200)
        self.assertEqual(opened["conversation"]["safety_hold"], 1)

        status, body, _ = self.request(
            "POST", "/api/technique-run",
            {"conv_id": conv_id, "action": "propose",
             "method_key": app.method_records("young")[0]["key"],
             "intensity": 2})
        self.assertEqual(status, 409)
        self.assertTrue(
            any(word in body["error"].casefold()
                for word in ("güven", "kriz", "destek")))
        self.assertIsNone(app.current_technique_run(conv_id))

        event = self.row(
            "SELECT * FROM safety_events WHERE conv=? ORDER BY id DESC LIMIT 1",
            (conv_id,))
        self.assertEqual(event["status"], "active")
        self.assertEqual(event["kind"], "self_harm")
        self.assertIsNotNone(event["source_message"])

    def test_explicit_reassessment_releases_hold_but_keeps_event_and_review(self):
        conv_id = self.conversation(therapist="young")
        status, crisis, _ = self.request(
            "POST", "/api/chat",
            {"conv_id": conv_id,
             "message": "Kendime zarar vermek istiyorum"})
        self.assertEqual(status, 200, crisis)
        event = self.row(
            "SELECT * FROM safety_events WHERE conv=? ORDER BY id DESC LIMIT 1",
            (conv_id,))

        status, blocked, _ = self.request(
            "POST", "/api/safety-hold/review",
            {"conv_id": conv_id, "action": "reassess",
             "event_id": event["id"], "current_status": "false_alarm"})
        self.assertEqual(status, 400, blocked)
        self.assertEqual(self.conversation_row(conv_id)["safety_hold"], 1)

        status, released, _ = self.request(
            "POST", "/api/safety-hold/review",
            {"conv_id": conv_id, "action": "reassess",
             "event_id": event["id"], "current_status": "false_alarm",
             "confirmed": True, "note": "Sözüm olumsuz bağlamdaydı."})
        self.assertEqual(status, 200, released)
        self.assertFalse(released["safety_hold"])
        self.assertIn("kayıtlı kaldı", released["message"])
        self.assertEqual(self.conversation_row(conv_id)["safety_hold"], 0)

        preserved = self.row(
            "SELECT * FROM safety_events WHERE id=?", (event["id"],))
        review = self.row(
            "SELECT * FROM safety_event_reviews WHERE safety_event=?",
            (event["id"],))
        self.assertEqual(preserved["status"], "released")
        self.assertIsNotNone(preserved["resolved_at"])
        self.assertEqual(review["outcome"], "false_alarm")
        self.assertEqual(review["note"], "Sözüm olumsuz bağlamdaydı.")

    def test_uncertain_reassessment_preserves_hold(self):
        conv_id = self.conversation(therapist="young")
        self.request(
            "POST", "/api/chat",
            {"conv_id": conv_id,
             "message": "Kendime zarar vermek istiyorum"})

        status, body, _ = self.request(
            "POST", "/api/safety-hold/review",
            {"conv_id": conv_id, "current_status": "not_sure",
             "confirmed": True})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["safety_hold"])
        self.assertEqual(self.conversation_row(conv_id)["safety_hold"], 1)


class SourcedConversationHTTPTests(HTTPTestCase):

    def assert_source_pack(self, sources):
        self.assertIsInstance(sources, list)
        self.assertGreater(len(sources), 0)
        for source in sources:
            self.assertTrue(source["title"].strip())
            self.assertTrue(source["url"].startswith("https://"))

    def test_new_case_and_reopened_conversation_return_title_and_sources(self):
        case = next(
            item for item in app.CASE_LIBRARY if item["id"] == "dora")
        status, created, _ = self.request(
            "POST", "/api/new",
            {"case_id": case["id"], "source_mode": True})
        self.assertEqual(status, 200)
        self.assertEqual(created["title"], case["title"])
        self.assert_source_pack(created["sources"])

        conv_id = created["id"]
        saved = self.conversation_row(conv_id)
        self.assertEqual(saved["title"], case["title"])
        self.assertEqual(saved["case_id"], case["id"])
        self.assertEqual(saved["source_mode"], 1)

        status, reopened, _ = self.request(
            "GET", "/api/conversation?" + urlencode({"id": conv_id}))
        self.assertEqual(status, 200)
        self.assertEqual(reopened["conversation"]["title"], case["title"])
        self.assert_source_pack(reopened["sources"])
        self.assertEqual(
            [source["url"] for source in reopened["sources"]],
            [source["url"] for source in created["sources"]])


class NonDestructiveHTTPRegressionTests(HTTPTestCase):

    def test_profile_and_session_frame_updates_do_not_cancel_inflight_work(self):
        conv_id = self.conversation()
        generation = app.data_generation()

        status, _, _ = self.request(
            "POST", "/api/profile", {"profile": "Yeni sabit bilgi"})
        self.assertEqual(status, 200)
        self.assertEqual(app.data_generation(), generation)

        status, _, _ = self.request(
            "POST", "/api/session-meta",
            {"conv_id": conv_id, "focus": "Bugünkü odak"})
        self.assertEqual(status, 200)
        self.assertEqual(app.data_generation(), generation)

    def test_withdrawing_summary_approval_clears_session_frame_copy(self):
        conv_id = self.conversation()
        status, _, _ = self.request(
            "POST", "/api/session-meta",
            {"conv_id": conv_id, "summary": "Artık kullanılmamalı"})
        self.assertEqual(status, 200)
        self.assertEqual(
            self.row(
                "SELECT status FROM session_summaries WHERE conv=?",
                (conv_id,))["status"],
            "approved")

        status, _, _ = self.request(
            "POST", "/api/session-summary",
            {"conv_id": conv_id, "action": "update",
             "content": "Onay bekleyen yeni taslak"})
        self.assertEqual(status, 200)
        summary = self.row(
            "SELECT * FROM session_summaries WHERE conv=?", (conv_id,))
        meta = self.row(
            "SELECT * FROM session_meta WHERE conv=?", (conv_id,))
        self.assertEqual(summary["status"], "pending")
        self.assertEqual(summary["approved_content"], "")
        self.assertEqual(meta["summary"], "")

    def test_global_diagnostics_is_safe_without_an_open_conversation(self):
        app.set_setting("api_key", "API-ANAHTARI-GÖRÜNMEMELİ")
        app.set_setting("profile", "PROFİL-METNİ-GÖRÜNMEMELİ")

        status, diagnostics, _ = self.request("GET", "/api/diagnostics")

        self.assertEqual(status, 200)
        self.assertIsNone(diagnostics["conversation"])
        self.assertTrue(diagnostics["content_redacted"])
        self.assertEqual(diagnostics["version"], app.VERSION)
        rendered = json.dumps(diagnostics, ensure_ascii=False)
        self.assertNotIn("API-ANAHTARI-GÖRÜNMEMELİ", rendered)
        self.assertNotIn("PROFİL-METNİ-GÖRÜNMEMELİ", rendered)
