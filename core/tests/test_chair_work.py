import json
from unittest import mock

from support import HTTPTestCase, app


CHAIR_NODE_IDS = {
    "perls:method:empty-chair",
    "perls:method:two-chair-conflict",
    "young:method:chair-dialogue",
    "satir:method:parts-party",
    "greenberg:method:two-chair-self-criticism",
    "greenberg:method:unfinished-business-chair",
}


class ChairWorkTestCase(HTTPTestCase):

    def method_for_node(self, therapist, node_id):
        return next(
            row for row in app.method_records(therapist)
            if row["node_id"] == node_id)

    def open_chair(self, therapist="young",
                   node_id="young:method:chair-dialogue",
                   begin=True, intensity=4, intensity_limit=None):
        conv_id = self.conversation(therapist=therapist)
        if intensity_limit is not None:
            status, body, _ = self.request(
                "POST", "/api/session-meta", {
                    "conv_id": conv_id,
                    "precheck_done": True,
                    "safety_ok": True,
                    "intensity_limit": intensity_limit,
                })
            self.assertEqual(status, 200, body)
        method = self.method_for_node(therapist, node_id)
        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": intensity,
            })
        self.assertEqual(status, 200, proposed)
        self.assertIsNone(proposed["chairwork"])
        run_id = proposed["run"]["id"]
        status, consented, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "id": run_id,
                "action": "consent",
                "confirmed": True,
            })
        self.assertEqual(status, 200, consented)
        chair = consented["chairwork"]
        self.assertIsNotNone(chair)
        self.assertEqual(chair["status"], "ready")
        if begin:
            status, begun, _ = self.request(
                "POST", "/api/chair-work", {
                    "conv_id": conv_id,
                    "chair_run_id": chair["id"],
                    "action": "begin",
                    "orientation_ok": True,
                    "frame_ok": True,
                    "stop_signal": "DUR",
                    "goal_text": "Parçaları güvenle ayırt etmek",
                })
            self.assertEqual(status, 200, begun)
            chair = begun["chairwork"]
            self.assertEqual(chair["status"], "dialogue")
        return conv_id, run_id, chair, method

    def speak(self, conv_id, chair, content="Bunu taşımak çok zor.",
              event_id="turn-1", participant_id=None, intensity=None,
              **extra):
        payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "participant_id": (
                participant_id
                if participant_id is not None
                else chair["active_participant_id"]),
            "content": content,
            "client_event_id": event_id,
        }
        if intensity is not None:
            payload["intensity"] = intensity
        payload.update(extra)
        return self.request("POST", "/api/chair-turn", payload)

    def guidance_payload(self, conv_id, turn_body,
                         request_id="guidance-1"):
        return {
            "conv_id": conv_id,
            "chair_run_id": turn_body["chairwork"]["id"],
            "after_seq": turn_body["turn"]["seq"],
            "revision": turn_body["chairwork"]["revision"],
            "request_id": request_id,
        }

    def checkpoint_fields(self, action, intensity=3,
                          note="Bu çalışmadan fark ettiğim kısa not."):
        if action == "ground":
            return {
                "checkpoint_confirmed": True,
                "orientation_ok": True,
                "intensity": intensity,
            }
        if action == "reflect":
            return {
                "checkpoint_confirmed": True,
                "checkpoint_note": note,
            }
        if action == "complete":
            return {"checkpoint_confirmed": True}
        return {}


class ChairCatalogAndSchemaTests(ChairWorkTestCase):

    def test_only_explicit_nodes_enable_chairwork_and_all_are_enhanced(self):
        self.assertEqual(set(app.CHAIR_METHODS), CHAIR_NODE_IDS)
        self.assertTrue(CHAIR_NODE_IDS.issubset(app.ENHANCED_GATE_NODE_IDS))

        chair_records = []
        ordinary_records = []
        for therapist in app.THERAPISTS:
            for record in app.method_records(therapist):
                if record["node_id"] in CHAIR_NODE_IDS:
                    chair_records.append(record)
                else:
                    ordinary_records.append(record)
        self.assertEqual(
            {row["node_id"] for row in chair_records}, CHAIR_NODE_IDS)
        for row in chair_records:
            with self.subTest(node_id=row["node_id"]):
                self.assertEqual(row["interaction_mode"], "chair_work")
                self.assertEqual(row["risk_level"], "enhanced")
                self.assertIsNotNone(row["chair_config"])
                self.assertGreaterEqual(
                    row["chair_config"]["max_participants"],
                    row["chair_config"]["min_participants"])
                self.assertLessEqual(
                    row["chair_config"]["max_participants"], 6)
        for row in ordinary_records:
            with self.subTest(node_id=row["node_id"]):
                expected_mode = (
                    "imagery_work"
                    if row["node_id"] in app.IMAGERY_METHODS
                    else "chat"
                )
                self.assertEqual(row["interaction_mode"], expected_mode)
                self.assertIsNone(row["chair_config"])

    def test_perls_two_chair_start_contract(self):
        conv_id, run_id, chair, method = self.open_chair(
            therapist="perls",
            node_id="perls:method:two-chair-conflict",
        )

        self.assertEqual(method["key"], "perls:iki-sandalye-catsmas")
        self.assertEqual(method["interaction_mode"], "chair_work")
        self.assertEqual(method["risk_level"], "enhanced")
        self.assertEqual(chair["technique_run_id"], run_id)
        self.assertEqual(
            chair["method_node_id"], "perls:method:two-chair-conflict")
        self.assertEqual(chair["protocol"], "two_chair_conflict")
        self.assertEqual(chair["status"], "dialogue")
        self.assertEqual(
            [(row["slot_key"], row["label"])
             for row in chair["participants"]],
            [("side_a", "Bir yanım"), ("side_b", "Diğer yanım")],
        )
        self.assertFalse(chair["capabilities"]["begin"])
        self.assertTrue(chair["capabilities"]["speak"])
        self.assertTrue(chair["capabilities"]["guide"])

        status, fetched, _ = self.request(
            "GET", "/api/chair-work?conv_id={}&chair_run_id={}".format(
                conv_id, chair["id"]))
        self.assertEqual(status, 200, fetched)
        self.assertEqual(fetched["chairwork"]["id"], chair["id"])
        self.assertEqual(len(fetched["chairworks"]), 1)

    def test_schema_is_created_idempotently_for_an_existing_database(self):
        conv_id = self.conversation(title="Göç öncesi görüşme")
        with app.db() as conn:
            conn.execute("DROP TABLE chair_turns")
            conn.execute("DROP TABLE chair_participants")
            conn.execute("DROP TABLE chair_runs")

        app.init_db()
        app.init_db()

        tables = {
            row["name"] for row in self.rows(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({
            "chair_runs", "chair_participants", "chair_turns",
        }.issubset(tables))
        self.assertEqual(
            self.conversation_row(conv_id)["title"], "Göç öncesi görüşme")
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])


