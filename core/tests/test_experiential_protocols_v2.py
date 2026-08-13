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

IMAGERY_NODE_IDS = {
    "young:method:imagery-rescripting",
    "young:method:limited-reparenting",
}

FEEDBACK_FITS = ("fit", "partly", "missed", "stop")


class ExperientialProtocolTestCase(HTTPTestCase):

    def post(self, path, **payload):
        return self.request("POST", path, payload)

    def method_for_node(self, therapist, node_id):
        return next(
            row for row in app.method_records(therapist)
            if row["node_id"] == node_id)

    @staticmethod
    def stage_ids(value):
        stages = value.get("stages", value) if isinstance(value, dict) else value
        result = []
        for stage in stages:
            if isinstance(stage, str):
                result.append(stage)
            else:
                result.append(stage["id"])
        return result

    @staticmethod
    def option_ids(options):
        result = []
        for option in options:
            if isinstance(option, str):
                result.append(option)
                continue
            for key in ("id", "value", "fit", "key"):
                if key in option:
                    result.append(option[key])
                    break
            else:
                raise AssertionError(
                    "feedback option has no stable identifier: {!r}".format(
                        option))
        return result

    def propose_and_consent(self, conv_id, therapist, node_id, intensity=3):
        method = self.method_for_node(therapist, node_id)
        status, proposed, _ = self.post(
            "/api/technique-run",
            conv_id=conv_id,
            action="propose",
            method_key=method["key"],
            intensity=intensity,
        )
        self.assertEqual(status, 200, proposed)
        status, consented, _ = self.post(
            "/api/technique-run",
            conv_id=conv_id,
            id=proposed["run"]["id"],
            action="consent",
            confirmed=True,
        )
        self.assertEqual(status, 200, consented)
        return method, consented["run"], consented

    def open_chair(self, therapist="young",
                   node_id="young:method:chair-dialogue", intensity=3):
        conv_id = self.conversation(therapist=therapist)
        method, technique, consented = self.propose_and_consent(
            conv_id, therapist, node_id, intensity=intensity)
        chair = consented["chairwork"]
        self.assertIsNotNone(chair)
        self.assertEqual(chair["status"], "ready")
        status, begun, _ = self.post(
            "/api/chair-work",
            conv_id=conv_id,
            chair_run_id=chair["id"],
            action="begin",
            revision=chair["revision"],
            orientation_ok=True,
            frame_ok=True,
            stop_signal="DUR",
            goal_text="Parçaları güvenle ayırt etmek",
        )
        self.assertEqual(status, 200, begun)
        chair = begun["chairwork"]
        self.assertEqual(chair["status"], "dialogue")
        return conv_id, technique, chair, method

    def chair_action(self, conv_id, chair, action, **overrides):
        payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "action": action,
            "revision": chair["revision"],
        }
        if action == "ground":
            payload.update({
                "checkpoint_confirmed": True,
                "orientation_ok": True,
                "intensity": 3,
            })
        elif action == "reflect":
            payload.update({
                "checkpoint_confirmed": True,
                "checkpoint_note": "Bu çalışmadan fark ettiğim kısa not.",
            })
        elif action == "complete":
            payload["checkpoint_confirmed"] = True
        payload.update(overrides)
        return self.request("POST", "/api/chair-work", payload)

    def chair_turn(self, conv_id, chair, content="Bugün bunu fark ediyorum.",
                   intensity=4, event_id="chair-v2-turn", **overrides):
        payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "participant_id": chair["active_participant_id"],
            "content": content,
            "intensity": intensity,
            "expected_revision": chair["revision"],
            "client_event_id": event_id,
        }
        payload.update(overrides)
        return self.request("POST", "/api/chair-turn", payload)

    def chair_guidance(self, conv_id, turn_body, request_id="chair-v2-guide"):
        return {
            "conv_id": conv_id,
            "chair_run_id": turn_body["chairwork"]["id"],
            "after_seq": turn_body["turn"]["seq"],
            "revision": turn_body["chairwork"]["revision"],
            "request_id": request_id,
        }

    def create_imagery(self, node_id="young:method:limited-reparenting",
                       intensity=3):
        conv_id = self.conversation(therapist="young")
        method, technique, _ = self.propose_and_consent(
            conv_id, "young", node_id, intensity=intensity)
        status, created, _ = self.post(
            "/api/imagery-work",
            conv_id=conv_id,
            action="create",
            technique_run_id=technique["id"],
        )
        self.assertEqual(status, 200, created)
        work = created["imagerywork"]
        self.assertFalse(work["consented"])
        return conv_id, technique, work, method

    def imagery_action(self, conv_id, work, action, **overrides):
        payload = {
            "conv_id": conv_id,
            "imagery_run_id": work["id"],
            "action": action,
            "revision": work["revision"],
        }
        payload.update(overrides)
        return self.request("POST", "/api/imagery-work", payload)

    def consent_imagery(self, conv_id, work):
        status, body, _ = self.imagery_action(
            conv_id,
            work,
            "consent",
            orientation_ok=True,
            frame_ok=True,
            reality_clear=True,
            stop_signal="DUR",
        )
        self.assertEqual(status, 200, body)
        return body["imagerywork"]

    def begin_imagery(self, conv_id, work):
        status, body, _ = self.imagery_action(
            conv_id,
            work,
            "begin",
            orientation_ok=True,
            frame_ok=True,
            reality_clear=True,
            stop_signal="DUR",
        )
        self.assertEqual(status, 200, body)
        result = body["imagerywork"]
        self.assertEqual(result["status"], "active")
        return result

    def open_imagery(self, node_id="young:method:limited-reparenting"):
        conv_id, technique, work, method = self.create_imagery(node_id)
        work = self.consent_imagery(conv_id, work)
        work = self.begin_imagery(conv_id, work)
        return conv_id, technique, work, method

    def imagery_turn(self, conv_id, work, event_id="reparent-v2-turn",
                     orientation_ok=True, **overrides):
        payload = {
            "conv_id": conv_id,
            "imagery_run_id": work["id"],
            "content": "Şu anda görülmeye ve korunmaya ihtiyacım var.",
            "intensity": 4,
            "orientation_ok": orientation_ok,
            "reality_clear": True,
            "expected_revision": work["revision"],
            "client_event_id": event_id,
        }
        payload.update(overrides)
        return self.request("POST", "/api/imagery-turn", payload)


