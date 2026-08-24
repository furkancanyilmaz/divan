import json

from support import HTTPTestCase, app


class SchemaPathTests(HTTPTestCase):
    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)

    def completed_turns(self, count=3):
        with app.db() as connection:
            for index in range(count):
                stamp = "2026-08-17 10:{:02d}".format(index)
                user = connection.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (self.conv, "user", "doğrudan kullanıcı kaynağı {}".format(
                        index), stamp),
                ).lastrowid
                assistant = connection.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (self.conv, "assistant", "tamamlanmış yanıt {}".format(
                        index), stamp),
                ).lastrowid
                job = connection.execute(
                    "INSERT INTO jobs(kind,conv,status,created,updated) "
                    "VALUES('chat_response',?,'succeeded',?,?)",
                    (self.conv, stamp, stamp)).lastrowid
                connection.execute(
                    "INSERT INTO chat_requests(request_id,job,conv,"
                    "user_message,assistant_message,status,created,updated) "
                    "VALUES(?,?,?,?,?,'completed',?,?)",
                    ("schema-path-turn-{:012d}".format(user), job,
                     self.conv, user, assistant, stamp, stamp))
        return user

    def candidate(self, status="candidate", claim_type="schema_hypothesis"):
        with app.db() as connection:
            source = connection.execute(
                "SELECT id,content,created FROM messages WHERE conv=? "
                "AND role='user' ORDER BY id LIMIT 1", (self.conv,)
            ).fetchone()
            if source is None:
                self.completed_turns(1)
                source = connection.execute(
                    "SELECT id,content,created FROM messages WHERE conv=? "
                    "AND role='user' ORDER BY id LIMIT 1", (self.conv,)
                ).fetchone()
            assistant = connection.execute(
                "SELECT assistant_message FROM chat_requests WHERE conv=? "
                "AND user_message=? AND status='completed'",
                (self.conv, source["id"])).fetchone()["assistant_message"]
            observation = connection.execute(
                "INSERT INTO psych_observations("
                "conv,source_message,therapist,dimension,content,"
                "source_created,created) VALUES(?,?,?,?,?,?,?)",
                (self.conv, source["id"], "young", "user_report",
                 source["content"], source["created"], app.now()),
            ).lastrowid
            claim = connection.execute(
                "INSERT INTO psych_claims("
                "public_id,source_conv,therapist,lens,claim_type,title,"
                "statement,trigger_text,experience_text,response_text,"
                "short_term_effect,long_term_effect,need_text,"
                "counterexample_text,status,scope,sensitive,first_seen,"
                "last_seen,schema_key,mode_key,source_assistant_message,"
                "created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "schema-test-{}".format(observation), self.conv, "young",
                    "schema", claim_type, "Olası çalışma örüntüsü",
                    "Bu olayda terk edilme beklentisine benzeyen bir "
                    "çalışma olasılığı olabilir.",
                    "Mesaj gecikince", "kaygı", "yakınlığı sınama",
                    "kısa süreli güvence", "ilişkide gerilim", "güven",
                    "Bazen gecikmeyi sakin karşılayabiliyorum.", status,
                    "therapist", 0, app.now(), app.now(),
                    next(iter(app.SCHEMA_CANDIDATE_CATALOG)), "", assistant,
                    app.now(), app.now(),
                ),
            ).lastrowid
            review_status = "pending" if status == "candidate" else "accepted"
            evidence = connection.execute(
                "INSERT INTO psych_claim_evidence("
                "claim,observation,relation,review_status,created) "
                "VALUES(?,?,?,?,?)",
                (claim, observation, "supports", review_status, app.now()),
            ).lastrowid
            if status != "candidate":
                connection.execute(
                    "UPDATE psych_claims SET reviewed_evidence_id=?,"
                    "reviewed_at=? WHERE id=?",
                    (evidence, app.now(), claim),
                )
        return claim

    def post(self, payload):
        return self.request("POST", "/api/schema-path", payload)[:2]

    def get(self):
        return self.request(
            "GET", "/api/schema-path?conv_id={}".format(self.conv))[:2]

    def review(self, claim_id, decision="confirm", suffix="review-0001"):
        return self.post({
            "action": "review_candidate", "conv_id": self.conv,
            "claim_id": claim_id, "decision": decision,
            "request_id": "schema-{}".format(suffix),
        })

    def to_method(self, path_id, suffix):
        """explore -> focus -> method.

        Odak aşaması araya girdiği için testler yöntem aşamasına bu yardımcı
        üzerinden çıkar: usta aday sunar, kullanıcı seçer, sonra yönteme
        geçilir.
        """
        status, body = self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "focus",
            "request_id": "schema-{}-focus".format(suffix),
        })
        if status != 200:
            return status, body
        status, body = self.post({
            "action": "offer_focus", "conv_id": self.conv, "path_id": path_id,
            "candidates": [{"mode_key": "detached_protector",
                            "evidence": "duvar örüyorum"}],
            "request_id": "schema-{}-offer".format(suffix),
        })
        if status != 200:
            return status, body
        status, body = self.post({
            "action": "choose_focus", "conv_id": self.conv,
            "path_id": path_id, "mode_key": "detached_protector",
            "request_id": "schema-{}-choose".format(suffix),
        })
        if status != 200:
            return status, body
        return self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "method",
            "request_id": "schema-{}-method".format(suffix),
        })

    def start(self, claim_id, request_id="schema-start-0001"):
        return self.post({
            "action": "start", "conv_id": self.conv,
            "claim_id": claim_id, "request_id": request_id,
        })

    def accept_candidate_chat(self, request_id="schema-chat-yes-0001"):
        status, dashboard = self.get()
        self.assertEqual(status, 200, dashboard)
        card = dashboard["next_card"]
        self.assertEqual(card["kind"], "candidate_prompt")
        action = next(item for item in card["actions"]
                      if item["action"] == "accept_candidate_chat")
        return self.post({
            "action": "accept_candidate_chat", "conv_id": self.conv,
            "request_id": request_id, **action["payload"],
        })

    def legacy_start_fixture(self, claim_id):
        """Create an existing flow-v3 row without reopening public start.

        These tests retain migration/back-compat coverage for already-stored
        workspace paths. New product paths are exercised through
        ``accept_candidate_chat`` above and can never be created as v3.
        """
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                stamp = app.now()
                path_id = connection.execute(
                    "INSERT INTO schema_paths(conv,therapist,claim,phase,"
                    "status,flow_version,stage,step,created,updated) "
                    "VALUES(?,'young',?,'explore','active',3,'listen',"
                    "'listen',?,?)",
                    (self.conv, claim_id, stamp, stamp)).lastrowid
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
                return 200, app.schema_path_payload(
                    self.conv, connection=connection,
                    include_terminal=path)

    def test_scope_and_one_completed_turn_start_gate(self):
        wrong = self.conversation(therapist="freud")
        status, body, _ = self.request(
            "GET", "/api/schema-path?conv_id={}".format(wrong))
        self.assertEqual(status, 409)
        self.assertIn("Şema", body["error"])

        self.completed_turns(3)
        claim = self.candidate()
        self.assertEqual(self.review(claim)[0], 200)
        status, body = self.start(claim)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "schema_v4_action_required")
        status, body = self.accept_candidate_chat()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["active_path"]["flow_version"], 5)
        self.assertEqual(body["presentation"], "chat_only")
        self.assertEqual(body["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(body["step"], "variable_explore")
        self.assertEqual(body["next_card"]["body"], "")
        self.assertEqual(body["next_card"]["actions"], [])
        self.assertIsNone(body["next_card"]["chat_binding"])
        self.assertEqual(
            body["next_card"]["prompt_delivery"]["status"], "queued")

    def test_candidate_decisions_are_user_owned(self):
        self.completed_turns(3)
        claim = self.candidate()

        status, body = self.review(claim, "unsure", "unsure-0001")
        self.assertEqual(status, 200)
        self.assertEqual(body["candidate"]["status"], "candidate")
        self.assertEqual(self.start(claim)[0], 409)

        status, body = self.review(claim, "confirm", "confirm-0001")
        self.assertEqual(status, 200)
        self.assertEqual(body["candidate"]["status"], "confirmed")
        status, body = self.start(claim)
        self.assertEqual(status, 409)
        status, body = self.accept_candidate_chat(
            "schema-chat-confirm-0001")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["active_path"]["flow_version"], 5)

    def test_candidate_must_have_direct_user_evidence(self):
        self.completed_turns(3)
        claim = self.candidate()
        with app.db() as connection:
            connection.execute(
                "DELETE FROM psych_claim_evidence WHERE claim=?", (claim,))
        status, body = self.review(claim)
        self.assertEqual(status, 409)
        self.assertIn("kullanıcı", body["error"].casefold())

    def test_start_and_events_are_exactly_idempotent(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        status, dashboard = self.get()
        self.assertEqual(status, 200, dashboard)
        card = dashboard["next_card"]
        action = next(item for item in card["actions"]
                      if item["action"] == "accept_candidate_chat")
        payload = {
            "action": "accept_candidate_chat", "conv_id": self.conv,
            "request_id": "schema-chat-idempotent-0001",
            **action["payload"],
        }
        status, first = self.post(payload)
        self.assertEqual(status, 200)
        status, duplicate = self.post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(
            first["active_path"]["id"], duplicate["active_path"]["id"])
        payload["request_id"] = "schema-chat-idempotent-0002"
        status, body = self.post(payload)
        self.assertEqual(status, 409)
        self.assertIn("etkin", body["error"].casefold())

    def test_request_id_cannot_be_reused_for_changed_payload(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]
        payload = {
            "action": "record", "conv_id": self.conv,
            "path_id": path["id"], "kind": "current_trigger",
            "value": "İlk olay", "request_id": "schema-hash-0001",
        }
        self.assertEqual(self.post(payload)[0], 200)
        payload["value"] = "Değiştirilmiş olay"
        status, body = self.post(payload)
        self.assertEqual(status, 409)
        self.assertIn("farklı", body["error"].casefold())
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM schema_path_events WHERE "
            "request_id='schema-hash-0001'")["n"], 1)

    def test_private_revoke_blocks_depth_but_keeps_stop_available(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]
        status, body = self.review(claim, "private", "private-0001")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["candidate"]["status"], "private")
        self.assertEqual(body["allowed_actions"], ["stop"])
        status, body = self.post({
            "action": "record", "conv_id": self.conv,
            "path_id": path["id"], "kind": "current_trigger",
            "value": "artık özel", "request_id": "schema-private-record-0001",
        })
        self.assertEqual(status, 409)
        self.assertIn("onaylı değil", body["error"].casefold())
        status, body = self.post({
            "action": "stop", "conv_id": self.conv,
            "path_id": path["id"], "request_id": "schema-private-stop-0001",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["active_path"]["status"], "stopped")

    def test_origin_is_optional_and_phase_guards_are_server_owned(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]

        status, body = self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path["id"],
            "to_phase": "method", "request_id": "schema-advance-0001",
        })
        self.assertEqual(status, 409)
        self.assertIn("tetikleyici", body["error"].casefold())

        for index, (kind, value) in enumerate((
                ("current_trigger", "Mesajın gecikmesi"),
                ("need", "Güven ve açık iletişim"),
                ("skip_origin", "Bu aşamada geçmişe gitmek istemiyorum"))):
            status, _ = self.post({
                "action": "record", "conv_id": self.conv,
                "path_id": path["id"], "kind": kind, "value": value,
                "request_id": "schema-record-{:04d}".format(index),
            })
            self.assertEqual(status, 200)
        status, body = self.to_method(path["id"], "advance-0002")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["active_path"]["phase"], "method")

    def test_enhanced_method_requires_fresh_reality_orientation_gate(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]
        early = {
            "action": "assign_practice", "conv_id": self.conv,
            "path_id": path["id"], "request_id": "schema-practice-early-0001",
            "user_confirmed": True,
            "experiment": {
                "variable": "Tek bir değişiklik", "constant": "Aynı bağlam",
                "prediction": "Bir miktar fark", "action": "Bir soru sormak",
                "observable_result": "Yanıtı not etmek",
                "tiny_version": "Soruyu yazmak", "target_per_week": 2,
            },
        }
        status, body = self.post(early)
        self.assertEqual(status, 409)
        self.assertIn("aşama", body["error"].casefold())
        for index, (kind, value) in enumerate((
                ("current_trigger", "Bugünkü olay"), ("need", "Korunmak"))):
            self.post({
                "action": "record", "conv_id": self.conv,
                "path_id": path["id"], "kind": kind, "value": value,
                "request_id": "schema-method-record-{:04d}".format(index),
            })
        self.to_method(path["id"], "to-method-0001")
        status, meta, _ = self.request(
            "POST", "/api/session-meta", {
                "conv_id": self.conv, "precheck_done": False,
                "safety_ok": None, "intensity_limit": 5,
            })
        self.assertEqual(status, 200, meta)
        base = {
            "action": "choose_method", "conv_id": self.conv,
            "path_id": path["id"], "method_id": "young:method:chair-dialogue",
            "confirmed": True,
            "request_id": "schema-method-0001",
        }
        status, body = self.post(base)
        self.assertEqual(status, 409)
        self.assertIn("başlangıç", body["error"].casefold())

        base["precheck"] = {
            "orientation_confirmed": True, "reality_clear": False,
            "sleep_activation_clear": True, "intensity": 4,
            "support_available": True, "stop_signal": "dur",
        }
        status, body = self.post(base)
        self.assertEqual(status, 409)
        self.assertIn("gerçeklik", body["error"].casefold())

        base["precheck"]["reality_clear"] = True
        status, body = self.post(base)
        self.assertEqual(status, 200)
        self.assertEqual(
            body["active_path"]["method_id"],
            "young:method:chair-dialogue")
        meta = self.row(
            "SELECT * FROM session_meta WHERE conv=?", (self.conv,))
        self.assertEqual(meta["precheck_done"], 1)
        self.assertEqual(meta["safety_ok"], 1)
        self.assertEqual(meta["anxiety_start"], 4)
        self.assertEqual(meta["intensity_limit"], 5)
        self.assertNotIn("precheck", body["active_path"])
        event = self.row(
            "SELECT payload_json FROM schema_path_events WHERE "
            "action='choose_method' AND path=?", (path["id"],))
        self.assertTrue(json.loads(event["payload_json"])["precheck"])

    def test_practice_is_opt_in_and_never_schedules_a_notification(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Bugünkü tetikleyici"),
                ("need", "Açık bir sınır"),
                ("skip_origin", "Geçmişe bugün gitmek istemiyorum"))):
            self.assertEqual(self.post({
                "action": "record", "conv_id": self.conv,
                "path_id": path["id"], "kind": kind, "value": value,
                "request_id": "schema-practice-record-{:04d}".format(index),
            })[0], 200)
        self.assertEqual(
            self.to_method(path["id"], "practice-method-0001")[0], 200)
        self.assertEqual(self.post({
            "action": "choose_method", "conv_id": self.conv,
            "path_id": path["id"],
            "method_id": "young:method:pattern-breaking",
            "confirmed": True,
            "request_id": "schema-practice-choice-0001",
        })[0], 200)
        self.assertEqual(self.post({
            "action": "advance", "conv_id": self.conv,
            "path_id": path["id"], "to_phase": "practice",
            "request_id": "schema-practice-phase-0001",
        })[0], 200)
        payload = {
            "action": "assign_practice", "conv_id": self.conv,
            "path_id": path["id"], "request_id": "schema-practice-0001",
            "user_confirmed": True,
            "experiment": {
                "variable": "Yanıt vermeden önce tek soru sormak",
                "constant": "Aynı kişi ve benzer bağlam",
                "prediction": "Kaygının biraz azalması",
                "action": "Bir açık soru sormak",
                "observable_result": "Konuşmanın netleşip netleşmemesi",
                "tiny_version": "Soruyu notlara yazmak",
                "target_per_week": 2,
            },
        }
        status, body = self.post(payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["active_path"]["practice"]["target_per_week"], 2)
        self.assertEqual(self.row("SELECT COUNT(*) n FROM reminders")["n"], 0)
        self.assertEqual(self.post(payload)[0], 200)
        self.assertEqual(
            self.row("SELECT COUNT(*) n FROM schema_path_events WHERE "
                     "action='assign_practice'")["n"], 1)

    def test_hold_blocks_depth_but_never_stop(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?", (self.conv,))
        status, body = self.post({
            "action": "record", "conv_id": self.conv, "path_id": path["id"],
            "kind": "current_trigger", "value": "örnek",
            "request_id": "schema-held-record-0001",
        })
        self.assertEqual(status, 409)
        self.assertIn("güvenlik", body["error"].casefold())
        status, body = self.post({
            "action": "stop", "conv_id": self.conv, "path_id": path["id"],
            "request_id": "schema-stop-0001",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["active_path"]["status"], "stopped")

    def test_only_approved_active_path_enters_prompt(self):
        self.completed_turns(3)
        candidate = self.candidate()
        candidate_text = self.row(
            "SELECT statement FROM psych_claims WHERE id=?", (candidate,)
        )["statement"]
        self.assertNotIn(candidate_text, self.system_prompt(self.conv))

        self.review(candidate)
        path = self.legacy_start_fixture(candidate)[1]["active_path"]
        marker = "BUGÜNÜN-DOĞRULANMIŞ-TETİKLEYİCİSİ"
        self.post({
            "action": "record", "conv_id": self.conv, "path_id": path["id"],
            "kind": "current_trigger", "value": marker,
            "request_id": "schema-prompt-record-0001",
        })
        prompt = self.system_prompt(self.conv)
        self.assertIn(marker, prompt)
        self.assertIn("çalışma hipotezi", prompt.casefold())
        self.assertNotIn("tanı", prompt.split(marker)[-1][:80].casefold())

    def test_delete_conversation_cascades_path_and_events(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path = self.legacy_start_fixture(claim)[1]["active_path"]
        with app.db() as connection:
            app.delete_conversation_data(connection, self.conv)
        self.assertIsNone(self.row(
            "SELECT id FROM schema_paths WHERE id=?", (path["id"],)))
        self.assertEqual(self.row(
            "SELECT COUNT(*) n FROM schema_path_events")["n"], 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