class ChairBoundaryTests(ChairWorkTestCase):

    def test_consent_is_required_before_workspace_exists_or_can_begin(self):
        conv_id = self.conversation(therapist="young")
        method = self.method_for_node(
            "young", "young:method:chair-dialogue")
        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 4,
            })
        self.assertEqual(status, 200, proposed)
        self.assertIsNone(proposed["chairwork"])
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM chair_runs")["n"], 0)

        status, fetched, _ = self.request(
            "GET", "/api/chair-work?conv_id={}".format(conv_id))
        self.assertEqual(status, 200, fetched)
        self.assertIsNone(fetched["chairwork"])
        status, body, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "action": "begin",
            })
        self.assertEqual(status, 404, body)

        status, consented, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "id": proposed["run"]["id"],
                "action": "consent",
                "confirmed": True,
            })
        self.assertEqual(status, 200, consented)
        self.assertEqual(consented["chairwork"]["status"], "ready")
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM chair_runs")["n"], 1)

    def test_paused_ended_and_safety_hold_sessions_reject_part_speech(self):
        scenarios = ("paused", "ended", "safety")
        for index, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario):
                conv_id, run_id, chair, _ = self.open_chair()
                if scenario == "paused":
                    status, body, _ = self.request(
                        "POST", "/api/chair-work", {
                            "conv_id": conv_id,
                            "chair_run_id": chair["id"],
                            "action": "ground",
                            "expected_revision": chair["revision"],
                            **self.checkpoint_fields("ground", intensity=3),
                        })
                    self.assertEqual(status, 200, body)
                else:
                    with app.db() as conn:
                        if scenario == "ended":
                            conn.execute(
                                "UPDATE conversations SET ended=1 WHERE id=?",
                                (conv_id,))
                        else:
                            conn.execute(
                                "UPDATE conversations SET safety_hold=1 "
                                "WHERE id=?", (conv_id,))
                status, body, _ = self.speak(
                    conv_id, chair,
                    event_id="guard-{}".format(index))
                self.assertEqual(status, 409, body)
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                        (conv_id,))["n"],
                    0)

    def test_cross_conversation_workspace_and_participant_ids_cannot_mutate(self):
        first_conv, _, first, _ = self.open_chair()
        second_conv, _, second, _ = self.open_chair()
        first_part = first["participants"][0]["id"]
        second_part = second["participants"][0]["id"]

        status, body, _ = self.speak(
            second_conv, first, participant_id=first_part,
            event_id="cross-workspace")
        self.assertEqual(status, 404, body)
        status, body, _ = self.speak(
            first_conv, first, participant_id=second_part,
            event_id="cross-participant")
        self.assertEqual(status, 404, body)
        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM chair_turns")["n"], 0)

    def test_labels_content_and_add_participant_limit_are_server_enforced(self):
        conv_id, _, chair, _ = self.open_chair()
        participant = chair["participants"][0]["id"]
        original_count = len(chair["participants"])

        invalid_labels = ("", "x" * (app.CHAIR_LABEL_LIMIT + 1))
        for index, label in enumerate(invalid_labels):
            with self.subTest(label=index):
                status, _, _ = self.request(
                    "POST", "/api/chair-work", {
                        "conv_id": conv_id,
                        "chair_run_id": chair["id"],
                        "action": "rename",
                        "participant_id": participant,
                        "label": label,
                    })
                self.assertEqual(status, 400)

        status, renamed, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "rename",
                "participant_id": participant,
                "label": "  Korunmaya ihtiyaç duyan yanım  ",
            })
        self.assertEqual(status, 200, renamed)
        self.assertIn(
            "Korunmaya ihtiyaç duyan yanım",
            {row["label"] for row in renamed["chairwork"]["participants"]})

        max_participants = app.CHAIR_METHODS[
            chair["method_node_id"]]["max_participants"]
        for index in range(
                chair["capabilities"]["add"]
                and (max_participants - original_count) or 0):
            status, added, _ = self.request(
                "POST", "/api/chair-work", {
                    "conv_id": conv_id,
                    "chair_run_id": chair["id"],
                    "action": "add",
                    "label": "Ek parça {}".format(index + 1),
                })
            self.assertEqual(status, 200, added)
        status, body, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "add",
                "label": "Sınırı aşan parça",
            })
        self.assertEqual(status, 409, body)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_participants "
                "WHERE chair_run=?", (chair["id"],))["n"],
            max_participants)

        for content, expected in (
                ("", 400),
                ("x" * (app.CHAIR_CONTENT_LIMIT + 1), 413)):
            with self.subTest(content_length=len(content)):
                status, _, _ = self.speak(
                    conv_id, chair, content=content,
                    event_id="content-{}".format(len(content)))
                self.assertEqual(status, expected)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (conv_id,))["n"],
            0)

    def test_duplicate_labels_are_rejected_after_normalization(self):
        conv_id, _, chair, _ = self.open_chair()
        first, second = chair["participants"][:2]
        status, body, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "rename",
                "participant_id": first["id"],
                "label": second["label"].upper(),
            })
        self.assertEqual(status, 409, body)
        status, body, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "add",
                "label": first["label"],
            })
        self.assertEqual(status, 409, body)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_participants "
                "WHERE chair_run=?", (chair["id"],))["n"],
            len(chair["participants"]))

    def test_boolean_identifiers_are_never_coerced_to_database_ids(self):
        conv_id, _, chair, _ = self.open_chair()
        requests = (
            ("/api/chair-work", {
                "conv_id": True,
                "chair_run_id": chair["id"],
                "action": "begin",
            }),
            ("/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": True,
                "action": "select",
                "participant_id": chair["active_participant_id"],
            }),
            ("/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "select",
                "participant_id": True,
            }),
            ("/api/chair-turn", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "participant_id": True,
                "content": "Bu kimlik geçersiz olmalı.",
                "client_event_id": "boolean-participant",
            }),
            ("/api/chair-guidance", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "after_seq": True,
                "revision": chair["revision"],
                "request_id": "boolean-seq",
            }),
        )
        for path, payload in requests:
            with self.subTest(path=path, payload=payload):
                status, _, _ = self.request("POST", path, payload)
                self.assertEqual(status, 400)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (conv_id,))["n"],
            0)

    def test_resume_requires_fresh_grounding_orientation_and_intensity(self):
        conv_id, run_id, chair, _ = self.open_chair(intensity_limit=10)
        status, paused, _ = self.speak(
            conv_id, chair, content="Şu an çok yoğun.",
            intensity=8, event_id="resume-after-grounding")
        self.assertEqual(status, 200, paused)
        self.assertEqual(paused["chairwork"]["status"], "grounding")

        status, lowered, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "id": run_id,
                "action": "intensity",
                "intensity": 4,
            })
        self.assertEqual(status, 200, lowered)
        self.assertTrue(lowered["chairwork"]["capabilities"]["resume"])

        required = {
            "checkpoint_confirmed": True,
            "orientation_ok": True,
            "intensity": 4,
        }
        for missing in required:
            with self.subTest(missing=missing):
                payload = dict(required)
                payload.pop(missing)
                status, blocked, _ = self.request(
                    "POST", "/api/chair-work", {
                        "conv_id": conv_id,
                        "chair_run_id": chair["id"],
                        "action": "resume",
                        **payload,
                    })
                self.assertEqual(status, 409, blocked)

        status, too_intense, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "resume",
                "checkpoint_confirmed": True,
                "orientation_ok": True,
                "intensity": 8,
            })
        self.assertEqual(status, 409, too_intense)

        status, resumed, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "resume",
                **required,
            })
        self.assertEqual(status, 200, resumed)
        self.assertEqual(
            (resumed["chairwork"]["status"],
             resumed["chairwork"]["technique_status"],
             resumed["chairwork"]["phase"]),
            ("dialogue", "active", "work"))
        self.assertTrue(resumed["chairwork"]["capabilities"]["speak"])

    def test_client_event_id_is_idempotent_and_cannot_be_reused_for_new_text(self):
        conv_id, _, chair, _ = self.open_chair()
        first_status, first, _ = self.speak(
            conv_id, chair, content="İlk ve tek söz.",
            event_id="stable-event")
        self.assertEqual(first_status, 200, first)
        revision = first["chairwork"]["revision"]

        status, duplicate, _ = self.speak(
            conv_id, first["chairwork"], content="İlk ve tek söz.",
            event_id="stable-event")
        self.assertEqual(status, 200, duplicate)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["turn"]["id"], first["turn"]["id"])
        self.assertEqual(duplicate["chairwork"]["revision"], revision)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (conv_id,))["n"],
            1)

        status, undone, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "undo",
            })
        self.assertEqual(status, 200, undone)
        self.assertFalse(undone["chairwork"]["can_undo"])
        reverted = self.row(
            "SELECT * FROM chair_turns WHERE id=?", (first["turn"]["id"],))
        self.assertIsNotNone(reverted["reverted_at"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND reverted_at IS NULL", (conv_id,))["n"],
            0)

        status, _, _ = self.speak(
            conv_id, duplicate["chairwork"], content="Başka bir söz.",
            event_id="stable-event")
        self.assertEqual(status, 409)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (conv_id,))["n"],
            1)

    def test_declared_intensity_limit_hard_rejects_without_any_mutation(self):
        conv_id, run_id, chair, _ = self.open_chair(intensity_limit=5)
        before_revision = chair["revision"]
        before_run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))

        with mock.patch.object(app, "ds_complete") as model:
            status, body, _ = self.speak(
                conv_id, chair, content="Bir adım deneyeyim.",
                intensity=6, event_id="over-limit")

        self.assertEqual(status, 409, body)
        model.assert_not_called()
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (conv_id,))["n"],
            0)
        after_run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual(
            after_run["intensity_current"],
            before_run["intensity_current"])
        self.assertEqual(
            self.row(
                "SELECT revision FROM chair_runs WHERE id=?",
                (chair["id"],))["revision"],
            before_revision)

    def test_intensity_eight_records_user_turn_then_pauses_without_map_credit(self):
        conv_id, run_id, chair, _ = self.open_chair(intensity_limit=10)
        with mock.patch.object(app, "ds_complete") as model:
            status, body, _ = self.speak(
                conv_id, chair, content="Yoğunluk birden yükseldi.",
                intensity=8, event_id="intensity-eight")

        self.assertEqual(status, 200, body)
        self.assertTrue(body["paused_for_intensity"])
        model.assert_not_called()
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual(
            (run["status"], run["phase"], run["intensity_current"]),
            ("paused", "grounding", 8))
        self.assertEqual(body["chairwork"]["status"], "grounding")
        target = self.row(
            "SELECT * FROM session_map_targets WHERE conv=? "
            "AND is_current=1", (conv_id,))
        self.assertEqual((target["status"], target["phase"]),
                         ("paused", "grounding"))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM session_map_events "
                "WHERE conv=? AND to_status='reached'",
                (conv_id,))["n"],
            0)

    def test_crisis_uses_fixed_help_without_provider_and_sets_safety_state(self):
        conv_id, run_id, chair, _ = self.open_chair()
        with mock.patch.object(app, "ds_complete") as model:
            status, body, _ = self.speak(
                conv_id, chair,
                content="Kendime zarar vermek istiyorum.",
                event_id="crisis-turn")

        self.assertEqual(status, 200, body)
        self.assertTrue(body["crisis"])
        self.assertTrue(body["safety_hold"])
        self.assertEqual(body["message"], app.CRISIS_HELP_MESSAGE)
        self.assertIn("112", body["message"])
        model.assert_not_called()
        self.assertEqual(self.conversation_row(conv_id)["safety_hold"], 1)
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual((run["status"], run["phase"]),
                         ("paused", "grounding"))

        turns = self.rows(
            "SELECT actor_kind,authored_by,turn_kind,content "
            "FROM chair_turns WHERE conv=? ORDER BY seq", (conv_id,))
        self.assertEqual(
            [(row["actor_kind"], row["authored_by"], row["turn_kind"])
             for row in turns],
            [("part", "user", "crisis"),
             ("therapist", "server", "safety")])
        self.assertEqual(turns[-1]["content"], app.CRISIS_HELP_MESSAGE)
        saved_help = self.row(
            "SELECT role,content FROM messages WHERE conv=? ORDER BY id DESC "
            "LIMIT 1", (conv_id,))
        self.assertEqual(saved_help["role"], "assistant")
        self.assertEqual(saved_help["content"], app.CRISIS_HELP_MESSAGE)
        safety_event = self.row(
            "SELECT * FROM session_map_events WHERE conv=? "
            "ORDER BY id DESC LIMIT 1", (conv_id,))
        self.assertEqual(safety_event["source"], "safety")
        self.assertEqual(
            (safety_event["to_status"], safety_event["to_phase"]),
            ("paused", "grounding"))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM session_map_events "
                "WHERE conv=? AND to_status='reached'", (conv_id,))["n"],
            0)