class ChairProtocolRegistryV2Tests(ExperientialProtocolTestCase):

    def test_every_chair_protocol_has_versioned_clinical_metadata(self):
        self.assertEqual(app.CHAIR_PROTOCOL_VERSION, 2)
        self.assertEqual(set(app.CHAIR_METHODS), CHAIR_NODE_IDS)

        for node_id, config in app.CHAIR_METHODS.items():
            with self.subTest(node_id=node_id):
                self.assertIsInstance(config["title"], str)
                self.assertGreaterEqual(len(config["title"].strip()), 3)
                self.assertIsInstance(config["frame"], str)
                self.assertGreaterEqual(len(config["frame"].strip()), 12)

                stages = self.stage_ids(config)
                self.assertGreaterEqual(len(stages), 4)
                self.assertEqual(len(stages), len(set(stages)))
                self.assertTrue(all(
                    isinstance(stage, str) and stage.strip()
                    for stage in stages))

                participant_meta = config["participant_meta"]
                self.assertIsInstance(participant_meta, dict)
                default_slots = [
                    row["slot_key"] if isinstance(row, dict) else row[0]
                    for row in config["participants"]
                ]
                self.assertTrue(set(default_slots).issubset(participant_meta))
                for slot_key in default_slots:
                    meta = participant_meta[slot_key]
                    self.assertTrue(
                        (isinstance(meta, str) and meta.strip())
                        or (isinstance(meta, dict) and meta),
                        "{} has empty participant metadata".format(slot_key),
                    )
                json.dumps(config, ensure_ascii=False)

    def test_each_school_and_method_has_a_distinct_stage_sequence(self):
        signatures = {
            node_id: tuple(self.stage_ids(app.CHAIR_METHODS[node_id]))
            for node_id in sorted(CHAIR_NODE_IDS)
        }
        self.assertEqual(
            len(set(signatures.values())),
            len(signatures),
            "Chair protocols must not share a generic one-size-fits-all "
            "sequence",
        )

        young = signatures["young:method:chair-dialogue"]
        satir = signatures["satir:method:parts-party"]
        perls = {
            signatures["perls:method:empty-chair"],
            signatures["perls:method:two-chair-conflict"],
        }
        greenberg = {
            signatures["greenberg:method:two-chair-self-criticism"],
            signatures["greenberg:method:unfinished-business-chair"],
        }
        self.assertNotEqual(young, satir)
        self.assertTrue(perls.isdisjoint(greenberg))

    def test_method_record_and_live_payload_expose_rich_protocol_state(self):
        conv_id, _, chair, method = self.open_chair()
        config = app.CHAIR_METHODS[chair["method_node_id"]]

        method_config = method["chair_config"]
        self.assertEqual(method_config["protocol_version"], 2)
        for field in ("title", "frame", "stages", "participant_meta"):
            self.assertIn(field, method_config)

        self.assertEqual(chair["protocol_version"], 2)
        self.assertEqual(chair["protocol_title"], config["title"])
        self.assertEqual(chair["protocol_frame"], config["frame"])
        self.assertEqual(
            self.stage_ids(chair["stage_defs"]),
            self.stage_ids(config),
        )
        self.assertEqual(
            self.stage_ids(chair["stages"]),
            self.stage_ids(config),
        )
        self.assertIn(chair["current_stage"], self.stage_ids(config))
        self.assertEqual(
            chair["current_stage_index"],
            self.stage_ids(config).index(chair["current_stage"]),
        )
        self.assertEqual(chair["stage_index"], chair["current_stage_index"])
        self.assertIn("stage_progress", chair)
        self.assertIsInstance(chair["completed_stage_ids"], list)
        self.assertIsInstance(chair["round_no"], int)
        self.assertGreaterEqual(chair["round_no"], 0)
        self.assertEqual(
            set(chair["participant_meta"]),
            set(config["participant_meta"]),
        )
        self.assertEqual(
            self.option_ids(chair["feedback_options"]),
            list(FEEDBACK_FITS),
        )
        participant_ids = {row["id"] for row in chair["participants"]}
        self.assertIn(
            chair["suggested_next_participant_id"],
            participant_ids | {None},
        )
        self.assertIsNone(chair["latest_guidance"])
        self.assertIsNone(chair["latest_feedback"])
        self.assertTrue(chair["capabilities"]["next_stage"])
        self.assertIn("previous_stage", chair["capabilities"])
        self.assertFalse(chair["capabilities"]["feedback"])

        status, fetched, _ = self.request(
            "GET",
            "/api/chair-work?conv_id={}&chair_run_id={}".format(
                conv_id, chair["id"]),
        )
        self.assertEqual(status, 200, fetched)
        self.assertEqual(
            fetched["chairwork"]["current_stage"], chair["current_stage"])


