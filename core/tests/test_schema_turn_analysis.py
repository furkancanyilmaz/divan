import json
from unittest import mock

from support import HTTPTestCase, app


class SchemaTurnAnalysisTests(HTTPTestCase):
    stamp = "2026-08-17 12:00"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        with app.db() as connection:
            app.initialize_living_map_autoscan_state(connection, self.conv)

    def completed_turn(self, text="kullanıcı anlatısı", safety=False):
        with app.db() as connection:
            user_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'user',?,?,'completed')",
                (self.conv, text, self.stamp)).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','yanıt',?,"
                "'completed')", (self.conv, self.stamp)).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'succeeded',?,?)",
                (self.conv, self.stamp, self.stamp)).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,created,updated) VALUES(?,?,?,?,?,"
                "'completed',?,?)",
                ("schema-turn-{:012d}".format(user_id), job_id, self.conv,
                 user_id, assistant_id, self.stamp, self.stamp))
            if safety:
                connection.execute(
                    "INSERT INTO safety_events(conv,source_message,kind,"
                    "created) VALUES(?,?,'crisis',?)",
                    (self.conv, user_id, self.stamp))
        return user_id, assistant_id

    @staticmethod
    def response(user_id):
        schema_id = next(iter(app.SCHEMA_CANDIDATE_CATALOG))
        mode_id = next(iter(app.SCHEMA_MODE_CANDIDATE_CATALOG))
        return json.dumps({
            "insights": [],
            "schema_candidates": [{
                "existing_claim_id": None,
                "schema_id": schema_id,
                "mode_id": mode_id,
                "statement": "Bu anlatımda erken bir çalışma olasılığı olabilir",
                "trigger": "bekleme", "experience": "kaygı",
                "response": "geri çekilme",
                "short_term_effect": "korunma",
                "long_term_effect": "uzaklık", "need": "güven",
                "context": "bu olay", "counterexample": "",
                "supporting_message_ids": [user_id],
                "counterexample_message_ids": [],
            }],
        }, ensure_ascii=False)

    def claim_auto(self, user_id):
        job_id = app.create_living_map_autoscan_job(user_id)[0]
        with app.db() as connection:
            connection.execute(
                "UPDATE living_map_auto_state SET next_attempt_at=0 "
                "WHERE conv=?", (self.conv,))
        self.assertIsNotNone(app.claim_queued_job(job_id))
        return job_id

    @staticmethod
    def provider_pair():
        return app._configured_provider_model_snapshot()

    def analyze_direct(self, user_id, response=None, source="explicit"):
        with mock.patch.object(
                app, "ds_complete",
                return_value=response or self.response(user_id)) as call:
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source=source, raise_errors=True)
        return result, call

    def test_mode_enable_is_future_only_and_first_future_turn_is_analyzed(self):
        old_user, _ = self.completed_turn("eski açık rıza dışı anlatı")
        old_job = self.claim_auto(old_user)
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})):
            app.run_living_map_autoscan_job(old_job)
        _previous, state = app.set_schema_mode(self.conv, True)
        self.assertEqual(state["enrolled_after_message_id"], old_user)
        new_user, new_assistant = self.completed_turn("yeni anlatı")
        job_id = self.claim_auto(new_user)
        with mock.patch.object(
                app, "ds_complete", return_value=self.response(new_user)) as call:
            app.run_living_map_autoscan_job(job_id)
        call.assert_called_once()
        ledger = self.row(
            "SELECT * FROM living_map_turn_analyses WHERE conv=? "
            "AND user_message=?", (self.conv, new_user))
        self.assertEqual(ledger["user_message"], new_user)
        self.assertEqual(ledger["assistant_message"], new_assistant)
        self.assertEqual(ledger["schema_mode"], 1)
        self.assertEqual(ledger["status"], "succeeded")
        candidate = app.schema_path_payload(self.conv)["candidates"][0]
        self.assertEqual(candidate["source_turn"]["user_message_id"], new_user)
        self.assertEqual(
            candidate["source_turn"]["assistant_message_id"], new_assistant)
        self.assertIsNotNone(candidate["schema"])
        self.assertIsNotNone(candidate["mode"])

    def test_generic_coverage_does_not_block_later_schema_rerun(self):
        user_id, _ = self.completed_turn()
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="historical_global", raise_errors=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.row(
            "SELECT schema_mode FROM living_map_turn_analyses")[
                "schema_mode"], 0)
        app.set_schema_mode(self.conv, True)
        with mock.patch.object(
                app, "ds_complete", return_value=self.response(user_id)) as call:
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit", raise_errors=True)
        self.assertEqual(result["status"], "succeeded")
        call.assert_called_once()
        self.assertEqual(self.row(
            "SELECT schema_mode FROM living_map_turn_analyses")[
                "schema_mode"], 1)
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("idempotent rerun called model")):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit", raise_errors=True)
        self.assertTrue(result["already_analyzed"])

    def test_free_form_schema_insight_cannot_bypass_catalog(self):
        user_id, _ = self.completed_turn()
        raw = json.dumps({
            "insights": [{
                "existing_claim_id": None,
                "claim_type": "schema_hypothesis",
                "title": "modelin serbest etiketi",
                "statement": "bir olasılık olabilir",
                "trigger": "", "experience": "", "response": "",
                "short_term_effect": "", "long_term_effect": "",
                "need": "", "context": "", "counterexample": "",
                "supporting_message_ids": [user_id],
                "counterexample_message_ids": [],
            }],
            "schema_candidates": [],
        })
        self.assertEqual(app.parse_turn_analysis_candidates(
            raw, [user_id], schema_mode=True), [])

    def test_mode_off_while_provider_runs_suppresses_stale_result(self):
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn()

        def complete(_messages, **_kwargs):
            app.set_schema_mode(self.conv, False)
            return self.response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit")
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)
        self.assertEqual(self.row(
            "SELECT status FROM living_map_turn_analyses")["status"],
            "interrupted")

    def test_incomplete_safety_and_guest_turns_are_rejected(self):
        app.set_schema_mode(self.conv, True)
        safe_user, _ = self.completed_turn(safety=True)
        with self.assertRaises(app.RequestInputError) as caught:
            app.create_turn_analysis_job(self.conv, safe_user)
        self.assertEqual(caught.exception.error_code, "safety_turn")
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET is_guest=1 WHERE id=?",
                (self.conv,))
        with self.assertRaises(app.RequestInputError) as caught:
            app.create_turn_analysis_job(self.conv, safe_user)
        self.assertEqual(caught.exception.error_code, "guest_conversation")

    def test_synced_preference_needs_local_provider_confirmation(self):
        with app.db() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO session_meta(conv,updated) VALUES(?,?)",
                (self.conv, self.stamp))
            connection.execute(
                "UPDATE session_meta SET schema_mode_enabled=1,"
                "schema_mode_initialized=0,schema_mode_provider='',"
                "schema_mode_model='' WHERE conv=?", (self.conv,))
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?", (self.conv,)
            ).fetchone()
            public = app.schema_mode_public(connection, conv)
        self.assertFalse(public["enabled"])
        self.assertTrue(public["preference_enabled"])
        self.assertTrue(public["pending_device_confirmation"])

        old_user, _ = self.completed_turn("hedef cihazdaki tur")
        job_id = self.claim_auto(old_user)
        with mock.patch.object(
                app, "ds_complete",
                return_value=json.dumps({"insights": []})) as generic_call:
            app.run_living_map_autoscan_job(job_id)
        generic_call.assert_called_once()
        generic_prompt = "\n".join(
            str(message.get("content") or "")
            for message in generic_call.call_args.args[0])
        self.assertNotIn('"schema_candidates"', generic_prompt)
        self.assertNotIn("## Mod önerisi", generic_prompt)
        self.assertEqual(self.row(
            "SELECT schema_mode FROM living_map_turn_analyses WHERE "
            "user_message=?", (old_user,))["schema_mode"], 0)

        provider_id, model_id = self.provider_pair()
        app.set_schema_mode(
            self.conv, True, provider_id=provider_id, model_id=model_id)
        new_user, _ = self.completed_turn("yerel onaydan sonraki tur")
        job_id = self.claim_auto(new_user)
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.response(new_user)) as schema_call:
            app.run_living_map_autoscan_job(job_id)
        schema_call.assert_called_once()
        self.assertEqual(self.row(
            "SELECT schema_mode FROM living_map_turn_analyses WHERE "
            "user_message=?", (new_user,))["schema_mode"], 1)

    def test_provider_change_requires_reconfirmation_and_stale_job_never_calls(self):
        provider_a, model_a = self.provider_pair()
        app.set_schema_mode(
            self.conv, True, provider_id=provider_a, model_id=model_a)
        user_id, _ = self.completed_turn()
        job_id = self.claim_auto(user_id)
        with app.db() as connection:
            connection.execute(
                "INSERT INTO settings(key,value) VALUES('llm_provider',"
                "'openai') ON CONFLICT(key) DO UPDATE SET value='openai'")
        provider_b, model_b = self.provider_pair()
        app.set_schema_mode(
            self.conv, True, provider_id=provider_b, model_id=model_b)
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("eski sağlayıcı çağrılmamalı")):
            app.run_living_map_autoscan_job(job_id)
        self.assertEqual(self.row(
            "SELECT status FROM jobs WHERE id=?", (job_id,))["status"],
            "interrupted")
        self.assertEqual(self.row(
            "SELECT error_code FROM jobs WHERE id=?", (job_id,))[
                "error_code"], "provider_changed")

    def test_http_actions_bind_consent_to_disclosed_provider(self):
        provider_id, model_id = self.provider_pair()
        base = {
            "action": "set_mode", "conv_id": self.conv, "enabled": True,
            "request_id": "schema-mode-http-0001",
        }
        status, body, _ = self.request("POST", "/api/schema-path", base)
        self.assertEqual(status, 400, body)
        self.assertEqual(body["error_code"], "provider_disclosure_required")
        base.update({"provider_id": provider_id, "model_id": model_id,
                     "request_id": "schema-mode-http-0002"})
        status, body, _ = self.request("POST", "/api/schema-path", base)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["schema_mode"]["enabled"])

        user_id, _ = self.completed_turn()
        analyze = {
            "action": "analyze_turn", "conv_id": self.conv,
            "user_message_id": user_id,
            "provider_id": provider_id, "model_id": model_id,
            "request_id": "schema-turn-http-0001",
        }
        status, body, _ = self.request(
            "POST", "/api/schema-path", analyze)
        self.assertEqual(status, 400, body)
        self.assertEqual(
            body["error_code"], "historical_turn_consent_required")
        analyze["consent"] = True
        analyze["request_id"] = "schema-turn-http-0002"
        status, body, _ = self.request(
            "POST", "/api/schema-path", analyze)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["queued"])
        self.assertEqual(
            body["turn_analysis"]["processing_user_message_ids"],
            [user_id])

    def test_auto_job_owns_turn_and_explicit_job_cannot_race_it(self):
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn()
        job_id = self.claim_auto(user_id)
        with self.assertRaises(app.RequestInputError) as caught:
            app.create_turn_analysis_job(self.conv, user_id)
        self.assertEqual(caught.exception.error_code, "analysis_busy")
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.response(user_id)) as call:
            app.run_living_map_autoscan_job(job_id)
        call.assert_called_once()
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM living_map_turn_analyses WHERE "
            "user_message=? AND status='succeeded'", (user_id,))["n"], 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM jobs WHERE conv=? AND status IN "
            "('queued','running','waiting_provider')", (self.conv,))["n"], 0)

    def test_explicit_running_job_blocks_auto_then_ledger_avoids_second_call(self):
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn()
        job_id, created, _already = app.create_turn_analysis_job(
            self.conv, user_id)
        self.assertTrue(created)
        self.assertIsNotNone(app.claim_queued_job(job_id))
        self.assertIsNone(app.create_living_map_autoscan_job(user_id)[0])
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.response(user_id)) as first_call:
            app.run_turn_analysis_job(job_id)
        first_call.assert_called_once()

        auto_job = app.create_living_map_autoscan_job(user_id)[0]
        self.assertIsNotNone(auto_job)
        self.assertIsNotNone(self.claim_auto(user_id))
        with mock.patch.object(
                app, "ds_complete",
                side_effect=AssertionError("ledger sonrası ikinci çağrı")):
            app.run_living_map_autoscan_job(auto_job)
        self.assertEqual(self.row(
            "SELECT status FROM jobs WHERE id=?", (auto_job,))["status"],
            "succeeded")

    def test_source_content_change_during_provider_call_is_suppressed(self):
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn("ilk metin")

        def complete(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE messages SET content='değişmiş metin' WHERE id=?",
                    (user_id,))
            return self.response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit")
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["error_code"], "source_changed")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_revoked_safety_source_cannot_be_reviewed_or_started(self):
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn()
        self.analyze_direct(user_id)
        candidate = app.schema_path_payload(self.conv)["candidates"][0]
        with app.db() as connection:
            connection.execute(
                "INSERT INTO safety_events(conv,source_message,kind,created) "
                "VALUES(?,?,'crisis',?)",
                (self.conv, user_id, self.stamp))
        candidate = app.schema_path_payload(self.conv)["candidates"][0]
        self.assertIsNone(candidate["source_turn"])
        self.assertTrue(candidate["source_invalidated"])
        self.assertFalse(candidate["approved_for_path"])
        self.assertEqual(candidate["available_decisions"], [])
        self.assertEqual(candidate["decision_state"], "invalidated")
        for key in (
                "title", "statement", "trigger", "experience", "response",
                "short_term_effect", "long_term_effect", "need",
                "counterexample", "context"):
            self.assertEqual(candidate[key], "", key)
        self.assertIsNone(candidate["schema"])
        self.assertIsNone(candidate["mode"])
        provider_id, model_id = self.provider_pair()
        status, body, _ = self.request("POST", "/api/schema-path", {
            "action": "review_candidate", "conv_id": self.conv,
            "claim_id": candidate["id"], "decision": "accept",
            "provider_id": provider_id, "model_id": model_id,
            "request_id": "schema-revoked-source-0001",
        })
        self.assertEqual(status, 409, body)

    def test_foreign_keys_off_conversation_and_message_delete_forget_graph(self):
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn()
        self.analyze_direct(user_id)
        self.assertGreater(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            app.delete_conversation_data(connection, self.conv)
        for table in (
                "living_map_turn_analyses", "psych_observations",
                "psych_claim_evidence", "psych_claim_history",
                "psych_claims", "schema_paths", "schema_path_events"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM {}".format(table))["n"], 0)

        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        user_id, _ = self.completed_turn()
        self.analyze_direct(user_id)
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DELETE FROM messages WHERE id=?", (user_id,))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM living_map_turn_analyses")["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_schema_history_scans_each_completed_turn_with_bounded_output(self):
        users = [self.completed_turn("geçmiş {}".format(index))[0]
                 for index in range(3)]
        app.set_schema_mode(self.conv, True)
        provider_id, model_id = self.provider_pair()
        job_id, created = app.create_schema_turn_backfill_job(
            self.conv, provider_id, model_id)
        self.assertTrue(created)
        calls = []

        def complete(messages, **kwargs):
            payload = json.loads(messages[-1]["content"].split("\n\n", 1)[1])
            source_id = payload["USER_MESSAGES"][0]["id"]
            calls.append((source_id, kwargs["max_tokens"]))
            return self.response(source_id)

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            for _ in users:
                self.assertIsNotNone(app.claim_queued_job(job_id))
                app.run_schema_turn_backfill_job(job_id)
        self.assertEqual(
            calls, [(user_id, app.LIVING_MAP_TURN_MAX_TOKENS)
                    for user_id in users])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM living_map_turn_analyses WHERE "
            "schema_mode=1 AND status='succeeded'")["n"], 3)
        self.assertEqual(self.row(
            "SELECT status FROM jobs WHERE id=?", (job_id,))["status"],
            "succeeded")

    def test_schema_mode_rejects_young_submode(self):
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET submode='adhd' WHERE id=?",
                (self.conv,))
        with self.assertRaises(app.RequestInputError) as caught:
            app.set_schema_mode(self.conv, True)
        self.assertEqual(caught.exception.error_code, "young_therapy_required")


if __name__ == "__main__":
    import unittest
    unittest.main()