class ChairGuidanceTests(ChairWorkTestCase):

    def test_user_and_model_provenance_are_separate_and_prompt_forbids_part_voice(self):
        conv_id, _, chair, _ = self.open_chair()
        status, spoken, _ = self.speak(
            conv_id, chair, content="Beni kimse görmüyor.",
            event_id="provenance-user",
            actor_kind="therapist", authored_by="model")
        self.assertEqual(status, 200, spoken)
        self.assertEqual(
            (spoken["turn"]["actor_kind"], spoken["turn"]["authored_by"]),
            ("part", "user"))

        captured = []

        def observer(messages, **_kwargs):
            captured.extend(messages)
            return json.dumps({
                "observation": "Görülmeme duygusu belirginleşiyor.",
                "instruction": "İstersen bu parçanın ihtiyacını tek cümle yaz.",
                "check_in": "Devam etmek senin için uygun mu?",
                "actor_kind": "part",
                "authored_by": "user",
                "part_reply": "Beni gör.",
            }, ensure_ascii=False)

        with mock.patch.object(app, "ds_complete", side_effect=observer):
            status, guided, _ = self.request(
                "POST", "/api/chair-guidance",
                self.guidance_payload(
                    conv_id, spoken, request_id="provenance-guidance"))

        self.assertEqual(status, 200, guided)
        self.assertEqual(
            (guided["turn"]["actor_kind"],
             guided["turn"]["authored_by"],
             guided["turn"]["participant_id"]),
            ("therapist", "model", None))
        self.assertIsNotNone(guided["turn"]["guidance"])
        rows = self.rows(
            "SELECT actor_kind,authored_by,participant FROM chair_turns "
            "WHERE conv=? ORDER BY seq", (conv_id,))
        self.assertEqual(
            [(row["actor_kind"], row["authored_by"])
             for row in rows],
            [("part", "user"), ("therapist", "model")])
        self.assertIsNotNone(rows[0]["participant"])
        self.assertIsNone(rows[1]["participant"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND actor_kind='part' AND authored_by!='user'",
                (conv_id,))["n"],
            0)

        system = captured[0]["content"]
        folded_system = system.casefold()
        for rule in (
                "hiçbir parçanın rolüne girme",
                "onun adına yeni",
                "bağımsız kişiler",
                "Taraf tutma",
                "anı, istismar",
                "kullanıcı durabilir"):
            with self.subTest(rule=rule):
                self.assertIn(rule.casefold(), folded_system)
        self.assertEqual(captured[-1]["role"], "user")
        self.assertIn("Beni kimse görmüyor.", captured[-1]["content"])

    def test_stale_revision_or_latest_sequence_rejects_before_model_call(self):
        conv_id, _, chair, _ = self.open_chair()
        _, spoken, _ = self.speak(
            conv_id, chair, event_id="stale-user")
        good = self.guidance_payload(conv_id, spoken, "stale-guidance")

        stale_payloads = [
            dict(good, revision=good["revision"] - 1),
            dict(good, after_seq=good["after_seq"] + 1),
        ]
        with mock.patch.object(app, "ds_complete") as model:
            for payload in stale_payloads:
                with self.subTest(payload=payload):
                    status, _, _ = self.request(
                        "POST", "/api/chair-guidance", payload)
                    self.assertEqual(status, 409)
        model.assert_not_called()
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND authored_by='model'", (conv_id,))["n"],
            0)

    def test_provider_failure_keeps_user_turn_and_retry_does_not_duplicate_it(self):
        conv_id, _, chair, _ = self.open_chair()
        _, spoken, _ = self.speak(
            conv_id, chair, content="Burada kalmak istiyorum.",
            event_id="retry-user")
        payload = self.guidance_payload(
            conv_id, spoken, request_id="retry-guidance")

        with mock.patch.object(
                app, "ds_complete",
                side_effect=RuntimeError("provider offline")):
            status, failed, _ = self.request(
                "POST", "/api/chair-guidance", payload)
        self.assertEqual(status, 502, failed)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND actor_kind='part' AND authored_by='user'",
                (conv_id,))["n"],
            1)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND authored_by='model'", (conv_id,))["n"],
            0)

        valid = json.dumps({
            "observation": "Burada kalma isteğiniz duyuluyor.",
            "instruction": "İsterseniz bir sonraki cümleyi siz seçin.",
            "check_in": "Devam etmek uygun mu?",
        }, ensure_ascii=False)
        with mock.patch.object(app, "ds_complete", return_value=valid):
            status, retried, _ = self.request(
                "POST", "/api/chair-guidance", payload)
        self.assertEqual(status, 200, retried)
        self.assertFalse(retried["duplicate"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND actor_kind='part' AND authored_by='user'",
                (conv_id,))["n"],
            1)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND actor_kind='therapist' AND authored_by='model'",
                (conv_id,))["n"],
            1)