class ChairLifecycleV2Tests(ExperientialProtocolTestCase):

    def test_ground_pauses_and_resume_restores_the_interrupted_stage(self):
        conv_id, _, chair, _ = self.open_chair()
        interrupted_stage = chair["current_stage"]

        status, grounded, _ = self.chair_action(
            conv_id, chair, "ground", intensity=3)
        self.assertEqual(status, 200, grounded)
        grounded = grounded["chairwork"]
        self.assertEqual(grounded["status"], "grounding")
        self.assertEqual(grounded["technique_status"], "paused")
        self.assertEqual(grounded["phase"], "grounding")
        self.assertTrue(grounded["capabilities"]["resume"])
        self.assertFalse(grounded["capabilities"]["speak"])

        status, resumed, _ = self.chair_action(
            conv_id,
            grounded,
            "resume",
            checkpoint_confirmed=True,
            orientation_ok=True,
            intensity=3,
        )
        self.assertEqual(status, 200, resumed)
        resumed = resumed["chairwork"]
        self.assertEqual(resumed["status"], "dialogue")
        self.assertEqual(resumed["technique_status"], "active")
        self.assertEqual(resumed["phase"], "work")
        self.assertEqual(resumed["current_stage"], interrupted_stage)
        self.assertTrue(resumed["capabilities"]["speak"])

    def test_next_and_previous_stage_follow_the_configured_sequence(self):
        conv_id, _, chair, _ = self.open_chair()
        stages = self.stage_ids(
            app.CHAIR_METHODS[chair["method_node_id"]])
        initial_stage = chair["current_stage"]
        initial_index = chair["current_stage_index"]
        self.assertLess(initial_index, len(stages) - 1)

        status, advanced, _ = self.chair_action(
            conv_id, chair, "next_stage")
        self.assertEqual(status, 200, advanced)
        advanced = advanced["chairwork"]
        self.assertEqual(advanced["current_stage_index"], initial_index + 1)
        self.assertEqual(
            advanced["current_stage"], stages[initial_index + 1])
        self.assertIn(initial_stage, advanced["completed_stage_ids"])
        self.assertTrue(advanced["capabilities"]["previous_stage"])

        status, previous, _ = self.chair_action(
            conv_id, advanced, "previous_stage")
        self.assertEqual(status, 200, previous)
        previous = previous["chairwork"]
        self.assertEqual(previous["current_stage"], initial_stage)
        self.assertEqual(previous["current_stage_index"], initial_index)
        self.assertNotIn(initial_stage, previous["completed_stage_ids"])

    def test_feedback_records_each_fit_and_stop_enters_grounding(self):
        model_result = json.dumps({
            "observation": "İhtiyaç daha görünür hale geliyor.",
            "instruction": "İstersen bunu tek cümleyle sınırlandır.",
            "check_in": "Bu gözlem sana uyuyor mu?",
        }, ensure_ascii=False)

        for index, fit in enumerate(FEEDBACK_FITS):
            with self.subTest(fit=fit):
                conv_id, _, chair, _ = self.open_chair()
                status, spoken, _ = self.chair_turn(
                    conv_id,
                    chair,
                    event_id="feedback-user-{}".format(index),
                )
                self.assertEqual(status, 200, spoken)
                request = self.chair_guidance(
                    conv_id,
                    spoken,
                    request_id="feedback-guidance-{}".format(index),
                )
                with mock.patch.object(
                        app, "ds_complete", return_value=model_result):
                    status, guided, _ = self.request(
                        "POST", "/api/chair-guidance", request)
                self.assertEqual(status, 200, guided)
                guidance_turn_id = guided["turn"]["id"]

                status, body, _ = self.chair_action(
                    conv_id,
                    guided["chairwork"],
                    "feedback",
                    fit=fit,
                    guidance_turn_id=guidance_turn_id,
                )
                self.assertEqual(status, 200, body)
                work = body["chairwork"]
                self.assertEqual(work["latest_feedback"]["fit"], fit)
                self.assertEqual(
                    work["latest_feedback"]["guidance_turn_id"],
                    guidance_turn_id,
                )
                feedback = self.row(
                    "SELECT * FROM chair_turns WHERE chair_run=? "
                    "AND turn_kind='feedback' ORDER BY seq DESC LIMIT 1",
                    (chair["id"],),
                )
                self.assertIsNotNone(feedback)
                self.assertEqual(feedback["actor_kind"], "system")
                payload = json.loads(feedback["payload_json"])
                self.assertEqual(payload["fit"], fit)
                self.assertEqual(
                    payload["guidance_turn_id"], guidance_turn_id)

                if fit == "stop":
                    self.assertEqual(work["status"], "closed")
                    self.assertEqual(work["technique_status"], "stopped")
                    self.assertEqual(work["phase"], "end")
                else:
                    self.assertEqual(work["status"], "dialogue")

    def test_archived_conversation_blocks_all_chair_mutations(self):
        conv_id, _, chair, _ = self.open_chair()
        status, spoken, _ = self.chair_turn(
            conv_id, chair, event_id="archive-source")
        self.assertEqual(status, 200, spoken)
        chair = spoken["chairwork"]
        before_revision = chair["revision"]
        before_turns = self.row(
            "SELECT COUNT(*) AS n FROM chair_turns WHERE chair_run=?",
            (chair["id"],),
        )["n"]
        with app.db() as conn:
            conn.execute(
                "UPDATE conversations SET archived_at=? WHERE id=?",
                (app.now(), conv_id),
            )

        requests = (
            (
                "/api/chair-work",
                {
                    "conv_id": conv_id,
                    "chair_run_id": chair["id"],
                    "action": "next_stage",
                    "revision": chair["revision"],
                },
            ),
            (
                "/api/chair-turn",
                {
                    "conv_id": conv_id,
                    "chair_run_id": chair["id"],
                    "participant_id": chair["active_participant_id"],
                    "content": "Arşive yazılmamalı.",
                    "intensity": 3,
                    "expected_revision": chair["revision"],
                    "client_event_id": "archived-turn",
                },
            ),
            (
                "/api/chair-guidance",
                {
                    "conv_id": conv_id,
                    "chair_run_id": chair["id"],
                    "after_seq": spoken["turn"]["seq"],
                    "revision": chair["revision"],
                    "request_id": "archived-guidance",
                },
            ),
        )
        with mock.patch.object(app, "ds_complete") as model:
            for path, payload in requests:
                with self.subTest(path=path):
                    status, _, _ = self.request("POST", path, payload)
                    self.assertEqual(status, 409)
        model.assert_not_called()
        self.assertEqual(
            self.row(
                "SELECT revision FROM chair_runs WHERE id=?",
                (chair["id"],),
            )["revision"],
            before_revision,
        )
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE chair_run=?",
                (chair["id"],),
            )["n"],
            before_turns,
        )

    def test_chair_turn_intensity_is_a_strict_json_integer(self):
        conv_id, technique, chair, _ = self.open_chair(intensity=3)
        before_revision = chair["revision"]
        invalid_values = (-1, 11, True, "4", 4.0)
        for index, value in enumerate(invalid_values):
            with self.subTest(value=value):
                status, _, _ = self.chair_turn(
                    conv_id,
                    chair,
                    intensity=value,
                    event_id="strict-intensity-{}".format(index),
                )
                self.assertEqual(status, 400)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE chair_run=?",
                (chair["id"],),
            )["n"],
            0,
        )
        self.assertEqual(
            self.row(
                "SELECT revision FROM chair_runs WHERE id=?",
                (chair["id"],),
            )["revision"],
            before_revision,
        )
        self.assertEqual(
            self.row(
                "SELECT intensity_current FROM technique_runs WHERE id=?",
                (technique["id"],),
            )["intensity_current"],
            3,
        )

        for edge in (0, 10):
            with self.subTest(valid_edge=edge):
                edge_conv, _, edge_chair, _ = self.open_chair(intensity=3)
                status, accepted, _ = self.chair_turn(
                    edge_conv,
                    edge_chair,
                    intensity=edge,
                    event_id="valid-edge-{}".format(edge),
                )
                self.assertEqual(status, 200, accepted)
                self.assertEqual(accepted["turn"]["intensity"], edge)
                self.assertEqual(accepted["chairwork"]["intensity"], edge)

    def test_stage_and_turn_mutations_reject_a_provided_stale_revision(self):
        conv_id, _, chair, _ = self.open_chair()
        revision = chair["revision"]

        status, _, _ = self.request(
            "POST",
            "/api/chair-work",
            {
                "conv_id": conv_id,
                "chair_run_id": chair["id"],
                "action": "next_stage",
                "revision": revision - 1,
            },
        )
        self.assertEqual(status, 409)

        base_turn = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "participant_id": chair["active_participant_id"],
            "content": "Eski panel bunu kaydetmemeli.",
            "intensity": 4,
        }
        stale_turn = dict(
            base_turn,
            client_event_id="revision-turn-stale",
            expected_revision=revision - 1,
        )
        status, _, _ = self.request(
            "POST", "/api/chair-turn", stale_turn)
        self.assertEqual(status, 409)

        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE chair_run=?",
                (chair["id"],),
            )["n"],
            0,
        )
        self.assertEqual(
            self.row(
                "SELECT revision FROM chair_runs WHERE id=?",
                (chair["id"],),
            )["revision"],
            revision,
        )

        # Missing revisions remain accepted for older clients. New clients
        # send expected_revision, whose stale value is rejected above.
        compatible = dict(
            base_turn,
            content="Eski istemci de güvenle yazabilmeli.",
            client_event_id="revision-turn-compatible",
        )
        status, accepted, _ = self.request(
            "POST", "/api/chair-turn", compatible)
        self.assertEqual(status, 200, accepted)

    def test_undo_restores_previous_reported_intensity(self):
        conv_id, technique, chair, _ = self.open_chair(intensity=3)
        status, first, _ = self.chair_turn(
            conv_id,
            chair,
            content="İlk sözüm.",
            intensity=5,
            event_id="undo-intensity-1",
        )
        self.assertEqual(status, 200, first)
        status, second, _ = self.chair_turn(
            conv_id,
            first["chairwork"],
            content="İkinci sözüm.",
            intensity=7,
            event_id="undo-intensity-2",
        )
        self.assertEqual(status, 200, second)
        self.assertEqual(second["chairwork"]["intensity"], 7)

        status, undone, _ = self.chair_action(
            conv_id, second["chairwork"], "undo")
        self.assertEqual(status, 200, undone)
        undone = undone["chairwork"]
        self.assertEqual(undone["intensity"], 5)
        self.assertEqual(
            self.row(
                "SELECT intensity_current FROM technique_runs WHERE id=?",
                (technique["id"],),
            )["intensity_current"],
            5,
        )

        status, empty, _ = self.chair_action(
            conv_id, undone, "undo")
        self.assertEqual(status, 200, empty)
        empty = empty["chairwork"]
        self.assertEqual(empty["intensity"], 3)
        self.assertEqual(
            self.row(
                "SELECT intensity_current FROM technique_runs WHERE id=?",
                (technique["id"],),
            )["intensity_current"],
            3,
        )

    def test_guidance_idempotency_is_bound_to_sequence_and_revision(self):
        conv_id, _, chair, _ = self.open_chair()
        status, first, _ = self.chair_turn(
            conv_id, chair, event_id="binding-user-1")
        self.assertEqual(status, 200, first)
        original_request = self.chair_guidance(
            conv_id, first, request_id="stable-binding")
        model_result = json.dumps({
            "observation": "İki eğilim arasındaki gerilim duyuluyor.",
            "instruction": "İstersen ihtiyacı tek cümle yaz.",
            "check_in": "Bu gözlem sana uyuyor mu?",
        }, ensure_ascii=False)
        with mock.patch.object(
                app, "ds_complete", return_value=model_result) as model:
            status, guided, _ = self.request(
                "POST", "/api/chair-guidance", original_request)
        self.assertEqual(status, 200, guided)
        self.assertFalse(guided["duplicate"])
        model.assert_called_once()

        with mock.patch.object(app, "ds_complete") as replay_model:
            status, replayed, _ = self.request(
                "POST", "/api/chair-guidance", original_request)
        self.assertEqual(status, 200, replayed)
        self.assertTrue(replayed["duplicate"])
        self.assertEqual(replayed["turn"]["id"], guided["turn"]["id"])
        replay_model.assert_not_called()

        status, second, _ = self.chair_turn(
            conv_id,
            guided["chairwork"],
            content="Şimdi farklı bir şey söylüyorum.",
            event_id="binding-user-2",
        )
        self.assertEqual(status, 200, second)
        rebound = self.chair_guidance(
            conv_id, second, request_id="stable-binding")
        with mock.patch.object(app, "ds_complete") as rebound_model:
            status, _, _ = self.request(
                "POST", "/api/chair-guidance", rebound)
        self.assertEqual(status, 409)
        rebound_model.assert_not_called()
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns WHERE chair_run=? "
                "AND authored_by='model' AND reverted_at IS NULL",
                (chair["id"],),
            )["n"],
            1,
        )


