import json
from unittest import mock

from support import HTTPTestCase, app


class SchemaTurnAdversarialAuditTests(HTTPTestCase):
    """Release gates for consent, stale-source, and lifecycle boundaries."""

    stamp = "2026-08-17 20:00"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        with app.db() as connection:
            app.initialize_living_map_autoscan_state(connection, self.conv)

    def completed_turn(self, text="kullanıcı anlatısı"):
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
                ("audit-turn-{:014d}".format(user_id), job_id, self.conv,
                 user_id, assistant_id, self.stamp, self.stamp))
        return user_id, assistant_id

    def failed_turn_job(self, text="yeniden denenecek kaynak"):
        app.set_schema_mode(self.conv, True)
        user_id, assistant_id = self.completed_turn(text)
        provider, model = app._configured_provider_model_snapshot()
        job_id, created, already = app.create_turn_analysis_job(
            self.conv, user_id, provider, model)
        self.assertTrue(created)
        self.assertFalse(already)
        with app.db() as connection:
            connection.execute(
                "UPDATE jobs SET status='failed',error_code='provider_timeout' "
                "WHERE id=?", (job_id,))
            connection.execute(
                "UPDATE living_map_turn_analyses SET status='failed',"
                "error_code='provider_timeout' WHERE job=?", (job_id,))
        return user_id, assistant_id, job_id

    def test_generic_jobs_retry_is_idempotent_for_turn_analysis(self):
        _user, _assistant, job_id = self.failed_turn_job()
        status, body, _ = self.request("POST", "/api/job/retry", {
            "id": job_id,
        })
        self.assertEqual(status, 200, body)
        self.assertTrue(body["queued"])
        self.assertEqual(body["kind"], app.LIVING_MAP_TURN_JOB_KIND)
        self.assertEqual(self.queued_job_id(), job_id)

        status, body, _ = self.request("POST", "/api/job/retry", {
            "job_id": job_id,
        })
        self.assertEqual(status, 200, body)
        self.assertFalse(body["queued"])
        self.assertEqual(body["status"], "queued")
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_generic_jobs_retry_rejects_provider_mismatch(self):
        _user, _assistant, job_id = self.failed_turn_job()
        with app.db() as connection:
            connection.execute(
                "UPDATE jobs SET provider='stale-provider' WHERE id=?",
                (job_id,))
        status, body, _ = self.request("POST", "/api/job/retry", {
            "id": job_id,
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "provider_changed")
        self.assertTrue(app.JOB_QUEUE.empty())

    def test_retried_turn_rechecks_stale_pair_before_provider_call(self):
        _user, assistant, job_id = self.failed_turn_job()
        with app.db() as connection:
            connection.execute(
                "UPDATE messages SET delivery_status='partial' WHERE id=?",
                (assistant,))
        status, body, _ = self.request("POST", "/api/job/retry", {
            "id": job_id,
        })
        self.assertEqual(status, 200, body)
        self.assertTrue(body["queued"])
        self.assertEqual(self.queued_job_id(), job_id)
        self.assertIsNotNone(app.claim_queued_job(job_id))
        with mock.patch.object(app, "ds_complete") as provider:
            app.run_turn_analysis_job(job_id)
        provider.assert_not_called()
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "interrupted")
        self.assertIn(job["error_code"], ("not_completed_turn", "source_changed"))

    @staticmethod
    def schema_response(user_id, statement="modelin ihtiyatlı cümlesi"):
        return json.dumps({
            "insights": [],
            "schema_candidates": [{
                "existing_claim_id": None,
                "schema_id": next(iter(app.SCHEMA_CANDIDATE_CATALOG)),
                "mode_id": next(iter(app.SCHEMA_MODE_CANDIDATE_CATALOG)),
                "statement": statement,
                "trigger": "bekleme", "experience": "kaygı",
                "response": "geri çekilme",
                "short_term_effect": "korunma",
                "long_term_effect": "uzaklık", "need": "güven",
                "context": "bu olay", "counterexample": "",
                "supporting_message_ids": [user_id],
                "counterexample_message_ids": [],
            }],
        }, ensure_ascii=False)

    def test_schema_history_archive_during_provider_is_interrupted(self):
        user_id, _assistant_id = self.completed_turn("geçmiş kaynak")
        app.set_schema_mode(self.conv, True)
        provider_id, model_id = app._configured_provider_model_snapshot()
        job_id, created = app.create_schema_turn_backfill_job(
            self.conv, provider_id, model_id)
        self.assertTrue(created)
        self.assertIsNotNone(app.claim_queued_job(job_id))

        def archive(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE conversations SET archived_at=? WHERE id=?",
                    (self.stamp, self.conv))
            return self.schema_response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=archive):
            app.run_schema_turn_backfill_job(job_id)

        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "interrupted")
        self.assertEqual(job["error_code"], "conversation_closed")
        ledger = self.row(
            "SELECT * FROM living_map_turn_analyses WHERE conv=? "
            "AND user_message=?", (self.conv, user_id))
        self.assertEqual(ledger["status"], "interrupted")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_schema_history_end_during_provider_is_interrupted(self):
        user_id, _assistant_id = self.completed_turn("kapanan kaynak")
        app.set_schema_mode(self.conv, True)
        provider_id, model_id = app._configured_provider_model_snapshot()
        job_id, created = app.create_schema_turn_backfill_job(
            self.conv, provider_id, model_id)
        self.assertTrue(created)
        self.assertIsNotNone(app.claim_queued_job(job_id))

        def end(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE conversations SET ended=1 WHERE id=?",
                    (self.conv,))
            return self.schema_response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=end):
            app.run_schema_turn_backfill_job(job_id)
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "interrupted")
        self.assertEqual(job["error_code"], "conversation_closed")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_global_history_safety_during_provider_is_terminal_interrupted(self):
        user_id, _assistant_id = self.completed_turn("global kaynak")
        provider_id, model_id = app._configured_provider_model_snapshot()
        job_id, created = app.create_living_map_backfill_job(
            provider_id, model_id)
        self.assertTrue(created)
        self.assertIsNotNone(app.claim_queued_job(job_id))

        def hold(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE conversations SET safety_hold=1 WHERE id=?",
                    (self.conv,))
            return json.dumps({"insights": []})

        with mock.patch.object(app, "ds_complete", side_effect=hold):
            app.run_living_map_backfill_job(job_id)

        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "interrupted")
        self.assertEqual(job["error_code"], "safety_hold")
        ledger = self.row(
            "SELECT * FROM living_map_turn_analyses WHERE conv=? "
            "AND user_message=?", (self.conv, user_id))
        self.assertEqual(ledger["status"], "interrupted")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_global_history_archive_during_provider_keeps_explicit_scope(self):
        user_id, _assistant_id = self.completed_turn("arşiv kapsamı")
        provider_id, model_id = app._configured_provider_model_snapshot()
        job_id, created = app.create_living_map_backfill_job(
            provider_id, model_id)
        self.assertTrue(created)
        self.assertIsNotNone(app.claim_queued_job(job_id))

        def archive(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE conversations SET archived_at=? WHERE id=?",
                    (self.stamp, self.conv))
            return json.dumps({"insights": []})

        with mock.patch.object(app, "ds_complete", side_effect=archive):
            app.run_living_map_backfill_job(job_id)

        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "succeeded")
        ledger = self.row(
            "SELECT * FROM living_map_turn_analyses WHERE conv=? "
            "AND user_message=?", (self.conv, user_id))
        self.assertEqual(ledger["status"], "succeeded")
        self.assertEqual(ledger["schema_mode"], 0)

    def test_global_history_delete_during_provider_is_terminal_interrupted(self):
        self.completed_turn("silinecek kaynak")
        provider_id, model_id = app._configured_provider_model_snapshot()
        job_id, created = app.create_living_map_backfill_job(
            provider_id, model_id)
        self.assertTrue(created)
        self.assertIsNotNone(app.claim_queued_job(job_id))

        def erase(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                app.delete_conversation_data(connection, self.conv)
            return json.dumps({"insights": []})

        with mock.patch.object(app, "ds_complete", side_effect=erase):
            app.run_living_map_backfill_job(job_id)
        job = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job["status"], "interrupted")
        self.assertEqual(job["error_code"], "conversation_changed")
        self.assertIsNone(self.row(
            "SELECT id FROM conversations WHERE id=?", (self.conv,)))
        for table in (
                "living_map_turn_analyses", "psych_observations",
                "psych_claim_evidence", "psych_claim_history",
                "psych_claims", "schema_paths", "schema_path_events"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM {}".format(table))["n"], 0)

    def test_explicit_turn_safety_event_during_provider_suppresses_result(self):
        app.set_schema_mode(self.conv, True)
        user_id, _assistant_id = self.completed_turn("sonradan güvenlik")
        job_id, created, already = app.create_turn_analysis_job(
            self.conv, user_id)
        self.assertTrue(created)
        self.assertFalse(already)
        self.assertIsNotNone(app.claim_queued_job(job_id))

        def revoke(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "INSERT INTO safety_events(conv,source_message,kind,"
                    "created) VALUES(?,?,'crisis',?)",
                    (self.conv, user_id, self.stamp))
            return self.schema_response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=revoke):
            app.run_turn_analysis_job(job_id)

        self.assertEqual(self.row(
            "SELECT status FROM jobs WHERE id=?", (job_id,))["status"],
            "interrupted")
        ledger = self.row(
            "SELECT * FROM living_map_turn_analyses WHERE user_message=?",
            (user_id,))
        self.assertEqual(ledger["status"], "interrupted")
        self.assertEqual(ledger["error_code"], "safety_turn")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def generated_candidate(self):
        app.set_schema_mode(self.conv, True)
        user_id, assistant_id = self.completed_turn("aday kaynağı")
        with mock.patch.object(
                app, "ds_complete",
                return_value=self.schema_response(user_id)):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit", raise_errors=True)
        self.assertEqual(result["status"], "succeeded")
        candidate = app.schema_path_payload(self.conv)["candidates"][0]
        return user_id, assistant_id, candidate

    def assert_candidate_redacted(self, candidate):
        self.assertFalse(candidate["approved_for_path"])
        self.assertEqual(candidate["available_decisions"], [])
        self.assertIsNone(candidate["source_turn"])
        self.assertEqual(candidate["source_turns"], [])
        self.assertEqual(candidate["sources"], [])
        self.assertEqual(candidate["direct_user_evidence"], [])
        for field in (
                "trigger", "experience", "response", "short_term_effect",
                "long_term_effect", "need", "counterexample", "context"):
            self.assertEqual(candidate[field], "", field)

    def test_later_safety_source_redacts_public_candidate_and_actions(self):
        user_id, _assistant_id, candidate = self.generated_candidate()
        self.assertTrue(candidate["available_decisions"])
        with app.db() as connection:
            connection.execute(
                "INSERT INTO safety_events(conv,source_message,kind,created) "
                "VALUES(?,?,'crisis',?)",
                (self.conv, user_id, self.stamp))
        self.assert_candidate_redacted(
            app.schema_path_payload(self.conv)["candidates"][0])

    def test_later_incomplete_pair_redacts_public_candidate_and_actions(self):
        _user_id, assistant_id, _candidate = self.generated_candidate()
        with app.db() as connection:
            connection.execute(
                "UPDATE messages SET delivery_status='partial' WHERE id=?",
                (assistant_id,))
        self.assert_candidate_redacted(
            app.schema_path_payload(self.conv)["candidates"][0])

    def test_private_candidate_redacts_public_derivation_and_actions(self):
        _user_id, _assistant_id, candidate = self.generated_candidate()
        status, body, _ = self.request("POST", "/api/schema-path", {
            "action": "review_candidate", "conv_id": self.conv,
            "claim_id": candidate["id"], "decision": "private",
            "request_id": "audit-private-candidate-0001",
        })
        self.assertEqual(status, 200, body)
        private_candidate = next(
            item for item in body["candidates"]
            if item["id"] == candidate["id"])
        self.assert_candidate_redacted(private_candidate)

    def test_assistant_pair_replacement_during_provider_is_source_changed(self):
        app.set_schema_mode(self.conv, True)
        user_id, _assistant_id = self.completed_turn("kaynak çifti")

        def replace(_messages, **_kwargs):
            with app.db() as connection:
                replacement = connection.execute(
                    "INSERT INTO messages(conv,role,content,created,"
                    "delivery_status) VALUES(?,'assistant','başka yanıt',?,"
                    "'completed')", (self.conv, self.stamp)).lastrowid
                connection.execute(
                    "UPDATE chat_requests SET assistant_message=? "
                    "WHERE conv=? AND user_message=?",
                    (replacement, self.conv, user_id))
            return self.schema_response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=replace):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit")
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["error_code"], "source_changed")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_partial_assistant_during_provider_suppresses_result(self):
        app.set_schema_mode(self.conv, True)
        user_id, assistant_id = self.completed_turn("yarım kalacak çift")

        def partial(_messages, **_kwargs):
            with app.db() as connection:
                connection.execute(
                    "UPDATE messages SET delivery_status='partial' WHERE id=?",
                    (assistant_id,))
            return self.schema_response(user_id)

        with mock.patch.object(app, "ds_complete", side_effect=partial):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit")
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["error_code"], "not_completed_turn")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims")["n"], 0)

    def test_private_sensitive_claims_never_enter_prompt_and_wording_is_owned(self):
        old_user, _ = self.completed_turn("eski kanıt")
        app.set_schema_mode(self.conv, True)
        with app.db() as connection:
            observation = connection.execute(
                "INSERT INTO psych_observations(conv,source_message,"
                "therapist,content,created) VALUES(?,?,'young','kanıt',?)",
                (self.conv, old_user, self.stamp)).lastrowid
            for scope, sensitive, secret in (
                    ("private", 0, "PRIVATE-SECRET-DO-NOT-SEND"),
                    ("therapist", 1, "SENSITIVE-SECRET-DO-NOT-SEND")):
                claim = connection.execute(
                    "INSERT INTO psych_claims(public_id,source_conv,"
                    "therapist,claim_type,title,statement,status,scope,"
                    "sensitive,created,updated) VALUES(?,?, 'young','pattern',"
                    "?,?, 'confirmed',?,?,?,?)",
                    (secret.lower(), self.conv, secret, secret, scope,
                     sensitive, self.stamp, self.stamp)).lastrowid
                evidence = connection.execute(
                    "INSERT INTO psych_claim_evidence(claim,observation,"
                    "relation,review_status,created) VALUES(?,?,'supports',"
                    "'accepted',?)", (claim, observation,
                                      self.stamp)).lastrowid
                connection.execute(
                    "UPDATE psych_claims SET reviewed_evidence_id=?,"
                    "reviewed_at=? WHERE id=?",
                    (evidence, self.stamp, claim))
        user_id, _ = self.completed_turn("yeni kaynak")
        captured = {}

        def complete(messages, **_kwargs):
            captured["prompt"] = json.dumps(messages, ensure_ascii=False)
            return self.schema_response(
                user_id, statement="KESİN TANI: değişmez bir kişilik özelliği")

        with mock.patch.object(app, "ds_complete", side_effect=complete):
            result = app.generate_living_map_candidates(
                self.conv, single_turn_user_message_id=user_id,
                analysis_source="explicit", raise_errors=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertNotIn("PRIVATE-SECRET-DO-NOT-SEND", captured["prompt"])
        self.assertNotIn("SENSITIVE-SECRET-DO-NOT-SEND", captured["prompt"])
        candidate = self.row(
            "SELECT statement,title,schema_key,mode_key FROM psych_claims "
            "WHERE source_conv=? AND claim_type='schema_hypothesis'",
            (self.conv,))
        self.assertNotIn("KESİN TANI", candidate["statement"])
        self.assertIn("tanı değildir", candidate["statement"])
        self.assertIn(candidate["schema_key"], app.SCHEMA_CANDIDATE_CATALOG)
        self.assertIn(candidate["mode_key"], app.SCHEMA_MODE_CANDIDATE_CATALOG)


if __name__ == "__main__":
    import unittest
    unittest.main()