class ChairLifecycleAndPersistenceTests(ChairWorkTestCase):

    def test_explicit_checkpoints_record_intensity_notes_and_exact_retries(self):
        conv_id, run_id, chair, _ = self.open_chair(intensity_limit=6)
        original_revision = chair["revision"]
        base = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "action": "ground",
            "expected_revision": original_revision,
        }
        invalid = (
            {},
            {"checkpoint_confirmed": True, "intensity": 2},
            {"checkpoint_confirmed": True, "orientation_ok": True},
            {
                "checkpoint_confirmed": True,
                "orientation_ok": True,
                "intensity": 7,
            },
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                status, _, _ = self.request(
                    "POST", "/api/chair-work", {**base, **payload})
                self.assertEqual(status, 409)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM technique_checkpoints "
                "WHERE technique_run=?", (run_id,))["n"],
            0)

        ground_payload = {
            **base,
            "checkpoint_confirmed": True,
            "orientation_ok": True,
            "intensity": 2,
            "checkpoint_note": "Ayaklarımı ve odayı fark ettim.",
        }
        status, grounded, _ = self.request(
            "POST", "/api/chair-work", ground_payload)
        self.assertEqual(status, 200, grounded)
        chair = grounded["chairwork"]
        self.assertEqual(chair["status"], "grounding")
        self.assertEqual(chair["intensity"], 2)
        self.assertEqual(chair["revision"], original_revision + 1)
        checkpoint = self.row(
            "SELECT * FROM technique_checkpoints WHERE technique_run=?",
            (run_id,))
        self.assertEqual(
            (checkpoint["from_phase"], checkpoint["to_phase"],
             checkpoint["note"], checkpoint["user_confirmed"]),
            ("work", "grounding", "Ayaklarımı ve odayı fark ettim.", 1))

        status, duplicate, _ = self.request(
            "POST", "/api/chair-work", ground_payload)
        self.assertEqual(status, 200, duplicate)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["chairwork"]["revision"], chair["revision"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM technique_checkpoints "
                "WHERE technique_run=?", (run_id,))["n"],
            1)

        status, changed_retry, _ = self.request(
            "POST", "/api/chair-work", {
                **ground_payload,
                "intensity": 3,
            })
        self.assertEqual(status, 409, changed_retry)

    def test_reflect_and_complete_require_distinct_confirmed_checkpoints(self):
        conv_id, run_id, chair, _ = self.open_chair()
        status, grounded, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "ground",
                "expected_revision": chair["revision"],
                **self.checkpoint_fields("ground", intensity=3),
            })
        self.assertEqual(status, 200, grounded)
        chair = grounded["chairwork"]

        status, missing_note, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "reflect",
                "expected_revision": chair["revision"],
                "checkpoint_confirmed": True,
                "checkpoint_note": "   ",
            })
        self.assertEqual(status, 409, missing_note)
        reflect_revision = chair["revision"]
        reflect_payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "action": "reflect",
            "expected_revision": reflect_revision,
            "checkpoint_confirmed": True,
            "checkpoint_note": "Eleştirel sesin altında korunma ihtiyacı var.",
        }
        status, reflected, _ = self.request(
            "POST", "/api/chair-work", reflect_payload)
        self.assertEqual(status, 200, reflected)
        chair = reflected["chairwork"]
        self.assertEqual(chair["status"], "review")
        status, duplicate_reflect, _ = self.request(
            "POST", "/api/chair-work", reflect_payload)
        self.assertEqual(status, 200, duplicate_reflect)
        self.assertTrue(duplicate_reflect["duplicate"])

        status, missing_complete, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "complete",
                "expected_revision": chair["revision"],
            })
        self.assertEqual(status, 409, missing_complete)
        complete_payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "action": "complete",
            "expected_revision": chair["revision"],
            "checkpoint_confirmed": True,
            "checkpoint_note": "Bugünlük burada tamamlıyorum.",
        }
        status, completed, _ = self.request(
            "POST", "/api/chair-work", complete_payload)
        self.assertEqual(status, 200, completed)
        self.assertEqual(completed["chairwork"]["status"], "closed")
        status, duplicate_complete, _ = self.request(
            "POST", "/api/chair-work", complete_payload)
        self.assertEqual(status, 200, duplicate_complete)
        self.assertTrue(duplicate_complete["duplicate"])
        checkpoints = self.rows(
            "SELECT from_phase,to_phase,note,user_confirmed "
            "FROM technique_checkpoints WHERE technique_run=? ORDER BY id",
            (run_id,))
        self.assertEqual(
            [
                (row["from_phase"], row["to_phase"],
                 row["note"], row["user_confirmed"])
                for row in checkpoints
            ],
            [
                ("work", "grounding", "", 1),
                ("grounding", "reflect",
                 "Eleştirel sesin altında korunma ihtiyacı var.", 1),
                ("reflect", "end", "Bugünlük burada tamamlıyorum.", 1),
            ])

    def test_emergency_stop_is_terminal_idempotent_and_unblocks_new_work(self):
        conv_id, run_id, chair, method = self.open_chair()
        original_revision = chair["revision"]
        payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "action": "stop",
            "expected_revision": "stale-client-value",
        }
        status, stopped, _ = self.request(
            "POST", "/api/chair-work", payload)
        self.assertEqual(status, 200, stopped)
        chair = stopped["chairwork"]
        self.assertEqual(
            (chair["status"], chair["technique_status"], chair["phase"]),
            ("closed", "stopped", "end"))
        self.assertEqual(chair["revision"], original_revision + 1)
        checkpoint = self.row(
            "SELECT from_phase,to_phase,user_confirmed,note "
            "FROM technique_checkpoints WHERE technique_run=?",
            (run_id,),
        )
        self.assertEqual(
            (checkpoint["from_phase"], checkpoint["to_phase"],
             checkpoint["user_confirmed"]),
            ("work", "end", 0),
        )
        self.assertIn("şimdiye dönüş önerildi", checkpoint["note"])

        status, duplicate, _ = self.request(
            "POST", "/api/chair-work", payload)
        self.assertEqual(status, 200, duplicate)
        self.assertEqual(duplicate["chairwork"]["revision"], chair["revision"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM technique_checkpoints "
                "WHERE technique_run=?", (run_id,))["n"],
            1)

        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 3,
            })
        self.assertEqual(status, 200, proposed)
        self.assertNotEqual(proposed["run"]["id"], run_id)
        self.assertEqual(proposed["run"]["status"], "proposed")

    def test_exact_personal_stop_signal_is_terminal_and_never_saved_as_a_turn(self):
        conv_id, run_id, chair, _ = self.open_chair()

        for index, content in enumerate(("DUR!", "Lütfen DUR")):
            status, spoken, _ = self.speak(
                conv_id,
                chair,
                content=content,
                event_id="stop-signal-mismatch-{}".format(index),
            )
            self.assertEqual(status, 200, spoken)
            self.assertEqual(spoken["chairwork"]["status"], "dialogue")
            chair = spoken["chairwork"]

        status, stopped, _ = self.speak(
            conv_id,
            chair,
            content="  ｄｕｒ \n",
            event_id="stop-signal-exact-normalized",
        )
        self.assertEqual(status, 200, stopped)
        chair = stopped["chairwork"]
        self.assertEqual(
            (chair["status"], chair["technique_status"], chair["phase"]),
            ("closed", "stopped", "end"))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND actor_kind='part' AND authored_by='user'",
                (conv_id,),
            )["n"],
            2,
        )
        run = self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual((run["status"], run["phase"]), ("stopped", "end"))

    def test_multiple_chair_runs_remain_separate_selectable_and_counted(self):
        conv_id, _, first, method = self.open_chair()
        status, first_turn, _ = self.speak(
            conv_id, first, content="İlk çalışmanın sözü.",
            event_id="multi-first")
        self.assertEqual(status, 200, first_turn)
        first = first_turn["chairwork"]
        for action in ("ground", "reflect", "complete"):
            checkpoint = self.checkpoint_fields(action)
            status, body, _ = self.request(
                "POST", "/api/chair-work", {
                    "conv_id": conv_id,
                    "chair_run_id": first["id"],
                    "action": action,
                    "expected_revision": first["revision"],
                    **checkpoint,
                })
            self.assertEqual(status, 200, body)
            first = body["chairwork"]

        status, proposed, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "action": "propose",
                "method_key": method["key"],
                "intensity": 4,
            })
        self.assertEqual(status, 200, proposed)
        self.assertIsNone(proposed["chairwork"])
        self.assertEqual(
            [row["id"] for row in proposed["chairworks"]], [first["id"]])

        second_run_id = proposed["run"]["id"]
        status, consented, _ = self.request(
            "POST", "/api/technique-run", {
                "conv_id": conv_id,
                "id": second_run_id,
                "action": "consent",
                "confirmed": True,
            })
        self.assertEqual(status, 200, consented)
        second = consented["chairwork"]
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(len(consented["chairworks"]), 2)

        status, begun, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": second["id"],
                "action": "begin",
                "orientation_ok": True,
                "frame_ok": True,
                "stop_signal": "DUR",
                "goal_text": "İkinci çalışmanın parçalarını ayırt etmek",
            })
        self.assertEqual(status, 200, begun)
        second = begun["chairwork"]
        status, second_turn, _ = self.speak(
            conv_id, second, content="İkinci çalışmanın sözü.",
            event_id="multi-second")
        self.assertEqual(status, 200, second_turn)
        second = second_turn["chairwork"]

        status, compact, _ = self.request(
            "GET", "/api/chair-work?conv_id={}".format(conv_id))
        self.assertEqual(status, 200, compact)
        self.assertEqual(compact["chairwork"]["id"], second["id"])
        self.assertEqual(
            [row["id"] for row in compact["chairworks"]],
            [first["id"], second["id"]])
        self.assertEqual(
            [row["turn_count"] for row in compact["chairworks"]], [1, 1])
        self.assertTrue(all(
            row["conversation_turn_count"] == 2
            for row in compact["chairworks"]))

        status, selected, _ = self.request(
            "GET", "/api/chair-work?conv_id={}&chair_run_id={}".format(
                conv_id, first["id"]))
        self.assertEqual(status, 200, selected)
        self.assertEqual(selected["chairwork"]["id"], first["id"])
        self.assertEqual(
            selected["chairwork"]["turns"][0]["content"],
            "İlk çalışmanın sözü.")

        status, full, _ = self.request(
            "GET", "/api/chair-work?conv_id={}&full=1".format(conv_id))
        self.assertEqual(status, 200, full)
        self.assertEqual(
            [row["turns"][0]["content"] for row in full["chairworks"]],
            ["İlk çalışmanın sözü.", "İkinci çalışmanın sözü."])

        status, techniques, _ = self.request(
            "GET", "/api/technique-runs?conv_id={}".format(conv_id))
        self.assertEqual(status, 200, techniques)
        self.assertEqual(techniques["chairwork"]["id"], second["id"])
        self.assertEqual(len(techniques["chairworks"]), 2)

        status, conversation, _ = self.request(
            "GET", "/api/conversation?id={}".format(conv_id))
        self.assertEqual(status, 200, conversation)
        self.assertEqual(conversation["chair_turn_count"], 2)
        self.assertEqual(conversation["activity_count"], 2)

        status, _, _ = self.request(
            "GET", "/api/chair-work?conv_id={}&chair_run_id=999999".format(
                conv_id))
        self.assertEqual(status, 404)
        status, _, _ = self.request(
            "GET", "/api/chair-work?conv_id={}&chair_run_id=abc".format(
                conv_id))
        self.assertEqual(status, 400)

    def test_conversation_activity_counts_and_full_view_include_all_chair_turns(self):
        conv_id, _, chair, _ = self.open_chair()
        participant = chair["participants"][0]["id"]
        with app.db() as conn:
            chair_row = conn.execute(
                "SELECT * FROM chair_runs WHERE id=?", (chair["id"],)).fetchone()
            for index in range(app.CHAIR_TURN_LIMIT + 3):
                app.insert_chair_turn(
                    conn, chair_row, "part", "user", "utterance",
                    "Tam kayıt turu {}".format(index), "test",
                    "turn:full-{}".format(index),
                    participant=participant)

        status, compact, _ = self.request(
            "GET", "/api/chair-work?conv_id={}".format(conv_id))
        self.assertEqual(status, 200, compact)
        self.assertEqual(
            len(compact["chairwork"]["turns"]), app.CHAIR_TURN_LIMIT)
        self.assertEqual(
            compact["chairwork"]["turn_count"], app.CHAIR_TURN_LIMIT + 3)

        status, full, _ = self.request(
            "GET", "/api/chair-work?conv_id={}&full=1".format(conv_id))
        self.assertEqual(status, 200, full)
        self.assertEqual(
            len(full["chairwork"]["turns"]), app.CHAIR_TURN_LIMIT + 3)
        self.assertEqual(
            full["chairwork"]["turns"][0]["content"], "Tam kayıt turu 0")

        status, conversation, _ = self.request(
            "GET", "/api/conversation?id={}".format(conv_id))
        self.assertEqual(status, 200, conversation)
        self.assertEqual(conversation["message_count"], 0)
        self.assertEqual(
            conversation["chair_turn_count"], app.CHAIR_TURN_LIMIT + 3)
        self.assertEqual(
            conversation["activity_count"], app.CHAIR_TURN_LIMIT + 3)

        status, rows, _ = self.request("GET", "/api/conversations")
        self.assertEqual(status, 200, rows)
        listed = next(row for row in rows if row["id"] == conv_id)
        self.assertEqual(listed["n"], app.CHAIR_TURN_LIMIT + 3)

    def test_completion_creates_map_review_candidate_but_never_reached(self):
        conv_id, run_id, chair, _ = self.open_chair()
        for action, expected in (
                ("ground", "grounding"),
                ("reflect", "review"),
                ("complete", "closed")):
            checkpoint = self.checkpoint_fields(action)
            status, body, _ = self.request(
                "POST", "/api/chair-work", {
                    "conv_id": conv_id,
                    "chair_run_id": chair["id"],
                    "action": action,
                    "expected_revision": chair["revision"],
                    **checkpoint,
                })
            self.assertEqual(status, 200, body)
            chair = body["chairwork"]
            self.assertEqual(chair["status"], expected)

        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual((run["status"], run["phase"]),
                         ("completed", "end"))
        target = self.row(
            "SELECT * FROM session_map_targets WHERE conv=? "
            "AND is_current=1", (conv_id,))
        self.assertEqual(target["status"], "review")
        self.assertEqual(target["candidate"], 1)
        self.assertIsNone(target["reached_at"])
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM session_map_events "
                "WHERE conv=? AND to_status='reached'", (conv_id,))["n"],
            0)

    def test_session_end_is_always_allowed_and_closes_active_chairwork(self):
        conv_id, run_id, chair, _ = self.open_chair()
        _, spoken, _ = self.speak(
            conv_id, chair, event_id="end-user")
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (conv_id,))

        status, ended, _ = self.request(
            "POST", "/api/end", {
                "conv_id": conv_id,
                "map_outcome": "paused",
                "map_fit": "too_much",
                "map_note": "Burada durmayı seçtim.",
            })

        self.assertEqual(status, 200, ended)
        self.assertTrue(ended["processing"])
        self.assertEqual(ended["chairwork"]["status"], "closed")
        self.assertEqual(self.conversation_row(conv_id)["ended"], 1)
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual((run["status"], run["phase"]),
                         ("stopped", "end"))
        self.assertEqual(
            ended["map"]["target"]["node_id"], "young:closure")
        self.assertEqual(ended["map"]["target"]["status"], "reached")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=? "
                "AND id=? AND reverted_at IS NULL",
                (conv_id, spoken["turn"]["id"]))["n"],
            1)

    def test_export_version_six_and_per_conversation_delete_cover_chair_graph(self):
        conv_id, _, chair, _ = self.open_chair()
        _, spoken, _ = self.speak(
            conv_id, chair, content="Dışa aktarılacak parça sözü.",
            event_id="export-turn")
        app.set_setting("openai_api_key", "EXPORTTA-GORUNMEMELI")

        status, exported, _ = self.request("GET", "/api/export-json")

        self.assertEqual(status, 200, exported)
        self.assertEqual(exported["version"], 6)
        for table in ("chair_runs", "chair_participants", "chair_turns"):
            self.assertIn(table, exported["data"])
        self.assertTrue(any(
            row["conv"] == conv_id
            for row in exported["data"]["chair_runs"]))
        self.assertTrue(any(
            row["conv"] == conv_id
            and row["content"] == "Dışa aktarılacak parça sözü."
            for row in exported["data"]["chair_turns"]))
        rendered = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("EXPORTTA-GORUNMEMELI", rendered)

        status, body, _ = self.request(
            "POST", "/api/delete", {"id": conv_id})
        self.assertEqual(status, 200, body)
        self.assertIsNone(self.conversation_row(conv_id))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (conv_id,))["n"],
            0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_runs WHERE conv=?",
                (conv_id,))["n"],
            0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_participants "
                "WHERE chair_run=?", (chair["id"],))["n"],
            0)
        self.assertIsNotNone(spoken["turn"]["id"])

    def test_retention_and_delete_all_remove_chair_graph_without_orphans(self):
        old_conv, _, old_chair, _ = self.open_chair()
        self.speak(
            old_conv, old_chair, event_id="old-retention",
            content="Eski sandalye sözü.")
        recent_conv, _, recent_chair, _ = self.open_chair()
        self.speak(
            recent_conv, recent_chair, event_id="recent-retention",
            content="Yeni sandalye sözü.")
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET created='2000-01-01 00:00',"
                "updated='2000-01-02 00:00' WHERE id=?", (old_conv,))
            conn.execute(
                "UPDATE conversations SET created='2999-01-01 00:00',"
                "updated='2999-01-02 00:00' WHERE id=?", (recent_conv,))
        app.set_setting("retention_days", "30")

        self.assertEqual(app.enforce_retention_policy(), 1)
        self.assertIsNone(self.conversation_row(old_conv))
        self.assertIsNotNone(self.conversation_row(recent_conv))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_runs WHERE conv=?",
                (old_conv,))["n"],
            0)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_participants "
                "WHERE chair_run=?", (old_chair["id"],))["n"],
            0)
        self.assertGreater(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE conv=?",
                (recent_conv,))["n"],
            0)

        status, body, _ = self.request(
            "POST", "/api/delete-all",
            {"confirm": "TÜM VERİLERİ SİL"})
        self.assertEqual(status, 200, body)
        for table in (
                "chair_turns", "chair_participants", "chair_runs"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.row(
                        "SELECT COUNT(*) AS n FROM {}".format(table))["n"],
                    0)
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_transcript_is_capped_and_diagnostics_redact_labels_and_content(self):
        conv_id, _, chair, _ = self.open_chair()
        secret_label = "GİZLİ-PARÇA-ETİKETİ"
        participant = chair["participants"][0]["id"]
        status, renamed, _ = self.request(
            "POST", "/api/chair-work", {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "rename",
                "participant_id": participant,
                "label": secret_label,
            })
        self.assertEqual(status, 200, renamed)
        chair = renamed["chairwork"]
        for index in range(app.CHAIR_PROMPT_TURN_LIMIT + 2):
            status, body, _ = self.speak(
                conv_id, chair,
                content="GİZLİ-TUR-{:02d}".format(index),
                event_id="cap-{:02d}".format(index),
                participant_id=participant)
            self.assertEqual(status, 200, body)
            chair = body["chairwork"]

        transcript = app.transcript_of(conv_id, "terapi")
        self.assertNotIn("GİZLİ-TUR-00", transcript)
        self.assertNotIn("GİZLİ-TUR-01", transcript)
        self.assertIn("GİZLİ-TUR-02", transcript)
        self.assertIn(
            "GİZLİ-TUR-{:02d}".format(
                app.CHAIR_PROMPT_TURN_LIMIT + 1),
            transcript)
        self.assertEqual(
            transcript.count("Danışan — ["),
            app.CHAIR_PROMPT_TURN_LIMIT)

        status, diagnostics, _ = self.request(
            "GET", "/api/diagnostics?id={}".format(conv_id))
        self.assertEqual(status, 200, diagnostics)
        self.assertIn("chair_work", diagnostics["components"])
        chair_diag = diagnostics["chair_work"]
        self.assertTrue(chair_diag["content_redacted"])
        self.assertEqual(
            chair_diag["stored_turns"],
            app.CHAIR_PROMPT_TURN_LIMIT + 2)
        self.assertNotIn("turns", chair_diag)
        self.assertNotIn("participants", chair_diag)
        rendered = json.dumps(diagnostics, ensure_ascii=False)
        self.assertNotIn(secret_label, rendered)
        self.assertNotIn("GİZLİ-TUR", rendered)
