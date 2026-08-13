import unittest

from support import HTTPTestCase, app


class HypothesisDecisionV2Tests(HTTPTestCase):

    def _hypothesis(self, text="Sınanmamış örüntü"):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            cur = c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) "
                "VALUES(?,'freud',?,'active',1,?,?)",
                (conv_id, text, app.now(), app.now()))
            return conv_id, cur.lastrowid

    def test_emin_degilim_keeps_hypothesis_undecided_and_out_of_prompt(self):
        conv_id, hypothesis_id = self._hypothesis()
        status, body, _ = self.request(
            "POST", "/api/hypothesis/decision",
            {"id": hypothesis_id, "decision": "emin_degilim"})
        self.assertEqual(status, 200, body)
        with app.db() as c:
            row = c.execute(
                "SELECT * FROM hypotheses WHERE id=?", (hypothesis_id,)
            ).fetchone()
        self.assertEqual(row["user_decision"], "emin_degilim")
        self.assertEqual(row["status"], "undecided")
        status, body, _ = self.request(
            "GET", "/api/inbox?therapist=freud")
        self.assertEqual(len(body["hypotheses"]), 0)
        prompt = self.system_prompt(conv_id)
        self.assertNotIn("Sınanmamış örüntü", prompt)

    def test_hafizaya_al_creates_approved_memory_and_closes_hypothesis(self):
        conv_id, hypothesis_id = self._hypothesis("Belleğe alınacak örüntü")
        status, body, _ = self.request(
            "POST", "/api/hypothesis/memory", {"id": hypothesis_id})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["memory_id"], 1)
        with app.db() as c:
            memory = c.execute(
                "SELECT * FROM memories WHERE id=?", (body["memory_id"],)
            ).fetchone()
            hypothesis = c.execute(
                "SELECT * FROM hypotheses WHERE id=?", (hypothesis_id,)
            ).fetchone()
        self.assertIsNotNone(memory)
        self.assertEqual(memory["content"], "Belleğe alınacak örüntü")
        # Anı yalnız açık kullanıcı kararıyla onaylıdır.
        self.assertEqual(memory["approved"], 1)
        self.assertEqual(hypothesis["user_decision"], "hafiza")
        status, body, _ = self.request(
            "GET", "/api/inbox?therapist=freud")
        self.assertEqual(len(body["hypotheses"]), 0)
        self.assertIn("Belleğe alınacak örüntü",
                      self.system_prompt(conv_id))

    def test_delete_removes_hypothesis_and_evidence(self):
        conv_id, hypothesis_id = self._hypothesis()
        with app.db() as c:
            cur = c.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user','kanıt cümlesi',?)",
                (conv_id, app.now()))
            c.execute(
                "INSERT INTO hypothesis_evidence(hypothesis,kind,quote,"
                "message_id,created) VALUES(?,'supports','kanıt',?,?)",
                (hypothesis_id, cur.lastrowid, app.now()))
        status, body, _ = self.request(
            "POST", "/api/hypothesis/delete", {"id": hypothesis_id})
        self.assertEqual(status, 200, body)
        with app.db() as c:
            self.assertIsNone(c.execute(
                "SELECT id FROM hypotheses WHERE id=?",
                (hypothesis_id,)).fetchone())
            self.assertIsNone(c.execute(
                "SELECT id FROM hypothesis_evidence WHERE hypothesis=?",
                (hypothesis_id,)).fetchone())

    def test_unknown_decision_rejected(self):
        _, hypothesis_id = self._hypothesis()
        status, body, _ = self.request(
            "POST", "/api/hypothesis/decision",
            {"id": hypothesis_id, "decision": "belki"})
        self.assertEqual(status, 400)


class MemoryApprovalTests(HTTPTestCase):

    def test_memory_without_explicit_approval_stays_out_of_prompt(self):
        conv_id = self.conversation(therapist="freud")
        status, body, _ = self.request(
            "POST", "/api/memory",
            {"therapist": "freud", "content": "Onaysız kayıt",
             "scope": "therapist"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["memory"]["approved"], 0)
        prompt = self.system_prompt(conv_id)
        self.assertNotIn("Onaysız kayıt", prompt)

    def test_memory_with_explicit_approval_enters_prompt(self):
        conv_id = self.conversation(therapist="freud")
        status, body, _ = self.request(
            "POST", "/api/memory",
            {"therapist": "freud", "content": "Onaylı kayıt",
             "scope": "therapist", "approved": True})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["memory"]["approved"], 1)
        self.assertIn("Onaylı kayıt", self.system_prompt(conv_id))