class ReparentingProtocolV2Tests(ExperientialProtocolTestCase):

    def test_imagery_registry_includes_rescripting_and_reparenting(self):
        self.assertEqual(set(app.IMAGERY_METHODS), IMAGERY_NODE_IDS)
        for node_id, config in app.IMAGERY_METHODS.items():
            with self.subTest(node_id=node_id):
                self.assertIsInstance(config["title"], str)
                self.assertTrue(config["title"].strip())
                self.assertIsInstance(config["frame"], str)
                self.assertGreaterEqual(len(config["frame"].strip()), 12)
                stages = self.stage_ids(config)
                self.assertGreaterEqual(len(stages), 5)
                self.assertEqual(len(stages), len(set(stages)))

        self.assertNotEqual(
            tuple(self.stage_ids(
                app.IMAGERY_METHODS[
                    "young:method:imagery-rescripting"])),
            tuple(self.stage_ids(
                app.IMAGERY_METHODS[
                    "young:method:limited-reparenting"])),
        )
        limited = self.method_for_node(
            "young", "young:method:limited-reparenting")
        self.assertEqual(limited["risk_level"], "enhanced")
        self.assertEqual(limited["interaction_mode"], "imagery_work")
        self.assertIn(
            "young:method:limited-reparenting",
            app.ENHANCED_GATE_NODE_IDS,
        )
        self.assertIsNotNone(limited["imagery_config"])
        self.assertEqual(
            self.stage_ids(limited["imagery_config"]),
            self.stage_ids(
                app.IMAGERY_METHODS[
                    "young:method:limited-reparenting"]),
        )

    def test_reparenting_consent_requires_all_four_explicit_checks(self):
        valid = {
            "orientation_ok": True,
            "frame_ok": True,
            "reality_clear": True,
            "stop_signal": "DUR",
        }
        invalid_cases = []
        for field in valid:
            missing = dict(valid)
            missing.pop(field)
            invalid_cases.append(("missing-{}".format(field), missing))
            false = dict(valid)
            false[field] = "" if field == "stop_signal" else False
            invalid_cases.append(("false-{}".format(field), false))

        for label, checks in invalid_cases:
            with self.subTest(case=label):
                conv_id, _, work, _ = self.create_imagery()
                status, body, _ = self.imagery_action(
                    conv_id, work, "consent", **checks)
                self.assertEqual(status, 409, body)
                status, fetched, _ = self.request(
                    "GET",
                    "/api/imagery-work?conv_id={}".format(conv_id),
                )
                self.assertEqual(status, 200, fetched)
                self.assertFalse(fetched["imagerywork"]["consented"])

        conv_id, _, work, _ = self.create_imagery()
        work = self.consent_imagery(conv_id, work)
        self.assertTrue(work["consented"])
        self.assertTrue(work["orientation_confirmed"])
        self.assertEqual(work["stop_signal"], "DUR")

    def test_reparenting_turn_requires_orientation_and_advances_by_config(self):
        conv_id, _, work, _ = self.open_imagery()
        starting_stage = work["current_stage"]
        starting_index = work["current_stage_index"]
        starting_progress = work["stage_progress"]
        descriptors = work["choice_descriptors"]
        self.assertEqual(
            [(item["id"], item["title"], item["action"])
             for item in descriptors],
            [
                ("present_trigger:1", "Bu an", "advance"),
                ("present_trigger:2", "Daha küçük bir an", "advance"),
                ("present_trigger:3", "Şimdiye dön", "ground"),
            ],
        )

        for index, orientation in enumerate((None, False)):
            payload = {
                "conv_id": conv_id,
                "imagery_run_id": work["id"],
                "content": "Yönelim olmadan kaydedilmemeli.",
                "intensity": 4,
                "reality_clear": True,
                "expected_revision": work["revision"],
                "client_event_id": "orientation-block-{}".format(index),
            }
            if orientation is not None:
                payload["orientation_ok"] = orientation
            status, _, _ = self.request(
                "POST", "/api/imagery-turn", payload)
            self.assertEqual(status, 409)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM imagery_steps "
                "WHERE imagery_run=?",
                (work["id"],),
            )["n"],
            0,
        )

        status, written, _ = self.imagery_turn(
            conv_id, work, event_id="config-stage-user")
        self.assertEqual(status, 200, written)
        work = written["imagerywork"]
        self.assertEqual(work["current_stage"], starting_stage)

        status, advanced, _ = self.imagery_action(
            conv_id, work, "advance")
        self.assertEqual(status, 200, advanced)
        advanced = advanced["imagerywork"]
        configured = self.stage_ids(
            app.IMAGERY_METHODS[
                "young:method:limited-reparenting"])
        self.assertEqual(advanced["current_stage_index"], starting_index + 1)
        self.assertEqual(
            advanced["current_stage"], configured[starting_index + 1])
        self.assertIn(starting_stage, advanced["completed_stage_ids"])
        self.assertNotEqual(advanced["stage_progress"], starting_progress)
        self.assertEqual(
            self.stage_ids(advanced["stage_defs"]), configured)

    def test_typed_now_choice_routes_to_ground_without_recording_normal_turn(self):
        conv_id, _, work, _ = self.open_imagery()
        choice = next(
            item for item in work["choice_descriptors"]
            if item["action"] == "ground")
        status, grounded, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="typed-ground-choice",
            content="Şimdiye dönmeyi seçiyorum.",
            intensity=3,
            step_data={"choice": choice["id"]},
        )
        self.assertEqual(status, 200, grounded)
        self.assertEqual(grounded["choice_action"], "ground")
        work = grounded["imagerywork"]
        self.assertEqual((work["status"], work["phase"]),
                         ("paused", "grounding"))
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM imagery_steps "
                "WHERE imagery_run=?", (work["id"],))["n"],
            0,
        )

        status, duplicate, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="typed-ground-choice",
            content="Bu metin normal bir tur olmamalı.",
            intensity=3,
            step_data={"choice": choice["id"]},
        )
        self.assertEqual(status, 200, duplicate)
        self.assertTrue(duplicate["duplicate"])

    def test_exact_imagery_stop_signal_closes_without_writing_a_step(self):
        conv_id, technique, work, _ = self.open_imagery()

        for index, content in enumerate(("DUR!", "Lütfen DUR")):
            status, written, _ = self.imagery_turn(
                conv_id,
                work,
                event_id="imagery-stop-mismatch-{}".format(index),
                content=content,
            )
            self.assertEqual(status, 200, written)
            work = written["imagerywork"]
            self.assertEqual(work["status"], "active")

        status, stopped, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="imagery-stop-exact-normalized",
            content="  ｄｕｒ \n",
        )
        self.assertEqual(status, 200, stopped)
        work = stopped["imagerywork"]
        self.assertEqual(
            (work["status"], work["technique_status"], work["phase"]),
            ("closed", "stopped", "end"),
        )
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM imagery_steps "
                "WHERE imagery_run=? AND authored_by='user'",
                (work["id"],),
            )["n"],
            2,
        )
        run = self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?",
            (technique["id"],),
        )
        self.assertEqual((run["status"], run["phase"]), ("stopped", "end"))

    def test_reparenting_ground_and_resume_restore_the_interrupted_stage(self):
        conv_id, _, work, _ = self.open_imagery()
        interrupted_stage = work["current_stage"]

        status, grounded, _ = self.imagery_action(
            conv_id,
            work,
            "ground",
            orientation_ok=True,
            intensity=3,
        )
        self.assertEqual(status, 200, grounded)
        grounded = grounded["imagerywork"]
        self.assertEqual(grounded["status"], "paused")
        self.assertEqual(grounded["phase"], "grounding")
        self.assertTrue(grounded["capabilities"]["resume"])

        status, resumed, _ = self.imagery_action(
            conv_id,
            grounded,
            "resume",
            orientation_ok=True,
            frame_ok=True,
            reality_clear=True,
            intensity=3,
        )
        self.assertEqual(status, 200, resumed)
        resumed = resumed["imagerywork"]
        self.assertEqual(resumed["status"], "active")
        self.assertEqual(resumed["phase"], "work")
        self.assertEqual(resumed["current_stage"], interrupted_stage)

    def test_reparenting_completion_requires_grounding_and_safe_orientation(self):
        conv_id, _, work, _ = self.open_imagery()

        status, _, _ = self.imagery_action(
            conv_id,
            work,
            "complete",
            orientation_ok=True,
            intensity=3,
        )
        self.assertEqual(status, 409)

        status, grounded, _ = self.imagery_action(
            conv_id,
            work,
            "ground",
            orientation_ok=True,
            intensity=3,
        )
        self.assertEqual(status, 200, grounded)
        grounded = grounded["imagerywork"]

        valid_completion = {
            "grounding_confirmed": True,
            "orientation_ok": True,
            "reality_clear": True,
            "intensity": 3,
        }
        invalid_checks = []
        for field in (
                "grounding_confirmed", "orientation_ok", "reality_clear"):
            checks = dict(valid_completion)
            checks[field] = False
            invalid_checks.append(checks)
        invalid_checks.append(dict(valid_completion, intensity=8))
        for checks in invalid_checks:
            with self.subTest(checks=checks):
                status, _, _ = self.imagery_action(
                    conv_id, grounded, "complete", **checks)
                self.assertEqual(status, 409)

        status, completed, _ = self.imagery_action(
            conv_id,
            grounded,
            "complete",
            **valid_completion
        )
        self.assertEqual(status, 200, completed)
        completed = completed["imagerywork"]
        configured = self.stage_ids(
            app.IMAGERY_METHODS[
                "young:method:limited-reparenting"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["current_stage"], configured[-1])
        self.assertEqual(
            completed["current_stage_index"], len(configured) - 1)

    def test_reparenting_prompt_and_validator_enforce_relational_boundaries(self):
        safe = (
            "Bu ihtiyacın anlaşılır. İstersen Sağlıklı Yetişkin sesinle "
            "kendine sıcak ve gerçekçi bir koruma cümlesi yaz.")
        first = app.validate_reparenting_guidance(safe)
        second = app.validate_reparenting_guidance(safe)
        self.assertEqual(first, second)

        unsafe = (
            "Ben senin annenim.",
            "Ben senin babanım.",
            "Seni hep koruyacağım.",
            "Yalnız ben seni gerçekten anlarım.",
        )
        for text in unsafe:
            with self.subTest(text=text):
                with self.assertRaises(app.ProviderError):
                    app.validate_reparenting_guidance(text)

        conv_id, _, work, _ = self.open_imagery()
        status, written, _ = self.imagery_turn(
            conv_id, work, event_id="prompt-contract-user")
        self.assertEqual(status, 200, written)
        captured = []

        def safe_model(messages, **_kwargs):
            captured.extend(messages)
            return json.dumps({
                "observation": "Korunma ihtiyacın anlaşılır görünüyor.",
                "instruction": (
                    "İstersen Sağlıklı Yetişkin sesinle bir cümle yaz."),
                "check_in": "Bu öneri sana uyuyor mu?",
            }, ensure_ascii=False)

        with mock.patch.object(
                app, "ds_complete", side_effect=safe_model):
            status, guided, _ = self.imagery_action(
                conv_id, written["imagerywork"], "guidance")
        self.assertEqual(status, 200, guided)
        system = captured[0]["content"].casefold()
        for phrase in (
                "gerçek ebeveyn",
                "sağlıklı yetişkin",
                "yalnız ben",
                "anı",
                "çocuklaştır"):
            with self.subTest(prompt_phrase=phrase):
                self.assertIn(phrase.casefold(), system)

    def test_reparenting_http_guidance_rejects_dependency_language(self):
        conv_id, _, work, _ = self.open_imagery()
        status, written, _ = self.imagery_turn(
            conv_id, work, event_id="validator-http-user")
        self.assertEqual(status, 200, written)
        invalid_result = json.dumps({
            "observation": "Yalnız ben seni gerçekten anlarım.",
            "instruction": "Bana güven; seni hep koruyacağım.",
            "check_in": "Benimle kalmak ister misin?",
        }, ensure_ascii=False)

        with mock.patch.object(
                app, "ds_complete", return_value=invalid_result):
            status, body, _ = self.imagery_action(
                conv_id, written["imagerywork"], "guidance")
        self.assertEqual(status, 502, body)
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM imagery_steps "
                "WHERE imagery_run=? AND authored_by='model' "
                "AND reverted_at IS NULL",
                (work["id"],),
            )["n"],
            0,
        )

    def test_consent_payload_exposes_all_four_server_confirmations(self):
        conv_id, _, work, _ = self.create_imagery()
        self.assertTrue(work["capabilities"]["begin"])
        self.assertFalse(work["orientation_confirmed"])
        self.assertFalse(work["frame_confirmed"])
        self.assertFalse(work["reality_confirmed"])
        self.assertFalse(work["consent_complete"])

        work = self.consent_imagery(conv_id, work)
        self.assertTrue(work["capabilities"]["begin"])
        self.assertTrue(work["orientation_confirmed"])
        self.assertTrue(work["frame_confirmed"])
        self.assertTrue(work["reality_confirmed"])
        self.assertTrue(work["consent_complete"])

    def test_ui_choice_field_is_accepted_and_stale_turn_is_rejected(self):
        conv_id, _, work, _ = self.open_imagery()
        status, written, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="ui-choice-field",
            step_data={"choice": "Bu an · Korunmak"},
        )
        self.assertEqual(status, 200, written)
        turn = next(
            row for row in written["imagerywork"]["turns"]
            if row["authored_by"] == "user")
        self.assertEqual(
            turn["step_data"]["choice"], "Bu an · Korunmak")

        status, body, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="stale-second-event",
            content="Eski panelden ikinci ve farklı bir tur.",
        )
        self.assertEqual(status, 409, body)

    def test_imagery_turn_retry_is_idempotent_and_keeps_resume_stage(self):
        conv_id, _, work, _ = self.open_imagery()
        interrupted = work["current_stage"]
        status, first, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="stable-imagery-retry",
            intensity=8,
            step_data={"choice": "Şimdiye dön"},
        )
        self.assertEqual(status, 200, first)
        self.assertTrue(first["paused_for_intensity"])
        paused = first["imagerywork"]
        self.assertEqual(paused["resume_stage"], interrupted)
        revision_after_first = paused["revision"]

        status, replay, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="stable-imagery-retry",
            intensity=8,
            step_data={"choice": "Şimdiye dön"},
        )
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(
            replay["imagerywork"]["revision"], revision_after_first)
        self.assertEqual(
            replay["imagerywork"]["resume_stage"], interrupted)

        status, body, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="stable-imagery-retry",
            intensity=8,
            content="Aynı olay kimliğiyle farklı içerik.",
            step_data={"choice": "Şimdiye dön"},
        )
        self.assertEqual(status, 409, body)

    def test_imagery_turn_enforces_the_session_intensity_limit(self):
        conv_id, _, work, _ = self.open_imagery()
        with app.db() as conn:
            conn.execute(
                "INSERT INTO session_meta(conv,intensity_limit,updated) "
                "VALUES(?,?,?)",
                (conv_id, 5, app.now()),
            )
        status, body, _ = self.imagery_turn(
            conv_id,
            work,
            event_id="above-session-limit",
            intensity=6,
        )
        self.assertEqual(status, 409, body)
        self.assertIn("5 sınırını", body["error"])

    def test_completion_builds_a_user_authored_reparenting_summary(self):
        conv_id, _, work, _ = self.open_imagery()
        contents = {
            "present_trigger": "Bugün eleştirilince içime kapandım.",
            "mode_and_need": "Kırılgan yanımın görülmeye ihtiyacı var.",
            "warm_validation": "Bunun zor gelmesi anlaşılır.",
            "protection": "Bir süre mesafe koyacağım.",
            "realistic_limit": "Bu dille konuşulmasını kabul etmiyorum.",
            "healthy_adult_words": "Seni duyuyorum ve yanında duruyorum.",
            "real_world_bridge": "Güvendiğim bir kişiyi arayacağım.",
        }
        for index, (stage, content) in enumerate(contents.items()):
            self.assertEqual(work["current_stage"], stage)
            status, written, _ = self.imagery_turn(
                conv_id,
                work,
                event_id="summary-user-{}".format(index),
                content=content,
                step_data={"choice": "Kullanıcının seçimi"},
            )
            self.assertEqual(status, 200, written)
            status, advanced, _ = self.imagery_action(
                conv_id, written["imagerywork"], "advance")
            self.assertEqual(status, 200, advanced)
            work = advanced["imagerywork"]

        self.assertEqual(work["current_stage"], "grounding")
        status, completed, _ = self.imagery_action(
            conv_id,
            work,
            "complete",
            grounding_confirmed=True,
            orientation_ok=True,
            reality_clear=True,
            intensity=3,
        )
        self.assertEqual(status, 200, completed)
        summary = completed["imagerywork"]["summary"]
        self.assertIsInstance(summary, dict)
        self.assertEqual(
            summary["healthy_adult_response"],
            contents["healthy_adult_words"],
        )
        self.assertEqual(
            summary["today_action"], contents["real_world_bridge"])

    def test_post_validation_rejects_scripted_parts_and_broader_parent_roles(self):
        unsafe_reparenting = (
            "Bugün senin annen olarak yanında olacağım.",
            "Artık terapistin benim.",
            "Seni seviyorum yavrum.",
            "I am your parent and I will never leave you.",
        )
        for text in unsafe_reparenting:
            with self.subTest(text=text):
                with self.assertRaises(app.ProviderError):
                    app.validate_reparenting_guidance(text)

        with self.assertRaises(app.ProviderError):
            app.validate_chair_role_boundary({
                "observation": "Eleştirel ses etkin görünüyor.",
                "instruction": (
                    'Kırılgan Çocuk şöyle desin: "Beni korumanı istiyorum."'),
                "check_in": "Bu sana uyuyor mu?",
            })


