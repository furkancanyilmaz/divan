import json
from unittest import mock

from support import HTTPTestCase, app


# Young'ın mod haritasının tamamı. Anahtarlar kalıcıdır: eşitleme ve
# kullanıcı kayıtları bunlara dayanır, yeniden adlandırılmaz.
REQUIRED_STRATEGY_IDS = {
    # Çocuk modları
    "vulnerable_child",
    "abandoned_child",
    "lonely_child",
    "humiliated_child",
    "dependent_child",
    "angry_child",
    "enraged_child",
    "impulsive_child",
    # İşlevsiz ebeveyn modları
    "punitive_parent",
    "demanding_parent",
    "guilt_inducing_parent",
    # Teslimci başa çıkma
    "compliant_surrender",
    # Kaçıngan başa çıkma
    "detached_protector",
    "detached_self_soother",
    "avoidant_protector",
    # Aşırı telafi
    "overcompensator",
    "bully_attack",
    "counterattack",
    "suspicious_overcontroller",
    "perfectionistic_overcontroller",
    "approval_seeker",
    # Sağlıklı modlar
    "healthy_adult",
    "happy_child",
}


class SchemaStrategyTestCase(HTTPTestCase):

    def post(self, path, **payload):
        return self.request("POST", path, payload)

    def method_for_node(self, therapist, node_id):
        return next(
            row for row in app.method_records(therapist)
            if row["node_id"] == node_id)

    def propose_and_consent(self, conv_id, therapist, node_id):
        method = self.method_for_node(therapist, node_id)
        if method["risk_level"] == "enhanced":
            status, meta, _ = self.post(
                "/api/session-meta",
                conv_id=conv_id,
                precheck_done=True,
                safety_ok=True,
                anxiety_start=3,
                intensity_limit=7,
            )
            self.assertEqual(status, 200, meta)
        status, proposed, _ = self.post(
            "/api/technique-run",
            conv_id=conv_id,
            action="propose",
            method_key=method["key"],
            intensity=3,
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

    def open_chair(self, therapist, node_id):
        conv_id = self.conversation(therapist=therapist)
        method, technique, consented = self.propose_and_consent(
            conv_id, therapist, node_id)
        chair = consented["chairwork"]
        self.assertIsNotNone(chair)
        status, begun, _ = self.post(
            "/api/chair-work",
            conv_id=conv_id,
            chair_run_id=chair["id"],
            action="begin",
            revision=chair["revision"],
            orientation_ok=True,
            frame_ok=True,
            stop_signal="DUR",
            goal_text="Şema modlarını güvenle ayırt etmek",
        )
        self.assertEqual(status, 200, begun)
        return conv_id, technique, begun["chairwork"], method

    def chair_turn(self, conv_id, chair, event_id, **overrides):
        payload = {
            "conv_id": conv_id,
            "chair_run_id": chair["id"],
            "participant_id": chair["active_participant_id"],
            "content": "Bu yanımın bugün neyi koruduğunu fark ediyorum.",
            "intensity": 4,
            "expected_revision": chair["revision"],
            "client_event_id": event_id,
        }
        payload.update(overrides)
        return self.request("POST", "/api/chair-turn", payload)

    def create_imagery(self, node_id):
        conv_id = self.conversation(therapist="young")
        method, technique, _ = self.propose_and_consent(
            conv_id, "young", node_id)
        status, created, _ = self.post(
            "/api/imagery-work",
            conv_id=conv_id,
            action="create",
            technique_run_id=technique["id"],
        )
        self.assertEqual(status, 200, created)
        return conv_id, technique, created["imagerywork"], method

    def open_imagery(self, node_id):
        conv_id, technique, work, method = self.create_imagery(node_id)
        status, consented, _ = self.post(
            "/api/imagery-work",
            conv_id=conv_id,
            imagery_run_id=work["id"],
            action="consent",
            revision=work["revision"],
            orientation_ok=True,
            frame_ok=True,
            reality_clear=True,
            stop_signal="DUR",
        )
        self.assertEqual(status, 200, consented)
        work = consented["imagerywork"]
        status, begun, _ = self.post(
            "/api/imagery-work",
            conv_id=conv_id,
            imagery_run_id=work["id"],
            action="begin",
            revision=work["revision"],
            intensity=3,
        )
        self.assertEqual(status, 200, begun)
        return conv_id, technique, begun["imagerywork"], method

    def imagery_turn(self, conv_id, work, event_id, **overrides):
        payload = {
            "conv_id": conv_id,
            "imagery_run_id": work["id"],
            "content": "Bugünkü olayda neye ihtiyaç duyduğumu fark ediyorum.",
            "intensity": 4,
            "orientation_ok": True,
            "reality_clear": True,
            "expected_revision": work["revision"],
            "client_event_id": event_id,
        }
        payload.update(overrides)
        return self.request("POST", "/api/imagery-turn", payload)

    @staticmethod
    def prompt_data(messages):
        user_message = messages[-1]
        assert user_message["role"] == "user"
        return json.loads(user_message["content"].split("\n\n", 1)[1])


class SchemaStrategyLibraryTests(SchemaStrategyTestCase):

    def test_catalogue_has_complete_versioned_mode_records(self):
        self.assertIsInstance(app.SCHEMA_STRATEGY_VERSION, int)
        self.assertGreaterEqual(app.SCHEMA_STRATEGY_VERSION, 1)
        rows = app.SCHEMA_STRATEGY_LIBRARY
        ids = [row["id"] for row in rows]
        self.assertEqual(set(ids), REQUIRED_STRATEGY_IDS)
        self.assertEqual(len(ids), len(set(ids)))

        chair_stages = {
            stage["id"] for stage in app.CHAIR_METHODS[
                "young:method:chair-dialogue"]["stages"]
        }
        reparenting_stages = {
            stage["id"] for stage in app.IMAGERY_METHODS[
                app.REPARENTING_METHOD_NODE_ID]["stages"]
        }
        allowed_stages = chair_stages | reparenting_stages
        required_fields = {
            "id", "label", "group", "chair_label", "slot_keys",
            "stage_ids", "recognize", "understand", "question", "steps",
            "healthy_adult_bridge", "real_world_bridge", "avoid",
        }
        for row in rows:
            with self.subTest(strategy=row["id"]):
                self.assertTrue(required_fields.issubset(row))
                for field in (
                        "label", "group", "chair_label", "recognize",
                        "understand", "question", "healthy_adult_bridge",
                        "real_world_bridge", "avoid"):
                    self.assertIsInstance(row[field], str)
                    self.assertTrue(row[field].strip())
                self.assertTrue(row["slot_keys"])
                self.assertTrue(row["stage_ids"])
                self.assertTrue(row["steps"])
                self.assertTrue(set(row["stage_ids"]).issubset(allowed_stages))
                self.assertIs(
                    app.schema_strategy_record(row["id"]), row)

        public = app.public_schema_strategies(
            "mode_map", "coping_mode")
        self.assertEqual(
            {row["id"] for row in public}, REQUIRED_STRATEGY_IDS)
        self.assertTrue(all(type(row["relevant"]) is bool for row in public))
        json.dumps(public, ensure_ascii=False)
        self.assertIsNone(app.schema_strategy_record("not-a-real-strategy"))

    def test_payload_exposes_catalogue_only_for_schema_methods(self):
        _, _, young_chair, _ = self.open_chair(
            "young", "young:method:chair-dialogue")
        self.assertEqual(
            young_chair["schema_strategy_version"],
            app.SCHEMA_STRATEGY_VERSION)
        self.assertEqual(
            {row["id"] for row in young_chair["schema_strategies"]},
            REQUIRED_STRATEGY_IDS)

        _, _, perls_chair, _ = self.open_chair(
            "perls", "perls:method:empty-chair")
        self.assertIsNone(perls_chair["schema_strategy_version"])
        self.assertEqual(perls_chair["schema_strategies"], [])

        _, _, reparenting, _ = self.create_imagery(
            app.REPARENTING_METHOD_NODE_ID)
        self.assertEqual(
            reparenting["schema_strategy_version"],
            app.SCHEMA_STRATEGY_VERSION)
        self.assertEqual(
            {row["id"] for row in reparenting["schema_strategies"]},
            REQUIRED_STRATEGY_IDS)

        _, _, rescripting, _ = self.create_imagery(
            app.IMAGERY_METHOD_NODE_ID)
        self.assertIsNone(rescripting["schema_strategy_version"])
        self.assertEqual(rescripting["schema_strategies"], [])

    def test_invalid_and_cross_method_strategy_ids_are_rejected(self):
        conv_id, _, chair, _ = self.open_chair(
            "young", "young:method:chair-dialogue")
        status, body, _ = self.chair_turn(
            conv_id,
            chair,
            "invalid-schema-chair-strategy",
            strategy_id="not-a-real-strategy",
        )
        self.assertEqual(status, 400, body)
        self.assertIn("geçersiz şema modu stratejisi", body["error"])

        conv_id, _, perls, _ = self.open_chair(
            "perls", "perls:method:empty-chair")
        status, body, _ = self.chair_turn(
            conv_id,
            perls,
            "cross-method-chair-strategy",
            strategy_id="vulnerable_child",
        )
        self.assertEqual(status, 400, body)
        self.assertIn("şema modu stratejisi kullanmaz", body["error"])

        conv_id, _, work, _ = self.open_imagery(
            app.REPARENTING_METHOD_NODE_ID)
        status, body, _ = self.imagery_turn(
            conv_id,
            work,
            "invalid-reparenting-strategy",
            step_data={"strategy_id": "not-a-real-strategy"},
        )
        self.assertEqual(status, 400, body)
        self.assertIn("geçersiz şema modu stratejisi", body["error"])

        conv_id, _, rescripting, _ = self.open_imagery(
            app.IMAGERY_METHOD_NODE_ID)
        status, body, _ = self.imagery_turn(
            conv_id,
            rescripting,
            "cross-method-imagery-strategy",
            step_data={"strategy_id": "vulnerable_child"},
        )
        self.assertEqual(status, 400, body)

    def test_chair_strategy_is_bound_to_turn_and_guidance_prompt(self):
        conv_id, _, chair, _ = self.open_chair(
            "young", "young:method:chair-dialogue")
        status, written, _ = self.chair_turn(
            conv_id,
            chair,
            "bound-chair-strategy",
            strategy_id="angry_child",
        )
        self.assertEqual(status, 200, written)
        self.assertEqual(
            written["turn"]["payload"]["strategy_id"], "angry_child")

        with app.db() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,)).fetchone()
            run = app.chair_run_row(
                conn, conv_id, written["chairwork"]["id"])
            messages = app.build_chair_guidance_messages(conn, conv, run)
        data = self.prompt_data(messages)
        self.assertEqual(
            data["turns"][-1]["strategy_id"], "angry_child")
        strategies = {
            row["id"]: row for row in data["schema_strategies"]
        }
        self.assertIn("angry_child", strategies)
        self.assertTrue(strategies["angry_child"]["avoid"])
        self.assertIn("Şema modu strateji sınırı", messages[0]["content"])

    def test_reparenting_strategy_is_bound_to_step_and_guidance_prompt(self):
        conv_id, _, work, _ = self.open_imagery(
            app.REPARENTING_METHOD_NODE_ID)
        status, first, _ = self.imagery_turn(
            conv_id, work, "reparent-trigger-step")
        self.assertEqual(status, 200, first)
        work = first["imagerywork"]
        status, advanced, _ = self.post(
            "/api/imagery-work",
            conv_id=conv_id,
            imagery_run_id=work["id"],
            action="advance",
            revision=work["revision"],
        )
        self.assertEqual(status, 200, advanced)
        work = advanced["imagerywork"]
        self.assertEqual(work["current_stage"], "mode_and_need")

        status, written, _ = self.imagery_turn(
            conv_id,
            work,
            "bound-reparenting-strategy",
            step_data={
                "mode_id": "angry_child",
                "strategy_id": "angry_child",
            },
        )
        self.assertEqual(status, 200, written)
        written_step = next(
            row for row in reversed(written["imagerywork"]["turns"])
            if row["authored_by"] == "user"
            and row["stage"] == "mode_and_need")
        self.assertEqual(
            written_step["step_data"]["strategy_id"], "angry_child")

        with app.db() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id=?",
                (conv_id,)).fetchone()
            run = app.imagery_run_row(
                conn, conv_id, written["imagerywork"]["id"])
            messages = app.build_imagery_guidance_messages(conn, conv, run)
        data = self.prompt_data(messages)
        self.assertEqual(
            data["turns"][-1]["step_data"]["strategy_id"],
            "angry_child")
        self.assertIn(
            "angry_child",
            {row["id"] for row in data["schema_strategies"]})
        self.assertIn(
            "step_data.strategy_id", messages[0]["content"])

    def test_dynamic_chair_label_role_script_is_rejected_end_to_end(self):
        conv_id, _, chair, _ = self.open_chair(
            "young", "young:method:chair-dialogue")
        participant_id = chair["active_participant_id"]
        status, renamed, _ = self.post(
            "/api/chair-work",
            conv_id=conv_id,
            chair_run_id=chair["id"],
            action="rename",
            revision=chair["revision"],
            participant_id=participant_id,
            label="İçimdeki Müfettiş",
        )
        self.assertEqual(status, 200, renamed)
        chair = renamed["chairwork"]
        status, written, _ = self.chair_turn(
            conv_id,
            chair,
            "dynamic-role-boundary-turn",
            strategy_id="demanding_parent",
        )
        self.assertEqual(status, 200, written)

        model_output = json.dumps({
            "observation": "Talepkâr bir standart belirgin.",
            "instruction": (
                'İçimdeki Müfettiş şöyle desin: "Daha çok çalışmalısın."'),
            "check_in": "Bu anda devam etmek istiyor musun?",
        }, ensure_ascii=False)
        request = {
            "conv_id": conv_id,
            "chair_run_id": written["chairwork"]["id"],
            "after_seq": written["turn"]["seq"],
            "revision": written["chairwork"]["revision"],
            "request_id": "dynamic-role-boundary-guide",
        }
        with mock.patch.object(
                app, "ds_complete", return_value=model_output):
            status, body, _ = self.request(
                "POST", "/api/chair-guidance", request)
        self.assertEqual(status, 502, body)
        self.assertEqual(body["code"], "unsafe_chair_guidance")
        self.assertEqual(
            self.row(
                "SELECT COUNT(*) AS n FROM chair_turns "
                "WHERE chair_run=? AND authored_by='model'",
                (chair["id"],),
            )["n"],
            0,
        )