class MidpassEvidenceDedupTests(HTTPTestCase):

    def test_same_quote_is_not_recorded_twice(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            cur = c.execute(
                "INSERT INTO hypotheses(conv,therapist,text,status,"
                "through_message_id,created,updated) VALUES("
                "?,'freud','Yinelenen kanıt örüntüsü','active',1,?,?)",
                (conv_id, app.now(), app.now()))
            hypothesis_id = cur.lastrowid
        app._seed_messages_for_test = None
        with app.db() as c:
            for index in range(12):
                c.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "user" if index % 2 == 0 else "assistant",
                     "aynı alıntı burada duruyor" if index == 0
                     else "mesaj-{}".format(index), app.now()))
        raw = json_dumps_midpass(hypothesis_id)
        with unittest.mock.patch.object(app, "ds_complete",
                                        return_value=raw):
            app.run_session_midpass(conv_id)
            app.run_session_midpass(conv_id)
        with app.db() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM hypothesis_evidence WHERE "
                "hypothesis=?", (hypothesis_id,)).fetchone()["n"]
        self.assertEqual(count, 1)


def json_dumps_midpass(hypothesis_id):
    import json
    return json.dumps({
        "hypotheses": [],
        "evidence": [{
            "hypothesis_id": hypothesis_id,
            "supports": ["aynı alıntı burada duruyor"],
            "against": [],
            "alternatives": [],
            "falsification": "",
            "context_note": "",
        }],
    }, ensure_ascii=False)


class SessionPulseAftermathTests(HTTPTestCase):

    def _pulse(self, conv_id, **extra):
        payload = {
            "conv_id": conv_id, "action": "record", "phase": "end",
            "understood": 7, "goal_owned": 7, "method_fit": 7,
            "pace_safe": 7,
        }
        payload.update(extra)
        return self.request("POST", "/api/session-pulse", payload)

    def test_missed_and_aftermath_fields_are_stored(self):
        conv_id = self.conversation(therapist="freud")
        status, body, _ = self._pulse(
            conv_id, missed="Öfke konusunu atladık",
            over_activated=True, after_worsening=False, control_loss=True)
        self.assertEqual(status, 200, body)
        pulse = body["pulse"]
        self.assertEqual(pulse["missed"], "Öfke konusunu atladık")
        self.assertTrue(pulse["over_activated"])
        self.assertFalse(pulse["after_worsening"])
        self.assertTrue(pulse["control_loss"])

    def test_aftermath_flags_must_be_boolean(self):
        conv_id = self.conversation(therapist="freud")
        status, body, _ = self._pulse(conv_id, over_activated="evet")
        self.assertEqual(status, 400)

    def test_aftermath_appears_in_progress(self):
        conv_id = self.conversation(therapist="freud")
        status, body, _ = self._pulse(
            conv_id, over_activated=True, control_loss=True)
        self.assertEqual(status, 200, body)
        status, progress, _ = self.request("GET", "/api/progress")
        self.assertEqual(status, 200)
        self.assertTrue(progress["aftermath"]["over_activated"])
        self.assertTrue(progress["aftermath"]["control_loss"])


