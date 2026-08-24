import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app
import sync_engine as sync


class _ProviderStream:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SchemaPathV4Tests(HTTPTestCase):
    """Durable chat-inline v4 contract and adversarial invariants."""

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        self._serial = 0

    def request_id(self, prefix="action"):
        self._serial += 1
        return "schema-v4-{}-{:06d}".format(prefix, self._serial)

    def completed_pair(self, user_text, assistant_text="Kısa yanıt."):
        self._serial += 1
        stamp = "2026-08-22 10:{:02d}:{:02d}".format(
            (self._serial // 60) % 60, self._serial % 60)
        request_id = "schema-v4-pair-{:010d}".format(self._serial)
        pair_public_id = app._chat_turn_pair_public_id(request_id)
        with app.db() as connection:
            user_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "turn_pair_public_id,delivery_status) "
                "VALUES(?, 'user', ?, ?, ?, 'completed')",
                (self.conv, user_text, stamp, pair_public_id)).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "turn_pair_public_id,delivery_status) "
                "VALUES(?, 'assistant', ?, ?, ?, 'completed')",
                (self.conv, assistant_text, stamp,
                 pair_public_id)).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'succeeded',?,?)",
                (self.conv, stamp, stamp)).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,provider,model,created,updated) "
                "VALUES(?,?,?,?,?,'completed',?,?,?,?)",
                (request_id, job_id, self.conv, user_id, assistant_id,
                 app.selected_provider(),
                 app._configured_model_snapshot(app.selected_provider()),
                 stamp, stamp))
            user = connection.execute(
                "SELECT * FROM messages WHERE id=?", (user_id,)).fetchone()
            assistant = connection.execute(
                "SELECT * FROM messages WHERE id=?",
                (assistant_id,)).fetchone()
        return {
            "user_message_id": user_id,
            "user_message_public_id": user["public_id"],
            "assistant_message_id": assistant_id,
            "assistant_message_public_id": assistant["public_id"],
            "user_content": user_text,
            "assistant_content": assistant_text,
        }

    def completed_pairs(self, count=3):
        return [self.completed_pair(
            "Doğrudan kullanıcı kaynağı {}".format(index))
            for index in range(count)]

    def approved_candidate(self, pair):
        stamp = app.now()
        with app.db() as connection:
            observation_id = connection.execute(
                "INSERT INTO psych_observations(conv,source_message,"
                "therapist,dimension,content,source_created,created) "
                "VALUES(?,?,'young','user_report',?,?,?)",
                (self.conv, pair["user_message_id"], pair["user_content"],
                 stamp, stamp)).lastrowid
            claim_id = connection.execute(
                "INSERT INTO psych_claims(public_id,source_conv,therapist,"
                "lens,claim_type,title,statement,trigger_text,experience_text,"
                "response_text,short_term_effect,long_term_effect,need_text,"
                "counterexample_text,status,scope,sensitive,first_seen,"
                "last_seen,schema_key,mode_key,source_assistant_message,"
                "created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?)",
                ("schema-v4-claim-{:08d}".format(observation_id), self.conv,
                 "young", "schema", "schema_hypothesis",
                 "Çalışılabilecek bir örüntü",
                 "Bu anlatıda terk edilme beklentisine benzeyen, birlikte "
                 "sınanacak bir çalışma olasılığı var.",
                 "Mesaj gecikince", "kaygı", "geri çekilme", "kısa güvence",
                 "ilişkide uzaklaşma", "güven", "Bazen bekleyebiliyorum.",
                 "confirmed", "therapist", 0, stamp, stamp,
                 next(iter(app.SCHEMA_CANDIDATE_CATALOG)), "",
                 pair["assistant_message_id"], stamp, stamp)).lastrowid
            evidence_id = connection.execute(
                "INSERT INTO psych_claim_evidence(claim,observation,relation,"
                "review_status,created) VALUES(?,?,'supports','accepted',?)",
                (claim_id, observation_id, stamp)).lastrowid
            connection.execute(
                "UPDATE psych_claims SET reviewed_at=?,"
                "reviewed_evidence_id=? WHERE id=?",
                (stamp, evidence_id, claim_id))
        return claim_id

    def post(self, payload):
        status, body, _headers = self.request(
            "POST", "/api/schema-path", payload)
        return status, body

    def dashboard(self):
        status, body, _headers = self.request(
            "GET", "/api/schema-path?conv_id={}".format(self.conv))
        self.assertEqual(status, 200, body)
        return body

    def post_card_action(self, card, action_name, request_prefix="card"):
        action = next(item for item in card["actions"]
                      if item["action"] == action_name)
        payload = {
            "action": action_name,
            "conv_id": self.conv,
            "request_id": self.request_id(request_prefix),
            **action.get("payload", {}),
        }
        return self.post(payload)

    def start_v5_prompt_pending(self, request_prefix="v5-first-prompt"):
        pairs = self.completed_pairs(3)
        self.approved_candidate(pairs[0])
        card = self.dashboard()["next_card"]
        self.assertEqual(card["kind"], "candidate_prompt")
        status, state = self.post_card_action(
            card, "accept_candidate_chat", request_prefix)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["active_path"]["flow_version"], 5)
        request = self.row(
            "SELECT * FROM chat_requests WHERE conv=? AND "
            "schema_prompt_protocol=?",
            (self.conv, app.SCHEMA_PATH_V5_PROTOCOL))
        self.assertIsNotNone(request)
        return state, request, pairs

    def run_v5_prompt(self, request_id, raw_output, before_done=None):
        def delta(_event, chunk, _provider):
            if chunk == "DONE":
                if before_done:
                    before_done()
                return "done", ""
            return "text", chunk

        events = []
        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False,
                                         "model": "test"})) as provider, \
                mock.patch.object(
                    app, "open_provider_url", return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", return_value=iter([
                        ("message", raw_output), ("message", "DONE")])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta), \
                mock.patch.object(app, "schedule_living_map_autoscan"), \
                mock.patch.object(app, "maybe_create_adhd_suggestion"), \
                mock.patch.object(app.threading, "Thread"):
            result = app.run_chat_request(
                request_id, emit=events.append, automatic_retries=False,
                generation=app.data_generation())
        return result, events, provider

    def start_v5_ready(self, request_prefix="v5-ready"):
        state, request, pairs = self.start_v5_prompt_pending(request_prefix)
        raw = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "Bunu en son yaşadığın somut bir anı kısaca anlatır mısın?"),
        }, ensure_ascii=False)
        completed, _events, _provider = self.run_v5_prompt(
            request["request_id"], raw)
        self.assertEqual(completed["status"], "completed")
        return self.dashboard(), pairs

    def prepare_v5_sync_receiver(self, stage="explore",
                                 step="variable_explore", method_id=""):
        """Drop local-only ledgers while retaining authenticated sync rows."""
        state, _pairs = self.start_v5_ready(
            "v5-sync-receiver-{}".format(step))
        path_id = state["active_path"]["id"]
        stamp = app.now()
        with app.db() as connection:
            sync._sync_tables(connection)
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            current = connection.execute(
                "SELECT * FROM schema_path_steps WHERE path=? AND "
                "status='active' ORDER BY id DESC LIMIT 1", (path_id,)
            ).fetchone()
            accepted = connection.execute(
                "SELECT * FROM schema_candidate_queue WHERE path=? AND "
                "status='accepted' ORDER BY id DESC LIMIT 1", (path_id,)
            ).fetchone()
            source_ids = {
                int(current["source_user_message"]),
                int(current["source_assistant_message"]),
                int(accepted["source_user_message"]),
                int(accepted["source_assistant_message"]),
            }
            source_messages = connection.execute(
                "SELECT * FROM messages WHERE id IN ({}) ORDER BY id".format(
                    ",".join("?" for _ in source_ids)),
                tuple(sorted(source_ids))).fetchall()
            for message in source_messages:
                connection.execute(
                    "INSERT INTO sync_records(record_type,local_id,public_id,"
                    "revision,origin_device_id,parent_origin_device_id,"
                    "parent_revision,updated_at,deleted_at,payload_hash) "
                    "VALUES('message',?,?,1,'fixture-peer',NULL,NULL,?,NULL,?) "
                    "ON CONFLICT(record_type,public_id) DO UPDATE SET "
                    "local_id=excluded.local_id,revision=excluded.revision,"
                    "origin_device_id=excluded.origin_device_id,"
                    "updated_at=excluded.updated_at,deleted_at=NULL,"
                    "payload_hash=excluded.payload_hash",
                    (message["id"], message["public_id"], stamp,
                     "fixture-{}".format(message["public_id"])))
            # These tables are intentionally receiver-local.  Messages,
            # shared path/candidate identity and its exact shared step remain.
            connection.execute(
                "DELETE FROM schema_v5_technique_turns WHERE path=?",
                (path_id,))
            connection.execute(
                "DELETE FROM schema_v5_technique_sessions WHERE path=?",
                (path_id,))
            for table in (
                    "schema_v5_integration_answers", "schema_origin_answers",
                    "schema_variable_trials", "schema_path_method_choices",
                    "schema_path_checkpoints"):
                connection.execute(
                    "DELETE FROM {} WHERE path=?".format(table), (path_id,))
            connection.execute(
                "DELETE FROM chat_requests WHERE conv=?", (self.conv,))
            connection.execute(
                "DELETE FROM schema_path_steps WHERE path=?", (path_id,))
            phase = {
                "explore": "explore", "origin": "depth",
                "work": "depth", "integrate": "integrate",
            }[stage]
            connection.execute(
                "UPDATE schema_paths SET phase=?,status='active',stage=?,"
                "step=?,pause_reason='',resume_required=0,method_node_id=?,"
                "technique_run=NULL,revision=41,updated=? WHERE id=?",
                (phase, stage, step, method_id, stamp, path_id))
            step_public_id = app._schema_natural_public_id(
                "receiver-step", path["public_id"], step)
            connection.execute(
                "INSERT INTO schema_path_steps(public_id,path,conv,stage,"
                "step,status,revision,source_user_message,"
                "source_assistant_message,payload_json,created,updated) "
                "VALUES(?,?,?,?,?,'active',1,?,?, '{}',?,?)",
                (step_public_id, path_id, self.conv, stage, step,
                 current["source_user_message"],
                 current["source_assistant_message"], stamp, stamp))
            source_user = connection.execute(
                "SELECT * FROM messages WHERE id=?",
                (current["source_user_message"],)).fetchone()
            source_assistant = connection.execute(
                "SELECT * FROM messages WHERE id=?",
                (current["source_assistant_message"],)).fetchone()
            message_snapshot = [tuple(row) for row in connection.execute(
                "SELECT id,public_id,role,content,turn_pair_public_id,"
                "delivery_status FROM messages WHERE conv=? ORDER BY id",
                (self.conv,)).fetchall()]
            counts = {
                "messages": connection.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                    (self.conv,)).fetchone()["n"],
                "jobs": connection.execute(
                    "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
                    (self.conv,)).fetchone()["n"],
                "requests": connection.execute(
                    "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
                    (self.conv,)).fetchone()["n"],
            }
        return {
            "path_id": path_id,
            "source_user_id": int(source_user["id"]),
            "source_user_public_id": str(source_user["public_id"]),
            "source_assistant_id": int(source_assistant["id"]),
            "source_assistant_public_id": str(source_assistant["public_id"]),
            "message_snapshot": message_snapshot,
            "counts": counts,
        }

    def complete_v5_turn(self, user_text, envelope, request_prefix="v5-turn"):
        envelope = dict(envelope)
        if envelope.get("intent_id") == "variable_counterfactual":
            delta = app.SCHEMA_PATH_V5_COUNTERFACTUAL_DELTAS[
                envelope["category"]]
            envelope.update({
                "changed_attribute": delta["changed_attribute"],
                "changed_value": delta["changed_value"],
                "assistant_text": "Eğer {}, bu an nasıl değişirdi?".format(
                    delta["delta_phrase"]),
            })
        state = self.dashboard()
        binding = dict(state["next_card"]["chat_binding"])
        request_id = self.request_id(request_prefix)
        request, created = app.begin_chat_request(
            self.conv, user_text, request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        result, events, provider = self.run_v5_prompt(
            request_id, json.dumps(envelope, ensure_ascii=False))
        return result, self.dashboard(), request, events, provider

    def v5_origin_ready(self, request_prefix="v5-origin-ready"):
        self.start_v5_ready(request_prefix)
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı seni kesmek yerine "
                    "dinlemek olsaydı, bu an nasıl değişirdi?"),
            }, request_prefix + "-scenario")
        result, state, _request, _events, _provider = self.complete_v5_turn(
            "Daha az gerilir ve kendimi daha güvende hissederdim.", {
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için imgeleme ile yeniden senaryolamayı "
                    "kullanacağım; o zamanki yaşına dair ne hatırlıyorsun?"),
            }, request_prefix + "-effect")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["step"], "origin_sequence")
        return state

    def v5_need_ready(self, request_prefix="v5-need-ready"):
        self.v5_origin_ready(request_prefix)
        turns = (
            ("8 yaşındaydım", {
                "intent_id": "origin_place",
                "assistant_text": "O an nerede olduğunu hatırlıyor musun?",
            }),
            ("Okulun koridorundaydım.", {
                "intent_id": "origin_event_response",
                "assistant_text": "Orada tam olarak ne oldu?",
            }),
            ("Arkadaşım herkesin içinde sözümü kesti.", {
                "intent_id": "origin_event_response",
                "assistant_text": "O anda nasıl karşılık verdin?",
            }),
            ("Sessiz kaldım ve uzaklaştım.", {
                "intent_id": "origin_unmet_need",
                "assistant_text": "O anda en çok neye ihtiyaç duyardın?",
            }),
        )
        state = None
        for index, (user_text, envelope) in enumerate(turns):
            result, state, _request, _events, _provider = \
                self.complete_v5_turn(
                    user_text, envelope,
                    request_prefix + "-{}".format(index))
            self.assertEqual(result["status"], "completed")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "need")
        return state

    def v5_chair_need_ready(self, request_prefix="v5-chair-need-ready"):
        state, _pairs = self.start_v5_ready(request_prefix)
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET focus_mode_key='punitive_parent' "
                "WHERE id=?", (state["active_path"]["id"],))
        self.complete_v5_turn(
            "Eleştirildiğim anda sesimi çıkaramayıp uzaklaşıyorum.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "Eleştirildiğim anda",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı eleştirmek yerine "
                    "dinlemek olsaydı, deneyimin nasıl değişirdi?"),
            }, request_prefix + "-scenario")
        result, state, _request, _events, _provider = self.complete_v5_turn(
            "Daha az zorlanır ve daha güvende hissederdim.", {
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için sandalye diyaloğunu kullanacağım; o "
                    "zamanki yaşına dair ne hatırlıyorsun?"),
            }, request_prefix + "-effect")
        self.assertEqual(result["status"], "completed")
        turns = (
            ("9 yaşındaydım", {
                "intent_id": "origin_place",
                "assistant_text": "O an nerede olduğunu hatırlıyor musun?",
            }),
            ("Evde, mutfaktaydım.", {
                "intent_id": "origin_event_response",
                "assistant_text": "Orada tam olarak ne oldu?",
            }),
            ("Sert biçimde eleştirildim.", {
                "intent_id": "origin_event_response",
                "assistant_text": "O anda nasıl karşılık verdin?",
            }),
            ("Sessiz kalıp odama gittim.", {
                "intent_id": "origin_unmet_need",
                "assistant_text": "O anda en çok neye ihtiyaç duyardın?",
            }),
        )
        for index, (user_text, envelope) in enumerate(turns):
            result, state, _request, _events, _provider = \
                self.complete_v5_turn(
                    user_text, envelope,
                    request_prefix + "-origin-{}".format(index))
            self.assertEqual(result["status"], "completed")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "need")
        return state

    def v5_healthy_voice_ready(self, request_prefix="v5-healthy-ready"):
        self.v5_need_ready(request_prefix)
        turns = (
            ("Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }),
            ("Biraz uzaktan bakmak istiyorum.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu mesafeden sahnede ilk neyi fark ediyorsun?"),
            }),
            ("Kapının yanında tek başıma durduğumu görüyorum.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Sağlıklı Yetişkinin hangi koruma ya da sınırı seçerdi?"),
            }),
            ("Yanıma gelip beni oradan çıkarırdı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu koruma eklendiğinde şimdi ne biraz farklı geliyor?"),
            }),
            ("Artık yalnız olmadığım anlamına geliyor.", {
                "intent_id": "grounding",
                "assistant_text": (
                    "Şimdi bulunduğun odada çevrenden neyi fark ediyorsun?"),
            }),
            ("Şimdi odadayım ve pencereyi görüyorum.", {
                "intent_id": "healthy_adult_voice",
                "assistant_text": (
                    "Bugünkü Sağlıklı Yetişkin tarafın o zamanki sana ne "
                    "söylemek ister?"),
            }),
        )
        state = None
        for index, (user_text, envelope) in enumerate(turns):
            result, state, _request, _events, _provider = \
                self.complete_v5_turn(
                    user_text, envelope,
                    request_prefix + "-work-{}".format(index))
            self.assertEqual(result["status"], "completed")
        self.assertEqual((state["stage"], state["step"]),
                         ("integrate", "healthy_adult_voice"))
        return state

    def force_v4_legacy_prompt(self, state, step="current_impact",
                               prompt_key="burden"):
        path_id = state["active_path"]["id"]
        stage = "listen" if step in {
            "current_impact", "variable_check", "focus_confirm"} else \
            "depth"
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET flow_version=4,stage=?,step=?,"
                "phase='explore',status='active',pause_reason='',"
                "resume_required=0 WHERE id=?", (stage, step, path_id))
            connection.execute(
                "UPDATE schema_path_checkpoints SET stage=?,step=?,"
                "prompt_key=? WHERE path=? AND status='active'",
                (stage, step, prompt_key, path_id))
        return path_id

    def _enable_internal_v4_compat_projection(self):
        """Expose retired v4 reducers only inside their legacy test fixture.

        Production dashboards always retire flow-v4 continuations into the
        silent v5 boundary.  The historical reducer tests still provide
        useful safety/idempotency coverage, so they opt into the unreachable
        pre-retirement projection with mocks local to this TestCase.  No
        server flag or runtime escape hatch is introduced.
        """
        if getattr(self, "_internal_v4_projection_enabled", False):
            return
        original_next_card = app.schema_v4_next_card
        original_require_path = app.schema_v4_require_path
        original_local_control = app._schema_chat_apply_local_control
        original_current_candidate = app.schema_current_candidate_row

        def legacy_next_card(connection, conv, path):
            projected_path = dict(path) if path else path
            if (projected_path and
                    int(projected_path.get("flow_version") or 0) == 4):
                # The old interactive branch remains after the explicit v4
                # retirement return and is reachable for versions >5.  A
                # copied row selects that branch without mutating the DB.
                projected_path["flow_version"] = 6
            return original_next_card(connection, conv, projected_path)

        def legacy_require_path(*args, **kwargs):
            path = original_require_path(*args, **kwargs)
            projected_path = dict(path)
            if int(projected_path.get("flow_version") or 0) == 4:
                projected_path["flow_version"] = 6
            return projected_path

        def legacy_local_control(
                connection, conv, path, command, request_id):
            if (int(path["flow_version"] or 0) == 4
                    and command == "backtrack_step"):
                # The public v5 contract retires v4 back commands.  Exercise
                # the old reducer directly with an already authoritative pair
                # so its append-only invalidation logic remains covered.
                pair = dict(app.schema_latest_safe_source_pair(
                    connection, conv["id"]))
                pair["user_content"] = "Geri dön"
                result = app._schema_v4_apply_chat_only_pair(
                    connection, conv, path, pair, request_id)
                return app.schema_v4_checkpoint_result(
                    connection, path, result,
                    backtracked=result.get("action") == "backtrack_step")
            return original_local_control(
                connection, conv, path, command, request_id)

        def legacy_current_candidate(connection, path):
            if (path and int(path["flow_version"] or 0) in (4, 6)
                    and path["step"] in ("candidate_review", "listen")):
                offered = connection.execute(
                    "SELECT * FROM schema_candidate_queue WHERE path=? "
                    "AND status='offered' ORDER BY sort_order,id LIMIT 1",
                    (path["id"],)).fetchone()
                if offered:
                    return offered
            return original_current_candidate(connection, path)

        retirement = mock.patch.object(
            app, "schema_v5_retire_legacy_interactive_path",
            side_effect=lambda _connection, _conv, path: (path, False))
        projection = mock.patch.object(
            app, "schema_v4_next_card", side_effect=legacy_next_card)
        authority = mock.patch.object(
            app, "schema_v4_require_path", side_effect=legacy_require_path)
        controls = mock.patch.object(
            app, "_schema_chat_apply_local_control",
            side_effect=legacy_local_control)
        candidates = mock.patch.object(
            app, "schema_current_candidate_row",
            side_effect=legacy_current_candidate)
        retirement.start()
        projection.start()
        authority.start()
        controls.start()
        candidates.start()
        self.addCleanup(candidates.stop)
        self.addCleanup(controls.stop)
        self.addCleanup(authority.stop)
        self.addCleanup(projection.stop)
        self.addCleanup(retirement.stop)
        self._internal_v4_projection_enabled = True

    def _convert_v5_start_to_internal_v4(self, state):
        """Turn a freshly accepted v5 fixture into an unreachable v4 seed."""
        self._enable_internal_v4_compat_projection()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            candidate = connection.execute(
                "SELECT * FROM schema_candidate_queue WHERE path=? AND "
                "status IN ('accepted','selected') ORDER BY id DESC LIMIT 1",
                (path_id,)).fetchone()
            pair = app.schema_exact_source_pair(
                connection, self.conv, candidate["source_user_message"],
                candidate["source_assistant_message"])
            requests = connection.execute(
                "SELECT request_id,job,user_message FROM chat_requests "
                "WHERE schema_path=? AND schema_prompt_protocol=?",
                (path_id, app.SCHEMA_PATH_V5_PROTOCOL)).fetchall()
            for request in requests:
                connection.execute(
                    "DELETE FROM chat_requests WHERE request_id=?",
                    (request["request_id"],))
                connection.execute(
                    "DELETE FROM jobs WHERE id=?", (request["job"],))
                connection.execute(
                    "DELETE FROM messages WHERE id=? AND "
                    "delivery_status='saved'", (request["user_message"],))
            for table in (
                    "schema_v5_technique_turns",
                    "schema_v5_technique_sessions",
                    "schema_v5_integration_answers",
                    "schema_origin_answers",
                    "schema_variable_trials",
                    "schema_path_method_choices",
                    "schema_path_checkpoints",
                    "schema_path_steps"):
                connection.execute(
                    "DELETE FROM {} WHERE path=?".format(table), (path_id,))
            connection.execute(
                "UPDATE schema_paths SET flow_version=4,stage='listen',"
                "step='current_impact',phase='explore',status='active',"
                "pause_reason='',resume_required=0,method_node_id='',"
                "technique_run=NULL,revision=0 WHERE id=?", (path_id,))
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            app.schema_v4_set_state(
                connection, path, "listen", "current_impact", pair, {
                    "chat": {"prompt": "burden", "values": {},
                             "sources": {}},
                })
        return self.dashboard()

    def force_v4_legacy_run(self, state, method_id, step):
        """Seed only the identities needed for an already-authorised run."""
        path_id = state["active_path"]["id"]
        stamp = app.now()
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            source = connection.execute(
                "SELECT source_user_message,source_assistant_message FROM "
                "schema_path_steps WHERE path=? AND status='active'",
                (path_id,)).fetchone()
            run_id = connection.execute(
                "INSERT INTO technique_runs(conv,therapist,method_key,"
                "method_name,phase,status,state_json,created,updated) "
                "VALUES(?,'young',?,?, 'work','active','{}',?,?)",
                (self.conv, method_id,
                 app.SCHEMA_PATH_V4_METHOD_LABELS[method_id], stamp,
                 stamp)).lastrowid
            link_public = app._schema_natural_public_id(
                "technique", path["public_id"], 1)
            link_id = connection.execute(
                "INSERT INTO schema_path_techniques(public_id,path,conv,"
                "step,technique_run,method_node_id,status,seq,created,"
                "updated) VALUES(?,?,?,?,?,?,'active',1,?,?)",
                (link_public, path_id, self.conv, step, run_id, method_id,
                 stamp, stamp)).lastrowid
            connection.execute(
                "UPDATE schema_path_steps SET status='completed',"
                "completed_at=?,updated=? WHERE path=? AND status='active'",
                (stamp, stamp, path_id))
            connection.execute(
                "INSERT INTO schema_path_steps(public_id,path,conv,stage,"
                "step,status,revision,source_user_message,"
                "source_assistant_message,payload_json,created,updated) "
                "VALUES(?,?,?,'depth',?,'active',1,?,?,?, ?,?)",
                (app._schema_natural_public_id("step", path["public_id"],
                                               step),
                 path_id, self.conv, step, source["source_user_message"],
                 source["source_assistant_message"], json.dumps({
                     "technique_link_id": link_id,
                     "chat": {"prompt": "technique_turn", "values": {},
                              "sources": {}}}, sort_keys=True), stamp,
                 stamp))
            connection.execute(
                "UPDATE schema_path_checkpoints SET stage='depth',step=?,"
                "prompt_key='technique_turn',method_node_id=? WHERE path=? "
                "AND status='active'",
                (step, method_id, path_id))
            connection.execute(
                "UPDATE schema_paths SET flow_version=4,stage='depth',"
                "step=?,phase='work',status='active',pause_reason='',"
                "resume_required=0,method_node_id=?,technique_run=? "
                "WHERE id=?", (step, method_id, run_id, path_id))
        return path_id, run_id, link_id

    def force_v4_legacy_integration(self, state, step):
        path_id = state["active_path"]["id"]
        stamp = app.now()
        method_id = app.IMAGERY_METHOD_NODE_ID
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            source = connection.execute(
                "SELECT source_user_message,source_assistant_message FROM "
                "schema_path_steps WHERE path=? AND status='active'",
                (path_id,)).fetchone()
            connection.execute(
                "UPDATE schema_path_steps SET status='completed',"
                "completed_at=?,updated=? WHERE path=? AND status='active'",
                (stamp, stamp, path_id))
            connection.execute(
                "INSERT INTO schema_path_steps(public_id,path,conv,stage,"
                "step,status,revision,source_user_message,"
                "source_assistant_message,payload_json,created,updated) "
                "VALUES(?,?,?,'integrate',?,'active',1,?,?, '{}',?,?)",
                (app._schema_natural_public_id("step", path["public_id"],
                                               step),
                 path_id, self.conv, step, source["source_user_message"],
                 source["source_assistant_message"], stamp, stamp))
            connection.execute(
                "UPDATE schema_path_checkpoints SET stage='integrate',"
                "step=?,prompt_key=? ,method_node_id=? WHERE path=? AND "
                "status='active'",
                (step, {
                    "healthy_adult_voice": "voice",
                    "age_ladder": "age_label",
                    "environment_rescript": "before",
                    "present_transfer": "trigger",
                    "optional_practice": "choice",
                    "followup": "review",
                 }[step], method_id, path_id))
            connection.execute(
                "UPDATE schema_paths SET flow_version=4,stage='integrate',"
                "step=?,phase='practice',status='active',pause_reason='',"
                "resume_required=0,method_node_id=?,technique_run=NULL "
                "WHERE id=?", (step, method_id, path_id))
            healthy_public = app._schema_natural_public_id(
                "healthy", path["public_id"], "legacy")
            connection.execute(
                "INSERT INTO healthy_adult_marks(public_id,conv,path,source,"
                "evidence,source_message,source_assistant_message,status,"
                "created) VALUES(?,?,?,'user','Koruyan söz',?,?, 'active',?)",
                (healthy_public, self.conv, path_id,
                 source["source_user_message"],
                 source["source_assistant_message"], stamp))
            growth_public = app._schema_natural_public_id(
                "growth", path["public_id"], 1)
            connection.execute(
                "INSERT INTO schema_growth(public_id,path,conv,"
                "source_user_message,source_assistant_message,mode_key,"
                "stage_label,now_response,status,environment_status,seq,"
                "created,updated) VALUES(?,?,?,?,?,?,'bugün',"
                "'Eski güvenli yaş izi','active','none',1,?,?)",
                (growth_public, path_id, self.conv,
                 source["source_user_message"],
                 source["source_assistant_message"],
                 str(path["focus_mode_key"] or ""), stamp, stamp))
        return path_id, healthy_public, growth_public

    def start_chat_only_path(self, candidate_pair_index=0):
        pairs = self.completed_pairs(3)
        self.approved_candidate(pairs[candidate_pair_index])
        state = self.dashboard()
        card = state["next_card"]
        self.assertEqual(card["kind"], "candidate_prompt")
        status, state = self.post_card_action(
            card, "accept_candidate_chat", "candidate-yes")
        self.assertEqual(status, 200, state)
        state = self._convert_v5_start_to_internal_v4(state)
        self.assertEqual(state["step"], "current_impact")
        return state, pairs

    def complete_chat_only_turn(
            self, user_text,
            assistant_text="Kısa bir yansıtma. Kontrollü sonraki soru."):
        return self.complete_bound_turn(
            user_text, None, assistant_text=assistant_text)

    def method_confirm_chat_only_path(self):
        state, pairs = self.start_chat_only_path()
        for text in (
                "7",
                "Gün içinde ilişkiden geri çekilmeme yol açıyor.",
                "Şimdi",
                "Karşımdakinin sakin kalması",
                "Aynı konu sakin biçimde konuşuluyor.",
                "4", "Kısmen", "Evet"):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(text)
            self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "method_confirm")
        return state, pairs

    def focus_chat_only_path(self):
        state, pairs = self.method_confirm_chat_only_path()
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Çalışalım")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "origin_or_unknown")
        return state, pairs

    def start_v4(self):
        pairs = self.completed_pairs(3)
        claim_id = self.approved_candidate(pairs[0])
        candidate = self.dashboard()["next_card"]
        self.assertEqual(candidate["kind"], "candidate_prompt")
        status, body = self.post_card_action(
            candidate, "accept_candidate_chat", "start-v4-chat-yes")
        self.assertEqual(status, 200, body)
        body = self._convert_v5_start_to_internal_v4(body)
        self.assertEqual(body["active_path"]["flow_version"], 4)
        self.assertEqual(body["step"], "current_impact")
        return body, pairs, claim_id

    def mutate(self, action, **values):
        state = self.dashboard()
        path = state["active_path"]
        payload = {
            "action": action, "conv_id": self.conv,
            "path_id": path["id"],
            "expected_revision": path["revision"],
            "request_id": self.request_id(action),
        }
        payload.update(values)
        return self.post(payload)

    def focus_path(self):
        state, pairs, claim_id = self.start_v4()
        candidate = state["active_path"]["current_candidate"]
        cref = {
            "candidate_queue_id": candidate["id"],
            "candidate_queue_public_id": candidate["public_id"],
        }
        status, body = self.mutate(
            "rate_current_situation", **cref, burden=7,
            impact="Gün içinde ilişkiden geri çekilmeme yol açıyor.",
            priority="now")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["step"], "variable_check")
        self.assertEqual(body["next_card"]["kind"], "chat_prompt")
        self.assertEqual(body["next_card"]["fields"], [])
        status, body = self.mutate(
            "record_variable_check", **cref, baseline_burden=7,
            variable="Karşımdakinin sakin kalması",
            changed_scenario="Aynı konu sakin biçimde konuşuluyor.",
            changed_burden=4, fit="partial")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["step"], "focus_confirm")
        status, body = self.mutate(
            "confirm_focus", **cref, confirmed=True)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["step"], "method_confirm")
        result, body, _user, _assistant = self.complete_bound_turn(
            "Çalışalım", None)
        self.assertTrue(result["applied"], result)
        self.assertEqual(body["step"], "origin_or_unknown")
        return body, pairs, claim_id

    def complete_bound_turn(self, user_text, step_data,
                            assistant_text="Seni kısa ve güvenli biçimde duyuyorum."):
        state = self.dashboard()
        path = state["active_path"]
        # The public request is always the hidden no-form binding.  Legacy
        # structured reducer fixtures are injected only after this validation
        # so back-compat coverage cannot weaken the chat-only API contract.
        binding = dict(state["next_card"]["chat_binding"])
        link = path.get("active_technique_link")
        if link:
            binding.update({
                "technique_link_id": link["id"],
                "technique_link_public_id": link["public_id"],
                "expected_technique_revision": link["technique_revision"],
            })
        request_id = self.request_id("bound")
        request_row, created = app.begin_chat_request(
            self.conv, user_text, request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        if request_row["status"] == "completed":
            result = json.loads(
                request_row["schema_binding_result_json"] or "null")
            return (result, self.dashboard(),
                    request_row["user_message"],
                    request_row["assistant_message"])
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                if step_data is not None:
                    legacy_binding = dict(binding)
                    legacy_binding["step_data"] = step_data
                    connection.execute(
                        "UPDATE chat_requests SET schema_binding_json=? "
                        "WHERE request_id=?",
                        (json.dumps(legacy_binding, ensure_ascii=False,
                                    sort_keys=True), request_id))
                request_row = app.chat_request_row(request_id, connection)
                connection.execute(
                    "UPDATE messages SET delivery_status='completed' "
                    "WHERE id=?", (request_row["user_message"],))
                assistant_id = app._upsert_chat_assistant(
                    connection, request_row, assistant_text, "completed")
                stamp = app.now()
                connection.execute(
                    "UPDATE chat_requests SET status='completed',"
                    "assistant_message=?,finished=?,updated=? "
                    "WHERE request_id=?",
                    (assistant_id, stamp, stamp, request_id))
                connection.execute(
                    "UPDATE jobs SET status='succeeded',finished=?,updated=? "
                    "WHERE id=?",
                    (stamp, stamp, request_row["job"]))
                request_row = app.chat_request_row(request_id, connection)
                result = app.schema_v4_apply_bound_chat(
                    connection, request_row)
                connection.execute(
                    "UPDATE chat_requests SET schema_binding_result_json=? "
                    "WHERE request_id=?",
                    (json.dumps(result, ensure_ascii=False, sort_keys=True),
                     request_id))
        return result, self.dashboard(), request_row["user_message"], assistant_id

    def bound_provider_system_prompt(self, user_text, step_data,
                                     cleanup=False):
        """Return the exact system text prepared for a bound provider turn."""
        state = self.dashboard()
        path = state["active_path"]
        binding = dict(state["next_card"]["chat_binding"])
        link = path.get("active_technique_link")
        if link:
            binding.update({
                "technique_link_id": link["id"],
                "technique_link_public_id": link["public_id"],
                "expected_technique_revision": link[
                    "technique_revision"],
            })
        request_id = self.request_id("prompt-capture")
        request_row, created = app.begin_chat_request(
            self.conv, user_text,
            request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        if step_data is not None:
            with app.db() as connection:
                legacy_binding = dict(binding)
                legacy_binding["step_data"] = step_data
                connection.execute(
                    "UPDATE chat_requests SET schema_binding_json=? "
                    "WHERE request_id=?",
                    (json.dumps(legacy_binding, ensure_ascii=False,
                                sort_keys=True), request_id))
                request_row = app.chat_request_row(request_id, connection)
        _conv, payload = app._chat_prompt_payload(request_row)
        system = "\n\n".join(
            item["content"] for item in payload["messages"]
            if item["role"] == "system")
        if cleanup:
            with app.db() as connection:
                connection.execute(
                    "DELETE FROM chat_requests WHERE request_id=?",
                    (request_id,))
                connection.execute(
                    "DELETE FROM jobs WHERE id=?", (request_row["job"],))
                connection.execute(
                    "DELETE FROM messages WHERE id=?",
                    (request_row["user_message"],))
        return system

    def add_deferred_candidate(self, path_id):
        pair = self.completed_pair(
            "Sıradaki olasılık için ayrı doğrudan kullanıcı kaynağı")
        claim_id = self.approved_candidate(pair)
        with app.db() as connection:
            row = app.ensure_schema_candidate_queue_for_claim(
                connection, self.conv, claim_id, path_id)
            connection.execute(
                "UPDATE schema_candidate_queue SET status='deferred',"
                "updated=? WHERE id=?", (app.now(), row["id"]))
            row = connection.execute(
                "SELECT * FROM schema_candidate_queue WHERE id=?",
                (row["id"],)).fetchone()
        return dict(row)

    def start_imagery(self):
        state, _pairs, _claim = self.focus_path()
        result, state, _user, _assistant = self.complete_bound_turn(
            "Bu formu kendi sözlerimle onaylıyorum.", {
                "confidence": "reported", "age": 8,
                "scene": "Kapının yanında yalnız beklediğim kısa sahne",
                "unmet_need": "Yanımda sakin bir yetişkin olması",
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        precheck = {
            "method_id": app.IMAGERY_METHOD_NODE_ID,
            "orientation_confirmed": True,
            "reality_clear": True,
            "sleep_activation_clear": True,
            "intensity": 3,
            "support_available": False,
            "stop_signal": "dur",
        }
        status, state = self.mutate("start_chat_technique", **precheck)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "imagery_work")
        return state

    def start_imagery_chat_only(self):
        """Start imagery using only ordinary chat, with unique provenance."""
        state, _pairs = self.focus_chat_only_path()
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Hatırlamıyorum")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        for answer in (
                "Evet", "Evet", "Evet", "Yoğunluk 3", "Hayır",
                "Durma işaretim 'dur' olsun"):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "imagery_work")
        return state

    def complete_imagery_to_healthy_adult(self):
        """Drive the real selected imagery reducer through grounding."""
        state = self.start_imagery()
        for _index in range(12):
            if state["step"] == "healthy_adult_voice":
                return state
            result, state, _user, _assistant = self.complete_chat_only_turn(
                "Şimdi buradayım; bunun bir çalışma olduğunu biliyorum; "
                "yoğunluk 2/7. Sahnede fark ettiğimi yalnız kendi "
                "sözlerimle anlatıyorum.")
            self.assertTrue(result["applied"], result)
        self.fail("Gerçek imgeleme reducerı Sağlıklı Yetişkin adımına ulaşmadı")

    def populated_erasure_graph(self):
        """Populate every v4 lifecycle table with one plaintext sentinel."""
        sentinel = "SCHEMA-V4-ERASE-SENTINEL-9f3c"
        state = self.start_imagery()
        path = state["active_path"]
        pair = self.completed_pair(
            sentinel + " kullanıcı kaynağı",
            sentinel + " asistan kaynağı")
        stamp = app.now()
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET focus_evidence=? WHERE id=?",
                (sentinel, path["id"]))
            connection.execute(
                "UPDATE schema_candidate_queue SET evidence=? WHERE path=?",
                (sentinel, path["id"]))
            connection.execute(
                "UPDATE schema_focus_checks SET variable_text=? WHERE path=?",
                (sentinel, path["id"]))
            connection.execute(
                "UPDATE schema_path_steps SET payload_json=? WHERE path=?",
                (json.dumps({"sentinel": sentinel}), path["id"]))
            connection.execute(
                "UPDATE schema_origin SET scene=? WHERE path=?",
                (sentinel, path["id"]))
            connection.execute(
                "INSERT INTO schema_growth(public_id,path,conv,"
                "source_user_message,source_assistant_message,stage_label,"
                "now_response,seq,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("81000000000000000000000000000001", path["id"],
                 self.conv, pair["user_message_id"],
                 pair["assistant_message_id"], sentinel, sentinel, 1,
                 stamp, stamp))
            connection.execute(
                "INSERT INTO healthy_adult_marks(public_id,conv,path,source,"
                "evidence,source_message,source_assistant_message,created) "
                "VALUES(?,?,?,'user',?,?,?,?)",
                ("82000000000000000000000000000002", self.conv,
                 path["id"], sentinel, pair["user_message_id"],
                 pair["assistant_message_id"], stamp))
            connection.execute(
                "INSERT INTO schema_transfer_records(public_id,path,conv,"
                "source_user_message,source_assistant_message,"
                "trigger_source_user_message,"
                "trigger_source_assistant_message,trigger_text,"
                "healthy_adult_response,planned_action,support_choice,"
                "predicted_result,observed_result,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("83000000000000000000000000000003", path["id"],
                 self.conv, pair["user_message_id"],
                 pair["assistant_message_id"], pair["user_message_id"],
                 pair["assistant_message_id"], sentinel, sentinel,
                 sentinel, sentinel, sentinel, sentinel, stamp, stamp))
            connection.execute(
                "INSERT INTO schema_clinical_sync_events(public_id,conv,"
                "clinical_generation,enabled,action,request_id,created) "
                "VALUES(?,?,0,1,'enable',?,?)",
                ("84000000000000000000000000000004", self.conv,
                 "schema-v4-erasure-consent-0001", stamp))
            connection.execute(
                "INSERT INTO schema_path_sync_conflicts(public_id,conv,"
                "path_public_id,status,reason,created,updated) "
                "VALUES(?,?,?,'open',?,?,?)",
                ("85000000000000000000000000000005", self.conv,
                 path["public_id"], sentinel, stamp, stamp))
            connection.execute(
                "INSERT INTO schema_focus_offers(path,conv,candidates_json,"
                "status,created,updated) VALUES(?,?,?,'declined',?,?)",
                (path["id"], self.conv,
                 json.dumps({"sentinel": sentinel}), stamp, stamp))
            connection.execute(
                "INSERT INTO schema_inline_suggestions(conv,"
                "assistant_message,mode_key,evidence,status,created) "
                "VALUES(?,?,? ,?,'dismissed',?)",
                (self.conv, pair["assistant_message_id"],
                 next(iter(app.SCHEMA_MODE_CANDIDATE_CATALOG)), sentinel,
                 stamp))
            connection.execute(
                "INSERT INTO message_techniques(conv,message,phase,technique,"
                "rationale,created) VALUES(?,?,'listen',?,?,?)",
                (self.conv, pair["assistant_message_id"], sentinel,
                 sentinel, stamp))
            connection.execute(
                "UPDATE message_meta_events SET summary=?,payload_json=?,"
                "actions_json=? WHERE conv=?",
                (sentinel, json.dumps({"sentinel": sentinel}),
                 json.dumps([{"sentinel": sentinel}]), self.conv))
            connection.execute(
                "UPDATE schema_path_events SET payload_json=? WHERE conv=?",
                (json.dumps({"sentinel": sentinel}), self.conv))
        tables = (
            "schema_focus_checks", "schema_transfer_records",
            "schema_origin", "schema_growth", "healthy_adult_marks",
            "message_meta_events", "schema_path_techniques",
            "schema_path_steps", "schema_candidate_queue",
            "schema_clinical_sync_events", "schema_path_sync_conflicts",
            "schema_focus_offers", "schema_path_events", "schema_paths",
            "schema_inline_suggestions", "message_techniques",
        )
        for table in tables:
            self.assertGreater(self.row(
                "SELECT COUNT(*) AS n FROM {} WHERE conv=?".format(table),
                (self.conv,))["n"], 0, table)
        return sentinel, tables

    def test_chat_only_candidate_is_the_single_visible_card_and_yes_starts(self):
        pairs = self.completed_pairs(2)
        self.approved_candidate(pairs[0])
        state = self.dashboard()
        self.assertIsNone(state["next_card"])
        self.assertEqual(
            state["interaction_policy"]["composer_mode"], "ordinary")
        self.assertTrue(state["interaction_policy"]["composer_allowed"])

        self.completed_pair("Üçüncü tamamlanmış güvenli kaynak")
        state = self.dashboard()
        card = state["next_card"]
        self.assertEqual(state["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(state["version"], 5)
        self.assertEqual(state["presentation"], "chat_only")
        self.assertEqual(card["kind"], "candidate_prompt")
        self.assertEqual(card["presentation"], "chat_only")
        self.assertEqual(card["body"], "Bunu çalışmak ister misin?")
        self.assertTrue(card["context_line"].endswith(
            "tetiklenmiş olabilir."))
        self.assertEqual(card["title"], "")
        self.assertEqual(card["fields"], [])
        self.assertIsNone(card["revision"])
        self.assertIsNone(card["path_id"])
        self.assertTrue(app.TRANSFER_PUBLIC_ID_RE.fullmatch(
            card["candidate"]["public_id"]))
        self.assertEqual(
            [(item["action"], item["label"]) for item in card["actions"]],
            [("accept_candidate_chat", "Evet"),
             ("reject_candidate_chat", "Hayır")])
        self.assertEqual(
            state["interaction_policy"]["composer_mode"], "disabled")
        source = card["source"]
        yes = card["actions"][0]
        for key in (
                "user_message_id", "user_message_public_id",
                "assistant_message_id", "assistant_message_public_id"):
            self.assertEqual(yes["payload"]["source_" + key], source[key])

        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        request = {
            "action": yes["action"], "conv_id": self.conv,
            "request_id": self.request_id("candidate-one-click"),
            **yes["payload"],
        }
        status, accepted = self.post(request)
        self.assertEqual(status, 200, accepted)
        retry_status, retry = self.post(request)
        self.assertEqual(retry_status, 200, retry)
        self.assertEqual(accepted, retry)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages + 1)
        self.assertEqual(accepted["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(accepted["version"], 5)
        self.assertEqual(accepted["step"], "variable_explore")
        self.assertEqual(accepted["active_path"]["flow_version"], 5)
        prompt = accepted["next_card"]
        self.assertEqual(prompt["kind"], "chat_state")
        self.assertEqual(prompt["presentation"], "chat_only")
        self.assertEqual(prompt["body"], "")
        self.assertEqual(prompt["fields"], [])
        self.assertEqual(prompt["actions"], [])
        self.assertIsNone(prompt["chat_binding"])
        self.assertEqual(prompt["prompt_delivery"]["status"], "queued")
        self.assertEqual(
            accepted["interaction_policy"]["composer_mode"], "disabled")
        user = self.row(
            "SELECT * FROM messages WHERE conv=? ORDER BY id DESC LIMIT 1",
            (self.conv,))
        self.assertEqual((user["role"], user["content"]), ("user", "Evet"))
        prompt_request = self.row(
            "SELECT * FROM chat_requests WHERE conv=? AND "
            "schema_prompt_protocol=?",
            (self.conv, app.SCHEMA_PATH_V5_PROTOCOL))
        self.assertIsNotNone(prompt_request)
        self.assertEqual(prompt_request["user_message"], user["id"])
        self.assertEqual(prompt_request["schema_prompt_intent"],
                         "variable_scenario")
        self.assertEqual(self.queued_job_id(), prompt_request["job"])
        self.assertTrue(app.JOB_QUEUE.empty())

        _conv, provider_payload = app._chat_prompt_payload(prompt_request)
        system = provider_payload["messages"][0]["content"]
        self.assertIn("intent_id", system)
        self.assertIn("assistant_text", system)
        self.assertNotIn("0 ile 10", system[-1800:])
        raw = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "Bunu en son yaşadığın somut bir anı kısaca anlatır mısın?"),
        }, ensure_ascii=False)

        def delta(_event, chunk, _provider):
            return ("done", "") if chunk == "DONE" else ("text", chunk)

        events = []
        with mock.patch.object(
                app, "provider_request",
                return_value=(object(), {"id": "deepseek", "local": False,
                                         "model": "test"})), \
                mock.patch.object(
                    app, "open_provider_url", return_value=_ProviderStream()), \
                mock.patch.object(
                    app, "iter_sse_events", return_value=iter([
                        ("message", raw), ("message", "DONE")])), \
                mock.patch.object(
                    app, "provider_stream_delta", side_effect=delta), \
                mock.patch.object(app, "schedule_living_map_autoscan"), \
                mock.patch.object(app, "maybe_create_adhd_suggestion"), \
                mock.patch.object(app.threading, "Thread"):
            completed = app.run_chat_request(
                prompt_request["request_id"], emit=events.append,
                automatic_retries=False, generation=app.data_generation())
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            completed["content"],
            "Bunu en son yaşadığın somut bir anı kısaca anlatır mısın?")
        self.assertFalse(any(event.get("type") == "delta" for event in events))
        replace = [event for event in events if event.get("type") == "replace"]
        self.assertEqual(len(replace), 1)
        self.assertNotIn("intent_id", replace[0]["text"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages + 2)

        ready = self.dashboard()
        ready_card = ready["next_card"]
        self.assertEqual(ready_card["body"], "")
        self.assertEqual(ready_card["actions"], [])
        self.assertEqual(ready_card["prompt_delivery"]["status"],
                         "completed")
        self.assertEqual(
            ready_card["prompt_delivery"]["prompt_assistant_message_id"],
            completed["assistant_message_id"])
        self.assertIsNotNone(ready_card["chat_binding"], ready_card)
        self.assertEqual(
            ready_card["chat_binding"]["prompt_assistant_message_id"],
            completed["assistant_message_id"])
        self.assertEqual(ready["interaction_policy"]["composer_mode"],
                         "bound")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (ready["active_path"]["id"],))["n"], 1)

    def test_v5_prompt_rejects_nonconforming_output_without_visible_question(self):
        state, request, _pairs = self.start_v5_prompt_pending(
            "v5-invalid-envelope")
        path_id = state["active_path"]["id"]
        revision = state["active_path"]["revision"]
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        raw = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "Somut bir anı anlatır mısın? Sonra puan verir misin?"),
        }, ensure_ascii=False)

        result, events, provider = self.run_v5_prompt(
            request["request_id"], raw)

        provider.assert_called_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "schema_prompt_shape_invalid")
        self.assertIsNone(result["assistant_message_id"])
        self.assertFalse(any(event.get("type") in ("delta", "replace")
                             for event in events))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)
        stored = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (request["request_id"],))
        self.assertEqual(stored["partial_content"], "")
        self.assertEqual(stored["best_partial_content"], "")
        self.assertEqual(stored["schema_prompt_result_json"], "{}")
        self.assertNotIn("puan verir", json.dumps(dict(stored)))
        self.assertEqual(self.row(
            "SELECT revision FROM schema_paths WHERE id=?", (path_id,)
        )["revision"], revision)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], 0)
        failed = self.dashboard()["next_card"]
        self.assertEqual(failed["prompt_delivery"]["status"], "failed")
        self.assertIsNone(failed["chat_binding"])
        self.assertEqual(failed["body"], "")
        self.assertEqual(failed["actions"], [])

    def test_v5_post_yes_cards_never_project_a_question_or_visible_control(self):
        state, request, _pairs = self.start_v5_prompt_pending(
            "v5-visible-matrix")

        def assert_metadata_only(payload, expected_delivery):
            card = payload["next_card"]
            self.assertEqual(card["kind"], "chat_state")
            self.assertEqual(card["presentation"], "chat_only")
            self.assertEqual(card["prompt_delivery"]["status"],
                             expected_delivery)
            self.assertEqual(card["title"], "")
            self.assertEqual(card["context_line"], "")
            self.assertEqual(card["body"], "")
            self.assertEqual(card["fields"], [])
            self.assertEqual(card["actions"], [])
            visible = json.dumps({
                "card": {
                    key: card[key] for key in (
                        "title", "context_line", "body", "fields",
                        "actions")},
                "policy": payload["interaction_policy"],
            }, ensure_ascii=False).casefold()
            for forbidden in (
                    "0 ile 10", "0–10", "0 ile 7", "0–7",
                    "yoğunluk", "şiddet", "seviye", "kaç olur",
                    "çalışalım mı", "onay", "izin", "itiraz",
                    "uyku", "gerçekliği ayır", "desteğin var",
                    "stop sinyali", "duraklat", "çalışmayı bitir",
                    "şimdiye dön"):
                self.assertNotIn(forbidden, visible, expected_delivery)
            return card

        assert_metadata_only(state, "queued")
        with app.db() as connection:
            for delivery in ("running", "waiting_provider", "failed",
                             "interrupted", "cancelled"):
                connection.execute(
                    "UPDATE chat_requests SET status=?,error_code=? "
                    "WHERE request_id=?",
                    (delivery, "provider_unavailable" if delivery ==
                     "failed" else "", request["request_id"]))
                connection.commit()
                card = assert_metadata_only(self.dashboard(), delivery)
                self.assertIsNone(card["chat_binding"])
                self.assertIsNone(card["prompt_delivery"]
                                  ["prompt_assistant_message_id"])
                self.assertIsNone(card["prompt_delivery"]
                                  ["prompt_assistant_message_public_id"])
            connection.execute(
                "UPDATE chat_requests SET status='queued',error_code='' "
                "WHERE request_id=?", (request["request_id"],))
            connection.commit()

        completed, _events, provider = self.run_v5_prompt(
            request["request_id"], json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "Bunu en son yaşadığın somut bir anı kısaca anlatır "
                    "mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        completed_card = assert_metadata_only(
            self.dashboard(), "completed")
        self.assertIsInstance(completed_card["chat_binding"], dict)
        self.assertEqual(
            completed_card["chat_binding"]["prompt_assistant_message_id"],
            completed["assistant_message_id"])

        pause_request, created = app.begin_chat_request(
            self.conv, "Dur",
            request_id=self.request_id("v5-visible-pause"),
            schema_binding=dict(completed_card["chat_binding"]))
        self.assertTrue(created)
        self.assertEqual(pause_request["status"], "completed")
        self.assertIsNone(pause_request["assistant_message"])
        paused_card = assert_metadata_only(self.dashboard(), "completed")
        self.assertEqual(paused_card["status"], "paused")
        self.assertIsInstance(paused_card["chat_binding"], dict)

        stop_request, created = app.begin_chat_request(
            self.conv, "Bitir",
            request_id=self.request_id("v5-visible-stop"),
            schema_binding=dict(paused_card["chat_binding"]))
        self.assertTrue(created)
        self.assertEqual(stop_request["status"], "completed")
        self.assertIsNone(stop_request["assistant_message"])
        terminal = self.dashboard()
        self.assertIsNone(terminal["next_card"])
        self.assertEqual(terminal["interaction_policy"]["composer_mode"],
                         "ordinary")

    def test_v5_prompt_safety_race_rolls_back_question_and_checkpoint(self):
        state, request, pairs = self.start_v5_prompt_pending(
            "v5-safety-race")
        path_id = state["active_path"]["id"]
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        raw = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "Bunu yaşadığın somut bir anı kısaca anlatır mısın?"),
        }, ensure_ascii=False)

        def hold_before_commit():
            with app.DATA_WRITE_LOCK:
                with app.db() as connection:
                    app.record_safety_event(
                        connection, self.conv,
                        {"detected": True, "kind": "current_risk",
                         "context": "chat", "detector_version": 1},
                        source_message=pairs[0]["user_message_id"],
                        detector_context="chat")

        result, events, provider = self.run_v5_prompt(
            request["request_id"], raw, before_done=hold_before_commit)

        provider.assert_called_once()
        # The safety coordinator may cancel a still-running prompt before its
        # terminal worker commit. Cancellation is the atomic, no-message
        # outcome; the safety-specific error remains durable.
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error_code"], "schema_safety_pause")
        self.assertIsNone(result["assistant_message_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], 0)
        self.assertFalse(any(event.get("type") in ("delta", "replace")
                             for event in events))
        paused = self.row(
            "SELECT status,pause_reason FROM schema_paths WHERE id=?",
            (path_id,))
        self.assertEqual((paused["status"], paused["pause_reason"]),
                         ("paused", "safety_hold"))

    def test_v5_prompt_source_race_fails_before_question_persistence(self):
        state, request, pairs = self.start_v5_prompt_pending(
            "v5-source-race")
        path_id = state["active_path"]["id"]
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        raw = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "En son yaşadığın somut bir anı kısaca anlatır mısın?"),
        }, ensure_ascii=False)

        def invalidate_before_commit():
            with app.db() as connection:
                connection.execute(
                    "UPDATE messages SET delivery_status='failed' WHERE id=?",
                    (pairs[0]["user_message_id"],))

        result, _events, provider = self.run_v5_prompt(
            request["request_id"], raw,
            before_done=invalidate_before_commit)

        provider.assert_called_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "schema_source_invalid")
        self.assertIsNone(result["assistant_message_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], 0)

    def test_v5_failed_prompt_retries_same_turn_and_commits_once(self):
        state, request, _pairs = self.start_v5_prompt_pending(
            "v5-provider-retry")
        path_id = state["active_path"]["id"]
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        invalid = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": "Somut bir durumu anlatır mısın? İkinci soru?",
        }, ensure_ascii=False)
        first, _events, _provider = self.run_v5_prompt(
            request["request_id"], invalid)
        self.assertEqual(first["status"], "failed")

        with mock.patch.object(app, "start_job_worker"), \
                mock.patch.object(app, "enqueue_job") as enqueue:
            retried, created = app.retry_chat_request(request["request_id"])
        self.assertTrue(created)
        self.assertEqual(retried["status"], "queued")
        enqueue.assert_called_once_with(
            request["job"], app.data_generation())
        valid = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "En son yaşadığın somut bir anı kısaca anlatır mısın?"),
        }, ensure_ascii=False)
        completed, events, provider = self.run_v5_prompt(
            request["request_id"], valid)
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages + 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], 1)
        self.assertEqual(len([
            event for event in events if event.get("type") == "replace"]), 1)

    def test_v5_completed_prompt_worker_retry_is_provider_free_idempotent(self):
        state, request, _pairs = self.start_v5_prompt_pending(
            "v5-completed-retry")
        path_id = state["active_path"]["id"]
        raw = json.dumps({
            "intent_id": "variable_scenario",
            "assistant_text": (
                "Bunu yaşadığın somut bir durumu anlatır mısın?"),
        }, ensure_ascii=False)
        completed, _events, _provider = self.run_v5_prompt(
            request["request_id"], raw)
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        before_checkpoints = self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"]

        emitted = []
        with mock.patch.object(
                app, "provider_request",
                side_effect=AssertionError("provider must not run")) as provider:
            repeated = app.run_chat_request(
                request["request_id"], emit=emitted.append,
                automatic_retries=False, generation=app.data_generation())

        provider.assert_not_called()
        self.assertEqual(repeated, completed)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], before_checkpoints)
        self.assertEqual([event["type"] for event in emitted],
                         ["replace", "done"])

    def test_v5_queued_prompt_is_recovered_after_process_restart(self):
        _state, request, _pairs = self.start_v5_prompt_pending(
            "v5-restart")
        with app.db() as connection:
            connection.execute(
                "UPDATE chat_requests SET status='running',attempt_count=1,"
                "lease_token='dead-process',heartbeat_at=? WHERE request_id=?",
                (0, request["request_id"]))
            connection.execute(
                "UPDATE jobs SET status='running' WHERE id=?",
                (request["job"],))

        with mock.patch.object(
                app, "schedule_chat_request") as schedule, \
                mock.patch.object(app, "signal_chat_cancellation"):
            summary = app.recover_stale_chat_requests(schedule=True)

        self.assertEqual(summary["stale"], 1)
        recovered = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?",
            (request["request_id"],))
        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(recovered["error_code"], "stale_worker_recovered")
        with app.db() as connection:
            public = app.public_chat_request(app.chat_request_row(
                request["request_id"], connection))
        self.assertEqual(public["schema_prompt_protocol"],
                         app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(public["schema_prompt_intent"],
                         "variable_scenario")
        self.assertNotIn("schema_prompt_plan_json", public)
        self.assertNotIn("schema_prompt_result_json", public)
        schedule.assert_called_once()
        self.assertEqual(schedule.call_args.args[:3], (
            request["request_id"], request["job"], app.data_generation()))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM chat_requests WHERE request_id=?",
            (request["request_id"],))["n"], 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE client_event_id=?",
            (request["request_id"],))["n"], 1)

    def test_v4_interactive_prompt_is_retired_then_only_devam_asks_real_v5_question(self):
        state, _pairs = self.start_v5_ready("v4-retire-to-v5")
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            step_pair = connection.execute(
                "SELECT source_user_message,source_assistant_message FROM "
                "schema_path_steps WHERE path=? AND step='variable_explore'",
                (path_id,)).fetchone()
            stamp = app.now()
            connection.execute(
                "UPDATE schema_paths SET flow_version=4,stage='listen',"
                "step='current_impact',phase='explore',status='active',"
                "pause_reason='',resume_required=0 WHERE id=?", (path_id,))
            connection.execute(
                "INSERT INTO schema_path_steps(public_id,path,conv,stage,"
                "step,status,revision,source_user_message,"
                "source_assistant_message,payload_json,created,updated) "
                "VALUES(?,?,?,'listen','current_impact','active',1,?,?,?,"
                "?,?)",
                (app._schema_natural_public_id(
                    "step", path["public_id"], "current_impact"), path_id,
                 self.conv, step_pair["source_user_message"],
                 step_pair["source_assistant_message"], json.dumps({
                     "chat": {"prompt": "burden", "values": {},
                              "sources": {}}}), stamp, stamp))
            connection.execute(
                "UPDATE schema_path_checkpoints SET stage='listen',"
                "step='current_impact',prompt_key='burden' WHERE path=? "
                "AND status='active'", (path_id,))

        migrated = self.dashboard()
        self.assertEqual(migrated["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(migrated["active_path"]["flow_version"], 5)
        self.assertEqual((migrated["stage"], migrated["step"]),
                         ("explore", "variable_explore"))
        self.assertEqual(migrated["active_path"]["status"], "paused")
        self.assertEqual(migrated["next_card"]["body"], "")
        self.assertEqual(migrated["next_card"]["actions"], [])
        self.assertIsInstance(migrated["next_card"]["chat_binding"], dict)
        frozen = json.dumps(migrated, ensure_ascii=False).casefold()
        for forbidden in (
                "0 ile 10", "yoğunluk", "yük kaç", "çalışalım mı",
                "uykun", "desteğin var mı", "stop sinyali"):
            self.assertNotIn(forbidden, frozen)
        retired = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
            "transition_kind='import' ORDER BY seq DESC LIMIT 1",
            (path_id,))
        self.assertEqual(retired["status"], "paused")
        self.assertEqual(retired["prompt_key"], "scenario")

        request_id = self.request_id("v4-retire-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=request_id,
            schema_binding=dict(migrated["next_card"]["chat_binding"]))
        self.assertTrue(created)
        completed, _events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "En son yaşadığın somut bir anı kısaca anlatır mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        resumed = self.dashboard()
        self.assertEqual(resumed["active_path"]["status"], "active")
        self.assertEqual(resumed["next_card"]["chat_binding"]
                         ["prompt_assistant_message_id"],
                         completed["assistant_message_id"])

    def test_v4_retirement_is_parallel_idempotent(self):
        state, _pairs = self.start_v5_ready("v4-retire-parallel")
        path_id = self.force_v4_legacy_prompt(state)

        def read_snapshot(_index):
            payload = app.schema_path_payload(self.conv)
            return (
                payload["active_path"]["flow_version"],
                payload["revision"],
                payload["next_card"]["checkpoint"]["public_id"],
                payload["next_card"]["checkpoint"]["seq"],
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            snapshots = list(pool.map(read_snapshot, range(8)))
        self.assertEqual(len(set(snapshots)), 1)
        self.assertEqual(snapshots[0][0], 5)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=? "
            "AND transition_kind='import' AND status='paused'",
            (path_id,))["n"], 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_steps WHERE path=? AND "
            "step='variable_explore' AND status='paused'",
            (path_id,))["n"], 1)

    def test_v4_source_or_safety_gate_never_projects_old_question_and_stop_has_no_ack(self):
        for index, gate in enumerate(("safety", "source")):
            with self.subTest(gate=gate):
                if index:
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                state, pairs = self.start_v5_ready(
                    "v4-retire-gate-{}".format(gate))
                path_id = self.force_v4_legacy_prompt(state)
                with app.db() as connection:
                    if gate == "safety":
                        connection.execute(
                            "UPDATE conversations SET safety_hold=1 WHERE id=?",
                            (self.conv,))
                    else:
                        connection.execute(
                            "UPDATE chat_requests SET status='failed' WHERE "
                            "conv=? AND user_message=?",
                            (self.conv, pairs[0]["user_message_id"]))
                gated = self.dashboard()
                self.assertEqual(gated["active_path"]["flow_version"], 4)
                self.assertEqual(gated["next_card"]["body"], "")
                self.assertEqual(gated["next_card"]["actions"], [])
                self.assertTrue(gated["next_card"]["legacy_prompt_retired"])
                rendered = json.dumps(gated, ensure_ascii=False).casefold()
                for forbidden in (
                        "0 ile 10", "0 ile 7", "yoğunluk", "yük kaç",
                        "çalışalım mı", "uykun", "desteğin var mı"):
                    self.assertNotIn(forbidden, rendered)
                binding = dict(gated["next_card"]["chat_binding"])
                before_messages = self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                    (self.conv,))["n"]
                before_assistants = self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
                    "role='assistant'", (self.conv,))["n"]
                with self.assertRaises(app.RequestInputError) as rejected, \
                        mock.patch.object(app, "open_provider_url") as network:
                    app.begin_chat_request(
                        self.conv, "7",
                        request_id=self.request_id(
                            "v4-retired-answer-{}".format(gate)),
                        schema_binding=binding)
                network.assert_not_called()
                self.assertEqual(rejected.exception.error_code,
                                 "schema_protocol_update_required")
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                    (self.conv,))["n"], before_messages)
                with mock.patch.object(
                        app, "selected_provider",
                        side_effect=AssertionError(
                            "provider must not be read")), \
                        mock.patch.object(app, "open_provider_url") as network:
                    stopped, created = app.begin_chat_request(
                        self.conv, "Bitir",
                        request_id=self.request_id(
                            "v4-retired-stop-{}".format(gate)),
                        schema_binding=binding)
                    network.assert_not_called()
                self.assertTrue(created)
                self.assertIsNone(stopped["assistant_message"])
                self.assertEqual(self.row(
                    "SELECT status FROM schema_paths WHERE id=?", (path_id,)
                )["status"], "stopped")
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
                    "role='assistant'", (self.conv,))["n"],
                    before_assistants)

    def test_v4_active_run_retires_to_real_grounding_before_integration(self):
        methods = (
            (app.IMAGERY_METHOD_NODE_ID, "imagery_work"),
            (app.REPARENTING_METHOD_NODE_ID, "reparent_or_chair_work"),
        )
        for index, (method_id, legacy_step) in enumerate(methods):
            with self.subTest(method_id=method_id):
                if index:
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                state, _pairs = self.start_v5_ready(
                    "legacy-run-{}".format(index))
                path_id, run_id, link_id = self.force_v4_legacy_run(
                    state, method_id, legacy_step)
                before = {
                    table: self.row(
                        "SELECT COUNT(*) AS n FROM {} WHERE conv=?".format(
                            table), (self.conv,))["n"]
                    for table in ("messages", "jobs", "chat_requests")
                }

                migrated = self.dashboard()
                self.assertEqual((migrated["stage"], migrated["step"]),
                                 ("work", "grounding_review"))
                self.assertEqual(migrated["active_path"]["flow_version"], 5)
                self.assertEqual(migrated["active_path"]["status"], "paused")
                self.assertEqual(migrated["active_path"]["method_id"], None)
                self.assertEqual(migrated["next_card"]["prompt_delivery"]
                                 ["status"], "imported_waiting")
                self.assertEqual((migrated["next_card"]["body"],
                                  migrated["next_card"]["actions"]),
                                 ("", []))
                for table, count in before.items():
                    self.assertEqual(self.row(
                        "SELECT COUNT(*) AS n FROM {} WHERE conv=?".format(
                            table), (self.conv,))["n"], count, table)
                self.assertEqual(self.row(
                    "SELECT status,phase FROM technique_runs WHERE id=?",
                    (run_id,))["status"], "paused")
                self.assertEqual(self.row(
                    "SELECT status FROM schema_path_techniques WHERE id=?",
                    (link_id,))["status"], "paused")
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
                    "WHERE path=?", (path_id,))["n"], 0)
                step_payload = json.loads(self.row(
                    "SELECT payload_json FROM schema_path_steps WHERE path=? "
                    "AND step='grounding_review'", (path_id,))[
                        "payload_json"])
                marker = step_payload["legacy_flow_boundary"]
                self.assertEqual((marker["kind"], marker["method_id"],
                                  marker["imported_step"]),
                                 ("legacy_run_grounding", method_id,
                                  legacy_step))

                resume_id = self.request_id("legacy-run-devam")
                request, created = app.begin_chat_request(
                    self.conv, "Devam", request_id=resume_id,
                    schema_binding=dict(
                        migrated["next_card"]["chat_binding"]))
                self.assertTrue(created)
                self.assertEqual(json.loads(request[
                    "schema_prompt_plan_json"])["intent_id"], "grounding")
                completed, _events, provider = self.run_v5_prompt(
                    resume_id, json.dumps({
                        "intent_id": "grounding",
                        "assistant_text": (
                            "Şimdi bulunduğun yerde çevrende ne görüyorsun?"),
                    }, ensure_ascii=False))
                provider.assert_called_once()
                self.assertEqual(completed["status"], "completed")
                active = self.dashboard()
                self.assertEqual(active["active_path"]["status"], "active")
                self.assertEqual(active["step"], "grounding_review")

                completed, integrated, _request, _events, provider = \
                    self.complete_v5_turn(
                        "Şimdi odadayım ve pencereyi görüyorum.", {
                            "intent_id": "healthy_adult_voice",
                            "assistant_text": (
                                "Bugünkü Sağlıklı Yetişkin tarafın o "
                                "zamanki sana ne söylemek ister?"),
                        }, "legacy-run-grounded")
                provider.assert_called_once()
                self.assertEqual(completed["status"], "completed")
                self.assertEqual((integrated["stage"], integrated["step"]),
                                 ("integrate", "healthy_adult_voice"))
                self.assertEqual(self.row(
                    "SELECT status,phase FROM technique_runs WHERE id=?",
                    (run_id,))["status"], "stopped")
                self.assertEqual(self.row(
                    "SELECT status FROM schema_path_techniques WHERE id=?",
                    (link_id,))["status"], "stopped")
                self.assertEqual(self.row(
                    "SELECT technique_run FROM schema_paths WHERE id=?",
                    (path_id,))["technique_run"], None)
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
                    "WHERE path=?", (path_id,))["n"], 0)

    def test_v4_integration_retires_in_place_and_preserves_artifacts(self):
        state, _pairs = self.start_v5_ready("legacy-integrate")
        path_id, healthy_public, growth_public = \
            self.force_v4_legacy_integration(
                state, "environment_rescript")
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]

        migrated = self.dashboard()
        self.assertEqual((migrated["stage"], migrated["step"]),
                         ("integrate", "environment_rescript"))
        self.assertEqual(migrated["active_path"]["flow_version"], 5)
        self.assertEqual(migrated["active_path"]["status"], "paused")
        self.assertEqual(migrated["next_card"]["prompt_delivery"]["status"],
                         "imported_waiting")
        self.assertEqual((migrated["next_card"]["body"],
                          migrated["next_card"]["actions"]), ("", []))
        self.assertEqual(self.row(
            "SELECT status FROM healthy_adult_marks WHERE public_id=?",
            (healthy_public,))["status"], "active")
        growth = self.row(
            "SELECT * FROM schema_growth WHERE public_id=?",
            (growth_public,))
        self.assertEqual((growth["status"], growth["now_response"]),
                         ("active", "Eski güvenli yaş izi"))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))["n"], 0)

        resume_id = self.request_id("legacy-integrate-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(migrated["next_card"]["chat_binding"]))
        self.assertTrue(created)
        plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual((plan["intent_id"], plan["output_prompt_key"]),
                         ("environment_rescript", "environment"))
        completed, _events, provider = self.run_v5_prompt(
            resume_id, json.dumps({
                "intent_id": "environment_rescript",
                "assistant_text": (
                    "O çevrede farklı olmasını istediğin tek şey ne olurdu?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        resumed = self.dashboard()
        self.assertEqual((resumed["stage"], resumed["step"]),
                         ("integrate", "environment_rescript"))
        self.assertEqual(self.row(
            "SELECT now_response FROM schema_growth WHERE public_id=?",
            (growth_public,))["now_response"], "Eski güvenli yaş izi")

        completed, advanced, _request, _events, provider = \
            self.complete_v5_turn(
                "Kapının açık olmasını isterdim.", {
                    "intent_id": "present_transfer",
                    "assistant_text": (
                        "Bugün bu örüntünün belirdiği somut bir durum neydi?"),
                }, "legacy-integrate-answer")
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual((advanced["stage"], advanced["step"]),
                         ("integrate", "present_transfer"))
        self.assertEqual(self.row(
            "SELECT status FROM healthy_adult_marks WHERE public_id=?",
            (healthy_public,))["status"], "active")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))["n"], 0)

    def test_v4_active_run_retirement_is_parallel_idempotent(self):
        state, _pairs = self.start_v5_ready("legacy-run-parallel")
        path_id, run_id, link_id = self.force_v4_legacy_run(
            state, app.IMAGERY_METHOD_NODE_ID, "imagery_work")

        with ThreadPoolExecutor(max_workers=4) as pool:
            states = list(pool.map(
                lambda _index: app.schema_path_payload(self.conv), range(8)))
        identities = {
            (item["revision"],
             item["next_card"]["checkpoint"]["public_id"],
             item["next_card"]["checkpoint"]["seq"])
            for item in states}
        self.assertEqual(len(identities), 1, identities)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=? "
            "AND transition_kind='import' AND status='paused'",
            (path_id,))["n"], 1)
        self.assertEqual(self.row(
            "SELECT status FROM technique_runs WHERE id=?", (run_id,)
        )["status"], "paused")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_techniques WHERE id=?",
            (link_id,))["status"], "paused")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))["n"], 0)

    def test_v4_run_and_integration_retirement_fail_closed_on_stale_lineage(self):
        # A stale current run anchor never becomes a v5 recovery boundary.
        state, _pairs = self.start_v5_ready("legacy-run-stale")
        path_id, run_id, _link_id = self.force_v4_legacy_run(
            state, app.IMAGERY_METHOD_NODE_ID, "imagery_work")
        checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
            "status='active'", (path_id,))
        with app.db() as connection:
            connection.execute(
                "UPDATE chat_requests SET status='failed' WHERE conv=? AND "
                "user_message=? AND assistant_message=?",
                (self.conv, checkpoint["anchor_user_message"],
                 checkpoint["anchor_assistant_message"]))
        stale_run = self.dashboard()
        self.assertEqual(stale_run["active_path"]["flow_version"], 4)
        self.assertEqual(stale_run["active_path"]["status"], "paused")
        self.assertTrue(stale_run["next_card"]["legacy_prompt_retired"])
        self.assertEqual((stale_run["next_card"]["body"],
                          stale_run["next_card"]["actions"]), ("", []))
        self.assertEqual(self.row(
            "SELECT status FROM technique_runs WHERE id=?", (run_id,)
        )["status"], "paused")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_steps WHERE path=? AND "
            "payload_json LIKE '%legacy_flow_boundary%'", (path_id,)
        )["n"], 0)

        # The current integration prompt remains safe while a distinct active
        # predecessor artifact loses its completed-turn authority.
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        state, _pairs = self.start_v5_ready("legacy-integrate-stale")
        path_id, healthy_public, _growth_public = \
            self.force_v4_legacy_integration(
                state, "environment_rescript")
        artifact_pair = self.completed_pair(
            "Bu yalnız eski Sağlıklı Yetişkin artefakt kaynağı.")
        with app.db() as connection:
            connection.execute(
                "UPDATE healthy_adult_marks SET source_message=?,"
                "source_assistant_message=? WHERE public_id=?",
                (artifact_pair["user_message_id"],
                 artifact_pair["assistant_message_id"], healthy_public))
            connection.execute(
                "UPDATE chat_requests SET status='failed' WHERE conv=? AND "
                "user_message=? AND assistant_message=?",
                (self.conv, artifact_pair["user_message_id"],
                 artifact_pair["assistant_message_id"]))
        stale_integration = self.dashboard()
        self.assertEqual(stale_integration["active_path"]["flow_version"], 4)
        self.assertEqual(stale_integration["active_path"]["status"],
                         "paused")
        self.assertEqual((stale_integration["next_card"]["body"],
                          stale_integration["next_card"]["actions"]),
                         ("", []))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_steps WHERE path=? AND "
            "payload_json LIKE '%legacy_flow_boundary%'", (path_id,)
        )["n"], 0)

    def test_v5_scenario_answer_creates_one_grounded_hypothetical_question(self):
        state, _pairs = self.start_v5_ready("v5-scenario-ready")
        first_question = state["next_card"]["prompt_delivery"][
            "prompt_assistant_message_id"]
        result, state, request, events, provider = self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve sesim çıkmadı.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "Toplantıda sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı sözünü kesmek yerine "
                    "seni dinlemek olsaydı, bu an nasıl değişirdi?"),
            }, "v5-scenario-answer")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(request["reply_to"], first_question)
        self.assertEqual(state["step"], "variable_explore")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "hypothetical_response")
        self.assertEqual(state["next_card"]["body"], "")
        self.assertEqual(state["next_card"]["actions"], [])
        trial = self.row(
            "SELECT * FROM schema_variable_trials WHERE path=?",
            (state["active_path"]["id"],))
        self.assertEqual((trial["category"], trial["status"]),
                         ("other_person_behavior", "asked"))
        self.assertEqual(trial["hypothetical_anchor"],
                         "Toplantıda sözüm kesildi")
        self.assertEqual(trial["question_user_message"],
                         request["user_message"])
        self.assertEqual(trial["question_assistant_message"],
                         result["assistant_message_id"])
        self.assertEqual(len([
            event for event in events if event.get("type") == "replace"]), 1)
        self.assertNotIn("grounded_quote", result["content"])

    def test_v5_explicit_variable_effect_selects_method_before_any_run(self):
        self.start_v5_ready("v5-driver-ready")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı seni kesmek yerine "
                    "dinlemek olsaydı, yaşadığın an nasıl değişirdi?"),
            }, "v5-driver-scenario")
        result, state, request, _events, provider = self.complete_v5_turn(
            "Daha az gerilir ve kendimi daha güvende hissederdim.", {
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için imgeleme ile yeniden senaryolamayı "
                    "kullanacağım; o zamanki yaşına dair ne hatırlıyorsun?"),
            }, "v5-driver-effect")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["stage"], "origin")
        self.assertEqual(state["step"], "origin_sequence")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "age")
        path_id = state["active_path"]["id"]
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_origin_answers WHERE path=?",
            (path_id,))["n"], 0)
        self.assertIsNone(self.row(
            "SELECT age_reported FROM schema_origin WHERE path=?",
            (path_id,)))
        path = self.row(
            "SELECT * FROM schema_paths WHERE id=?",
            (state["active_path"]["id"],))
        self.assertEqual(path["method_node_id"], app.IMAGERY_METHOD_NODE_ID)
        choice = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=?",
            (path["id"],))
        self.assertEqual(
            (choice["method_node_id"], choice["status"],
             choice["authored_by"]),
            (app.IMAGERY_METHOD_NODE_ID, "selected", "server_rule"))
        self.assertEqual(
            (choice["source_user_message"],
             choice["source_assistant_message"]),
            (request["user_message"], result["assistant_message_id"]))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE path=?",
            (path["id"],))["n"], 0)
        self.assertNotIn("çalışalım mı", result["content"].casefold())
        self.assertNotIn("ister misin", result["content"].casefold())
        self.assertEqual(result["content"].count("?"), 1)

    def test_v5_origin_sequence_asks_one_durable_question_per_exact_pair(self):
        state = self.v5_origin_ready("v5-origin-sequence")
        path_id = state["active_path"]["id"]
        turns = (
            ("8 yaşındaydım", {
                "intent_id": "origin_place",
                "assistant_text": (
                    "O anı düşündüğünde nerede olduğunu hatırlıyor musun?"),
            }, "place", "age", 8),
            ("Okulun koridorundaydım.", {
                "intent_id": "origin_event_response",
                "assistant_text": "Orada tam olarak ne oldu?",
            }, "what", "place", None),
            ("Arkadaşım herkesin içinde sözümü kesti.", {
                "intent_id": "origin_event_response",
                "assistant_text": "O anda nasıl karşılık verdin?",
            }, "how", "what", None),
            ("Sessiz kaldım ve uzaklaştım.", {
                "intent_id": "origin_unmet_need",
                "assistant_text": "O anda en çok neye ihtiyaç duyardın?",
            }, "need", "how", None),
        )
        expected_sources = {}
        for index, (user_text, envelope, next_key, field, age) in enumerate(
                turns):
            result, state, request, events, provider = self.complete_v5_turn(
                user_text, envelope,
                "v5-origin-{}".format(index))
            provider.assert_called_once()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(state["step"], "origin_sequence")
            self.assertEqual(
                state["next_card"]["checkpoint"]["prompt_key"], next_key)
            self.assertEqual(result["content"].count("?"), 1)
            self.assertEqual(len([
                event for event in events
                if event.get("type") == "replace"]), 1)
            expected_sources[field] = (
                request["user_message"], result["assistant_message_id"], age)

        rows = self.rows(
            "SELECT * FROM schema_origin_answers WHERE path=? ORDER BY seq",
            (path_id,))
        self.assertEqual([row["field"] for row in rows],
                         ["age", "place", "what", "how"])
        for row in rows:
            user_id, assistant_id, age = expected_sources[row["field"]]
            self.assertEqual(
                (row["source_user_message"],
                 row["source_assistant_message"]),
                (user_id, assistant_id))
            self.assertEqual(row["status"], "active")
            self.assertEqual(row["age_value"], age)
        aggregate = self.row(
            "SELECT * FROM schema_origin WHERE path=?", (path_id,))
        self.assertEqual(aggregate["age_reported"], 8)
        self.assertEqual(
            aggregate["scene"],
            "Arkadaşım herkesin içinde sözümü kesti.")
        self.assertEqual(aggregate["unmet_need"], "")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_v5_origin_hatirlamiyorum_skips_age_without_inventing_value(self):
        state = self.v5_origin_ready("v5-origin-unknown")
        result, state, request, _events, provider = self.complete_v5_turn(
            "Hatırlamıyorum.", {
                "intent_id": "origin_place",
                "assistant_text": "Aklına gelen bir yer ya da ortam var mı?",
            }, "v5-origin-unknown-age")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "place")
        answer = self.row(
            "SELECT * FROM schema_origin_answers WHERE path=? AND field='age'",
            (state["active_path"]["id"],))
        self.assertEqual(answer["status"], "unknown")
        self.assertIsNone(answer["age_value"])
        self.assertEqual(answer["text_value"], "")
        self.assertEqual(
            (answer["source_user_message"],
             answer["source_assistant_message"]),
            (request["user_message"], result["assistant_message_id"]))
        aggregate = self.row(
            "SELECT * FROM schema_origin WHERE path=?",
            (state["active_path"]["id"],))
        self.assertIsNone(aggregate["age_reported"])
        self.assertEqual(aggregate["confidence"], "unknown")

    def test_v5_ambiguous_effect_clarifies_without_method_or_run(self):
        self.start_v5_ready("v5-effect-unclear")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı seni dinlemek "
                    "olsaydı, bu an nasıl değişirdi?"),
            }, "v5-effect-unclear-scenario")
        result, state, _request, _events, provider = self.complete_v5_turn(
            "Bilmiyorum, emin olamadım.", {
                "intent_id": "variable_response_clarify",
                "assistant_text": (
                    "Bu varsayımsal değişiklik deneyimini azaltır mı, "
                    "artırır mı, yoksa aynı mı bırakırdı?"),
            }, "v5-effect-unclear-answer")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["step"], "variable_explore")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "hypothetical_response")
        trials = self.rows(
            "SELECT status,effect,category FROM schema_variable_trials "
            "WHERE path=? ORDER BY seq",
            (state["active_path"]["id"],))
        self.assertEqual(
            [(row["status"], row["effect"], row["category"])
             for row in trials],
            [("unclear", "unclear", "other_person_behavior"),
             ("asked", "", "other_person_behavior")])
        self.assertEqual(state["active_path"]["method_id"], None)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices WHERE path=?",
            (state["active_path"]["id"],))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_v5_no_change_asks_next_distinct_hypothetical(self):
        self.start_v5_ready("v5-no-change")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "Toplantıda sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı seni dinlemek "
                    "olsaydı, bu an nasıl değişirdi?"),
            }, "v5-no-change-scenario")
        result, state, _request, _events, provider = self.complete_v5_turn(
            "Aynı kalırdı.", {
                "intent_id": "variable_counterfactual",
                "category": "place",
                "grounded_quote": "Toplantıda sözüm kesildi",
                "assistant_text": (
                    "Eğer bulunduğun yer farklı bir ortam olsaydı, bu an "
                    "nasıl değişirdi?"),
            }, "v5-no-change-answer")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["step"], "variable_explore")
        trials = self.rows(
            "SELECT status,effect,category FROM schema_variable_trials "
            "WHERE path=? ORDER BY seq",
            (state["active_path"]["id"],))
        self.assertEqual(
            [(row["status"], row["effect"], row["category"])
             for row in trials],
            [("no_change", "no_change", "other_person_behavior"),
             ("asked", "", "place")])
        self.assertIsNone(state["active_path"]["method_id"])

    def test_v5_variable_exploration_has_total_four_question_limit(self):
        self.start_v5_ready("v5-variable-limit")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": "ignored by helper",
            }, "v5-variable-limit-scenario")
        for index in range(3):
            result, state, _request, _events, provider = self.complete_v5_turn(
                "Emin değilim, bilmiyorum.", {
                    "intent_id": "variable_response_clarify",
                    "assistant_text": (
                        "Bu varsayımsal değişiklik deneyimini nasıl etkilerdi?"),
                }, "v5-variable-limit-clarify-{}".format(index))
            provider.assert_called_once()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(state["step"], "variable_explore")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_variable_trials WHERE path=?",
            (state["active_path"]["id"],))["n"], 4)
        path_id = state["active_path"]["id"]
        result, _state, _request, events, provider = self.complete_v5_turn(
            "Kararsızım, net değil.", {
                "intent_id": "variable_limit_close",
                "assistant_text": (
                    "Belirleyici değişkeni güvenle ayıramadığım için çalışmayı "
                    "derinleştirmeden burada bırakıyorum."),
            }, "v5-variable-limit-close")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["content"].count("?"), 0)
        self.assertEqual(len([
            event for event in events if event.get("type") == "replace"]), 1)
        path = self.row("SELECT * FROM schema_paths WHERE id=?", (path_id,))
        self.assertEqual((path["status"], path["stage"], path["step"]),
                         ("completed", "complete", "complete"))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_variable_trials WHERE path=?",
            (path_id,))["n"], 4)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices WHERE path=?",
            (path_id,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))["n"], 0)

    def test_v5_fourth_trial_concurrent_answers_create_one_request_and_close_once(self):
        self.start_v5_ready("v5-variable-limit-race")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": "ignored by helper",
            }, "v5-variable-race-scenario")
        state = None
        for index in range(3):
            _result, state, _request, _events, provider = \
                self.complete_v5_turn(
                    "Emin değilim, bilmiyorum.", {
                        "intent_id": "variable_response_clarify",
                        "assistant_text": (
                            "Bu varsayımsal değişiklik deneyimini nasıl "
                            "etkilerdi?"),
                    }, "v5-variable-race-clarify-{}".format(index))
            provider.assert_called_once()
        path_id = state["active_path"]["id"]
        binding = dict(state["next_card"]["chat_binding"])
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        request_ids = (
            self.request_id("v5-variable-race-a"),
            self.request_id("v5-variable-race-b"))

        def submit(request_id):
            try:
                return app.begin_chat_request(
                    self.conv, "Kararsızım, net değil.",
                    request_id=request_id, schema_binding=dict(binding))
            except app.RequestInputError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, request_ids))
        accepted = [item for item in outcomes if isinstance(item, tuple)]
        rejected = [item for item in outcomes
                    if isinstance(item, app.RequestInputError)]
        self.assertEqual((len(accepted), len(rejected)), (1, 1))
        request, created = accepted[0]
        self.assertTrue(created)
        self.assertIn(rejected[0].error_code, (
            "schema_chat_binding_stale", None))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages + 1)
        retry, retry_created = app.begin_chat_request(
            self.conv, "Kararsızım, net değil.",
            request_id=request["request_id"], schema_binding=dict(binding))
        self.assertFalse(retry_created)
        self.assertEqual(retry["user_message"], request["user_message"])
        completed, _events, provider = self.run_v5_prompt(
            request["request_id"], json.dumps({
                "intent_id": "variable_limit_close",
                "assistant_text": (
                    "Belirleyici değişkeni güvenle ayıramadığım için "
                    "çalışmayı derinleştirmeden burada bırakıyorum."),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        path = self.row(
            "SELECT status,stage,step FROM schema_paths WHERE id=?",
            (path_id,))
        self.assertEqual((path["status"], path["stage"], path["step"]),
                         ("completed", "complete", "complete"))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_variable_trials WHERE path=?",
            (path_id,))["n"], 4)

    def test_v5_counterfactual_requires_exact_grounded_quote(self):
        state, _pairs = self.start_v5_ready("v5-grounding-negative")
        path_id = state["active_path"]["id"]
        binding = dict(state["next_card"]["chat_binding"])
        request_id = self.request_id("v5-forged-grounding")
        request, created = app.begin_chat_request(
            self.conv, "Toplantıda sözüm kesildi.", request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        before_revision = state["active_path"]["revision"]
        before_checkpoints = self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"]
        result, events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "Yöneticim bana bağırdı",
                "changed_attribute": "response_style",
                "changed_value": "listening",
                "assistant_text": (
                    "Eğer karşındaki kişi seni dinleseydi, bu durum nasıl "
                    "değişirdi?"),
            }, ensure_ascii=False))

        provider.assert_called_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"],
                         "schema_prompt_grounding_invalid")
        self.assertIsNone(result["assistant_message_id"])
        self.assertFalse(any(event.get("type") in ("delta", "replace")
                             for event in events))
        self.assertEqual(self.row(
            "SELECT revision FROM schema_paths WHERE id=?", (path_id,)
        )["revision"], before_revision)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], before_checkpoints)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_variable_trials WHERE path=?",
            (path_id,))["n"], 0)

    def test_v5_origin_ambiguous_age_reasks_without_origin_fact(self):
        state = self.v5_origin_ready("v5-age-ambiguous")
        path_id = state["active_path"]["id"]
        old_checkpoint = dict(state["next_card"]["checkpoint"])
        result, state, _request, _events, provider = self.complete_v5_turn(
            "Çok küçüktüm ama yaşımı bilmiyorum.", {
                "intent_id": "origin_age",
                "assistant_text": (
                    "O zamanki yaşınla ilgili hatırladığın bir şey var mı?"),
            }, "v5-age-ambiguous-answer")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["step"], "origin_sequence")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "age")

    def test_v5_missing_origin_predecessor_rejects_before_provider_or_user_row(self):
        state = self.v5_need_ready("v5-origin-lineage-gap")
        path_id = state["active_path"]["id"]
        binding = dict(state["next_card"]["chat_binding"])
        with app.db() as connection:
            connection.execute(
                "DELETE FROM schema_origin_answers WHERE path=? AND "
                "field='place' AND status IN ('active','unknown')",
                (path_id,))
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?", (self.conv,)
        )["n"]
        with self.assertRaises(app.RequestInputError) as caught:
            app.begin_chat_request(
                self.conv, "Beni görmelerine ihtiyacım vardı.",
                request_id=self.request_id("v5-origin-lineage-reject"),
                schema_binding=binding)
        self.assertEqual(caught.exception.error_code,
                         "schema_source_invalid")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?", (self.conv,)
        )["n"], before_messages)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))["n"], 0)

    def test_v5_server_rule_chair_mapping_is_stable_and_never_reparenting(self):
        state, _pairs = self.start_v5_ready("v5-chair-mapping")
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET focus_mode_key='punitive_parent' "
                "WHERE id=?", (path_id,))
        self.complete_v5_turn(
            "Eleştirildiğim anda sesimi çıkaramayıp uzaklaşıyorum.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "Eleştirildiğim anda",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı eleştirmek yerine "
                    "dinlemek olsaydı, deneyimin nasıl değişirdi?"),
            }, "v5-chair-scenario")
        result, state, _request, _events, provider = self.complete_v5_turn(
            "Daha az zorlanır ve daha güvende hissederdim.", {
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için sandalye diyaloğunu kullanacağım; o "
                    "zamanki yaşına dair ne hatırlıyorsun?"),
            }, "v5-chair-effect")

        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["active_path"]["method_id"],
                         "young:method:chair-dialogue")
        choice = self.row(
            "SELECT method_node_id,status,authored_by FROM "
            "schema_path_method_choices WHERE path=?", (path_id,))
        self.assertEqual(choice["method_node_id"],
                         "young:method:chair-dialogue")
        self.assertNotEqual(choice["method_node_id"],
                            app.REPARENTING_METHOD_NODE_ID)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_v5_method_explanation_cannot_ask_for_approval(self):
        state, _pairs = self.start_v5_ready("v5-method-no-approval")
        path_id = state["active_path"]["id"]
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi ve geri çekildim.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı seni dinlemek "
                    "olsaydı, bu an nasıl değişirdi?"),
            }, "v5-method-no-approval-scenario")
        binding = dict(self.dashboard()["next_card"]["chat_binding"])
        request_id = self.request_id("v5-method-approval-forged")
        request, created = app.begin_chat_request(
            self.conv, "Daha az gerilirdim.", request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        result, events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "İmgeleme ile yeniden senaryolamayı çalışalım mı; o "
                    "zamanki yaşın kaçtı?"),
            }, ensure_ascii=False))

        provider.assert_called_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"],
                         "schema_prompt_intent_mismatch")
        self.assertIsNone(result["assistant_message_id"])
        self.assertFalse(any(event.get("type") in ("delta", "replace")
                             for event in events))
        path = self.row(
            "SELECT * FROM schema_paths WHERE id=?", (path_id,))
        self.assertEqual(path["step"], "variable_explore")
        self.assertEqual(path["method_node_id"], "")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices WHERE path=?",
            (path_id,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_v5_effect_parser_is_fail_closed_for_negation_and_uncertainty(self):
        unclear = (
            "Daha güvende hissetmezdim.", "Kolaylaşmazdı.",
            "Daha az gerilmezdim.", "Daha çok zorlanmazdım.",
            "Hiçbir şekilde rahatlar mıydım, sanmıyorum.",
            "Daha az olmazdı.", "Daha az değil.", "Aynı kalmazdı.",
            "Aynı kalmayacaktı.", "Değişmez değil.",
            "Aynı kalırdı ama daha çok zorlaşırdı.",
            "Net değil ama daha az olurdu.",
            "Sanırım daha az olurdu.",
            "Kararsızım ama daha az olurdu.",
            "Daha çok olmazdı.", "Daha yoğun olmazdı.",
            "Daha güvende değildim.",
            "Daha az olacağını düşünmüyorum.",
            "Daha az olacağını sanmam.",
            "Daha az olacağını söyleyemem.",
            "Daha az olacağı şüpheli.",
            "Daha az olacağına ihtimal vermiyorum.",
            "Emin olamadım ama daha az olurdu.",
            "Belirsiz ama daha az olurdu.",
            "Muhtemelen daha az olurdu.",
            "Herhalde daha az olurdu.",
            "Daha az gibi değil.",
            "Fark etmez değil.", "Etkilemez değildi.",
        )
        for text in unclear:
            with self.subTest(text=text):
                self.assertEqual(app._schema_v5_explicit_effect(text),
                                 "unclear")
        self.assertEqual(app._schema_v5_explicit_effect(
            "Daha az gerilirdim."), "decrease")
        self.assertEqual(app._schema_v5_explicit_effect(
            "Hiçbir şey değişmezdi."), "no_change")
        self.assertEqual(app._schema_v5_explicit_effect(
            "Daha az gerilir ve kendimi daha güvende hissederdim."),
            "decrease")

    def test_v5_grounding_requires_affirmative_present_observation(self):
        for text in (
                "Şimdi nerede olduğumu bilmiyorum.",
                "Buradayım diyemem.", "Pencereyi görmüyorum.",
                "Kapı yok.", "Etrafımda hiçbir şey seçemiyorum.",
                "Odadayım ama çevrem gerçek değil."):
            with self.subTest(text=text):
                self.assertFalse(app._schema_v5_grounding_explicit(text))
        self.assertTrue(app._schema_v5_grounding_explicit(
            "Şimdi odadayım ve pencereyi görüyorum."))

    def test_v5_counterfactual_hidden_quote_is_exact_contiguous_source_text(self):
        plan = {
            "intent_id": "variable_counterfactual",
            "category": "other_person_behavior",
            "next_category": "other_person_behavior",
            "grounding_text": "Toplantıda müdürüm sesini yükseltti.",
            "changed_attribute": "response_style",
            "changed_value": "listening",
            "delta_phrase": "karşındaki kişi seni dinleseydi",
        }
        base = {
            "intent_id": "variable_counterfactual",
            "category": "other_person_behavior",
            "changed_attribute": "response_style",
            "changed_value": "listening",
            "assistant_text": (
                "Eğer karşındaki kişi seni dinleseydi, bu an nasıl değişirdi?"),
        }
        for quote in (
                "müdürüm sesini çocukken bağırdı",
                "Toplantıda müdürüm çocukken bağırdı"):
            with self.subTest(quote=quote):
                envelope = dict(base, grounded_quote=quote)
                with self.assertRaises(app.ProviderError) as caught:
                    app.validate_schema_v5_prompt_output(
                        plan, json.dumps(envelope, ensure_ascii=False))
                self.assertEqual(caught.exception.code,
                                 "schema_prompt_grounding_invalid")
        for quote in (
                "müdürüm sesini",
                "Toplantıda müdürüm sesini yükseltti"):
            with self.subTest(quote=quote):
                envelope = dict(base, grounded_quote=quote)
                self.assertTrue(app.validate_schema_v5_prompt_output(
                    plan, json.dumps(envelope, ensure_ascii=False)))

    def test_v5_provider_contract_rejects_invention_ratings_and_approval(self):
        counter_plan = {
            "intent_id": "variable_counterfactual",
            "category": "other_person_behavior",
            "grounding_text": "Toplantıda müdürüm sözümü kesti.",
            "changed_attribute": "response_style",
            "changed_value": "listening",
            "delta_phrase": "karşındaki kişi seni dinleseydi",
        }
        counter_base = {
            "intent_id": "variable_counterfactual",
            "category": "other_person_behavior",
            "grounded_quote": "sözümü kesti",
            "changed_attribute": "response_style",
            "changed_value": "listening",
        }
        bad_counterfactuals = (
            "Eğer narsist olan müdürünün davranışı seni dinleseydi, bu an "
            "nasıl değişirdi?",
            "Eğer karşındaki kişi sakin, nazik ve destekleyen biri olsaydı, "
            "bu an nasıl değişirdi?",
            "Eğer karşındaki kişi seni dinleseydi ve yer daha sakin olsaydı, "
            "bu an nasıl değişirdi?",
            "Eğer karşındaki kişi seni çocukluğundaki gibi tehdit etmeseydi, "
            "bu an nasıl değişirdi?",
        )
        for text in bad_counterfactuals:
            with self.subTest(text=text), self.assertRaises(app.ProviderError):
                app.validate_schema_v5_prompt_output(
                    counter_plan, json.dumps({
                        **counter_base, "assistant_text": text,
                    }, ensure_ascii=False), counter_plan["grounding_text"])

        bad = (
            ({"intent_id": "origin_place"},
             "8 yaşındaydım.",
             "Annen yanındaydı ve sekiz yaşındaydın; orası nerede?"),
            ({"intent_id": "origin_event_response",
              "output_prompt_key": "what"},
             "Mutfaktaydım.",
             "Baban sana bağırdıktan sonra orada ne oldu?"),
            ({"intent_id": "origin_unmet_need"},
             "Sessiz kaldım.",
             "Kesinlikle korunmaya ihtiyacın vardı; başka neye ihtiyaç "
             "duydun?"),
            ({"intent_id": "healthy_adult_voice"},
             "Şimdi odadayım.",
             "İncinmiş çocuğun terk edildi; Sağlıklı Yetişkinin ona ne "
             "söyler?"),
            ({"intent_id": "age_ladder"},
             "Sana inanıyorum.",
             "Sekiz yaşındaki halin çaresizdi; bugünkü imkânlarınla fark ne?"),
            ({"intent_id": "grounding"},
             "Biraz zor geldi.",
             "Şimdi çevrene bakınca yoğunluğun hangi seviyede?"),
            ({"intent_id": "origin_age"},
             "Çok küçüktüm.",
             "Yoğunluğunu sıfırdan ona kadar bir sayıyla söyler misin?"),
            ({"intent_id": "method_explain_origin_age",
              "method_id": app.IMAGERY_METHOD_NODE_ID},
             "Daha az gerilirdim.",
             "Bu örüntü için imgeleme ile yeniden senaryolamayı "
             "kullanacağım; bunu kabul edip yaşını söyler misin?"),
            ({"intent_id": "variable_scenario"},
             "Evet.", "Bunu bugün çalışmak ister misin?"),
            ({"intent_id": "method_explain_origin_age",
              "method_id": app.IMAGERY_METHOD_NODE_ID},
             "Daha az gerilirdim.",
             "Bu örüntü için imgeleme ile yeniden senaryolamayı "
             "kullanacağım; çalışmayla gerçeği ayırabildiğini ve uykunun "
             "uygun olduğunu söyler misin?"),
        )
        for plan, source, text in bad:
            with self.subTest(text=text), self.assertRaises(app.ProviderError):
                app.validate_schema_v5_prompt_output(
                    plan, json.dumps({
                        "intent_id": plan["intent_id"],
                        "assistant_text": text,
                    }, ensure_ascii=False), source)

    def test_v5_stale_real_question_binding_rejects_before_user_row(self):
        state, _pairs = self.start_v5_ready("v5-stale-question")
        stale = dict(state["next_card"]["chat_binding"])
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": (
                    "Eğer karşındaki kişinin davranışı seni dinlemek "
                    "olsaydı, bu an nasıl değişirdi?"),
            }, "v5-stale-question-advance")
        before = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with mock.patch.object(app, "open_provider_url") as provider:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Eski soruya geç yanıt.",
                    request_id=self.request_id("v5-stale-question-post"),
                    schema_binding=stale)
        provider.assert_not_called()
        self.assertEqual(rejected.exception.error_code,
                         "stale_schema_revision")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before)

    def test_v5_typed_pause_and_bare_bitir_are_provider_free_without_fake_bubble(self):
        state, _pairs = self.start_v5_ready("v5-local-controls")
        path_id = state["active_path"]["id"]
        binding = dict(state["next_card"]["chat_binding"])
        before_assistants = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"]
        pause_id = self.request_id("v5-local-pause")
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("provider must not be read")), \
                mock.patch.object(
                    app, "_configured_model_snapshot",
                    side_effect=AssertionError("model must not be read")), \
                mock.patch.object(app, "open_provider_url") as provider_call:
            paused, created = app.begin_chat_request(
                self.conv, "Dur", request_id=pause_id,
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertEqual(paused["status"], "completed")
        self.assertIsNone(paused["assistant_message"])
        result = json.loads(paused["schema_binding_result_json"])
        self.assertEqual(result["action"], "pause")
        self.assertFalse(result["provider_called"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"], before_assistants)
        paused_state = self.dashboard()
        self.assertEqual(paused_state["active_path"]["status"], "paused")
        self.assertEqual(paused_state["next_card"]["body"], "")
        self.assertEqual(paused_state["next_card"]["actions"], [])
        self.assertIsInstance(
            paused_state["next_card"]["chat_binding"], dict)
        self.assertTrue(paused_state["interaction_policy"]["composer_allowed"])
        retry, retry_created = app.begin_chat_request(
            self.conv, "Dur", request_id=pause_id, schema_binding=binding)
        self.assertFalse(retry_created)
        self.assertEqual(retry["user_message"], paused["user_message"])

        stop_binding = dict(paused_state["next_card"]["chat_binding"])
        with mock.patch.object(app, "open_provider_url") as provider_call:
            stopped, created = app.begin_chat_request(
                self.conv, "Bitir", request_id=self.request_id(
                    "v5-local-stop"), schema_binding=stop_binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertIsNone(stopped["assistant_message"])
        self.assertEqual(json.loads(
            stopped["schema_binding_result_json"])["action"], "stop")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"], before_assistants)

    def test_v5_typed_back_is_provider_free_and_keeps_append_only_target(self):
        self.start_v5_ready("v5-local-back")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Toplantıda sözüm kesildi.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": "ignored by helper",
            }, "v5-local-back-advance")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        binding = dict(state["next_card"]["chat_binding"])
        before_assistants = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"]
        before_checkpoints = self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"]
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("provider must not be read")), \
                mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "Geri dön",
                request_id=self.request_id("v5-local-back-command"),
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertIsNone(row["assistant_message"])
        result = json.loads(row["schema_binding_result_json"])
        self.assertEqual(result["action"], "backtrack_grounding_required")
        self.assertTrue(result["backtracked"])
        checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC,id DESC LIMIT 1", (path_id,))
        self.assertEqual(checkpoint["status"], "paused")
        self.assertIsNotNone(checkpoint["pending_backtrack"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], before_checkpoints)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"], before_assistants)

    def test_v5_back_from_origin_replays_driver_as_new_exact_trial(self):
        state = self.v5_origin_ready("v5-back-driver-replay")
        path_id = state["active_path"]["id"]
        driver_before = self.row(
            "SELECT * FROM schema_variable_trials WHERE path=? AND "
            "status='driver'", (path_id,))
        choice_before = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=? AND "
            "status='selected'", (path_id,))
        binding = dict(state["next_card"]["chat_binding"])
        before_assistants = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"]
        back_id = self.request_id("v5-back-driver-control")
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("back must be provider-free")), \
                mock.patch.object(app, "open_provider_url") as transport:
            back, created = app.begin_chat_request(
                self.conv, "Geri dön", request_id=back_id,
                schema_binding=binding)
            transport.assert_not_called()
        self.assertTrue(created)
        self.assertIsNone(back["assistant_message"])
        retry, retry_created = app.begin_chat_request(
            self.conv, "Geri dön", request_id=back_id,
            schema_binding=binding)
        self.assertFalse(retry_created)
        self.assertEqual(retry["user_message"], back["user_message"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"], before_assistants)

        paused = self.dashboard()
        paused_checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
            "status='paused'", (path_id,))
        target = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE id=?",
            (paused_checkpoint["pending_backtrack"],))
        self.assertEqual(
            (target["stage"], target["step"], target["prompt_key"]),
            ("explore", "variable_explore", "hypothetical_response"))

        resume_id = self.request_id("v5-back-driver-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(paused["next_card"]["chat_binding"]))
        self.assertTrue(created)
        plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual(plan["intent_id"], "variable_response_clarify")
        self.assertEqual(plan["replay_trial_public_id"],
                         driver_before["public_id"])
        self.assertEqual(plan["pending_target_checkpoint_id"], target["id"])
        completed, _events, provider = self.run_v5_prompt(
            resume_id, json.dumps({
                "intent_id": "variable_response_clarify",
                "assistant_text": (
                    "Bu varsayımsal değişiklik deneyimini nasıl etkilerdi?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        replay = self.row(
            "SELECT * FROM schema_variable_trials WHERE prompt_request_id=?",
            (resume_id,))
        self.assertNotEqual(replay["public_id"], driver_before["public_id"])
        self.assertEqual((replay["status"], replay["category"],
                          replay["hypothetical_anchor"]),
                         ("asked", driver_before["category"],
                          driver_before["hypothetical_anchor"]))
        self.assertEqual((replay["question_user_message"],
                          replay["question_assistant_message"]),
                         (request["user_message"],
                          completed["assistant_message_id"]))
        current_checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
            "status='active'", (path_id,))
        self.assertEqual((current_checkpoint["prompt_request_id"],
                          current_checkpoint["revisit_of"]),
                         (resume_id, target["id"]))
        driver_after_replay = self.row(
            "SELECT status,effect,evidence_quote FROM "
            "schema_variable_trials WHERE id=?", (driver_before["id"],))
        self.assertEqual(
            (driver_after_replay["status"], driver_after_replay["effect"],
             driver_after_replay["evidence_quote"]),
            (driver_before["status"], driver_before["effect"],
             driver_before["evidence_quote"]))
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_method_choices WHERE id=?",
            (choice_before["id"],))["status"], "superseded")
        self.assertEqual(self.row(
            "SELECT method_node_id FROM schema_paths WHERE id=?",
            (path_id,))["method_node_id"], "")

        result, origin, _request, _events, provider = self.complete_v5_turn(
            "Daha az gerilirdim.", {
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için imgeleme ile yeniden senaryolamayı "
                    "kullanacağım; o zamanki yaşını hatırlıyor musun?"),
            }, "v5-back-driver-answer")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((origin["stage"], origin["step"]),
                         ("origin", "origin_sequence"))
        self.assertEqual(self.row(
            "SELECT status FROM schema_variable_trials WHERE id=?",
            (driver_before["id"],))["status"], "driver")
        self.assertEqual(self.row(
            "SELECT status FROM schema_variable_trials WHERE id=?",
            (replay["id"],))["status"], "driver")

    def test_v5_back_replay_pins_selected_old_trial_not_latest_asked(self):
        self.start_v5_ready("v5-back-old-trial")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": "ignored by helper",
            }, "v5-back-old-trial-scenario")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Aynı kalırdı.", {
                "intent_id": "variable_counterfactual",
                "category": "place", "grounded_quote": "Toplantıda",
                "assistant_text": "ignored by helper",
            }, "v5-back-old-trial-second")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        first, second = self.rows(
            "SELECT * FROM schema_variable_trials WHERE path=? "
            "ORDER BY seq,id", (path_id,))
        self.assertEqual((first["status"], second["status"]),
                         ("no_change", "asked"))
        app.begin_chat_request(
            self.conv, "Geri dön",
            request_id=self.request_id("v5-back-old-trial-control"),
            schema_binding=dict(state["next_card"]["chat_binding"]))
        paused = self.dashboard()
        resume_id = self.request_id("v5-back-old-trial-devam")
        resume, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(paused["next_card"]["chat_binding"]))
        self.assertTrue(created)
        self.assertEqual(json.loads(resume["schema_prompt_plan_json"])[
            "replay_trial_public_id"], first["public_id"])
        self.run_v5_prompt(resume_id, json.dumps({
            "intent_id": "variable_response_clarify",
            "assistant_text": (
                "Bu varsayımsal değişiklik deneyimini nasıl etkilerdi?"),
        }, ensure_ascii=False))
        replay = self.row(
            "SELECT * FROM schema_variable_trials WHERE prompt_request_id=?",
            (resume_id,))
        self.assertEqual((replay["status"], replay["category"]),
                         ("asked", first["category"]))
        self.assertEqual(self.row(
            "SELECT status FROM schema_variable_trials WHERE id=?",
            (second["id"],))["status"], "invalidated")
        binding = dict(self.dashboard()["next_card"]["chat_binding"])
        request_ids = (
            self.request_id("v5-back-old-trial-answer-a"),
            self.request_id("v5-back-old-trial-answer-b"))

        def submit(request_id):
            try:
                return app.begin_chat_request(
                    self.conv, "Daha az gerilirdim.",
                    request_id=request_id, schema_binding=dict(binding))
            except app.RequestInputError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, request_ids))
        accepted = [item for item in outcomes if isinstance(item, tuple)]
        rejected = [item for item in outcomes
                    if isinstance(item, app.RequestInputError)]
        self.assertEqual((len(accepted), len(rejected)), (1, 1))
        request, created = accepted[0]
        self.assertTrue(created)
        answer_plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual(answer_plan["trial_public_id"], replay["public_id"])
        self.assertEqual(answer_plan["trial_seq"], replay["seq"])
        retry, retry_created = app.begin_chat_request(
            self.conv, "Daha az gerilirdim.",
            request_id=request["request_id"], schema_binding=binding)
        self.assertFalse(retry_created)
        self.assertEqual(retry["user_message"], request["user_message"])
        completed, _events, provider = self.run_v5_prompt(
            request["request_id"], json.dumps({
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için imgeleme ile yeniden senaryolamayı "
                    "kullanacağım; o zamanki yaşını hatırlıyor musun?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.row(
            "SELECT status FROM schema_variable_trials WHERE id=?",
            (replay["id"],))["status"], "driver")

    def test_v5_back_replay_source_and_safety_fail_before_new_turn(self):
        for reason in ("source", "safety"):
            with self.subTest(reason=reason):
                if reason == "safety":
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                state = self.v5_origin_ready(
                    "v5-back-replay-gate-{}".format(reason))
                path_id = state["active_path"]["id"]
                app.begin_chat_request(
                    self.conv, "Geri dön", request_id=self.request_id(
                        "v5-back-replay-gate-control-{}".format(reason)),
                    schema_binding=dict(state["next_card"]["chat_binding"]))
                paused = self.dashboard()
                checkpoint = self.row(
                    "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
                    "status='paused'", (path_id,))
                target = self.row(
                    "SELECT * FROM schema_path_checkpoints WHERE id=?",
                    (checkpoint["pending_backtrack"],))
                if reason == "source":
                    with app.db() as connection:
                        connection.execute(
                            "UPDATE chat_requests SET status='failed' "
                            "WHERE assistant_message=?",
                            (target["anchor_assistant_message"],))
                    expected = "schema_source_invalid"
                else:
                    with app.db() as connection:
                        connection.execute(
                            "UPDATE conversations SET safety_hold=1 "
                            "WHERE id=?", (self.conv,))
                    expected = "schema_safety_pause"
                before = self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                    (self.conv,))["n"]
                with mock.patch.object(
                        app, "open_provider_url") as provider, \
                        self.assertRaises(app.RequestInputError) as caught:
                    app.begin_chat_request(
                        self.conv, "Devam", request_id=self.request_id(
                            "v5-back-replay-gate-devam-{}".format(reason)),
                        schema_binding=dict(
                            paused["next_card"]["chat_binding"]))
                provider.assert_not_called()
                self.assertEqual(caught.exception.error_code, expected)
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                    (self.conv,))["n"], before)

    def test_v5_fourth_driver_cannot_be_replayed_past_variable_limit(self):
        self.start_v5_ready("v5-back-limit")
        self.complete_v5_turn(
            "Toplantıda sözüm kesildi.", {
                "intent_id": "variable_counterfactual",
                "category": "other_person_behavior",
                "grounded_quote": "sözüm kesildi",
                "assistant_text": "ignored by helper",
            }, "v5-back-limit-scenario")
        state = None
        for index in range(3):
            _result, state, _request, _events, provider = \
                self.complete_v5_turn(
                    "Emin değilim.", {
                        "intent_id": "variable_response_clarify",
                        "assistant_text": (
                            "Bu varsayımsal değişiklik deneyimini nasıl "
                            "etkilerdi?"),
                    }, "v5-back-limit-clarify-{}".format(index))
            provider.assert_called_once()
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Daha az gerilirdim.", {
                "intent_id": "method_explain_origin_age",
                "assistant_text": (
                    "Bu örüntü için imgeleme ile yeniden senaryolamayı "
                    "kullanacağım; o zamanki yaşını hatırlıyor musun?"),
            }, "v5-back-limit-driver")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with self.assertRaises(app.RequestInputError) as caught, \
                mock.patch.object(
                    app, "selected_provider",
                    side_effect=AssertionError("back must be provider-free")):
            app.begin_chat_request(
                self.conv, "Geri dön",
                request_id=self.request_id("v5-back-limit-control"),
                schema_binding=dict(state["next_card"]["chat_binding"]))
        self.assertEqual(caught.exception.error_code,
                         "schema_backtrack_unavailable")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_variable_trials WHERE path=? "
            "AND status!='invalidated'", (path_id,))["n"], 4)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)

    def test_v5_devam_creates_one_real_provider_question_after_pause(self):
        state, _pairs = self.start_v5_ready("v5-devam")
        binding = dict(state["next_card"]["chat_binding"])
        paused, created = app.begin_chat_request(
            self.conv, "Dur", request_id=self.request_id("v5-devam-pause"),
            schema_binding=binding)
        self.assertTrue(created)
        self.assertIsNone(paused["assistant_message"])
        paused_state = self.dashboard()
        paused_checkpoint = dict(paused_state["next_card"]["checkpoint"])
        resume_binding = dict(paused_state["next_card"]["chat_binding"])
        before_assistants = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"]
        request_id = self.request_id("v5-devam-request")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=request_id,
            schema_binding=resume_binding)
        self.assertTrue(created)
        self.assertEqual(request["status"], "queued")
        self.assertEqual(request["schema_prompt_protocol"],
                         app.SCHEMA_PATH_V5_PROTOCOL)
        plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual(plan["plan_kind"], "resume_prompt")
        result, events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "En son yaşadığın somut bir anı kısaca anlatır mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["assistant_message_id"])
        self.assertEqual(len([
            event for event in events if event.get("type") == "replace"]), 1)
        resumed = self.dashboard()
        self.assertEqual(resumed["active_path"]["status"], "active")
        self.assertEqual(resumed["next_card"]["body"], "")
        self.assertEqual(
            resumed["next_card"]["chat_binding"][
                "prompt_assistant_message_id"],
            result["assistant_message_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"], before_assistants + 1)
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE public_id=?",
            (paused_checkpoint["public_id"],))["status"], "completed")
        self.assertEqual(resumed["next_card"]["checkpoint"][
            "status"], "active")

    def test_v5_sync_receiver_get_is_metadata_only_parallel_and_devam_is_real(self):
        fixture = self.prepare_v5_sync_receiver()

        with mock.patch.object(app, "provider_request") as provider, \
                mock.patch.object(app, "open_provider_url") as transport:
            with ThreadPoolExecutor(max_workers=4) as pool:
                states = list(pool.map(
                    lambda _index: app.schema_path_payload(self.conv),
                    range(8)))
            provider.assert_not_called()
            transport.assert_not_called()
        identities = {
            (state["revision"],
             state["next_card"]["checkpoint"]["public_id"],
             state["next_card"]["checkpoint"]["seq"])
            for state in states}
        self.assertEqual(len(identities), 1, identities)
        state = states[0]
        card = state["next_card"]
        self.assertEqual((state["stage"], state["step"]),
                         ("explore", "variable_explore"))
        self.assertEqual(state["active_path"]["status"], "paused")
        self.assertEqual(state["active_path"]["pause_reason"],
                         "sync_import_resume_required")
        self.assertEqual((card["title"], card["context_line"], card["body"]),
                         ("", "", ""))
        self.assertEqual((card["fields"], card["actions"]), ([], []))
        self.assertEqual(card["prompt_delivery"], {
            "request_id": None,
            "status": "imported_waiting",
            "prompt_assistant_message_id": None,
            "prompt_assistant_message_public_id": None,
            "error_code": None,
        })
        self.assertEqual(card["checkpoint"]["status"], "paused")
        self.assertFalse(card["checkpoint"]["can_backtrack"])
        binding = dict(card["chat_binding"])
        self.assertEqual(set(binding), {
            "protocol", "sync_import_control", "path_id",
            "path_public_id", "step_id", "expected_revision",
            "checkpoint_public_id", "expected_checkpoint_seq",
            "prompt_request_id", "prompt_assistant_message_id",
            "prompt_assistant_message_public_id", "source_user_message_id",
            "source_user_message_public_id", "source_assistant_message_id",
            "source_assistant_message_public_id",
        })
        self.assertTrue(binding["sync_import_control"])
        self.assertIsNone(binding["prompt_request_id"])
        self.assertIsNone(binding["prompt_assistant_message_id"])
        self.assertIsNone(binding["prompt_assistant_message_public_id"])
        self.assertEqual(binding["source_user_message_id"],
                         fixture["source_user_id"])
        self.assertEqual(binding["source_user_message_public_id"],
                         fixture["source_user_public_id"])
        self.assertEqual(binding["source_assistant_message_id"],
                         fixture["source_assistant_id"])
        self.assertEqual(binding["source_assistant_message_public_id"],
                         fixture["source_assistant_public_id"])
        policy = state["interaction_policy"]
        self.assertTrue(policy["composer_allowed"])
        self.assertEqual(policy["composer_mode"], "bound")
        self.assertEqual(policy["composer_surface"], "ordinary_chat")
        self.assertTrue(policy["composer_binding_required"])
        self.assertEqual(policy["reason"],
                         "prompt_delivery_imported_waiting")
        checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=?",
            (fixture["path_id"],))
        self.assertEqual((checkpoint["seq"], checkpoint["status"],
                          checkpoint["transition_kind"],
                          checkpoint["prompt_request_id"]),
                         (1, "paused", "import", ""))
        for table, key in (("messages", "messages"), ("jobs", "jobs"),
                           ("chat_requests", "requests")):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM {} WHERE conv=?".format(table),
                (self.conv,))["n"], fixture["counts"][key], table)
        with app.db() as connection:
            after_messages = [tuple(row) for row in connection.execute(
                "SELECT id,public_id,role,content,turn_pair_public_id,"
                "delivery_status FROM messages WHERE conv=? ORDER BY id",
                (self.conv,)).fetchall()]
        self.assertEqual(after_messages, fixture["message_snapshot"])

        # The imported binding is a control boundary, not authority for a
        # clinical answer or a nonexistent previous prompt delivery.
        with mock.patch.object(app, "provider_request") as provider, \
                mock.patch.object(app, "open_provider_url") as transport:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Toplantıda yalnız hissettim.",
                    request_id=self.request_id("v5-import-ordinary"),
                    schema_binding=binding)
            provider.assert_not_called()
            transport.assert_not_called()
        self.assertEqual(rejected.exception.status, 409)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], fixture["counts"]["messages"])

        request_id = self.request_id("v5-import-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        self.assertEqual(request["status"], "queued")
        self.assertEqual(request["reply_to"], fixture["source_assistant_id"])
        plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual((plan["plan_kind"], plan["intent_id"],
                          plan["output_prompt_key"]),
                         ("resume_prompt", "variable_scenario", "scenario"))
        self.assertIsNone(plan["source_prompt_request_id"])
        self.assertEqual(plan["sync_import_boundary"]["imported_stage"],
                         "explore")
        retry, retry_created = app.begin_chat_request(
            self.conv, "Devam", request_id=request_id,
            schema_binding=binding)
        self.assertFalse(retry_created)
        self.assertEqual(retry["user_message"], request["user_message"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], fixture["counts"]["messages"] + 1)
        completed, _events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "En son yaşadığın somut bir anı kısaca anlatır mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        resumed = self.dashboard()
        self.assertEqual(resumed["active_path"]["status"], "active")
        self.assertEqual(resumed["next_card"]["prompt_delivery"]["status"],
                         "completed")
        self.assertNotIn("sync_import_control",
                         resumed["next_card"]["chat_binding"])
        self.assertEqual(
            resumed["next_card"]["chat_binding"]
            ["prompt_assistant_message_id"],
            completed["assistant_message_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], fixture["counts"]["messages"] + 2)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
            (self.conv,))["n"], fixture["counts"]["jobs"] + 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
            (self.conv,))["n"], fixture["counts"]["requests"] + 1)

    def test_v5_sync_receiver_work_without_private_session_restarts_safely(self):
        fixture = self.prepare_v5_sync_receiver(
            "work", "imagery_work", app.IMAGERY_METHOD_NODE_ID)
        with mock.patch.object(app, "provider_request") as provider, \
                mock.patch.object(app, "open_provider_url") as transport:
            first = self.dashboard()
            second = self.dashboard()
            provider.assert_not_called()
            transport.assert_not_called()
        self.assertEqual(
            (first["revision"], first["next_card"]["checkpoint"]["public_id"]),
            (second["revision"],
             second["next_card"]["checkpoint"]["public_id"]))
        self.assertEqual((first["stage"], first["step"]),
                         ("explore", "variable_explore"))
        path = self.row(
            "SELECT * FROM schema_paths WHERE id=?", (fixture["path_id"],))
        self.assertEqual((path["status"], path["stage"], path["step"],
                          path["phase"], path["method_node_id"],
                          path["technique_run"]),
                         ("paused", "explore", "variable_explore",
                          "explore", "", None))
        step = self.row(
            "SELECT * FROM schema_path_steps WHERE path=? AND "
            "step='variable_explore'", (fixture["path_id"],))
        marker = json.loads(step["payload_json"])["sync_import_boundary"]
        self.assertEqual((marker["stage"], marker["step"],
                          marker["imported_stage"], marker["imported_step"],
                          marker["method_id"]),
                         ("explore", "variable_explore", "work",
                          "imagery_work", ""))
        self.assertEqual(first["next_card"]["checkpoint"]["prompt_key"],
                         "scenario")
        self.assertFalse(first["next_card"]["checkpoint"]["can_backtrack"])
        self.assertEqual(first["next_card"]["prompt_delivery"]["status"],
                         "imported_waiting")
        for table, key in (("messages", "messages"), ("jobs", "jobs"),
                           ("chat_requests", "requests")):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM {} WHERE conv=?".format(table),
                (self.conv,))["n"], fixture["counts"][key], table)
        for table in (
                "schema_v5_technique_sessions",
                "schema_v5_technique_turns", "schema_origin_answers",
                "schema_variable_trials", "schema_v5_integration_answers"):
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM {} WHERE path=?".format(table),
                (fixture["path_id"],))["n"], 0, table)

        # The local audit marker is deliberately absent from the shared step
        # projection.  Once refresh observes this safe restart, a second
        # refresh/export has a stable cursor and cannot re-emit it.
        with app.db() as connection:
            device_id = "d" * 32
            sync.initialize_sync(connection, device_id)
            sync.refresh_local_changes(connection, device_id)
            cursor = connection.execute(
                "SELECT COALESCE(MAX(cursor),0) AS n FROM sync_changes"
            ).fetchone()["n"]
            batch = sync.export_change_batch(
                connection, device_id, after_cursor=0)
            serialized = json.dumps(batch, ensure_ascii=False)
            self.assertNotIn("sync_import_boundary", serialized)
            self.assertNotIn("sync_import_restart_from", serialized)
            stable = sync.refresh_local_changes(connection, device_id)
            self.assertEqual((stable["added"], stable["updated"],
                              stable["deleted"]), (0, 0, 0))
            self.assertEqual(connection.execute(
                "SELECT COALESCE(MAX(cursor),0) AS n FROM sync_changes"
            ).fetchone()["n"], cursor)

        binding = dict(first["next_card"]["chat_binding"])
        request_id = self.request_id("v5-import-work-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=request_id,
            schema_binding=binding)
        self.assertTrue(created)
        plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual((plan["intent_id"], plan["output_prompt_key"]),
                         ("variable_scenario", "scenario"))
        self.assertEqual((plan["sync_import_boundary"]["imported_stage"],
                          plan["sync_import_boundary"]["imported_step"]),
                         ("work", "imagery_work"))
        completed, _events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "En son yaşadığın somut bir anı kısaca anlatır mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(completed["status"], "completed")
        resumed = self.dashboard()
        self.assertEqual((resumed["active_path"]["status"], resumed["stage"],
                          resumed["step"]),
                         ("active", "explore", "variable_explore"))

    def test_v5_sync_receiver_origin_and_integrate_resume_plan_matrix(self):
        cases = (
            ("origin", "origin_sequence", "origin_age", "age",
             "O zamanki yaşını hatırlıyor musun?"),
            ("integrate", "environment_rescript",
             "environment_rescript", "environment",
             "O çevrede farklı olmasını istediğin tek şey ne olurdu?"),
        )
        for index, (stage, step, intent, prompt_key, assistant_text) in \
                enumerate(cases):
            with self.subTest(stage=stage, step=step):
                if index:
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                fixture = self.prepare_v5_sync_receiver(
                    stage, step, app.IMAGERY_METHOD_NODE_ID)
                with mock.patch.object(app, "provider_request") as provider:
                    state = self.dashboard()
                    provider.assert_not_called()
                self.assertEqual(state["next_card"]["prompt_delivery"]
                                 ["status"], "imported_waiting")
                self.assertEqual(state["next_card"]["checkpoint"]
                                 ["prompt_key"], prompt_key)
                binding = dict(state["next_card"]["chat_binding"])
                request_id = self.request_id(
                    "v5-import-matrix-{}".format(step))
                request, created = app.begin_chat_request(
                    self.conv, "Devam", request_id=request_id,
                    schema_binding=binding)
                self.assertTrue(created)
                plan = json.loads(request["schema_prompt_plan_json"])
                self.assertEqual((plan["intent_id"],
                                  plan["output_prompt_key"]),
                                 (intent, prompt_key))
                self.assertEqual((plan["resume_stage"], plan["resume_step"]),
                                 (stage, step))
                completed, _events, provider = self.run_v5_prompt(
                    request_id, json.dumps({
                        "intent_id": intent,
                        "assistant_text": assistant_text,
                    }, ensure_ascii=False))
                provider.assert_called_once()
                self.assertEqual(completed["status"], "completed",
                                 dict(completed))
                resumed = self.dashboard()
                self.assertEqual((resumed["active_path"]["status"],
                                  resumed["stage"], resumed["step"]),
                                 ("active", stage, step))
                self.assertEqual(
                    resumed["next_card"]["chat_binding"]
                    ["prompt_assistant_message_id"],
                    completed["assistant_message_id"])
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM schema_path_method_choices "
                    "WHERE path=?", (fixture["path_id"],))["n"], 0)
                if stage == "integrate":
                    self.assertEqual(self.row(
                        "SELECT COUNT(*) AS n FROM schema_origin_answers "
                        "WHERE path=?", (fixture["path_id"],))["n"], 0)
                    self.assertEqual(self.row(
                        "SELECT COUNT(*) AS n FROM "
                        "schema_v5_technique_sessions WHERE path=?",
                        (fixture["path_id"],))["n"], 0)

    def test_v5_sync_receiver_source_safety_and_conflict_fail_closed(self):
        for index, gate in enumerate(("source", "safety", "conflict")):
            with self.subTest(gate=gate):
                if index:
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                fixture = self.prepare_v5_sync_receiver()
                with app.db() as connection:
                    if gate == "source":
                        connection.execute(
                            "UPDATE messages SET delivery_status='failed' "
                            "WHERE id=?",
                            (fixture["source_assistant_id"],))
                    elif gate == "safety":
                        connection.execute(
                            "UPDATE conversations SET safety_hold=1 "
                            "WHERE id=?", (self.conv,))
                    else:
                        path = connection.execute(
                            "SELECT public_id FROM schema_paths WHERE id=?",
                            (fixture["path_id"],)).fetchone()
                        connection.execute(
                            "INSERT INTO schema_path_sync_conflicts("
                            "public_id,conv,path_public_id,status,reason,"
                            "created,updated) VALUES(?,?,?,'open',"
                            "'receiver_fixture',?,?)",
                            (("b" if index == 2 else "c") * 32,
                             self.conv, path["public_id"], app.now(),
                             app.now()))
                with mock.patch.object(app, "provider_request") as provider, \
                        mock.patch.object(
                            app, "open_provider_url") as transport:
                    state = self.dashboard()
                    provider.assert_not_called()
                    transport.assert_not_called()
                path = self.row(
                    "SELECT * FROM schema_paths WHERE id=?",
                    (fixture["path_id"],))
                self.assertEqual(path["status"], "paused")
                self.assertEqual(path["pause_reason"], {
                    "source": "source_invalid",
                    "safety": "safety_hold",
                    "conflict": "sync_conflict",
                }[gate])
                self.assertIsNone(state["next_card"]["chat_binding"])
                self.assertEqual(state["next_card"]["prompt_delivery"]
                                 ["status"], "missing")
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM schema_path_checkpoints "
                    "WHERE path=?", (fixture["path_id"],))["n"], 0)
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
                    (self.conv,))["n"], fixture["counts"]["jobs"])
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
                    (self.conv,))["n"], fixture["counts"]["requests"])

    def test_v5_sync_receiver_only_allowlisted_local_controls_are_provider_free(self):
        cases = (
            ("Dur", "pause"),
            ("Şimdiye dön", "ground_chat_technique"),
            ("Bitir", "stop"),
        )
        for index, (text, action) in enumerate(cases):
            with self.subTest(action=action):
                if index:
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                fixture = self.prepare_v5_sync_receiver()
                binding = dict(self.dashboard()["next_card"]["chat_binding"])
                with mock.patch.object(
                        app, "selected_provider",
                        side_effect=AssertionError(
                            "local control must not read provider")), \
                        mock.patch.object(app, "provider_request") as provider, \
                        mock.patch.object(
                            app, "open_provider_url") as transport:
                    row, created = app.begin_chat_request(
                        self.conv, text,
                        request_id=self.request_id(
                            "v5-import-control-{}".format(action)),
                        schema_binding=binding)
                    provider.assert_not_called()
                    transport.assert_not_called()
                self.assertTrue(created)
                self.assertEqual((row["status"], row["provider"],
                                  row["model"], row["assistant_message"]),
                                 ("completed", "local-control",
                                  "fixed-response", None))
                result = json.loads(row["schema_binding_result_json"])
                self.assertEqual((result["action"],
                                  result["provider_called"]),
                                 (action, False))
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
                    "role='assistant'", (self.conv,))["n"], sum(
                        item[2] == "assistant"
                        for item in fixture["message_snapshot"]))

        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        fixture = self.prepare_v5_sync_receiver()
        binding = dict(self.dashboard()["next_card"]["chat_binding"])
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError(
                    "rejected back must not read provider")), \
                mock.patch.object(app, "provider_request") as provider:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Geri dön",
                    request_id=self.request_id("v5-import-back"),
                    schema_binding=binding)
            provider.assert_not_called()
        self.assertEqual(rejected.exception.status, 409)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], fixture["counts"]["messages"])

    def test_v5_imagery_work_is_chat_native_and_grounds_without_precheck_facts(self):
        state = self.v5_need_ready("v5-imagery-work")
        path_id = state["active_path"]["id"]
        result, state, request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-imagery-start")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((state["stage"], state["step"]),
                         ("work", "imagery_work"))
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "scene_boundary")
        session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))
        self.assertEqual(
            (session["method_node_id"], session["status"],
             session["current_stage"]),
            (app.IMAGERY_METHOD_NODE_ID, "active", "scene_boundary"))
        self.assertEqual(
            (session["source_user_message"],
             session["source_assistant_message"]),
            (request["user_message"], result["assistant_message_id"]))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE path=?",
            (path_id,))["n"], 0)

        turns = (
            ("Biraz uzaktan bakmak istiyorum.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu mesafeden sahnede ilk neyi fark ediyorsun?"),
            }, "notice"),
            ("Kapının yanında tek başıma durduğumu görüyorum.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Sağlıklı Yetişkinin hangi koruma ya da sınırı seçerdi?"),
            }, "protective_response"),
            ("Yanıma gelip beni oradan çıkarırdı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu koruma eklendiğinde şimdi ne biraz farklı geliyor?"),
            }, "meaning"),
            ("Artık yalnız olmadığım anlamına geliyor.", {
                "intent_id": "grounding",
                "assistant_text": (
                    "Şimdi bulunduğun odada çevrenden neyi fark ediyorsun?"),
            }, "grounding"),
        )
        for index, (user_text, envelope, expected_stage) in enumerate(turns):
            result, state, _request, events, provider = self.complete_v5_turn(
                user_text, envelope,
                "v5-imagery-stage-{}".format(index))
            provider.assert_called_once()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                state["next_card"]["checkpoint"]["prompt_key"],
                expected_stage)
            self.assertEqual(result["content"].count("?"), 1)
            self.assertEqual(len([
                event for event in events
                if event.get("type") == "replace"]), 1)

        old_grounding = dict(state["next_card"]["checkpoint"])
        result, state, _request, _events, provider = self.complete_v5_turn(
            "Bilmiyorum.", {
                "intent_id": "grounding",
                "assistant_text": (
                    "Şimdi bulunduğun yerde etrafından neyi seçebiliyorsun?"),
            }, "v5-grounding-clarify")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["step"], "imagery_work")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "grounding")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE public_id=?",
            (old_grounding["public_id"],))["status"], "clarification")

        result, state, _request, _events, provider = self.complete_v5_turn(
            "Şimdi odadayım ve pencereyi görüyorum.", {
                "intent_id": "healthy_adult_voice",
                "assistant_text": (
                    "Bugünkü Sağlıklı Yetişkin tarafın o zamanki sana ne "
                    "söylemek ister?"),
            }, "v5-grounding-complete")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((state["stage"], state["step"]),
                         ("integrate", "healthy_adult_voice"))
        session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))
        self.assertEqual(session["status"], "completed")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_turns "
            "WHERE session=?", (session["id"],))["n"], 6)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_v5_typed_ground_pauses_private_session_without_provider_or_ack(self):
        state = self.v5_need_ready("v5-typed-ground")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-typed-ground-start")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        binding = dict(state["next_card"]["chat_binding"])
        before_assistants = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"]
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("provider must not be read")), \
                mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "Şimdiye dön",
                request_id=self.request_id("v5-typed-ground-control"),
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertIsNone(row["assistant_message"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "paused")
        session = self.row(
            "SELECT status,current_stage FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))
        self.assertEqual((session["status"], session["current_stage"]),
                         ("paused", "grounding"))
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"], "paused")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=? AND "
            "role='assistant'", (self.conv,))["n"], before_assistants)

    def test_v5_ground_then_devam_uses_real_prompt_and_closes_without_integration(self):
        state = self.v5_need_ready("v5-ground-resume-close")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-ground-resume-start")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))
        ground_row, created = app.begin_chat_request(
            self.conv, "Şimdiye dön",
            request_id=self.request_id("v5-ground-resume-control"),
            schema_binding=dict(state["next_card"]["chat_binding"]))
        self.assertTrue(created)
        self.assertIsNone(ground_row["assistant_message"])
        paused = self.dashboard()
        resume_id = self.request_id("v5-ground-resume-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(paused["next_card"]["chat_binding"]))
        self.assertTrue(created)
        self.assertEqual(request["status"], "queued")
        resumed_row, _events, provider = self.run_v5_prompt(
            resume_id, json.dumps({
                "intent_id": "grounding",
                "assistant_text": (
                    "Şimdi bulunduğun yerde çevrende ne görüyorsun?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(resumed_row["status"], "completed")
        resumed = self.dashboard()
        self.assertEqual((resumed["stage"], resumed["step"]),
                         ("work", "imagery_work"))
        self.assertEqual(resumed["next_card"]["checkpoint"]["prompt_key"],
                         "grounding")
        result, closed, _request, _events, provider = self.complete_v5_turn(
            "Şimdi odadayım ve pencereyi görüyorum.", {
                "intent_id": "complete",
                "assistant_text": (
                    "Bugünkü çalışmayı burada güvenle kapatıyoruz."),
            }, "v5-ground-resume-finish")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(closed["active_path"])
        self.assertEqual(self.row(
            "SELECT stage,step,status FROM schema_paths WHERE id=?",
            (path_id,))["status"], "completed")
        self.assertEqual(self.row(
            "SELECT status FROM schema_v5_technique_sessions WHERE id=?",
            (session["id"],))["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_integration_answers "
            "WHERE path=?", (path_id,))["n"], 0)

    def test_v5_back_during_technique_grounds_then_revisits_safe_origin(self):
        state = self.v5_need_ready("v5-back-resume-origin")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-back-resume-start")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))
        back_row, created = app.begin_chat_request(
            self.conv, "Geri dön",
            request_id=self.request_id("v5-back-resume-control"),
            schema_binding=dict(state["next_card"]["chat_binding"]))
        self.assertTrue(created)
        self.assertIsNone(back_row["assistant_message"])
        paused = self.dashboard()
        paused_checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC,id DESC LIMIT 1", (path_id,))
        self.assertIsNotNone(paused_checkpoint["pending_backtrack"])
        resume_id = self.request_id("v5-back-resume-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(paused["next_card"]["chat_binding"]))
        self.assertTrue(created)
        resumed_row, _events, provider = self.run_v5_prompt(
            resume_id, json.dumps({
                "intent_id": "grounding",
                "assistant_text": (
                    "Şimdi bulunduğun yerde çevrende ne görüyorsun?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(resumed_row["status"], "completed")
        result, revisited, request, _events, provider = self.complete_v5_turn(
            "Şimdi odadayım ve pencereyi görüyorum.", {
                "intent_id": "origin_unmet_need",
                "assistant_text": "O anda en çok neye ihtiyaç duyardın?",
            }, "v5-back-resume-grounded")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        binding_result = json.loads(self.row(
            "SELECT schema_binding_result_json FROM chat_requests "
            "WHERE request_id=?", (request["request_id"],)
        )["schema_binding_result_json"])
        self.assertTrue(binding_result["backtracked"])
        self.assertEqual(binding_result["action"],
                         "backtrack_after_grounding")
        self.assertEqual((revisited["stage"], revisited["step"]),
                         ("origin", "origin_sequence"))
        self.assertEqual(revisited["next_card"]["checkpoint"]["prompt_key"],
                         "need")
        self.assertEqual(self.row(
            "SELECT status FROM schema_v5_technique_sessions WHERE id=?",
            (session["id"],))["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_integration_answers "
            "WHERE path=?", (path_id,))["n"], 0)

    def test_v5_back_after_completed_technique_skips_micro_prompt_and_restarts_at_need(self):
        state = self.v5_healthy_voice_ready("v5-back-completed-session")
        path_id = state["active_path"]["id"]
        completed_session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=? AND "
            "status='completed'", (path_id,))
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("back must be provider-free")), \
                mock.patch.object(app, "open_provider_url") as transport:
            row, created = app.begin_chat_request(
                self.conv, "Geri dön", request_id=self.request_id(
                    "v5-back-completed-control"),
                schema_binding=dict(state["next_card"]["chat_binding"]))
            transport.assert_not_called()
        self.assertTrue(created)
        self.assertIsNone(row["assistant_message"])
        paused = self.dashboard()
        paused_checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
            "status='paused'", (path_id,))
        target = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE id=?",
            (paused_checkpoint["pending_backtrack"],))
        self.assertEqual(
            (target["stage"], target["step"], target["prompt_key"]),
            ("origin", "origin_sequence", "need"))
        self.assertNotIn(target["step"], {
            "imagery_work", "mode_dialogue", "reparent_or_chair_work",
            "grounding_review",
        })

        resume_id = self.request_id("v5-back-completed-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(paused["next_card"]["chat_binding"]))
        self.assertTrue(created)
        plan = json.loads(request["schema_prompt_plan_json"])
        self.assertEqual((plan["resume_stage"], plan["resume_step"],
                          plan["output_prompt_key"], plan["intent_id"]),
                         ("origin", "origin_sequence", "need",
                          "origin_unmet_need"))
        self.assertFalse(plan.get("technique_session_public_id"))
        result, _events, provider = self.run_v5_prompt(
            resume_id, json.dumps({
                "intent_id": "origin_unmet_need",
                "assistant_text": "O anda en çok neye ihtiyaç duyardın?",
            }, ensure_ascii=False))
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        revisited = self.dashboard()
        self.assertEqual((revisited["stage"], revisited["step"],
                          revisited["next_card"]["checkpoint"]["prompt_key"]),
                         ("origin", "origin_sequence", "need"))
        active_checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? AND "
            "status='active'", (path_id,))
        self.assertEqual(active_checkpoint["revisit_of"], target["id"])

        result, work, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun "
                    "gelir?"),
            }, "v5-back-completed-need")
        provider.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual((work["stage"], work["step"]),
                         ("work", "imagery_work"))
        sessions = self.rows(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=? "
            "ORDER BY seq,id", (path_id,))
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["id"], completed_session["id"])
        self.assertEqual((sessions[0]["status"], sessions[1]["status"]),
                         ("completed", "active"))
        self.assertNotEqual(sessions[0]["public_id"],
                            sessions[1]["public_id"])

    def test_v5_mode_off_and_archive_pause_session_checkpoint_and_pending_prompt(self):
        state = self.v5_need_ready("v5-lifecycle-pause")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-lifecycle-start")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        app.set_schema_mode(self.conv, False)
        self.assertEqual(self.row(
            "SELECT status,pause_reason FROM schema_paths WHERE id=?",
            (path_id,))["status"], "paused")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"], "paused")
        session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))
        self.assertEqual((session["status"], session["current_stage"]),
                         ("paused", "grounding"))
        app.set_schema_mode(self.conv, True)
        paused = self.dashboard()
        self.assertEqual(paused["next_card"]["body"], "")
        self.assertEqual(paused["next_card"]["actions"], [])
        resume_id = self.request_id("v5-lifecycle-devam")
        request, created = app.begin_chat_request(
            self.conv, "Devam", request_id=resume_id,
            schema_binding=dict(paused["next_card"]["chat_binding"]))
        self.assertTrue(created)
        self.assertEqual(request["status"], "queued")
        status, archived, _headers = self.request(
            "POST", "/api/archive", {"id": self.conv, "archived": True})
        self.assertEqual(status, 200, archived)
        self.assertTrue(archived["archived"])
        self.assertEqual(self.row(
            "SELECT status,error_code FROM chat_requests WHERE request_id=?",
            (resume_id,))["status"], "cancelled")
        self.assertEqual(self.row(
            "SELECT status FROM schema_v5_technique_sessions WHERE id=?",
            (session["id"],))["status"], "paused")
        status, restored, _headers = self.request(
            "POST", "/api/archive", {"id": self.conv, "archived": False})
        self.assertEqual(status, 200, restored)
        self.assertFalse(restored["archived"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "paused")

    def test_v5_safety_pause_still_allows_typed_stop_without_provider(self):
        state = self.v5_need_ready("v5-safety-stop")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-safety-stop-start")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv,))
            app.pause_schema_v4_for_safety(connection, self.conv)
        held = self.dashboard()
        self.assertEqual(held["active_path"]["status"], "paused")
        self.assertEqual(self.row(
            "SELECT status,current_stage FROM schema_v5_technique_sessions "
            "WHERE path=?", (path_id,))["status"], "paused")
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("provider must not be read")), \
                mock.patch.object(app, "open_provider_url") as provider_call:
            stopped, created = app.begin_chat_request(
                self.conv, "Bitir",
                request_id=self.request_id("v5-safety-stop-command"),
                schema_binding=dict(held["next_card"]["chat_binding"]))
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertIsNone(stopped["assistant_message"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT status FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"],
            "invalidated")

    def test_v5_session_end_stops_private_session_and_invalidates_checkpoint(self):
        state = self.v5_need_ready("v5-session-end")
        _result, state, _request, _events, provider = self.complete_v5_turn(
            "Görülmeye ve korunmaya ihtiyacım vardı.", {
                "intent_id": "imagery_stage",
                "assistant_text": (
                    "Bu küçük ana hangi mesafeden yaklaşmak sana uygun gelir?"),
            }, "v5-session-end-start")
        provider.assert_called_once()
        path_id = state["active_path"]["id"]
        with mock.patch.object(app, "start_job_worker"), \
                mock.patch.object(app, "enqueue_job"):
            status, ended, _headers = self.request(
                "POST", "/api/end", {"conv_id": self.conv})
        self.assertEqual(status, 200, ended)
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT status FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"],
            "invalidated")

    def test_v5_chair_work_uses_only_selected_branch_and_real_questions(self):
        state = self.v5_chair_need_ready("v5-chair-work")
        path_id = state["active_path"]["id"]
        turns = (
            ("Saygı görmeye ve kendimi savunmaya ihtiyacım vardı.", {
                "intent_id": "chair_stage",
                "assistant_text": (
                    "İncinmiş ya da eleştiren parça şimdi ne söylüyor?"),
            }, "parts_words"),
            ("Ne yapsam yeterli olmadığını söylüyor.", {
                "intent_id": "chair_stage",
                "assistant_text": (
                    "Sağlıklı Yetişkin tarafın bu sözlere nasıl yanıt verir?"),
            }, "healthy_adult_reply"),
            ("Bu sözün doğru olmadığını ve çabaladığımı söyler.", {
                "intent_id": "chair_stage",
                "assistant_text": (
                    "Burada seçmek istediğin tek sınır cümlesi ne olur?"),
            }, "boundary_choice"),
            ("Benimle aşağılayıcı biçimde konuşamazsın.", {
                "intent_id": "chair_stage",
                "assistant_text": (
                    "Bu sınır söylendiğinde şimdi ne biraz farklı geliyor?"),
            }, "meaning"),
            ("Kendimi daha az çaresiz hissediyorum.", {
                "intent_id": "grounding",
                "assistant_text": (
                    "Şimdi bulunduğun odada çevrenden neyi fark ediyorsun?"),
            }, "grounding"),
            ("Şimdi buradayım ve masayı görüyorum.", {
                "intent_id": "healthy_adult_voice",
                "assistant_text": (
                    "Bugünkü Sağlıklı Yetişkin tarafın o zamanki sana ne "
                    "söylemek ister?"),
            }, "voice"),
        )
        state = None
        for index, (user_text, envelope, prompt_key) in enumerate(turns):
            result, state, _request, events, provider = self.complete_v5_turn(
                user_text, envelope, "v5-chair-stage-{}".format(index))
            provider.assert_called_once()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(len([
                event for event in events if event.get("type") == "replace"
            ]), 1)
            self.assertEqual(result["content"].count("?"), 1)
            self.assertEqual(
                state["next_card"]["checkpoint"]["prompt_key"], prompt_key)
        self.assertEqual((state["stage"], state["step"]),
                         ("integrate", "healthy_adult_voice"))
        session = self.row(
            "SELECT * FROM schema_v5_technique_sessions WHERE path=?",
            (path_id,))
        self.assertEqual((session["method_node_id"], session["status"]),
                         ("young:method:chair-dialogue", "completed"))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_v5_technique_turns "
            "WHERE session=?", (session["id"],))["n"], 5)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE path=?",
            (path_id,))["n"], 0)

    def test_v5_integration_chain_is_durable_natural_and_closes(self):
        state = self.v5_healthy_voice_ready("v5-integration")
        path_id = state["active_path"]["id"]
        turns = (
            ("Sana inanıyorum; artık yanında ve seni koruyabilirim.", {
                "intent_id": "age_ladder",
                "assistant_text": (
                    "O zamanki halinle bugünkü imkânların arasındaki en "
                    "belirgin fark ne?"),
            }, "age_ladder", "age_integration"),
            ("Bugün uzaklaşabilir, yardım isteyebilir ve sınır koyabilirim.", {
                "intent_id": "environment_rescript",
                "assistant_text": (
                    "O çevrede farklı olmasını istediğin tek şey ne olurdu?"),
            }, "environment_rescript", "environment"),
            ("Yanımda beni dinleyen güvenilir bir yetişkin olmasını isterdim.", {
                "intent_id": "present_transfer",
                "assistant_text": (
                    "Bugün bu örüntünün belirdiği somut bir durum neydi?"),
            }, "present_transfer", "present_trigger"),
            ("Bu sabah toplantıda sözüm yeniden kesildi.", {
                "intent_id": "present_transfer",
                "assistant_text": (
                    "Sağlıklı Yetişkin tarafın bugün buna nasıl karşılık "
                    "vermek ister?"),
            }, "present_transfer", "present_response"),
            ("Sözümü bitirmek istediğimi sakin biçimde söylemek isterim.", {
                "intent_id": "optional_practice",
                "assistant_text": (
                    "İstersen bu hafta deneyebileceğin küçük adım ve sana "
                    "uygun doğal ritmi ne olur?"),
            }, "optional_practice", "practice"),
            ("Uygun bir toplantıda bir kez sözümü tamamlamayı deneyeceğim.", {
                "intent_id": "followup",
                "assistant_text": (
                    "Bu çalışmada sana ne yardım etti, ne zor geldi?"),
            }, "followup", "review"),
            ("Soruların kısa olması yardımcı oldu; sahne biraz zorladı.", {
                "intent_id": "complete",
                "assistant_text": "Bugünkü çalışmayı burada güvenle kapatıyoruz.",
            }, "complete", "closed"),
        )
        request_pairs = []
        for index, (user_text, envelope, expected_step,
                    expected_prompt) in enumerate(turns):
            result, state, request, events, provider = self.complete_v5_turn(
                user_text, envelope,
                "v5-integration-turn-{}".format(index))
            provider.assert_called_once()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(len([
                event for event in events if event.get("type") == "replace"
            ]), 1)
            request_pairs.append(
                (request["user_message"], result["assistant_message_id"]))
            path = self.row(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,))
            self.assertEqual(path["step"], expected_step)
            latest = self.row(
                "SELECT * FROM schema_path_checkpoints WHERE path=? "
                "ORDER BY seq DESC,id DESC LIMIT 1", (path_id,))
            self.assertEqual(latest["prompt_key"], expected_prompt)
            if expected_step == "complete":
                self.assertEqual(result["content"].count("?"), 0)
            else:
                self.assertEqual(result["content"].count("?"), 1)

        path = self.row("SELECT * FROM schema_paths WHERE id=?", (path_id,))
        self.assertEqual((path["stage"], path["step"], path["status"]),
                         ("complete", "complete", "completed"))
        self.assertEqual(path["practice_status"], "active")
        self.assertEqual(path["practice_json"], "{}")
        rows = self.rows(
            "SELECT * FROM schema_v5_integration_answers WHERE path=? "
            "ORDER BY seq", (path_id,))
        self.assertEqual([row["field"] for row in rows], [
            "healthy_voice", "age_integration", "environment",
            "present_trigger", "present_response", "practice", "followup",
        ])
        self.assertEqual([
            (row["source_user_message"], row["source_assistant_message"])
            for row in rows], request_pairs)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM healthy_adult_marks WHERE path=? "
            "AND status='active'", (path_id,))["n"], 1)
        growth = self.row(
            "SELECT * FROM schema_growth WHERE path=? AND status='active'",
            (path_id,))
        self.assertIn("yardım isteyebilir", growth["difference"])
        self.assertIn("güvenilir bir yetişkin",
                      growth["environment_rescripted"])
        transfer = self.row(
            "SELECT * FROM schema_transfer_records WHERE path=?",
            (path_id,))
        self.assertIn("toplantıda", transfer["trigger_text"])
        self.assertIn("Sözümü bitirmek", transfer["healthy_adult_response"])
        self.assertEqual(transfer["planned_action"], "")
        self.assertEqual(int(self.row(
            "SELECT precheck_done FROM session_meta WHERE conv=?",
            (self.conv,))["precheck_done"] or 0), 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE path=?",
            (path_id,))["n"], 0)

    def test_chat_only_candidate_no_advances_then_unlocks_listening(self):
        pairs = self.completed_pairs(3)
        self.approved_candidate(pairs[0])
        self.approved_candidate(pairs[1])
        first = self.dashboard()["next_card"]
        first_public = first["candidate"]["public_id"]
        no = first["actions"][1]
        request = {
            "action": no["action"], "conv_id": self.conv,
            "request_id": self.request_id("candidate-no"),
            **no["payload"],
        }
        status, state = self.post(request)
        self.assertEqual(status, 200, state)
        self.assertEqual(self.post(request), (200, state))
        second = state["next_card"]
        self.assertEqual(second["kind"], "candidate_prompt")
        self.assertNotEqual(second["candidate"]["public_id"], first_public)
        status, state = self.post_card_action(
            second, "reject_candidate_chat", "candidate-no-last")
        self.assertEqual(status, 200, state)
        self.assertIsNone(state["active_path"])
        self.assertIsNone(state["next_card"])
        self.assertEqual(
            state["interaction_policy"]["composer_mode"], "ordinary")
        self.assertTrue(state["interaction_policy"]["composer_allowed"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims WHERE source_conv=? "
            "AND status='rejected'", (self.conv,))["n"], 2)

    def test_delayed_candidate_accept_anchors_prompt_to_latest_safe_pair(self):
        pairs = self.completed_pairs(3)
        claim_id = self.approved_candidate(pairs[0])
        candidate_card = self.dashboard()["next_card"]
        self.assertEqual(
            candidate_card["source"]["assistant_message_id"],
            pairs[0]["assistant_message_id"])

        # The candidate stays pending while ordinary listening continues.
        # Accepting it creates a genuine user-authored Yes and a provider job;
        # it never reuses either the older evidence bubble or this intervening
        # ordinary assistant as a synthetic question anchor.
        latest = self.completed_pair(
            "Aday kartından sonra anlattığım yeni güvenli mesaj.",
            "Aday beklerken gelen en güncel gerçek Kerem yanıtı.")
        status, accepted = self.post_card_action(
            candidate_card, "accept_candidate_chat", "delayed-candidate")
        self.assertEqual(status, 200, accepted)
        prompt = accepted["next_card"]
        self.assertEqual(prompt["kind"], "chat_state")
        self.assertEqual(prompt["body"], "")
        self.assertEqual(prompt["actions"], [])
        self.assertIsNone(prompt["chat_binding"])
        self.assertEqual(prompt["prompt_delivery"]["status"], "queued")
        request_id = prompt["prompt_delivery"]["request_id"]
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?", (request_id,))
        completed, _events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "Bunu en son yaşadığın somut bir anı kısaca anlatır "
                    "mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        prompt = self.dashboard()["next_card"]
        self.assertEqual(prompt["prompt_delivery"]["status"], "completed")
        self.assertEqual(
            prompt["source"]["assistant_message_id"],
            completed["assistant_message_id"])
        self.assertEqual(
            prompt["source"]["assistant_message_public_id"],
            self.row("SELECT public_id FROM messages WHERE id=?", (
                completed["assistant_message_id"],))["public_id"])
        binding = prompt["chat_binding"]
        self.assertEqual(binding["source_user_message_id"],
                         request["user_message"])
        self.assertEqual(binding["source_assistant_message_id"],
                         completed["assistant_message_id"])
        self.assertNotEqual(binding["source_assistant_message_id"],
                            latest["assistant_message_id"])

        path_id = accepted["active_path"]["id"]
        step = self.row(
            "SELECT source_user_message,source_assistant_message "
            "FROM schema_path_steps WHERE path=? AND status='active'",
            (path_id,))
        self.assertEqual(
            (step["source_user_message"], step["source_assistant_message"]),
            (request["user_message"], completed["assistant_message_id"]))

        # Candidate evidence/focus lineage remains on the original exact
        # pair; only the conversational continuation anchor moves forward.
        queued = self.row(
            "SELECT claim,source_user_message,source_assistant_message "
            "FROM schema_candidate_queue WHERE path=? AND status='accepted'",
            (path_id,))
        self.assertEqual(queued["claim"], claim_id)
        self.assertEqual(
            (queued["source_user_message"],
             queued["source_assistant_message"]),
            (pairs[0]["user_message_id"],
             pairs[0]["assistant_message_id"]))
        meta = self.row(
            "SELECT source_user_message,source_assistant_message "
            "FROM message_meta_events WHERE path=? AND kind='candidate'",
            (path_id,))
        self.assertEqual(
            (meta["source_user_message"], meta["source_assistant_message"]),
            (pairs[0]["user_message_id"],
             pairs[0]["assistant_message_id"]))

    def test_reject_then_delayed_pending_candidate_accepts_and_reanchors(self):
        pairs = self.completed_pairs(3)
        shared = pairs[0]

        # Model analysis may emit more than one controlled hypothesis from
        # the same turn. The second one can remain pending until its own Yes.
        second_claim = self.approved_candidate(shared)
        second_schema = list(app.SCHEMA_CANDIDATE_CATALOG)[1]
        with app.db() as connection:
            connection.execute(
                "UPDATE psych_claims SET schema_key=?,reviewed_at=NULL,"
                "reviewed_evidence_id=0 WHERE id=?",
                (second_schema, second_claim))
            connection.execute(
                "UPDATE psych_claim_evidence SET review_status='pending' "
                "WHERE claim=?", (second_claim,))
            stamp = app.now()
            observation_id = connection.execute(
                "INSERT INTO psych_observations(conv,source_message,"
                "therapist,dimension,content,source_created,created) "
                "VALUES(?,?,'young','user_report_secondary',?,?,?)",
                (self.conv, shared["user_message_id"],
                 shared["user_content"], stamp, stamp)).lastrowid
            first_claim = connection.execute(
                "INSERT INTO psych_claims(public_id,source_conv,therapist,"
                "lens,claim_type,title,statement,trigger_text,experience_text,"
                "response_text,short_term_effect,long_term_effect,need_text,"
                "counterexample_text,status,scope,sensitive,first_seen,"
                "last_seen,schema_key,mode_key,source_assistant_message,"
                "created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?)",
                ("schema-v4-shared-{:08d}".format(observation_id),
                 self.conv, "young", "schema", "schema_hypothesis",
                 "İlk gösterilecek çalışma olasılığı",
                 "Aynı turdan gelen ayrı kontrollü olasılık.",
                 "Mesaj gecikince", "kaygı", "geri çekilme",
                 "kısa güvence", "ilişkide uzaklaşma", "güven",
                 "Bazen bekleyebiliyorum.", "confirmed", "therapist", 0,
                 stamp, stamp, next(iter(app.SCHEMA_CANDIDATE_CATALOG)), "",
                 shared["assistant_message_id"], stamp, stamp)).lastrowid
            evidence_id = connection.execute(
                "INSERT INTO psych_claim_evidence(claim,observation,relation,"
                "review_status,created) VALUES(?,?,'supports','accepted',?)",
                (first_claim, observation_id, stamp)).lastrowid
            connection.execute(
                "UPDATE psych_claims SET reviewed_at=?,"
                "reviewed_evidence_id=? WHERE id=?",
                (stamp, evidence_id, first_claim))

        first = self.dashboard()["next_card"]
        self.assertEqual(first["source"]["user_message_id"],
                         shared["user_message_id"])
        self.assertEqual(first["actions"][1]["action"],
                         "reject_candidate_chat")
        status, rejected = self.post_card_action(
            first, "reject_candidate_chat", "same-pair-first-no")
        self.assertEqual(status, 200, rejected)
        self.assertEqual(self.row(
            "SELECT status FROM psych_claims WHERE id=?", (first_claim,)
        )["status"], "rejected")

        second = rejected["next_card"]
        self.assertEqual(second["kind"], "candidate_prompt")
        self.assertEqual(second["source"]["user_message_id"],
                         shared["user_message_id"])
        self.assertEqual(second["candidate"]["schema_code"], second_schema)
        self.assertNotEqual(second["candidate"]["public_id"],
                            first["candidate"]["public_id"])

        latest = self.completed_pair(
            "İkinci aday görünürken gelen daha yeni güvenli anlatım.",
            "İkinci aday kabul edilmeden önceki en yeni gerçek Kerem yanıtı.")
        status, accepted = self.post_card_action(
            second, "accept_candidate_chat", "same-pair-second-yes")
        self.assertEqual(status, 200, accepted)
        self.assertEqual(accepted["step"], "variable_explore")
        prompt = accepted["next_card"]
        self.assertEqual(prompt["kind"], "chat_state")
        self.assertEqual(prompt["prompt_delivery"]["status"], "queued")
        request_id = prompt["prompt_delivery"]["request_id"]
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id=?", (request_id,))
        completed, _events, provider = self.run_v5_prompt(
            request_id, json.dumps({
                "intent_id": "variable_scenario",
                "assistant_text": (
                    "Bunu en son yaşadığın somut bir anı kısaca anlatır "
                    "mısın?"),
            }, ensure_ascii=False))
        provider.assert_called_once()
        prompt = self.dashboard()["next_card"]
        self.assertEqual(
            prompt["source"]["assistant_message_id"],
            completed["assistant_message_id"])
        self.assertEqual(
            prompt["chat_binding"]["source_user_message_id"],
            request["user_message"])
        self.assertNotEqual(
            prompt["chat_binding"]["source_assistant_message_id"],
            latest["assistant_message_id"])
        queued = self.row(
            "SELECT claim,source_user_message,source_assistant_message,status "
            "FROM schema_candidate_queue WHERE path=? AND status='accepted'",
            (accepted["active_path"]["id"],))
        self.assertEqual(queued["claim"], second_claim)
        self.assertEqual(
            (queued["source_user_message"],
             queued["source_assistant_message"]),
            (shared["user_message_id"], shared["assistant_message_id"]))
        self.assertEqual(self.row(
            "SELECT review_status FROM psych_claim_evidence WHERE claim=?",
            (second_claim,))["review_status"], "accepted")

    def test_chat_only_stage1_collects_explicit_text_without_forms(self):
        state, _pairs = self.start_chat_only_path()
        original_revision = state["revision"]
        original_checkpoint = dict(state["next_card"]["checkpoint"])
        result, state, _user, assistant = self.complete_chat_only_turn(
            "Oldukça ağır")
        self.assertFalse(result["applied"], result)
        self.assertTrue(result["followup_required"])
        self.assertEqual(result["missing"], ["burden"])
        self.assertEqual(state["step"], "current_impact")
        self.assertGreater(state["revision"], original_revision)
        self.assertEqual(
            state["next_card"]["source"]["assistant_message_id"],
            assistant)
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE public_id=?",
            (original_checkpoint["public_id"],))["status"],
            "clarification")
        clarified = state["next_card"]["checkpoint"]
        self.assertEqual(clarified["status"], "active")
        self.assertEqual(clarified["seq"], original_checkpoint["seq"] + 1)
        self.assertEqual(result["checkpoint_public_id"],
                         clarified["public_id"])
        self.assertEqual(result["checkpoint_seq"], clarified["seq"])
        self.assertEqual(
            self.row(
                "SELECT anchor_assistant_message FROM "
                "schema_path_checkpoints WHERE public_id=?",
                (clarified["public_id"],))["anchor_assistant_message"],
            assistant)
        reloaded = self.dashboard()
        self.assertEqual(reloaded["next_card"]["checkpoint"], clarified)
        self.assertEqual(
            reloaded["next_card"]["chat_binding"]["checkpoint_public_id"],
            clarified["public_id"])
        self.assertIsNone(state["active_path"]["current_candidate"][
            "burden"])

        turns = (
            ("7", "current_impact", "impact"),
            ("Gün içinde ilişkiden geri çekilmeme yol açıyor.",
             "current_impact", "priority"),
            ("Şimdi", "variable_check", "variable"),
            ("Karşımdakinin sakin kalması", "variable_check", "scenario"),
            ("Aynı konu sakin biçimde konuşuluyor.",
             "variable_check", "changed_burden"),
            ("4", "variable_check", "fit"),
            ("Kısmen", "focus_confirm", "confirm"),
            ("Evet", "method_confirm", "confirm"),
            ("Çalışalım", "origin_or_unknown", "memory"),
        )
        for text, expected_step, expected_prompt in turns:
            result, state, _user, assistant = \
                self.complete_chat_only_turn(text)
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["step"], expected_step)
            self.assertEqual(
                state["next_card"]["source"]["assistant_message_id"],
                assistant)
            with app.db() as connection:
                payload = app._schema_v4_step_payload(
                    connection, connection.execute(
                        "SELECT * FROM schema_paths WHERE id=?",
                        (state["active_path"]["id"],)).fetchone())
            self.assertEqual(payload.get("chat", {}).get("prompt"),
                             expected_prompt)
            self.assertEqual(state["next_card"]["fields"], [])

        candidate = state["active_path"]["current_candidate"]
        self.assertEqual(candidate["burden"], 7)
        self.assertEqual(candidate["priority"], "now")
        self.assertTrue(state["active_path"]["focus"]["confirmed"])

    def test_minimal_accepted_chat_binding_retry_is_semantically_idempotent(self):
        state, _pairs = self.start_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        binding.pop("protocol", None)
        binding.pop("path_public_id", None)
        binding["step_data"] = {}
        request_id = self.request_id("minimal-binding-retry")
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        before_jobs = self.row(
            "SELECT COUNT(*) AS n FROM jobs WHERE conv=?", (self.conv,))["n"]

        first, created = app.begin_chat_request(
            self.conv, "7", request_id=request_id,
            schema_binding=binding)
        second, created_again = app.begin_chat_request(
            self.conv, "7", request_id=request_id,
            schema_binding=dict(binding))
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(first["user_message"], second["user_message"])
        self.assertEqual(first["job"], second["job"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages + 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
            (self.conv,))["n"], before_jobs + 1)

        divergent = dict(binding)
        divergent["expected_checkpoint_seq"] += 1
        with self.assertRaises(app.RequestInputError) as stale:
            app.begin_chat_request(
                self.conv, "7", request_id=request_id,
                schema_binding=divergent)
        self.assertEqual(stale.exception.status, 409)
        unknown = dict(binding)
        unknown["client_note"] = "ignored olmamalı"
        with self.assertRaises(app.RequestInputError) as unsupported:
            app.begin_chat_request(
                self.conv, "7", request_id=request_id,
                schema_binding=unknown)
        self.assertEqual(unsupported.exception.status, 409)

    def test_chat_only_origin_precheck_imagery_and_grounding_reuse_engine(self):
        state, _pairs = self.focus_chat_only_path()
        result, state, scene_user, scene_assistant = \
            self.complete_chat_only_turn(
                "İlkokul yıllarında koridorda yalnız beklediğim bir an.")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["followup_required"])
        self.assertEqual(state["step"], "origin_or_unknown")
        self.assertIsNone(self.row(
            "SELECT * FROM schema_origin WHERE path=?",
            (state["active_path"]["id"],)))
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Yanımda sakin ve güvenilir bir yetişkin olmasına ihtiyacım vardı.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        origin = self.row(
            "SELECT * FROM schema_origin WHERE path=?",
            (state["active_path"]["id"],))
        self.assertIsNone(origin["age_reported"])
        self.assertEqual(origin["source_user_message"], scene_user)
        self.assertEqual(origin["source_assistant_message"], scene_assistant)
        self.assertIn("İlkokul", origin["scene"])

        before_revision = state["revision"]
        result, state, _user, ambiguous_assistant = \
            self.complete_chat_only_turn("Emin değilim")
        self.assertFalse(result["applied"], result)
        self.assertEqual(result["error_code"],
                         "schema_chat_followup_required")
        self.assertEqual(result["missing"], ["orientation_confirmed"])
        self.assertGreater(state["revision"], before_revision)
        self.assertEqual(
            state["next_card"]["source"]["assistant_message_id"],
            ambiguous_assistant)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

        for answer, expected_prompt in (
                ("Evet", "reality"),
                ("Evet", "sleep"),
                ("Evet", "intensity"),
                ("Yoğunluk 3", "support"),
                ("Hayır", "stop_signal")):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
            self.assertTrue(result["followup_required"], result)
            with app.db() as connection:
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?",
                    (state["active_path"]["id"],)).fetchone()
                payload = app._schema_v4_step_payload(connection, path)
            self.assertEqual(payload["chat"]["prompt"], expected_prompt)
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Durma işaretim 'dur' olsun")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["progressed"], result)
        self.assertEqual(state["step"], "imagery_work")
        link = state["active_path"]["active_technique_link"]
        self.assertEqual(link["method_id"], app.IMAGERY_METHOD_NODE_ID)
        self.assertEqual(state["next_card"]["fields"], [])
        self.assertEqual(
            state["next_card"]["chat_binding"]["technique_link_public_id"],
            link["public_id"])
        run = self.row(
            "SELECT * FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))
        precheck_sources = json.loads(run["state_json"])[
            "schema_v4_precheck_sources"]
        self.assertEqual(set(precheck_sources), {
            "orientation_confirmed", "reality_clear",
            "sleep_activation_clear", "intensity", "support_available",
            "stop_signal",
        })
        self.assertEqual(len({
            item["user_message_id"] for item in precheck_sources.values()}),
            6)

        before_steps = self.row(
            "SELECT COUNT(*) AS n FROM imagery_steps WHERE technique_run=?",
            (link["technique_run_id"],))["n"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Kapının yanında beklediğim sahne.")
        self.assertFalse(result["applied"], result)
        self.assertEqual(set(result["missing"]), {
            "orientation_ok", "reality_clear", "intensity"})
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM imagery_steps WHERE technique_run=?",
            (link["technique_run_id"],))["n"], before_steps)

        for _index in range(10):
            current_link = state["active_path"]["active_technique_link"]
            run = self.row(
                "SELECT status,phase FROM technique_runs WHERE id=?",
                (current_link["technique_run_id"],))
            if run["phase"] == "grounding":
                break
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(
                    "Şimdi buradayım; bunun bir çalışma olduğunu biliyorum; "
                    "yoğunluk 3. Sahnede fark ettiğimi kendi sözlerimle "
                    "anlatıyorum.")
            self.assertTrue(result["applied"], result)
        else:
            self.fail("İmgeleme reducerı grounding aşamasına ulaşmadı")
        self.assertEqual(run["status"], "paused")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Şimdi buradayım; bunun bir çalışma olduğunu biliyorum; "
            "yoğunluk 2. Çevremde masayı görüyorum.")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["progressed"], result)
        self.assertEqual(state["step"], "healthy_adult_voice")
        self.assertEqual(self.row(
            "SELECT status FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))["status"], "completed")

    def test_chat_only_stage3_preserves_field_sources_and_closes(self):
        state, pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            pair = app.schema_exact_source_pair(
                connection, self.conv, pairs[0]["user_message_id"],
                pairs[0]["assistant_message_id"])
            app.schema_v4_set_state(
                connection, path, "integrate", "healthy_adult_voice", pair,
                {"chat": {"prompt": "", "values": {}, "sources": {}}})
        state = self.dashboard()
        result, state, healthy_user, healthy_assistant = \
            self.complete_chat_only_turn(
                "Bugün sınırımı sakin biçimde söyleyebilirim.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "age_ladder")
        healthy = self.row(
            "SELECT * FROM healthy_adult_marks WHERE path=?",
            (path_id,))
        self.assertEqual(healthy["source_message"], healthy_user)
        self.assertEqual(
            healthy["source_assistant_message"], healthy_assistant)

        growth_turns = (
            "8 yaşındaydım",
            "O zaman saklanırdım.",
            "Bugün sakin biçimde konuşabilirim.",
            "Artık seçim yapabildiğimi biliyorum.",
        )
        growth_sources = []
        for answer in growth_turns:
            result, state, user_id, assistant_id = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
            growth_sources.append((user_id, assistant_id))
        self.assertEqual(state["step"], "age_ladder")
        growth = self.row(
            "SELECT * FROM schema_growth WHERE path=? ORDER BY seq LIMIT 1",
            (path_id,))
        self.assertEqual(growth["stage_age"], 8)
        self.assertEqual(growth["source_user_message"], growth_sources[0][0])
        self.assertEqual(
            growth["source_assistant_message"], growth_sources[0][1])
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Çevreyi yeniden resmetmeye devam edelim.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "environment_rescript")
        for answer in (
                "O zaman çevre sessiz ve kapalıydı.",
                "Yanımda güvenilir biri ve açık bir kapı olsun isterdim.",
                "Sağlıklı Yetişkin yanım yalnız olmadığımı söylerdi."):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "present_transfer")

        transfer_turns = (
            "Bugün mesajıma geç yanıt gelmesi tetikledi.",
            "Sağlıklı Yetişkin yanım bekleyebileceğimi söyler.",
            "Bir kez sakin bir soru soracağım.",
            "Gerekirse bir arkadaşımdan destek alırım.",
            "Konuşmanın daha açık olacağını tahmin ediyorum.",
        )
        transfer_sources = []
        for answer in transfer_turns:
            result, state, user_id, assistant_id = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
            transfer_sources.append((user_id, assistant_id))
        self.assertEqual(state["step"], "optional_practice")
        transfer = self.row(
            "SELECT * FROM schema_transfer_records WHERE path=?",
            (path_id,))
        self.assertEqual(
            transfer["trigger_source_user_message"],
            transfer_sources[0][0])
        self.assertEqual(
            transfer["trigger_source_assistant_message"],
            transfer_sources[0][1])
        self.assertEqual(
            transfer["source_user_message"], transfer_sources[-1][0])
        self.assertEqual(
            transfer["source_assistant_message"],
            transfer_sources[-1][1])
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            payload = app._schema_v4_step_payload(connection, path)
        sources = payload["present_transfer_sources"]
        self.assertEqual(
            sources["planned_action"]["user_message_id"],
            transfer_sources[2][0])
        self.assertEqual(
            sources["support_choice"]["user_message_id"],
            transfer_sources[3][0])

        result, state, _user, _assistant = \
            self.complete_chat_only_turn("Geç")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "followup")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Kendi cümlemi kurmak yardımcı oldu; yoğunluk kısmı zordu.")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["followup_required"], result)
        result, state, _user, _assistant = \
            self.complete_chat_only_turn("Evet")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["progressed"], result)
        self.assertEqual(result["step"], "complete")
        self.assertEqual(state["step"], "listen")
        self.assertEqual(state["active_path"], None)
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "completed")

    def test_real_stage3_backtrack_retires_stale_artifacts_and_reanswers(self):
        state = self.complete_imagery_to_healthy_adult()
        path_id = state["active_path"]["id"]

        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bugün sınırımı sakin biçimde ben söyleyebilirim.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "age_ladder")
        for answer in (
                "8 yaşındaydım", "O zaman saklanırdım.",
                "Bugün konuşmayı seçebilirim.",
                "Artık seçim yapabildiğimi biliyorum."):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
        first_growth = self.row(
            "SELECT * FROM schema_growth WHERE path=? AND status='active'",
            (path_id,))
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Çevreyi yeniden resmetmeye devam edelim.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "environment_rescript")

        # One ordinary back command revisits the last age decision. The
        # completed age row remains authoritative; it is not mistaken for a
        # new answer and does not need to be entered again.
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "age_ladder")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "continue")
        self.assertEqual(self.row(
            "SELECT status FROM schema_growth WHERE id=?",
            (first_growth["id"],))["status"], "active")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Çevreye geçelim.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "environment_rescript")

        for answer in (
                "O zamanki çevre kapalı ve sessizdi.",
                "Açık bir kapı ve güvenilir bir kişi olsun isterdim.",
                "Sağlıklı Yetişkin yanım yalnız olmadığımı söylerdi."):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "present_transfer")
        old_environment_source = self.row(
            "SELECT environment_source_user_message FROM schema_growth "
            "WHERE id=?", (first_growth["id"],))[
                "environment_source_user_message"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "environment_rescript")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "healthy_words")
        self.assertEqual(self.row(
            "SELECT status,environment_status FROM schema_growth WHERE id=?",
            (first_growth["id"],))["environment_status"], "invalidated")
        result, state, new_environment_user, _assistant = \
            self.complete_chat_only_turn(
                "Yeni resimde Sağlıklı Yetişkin yanım yanımda kalır.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "present_transfer")
        current_growth = self.row(
            "SELECT * FROM schema_growth WHERE id=?", (first_growth["id"],))
        self.assertEqual(current_growth["status"], "active")
        self.assertEqual(current_growth["environment_status"], "active")
        self.assertNotEqual(old_environment_source, new_environment_user)
        self.assertEqual(current_growth["environment_source_user_message"],
                         new_environment_user)
        self.assertEqual(current_growth["source_user_message"],
                         first_growth["source_user_message"])

        transfer_answers = (
            "Bugün mesajıma geç yanıt gelmesi tetikledi.",
            "Sağlıklı Yetişkin yanım bekleyebileceğimi söyler.",
            "Bir kez sakin bir soru soracağım.",
            "Gerekirse bir arkadaşımdan destek alırım.",
            "Konuşmanın daha açık olacağını tahmin ediyorum.",
        )
        for answer in transfer_answers:
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "optional_practice")
        transfer_id = self.row(
            "SELECT id FROM schema_transfer_records WHERE path=?",
            (path_id,))["id"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "present_transfer")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "prediction")
        self.assertEqual(self.row(
            "SELECT status FROM schema_transfer_records WHERE id=?",
            (transfer_id,))["status"], "invalidated")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Yeni denemede daha açık bir konuşma bekliyorum.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "optional_practice")
        self.assertEqual(self.row(
            "SELECT status FROM schema_transfer_records WHERE id=?",
            (transfer_id,))["status"], "active")

        for answer in (
                "Evet", "Bir kez sakin bir soru soracağım.",
                "Mesajın gelme süresi", "Soruyu bir kez sormam",
                "Konuşmanın açılması", "Yanıt gelip gelmemesi",
                "Önce tek cümle yazmak", "2"):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], (answer, result))
        self.assertEqual(state["step"], "followup")
        self.assertEqual(self.row(
            "SELECT practice_status FROM schema_paths WHERE id=?",
            (path_id,))["practice_status"], "active")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "optional_practice")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "frequency")
        self.assertEqual(self.row(
            "SELECT practice_status FROM schema_paths WHERE id=?",
            (path_id,))["practice_status"], "invalidated")
        self.assertIsNone(state["active_path"]["practice"])
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "3")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "followup")
        self.assertEqual(self.row(
            "SELECT practice_status FROM schema_paths WHERE id=?",
            (path_id,))["practice_status"], "active")

        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Kendi cümlemi kurmak yardımcı oldu.")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "close")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "followup")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "review")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Yeni gözden geçirmemde sınır koymak yardımcı oldu.")
        self.assertTrue(result["applied"], result)
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Evet")
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["step"], "complete")
        self.assertIsNone(state["active_path"])
        self.assertGreater(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], 20)
        self.assertTrue(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=? "
            "AND status='backtracked'", (path_id,))["n"])

    def test_age_revisit_after_six_real_stages_has_no_limit_or_order_deadlock(self):
        state = self.complete_imagery_to_healthy_adult()
        path_id = state["active_path"]["id"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bugün kendi sesimle seçim yapabilirim.")
        self.assertTrue(result["applied"], result)
        for index, age in enumerate(range(8, 14)):
            for answer in (
                    "{} yaşındaydım".format(age),
                    "O zaman {} yaşımda geri çekilirdim.".format(age),
                    "Bugün {} yaş durağına daha sakin bakıyorum.".format(age),
                    "Şimdi seçim yapabilmem aradaki fark."):
                result, state, _user, _assistant = \
                    self.complete_chat_only_turn(answer)
                self.assertTrue(result["applied"], (age, answer, result))
            if index < 5:
                result, state, _user, _assistant = \
                    self.complete_chat_only_turn("Bir yaş daha")
                self.assertTrue(result["applied"], result)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_growth WHERE path=? "
            "AND status='active'", (path_id,))["n"], 6)
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Çevreye geçelim")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "environment_rescript")

        for expected_prompt in (
                "continue", "difference", "now_response", "then_response",
                "age_label"):
            result, state, _user, _assistant = self.complete_chat_only_turn(
                "Geri dön")
            self.assertTrue(result["backtracked"],
                            (expected_prompt, result))
            self.assertEqual(state["step"], "age_ladder")
            self.assertEqual(
                state["next_card"]["checkpoint"]["prompt_key"],
                expected_prompt)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_growth WHERE path=? "
            "AND status='active'", (path_id,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_growth WHERE path=? "
            "AND status='invalidated'", (path_id,))["n"], 6)

        # A younger new sequence is valid because the six former stages are
        # historical audit, not an ordering/limit authority for this revisit.
        for answer in (
                "5 yaşındaydım", "O zaman saklanırdım.",
                "Bugün yardım isteyebilirim.",
                "Şimdi seçim yapabilmem fark yaratıyor."):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], (answer, result))
        active = self.rows(
            "SELECT seq,stage_age,status FROM schema_growth WHERE path=? "
            "AND status='active'", (path_id,))
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["stage_age"], 5)
        self.assertGreater(active[0]["seq"], 6)

    def test_chat_only_invalidates_all_collected_sources_before_commit(self):
        state, _pairs = self.start_chat_only_path()
        result, state, burden_user, _assistant = \
            self.complete_chat_only_turn("7")
        self.assertTrue(result["applied"], result)
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Gün içinde ilişkiden geri çekilmeme yol açıyor.")
        self.assertTrue(result["applied"], result)
        old_binding = dict(state["next_card"]["chat_binding"])
        path_id = state["active_path"]["id"]
        before_checkpoints = self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"]
        with app.db() as connection:
            connection.execute(
                "UPDATE messages SET delivery_status='failed' WHERE id=?",
                (burden_user,))
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with mock.patch.object(app, "open_provider_url") as provider_call:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Şimdi",
                    request_id=self.request_id("invalid-collected-preflight"),
                    schema_binding=old_binding)
            provider_call.assert_not_called()
        self.assertEqual(rejected.exception.error_code,
                         "schema_source_invalid")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)

        # Concurrent dashboards serialize the single append-only repair.
        with ThreadPoolExecutor(max_workers=2) as pool:
            repaired = list(pool.map(
                lambda _index: app.schema_path_payload(self.conv), range(2)))
        identities = {
            (item["revision"],
             item["next_card"]["checkpoint"]["public_id"],
             item["next_card"]["checkpoint"]["seq"])
            for item in repaired}
        self.assertEqual(len(identities), 1, identities)
        state = repaired[0]
        self.assertEqual(state["step"], "current_impact")
        self.assertEqual(state["active_path"]["status"], "active")
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "burden")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], before_checkpoints + 1)
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1 OFFSET 1", (path_id,))["status"],
            "clarification")
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?",
                (path_id,)).fetchone()
            payload = app._schema_v4_step_payload(connection, path)
        self.assertEqual(payload["chat"], {
            "prompt": "burden", "sources": {}, "values": {}})
        self.assertEqual(payload["chat_invalidated"], "burden")
        result, state, _user, _assistant = self.complete_chat_only_turn("6")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["next_card"]["checkpoint"]["prompt_key"],
                         "impact")

    def test_dashboard_source_invalidation_is_redacted_blocked_and_stable(self):
        state, pairs = self.start_chat_only_path()
        path_id = state["active_path"]["id"]
        result, state, _user, _assistant = \
            self.complete_chat_only_turn("7")
        self.assertTrue(result["applied"], result)
        with app.db() as connection:
            connection.execute(
                "UPDATE chat_requests SET status='failed' "
                "WHERE conv=? AND user_message=?",
                (self.conv, pairs[0]["user_message_id"]))
        blocked = self.dashboard()
        self.assertEqual(blocked["active_path"]["status"], "paused")
        self.assertEqual(blocked["active_path"]["pause_reason"],
                         "source_invalid")
        self.assertEqual(blocked["next_card"]["kind"], "blocked")
        self.assertIsNone(blocked["next_card"]["chat_binding"])
        self.assertEqual(
            [item["action"] for item in blocked["next_card"]["actions"]],
            ["stop"])
        self.assertFalse(blocked["interaction_policy"][
            "composer_allowed"])
        self.assertIsNone(blocked["active_path"]["candidate"])
        self.assertIsNone(blocked["active_path"]["current_candidate"])
        self.assertEqual(blocked["active_path"]["focus"]["evidence"], "")
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            payload = app._schema_v4_step_payload(connection, path)
        self.assertNotIn("chat", payload)
        self.assertEqual(payload["chat_invalidated"], "source")
        identity = (
            blocked["revision"],
            blocked["next_card"]["checkpoint"]["public_id"],
            blocked["next_card"]["checkpoint"]["status"],
            self.row(
                "SELECT COUNT(*) AS n FROM schema_path_method_choices "
                "WHERE path=?", (path_id,))["n"])
        repeated = self.dashboard()
        self.assertEqual((
            repeated["revision"],
            repeated["next_card"]["checkpoint"]["public_id"],
            repeated["next_card"]["checkpoint"]["status"],
            self.row(
                "SELECT COUNT(*) AS n FROM schema_path_method_choices "
                "WHERE path=?", (path_id,))["n"]), identity)
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with mock.patch.object(app, "open_provider_url") as provider_call:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Bu adım ilerlemesin.",
                    request_id=self.request_id("blocked-source"),
                    schema_binding=None)
            provider_call.assert_not_called()
        self.assertEqual(rejected.exception.error_code,
                         "schema_chat_binding_required")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)

    def test_safety_hold_redacts_provisional_chat_values_atomically(self):
        state, _pairs = self.start_chat_only_path()
        result, state, _user, _assistant = \
            self.complete_chat_only_turn("7")
        self.assertTrue(result["applied"], result)
        sentinel = "yalnız-bu-provisional-etki-metni"
        result, state, source_user, _assistant = \
            self.complete_chat_only_turn(sentinel)
        self.assertTrue(result["applied"], result)
        path_id = state["active_path"]["id"]
        before_payload = self.row(
            "SELECT payload_json FROM schema_path_steps WHERE path=? "
            "AND step='current_impact'", (path_id,))["payload_json"]
        self.assertIn(sentinel, before_payload)
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                app.record_safety_event(
                    connection, self.conv,
                    {"detected": True, "kind": "current_risk",
                     "context": "chat", "detector_version": 1},
                    source_message=source_user,
                    detector_context="chat")
        path = self.row(
            "SELECT * FROM schema_paths WHERE id=?", (path_id,))
        self.assertEqual(path["status"], "paused")
        self.assertEqual(path["pause_reason"], "safety_hold")
        after_payload = self.row(
            "SELECT payload_json FROM schema_path_steps WHERE path=? "
            "AND step='current_impact'", (path_id,))["payload_json"]
        self.assertNotIn(sentinel, after_payload)
        redacted = json.loads(after_payload)
        self.assertNotIn("chat", redacted)
        self.assertTrue(redacted["safety_redacted"])

    def test_method_proposal_requires_explicit_confirmation_before_run(self):
        state, _pairs = self.method_confirm_chat_only_path()
        path = state["active_path"]
        self.assertIsNone(path["method_id"])
        self.assertEqual(state["step"], "method_confirm")
        self.assertEqual(
            state["next_card"]["body"],
            "Bu odağı bugün şu yöntemle çalışalım mı: İmgeleme ile yeniden "
            "senaryolama? "
            "Evet ya da hayır diyebilirsin.")
        checkpoint = state["next_card"]["checkpoint"]
        binding = state["next_card"]["chat_binding"]
        self.assertRegex(checkpoint["public_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(binding["checkpoint_public_id"],
                         checkpoint["public_id"])
        self.assertEqual(binding["expected_checkpoint_seq"],
                         checkpoint["seq"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)
        choice = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=?",
            (path["id"],))
        self.assertEqual((choice["status"], choice["authored_by"]),
                         ("proposed", "server_rule"))

    def test_incomplete_method_confirmation_never_advances_or_starts(self):
        state, _pairs = self.method_confirm_chat_only_path()
        old_seq = state["next_card"]["checkpoint"]["seq"]
        result, state, _user, assistant = self.complete_chat_only_turn(
            "Bundan pek emin değilim.")
        self.assertFalse(result["applied"], result)
        self.assertTrue(result["followup_required"])
        self.assertEqual(result["error_code"],
                         "schema_method_confirmation_required")
        self.assertEqual(state["step"], "method_confirm")
        self.assertGreater(state["next_card"]["checkpoint"]["seq"], old_seq)
        self.assertEqual(state["next_card"]["source"]["assistant_message_id"],
                         assistant)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_all_method_branches_require_exact_user_confirmation(self):
        branches = (
            ("İmgeleme ile çalışmak istiyorum", app.IMAGERY_METHOD_NODE_ID,
             "imagery_precheck"),
            ("Sandalye diyaloğunu seçiyorum",
             "young:method:chair-dialogue", "mode_dialogue"),
            ("Sınırlı yeniden ebeveynleştirmeyi seçiyorum",
             app.REPARENTING_METHOD_NODE_ID,
             "reparent_or_chair_precheck"),
        )
        for index, (answer, method_id, expected_precheck) in enumerate(branches):
            if index:
                self.conv = self.conversation(therapist="young")
                app.set_schema_mode(self.conv, True)
            state, _pairs = self.method_confirm_chat_only_path()
            path_id = state["active_path"]["id"]
            initial = self.row(
                "SELECT * FROM schema_path_method_choices WHERE path=?",
                (path_id,))
            self.assertEqual(initial["method_node_id"],
                             app.IMAGERY_METHOD_NODE_ID)
            self.assertNotEqual(initial["method_node_id"],
                                app.REPARENTING_METHOD_NODE_ID)
            status, rejected = self.mutate(
                "start_chat_technique", method_id=method_id,
                orientation_confirmed=True, reality_clear=True,
                sleep_activation_clear=True, intensity=2,
                support_available=False, stop_signal="dur")
            self.assertEqual(status, 409, rejected)
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
                (self.conv,))["n"], 0)
            result, state, _user, _assistant = self.complete_chat_only_turn(
                "Hayır")
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["step"], "method_select")
            if index == 0:
                ambiguous, state, _user, _assistant = \
                    self.complete_chat_only_turn("İmgeleme ve sandalye")
                self.assertFalse(ambiguous["applied"], ambiguous)
                self.assertEqual(ambiguous["error_code"],
                                 "schema_method_ambiguous")
                self.assertEqual(state["step"], "method_select")
            result, state, _user, _assistant = self.complete_chat_only_turn(
                answer)
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["step"], "method_confirm")
            proposed = self.row(
                "SELECT * FROM schema_path_method_choices WHERE path=? "
                "ORDER BY seq DESC LIMIT 1", (path_id,))
            self.assertEqual((proposed["method_node_id"], proposed["status"]),
                             (method_id, "proposed"))
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
                (self.conv,))["n"], 0)
            result, state, _user, _assistant = self.complete_chat_only_turn(
                "Bunu bugünkü seansta çalışalım")
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["active_path"]["method_id"], method_id)
            self.assertEqual(state["step"], "origin_or_unknown")
            selected = self.row(
                "SELECT * FROM schema_path_method_choices WHERE path=? "
                "ORDER BY seq DESC LIMIT 1", (path_id,))
            self.assertEqual(selected["status"], "selected")
            result, state, _user, _assistant = self.complete_chat_only_turn(
                "Hatırlamıyorum")
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["step"], expected_precheck)
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
                (self.conv,))["n"], 0)
            prompt = self.bound_provider_system_prompt("Evet", None)
            self.assertIn(app.SCHEMA_PATH_V4_METHOD_LABELS[method_id], prompt)
            self.assertIn(
                state["next_card"]["checkpoint"]["public_id"], prompt)

    def test_legacy_deep_path_without_method_choice_repairs_to_confirmation(self):
        state, _pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            connection.execute(
                "DELETE FROM schema_path_method_choices WHERE path=?",
                (path_id,))
            connection.execute(
                "UPDATE schema_paths SET method_node_id=? WHERE id=?",
                (app.IMAGERY_METHOD_NODE_ID, path_id))
        repaired = self.dashboard()
        self.assertEqual(repaired["step"], "method_confirm")
        self.assertIsNone(repaired["active_path"]["method_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)
        proposal = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=?",
            (path_id,))
        self.assertEqual((proposal["status"], proposal["authored_by"]),
                         ("proposed", "server_rule"))
        self.assertTrue(json.loads(self.row(
            "SELECT payload_json FROM schema_path_steps WHERE path=? "
            "AND step='method_confirm'", (path_id,))["payload_json"])[
                "legacy_method_gate_repair"])

    def test_method_proposal_dashboard_repair_is_parallel_idempotent(self):
        state, _pairs = self.method_confirm_chat_only_path()
        path_id = state["active_path"]["id"]
        initial_revision = state["revision"]
        initial_checkpoint = dict(state["next_card"]["checkpoint"])
        initial_choice = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=? "
            "AND status='proposed'", (path_id,))

        def read_snapshot(_index):
            payload = app.schema_path_payload(self.conv)
            card = payload["next_card"]
            return (payload["revision"],
                    card["checkpoint"]["public_id"],
                    card["checkpoint"]["seq"], card["step"])

        with ThreadPoolExecutor(max_workers=6) as pool:
            snapshots = list(pool.map(read_snapshot, range(12)))
        self.assertEqual(set(snapshots), {(
            initial_revision, initial_checkpoint["public_id"],
            initial_checkpoint["seq"], "method_confirm")})
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices "
            "WHERE path=? AND status='proposed'", (path_id,))["n"], 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints "
            "WHERE path=? AND status='active'", (path_id,))["n"], 1)
        self.assertEqual(self.row(
            "SELECT public_id FROM schema_path_method_choices WHERE path=? "
            "AND status='proposed'", (path_id,))["public_id"],
            initial_choice["public_id"])

        # Invalidate the old proposed pair after a newer safe pair exists.
        # Exactly one replacement proposal/checkpoint may be produced.
        replacement_pair = self.completed_pair(
            "Yöntem önerisini yeniden bağlamak için güvenli yeni kaynak")
        with app.db() as connection:
            connection.execute(
                "UPDATE chat_requests SET status='failed' "
                "WHERE conv=? AND user_message=?",
                (self.conv, initial_choice["source_user_message"]))
        repaired = self.dashboard()
        self.assertEqual(repaired["step"], "method_confirm")
        replacement = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=? "
            "AND status='proposed'", (path_id,))
        self.assertNotEqual(replacement["public_id"],
                            initial_choice["public_id"])
        self.assertEqual((replacement["source_user_message"],
                          replacement["source_assistant_message"]),
                         (replacement_pair["user_message_id"],
                          replacement_pair["assistant_message_id"]))
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_method_choices WHERE id=?",
            (initial_choice["id"],))["status"], "invalidated")
        repaired_identity = (
            repaired["revision"],
            repaired["next_card"]["checkpoint"]["public_id"],
            repaired["next_card"]["checkpoint"]["seq"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            after = list(pool.map(read_snapshot, range(8)))
        self.assertEqual({item[:3] for item in after}, {repaired_identity})
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices "
            "WHERE path=? AND status='proposed'", (path_id,))["n"], 1)

    def test_legacy_integrate_gate_repairs_without_completed_method_only(self):
        state, _pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            pair = app.schema_latest_safe_source_pair(connection, self.conv)
            app.schema_v4_set_state(
                connection, path, "integrate", "healthy_adult_voice", pair,
                {"chat": {"prompt": "voice", "values": {},
                          "sources": {}}})
            connection.execute(
                "DELETE FROM schema_path_method_choices WHERE path=?",
                (path_id,))
            connection.execute(
                "UPDATE schema_paths SET method_node_id='',"
                "technique_run=NULL WHERE id=?", (path_id,))
        repaired = self.dashboard()
        self.assertEqual(repaired["step"], "method_confirm")
        self.assertIsNone(repaired["active_path"]["method_id"])
        proposal = self.row(
            "SELECT * FROM schema_path_method_choices WHERE path=? "
            "AND status='proposed'", (path_id,))
        self.assertEqual(proposal["authored_by"], "server_rule")

        # A receiver at method_confirm with no device-local choice is repaired
        # once and remains stable on every later dashboard read.
        with app.db() as connection:
            connection.execute(
                "DELETE FROM schema_path_method_choices WHERE path=?",
                (path_id,))
        imported = self.dashboard()
        imported_again = self.dashboard()
        self.assertEqual(imported["step"], "method_confirm")
        self.assertEqual(imported_again["revision"], imported["revision"])
        self.assertEqual(
            imported_again["next_card"]["checkpoint"]["public_id"],
            imported["next_card"]["checkpoint"]["public_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices "
            "WHERE path=? AND status='proposed'", (path_id,))["n"], 1)

        # A verified completed local technique is sufficient legacy evidence.
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        completed = self.complete_imagery_to_healthy_adult()
        completed_path = completed["active_path"]["id"]
        with app.db() as connection:
            connection.execute(
                "DELETE FROM schema_path_method_choices WHERE path=?",
                (completed_path,))
        continued = self.dashboard()
        self.assertEqual(continued["step"], "healthy_adult_voice")
        self.assertEqual(continued["active_path"]["method_id"],
                         app.IMAGERY_METHOD_NODE_ID)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE path=? "
            "AND status='completed'", (completed_path,))["n"], 1)

    def test_imported_stage3_continues_without_rewinding_or_repeating_method(self):
        cases = (
            ("age_ladder", "age_label", ("Geç",),
             "environment_rescript"),
            ("environment_rescript", "before", ("Geç",),
             "present_transfer"),
            ("present_transfer", "trigger", (
                "Bugünkü konuşma gerildiğinde",
                "Bir an durup ihtiyacımı söyleyebilirim",
                "Sınırımı tek cümleyle söylemek",
                "Geç", "Geç"), "optional_practice"),
            ("optional_practice", "choice", ("Geç",), "followup"),
            ("followup", "review", ("Tamam",), "complete"),
        )
        for index, (step, prompt, answers, expected_step) in enumerate(cases):
            with self.subTest(step=step):
                if index:
                    self.conv = self.conversation(therapist="young")
                    app.set_schema_mode(self.conv, True)
                state, _pairs = self.focus_chat_only_path()
                path_id = state["active_path"]["id"]
                with app.db() as connection:
                    path = connection.execute(
                        "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                    ).fetchone()
                    pair = app.schema_latest_safe_source_pair(
                        connection, self.conv)
                    path = app.schema_v4_set_state(
                        connection, path, "integrate", step, pair,
                        {"chat": {"prompt": prompt, "values": {},
                                  "sources": {}}})
                    connection.execute(
                        "DELETE FROM schema_path_method_choices WHERE path=?",
                        (path_id,))
                    connection.execute(
                        "DELETE FROM schema_path_checkpoints WHERE path=?",
                        (path_id,))
                    connection.execute(
                        "UPDATE schema_paths SET method_node_id=?,"
                        "technique_run=NULL WHERE id=?",
                        (app.IMAGERY_METHOD_NODE_ID, path_id))
                    baseline = connection.execute(
                        "SELECT revision,stage,step FROM schema_paths "
                        "WHERE id=?", (path_id,)).fetchone()
                with mock.patch.object(
                        app, "open_provider_url") as provider_call:
                    repaired = self.dashboard()
                    provider_call.assert_not_called()
                self.assertEqual((repaired["stage"], repaired["step"]),
                                 ("integrate", step))
                self.assertEqual(repaired["revision"], baseline["revision"])
                self.assertEqual(repaired["active_path"]["method_id"],
                                 app.IMAGERY_METHOD_NODE_ID)
                checkpoint = self.row(
                    "SELECT * FROM schema_path_checkpoints WHERE path=?",
                    (path_id,))
                self.assertEqual(
                    (checkpoint["status"], checkpoint["transition_kind"]),
                    ("active", "import"))
                self.assertFalse(
                    repaired["next_card"]["checkpoint"]["can_backtrack"])
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM schema_path_method_choices "
                    "WHERE path=?", (path_id,))["n"], 0)
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM schema_path_techniques "
                    "WHERE path=?", (path_id,))["n"], 0)

                for answer in answers:
                    result, continued, _user, _assistant = \
                        self.complete_chat_only_turn(answer)
                    self.assertTrue(result["applied"], (answer, result))
                self.assertTrue(result["progressed"], result)
                self.assertEqual(result["step"], expected_step)
                if continued["active_path"]:
                    self.assertNotEqual(continued["stage"], "depth")
                    self.assertNotIn(
                        continued["step"],
                        ("method_select", "method_confirm",
                         "origin_or_unknown", "imagery_precheck",
                         "imagery_work"))
                self.assertEqual(self.row(
                    "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
                    (self.conv,))["n"], 0)
                # The import marker remains local authority across later
                # Stage-3 checkpoints; a reload cannot silently rewind it.
                reloaded = self.dashboard()
                if reloaded["active_path"]:
                    self.assertNotEqual(reloaded["stage"], "depth")

    def test_legacy_active_run_keeps_continuity_and_imports_checkpoint(self):
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        run_id = state["active_path"]["active_technique_link"][
            "technique_run_id"]
        with app.db() as connection:
            connection.execute(
                "DELETE FROM schema_path_checkpoints WHERE path=?", (path_id,))
            connection.execute(
                "DELETE FROM schema_path_method_choices WHERE path=?",
                (path_id,))
        repaired = self.dashboard()
        self.assertEqual(repaired["step"], "imagery_work")
        self.assertEqual(repaired["active_path"]["method_id"],
                         app.IMAGERY_METHOD_NODE_ID)
        self.assertEqual(repaired["active_path"]["active_technique_link"][
            "technique_run_id"], run_id)
        checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=?", (path_id,))
        self.assertEqual((checkpoint["status"], checkpoint["transition_kind"]),
                         ("active", "import"))
        self.assertTrue(checkpoint["anchor_user_message"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_method_choices WHERE path=?",
            (path_id,))["n"], 0)

    def test_backtrack_without_run_appends_audited_method_revisit(self):
        state, _pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        before = self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["backtracked"], result)
        self.assertEqual((result["action"], state["step"]),
                         ("backtrack_step", "method_confirm"))
        self.assertIsNone(state["active_path"]["method_id"])
        self.assertGreater(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=?",
            (path_id,))["n"], before)
        choices = self.rows(
            "SELECT status FROM schema_path_method_choices WHERE path=? "
            "ORDER BY seq", (path_id,))
        self.assertEqual([row["status"] for row in choices],
                         ["superseded", "proposed"])
        self.assertTrue(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=? "
            "AND status='backtracked'", (path_id,))["n"])
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Hayır")
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "method_select")

    def test_backtrack_to_focus_confirm_restores_listen_phase_projection(self):
        state, _pairs = self.focus_chat_only_path()
        first, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(first["backtracked"], first)
        self.assertEqual(state["step"], "method_confirm")
        second, state, _user, _assistant = self.complete_chat_only_turn(
            "Geri dön")
        self.assertTrue(second["backtracked"], second)
        self.assertEqual((state["stage"], state["step"]),
                         ("listen", "focus_confirm"))
        self.assertEqual(state["active_path"]["phase"], "explore")
        self.assertIsNone(state["active_path"]["method_id"])

    def test_stage3_backtrack_revisits_each_immediate_safe_checkpoint(self):
        state, pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        conv = self.conversation_row(self.conv)
        chain = (
            "healthy_adult_voice", "age_ladder", "environment_rescript",
            "present_transfer", "optional_practice", "followup")
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)).fetchone()
            source = app.schema_exact_source_pair(
                connection, self.conv, pairs[0]["user_message_id"],
                pairs[0]["assistant_message_id"])
            path = app.schema_v4_set_state(
                connection, path, "integrate", chain[0], source,
                {"chat": {"prompt": "voice", "values": {}, "sources": {}}})
        for previous, current in zip(chain, chain[1:]):
            forward = self.completed_pair("{} adımına geçiş".format(current))
            with app.db() as connection:
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
                source = app.schema_exact_source_pair(
                    connection, self.conv, forward["user_message_id"],
                    forward["assistant_message_id"])
                if path["step"] != previous:
                    path = app.schema_v4_set_state(
                        connection, path, "integrate", previous, source,
                        {"chat": {"prompt":
                                  app.SCHEMA_V4_INITIAL_PROMPT_KEYS[previous],
                                  "values": {}, "sources": {}}})
                path = app.schema_v4_set_state(
                    connection, path, "integrate", current, source,
                    {"chat": {"prompt": app.SCHEMA_V4_INITIAL_PROMPT_KEYS[
                        current], "values": {}, "sources": {}}})
                before_seq = app.schema_v4_checkpoint_public(
                    connection, path)["seq"]
            command = self.completed_pair("Geri dön")
            with app.db() as connection:
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
                pair = app.schema_exact_source_pair(
                    connection, self.conv, command["user_message_id"],
                    command["assistant_message_id"])
                result = app._schema_v4_apply_chat_only_pair(
                    connection, conv, path, pair,
                    self.request_id("stage3-back"))
                revisited = app.schema_v4_checkpoint_public(
                    connection, connection.execute(
                        "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                    ).fetchone())
            self.assertTrue(result["applied"], (previous, current, result))
            self.assertEqual(result["step"], previous)
            self.assertGreater(revisited["seq"], before_seq)
            self.assertEqual(revisited["prompt_key"],
                             app.SCHEMA_V4_INITIAL_PROMPT_KEYS[previous])
            self.assertTrue(self.row(
                "SELECT COUNT(*) AS n FROM schema_path_checkpoints WHERE path=? "
                "AND step=? AND status='backtracked'",
                (path_id, previous))["n"])

    def test_active_run_backtrack_waits_for_grounding_then_stops_run(self):
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        run_id = state["active_path"]["active_technique_link"][
            "technique_run_id"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["action"], "backtrack_grounding_required")
        self.assertFalse(result["backtracked"])
        self.assertEqual(state["step"], "grounding_review")
        self.assertTrue(state["next_card"]["checkpoint"]["backtrack_pending"])
        run = self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?", (run_id,))
        self.assertEqual((run["status"], run["phase"]),
                         ("paused", "grounding"))
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Buradayım; bu bir çalışma olduğunu biliyorum; yoğunluk 3/7.")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        self.assertEqual(self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?", (run_id,))[
                "status"], "stopped")
        self.assertIsNone(self.row(
            "SELECT technique_run FROM schema_paths WHERE id=?", (path_id,))[
                "technique_run"])

    def test_direct_completion_honors_pending_backtrack_after_grounding(self):
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["action"], "backtrack_grounding_required")
        self.assertEqual(state["step"], "grounding_review")
        self.assertTrue(state["next_card"]["checkpoint"][
            "backtrack_pending"])
        link = state["active_path"]["active_technique_link"]
        run_id = link["technique_run_id"]
        status, state = self.mutate(
            "complete_chat_technique", step_id=state["step"],
            technique_link_id=link["id"],
            technique_link_public_id=link["public_id"],
            expected_technique_revision=link["technique_revision"],
            grounding_confirmed=True, orientation_ok=True,
            reality_clear=True, intensity=2)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "imagery_precheck")
        self.assertFalse(state["next_card"]["checkpoint"][
            "backtrack_pending"])
        self.assertEqual(self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?", (run_id,)
        )["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_techniques WHERE path=?",
            (path_id,))["status"], "invalidated")

    def test_pending_backtrack_source_is_rejected_before_provider_or_write(self):
        state = self.start_imagery_chat_only()
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertEqual(result["action"], "backtrack_grounding_required")
        card = state["next_card"]
        binding = dict(card["chat_binding"])
        link = state["active_path"]["active_technique_link"]
        binding.update({
            "technique_link_id": link["id"],
            "technique_link_public_id": link["public_id"],
            "expected_technique_revision": link["technique_revision"],
        })
        current = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? "
            "AND status='active' ORDER BY seq DESC LIMIT 1",
            (state["active_path"]["id"],))
        target = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE id=?",
            (current["pending_backtrack"],))
        with app.db() as connection:
            connection.execute(
                "UPDATE chat_requests SET status='failed' "
                "WHERE user_message=?",
                (target["answer_user_message"] or
                 target["anchor_user_message"],))
        before = {
            "messages": self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (self.conv,))["n"],
            "jobs": self.row(
                "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
                (self.conv,))["n"],
            "requests": self.row(
                "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
                (self.conv,))["n"],
        }
        with mock.patch.object(app, "open_provider_url") as provider_call:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv,
                    "Buradayım; bu bir çalışma; yoğunluk 2/7.",
                    request_id=self.request_id("invalid-pending-target"),
                    schema_binding=binding)
            provider_call.assert_not_called()
        self.assertEqual(rejected.exception.error_code,
                         "schema_backtrack_source_invalid")
        self.assertEqual({
            "messages": self.row(
                "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                (self.conv,))["n"],
            "jobs": self.row(
                "SELECT COUNT(*) AS n FROM jobs WHERE conv=?",
                (self.conv,))["n"],
            "requests": self.row(
                "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
                (self.conv,))["n"],
        }, before)

    def test_resume_rejects_safety_invalid_pending_backtrack_target(self):
        state = self.start_imagery_chat_only()
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertEqual(result["action"], "backtrack_grounding_required")
        path_id = state["active_path"]["id"]
        current = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? "
            "AND status='active' ORDER BY seq DESC LIMIT 1", (path_id,))
        target = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE id=?",
            (current["pending_backtrack"],))
        target_user = (target["answer_user_message"] or
                       target["anchor_user_message"])
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                app.record_safety_event(
                    connection, self.conv,
                    {"detected": True, "kind": "current_risk",
                     "context": "chat", "detector_version": 1},
                    source_message=target_user,
                    detector_context="chat")
                connection.execute(
                    "UPDATE safety_events SET status='released',resolved_at=? "
                    "WHERE conv=?", (app.now(), self.conv))
                connection.execute(
                    "UPDATE conversations SET safety_hold=0 WHERE id=?",
                    (self.conv,))
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
        status, body = self.post({
            "action": "resume_path", "conv_id": self.conv,
            "path_id": path_id, "path_public_id": path["public_id"],
            "expected_revision": path["revision"],
            "request_id": self.request_id("invalid-pending-resume"),
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"],
                         "schema_checkpoint_stale")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "paused")

    def test_second_run_backtrack_targets_nearest_precheck_visit(self):
        state = self.start_imagery()
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertEqual(result["action"], "backtrack_grounding_required")
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Buradayım; bu bir çalışma olduğunu biliyorum; yoğunluk 2/7.")
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        second_precheck = dict(state["next_card"]["checkpoint"])
        status, state = self.mutate(
            "start_chat_technique", method_id=app.IMAGERY_METHOD_NODE_ID,
            orientation_confirmed=True, reality_clear=True,
            sleep_activation_clear=True, intensity=2,
            support_available=True, stop_signal="dur")
        self.assertEqual(status, 200, state)
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertEqual(result["action"], "backtrack_grounding_required")
        checkpoint = state["next_card"]["checkpoint"]
        self.assertEqual(checkpoint["pending_target_public_id"],
                         second_precheck["public_id"])
        self.assertGreater(second_precheck["seq"], 1)
        links = self.rows(
            "SELECT status FROM schema_path_techniques WHERE path=? "
            "ORDER BY seq", (state["active_path"]["id"],))
        self.assertEqual(links[0]["status"], "invalidated")
        self.assertEqual(links[1]["status"], "paused")

    def test_pause_resume_checkpoint_identity_has_atomic_status_parity(self):
        state, _pairs = self.focus_chat_only_path()
        checkpoint = dict(state["next_card"]["checkpoint"])
        status, state = self.mutate("pause")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["next_card"]["checkpoint"]["status"], "paused")
        self.assertEqual(state["next_card"]["checkpoint"]["public_id"],
                         checkpoint["public_id"])
        status, state = self.mutate("resume_path")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["next_card"]["checkpoint"]["status"], "active")
        self.assertEqual(state["next_card"]["checkpoint"]["public_id"],
                         checkpoint["public_id"])

    def test_mode_off_all_entry_points_pause_checkpoint_and_local_run(self):
        def assert_grounded_pause(state, expected_revision_floor):
            path_id = state["active_path"]["id"]
            link = state["active_path"]["active_technique_link"]
            path = self.row(
                "SELECT status,pause_reason,revision FROM schema_paths "
                "WHERE id=?", (path_id,))
            self.assertEqual((path["status"], path["pause_reason"]),
                             ("paused", "schema_mode_off"))
            self.assertGreaterEqual(path["revision"],
                                    expected_revision_floor)
            self.assertEqual(self.row(
                "SELECT status FROM schema_path_steps WHERE path=? "
                "AND step='imagery_work'", (path_id,))["status"], "paused")
            self.assertEqual(self.row(
                "SELECT status FROM schema_path_checkpoints WHERE path=? "
                "ORDER BY seq DESC LIMIT 1", (path_id,))["status"],
                "paused")
            self.assertEqual(self.row(
                "SELECT status FROM schema_path_techniques WHERE id=?",
                (link["id"],))["status"], "paused")
            run = self.row(
                "SELECT status,phase FROM technique_runs WHERE id=?",
                (link["technique_run_id"],))
            self.assertEqual((run["status"], run["phase"]),
                             ("paused", "grounding"))
            self.assertEqual(self.row(
                "SELECT current_stage FROM imagery_runs "
                "WHERE technique_run=?", (link["technique_run_id"],)
            )["current_stage"], "grounding")
            return path

        direct = self.start_imagery()
        direct_revision = direct["revision"]
        app.set_schema_mode(self.conv, False)
        paused = assert_grounded_pause(direct, direct_revision + 1)
        app.set_schema_mode(self.conv, False)
        self.assertEqual(self.row(
            "SELECT revision FROM schema_paths WHERE id=?",
            (direct["active_path"]["id"],))["revision"],
            paused["revision"])

        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        reconciled = self.start_imagery()
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_mode_enabled=0 WHERE conv=?",
                (self.conv,))
        self.assertEqual(app.reconcile_disabled_schema_paths(), 1)
        reconciled_path = assert_grounded_pause(
            reconciled, reconciled["revision"] + 1)
        self.assertEqual(app.reconcile_disabled_schema_paths(), 0)
        self.assertEqual(self.row(
            "SELECT revision FROM schema_paths WHERE id=?",
            (reconciled["active_path"]["id"],))["revision"],
            reconciled_path["revision"])

        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        getter = self.start_imagery()
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_mode_enabled=0 WHERE conv=?",
                (self.conv,))
        projected = self.dashboard()
        assert_grounded_pause(getter, getter["revision"] + 1)
        self.assertEqual(projected["next_card"]["kind"], "resume")
        self.assertEqual(projected["next_card"]["checkpoint"]["status"],
                         "paused")

    def test_resume_requires_one_safe_paused_checkpoint(self):
        state, _pairs = self.focus_chat_only_path()
        status, paused = self.mutate("pause")
        self.assertEqual(status, 200, paused)
        path_id = paused["active_path"]["id"]
        checkpoint = self.row(
            "SELECT * FROM schema_path_checkpoints WHERE path=? "
            "AND status='paused'", (path_id,))
        with app.db() as connection:
            connection.execute(
                "UPDATE messages SET delivery_status='failed' WHERE id=?",
                (checkpoint["anchor_user_message"],))
        status, body = self.mutate("resume_path")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "schema_source_invalid")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "paused")

        with app.db() as connection:
            connection.execute(
                "UPDATE messages SET delivery_status='completed' WHERE id=?",
                (checkpoint["anchor_user_message"],))
            connection.execute(
                "UPDATE schema_path_checkpoints SET status='invalidated',"
                "invalidated_at=?,updated=? WHERE id=?",
                (app.now(), app.now(), checkpoint["id"]))
        status, body = self.mutate("resume_path")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "schema_checkpoint_stale")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "paused")

    def test_stop_response_has_no_stale_chat_card_and_matches_reload(self):
        state, _pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        status, stopped = self.mutate("stop")
        self.assertEqual(status, 200, stopped)
        self.assertEqual(stopped["active_path"]["status"], "stopped")
        self.assertIsNone(stopped["next_card"])
        self.assertFalse(stopped["interaction_policy"][
            "composer_binding_required"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"],
            "invalidated")
        reloaded = self.dashboard()
        self.assertIsNone(reloaded["active_path"])
        self.assertIsNone(reloaded["next_card"])

    def test_chat_stop_invalidates_checkpoint_and_returns_total_identity(self):
        state, _pairs = self.focus_chat_only_path()
        path_id = state["active_path"]["id"]
        checkpoint_id = state["next_card"]["checkpoint"]["public_id"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Çalışmayı bitir")
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["action"], "stop")
        self.assertEqual(result["checkpoint_public_id"], checkpoint_id)
        self.assertIsInstance(result["checkpoint_seq"], int)
        self.assertFalse(result["backtracked"])
        self.assertIsNone(state["active_path"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"], "invalidated")

    def test_exact_chat_commands_pause_every_step_stop_and_ground(self):
        state, pairs, _claim = self.start_v4()
        path_id = state["active_path"]["id"]
        anchor = pairs[0]
        for step in app.SCHEMA_PATH_V4_STEPS:
            if step == "complete":
                continue
            with app.db() as connection:
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
                connection.execute(
                    "UPDATE schema_paths SET status='active',"
                    "pause_reason='',resume_required=0 WHERE id=?",
                    (path_id,))
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
                source_pair = app.schema_exact_source_pair(
                    connection, self.conv, anchor["user_message_id"],
                    anchor["assistant_message_id"])
                path = app.schema_v4_set_state(
                    connection, path,
                    app.SCHEMA_PATH_V4_STEP_STAGE[step], step, source_pair,
                    {"chat": {"prompt": "", "values": {}, "sources": {}}})
            command_pair = self.completed_pair("dur")
            with app.db() as connection:
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?", (path_id,)
                ).fetchone()
                pair = app.schema_exact_source_pair(
                    connection, self.conv,
                    command_pair["user_message_id"],
                    command_pair["assistant_message_id"])
                result = app._schema_v4_apply_chat_only_pair(
                    connection, self.conversation_row(self.conv), path,
                    pair, self.request_id("pause-every-step"))
            self.assertTrue(result["applied"], (step, result))
            self.assertEqual(result["action"], "pause", step)
            self.assertEqual(self.row(
                "SELECT status FROM schema_paths WHERE id=?", (path_id,)
            )["status"], "paused")

        # Grounding is a distinct exact command and keeps the path active.
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        link = state["active_path"]["active_technique_link"]
        intensity_before = self.row(
            "SELECT intensity_current FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))["intensity_current"]
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Şimdiye dön")
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["action"], "ground_chat_technique")
        self.assertEqual(state["step"], "imagery_work")
        self.assertEqual(state["active_path"]["status"], "paused")
        grounded = self.row(
            "SELECT status,phase,intensity_current FROM technique_runs "
            "WHERE id=?", (link["technique_run_id"],))
        self.assertEqual((grounded["status"], grounded["phase"]),
                         ("paused", "grounding"))
        self.assertEqual(grounded["intensity_current"], intensity_before)

        stop_pair = self.completed_pair("Bu çalışmayı bırak")
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            pair = app.schema_exact_source_pair(
                connection, self.conv, stop_pair["user_message_id"],
                stop_pair["assistant_message_id"])
            result = app._schema_v4_apply_chat_only_pair(
                connection, self.conversation_row(self.conv), path, pair,
                self.request_id("stop-command"))
        self.assertTrue(result["applied"], result)
        self.assertEqual(result["action"], "stop")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "stopped")

    def test_chat_command_is_completed_before_provider_and_retry_is_exact(self):
        self.assertIsNone(app._schema_v4_chat_command(
            "Burada dur demek bazen bana zor geliyor"))
        state, _pairs = self.start_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        request_id = self.request_id("local-pause-command")
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "dur", request_id=request_id,
                schema_binding=binding)
            self.assertTrue(created)
            self.assertEqual(row["status"], "completed")
            events = []
            public = app.run_chat_request(
                request_id, emit=events.append,
                generation=app.data_generation())
            provider_call.assert_not_called()
        self.assertEqual(public["status"], "completed")
        result = public["schema_binding_result"]
        self.assertEqual(result["action"], "pause")
        self.assertTrue(result["applied"])
        self.assertEqual(public["attempt"], 0)
        # Post-Yes typed controls persist only the user's genuine command;
        # no fixed/synthetic Kerem acknowledgement is manufactured.
        self.assertEqual(public["content"], "")
        self.assertIsNone(row["assistant_message"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["schema_binding_result"], result)
        self.assertTrue(events[-1]["resume_state"]["required"])
        self.assertEqual(self.row(
            "SELECT status FROM jobs WHERE id=?", (row["job"],)
        )["status"], "succeeded")

        retry, created = app.begin_chat_request(
            self.conv, "dur", request_id=request_id,
            schema_binding=binding)
        self.assertFalse(created)
        self.assertEqual(retry["user_message"], row["user_message"])
        self.assertEqual(retry["assistant_message"], row["assistant_message"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages + 1)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM chat_requests WHERE request_id=?",
            (request_id,))["n"], 1)

        stale_count = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with self.assertRaises(app.RequestInputError) as stale:
            app.begin_chat_request(
                self.conv, "Çalışmayı bitir",
                request_id=self.request_id("stale-local-command"),
                schema_binding=binding)
        self.assertEqual(stale.exception.error_code,
                         "stale_schema_revision")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], stale_count)

        # A safety hold racing immediately after the atomic command may
        # strengthen the pause, but cannot resurrect provider work or rewrite
        # the already durable command result.
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                app.record_safety_event(
                    connection, self.conv,
                    {"detected": True, "kind": "current_risk",
                     "context": "chat", "detector_version": 1},
                    source_message=row["user_message"],
                    detector_context="chat")
        self.assertEqual(self.row(
            "SELECT pause_reason FROM schema_paths WHERE id=?",
            (result["path_id"],))["pause_reason"], "safety_hold")
        stored = json.loads(self.row(
            "SELECT schema_binding_result_json FROM chat_requests "
            "WHERE request_id=?", (request_id,)
        )["schema_binding_result_json"])
        self.assertEqual(stored["action"], "pause")

    def test_active_chat_prompt_rejects_unbound_turn_before_any_write(self):
        state, _pairs = self.start_chat_only_path()
        self.assertTrue(state["interaction_policy"][
            "composer_binding_required"])
        before_messages = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        before_jobs = self.row(
            "SELECT COUNT(*) AS n FROM jobs WHERE conv=?", (self.conv,))["n"]
        before_requests = self.row(
            "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
            (self.conv,))["n"]
        with mock.patch.object(app, "open_provider_url") as provider_call:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Bu sıradan ama bağsız bir yanıttır.",
                    request_id=self.request_id("missing-binding"),
                    schema_binding=None)
            provider_call.assert_not_called()
        self.assertEqual(rejected.exception.status, 409)
        self.assertEqual(rejected.exception.error_code,
                         "schema_chat_binding_required")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before_messages)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM jobs WHERE conv=?", (self.conv,)
        )["n"], before_jobs)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM chat_requests WHERE conv=?",
            (self.conv,))["n"], before_requests)

    def test_chat_only_ground_control_needs_no_form_and_preserves_intensity(self):
        state = self.start_imagery()
        card = state["next_card"]
        self.assertEqual(card["kind"], "chat_prompt")
        self.assertEqual(card["fields"], [])
        # The public v5 matrix separately pins actions=[]; this unreachable
        # v4 reducer is exercised only through the exact typed command, which
        # needs neither a form nor invented safety values.
        path = state["active_path"]
        link = path["active_technique_link"]
        before = self.row(
            "SELECT intensity_current FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))["intensity_current"]
        request, created = app.begin_chat_request(
            self.conv, "Şimdiye dön",
            request_id=self.request_id("ground-control"),
            schema_binding=dict(card["chat_binding"]))
        self.assertTrue(created)
        self.assertEqual(request["status"], "completed")
        self.assertIsNone(request["assistant_message"])
        grounded = self.dashboard()
        self.assertEqual(grounded["step"], "imagery_work")
        self.assertEqual(grounded["active_path"]["status"], "paused")
        run = self.row(
            "SELECT status,phase,intensity_current FROM technique_runs "
            "WHERE id=?", (link["technique_run_id"],))
        self.assertEqual((run["status"], run["phase"]),
                         ("paused", "grounding"))
        self.assertEqual(run["intensity_current"], before)

    def test_path_bound_cards_project_identity_for_chat_resume_blocked_complete(self):
        state, pairs = self.start_chat_only_path()

        def assert_path_identity(card, snapshot, expected_kind):
            path = snapshot["active_path"]
            self.assertEqual(card["kind"], expected_kind)
            self.assertEqual(card["path_id"], path["id"])
            self.assertEqual(card["path_public_id"], path["public_id"])
            self.assertEqual(card["revision"], path["revision"])
            self.assertEqual(card["stage"], path["stage"])
            self.assertEqual(card["step"], path["step"])
            self.assertTrue(app.TRANSFER_PUBLIC_ID_RE.fullmatch(
                card["path_public_id"]))

        chat_card = state["next_card"]
        assert_path_identity(chat_card, state, "chat_prompt")
        self.assertEqual(
            chat_card["chat_binding"]["path_id"], chat_card["path_id"])
        self.assertEqual(
            chat_card["chat_binding"]["path_public_id"],
            chat_card["path_public_id"])
        self.assertEqual(
            chat_card["chat_binding"]["expected_revision"],
            chat_card["revision"])

        # A real direct control request is built solely from the projected
        # card identity; it must remain executable without consulting a
        # desktop-only workspace or the hidden binding.
        status, paused = self.post({
            "action": "pause", "conv_id": self.conv,
            "path_id": chat_card["path_id"],
            "path_public_id": chat_card["path_public_id"],
            "expected_revision": chat_card["revision"],
            "request_id": self.request_id("identity-pause"),
        })
        self.assertEqual(status, 200, paused)
        resume = paused["next_card"]
        assert_path_identity(resume, paused, "resume")
        self.assertIsNone(resume["chat_binding"])

        status, resumed = self.post({
            "action": "resume_path", "conv_id": self.conv,
            "path_id": resume["path_id"],
            "path_public_id": resume["path_public_id"],
            "expected_revision": resume["revision"],
            "request_id": self.request_id("identity-resume"),
        })
        self.assertEqual(status, 200, resumed)
        assert_path_identity(resumed["next_card"], resumed, "chat_prompt")

        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv,))
            connection.execute(
                "UPDATE schema_paths SET status='paused',"
                "pause_reason='safety_hold',resume_required=1,"
                "revision=revision+1 WHERE id=?",
                (resumed["active_path"]["id"],))
        blocked_state = self.dashboard()
        blocked = blocked_state["next_card"]
        assert_path_identity(blocked, blocked_state, "blocked")
        self.assertIsNone(blocked["chat_binding"])

        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=0 WHERE id=?",
                (self.conv,))
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?",
                (blocked_state["active_path"]["id"],)).fetchone()
            pair = app.schema_exact_source_pair(
                connection, self.conv, pairs[-1]["user_message_id"],
                pairs[-1]["assistant_message_id"])
            app.schema_v4_set_state(
                connection, path, "complete", "complete", pair, {})
        completed_state = self.dashboard()
        complete = completed_state["next_card"]
        assert_path_identity(complete, completed_state, "chat_prompt")
        self.assertEqual(complete["status"], "completed")
        self.assertIsNone(complete["chat_binding"])
        self.assertEqual(complete["actions"], [])

    def test_escape_commands_bypass_provider_hold_and_sync_gates(self):
        # Provider/model re-confirmation never blocks an exact local stop.
        state, _pairs = self.start_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_mode_model='changed-model' "
                "WHERE conv=?", (self.conv,))
        with mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "Çalışmayı bitir",
                request_id=self.request_id("provider-exit"),
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(json.loads(
            row["schema_binding_result_json"])["action"], "stop")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?",
            (binding["path_id"],))["status"], "stopped")

        # Use a fresh conversation for held/conflicted paths.
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        state, _pairs = self.start_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                app.record_safety_event(
                    connection, self.conv,
                    {"detected": True, "kind": "current_risk",
                     "context": "chat", "detector_version": 1},
                    detector_context="chat")
                path = connection.execute(
                    "SELECT * FROM schema_paths WHERE id=?",
                    (binding["path_id"],)).fetchone()
        binding["expected_revision"] = int(path["revision"])
        with mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "Bu çalışmayı bırak",
                request_id=self.request_id("safety-exit"),
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        self.assertEqual(json.loads(
            row["schema_binding_result_json"])["action"], "stop")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?",
            (binding["path_id"],))["status"], "stopped")

        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        state, _pairs = self.start_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        with app.db() as connection:
            connection.execute(
                "INSERT INTO schema_path_sync_conflicts(public_id,conv,"
                "path_public_id,status,reason,created,updated) "
                "VALUES(?,?,?,'open','concurrent_path',?,?)",
                ("f" * 32, self.conv, binding["path_public_id"],
                 app.now(), app.now()))
        with mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "duraklat",
                request_id=self.request_id("conflict-pause"),
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        result = json.loads(row["schema_binding_result_json"])
        self.assertEqual(result["action"], "pause")
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?",
            (binding["path_id"],))["status"], "paused")

    def test_back_command_is_provider_free_but_not_authority_free(self):
        state, _pairs = self.focus_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_mode_model='changed-model' "
                "WHERE conv=?", (self.conv,))
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("provider must not be read")), \
                mock.patch.object(
                    app, "_configured_model_snapshot",
                    side_effect=AssertionError("model must not be read")), \
                mock.patch.object(app, "open_provider_url") as provider_call:
            row, created = app.begin_chat_request(
                self.conv, "Geri dön",
                request_id=self.request_id("provider-free-back"),
                schema_binding=binding)
            provider_call.assert_not_called()
        self.assertTrue(created)
        result = json.loads(row["schema_binding_result_json"])
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(result["step"], "method_confirm")
        self.assertEqual((row["provider"], row["model"]),
                         ("local-control", "fixed-response"))

        # A fresh active path with an unresolved clinical sync conflict may
        # not use the provider-free command as an authority bypass.
        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        state, _pairs = self.focus_chat_only_path()
        binding = dict(state["next_card"]["chat_binding"])
        with app.db() as connection:
            connection.execute(
                "INSERT INTO schema_path_sync_conflicts(public_id,conv,"
                "path_public_id,status,reason,created,updated) "
                "VALUES(?,?,?,'open','concurrent_path',?,?)",
                ("e" * 32, self.conv, binding["path_public_id"],
                 app.now(), app.now()))
        before = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"]
        with mock.patch.object(
                app, "selected_provider",
                side_effect=AssertionError("provider must not be read")), \
                mock.patch.object(
                    app, "_configured_model_snapshot",
                    side_effect=AssertionError("model must not be read")), \
                mock.patch.object(app, "open_provider_url") as provider_call:
            with self.assertRaises(app.RequestInputError) as rejected:
                app.begin_chat_request(
                    self.conv, "Bir adım geri",
                    request_id=self.request_id("conflicted-back"),
                    schema_binding=binding)
            provider_call.assert_not_called()
        self.assertEqual(rejected.exception.error_code,
                         "schema_sync_conflict")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?",
            (self.conv,))["n"], before)

    def test_legacy_start_and_path_mutations_cannot_bypass_v4_authority(self):
        pairs = self.completed_pairs(3)
        claim_id = self.approved_candidate(pairs[0])
        before = {
            "paths": self.row(
                "SELECT COUNT(*) AS n FROM schema_paths WHERE conv=?",
                (self.conv,))["n"],
            "events": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_events WHERE conv=?",
                (self.conv,))["n"],
        }
        status, body = self.post({
            "action": "start", "conv_id": self.conv,
            "claim_id": claim_id,
            "request_id": self.request_id("retired-legacy-start"),
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "schema_v4_action_required")
        self.assertEqual({
            "paths": self.row(
                "SELECT COUNT(*) AS n FROM schema_paths WHERE conv=?",
                (self.conv,))["n"],
            "events": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_events WHERE conv=?",
                (self.conv,))["n"],
        }, before)
        self.assertEqual(self.dashboard()["next_card"]["kind"],
                         "candidate_prompt")

        state, _pairs = self.method_confirm_chat_only_path()
        path_id = state["active_path"]["id"]
        baseline = self.row(
            "SELECT revision,phase,stage,step,method_node_id FROM "
            "schema_paths WHERE id=?", (path_id,))
        counts = {
            "choices": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_method_choices "
                "WHERE path=?", (path_id,))["n"],
            "checkpoints": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_checkpoints "
                "WHERE path=?", (path_id,))["n"],
            "events": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_events WHERE path=?",
                (path_id,))["n"],
        }
        legacy_payloads = (
            ("choose_method", {
                "confirmed": True,
                "method_id": "young:method:chair-dialogue",
                "precheck": {
                    "orientation_confirmed": True,
                    "reality_clear": True,
                    "sleep_activation_clear": True,
                    "intensity": 2,
                    "support_available": False,
                    "stop_signal": "dur",
                },
            }),
            ("link_technique", {"technique_run_id": 1}),
            ("record", {"kind": "current_trigger", "value": "sahte"}),
            ("advance", {"to_phase": "work"}),
            ("offer_focus", {"candidates": []}),
            ("choose_focus", {"mode_key": "detached_protector"}),
            ("decline_focus", {}),
        )
        for action, extra in legacy_payloads:
            status, body = self.post({
                "action": action, "conv_id": self.conv,
                "path_id": path_id,
                "expected_revision": baseline["revision"],
                "request_id": self.request_id("legacy-" + action),
                **extra,
            })
            self.assertEqual(status, 409, (action, body))
            self.assertEqual(body["error_code"],
                             "schema_v4_action_required", (action, body))
        self.assertEqual(dict(self.row(
            "SELECT revision,phase,stage,step,method_node_id FROM "
            "schema_paths WHERE id=?", (path_id,))), dict(baseline))
        self.assertEqual({
            "choices": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_method_choices "
                "WHERE path=?", (path_id,))["n"],
            "checkpoints": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_checkpoints "
                "WHERE path=?", (path_id,))["n"],
            "events": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_events WHERE path=?",
                (path_id,))["n"],
        }, counts)

    def test_historical_legacy_start_retry_is_exact_and_cannot_reopen_gate(self):
        payload = {
            "action": "start", "conv_id": self.conv,
            "claim_id": 77,
            "request_id": "schema-historical-start-retry-0001",
        }
        request_hash = app.schema_path_request_hash(payload)
        stored = {"ok": True, "sentinel": "historical-start-200"}
        with app.db() as connection:
            stamp = app.now()
            path_id = connection.execute(
                "INSERT INTO schema_paths(conv,therapist,claim,phase,"
                "status,flow_version,stage,step,created,updated) "
                "VALUES(?,'young',NULL,'explore','stopped',3,'listen',"
                "'listen',?,?)", (self.conv, stamp, stamp)).lastrowid
            event_id = app.schema_path_insert_event(
                connection, path_id, self.conv, "start",
                payload["request_id"], request_hash,
                payload={"claim_id": payload["claim_id"]})
            app.schema_path_store_response(connection, event_id, stored)
        before = {
            "paths": self.row(
                "SELECT COUNT(*) AS n FROM schema_paths WHERE conv=?",
                (self.conv,))["n"],
            "events": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_events WHERE conv=?",
                (self.conv,))["n"],
        }

        status, replay = self.post(payload)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay, stored)

        status, fresh = self.post({
            **payload,
            "request_id": "schema-historical-start-fresh-0001",
        })
        self.assertEqual(status, 409, fresh)
        self.assertEqual(fresh["error_code"], "schema_v4_action_required")

        status, divergent = self.post({**payload, "claim_id": 78})
        self.assertEqual(status, 409, divergent)
        other_conv = self.conversation(therapist="young")
        status, wrong_conv = self.post({**payload, "conv_id": other_conv})
        self.assertEqual(status, 409, wrong_conv)
        self.assertEqual({
            "paths": self.row(
                "SELECT COUNT(*) AS n FROM schema_paths WHERE conv=?",
                (self.conv,))["n"],
            "events": self.row(
                "SELECT COUNT(*) AS n FROM schema_path_events WHERE conv=?",
                (self.conv,))["n"],
        }, before)

    def test_exact_source_pair_accepts_only_live_safe_synced_message_pair(self):
        stamp = app.now()
        with app.db() as connection:
            sync._sync_tables(connection)

            def message(public_id, role, content, pair_public_id=""):
                return connection.execute(
                    "INSERT INTO messages(public_id,conv,role,content,"
                    "created,turn_pair_public_id,delivery_status) "
                    "VALUES(?,?,?,?,?,?,'completed')",
                    (public_id, self.conv, role, content, stamp,
                     pair_public_id)).lastrowid

            pair_public_id = "8" * 32
            user_id = message(
                "1" * 32, "user", "Eşitlenmiş kullanıcı",
                pair_public_id)
            assistant_id = message(
                "2" * 32, "assistant", "Eşitlenmiş yardımcı",
                pair_public_id)
            for local_id, public_id in (
                    (user_id, "1" * 32), (assistant_id, "2" * 32)):
                connection.execute(
                    "INSERT INTO sync_records(record_type,local_id,public_id,"
                    "revision,origin_device_id,updated_at,deleted_at,"
                    "payload_hash) VALUES('message',?,?,1,'remote-device',"
                    "?,NULL,?)",
                    (local_id, public_id, stamp, public_id))

            resolved = app.schema_exact_source_pair(
                connection, self.conv, user_id, assistant_id)
            self.assertEqual(
                (resolved["user_message_id"],
                 resolved["assistant_message_id"]),
                (user_id, assistant_id))

            unrelated_assistant = message(
                "7" * 32, "assistant", "Daha sonraki ilgisiz yardımcı",
                "9" * 32)
            connection.execute(
                "INSERT INTO sync_records(record_type,local_id,public_id,"
                "revision,origin_device_id,updated_at,deleted_at,"
                "payload_hash) VALUES('message',?,?,1,'remote-device',"
                "?,NULL,?)",
                (unrelated_assistant, "7" * 32, stamp, "7" * 32))
            with self.assertRaises(app.RequestInputError):
                app.schema_exact_source_pair(
                    connection, self.conv, user_id, unrelated_assistant)

            local_pair = "a" * 32
            local_user = message(
                "3" * 32, "user", "Yerel sahte kullanıcı", local_pair)
            local_assistant = message(
                "4" * 32, "assistant", "Yerel sahte yardımcı",
                local_pair)
            with self.assertRaises(app.RequestInputError):
                app.schema_exact_source_pair(
                    connection, self.conv, local_user, local_assistant)

            connection.execute(
                "UPDATE sync_records SET deleted_at=? WHERE record_type="
                "'message' AND local_id=?", (stamp, assistant_id))
            with self.assertRaises(app.RequestInputError):
                app.schema_exact_source_pair(
                    connection, self.conv, user_id, assistant_id)
            connection.execute(
                "UPDATE sync_records SET deleted_at=NULL WHERE record_type="
                "'message' AND local_id=?", (assistant_id,))
            connection.execute(
                "INSERT INTO safety_events(conv,source_message,kind,"
                "detector_context,status,created) "
                "VALUES(?,?,'test','source','released',?)",
                (self.conv, user_id, stamp))
            with self.assertRaises(app.RequestInputError):
                app.schema_exact_source_pair(
                    connection, self.conv, user_id, assistant_id)

            reversed_assistant = message(
                "5" * 32, "assistant", "Önce gelen yardımcı", "b" * 32)
            reversed_user = message(
                "6" * 32, "user", "Sonra gelen kullanıcı", "b" * 32)
            for local_id, public_id in (
                    (reversed_assistant, "5" * 32),
                    (reversed_user, "6" * 32)):
                connection.execute(
                    "INSERT INTO sync_records(record_type,local_id,public_id,"
                    "revision,origin_device_id,updated_at,deleted_at,"
                    "payload_hash) VALUES('message',?,?,1,'remote-device',"
                    "?,NULL,?)",
                    (local_id, public_id, stamp, public_id))
            shuffled = app.schema_exact_source_pair(
                connection, self.conv, reversed_user, reversed_assistant)
            self.assertEqual(
                (shuffled["user_message_id"],
                 shuffled["assistant_message_id"]),
                (reversed_user, reversed_assistant))

    def test_turn_pair_identity_is_written_and_legacy_completed_turn_is_backfilled(self):
        stamp = app.now()
        legacy_request_id = "schema-legacy-pair-backfill-0001"
        with app.db() as connection:
            user_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user','Eski kullanıcı turu',?)",
                (self.conv, stamp)).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'assistant','Eski yardımcı turu',?)",
                (self.conv, stamp)).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'succeeded',?,?)",
                (self.conv, stamp, stamp)).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,created,updated) "
                "VALUES(?,?,?,?,?,'completed',?,?)",
                (legacy_request_id, job_id, self.conv, user_id,
                 assistant_id, stamp, stamp))
        app.init_db()
        expected = app._chat_turn_pair_public_id(legacy_request_id)
        self.assertEqual([
            row["turn_pair_public_id"] for row in self.rows(
                "SELECT turn_pair_public_id FROM messages WHERE id IN (?,?) "
                "ORDER BY role DESC", (user_id, assistant_id))
        ], [expected, expected])

        new_request_id = "schema-new-pair-written-0001"
        request_row, created = app.begin_chat_request(
            self.conv, "Yeni normal tur", request_id=new_request_id)
        self.assertTrue(created)
        with app.db() as connection:
            assistant = app._upsert_chat_assistant(
                connection, request_row, "Yeni normal yanıt", "completed")
            pair_rows = connection.execute(
                "SELECT role,turn_pair_public_id FROM messages "
                "WHERE id IN (?,?) ORDER BY role",
                (request_row["user_message"], assistant)).fetchall()
            index_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='messages_turn_pair_role'").fetchone()[0]
        new_expected = app._chat_turn_pair_public_id(new_request_id)
        self.assertEqual({row["turn_pair_public_id"] for row in pair_rows},
                         {new_expected})
        self.assertIn("turn_pair_public_id,role", index_sql.replace(" ", ""))

    def test_legacy_resume_alias_uses_pending_backtrack_coordinator(self):
        state = self.start_imagery_chat_only()
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Bir adım geri")
        self.assertEqual(result["action"], "backtrack_grounding_required")
        pending = dict(state["next_card"]["checkpoint"])
        self.assertTrue(pending["backtrack_pending"])
        status, paused = self.mutate("pause")
        self.assertEqual(status, 200, paused)
        path = paused["active_path"]
        status, resumed = self.post({
            "action": "resume", "conv_id": self.conv,
            "path_id": path["id"],
            "expected_revision": path["revision"],
            "request_id": self.request_id("legacy-resume-alias"),
        })
        self.assertEqual(status, 200, resumed)
        self.assertEqual(resumed["next_card"]["checkpoint"]["public_id"],
                         pending["public_id"])
        self.assertTrue(resumed["next_card"]["checkpoint"][
            "backtrack_pending"])
        result, state, _user, _assistant = self.complete_chat_only_turn(
            "Buradayım; bu bir çalışma olduğunu biliyorum; yoğunluk 2/7.")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["backtracked"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        self.assertFalse(state["next_card"]["checkpoint"][
            "backtrack_pending"])

    def test_v4_requires_three_safe_pairs_and_legacy_reducer_source(self):
        pairs = self.completed_pairs(2)
        claim_id = self.approved_candidate(pairs[0])
        body = self.dashboard()
        self.assertNotEqual((body.get("next_card") or {}).get("kind"),
                            "candidate_prompt")
        self.assertIsNone(body["active_path"])

        self.completed_pair("Üçüncü tamamlanmış güvenli kaynak")
        card = self.dashboard()["next_card"]
        self.assertEqual(card["kind"], "candidate_prompt")
        status, body = self.post_card_action(
            card, "accept_candidate_chat", "three-pair-yes")
        self.assertEqual(status, 200, body)
        body = self._convert_v5_start_to_internal_v4(body)
        # Complete focus from the current test state.
        candidate = body["active_path"]["current_candidate"]
        cref = {
            "candidate_queue_id": candidate["id"],
            "candidate_queue_public_id": candidate["public_id"],
        }
        self.assertEqual(self.mutate(
            "rate_current_situation", **cref, burden=6,
            impact="İlişkide geri çekiliyorum", priority="now")[0], 200)
        self.assertEqual(self.mutate(
            "record_variable_check", **cref, baseline_burden=6,
            variable="sakin ton", changed_scenario="sakin konuşma",
            changed_burden=3, fit="yes")[0], 200)
        self.assertEqual(self.mutate(
            "confirm_focus", **cref, confirmed=True)[0], 200)

        method_result, method_state, _method_user, _method_assistant = \
            self.complete_bound_turn("Çalışalım", None)
        self.assertTrue(method_result["applied"], method_result)
        self.assertEqual(method_state["step"], "origin_or_unknown")

        result, state, user_id, _assistant_id = self.complete_bound_turn(
            "Form alanlarını ayrıca tekrar etmeyen doğal kısa cevap.", {
                "confidence": "reported", "age": 9,
                "scene": "Pencerede tek başıma beklediğim sahne",
                "unmet_need": "Güven veren bir yetişkin",
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "imagery_precheck")
        origin = self.row(
            "SELECT * FROM schema_origin WHERE path=?",
            (state["active_path"]["id"],))
        self.assertEqual(origin["age_reported"], 9)
        self.assertEqual(origin["source_user_message"], user_id)
        saved = self.row(
            "SELECT schema_binding_json FROM chat_requests "
            "WHERE user_message=?", (user_id,))
        self.assertEqual(
            json.loads(saved["schema_binding_json"])["step_data"]["scene"],
            "Pencerede tek başıma beklediğim sahne")

    def test_concurrent_v4_start_has_one_natural_path(self):
        pairs = self.completed_pairs(3)
        self.approved_candidate(pairs[0])
        card = self.dashboard()["next_card"]
        action = next(item for item in card["actions"]
                      if item["action"] == "accept_candidate_chat")
        payloads = [{
            "action": "accept_candidate_chat", "conv_id": self.conv,
            **action["payload"],
            "request_id": "schema-v4-concurrent-start-{}".format(index),
        } for index in (1, 2)]

        def submit(payload):
            return self.request("POST", "/api/schema-path", payload)[:2]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, payloads))
        self.assertEqual(sorted(status for status, _body in results),
                         [200, 409])
        paths = self.rows(
            "SELECT * FROM schema_paths WHERE conv=? AND flow_version=5",
            (self.conv,))
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["path_sequence"], 1)
        expected = app._schema_natural_public_id(
            "path", self.conversation_row(self.conv)["public_id"],
            paths[0]["clinical_generation"], 1)
        self.assertEqual(paths[0]["public_id"], expected)

    def test_reject_candidate_advances_atomically_then_returns_to_listen(self):
        pairs = self.completed_pairs(3)
        first_claim = self.approved_candidate(pairs[0])
        second_claim = self.approved_candidate(pairs[1])
        first = self.dashboard()["next_card"]
        request_id = self.request_id("reject-first")
        reject = next(item for item in first["actions"]
                      if item["action"] == "reject_candidate_chat")
        shown_first_claim = reject["payload"]["claim_id"]
        self.assertIn(shown_first_claim, (first_claim, second_claim))
        payload = {"action": "reject_candidate_chat",
                   "conv_id": self.conv, "request_id": request_id,
                   **reject["payload"]}
        status, state = self.post(payload)
        self.assertEqual(status, 200, state)
        second = state["next_card"]
        self.assertEqual(second["kind"], "candidate_prompt")
        second_reject = next(item for item in second["actions"]
                             if item["action"] == "reject_candidate_chat")
        shown_second_claim = second_reject["payload"]["claim_id"]
        self.assertEqual(
            {shown_first_claim, shown_second_claim},
            {first_claim, second_claim})
        self.assertIsNone(state["active_path"])
        # A transport retry returns the original durable projection and never
        # rejects the newly offered sibling.
        retry_status, retry = self.post(payload)
        self.assertEqual(retry_status, 200, retry)
        self.assertEqual(retry["next_card"]["candidate"]["public_id"],
                         second["candidate"]["public_id"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_events WHERE request_id=?",
            (request_id,))["n"], 1)

        status, state = self.post_card_action(
            second, "reject_candidate_chat", "reject-second")
        self.assertEqual(status, 200, state)
        self.assertIsNone(state["active_path"])
        self.assertNotEqual((state.get("next_card") or {}).get("kind"),
                            "candidate_prompt")
        self.assertTrue(state["interaction_policy"]["composer_allowed"])
        self.assertFalse(
            state["interaction_policy"]["composer_binding_required"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims WHERE id IN (?,?) "
            "AND status='rejected'", (first_claim, second_claim))["n"], 2)

    def test_pathless_listening_map_is_visible_and_reversible(self):
        pair = self.completed_pair(
            "Gerilince geri çekiliyorum ve biraz alana ihtiyaç duyuyorum.")
        with app.db() as connection:
            conv = connection.execute(
                "SELECT * FROM conversations WHERE id=?", (self.conv,)
            ).fetchone()
            app._record_map_notes(
                connection, conv, pair["assistant_message_id"], [{
                    "category": "dongu", "section": "cycles",
                    "claim_type": "pattern",
                    "note": "Gerilince geri çekiliyorum",
                }], user_message_id=pair["user_message_id"])
            inserted = app.schema_v4_record_map_meta_for_pair(
                connection, self.conv, pair["user_message_id"],
                pair["assistant_message_id"])
        self.assertEqual(len(inserted), 1)
        self.assertIsNone(inserted[0]["path"])
        state = self.dashboard()
        self.assertIsNone(state["active_path"])
        meta = next(item for item in state["message_meta"]
                    if item["public_id"] == inserted[0]["public_id"])
        self.assertEqual(meta["kind"], "map_update")
        self.assertEqual(meta["step"], "listen")
        self.assertIsNone(meta["path_id"])
        self.assertEqual(
            {item["action"] for item in meta["actions"]},
            {"undo_map_update", "make_map_update_private",
             "edit_map_update"})

        edit = next(item for item in meta["actions"]
                    if item["action"] == "edit_map_update")
        status, state = self.post({
            "action": "edit_map_update", "conv_id": self.conv,
            **edit["payload"], "note": "Gerilimde geri çekilme döngüsü",
            "request_id": self.request_id("pathless-edit"),
        })
        self.assertEqual(status, 200, state)
        meta = next(item for item in state["message_meta"]
                    if item["id"] == meta["id"])
        private = next(item for item in meta["actions"]
                       if item["action"] == "make_map_update_private")
        status, state = self.post({
            "action": "make_map_update_private", "conv_id": self.conv,
            **private["payload"],
            "request_id": self.request_id("pathless-private"),
        })
        self.assertEqual(status, 200, state)
        meta = next(item for item in state["message_meta"]
                    if item["id"] == meta["id"])
        self.assertEqual(meta["status"], "private")
        undo = next(item for item in meta["actions"]
                    if item["action"] == "undo_map_update")
        status, state = self.post({
            "action": "undo_map_update", "conv_id": self.conv,
            **undo["payload"],
            "request_id": self.request_id("pathless-undo"),
        })
        self.assertEqual(status, 200, state)
        meta = next(item for item in state["message_meta"]
                    if item["id"] == meta["id"])
        self.assertEqual(meta["status"], "undone")
        self.assertEqual(meta["actions"], [])

    def test_prepath_prompt_is_short_label_free_and_card_authoritative(self):
        provider = app.selected_provider()
        model = app._configured_model_snapshot(provider)
        conv = self.conversation_row(self.conv)
        prompt = app.schema_path_prompt_context(conv)
        self.assertIn("en fazla bir kısa yansıtma ve bir açık soru", prompt)
        self.assertIn("çalışma yolu yok", prompt)
        self.assertIn("çalışma yolu başlatılmış gibi konuşma", prompt)
        self.assertEqual(app.schema_inline_suggestion_prompt(
            conv, provider_id=provider, model_id=model), "")

        self.completed_pair("İlk güvenli dinleme kaynağı")
        conv = self.conversation_row(self.conv)
        self.assertEqual(app.schema_inline_suggestion_prompt(
            conv, provider_id=provider, model_id=model), "")
        self.assertIn("ilk iki güvenli dinleme",
                      app.schema_path_prompt_context(conv))

        self.completed_pair("İkinci güvenli dinleme kaynağı")
        conv = self.conversation_row(self.conv)
        inline = app.schema_inline_suggestion_prompt(
            conv, provider_id=provider, model_id=model)
        self.assertIn(app.SCHEMA_SUGGESTION_MARK, inline)
        self.assertIn("yalnız ayrı, kaynak-alıntılı kartlarda", inline)
        self.assertNotIn("Hangisiyle başlamak istersin", inline)
        self.assertIn("karar ve başlangıç yine kullanıcıdadır",
                      app.schema_path_prompt_context(conv))

    def test_not_now_atomically_offers_next_candidate_and_retry_is_idempotent(self):
        state, _pairs, _claim = self.start_v4()
        path = state["active_path"]
        first = path["current_candidate"]
        second = self.add_deferred_candidate(path["id"])
        first_ref = {
            "candidate_queue_id": first["id"],
            "candidate_queue_public_id": first["public_id"],
        }
        request = {
            "action": "rate_current_situation", "conv_id": self.conv,
            "path_id": path["id"],
            "expected_revision": path["revision"],
            "request_id": self.request_id("not-now-idempotent"),
            **first_ref, "burden": 6,
            "impact": "Bugün geri çekilmeme yol açıyor.",
            "priority": "not_now",
        }
        status, first_response = self.post(request)
        self.assertEqual(status, 200, first_response)
        status, retry_response = self.post(request)
        self.assertEqual(status, 200, retry_response)
        self.assertEqual(first_response, retry_response)
        self.assertEqual(first_response["step"], "candidate_review")
        offered = self.row(
            "SELECT * FROM schema_candidate_queue WHERE path=? AND "
            "status='offered'", (path["id"],))
        self.assertEqual(offered["public_id"], second["public_id"])
        second_ref = {
            "candidate_queue_id": second["id"],
            "candidate_queue_public_id": second["public_id"],
        }
        status, state = self.mutate(
            "rate_current_situation", **second_ref, transition_only=True)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "current_impact")

    def test_variable_no_offers_next_then_queue_exhaustion_returns_listen(self):
        state, _pairs, _claim = self.start_v4()
        path = state["active_path"]
        first = path["current_candidate"]
        second = self.add_deferred_candidate(path["id"])
        first_ref = {
            "candidate_queue_id": first["id"],
            "candidate_queue_public_id": first["public_id"],
        }
        status, state = self.mutate(
            "rate_current_situation", **first_ref, burden=7,
            impact="Bugün ilişkiden geri çekilmeme yol açıyor.",
            priority="now")
        self.assertEqual(status, 200, state)
        status, state = self.mutate(
            "record_variable_check", **first_ref, baseline_burden=7,
            variable="Karşımdakinin sakin kalması",
            changed_scenario="Aynı konu sakin biçimde konuşuluyor.",
            changed_burden=7, fit="no")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "candidate_review")
        offered = self.row(
            "SELECT * FROM schema_candidate_queue WHERE path=? AND "
            "status='offered'", (path["id"],))
        self.assertEqual(offered["public_id"], second["public_id"])
        status, state = self.mutate(
            "reject_candidate", candidate_queue_id=second["id"],
            candidate_queue_public_id=second["public_id"])
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "listen")
        self.assertEqual(state["next_card"]["kind"], "chat_prompt")
        self.assertEqual(
            state["interaction_policy"]["composer_mode"], "bound")
        self.assertTrue(state["interaction_policy"]["composer_allowed"])

    def test_experiential_skips_are_visible_durable_and_create_no_run(self):
        state, _pairs, _claim = self.focus_path()
        status, state = self.mutate(
            "skip_step", step_id="origin_or_unknown")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "imagery_precheck")
        self.assertNotIn("skip_step", {
            action["action"] for action in state["next_card"]["actions"]})
        self.assertEqual(state["next_card"]["fields"], [])

        status, state = self.mutate(
            "skip_step", step_id="imagery_precheck")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "healthy_adult_voice")
        reloaded = self.dashboard()
        self.assertEqual(reloaded["step"], "healthy_adult_voice")
        self.assertEqual(reloaded["active_path"]["revision"],
                         state["active_path"]["revision"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE conv=?",
            (self.conv,))["n"], 0)

    def test_bound_imagery_provider_prompt_uses_only_current_protocol_stage(self):
        state = self.start_imagery()
        card = state["next_card"]
        choice = next((
            option["value"] for field in card["fields"]
            if field["id"] == "choice" for option in field["options"]), None)
        turn_text = "Sınırı kapının dışında tutmayı ben seçiyorum."
        step_data = {
            "content": turn_text, "orientation_ok": True,
            "reality_clear": True, "intensity": 2,
        }
        if choice:
            step_data["choice"] = choice
        result, state, _user, _assistant = self.complete_bound_turn(
            turn_text, step_data)
        self.assertTrue(result["applied"], result)
        link = state["active_path"]["active_technique_link"]
        run = self.row(
            "SELECT * FROM imagery_runs WHERE technique_run=?",
            (link["technique_run_id"],))
        config = app.imagery_method_config(link["method_id"])
        stages = list(config["stages"])
        current_index = next(
            index for index, item in enumerate(stages)
            if item["id"] == run["current_stage"])
        current = stages[current_index]
        future = stages[current_index + 1]
        prompt_text = "Bu mikro aşamada yazdığım yeni cevabım."
        system = self.bound_provider_system_prompt(prompt_text, {
            "content": prompt_text, "orientation_ok": True,
            "reality_clear": True, "intensity": 2,
        })
        for exact in (config["title"], config["frame"], current["label"],
                      current["aim"], turn_text):
            self.assertIn(exact, system)
        self.assertIn(current["prompt"], state["next_card"]["body"])
        self.assertNotIn(current["prompt"], system)
        self.assertNotIn(future["prompt"], system)
        self.assertIn("Yalnız en fazla bir kısa, ihtiyatlı yansıtma", system)
        self.assertIn("Soru sorma", system)
        self.assertNotIn("Soru politikası:", system)
        self.assertTrue(system.rstrip().endswith(
            "sunucu tarafından eklenecek."))
        self.assertIn("tarihsel kanıt değildir", system)
        self.assertIn("ebeveyn, bağlanma figürü veya gerçek terapist", system)

    def test_bound_provider_reflects_before_reducer_owned_next_question(self):
        state, _pairs = self.start_chat_only_path()
        answered_prompt = state["next_card"]["body"]
        self.assertIn("yükü", answered_prompt)
        system = self.bound_provider_system_prompt("7", None, cleanup=True)
        self.assertNotIn(answered_prompt, system)
        self.assertNotIn("Soru politikası:", system)
        self.assertIn("Soru sorma", system)
        self.assertTrue(system.rstrip().endswith(
            "sunucu tarafından eklenecek."))
        result, state, _user, _assistant = self.complete_chat_only_turn("7")
        self.assertTrue(result["applied"], result)
        self.assertTrue(result["followup_required"], result)
        self.assertEqual(state["step"], "current_impact")
        self.assertEqual(
            state["next_card"]["body"],
            "Bu örüntü bugün hayatında en çok neyi etkiliyor?")
        self.assertNotEqual(state["next_card"]["body"], answered_prompt)

    def test_bound_mode_dialogue_prompt_has_current_stage_roles_and_user_turns(self):
        state, _pairs = self.method_confirm_chat_only_path()
        for answer, expected in (
                ("Hayır", "method_select"),
                ("Sandalye diyaloğunu seçiyorum", "method_confirm"),
                ("Bugün bunu çalışalım", "origin_or_unknown"),
                ("Hatırlamıyorum", "mode_dialogue")):
            result, state, _user, _assistant = \
                self.complete_chat_only_turn(answer)
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["step"], expected)
        status, state = self.mutate(
            "start_chat_technique",
            method_id="young:method:chair-dialogue",
            orientation_confirmed=True, reality_clear=True,
            sleep_activation_clear=True, intensity=2,
            support_available=True, stop_signal="dur")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["active_path"]["method_id"],
                         "young:method:chair-dialogue")
        user_turn = "Kırılgan yanım bu anda görülmek istediğini söylüyor."
        result, state, _user, _assistant = self.complete_bound_turn(
            user_turn, {"content": user_turn,
                        "orientation_ok": True, "intensity": 2})
        self.assertTrue(result["applied"], result)
        link = state["active_path"]["active_technique_link"]
        chair = self.row(
            "SELECT * FROM chair_runs WHERE technique_run=?",
            (link["technique_run_id"],))
        config, stages, stage_index = app.chair_stage_contract(chair)
        current = stages[stage_index]
        future = stages[stage_index + 1]
        next_turn = "Bu turda kendi parçamın sözünü ben yazıyorum."
        system = self.bound_provider_system_prompt(next_turn, {
            "content": next_turn, "orientation_ok": True, "intensity": 2,
        })
        for exact in (config["title"], config["frame"], current["label"],
                      current["aim"], user_turn):
            self.assertIn(exact, system)
        self.assertIn(current["prompt"], state["next_card"]["body"])
        self.assertNotIn(current["prompt"], system)
        self.assertNotIn(future["prompt"], system)
        for label in (
                "Kırılgan Çocuk", "Eleştirel/Talepkâr Ebeveyn",
                "Başa çıkma modu", "Sağlıklı Yetişkin"):
            self.assertIn(label, system)
        self.assertIn("Hiçbir parçanın yerine konuşma", system)
        self.assertIn("Yalnız en fazla bir kısa, ihtiyatlı yansıtma", system)
        self.assertIn("Soru sorma", system)
        self.assertNotIn("Soru politikası:", system)
        self.assertTrue(system.rstrip().endswith(
            "sunucu tarafından eklenecek."))

    def test_real_imagery_reducer_method_gate_and_grounding_action_policy(self):
        state, _pairs, _claim = self.focus_path()
        _result, state, _user, _assistant = self.complete_bound_turn(
            "En erken izi yalnız benim bildirdiğim kadar kaydet.", {
                "confidence": "uncertain",
            })
        self.assertEqual(state["step"], "imagery_precheck")
        status, body = self.mutate(
            "start_chat_technique",
            method_id="young:method:chair-dialogue",
            orientation_confirmed=True, reality_clear=True,
            sleep_activation_clear=True, intensity=3,
            support_available=True, stop_signal="dur")
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "schema_method_step_mismatch")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM technique_runs WHERE conv=?",
            (self.conv,))["n"], 0)

        state = self.start_imagery_from_existing_path()
        card = state["next_card"]
        option = next((option["value"] for field in card["fields"]
                       if field["id"] == "choice"
                       for option in field["options"]), None)
        step_data = {
            "content": "Bu sınır uygun ve kapının dışında kalıyorum.",
            "orientation_ok": True, "reality_clear": True,
            "intensity": 3,
        }
        if option:
            step_data["choice"] = option
        result, state, _user, _assistant = self.complete_bound_turn(
            step_data["content"], step_data)
        self.assertTrue(result["applied"], result)
        imagery = self.row(
            "SELECT * FROM imagery_runs WHERE technique_run=?",
            (state["active_path"]["active_technique_link"][
                "technique_run_id"],))
        self.assertGreaterEqual(imagery["revision"], 2)
        self.assertNotEqual(imagery["current_stage"], "boundary")

        link = state["active_path"]["active_technique_link"]
        status, state = self.mutate(
            "ground_chat_technique", step_id=state["step"],
            technique_link_id=link["id"],
            expected_technique_revision=link["technique_revision"],
            orientation_ok=True, intensity=2)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["next_card"]["kind"], "chat_prompt")
        self.assertEqual(state["next_card"]["fields"], [])
        self.assertTrue(
            state["interaction_policy"]["composer_binding_required"])

        link = state["active_path"]["active_technique_link"]
        status, state = self.mutate(
            "complete_chat_technique", step_id=state["step"],
            technique_link_id=link["id"],
            expected_technique_revision=link["technique_revision"],
            grounding_confirmed=True, orientation_ok=True,
            reality_clear=True, intensity=2)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "healthy_adult_voice")
        self.assertEqual(state["next_card"]["kind"], "chat_prompt")
        self.assertEqual(state["next_card"]["fields"], [])
        self.assertTrue(
            state["interaction_policy"]["composer_binding_required"])
        self.assertIsNone(state["active_path"]["active_technique_link"])
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_techniques WHERE path=?",
            (state["active_path"]["id"],))["n"], 1)

    def start_imagery_from_existing_path(self):
        precheck = {
            "method_id": app.IMAGERY_METHOD_NODE_ID,
            "orientation_confirmed": True,
            "reality_clear": True,
            "sleep_activation_clear": True,
            "intensity": 3,
            "support_available": False,
            "stop_signal": "dur",
        }
        status, state = self.mutate("start_chat_technique", **precheck)
        self.assertEqual(status, 200, state)
        self.assertEqual(state["step"], "imagery_work")
        return state

    def test_notification_prepath_candidate_is_redacted(self):
        pairs = self.completed_pairs(3)
        self.approved_candidate(pairs[0])
        contexts = app.notification_contexts(allow_preview=True)["contexts"]
        self.assertTrue(contexts)
        latest = contexts[-1]
        self.assertTrue(latest["requires_in_app"])
        self.assertFalse(latest["preview_allowed"])
        self.assertFalse(latest["reply_allowed"])
        self.assertEqual(latest["content"], "")
        direct = app.latest_notification_context(self.conv)
        self.assertTrue(direct["requires_in_app"])
        self.assertEqual(direct["content"], "")
        self.assertEqual(direct["user_content"], "")

    def test_android_notification_reply_is_closed_for_method_checkpoints_and_pause(self):
        state, _pairs = self.method_confirm_chat_only_path()
        path_id = state["active_path"]["id"]
        for index, (step, path_status) in enumerate((
                ("method_select", "active"),
                ("method_confirm", "active"),
                ("method_confirm", "paused")), 1):
            with app.db() as connection:
                connection.execute(
                    "UPDATE schema_paths SET step=?,status=? WHERE id=?",
                    (step, path_status, path_id))
            contexts = app.notification_contexts(
                allow_preview=True)["contexts"]
            latest = contexts[-1]
            self.assertTrue(latest["requires_in_app"])
            self.assertFalse(latest["preview_allowed"])
            self.assertFalse(latest["reply_allowed"])
            self.assertEqual(latest["content"], "")
            status, body, _headers = self.request(
                "POST", "/api/notification-reply", {
                    "conversation_id": self.conv,
                    "message": "Bildirimden devam",
                    "request_id": "schema-native-reply-{:04d}".format(
                        index),
                    "source_id": latest["request_id"],
                    "reply_to": latest["message_id"],
                })
            self.assertEqual(status, 409, body)
            self.assertEqual(body["error_code"],
                             "notification_reply_requires_app")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM chat_requests WHERE request_id LIKE "
            "'schema-native-reply-%'")["n"], 0)

    def test_forged_legacy_markers_are_inert_on_v4_path(self):
        state, pairs, _claim = self.focus_path()
        path_id = state["active_path"]["id"]
        before = self.row(
            "SELECT stage,step,phase,revision FROM schema_paths WHERE id=?",
            (path_id,))
        marker_text = (
            "Kısa güvenli yanıt.\n"
            "[[FAZ]] complete | çalışma bitti\n"
            "[[KAYIT]] tetikleyici | Doğrudan kullanıcı kaynağı 0")
        (visible, _suggestion, phase_request, technique, map_notes,
         stage_records) = app.split_schema_markers(marker_text)
        self.assertNotIn("[[", visible)
        with app.db() as connection:
            app._record_message_technique(
                connection, self.conv,
                pairs[0]["assistant_message_id"], technique, phase_request,
                map_notes, stage_records,
                pairs[0]["user_message_id"], app.selected_provider(),
                app._configured_model_snapshot(app.selected_provider()))
        after = self.row(
            "SELECT stage,step,phase,revision FROM schema_paths WHERE id=?",
            (path_id,))
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_path_events WHERE path=? "
            "AND action='record'", (path_id,))["n"], 0)
        prompt = app.schema_flow_marker_prompt(
            self.conversation_row(self.conv))
        self.assertNotIn("[[FAZ]]", prompt)
        self.assertNotIn("[[KAYIT]]", prompt)

    def test_age_ladder_environment_and_present_transfer_are_user_authored(self):
        state, pairs, _claim = self.focus_path()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            pair = app.schema_exact_source_pair(
                connection, self.conv, pairs[0]["user_message_id"],
                pairs[0]["assistant_message_id"])
            app.schema_v4_set_state(
                connection, path, "integrate", "healthy_adult_voice", pair,
                {"test_setup": True})

        result, state, healthy_user, healthy_assistant = self.complete_bound_turn(
            "Kısa doğal cevabım.", {
                "evidence": "Bugün sınırımı sakin biçimde söyleyebilirim",
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "age_ladder")
        healthy = state["healthy_adult"]["recent"][0]
        self.assertEqual(healthy["source_user_message_id"], healthy_user)
        self.assertEqual(healthy["source_assistant_message_id"],
                         healthy_assistant)
        self.assertTrue(healthy["source_user_message_public_id"])
        self.assertTrue(healthy["source_assistant_message_public_id"])

        self.assertEqual(state["next_card"]["fields"], [])
        bad_binding = dict(state["next_card"]["chat_binding"])
        bad_binding["step_data"] = {
            "age": 8, "label": "İlkokul dönemi",
            "now_response": "Bugün konuşabilirim",
            "continue_ladder": "true",
        }
        status, bad, _headers = self.request("POST", "/api/chat", {
            "conv_id": self.conv,
            "message": "Türü bozulmuş seçenek gönderilmeye çalışıldı.",
            "request_id": self.request_id("bad-age-radio"),
            "schema_binding": bad_binding,
        })
        self.assertEqual(status, 409, bad)
        self.assertEqual(bad["error_code"], "schema_chat_only_step_data")

        result, state, _user, _assistant = self.complete_bound_turn(
            "Bu formu kendim doldurdum.", {
                "age": 8, "label": "İlkokul dönemi",
                "then_response": "O zaman saklanırdım",
                "now_response": "Bugün konuşabilirim",
                "difference": "Artık seçim yapabiliyorum",
                "continue_ladder": True,
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "age_ladder")
        self.assertEqual(self.row(
            "SELECT stage_age FROM schema_growth WHERE path=? ORDER BY seq",
            (path_id,))["stage_age"], 8)

        result, state, duplicate_user, duplicate_assistant = self.complete_bound_turn(
            "Yine kendi form yanıtım.", {
                "age": 8, "label": "Tekrar",
                "now_response": "Başka bir yanıt", "continue_ladder": True,
            })
        self.assertFalse(result["applied"])
        self.assertEqual(result["error_code"], "schema_growth_age_order")
        self.assertEqual(state["step"], "age_ladder")
        status, status_body, _headers = self.request(
            "GET", "/api/chat-status?conv_id={}".format(self.conv))
        self.assertEqual(status, 200, status_body)
        self.assertEqual(
            status_body["chat"]["schema_binding_result"]["error_code"],
            "schema_growth_age_order")
        status, conversation_body, _headers = self.request(
            "GET", "/api/conversation?id={}".format(self.conv))
        self.assertEqual(status, 200, conversation_body)
        reloaded = next(item for item in conversation_body["messages"]
                        if item["id"] == duplicate_user)
        self.assertEqual(
            reloaded["schema_binding_result"]["error_code"],
            "schema_growth_age_order")
        assistant_reload = next(
            item for item in conversation_body["messages"]
            if item["id"] == duplicate_assistant)
        self.assertIsNone(assistant_reload["schema_binding_result"])

        result, state, _user, _assistant = self.complete_bound_turn(
            "Bir sonraki yaş durağımı seçiyorum.", {
                "age": 12, "label": "Ergenliğe geçiş",
                "then_response": "O zaman susardım",
                "now_response": "Bugün destek isteyebilirim",
                "difference": "Tek başıma kalmak zorunda değilim",
                "continue_ladder": False,
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "environment_rescript")

        result, state, _user, _assistant = self.complete_bound_turn(
            "Çevre formuna kendi seçimlerimi yazdım.", {
                "environment_before": "Kapalı ve sessiz bir oda",
                "environment_rescripted": "Kapısı açık ve destek seçebildiğim bir ortam",
                "healthy_adult_words": "Burada söz hakkın var",
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "present_transfer")

        forged_binding = dict(state["next_card"]["chat_binding"])
        forged_binding["step_data"] = {
            "trigger_source_user_message_id": pairs[0]["user_message_id"],
            "trigger": "Bu metin seçilen eski kaynakta hiç yok",
            "healthy_adult_response": "Bir an durabilirim",
            "planned_action": "Sınırımı söylemek",
        }
        with self.assertRaises(app.RequestInputError) as raised:
            app.begin_chat_request(
                self.conv, "Doğal kısa yanıt",
                request_id=self.request_id("forged-transfer"),
                schema_binding=forged_binding)
        self.assertEqual(raised.exception.error_code,
                         "schema_chat_only_step_data")

        result, state, user_id, _assistant = self.complete_bound_turn(
            "Bugüne taşıma formunu kendim doldurdum.", {
                "trigger": "Konuşma gerildiğinde",
                "healthy_adult_response": "Bir an durup ihtiyacımı söyleyebilirim",
                "planned_action": "Tek cümleyle sınırımı söylemek",
                "support_choice": "Gerekirse ara vermek",
                "predicted_result": "Geri çekilmeden seçim alanım olur",
            })
        self.assertTrue(result["applied"], result)
        self.assertEqual(state["step"], "optional_practice")
        transfer = self.row(
            "SELECT * FROM schema_transfer_records WHERE path=?",
            (path_id,))
        self.assertEqual(transfer["source_user_message"], user_id)
        self.assertEqual(transfer["trigger_source_user_message"], user_id)
        self.assertEqual(transfer["trigger_source_assistant_message"],
                         _assistant)
        self.assertEqual(transfer["planned_action"],
                         "Tek cümleyle sınırımı söylemek")
        self.assertEqual(
            state["present_transfer"]["trigger_source_assistant_message_id"],
            _assistant)

    def test_age_ladder_is_bounded_at_six_without_autofill(self):
        state, pairs, _claim = self.focus_path()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            pair = app.schema_exact_source_pair(
                connection, self.conv, pairs[0]["user_message_id"],
                pairs[0]["assistant_message_id"])
            app.schema_v4_set_state(
                connection, path, "integrate", "age_ladder", pair,
                {"test_setup": True})
        for age in range(6, 12):
            result, state, _user, _assistant = self.complete_bound_turn(
                "{} yaş durağını formda seçtim.".format(age), {
                    "age": age,
                    "now_response": "{} yaş için bugünkü cevabım".format(age),
                    "continue_ladder": True,
                })
            self.assertTrue(result["applied"], result)
            self.assertEqual(state["step"], "age_ladder")
        result, state, _user, _assistant = self.complete_bound_turn(
            "12 yaş durağını da eklemek istedim.", {
                "age": 12, "now_response": "Yedinci yanıt",
                "continue_ladder": True,
            })
        self.assertFalse(result["applied"])
        self.assertEqual(result["error_code"], "schema_growth_limit")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM schema_growth WHERE path=?",
            (path_id,))["n"], 6)

    def test_direct_present_transfer_persists_two_exact_pairs(self):
        state, pairs, _claim = self.focus_path()
        path_id = state["active_path"]["id"]
        with app.db() as connection:
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            source_pair = app.schema_exact_source_pair(
                connection, self.conv, pairs[2]["user_message_id"],
                pairs[2]["assistant_message_id"])
            app.schema_v4_set_state(
                connection, path, "integrate", "present_transfer",
                source_pair, {"test_setup": True})
        status, body = self.mutate(
            "record_present_transfer",
            source_user_message_id=pairs[2]["user_message_id"],
            source_assistant_message_id=pairs[2]["assistant_message_id"],
            trigger_source_user_message_id=pairs[1]["user_message_id"],
            trigger_source_assistant_message_id=
                pairs[1]["assistant_message_id"],
            trigger="kullanıcı kaynağı 1",
            healthy_adult_response="Durup ihtiyacımı söyleyebilirim",
            planned_action="Bir cümleyle sınır koymak")
        self.assertEqual(status, 200, body)
        transfer = self.row(
            "SELECT * FROM schema_transfer_records WHERE path=?", (path_id,))
        self.assertEqual(transfer["source_user_message"],
                         pairs[2]["user_message_id"])
        self.assertEqual(transfer["source_assistant_message"],
                         pairs[2]["assistant_message_id"])
        self.assertEqual(transfer["trigger_source_user_message"],
                         pairs[1]["user_message_id"])
        self.assertEqual(transfer["trigger_source_assistant_message"],
                         pairs[1]["assistant_message_id"])

    def test_safety_pause_is_atomic_and_idempotent_during_imagery(self):
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        link = state["active_path"]["active_technique_link"]
        source = self.row(
            "SELECT source_user_message FROM schema_path_steps "
            "WHERE path=? AND step='imagery_work'", (path_id,))
        decision = {"detected": True, "kind": "self_harm",
                    "context": "chat", "detector_version": 1}
        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                event_one = app.record_safety_event(
                    connection, self.conv, decision,
                    source_message=source["source_user_message"])
        path_after = self.row(
            "SELECT * FROM schema_paths WHERE id=?", (path_id,))
        step_after = self.row(
            "SELECT * FROM schema_path_steps WHERE path=? AND step=?",
            (path_id, path_after["step"]))
        run_after = self.row(
            "SELECT * FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))
        imagery_after = self.row(
            "SELECT * FROM imagery_runs WHERE technique_run=?",
            (link["technique_run_id"],))
        self.assertEqual(path_after["status"], "paused")
        self.assertEqual(path_after["pause_reason"], "safety_hold")
        self.assertEqual(step_after["status"], "paused")
        self.assertEqual(run_after["status"], "paused")
        self.assertEqual(run_after["phase"], "grounding")
        self.assertEqual(imagery_after["current_stage"], "grounding")
        revisions = (path_after["revision"], step_after["revision"],
                     imagery_after["revision"])

        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                event_two = app.record_safety_event(
                    connection, self.conv, decision,
                    source_message=source["source_user_message"])
        self.assertEqual(event_two, event_one)
        self.assertEqual((
            self.row("SELECT revision FROM schema_paths WHERE id=?",
                     (path_id,))["revision"],
            self.row("SELECT revision FROM schema_path_steps WHERE path=? "
                     "AND step=?", (path_id, path_after["step"]))["revision"],
            self.row("SELECT revision FROM imagery_runs WHERE technique_run=?",
                     (link["technique_run_id"],))["revision"]), revisions)
        blocked = self.dashboard()
        self.assertEqual(blocked["next_card"]["kind"], "blocked")
        self.assertEqual(
            [action["action"] for action in blocked["next_card"]["actions"]],
            ["stop"])

    def test_map_action_requires_exact_safe_pair_and_safety_invalidates(self):
        state, pairs, _claim_id = self.start_v4()
        path_id = state["active_path"]["id"]
        pair = pairs[0]
        other_pair = pairs[1]
        with app.db() as connection:
            claim_id = connection.execute(
                "INSERT INTO psych_claims(public_id,source_conv,therapist,"
                "lens,claim_type,title,statement,status,scope,sensitive,"
                "first_seen,last_seen,source_assistant_message,created,updated) "
                "VALUES(?,?,'young','turn_marker','pattern','Harita notu',"
                "'Kaynağa bağlı not','confirmed','session',0,?,?,?,?,?)",
                ("schema-v4-map-0000000000000001", self.conv, app.now(),
                 app.now(), pair["assistant_message_id"], app.now(),
                 app.now())).lastrowid
            path = connection.execute(
                "SELECT * FROM schema_paths WHERE id=?", (path_id,)
            ).fetchone()
            meta = app.schema_message_meta_insert(
                connection, "schema-v4-map-test", self.conv,
                pair["assistant_message_id"], pair, "map_update",
                "Yaşayan Harita", "Kaynağa bağlı not", path=path,
                step=path["step"], artifact_type="psych_claim",
                artifact_id=claim_id,
                artifact_public_id="schema-v4-map-0000000000000001")
        meta_public = next(
            item for item in self.dashboard()["message_meta"]
            if item["id"] == meta["id"])
        action_payload = dict(meta_public["actions"][0]["payload"])
        action_payload.update({
            "source_user_message_id": other_pair["user_message_id"],
            "source_assistant_message_id": other_pair[
                "assistant_message_id"],
        })
        status, body = self.mutate(
            "edit_map_update", note="Sahte düzenleme", **action_payload)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["error_code"], "schema_source_invalid")
        self.assertEqual(self.row(
            "SELECT summary FROM message_meta_events WHERE id=?",
            (meta["id"],))["summary"], "Kaynağa bağlı not")

        refreshed_meta = next(
            item for item in self.dashboard()["message_meta"]
            if item["id"] == meta["id"])
        private_action = next(
            action for action in refreshed_meta["actions"]
            if action["action"] == "make_map_update_private")
        status, body = self.mutate(
            "make_map_update_private", **private_action["payload"])
        self.assertEqual(status, 200, body)
        self.assertEqual(self.row(
            "SELECT status FROM message_meta_events WHERE id=?",
            (meta["id"],))["status"], "private")

        with app.DATA_WRITE_LOCK:
            with app.db() as connection:
                app.record_safety_event(
                    connection, self.conv,
                    {"detected": True, "kind": "self_harm",
                     "context": "chat", "detector_version": 1},
                    source_message=pair["user_message_id"])
        self.assertEqual(self.row(
            "SELECT status FROM message_meta_events WHERE id=?",
            (meta["id"],))["status"], "invalidated")
        self.assertEqual(self.row(
            "SELECT status FROM psych_claims WHERE id=?",
            (claim_id,))["status"], "rejected")

    def test_clinical_generation_rekeys_path_and_pathless_meta(self):
        state, pairs, _claim = self.start_v4()
        path_id = state["active_path"]["id"]
        original_path_public = state["active_path"]["public_id"]
        with app.db() as connection:
            first = app.schema_message_meta_insert(
                connection, "same-pathless-event", self.conv,
                pairs[0]["assistant_message_id"], pairs[0], "candidate",
                "Aday", "Yerel aday")
        self.assertEqual(first["clinical_generation"], 0)

        status, body = self.post({
            "action": "set_clinical_sync", "conv_id": self.conv,
            "enabled": True, "confirmed": True,
            "request_id": self.request_id("sync-enable")})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["clinical_sync"]["generation"], 1)
        generation_one_public = body["active_path"]["public_id"]
        self.assertNotEqual(generation_one_public, original_path_public)
        self.assertEqual(body["active_path"]["clinical_generation"], 1)
        with app.db() as connection:
            second = app.schema_message_meta_insert(
                connection, "same-pathless-event", self.conv,
                pairs[1]["assistant_message_id"], pairs[1], "candidate",
                "Aday", "Birinci nesil aday")
        self.assertEqual(second["clinical_generation"], 1)

        self.assertEqual(self.post({
            "action": "set_clinical_sync", "conv_id": self.conv,
            "enabled": False, "confirmed": True,
            "request_id": self.request_id("sync-off")})[0], 200)
        status, body = self.post({
            "action": "set_clinical_sync", "conv_id": self.conv,
            "enabled": True, "confirmed": True,
            "request_id": self.request_id("sync-reenable")})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["clinical_sync"]["generation"], 2)
        self.assertNotEqual(body["active_path"]["public_id"],
                            generation_one_public)
        self.assertEqual(self.row(
            "SELECT clinical_generation FROM schema_paths WHERE id=?",
            (path_id,))["clinical_generation"], 2)
        with app.db() as connection:
            third = app.schema_message_meta_insert(
                connection, "same-pathless-event", self.conv,
                pairs[2]["assistant_message_id"], pairs[2], "candidate",
                "Aday", "İkinci nesil aday")
        self.assertEqual(third["clinical_generation"], 2)
        self.assertEqual(len({first["public_id"], second["public_id"],
                              third["public_id"]}), 3)
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM message_meta_events WHERE "
            "event_key LIKE ?", ("%same-pathless-event",))["n"], 3)

    def test_legacy_claim_not_null_table_is_rebuilt(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE schema_paths(id INTEGER PRIMARY KEY,"
                "public_id TEXT,conv INTEGER NOT NULL,therapist TEXT NOT NULL,"
                "claim INTEGER NOT NULL,phase TEXT,status TEXT,created TEXT,"
                "updated TEXT)")
            connection.execute(
                "CREATE UNIQUE INDEX schema_path_one_active ON "
                "schema_paths(conv) WHERE status IN ('active','paused')")
            connection.execute(
                "INSERT INTO schema_paths VALUES(1,'legacy',1,'young',7,"
                "'focus','active','x','x')")
            self.assertTrue(app._migrate_schema_paths_nullable_claim(
                connection))
            claim = next(row for row in connection.execute(
                "PRAGMA table_info(schema_paths)") if row[1] == "claim")
            self.assertEqual(claim[3], 0)
            connection.execute(
                "INSERT INTO schema_paths VALUES(2,'synced',2,'young',NULL,"
                "'work','active','x','x')")
            self.assertEqual(connection.execute(
                "SELECT claim FROM schema_paths WHERE id=2").fetchone()[0],
                None)
        finally:
            connection.close()

    def test_conversation_delete_erases_all_v4_rows_with_fk_disabled(self):
        sentinel, tables = self.populated_erasure_graph()
        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            app.delete_conversation_data(connection, self.conv)
        for table in tables:
            self.assertEqual(self.row(
                "SELECT COUNT(*) AS n FROM {}".format(table))["n"], 0,
                table)
        with app.db() as connection:
            dump = "\n".join(connection.iterdump())
            for table in ("sync_changes", "sync_conflicts"):
                if connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name=?", (table,)).fetchone():
                    for row in connection.execute(
                            "SELECT * FROM {}".format(table)).fetchall():
                        self.assertNotIn(sentinel, repr(tuple(row)), table)
        self.assertNotIn(sentinel, dump)

    def test_delete_all_erases_v4_rows_sync_metadata_and_file_bytes(self):
        sentinel, tables = self.populated_erasure_graph()
        path_public = self.row(
            "SELECT public_id FROM schema_paths LIMIT 1")["public_id"]
        with app.db() as connection:
            app.sync_engine._sync_tables(connection)
            connection.execute(
                "INSERT INTO sync_changes(event_id,record_type,public_id,"
                "revision,origin_device_id,updated_at,payload_json) "
                "VALUES(?, 'schema_path', ?,1,'test-device',?,?)",
                ("schema-v4-erasure-change", path_public, app.now(),
                 json.dumps({"sentinel": sentinel})))
            connection.execute(
                "INSERT INTO sync_conflicts(record_type,public_id,reason,"
                "local_json,incoming_json,incoming_event_id,created_at) "
                "VALUES('schema_path',?,?,?,?,?,?)",
                (path_public, sentinel,
                 json.dumps({"sentinel": sentinel}),
                 json.dumps({"sentinel": sentinel}),
                 "schema-v4-erasure-conflict", app.now()))
        status, body, _headers = self.request(
            "POST", "/api/delete-all",
            {"confirm": "TÜM VERİLERİ SİL"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        with app.db() as connection:
            for table in tables + ("sync_changes", "sync_conflicts"):
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) AS n FROM {}".format(table)
                ).fetchone()["n"], 0, table)
            dump = "\n".join(connection.iterdump())
        self.assertNotIn(sentinel, dump)
        raw_sentinel = sentinel.encode("utf-8")
        for suffix in ("", "-wal", "-shm"):
            path = Path(app.DB_PATH + suffix)
            if path.exists():
                self.assertNotIn(raw_sentinel, path.read_bytes(), str(path))

    def test_archive_and_end_coordinate_checkpoint_and_local_run(self):
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        link = state["active_path"]["active_technique_link"]
        status, archived, _headers = self.request(
            "POST", "/api/archive", {"id": self.conv, "archived": True})
        self.assertEqual(status, 200, archived)
        self.assertTrue(archived["archived"])
        path = self.row(
            "SELECT status,pause_reason FROM schema_paths WHERE id=?",
            (path_id,))
        self.assertEqual((path["status"], path["pause_reason"]),
                         ("paused", "conversation_archived"))
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"], "paused")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_techniques WHERE id=?",
            (link["id"],))["status"], "paused")
        run = self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))
        self.assertEqual((run["status"], run["phase"]),
                         ("paused", "grounding"))

        status, unarchived, _headers = self.request(
            "POST", "/api/archive", {"id": self.conv, "archived": False})
        self.assertEqual(status, 200, unarchived)
        self.assertFalse(unarchived["archived"])
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "paused")

        self.conv = self.conversation(therapist="young")
        app.set_schema_mode(self.conv, True)
        state = self.start_imagery()
        path_id = state["active_path"]["id"]
        link = state["active_path"]["active_technique_link"]
        with mock.patch.object(app, "start_job_worker"), \
                mock.patch.object(app, "enqueue_job"):
            status, ended, _headers = self.request(
                "POST", "/api/end", {"conv_id": self.conv})
        self.assertEqual(status, 200, ended)
        self.assertEqual(self.row(
            "SELECT status FROM schema_paths WHERE id=?", (path_id,)
        )["status"], "stopped")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_checkpoints WHERE path=? "
            "ORDER BY seq DESC LIMIT 1", (path_id,))["status"],
            "invalidated")
        self.assertEqual(self.row(
            "SELECT status FROM schema_path_techniques WHERE id=?",
            (link["id"],))["status"], "stopped")
        run = self.row(
            "SELECT status,phase FROM technique_runs WHERE id=?",
            (link["technique_run_id"],))
        self.assertEqual((run["status"], run["phase"]),
                         ("stopped", "end"))

    def test_export_json_contains_v4_progress_without_secret_settings(self):
        sentinel, tables = self.populated_erasure_graph()
        app.set_setting("deepseek_api_key", "DO-NOT-EXPORT-SECRET")
        status, body, _headers = self.request("GET", "/api/export-json")
        self.assertEqual(status, 200)
        exported = body
        for table in tables:
            self.assertIn(table, exported["data"])
            self.assertGreater(len(exported["data"][table]), 0, table)
        encoded = json.dumps(exported, ensure_ascii=False)
        self.assertIn(sentinel, encoded)
        self.assertNotIn("DO-NOT-EXPORT-SECRET", encoded)

    def test_real_reducer_graph_exports_as_consent_split_canonical_projection(self):
        device_a = "schema-v4-real-device-a"
        device_b = "schema-v4-real-device-b"
        status, enabled = self.post({
            "action": "set_clinical_sync", "conv_id": self.conv,
            "enabled": True, "confirmed": True,
            "request_id": self.request_id("clinical-sync-enable"),
        })
        self.assertEqual(status, 200, enabled)
        self.assertEqual(enabled["clinical_sync"]["generation"], 1)

        state = self.start_imagery()
        self.assertEqual(state["active_path"]["clinical_generation"], 1)
        card = state["next_card"]
        choice = next((
            option["value"] for field in card["fields"]
            if field["id"] == "choice" for option in field["options"]), None)
        imagery_text = "Sahne sınırını kapının dışında tutuyorum."
        step_data = {
            "content": imagery_text, "orientation_ok": True,
            "reality_clear": True, "intensity": 2,
        }
        if choice:
            step_data["choice"] = choice
        result, state, _user, _assistant = self.complete_bound_turn(
            imagery_text, step_data)
        self.assertTrue(result["applied"], result)
        link = state["active_path"]["active_technique_link"]
        status, state = self.mutate(
            "ground_chat_technique", step_id=state["step"],
            technique_link_id=link["id"],
            expected_technique_revision=link["technique_revision"],
            orientation_ok=True, intensity=2)
        self.assertEqual(status, 200, state)
        self.assertGreater(self.row(
            "SELECT COUNT(*) AS n FROM message_meta_events "
            "WHERE conv=? AND path IS NOT NULL", (self.conv,))["n"], 0)

        # These sentinels live only in explicitly local reducer/private
        # columns.  They must not survive logical wire projection.
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET practice_json=? WHERE conv=?",
                ('{"private":"PATH-PRIVATE-REAL-NEVER-WIRE"}', self.conv))
            connection.execute(
                "UPDATE schema_path_steps SET payload_json=? WHERE conv=?",
                ('{"private":"STEP-PRIVATE-REAL-NEVER-WIRE"}', self.conv))
            connection.execute(
                "UPDATE technique_runs SET state_json=? WHERE conv=?",
                ('{"private":"PRECHECK-REAL-NEVER-WIRE"}', self.conv))
            connection.execute(
                "UPDATE imagery_steps SET payload_json=? WHERE conv=?",
                ('{"private":"IMAGERY-LOCAL-REAL-NEVER-WIRE"}', self.conv))
            initialized = sync.initialize_sync(connection, device_a)
            refreshed = sync.refresh_local_changes(connection, device_a)
            self.assertGreater(initialized["bootstrapped"], 0)
            self.assertEqual(refreshed["added"], 0)

            batches = []
            cursor = 0
            while True:
                batch = sync.export_change_batch(
                    connection, device_a, after_cursor=cursor)
                batches.append(batch)
                self.assertGreaterEqual(batch["cursor"], cursor)
                if not batch["has_more"]:
                    break
                self.assertGreater(batch["cursor"], cursor)
                cursor = batch["cursor"]

        clinical_types = set(sync._SCHEMA_CLINICAL_RECORD_TYPES)
        live_batches = [batch for batch in batches if batch["records"]]
        self.assertGreaterEqual(len(live_batches), 2)
        seen_clinical = False
        clinical_records = []
        ordinary_batches, clinical_batches = [], []
        for batch in live_batches:
            types = {row["record_type"] for row in batch["records"]}
            is_clinical = bool(types & clinical_types)
            if is_clinical:
                self.assertTrue(types <= clinical_types)
                seen_clinical = True
                clinical_batches.append(batch)
                clinical_records.extend(batch["records"])
            else:
                self.assertFalse(seen_clinical)
                ordinary_batches.append(batch)
        self.assertTrue(ordinary_batches)
        self.assertTrue(clinical_batches)
        self.assertTrue({
            "schema_path", "schema_candidate", "schema_focus_check",
            "schema_step", "schema_origin", "schema_message_meta",
        } <= {row["record_type"] for row in clinical_records})

        def server_natural_id(record):
            payload = record["payload"]
            record_type = record["record_type"]
            if record_type == "schema_path":
                return app._schema_natural_public_id(
                    "path", payload["conversation_public_id"],
                    payload["clinical_generation"], payload["path_sequence"])
            if record_type == "schema_candidate":
                return app._schema_natural_public_id(
                    "candidate", payload["conversation_public_id"],
                    payload["clinical_generation"],
                    payload["source_user_message_public_id"],
                    payload["source_assistant_message_public_id"],
                    payload.get("schema_key") or "-",
                    payload.get("mode_key") or "-")
            if record_type == "schema_focus_check":
                return app._schema_natural_public_id(
                    "focus", payload["path_public_id"],
                    payload["candidate_public_id"])
            if record_type == "schema_step":
                return app._schema_natural_public_id(
                    "step", payload["path_public_id"], payload["step"])
            if record_type == "schema_origin":
                return app._schema_natural_public_id(
                    "origin", payload["path_public_id"])
            if record_type == "schema_growth":
                return app._schema_natural_public_id(
                    "growth", payload["path_public_id"], payload["seq"])
            if record_type == "schema_healthy_adult":
                return app._schema_natural_public_id(
                    "healthy", payload["path_public_id"],
                    payload["source_message_public_id"],
                    payload["source_assistant_message_public_id"],
                    payload["source"])
            if record_type == "schema_transfer":
                return app._schema_natural_public_id(
                    "transfer", payload["path_public_id"])
            if record_type == "schema_message_meta":
                if payload.get("path_public_id"):
                    return app._schema_natural_public_id(
                        "meta", payload["path_public_id"],
                        payload["event_key"])
                return app._schema_natural_public_id(
                    "meta-local", payload["conversation_public_id"],
                    payload["clinical_generation"], payload["event_key"])
            self.fail("beklenmeyen klinik kayıt: " + record_type)

        for record in clinical_records:
            self.assertEqual(record["public_id"], server_natural_id(record))
            self.assertEqual(
                record["public_id"],
                sync._expected_schema_public_id(
                    record["record_type"], record["payload"]))

        wire = json.dumps(batches, ensure_ascii=False)
        for forbidden in (
                "PATH-PRIVATE-REAL-NEVER-WIRE",
                "STEP-PRIVATE-REAL-NEVER-WIRE",
                "PRECHECK-REAL-NEVER-WIRE",
                "IMAGERY-LOCAL-REAL-NEVER-WIRE",
                "payload_json", "practice_json", "technique_run",
                "schema_path_techniques", "imagery_steps", "chair_turns"):
            self.assertNotIn(forbidden, wire)

        target = str(Path(self._tmp.name) / "real-v4-receiver.db")
        source_path = app.DB_PATH
        try:
            app.DB_PATH = target
            app.init_db()
            with app.db() as connection:
                for batch in ordinary_batches:
                    sync.apply_change_batch(connection, batch, device_b)
                pending = connection.execute(
                    "SELECT schema_clinical_sync_enabled,"
                    "schema_clinical_sync_initialized,"
                    "schema_clinical_sync_generation FROM session_meta"
                ).fetchone()
                self.assertEqual(tuple(pending), (1, 0, 1))
                with self.assertRaises(
                        sync.ClinicalSyncConfirmationRequired):
                    sync.apply_change_batch(
                        connection, clinical_batches[0], device_b)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0], 0)
                connection.execute(
                    "UPDATE session_meta SET "
                    "schema_clinical_sync_initialized=1")
                for batch in clinical_batches:
                    sync.apply_change_batch(connection, batch, device_b)
                counts = {
                    table: connection.execute(
                        "SELECT COUNT(*) FROM {}".format(table)
                    ).fetchone()[0]
                    for table in (
                        "schema_paths", "schema_candidate_queue",
                        "schema_focus_checks", "schema_path_steps",
                        "schema_origin", "message_meta_events")}
                self.assertTrue(all(value > 0 for value in counts.values()),
                                counts)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM technique_runs").fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM schema_path_techniques"
                ).fetchone()[0], 0)
        finally:
            app.DB_PATH = source_path

    def test_frozen_contract_fixture_pins_types_actions_and_wire_tables(self):
        fixture_path = (Path(__file__).parent / "fixtures" /
                        "schema_path_v4_contract.json")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(fixture["fixture_version"], 8)
        self.assertEqual(fixture["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(fixture["version"], app.SCHEMA_PATH_VERSION)
        self.assertEqual(fixture["presentation"], "chat_only")
        self.assertEqual(fixture["contract"]["runtime"], {
            "protocol": app.SCHEMA_PATH_V5_PROTOCOL,
            "schema_version": app.SCHEMA_PATH_VERSION,
            "path_flow_version": 5,
            "presentation": "chat_only",
            "sync_batch_version": sync.BATCH_VERSION,
            "fixture_version": 8,
        })
        self.assertEqual(
            fixture["contract"]["request_id"]["endpoint_patterns"], {
                "/api/schema-path": app.SCHEMA_PATH_REQUEST_RE.pattern,
                "/api/chat": app.CHAT_REQUEST_ID_RE.pattern,
            })

        candidate = fixture["next_card"]
        self.assertEqual(candidate["kind"], "candidate_prompt")
        self.assertEqual(candidate["body"], "Bunu çalışmak ister misin?")
        self.assertTrue(candidate["context_line"].endswith(
            "tetiklenmiş olabilir."))
        self.assertIsNone(candidate["path_id"])
        self.assertIsNone(candidate["revision"])
        self.assertEqual(candidate["fields"], [])
        self.assertEqual(
            [(item["action"], item["label"])
             for item in candidate["actions"]],
            [("accept_candidate_chat", "Evet"),
             ("reject_candidate_chat", "Hayır")])
        for item in candidate["actions"]:
            self.assertEqual(item["payload"]["candidate_public_id"],
                             candidate["candidate"]["public_id"])
            for role in ("user", "assistant"):
                self.assertIsInstance(
                    item["payload"][f"source_{role}_message_id"], int)
                self.assertRegex(
                    item["payload"][f"source_{role}_message_public_id"],
                    r"^[0-9a-f]{32}$")
        self.assertEqual(
            fixture["contract"]["candidate_prompt"]["protocol"],
            app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertTrue(fixture["contract"]["candidate_prompt"]
                        ["sole_visible_schema_ui"])
        self.assertIsNone(fixture["active_path"])
        self.assertEqual(
            fixture["interaction_policy"]["composer_mode"], "disabled")
        self.assertEqual(
            fixture["interaction_policy"]["composer_surface"],
            "ordinary_chat")

        card_contract = fixture["contract"]["card"]
        self.assertEqual(set(card_contract["kind_values"]), {
            "candidate_prompt", "chat_state"})
        self.assertEqual(card_contract["visible_path_action_values"], [
            "accept_candidate_chat", "reject_candidate_chat"])
        self.assertEqual(card_contract["post_yes_visible_action_values"], [])
        delivery_keys = set(
            fixture["contract"]["prompt_delivery"]["total_keys"])
        delivery_statuses = set(
            fixture["contract"]["prompt_delivery"]["status_values"])
        self.assertEqual(delivery_keys, {
            "request_id", "status", "prompt_assistant_message_id",
            "prompt_assistant_message_public_id", "error_code"})
        self.assertEqual(delivery_statuses, {
            "missing", "queued", "running", "waiting_provider",
            "completed", "failed", "interrupted", "cancelled",
            "imported_waiting"})

        for name, card in fixture["card_examples"].items():
            self.assertEqual(card["presentation"], "chat_only", name)
            self.assertEqual(card["fields"], [], name)
            if card["kind"] == "candidate_prompt":
                continue
            self.assertEqual(card["kind"], "chat_state", name)
            self.assertEqual(
                (card["title"], card["context_line"], card["body"]),
                ("", "", ""), name)
            self.assertEqual(card["actions"], [], name)
            self.assertEqual(
                set(card["prompt_delivery"]), delivery_keys, name)
            self.assertIn(
                card["prompt_delivery"]["status"], delivery_statuses, name)

        completed = fixture["card_examples"]["completed_chat_state"]
        binding = fixture["chat_schema_binding"]
        self.assertEqual(completed["chat_binding"], binding)
        self.assertNotIn("step_data", binding)
        self.assertEqual(binding["protocol"], app.SCHEMA_PATH_V5_PROTOCOL)
        self.assertEqual(binding["path_public_id"],
                         completed["path_public_id"])
        self.assertEqual(binding["step_id"], completed["step"])
        self.assertEqual(binding["expected_revision"],
                         completed["revision"])
        self.assertEqual(binding["checkpoint_public_id"],
                         completed["checkpoint"]["public_id"])
        self.assertEqual(binding["expected_checkpoint_seq"],
                         completed["checkpoint"]["seq"])
        self.assertEqual(binding["prompt_request_id"],
                         completed["prompt_delivery"]["request_id"])
        self.assertEqual(binding["prompt_assistant_message_id"],
                         completed["prompt_delivery"][
                             "prompt_assistant_message_id"])
        self.assertEqual(binding["source_assistant_message_id"],
                         completed["source"]["assistant_message_id"])
        self.assertEqual(binding["source_assistant_message_id"],
                         binding["prompt_assistant_message_id"])

        imported = fixture["card_examples"]["imported_waiting_chat_state"]
        import_binding = fixture["import_control_binding"]
        self.assertEqual(imported["chat_binding"], import_binding)
        self.assertIs(import_binding["sync_import_control"], True)
        for key in (
                "prompt_request_id", "prompt_assistant_message_id",
                "prompt_assistant_message_public_id"):
            self.assertIn(key, import_binding)
            self.assertIsNone(import_binding[key])
        self.assertIsNone(imported["prompt_delivery"]["request_id"])
        self.assertIsNone(imported["prompt_delivery"]
                          ["prompt_assistant_message_id"])
        self.assertIsNone(imported["prompt_delivery"]
                          ["prompt_assistant_message_public_id"])
        self.assertEqual(
            imported["prompt_delivery"]["status"], "imported_waiting")
        self.assertEqual(imported["checkpoint"]["status"], "paused")
        self.assertFalse(imported["checkpoint"]["can_backtrack"])

        visible = json.dumps({
            name: {
                "title": card["title"],
                "context_line": card["context_line"],
                "body": card["body"],
                "fields": card["fields"],
                "actions": card["actions"],
            }
            for name, card in fixture["card_examples"].items()
            if card["kind"] == "chat_state"
        }, ensure_ascii=False).casefold()
        for forbidden in (
                "0 ile 10", "0–10", "0 ile 7", "0–7", "yoğunluk",
                "şiddet", "seviye", "çalışalım mı", "onay", "uyku",
                "gerçekliği ayır", "desteğin var", "stop sinyali",
                "duraklat", "çalışmayı bitir", "şimdiye dön"):
            self.assertNotIn(forbidden, visible)

        self.assertEqual(
            set(fixture["contract"]["prompt_intents"]),
            set(app.SCHEMA_PATH_V5_PROMPT_INTENTS))
        self.assertEqual(
            fixture["contract"]["reachable_flow"]["steps"],
            list(app.SCHEMA_PATH_V5_STEPS))
        self.assertEqual(
            fixture["contract"]["method_flow"]["new_v5_method_ids"],
            [app.IMAGERY_METHOD_NODE_ID,
             "young:method:chair-dialogue"])
        self.assertFalse(fixture["contract"]["method_flow"]
                         ["user_method_approval_question"])
        self.assertTrue(fixture["contract"]["reachable_flow"]
                        ["no_rating_or_precheck_question"])
        self.assertFalse(fixture["contract"]["post_yes_messages"]
                         ["visible_suffix_or_continuation"])
        self.assertFalse(fixture["contract"]["post_yes_messages"]
                         ["synthetic_assistant_message"])

        self.assertEqual(
            fixture["chat_post"]["forbidden_fields"], [
                "schema_binding.step_data", "schema_prompt_plan_json",
                "schema_prompt_result_json"])
        result_keys = set(
            fixture["schema_binding_results"]["total_keys"])
        self.assertEqual(result_keys, {
            "applied", "progressed", "followup_required", "error_code",
            "missing", "path_id", "path_revision", "revision", "stage",
            "step", "action", "checkpoint_public_id", "checkpoint_seq",
            "prompt_request_id", "backtracked"})
        for name in ("success", "terminal", "source_invalid", "stale"):
            result = fixture["schema_binding_results"][name]
            self.assertEqual(set(result), result_keys, name)
            self.assertIsInstance(result["missing"], list, name)
        for code in (
                "schema_chat_binding_required", "schema_source_invalid",
                "schema_prompt_shape_invalid",
                "schema_prompt_grounding_invalid",
                "schema_protocol_update_required",
                "sync_protocol_update_required"):
            self.assertIn(code, fixture["errors"])

        controls = fixture["contract"]["controls"]
        self.assertEqual(controls["visible_controls_after_yes"], [])
        self.assertEqual(controls["exact_commands"]["stop"], [
            "bitir", "bitirelim", "çalışmayı bitir",
            "bu çalışmayı bırak"])
        self.assertEqual(set(controls["provider_zero"]), {
            "pause", "stop", "back", "ground"})
        self.assertFalse(controls["synthetic_acknowledgement"])
        for name in (
                "exact_pause_chat", "exact_stop_chat",
                "exact_back_chat", "exact_ground_chat"):
            self.assertEqual(
                fixture["action_requests"][name]["provider_calls"], 0)
            self.assertEqual(
                fixture["action_requests"][name]["assistant_messages"], 0)

        wire = fixture["sync_wire"]
        self.assertEqual(wire["batch_version"], sync.BATCH_VERSION)
        self.assertEqual(
            wire["capability_gate"]["ordered_capabilities"],
            ["schema_checkpoint_v1", app.SCHEMA_PATH_V5_PROTOCOL])
        self.assertEqual(
            set(wire["safe_tables_and_columns"]), {
                "schema_paths", "schema_candidate_queue",
                "schema_focus_checks", "schema_path_steps", "schema_origin",
                "schema_growth", "healthy_adult_marks",
                "schema_transfer_records", "message_meta_events"})
        fixture_columns = wire["safe_tables_and_columns"]
        for record_type in sync._SCHEMA_CLINICAL_RECORD_TYPES:
            spec = sync.RECORD_TYPES[record_type]
            expected = {"public_id", *spec.fields,
                        *(item[0] for item in spec.references)}
            self.assertEqual(set(fixture_columns[spec.table]), expected,
                             record_type)
        message_spec = sync.RECORD_TYPES["message"]
        self.assertEqual(
            wire["ordinary_message_lineage"]["safe_columns"],
            ["public_id", *message_spec.fields,
             *(item[0] for item in message_spec.references)])
        self.assertIn(
            "turn_pair_public_id",
            sync._REQUIRED_PAYLOAD_FIELDS["message"])
        local_only = " ".join(wire["local_only"])
        for table in (
                "schema_path_checkpoints", "schema_path_method_choices",
                "schema_variable_trials", "schema_origin_answers",
                "schema_v5_technique_sessions",
                "schema_v5_technique_turns",
                "schema_v5_integration_answers", "chat_requests"):
            self.assertIn(table, local_only)
        self.assertIn("method_node_id is wire-safe", local_only)


if __name__ == "__main__":
    import unittest
    unittest.main()