class ExperientialConsentContractTests(ExperientialProtocolTestCase):

    def test_chair_begin_requires_and_persists_explicit_frame_contract(self):
        conv_id = self.conversation(therapist="young")
        _, _, consented = self.propose_and_consent(
            conv_id, "young", "young:method:chair-dialogue")
        chair = consented["chairwork"]

        status, rejected, _ = self.post(
            "/api/chair-work",
            conv_id=conv_id,
            chair_run_id=chair["id"],
            action="begin",
            revision=chair["revision"],
        )
        self.assertEqual(status, 409, rejected)
        self.assertFalse(rejected.get("ok", False))

        status, begun, _ = self.post(
            "/api/chair-work",
            conv_id=conv_id,
            chair_run_id=chair["id"],
            action="begin",
            revision=chair["revision"],
            orientation_ok=True,
            frame_ok=True,
            stop_signal="  DUR  ",
            goal_text="  Parçaları birbirinden ayırt etmek  ",
        )
        self.assertEqual(status, 200, begun)
        work = begun["chairwork"]
        self.assertTrue(work["consent_complete"])
        self.assertTrue(work["orientation_confirmed"])
        self.assertTrue(work["frame_confirmed"])
        self.assertEqual(work["stop_signal"], "DUR")
        self.assertEqual(
            work["goal_text"], "Parçaları birbirinden ayırt etmek")
        row = self.row(
            "SELECT stop_signal,goal_text,protocol_state_json "
            "FROM chair_runs WHERE id=?", (chair["id"],))
        self.assertEqual(row["stop_signal"], "DUR")
        state = json.loads(row["protocol_state_json"])
        self.assertTrue(state["consent"]["orientation_ok"])
        self.assertTrue(state["consent"]["frame_ok"])

    def test_preconsent_imagery_stop_closes_instead_of_bypassing_consent(self):
        conv_id, _, work, _ = self.create_imagery()
        self.assertFalse(work["consent_complete"])

        status, stopped, _ = self.imagery_action(
            conv_id, work, "stop")
        self.assertEqual(status, 200, stopped)
        closed = stopped["imagerywork"]
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["technique_status"], "stopped")
        self.assertEqual(closed["phase"], "end")

        status, rejected, _ = self.request(
            "POST", "/api/imagery-work", {
                "conv_id": conv_id,
                "imagery_run_id": work["id"],
                "action": "complete",
                "grounding_confirmed": True,
                "orientation_ok": True,
                "reality_clear": True,
                "intensity": 3,
            })
        self.assertEqual(status, 409, rejected)