class MeasureRadarTests(HTTPTestCase):

    def _save_measures(self, measures):
        return self.request("POST", "/api/measures",
                            {"measures": measures})

    def _checkin(self, **scores):
        return self.request("POST", "/api/checkin", scores)

    def test_measures_config_roundtrip(self):
        status, body, _ = self._save_measures([
            {"measure_key": "kaygi", "kind": "symptom", "label": "Kaygı"},
            {"measure_key": "uyku", "kind": "function", "label": "Uyku"},
            {"measure_key": "hedef", "kind": "goal", "label": "Kişisel hedef"},
        ])
        self.assertEqual(status, 200, body)
        self.assertEqual(len(body["measures"]), 3)
        status, body, _ = self.request("GET", "/api/measures")
        self.assertEqual(len(body["measures"]), 3)

    def test_measures_config_rejects_invalid_kind_and_duplicates(self):
        status, body, _ = self._save_measures([
            {"measure_key": "a", "kind": "huy", "label": "A"}])
        self.assertEqual(status, 400)
        status, body, _ = self._save_measures([
            {"measure_key": "a", "kind": "goal", "label": "A"},
            {"measure_key": "a", "kind": "goal", "label": "A2"}])
        self.assertEqual(status, 400)

    def test_radar_worsening_for_symptom_and_improving_for_goal(self):
        self._save_measures([
            {"measure_key": "kaygi", "kind": "symptom", "label": "Kaygı"},
            {"measure_key": "hedef", "kind": "goal", "label": "Kişisel hedef"},
        ])
        self._checkin(symptom_score=3, goal_score=4)
        self._checkin(symptom_score=6, goal_score=8)
        status, body, _ = self.request("GET", "/api/progress")
        self.assertEqual(status, 200)
        radar = {item["key"]: item for item in body["radar"]}
        self.assertEqual(radar["kaygi"]["status"], "possible_worsening")
        self.assertEqual(
            radar["kaygi"]["status_label"],
            "Güvenilir kötüleşme olabilir")
        self.assertTrue(radar["kaygi"]["worsening"])
        self.assertEqual(radar["hedef"]["status"], "improving")
        self.assertEqual(radar["hedef"]["status_label"], "Yolunda gidiyor")

    def test_radar_requires_two_records_and_reports_no_change(self):
        self._save_measures([
            {"measure_key": "uyku", "kind": "function", "label": "Uyku"}])
        self._checkin(function_score=5)
        status, body, _ = self.request("GET", "/api/progress")
        radar = {item["key"]: item for item in body["radar"]}
        self.assertEqual(radar["uyku"]["status"], "unclear")
        self._checkin(function_score=5)
        status, body, _ = self.request("GET", "/api/progress")
        radar = {item["key"]: item for item in body["radar"]}
        self.assertEqual(radar["uyku"]["status"], "no_change")

    def test_measure_due_after_two_ended_sessions(self):
        self._save_measures([
            {"measure_key": "uyku", "kind": "function", "label": "Uyku"}])
        status, body, _ = self.request("GET", "/api/progress")
        self.assertFalse(body["measure_due"])
        with app.db() as c:
            for index in range(2):
                c.execute(
                    "INSERT INTO conversations(mode,therapist,title,ended,"
                    "created,updated) VALUES('terapi','freud','Eski seans',"
                    "1,?,?)",
                    (app.now(), app.now()))
        status, body, _ = self.request("GET", "/api/progress")
        self.assertTrue(body["measure_due"])

    def test_checkin_rejects_out_of_range_measure_scores(self):
        status, body, _ = self._checkin(symptom_score=11)
        self.assertEqual(status, 400)


class WorkFollowupTests(HTTPTestCase):

    def _completed_chair(self, conv_id, ended=0):
        with app.db() as c:
            if ended:
                c.execute(
                    "UPDATE conversations SET ended=1 WHERE id=?", (conv_id,))
            c.execute(
                "UPDATE conversations SET safety_hold=0 WHERE id=?", (conv_id,))
            cur = c.execute(
                "INSERT INTO technique_runs(conv,therapist,method_key,"
                "method_name,status,phase,consent_at,"
                "intensity_start,intensity_current,created,updated) "
                "VALUES(?,'freud','chair','Sandalye',"
                "'completed','end',?,4,3,?,?)",
                (conv_id, app.now(), app.now(), app.now()))
            technique_id = cur.lastrowid
            cur = c.execute(
                "INSERT INTO chair_runs(conv,therapist,technique_run,"
                "method_node_id,protocol,protocol_version,current_stage,"
                "stop_signal,goal_text,effect_rating,effect_note,"
                "followup_due,created,updated) VALUES("
                "?,'freud',?,'perls:method:empty-chair','empty_chair',2,'',"
                "'dur','Amaç',6,'İyi geldi',?,?,?)",
                (conv_id, technique_id, app.followup_due_stamp(),
                 app.now(), app.now()))
            return cur.lastrowid

    def test_followup_listed_and_recorded_once(self):
        conv_id = self.conversation(therapist="freud")
        chair_id = self._completed_chair(conv_id, ended=1)
        status, body, _ = self.request("GET", "/api/work-followups")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["followups"]), 1)
        self.assertEqual(body["followups"][0]["run_type"], "chair")
        status, body, _ = self.request(
            "POST", "/api/chair-work",
            {"conv_id": conv_id, "chair_run_id": chair_id,
             "action": "followup",
             "followup_effect": 3,
             "followup_note": "Ertesi gün daha sakindim",
             "sleep_worse": False})
        self.assertEqual(status, 200, body)
        followup = body["chairwork"]["followup"]
        self.assertEqual(followup["effect"], 3)
        self.assertEqual(followup["note"], "Ertesi gün daha sakindim")
        status, body, _ = self.request(
            "POST", "/api/chair-work",
            {"conv_id": conv_id, "chair_run_id": chair_id,
             "action": "followup", "followup_effect": 5})
        self.assertEqual(status, 409)
        status, body, _ = self.request("GET", "/api/work-followups")
        self.assertEqual(len(body["followups"]), 0)

    def test_followup_requires_planned_due_date(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute(
                "INSERT INTO technique_runs(conv,therapist,method_key,"
                "method_name,status,phase,consent_at,"
                "intensity_start,intensity_current,created,updated) "
                "VALUES(?,'freud','chair','Sandalye',"
                "'completed','end',?,4,3,?,?)",
                (conv_id, app.now(), app.now(), app.now()))
            technique_id = c.execute(
                "SELECT id FROM technique_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
            cur = c.execute(
                "INSERT INTO chair_runs(conv,therapist,technique_run,"
                "method_node_id,protocol,protocol_version,current_stage,"
                "created,updated) VALUES(?,'freud',?,"
                "'perls:method:empty-chair',"
                "'empty_chair',2,'',?,?)",
                (conv_id, technique_id, app.now(), app.now()))
            chair_id = cur.lastrowid
        status, body, _ = self.request(
            "POST", "/api/chair-work",
            {"conv_id": conv_id, "chair_run_id": chair_id,
             "action": "followup", "followup_effect": 5})
        self.assertEqual(status, 409)

    def test_followup_on_open_conversation_rejected_for_non_followup(self):
        conv_id = self.conversation(therapist="freud")
        with app.db() as c:
            c.execute("UPDATE conversations SET ended=1 WHERE id=?", (conv_id,))
        status, body, _ = self.request(
            "POST", "/api/chair-work",
            {"conv_id": conv_id, "action": "begin"})
        self.assertEqual(status, 409)


class PsychPrepTransferV2Tests(HTTPTestCase):

    def _save_sections(self):
        return self.request("POST", "/api/psych-prep", {
            "sections": {
                "reason": "Altı aydır uykusuzluk ve kaygı.",
                "medical": "Migren takibi sürüyor.",
                "safety": "Yalnız kalınca sıkıntı artıyor.",
                "goals": "İlaç seçeneklerini öğrenmek istiyorum.",
                "methods_effects": "Nefes çalışması kısmen işe yaradı.",
            }})

    def test_new_sections_saved_and_returned(self):
        status, body, _ = self._save_sections()
        self.assertEqual(status, 200, body)
        status, body, _ = self.request("GET", "/api/psych-prep")
        self.assertEqual(status, 200)
        self.assertEqual(body["sections"]["medical"], "Migren takibi sürüyor.")
        self.assertEqual(body["sections"]["safety"],
                         "Yalnız kalınca sıkıntı artıyor.")

    def test_summary_filters_sections_and_marks_sources(self):
        self._save_sections()
        status, body, _ = self.request(
            "POST", "/api/psych-prep/summary",
            {"include_sections": ["reason", "medical"]})
        self.assertEqual(status, 200)
        summary = body["summary"]
        self.assertIn("kullanıcı beyanı", summary)
        self.assertIn("Altı aydır uykusuzluk", summary)
        self.assertIn("Migren takibi sürüyor.", summary)
        self.assertNotIn("Yalnız kalınca", summary)
        self.assertIn("Güvenlik planı", summary)

    def test_summary_with_measures_marks_measurement_source(self):
        self._save_sections()
        self.request("POST", "/api/checkin",
                     {"mood": 6, "symptom_score": 5, "note": "orta"})
        status, body, _ = self.request(
            "POST", "/api/psych-prep/summary", {"include_measures": True})
        self.assertEqual(status, 200)
        summary = body["summary"]
        self.assertIn("Ölçüm sonuçları", summary)
        self.assertIn("kullanıcı özbildirimi", summary)
        self.assertIn("Duygudurum 6/10", summary)
        self.assertNotIn("AI yorumu", summary)

    def test_summary_rejects_unknown_sections(self):
        status, body, _ = self.request(
            "POST", "/api/psych-prep/summary",
            {"include_sections": ["tanı"]})
        self.assertEqual(status, 400)

    def test_encrypted_export_uses_approved_sections_only(self):
        self._save_sections()
        status, body, headers = self.request(
            "POST", "/api/psych-prep/encrypted",
            {"passphrase": "uzun-bir-parola",
             "include_sections": ["reason"]})
        self.assertEqual(status, 200)
        self.assertIn("application/octet-stream",
                      headers.get("Content-Type", ""))


if __name__ == "__main__":
    unittest.main()
