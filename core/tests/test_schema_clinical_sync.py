import copy
import json
from pathlib import Path
from unittest import mock

from support import DatabaseTestCase, HTTPTestCase, app

import sync_engine as sync
import sync_service


DEVICE_A = "schema-clinical-device-a"
DEVICE_B = "schema-clinical-device-b"


class SchemaClinicalSyncTests(DatabaseTestCase):

    def _target_path(self):
        return str(Path(self._tmp.name) / "schema-clinical-target.db")

    def _with_database(self, path, callback):
        original = app.DB_PATH
        app.DB_PATH = path
        try:
            app.init_db()
            with app.db() as connection:
                return callback(connection)
        finally:
            app.DB_PATH = original

    def _seed_projection(
            self, stage="depth", step="origin_or_unknown",
            include_second_pair=False):
        stamp = "2026-08-22 12:00:00"
        conv_public = "c" * 32
        user_public = "b" * 32
        assistant_public = "a" * 32
        turn_pair_public = app._chat_turn_pair_public_id(
            "schema-clinical-chat-request")
        generation = 1
        path_public = app._schema_natural_public_id(
            "path", conv_public, generation, 1)
        candidate_public = app._schema_natural_public_id(
            "candidate", conv_public, generation, user_public,
            assistant_public, "social_isolation", "vulnerable_child")
        with app.db() as connection:
            conv_id = connection.execute(
                "INSERT INTO conversations("
                "public_id,mode,therapist,title,created,updated) "
                "VALUES(?,'terapi','young','Şema v4 eşitleme',?,?)",
                (conv_public, stamp, stamp),
            ).lastrowid
            user_id = connection.execute(
                "INSERT INTO messages(public_id,conv,role,content,created,"
                "turn_pair_public_id) "
                "VALUES(?,?,'user','KAYNAK-KULLANICI-icerigi',?,?)",
                (user_public, conv_id, stamp, turn_pair_public),
            ).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(public_id,conv,role,content,created,"
                "turn_pair_public_id) "
                "VALUES(?,?,'assistant','KAYNAK-ASISTAN-yaniti',?,?)",
                (assistant_public, conv_id, stamp, turn_pair_public),
            ).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat',?,'done',?,?)",
                (conv_id, stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO chat_requests("
                "request_id,job,conv,user_message,assistant_message,status,"
                "created,updated) VALUES(?,?,?,?,?,'completed',?,?)",
                ("schema-clinical-chat-request", job_id, conv_id, user_id,
                 assistant_id, stamp, stamp),
            )
            connection.execute(
                "INSERT INTO session_meta("
                "conv,schema_mode_enabled,schema_mode_initialized,"
                "schema_clinical_sync_enabled,"
                "schema_clinical_sync_initialized,"
                "schema_clinical_sync_generation,schema_mode_provider,"
                "schema_mode_model,updated) VALUES(?,1,1,1,1,1,"
                "'LOCAL-PROVIDER-NEVER-WIRE','LOCAL-MODEL-NEVER-WIRE',?)",
                (conv_id, stamp),
            )
            path_id = connection.execute(
                "INSERT INTO schema_paths("
                "public_id,conv,therapist,path_sequence,clinical_generation,"
                "phase,status,flow_version,stage,step,"
                "focus_candidate_public_id,focus_schema_key,focus_mode_key,"
                "focus_label,focus_evidence,"
                "focus_source_user_public_id,"
                "focus_source_assistant_public_id,method_node_id,"
                "practice_json,practice_status,revision,created,updated) "
                "VALUES(?,?,'young',1,1,'work','active',4,?,?,"
                "?,?,?,?,?,?,?,?,?,'active',8,?,?)",
                (
                    path_public, conv_id, stage, step, candidate_public,
                    "social_isolation", "vulnerable_child",
                    "Birlikte sınanan olasılık", "Kullanıcının exact sözü",
                    user_public, assistant_public,
                    "young:method:imagery-rescripting",
                    '{"raw_private":"PATH-PRIVATE-NEVER-WIRE"}',
                    stamp, stamp,
                ),
            ).lastrowid
            candidate_id = connection.execute(
                "INSERT INTO schema_candidate_queue("
                "public_id,conv,path,clinical_generation,"
                "source_user_message,source_assistant_message,schema_key,"
                "mode_key,evidence,burden,impact,priority,status,sort_order,"
                "revision,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,"
                "'selected',0,4,?,?)",
                (
                    candidate_public, conv_id, path_id, generation, user_id,
                    assistant_id, "social_isolation", "vulnerable_child",
                    "Kullanıcıya gösterilen kısa kanıt", 8,
                    "Günlük ilişkide geri çekilme", "now", stamp, stamp,
                ),
            ).lastrowid
            focus_public = app._schema_natural_public_id(
                "focus", path_public, candidate_public)
            connection.execute(
                "INSERT INTO schema_focus_checks("
                "public_id,conv,path,candidate_queue,source_user_message,"
                "source_assistant_message,baseline_burden,variable_text,"
                "changed_scenario,changed_burden,fit,confirmed,authored_by,"
                "revision,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,"
                "'partial',1,'user',3,?,?)",
                (
                    focus_public, conv_id, path_id, candidate_id, user_id,
                    assistant_id, 8, "Karşımdakinin sakin kalması",
                    "Aynı konu sakin konuşuluyor", 4, stamp, stamp,
                ),
            )
            step_public = app._schema_natural_public_id(
                "step", path_public, step)
            connection.execute(
                "INSERT INTO schema_path_steps("
                "public_id,path,conv,stage,step,status,revision,"
                "source_user_message,source_assistant_message,payload_json,"
                "created,updated) VALUES(?,?,?,?,?,'active',8,?,?,?, ?,?)",
                (
                    step_public, path_id, conv_id, stage, step,
                    user_id, assistant_id,
                    '{"private_scene":"STEP-PRIVATE-NEVER-WIRE"}',
                    stamp, stamp,
                ),
            )
            origin_public = app._schema_natural_public_id(
                "origin", path_public)
            connection.execute(
                "INSERT INTO schema_origin("
                "public_id,path,conv,source_user_message,"
                "source_assistant_message,mode_key,age_range,scene,"
                "unmet_need,confidence,authored_by,created,updated) "
                "VALUES(?,?,?,?,?,'vulnerable_child','hatırlamıyorum',"
                "'Kullanıcının bildirdiği belirsiz örnek','Güven',"
                "'unknown','user',?,?)",
                (origin_public, path_id, conv_id, user_id, assistant_id,
                 stamp, stamp),
            )
            growth_public = app._schema_natural_public_id(
                "growth", path_public, 1)
            connection.execute(
                "INSERT INTO schema_growth("
                "public_id,path,conv,source_user_message,"
                "source_assistant_message,mode_key,stage_age,stage_label,"
                "then_response,now_response,difference,environment_before,"
                "environment_rescripted,healthy_adult_words,"
                "environment_source_user_message,"
                "environment_source_assistant_message,status,"
                "environment_status,seq,created,updated) "
                "VALUES(?,?,?,?,?,'vulnerable_child',9,'9 yaş',"
                "'Geri çekilmek','Durup ihtiyacımı söylemek','Seçim alanı',"
                "'Yalnız bir oda','Kapısı açık güvenli oda',"
                "'Buradayım ve seni dinliyorum',?,?,'active','active',1,?,?)",
                (growth_public, path_id, conv_id, user_id, assistant_id,
                 user_id, assistant_id, stamp, stamp),
            )
            healthy_public = app._schema_natural_public_id(
                "healthy", path_public, user_public, assistant_public,
                "user")
            connection.execute(
                "INSERT INTO healthy_adult_marks("
                "public_id,conv,path,source,evidence,source_message,"
                "source_assistant_message,created) "
                "VALUES(?,?,?,'user','Kullanıcının şefkatli cümlesi',?,?,?)",
                (healthy_public, conv_id, path_id, user_id, assistant_id,
                 stamp),
            )
            transfer_public = app._schema_natural_public_id(
                "transfer", path_public)
            connection.execute(
                "INSERT INTO schema_transfer_records("
                "public_id,path,conv,source_user_message,"
                "source_assistant_message,trigger_source_user_message,"
                "trigger_source_assistant_message,trigger_text,"
                "healthy_adult_response,planned_action,support_choice,"
                "predicted_result,observed_result,authored_by,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'user',?,?)",
                (
                    transfer_public, path_id, conv_id, user_id, assistant_id,
                    user_id, assistant_id, "Konuşma gerildiğinde",
                    "Bir an durup ihtiyacımı söyleyebilirim",
                    "Bir cümleyle sınırımı söylemek",
                    "Gerekirse ara vermek", "Seçim alanım olur", "",
                    stamp, stamp,
                ),
            )
            for index, linked_path in enumerate((path_id, None), start=1):
                event_key = "schema-test-meta-{}".format(index)
                meta_public = app._schema_natural_public_id(
                    "meta" if linked_path else "meta-local",
                    path_public if linked_path else conv_public,
                    event_key if linked_path else generation,
                    *(tuple() if linked_path else (event_key,)))
                connection.execute(
                    "INSERT INTO message_meta_events("
                    "public_id,event_key,conv,message,clinical_generation,"
                    "source_user_message,source_assistant_message,path,step,"
                    "kind,status,title,summary,artifact_type,"
                    "artifact_public_id,payload_json,actions_json,created,"
                    "updated) VALUES(?,?,?,?,?,?,?,?,?,'map_update','active',"
                    "'Yaşayan Harita','Kısa, paylaşılabilir ilerleme notu',"
                    "'schema_path',?,?,?, ?,?)",
                    (
                        meta_public, event_key, conv_id, assistant_id,
                        generation, user_id, assistant_id, linked_path,
                        "candidate_review", path_public,
                        '{"raw":"META-PRIVATE-NEVER-WIRE"}',
                        '[{"raw":"META-ACTION-NEVER-WIRE"}]',
                        stamp, stamp,
                    ),
                )
            if include_second_pair:
                second_request_id = "schema-clinical-second-request"
                second_pair_public = app._chat_turn_pair_public_id(
                    second_request_id)
                second_user_id = connection.execute(
                    "INSERT INTO messages("
                    "public_id,conv,role,content,created,reply_to,"
                    "turn_pair_public_id) VALUES(?,?,'user',?,?,?,?)",
                    ("d" * 32, conv_id, "İkinci kullanıcı", stamp,
                     assistant_id, second_pair_public),
                ).lastrowid
                second_assistant_id = connection.execute(
                    "INSERT INTO messages("
                    "public_id,conv,role,content,created,reply_to,"
                    "turn_pair_public_id) VALUES(?,?,'assistant',?,?,?,?)",
                    ("e" * 32, conv_id, "İkinci yardımcı", stamp,
                     assistant_id, second_pair_public),
                ).lastrowid
                second_job_id = connection.execute(
                    "INSERT INTO jobs(kind,conv,status,created,updated) "
                    "VALUES('chat',?,'done',?,?)",
                    (conv_id, stamp, stamp),
                ).lastrowid
                connection.execute(
                    "INSERT INTO chat_requests("
                    "request_id,job,conv,user_message,assistant_message,"
                    "status,created,updated) "
                    "VALUES(?,?,?,?,?,'completed',?,?)",
                    (second_request_id, second_job_id, conv_id,
                     second_user_id, second_assistant_id, stamp, stamp),
                )
            sync.initialize_sync(connection, DEVICE_A)
        return {
            "conv": conv_id,
            "path": path_id,
            "path_public": path_public,
            "candidate_public": candidate_public,
        }

    def _export_two_phases(self, after_cursor=0):
        with app.db() as connection:
            ordinary = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=after_cursor)
            clinical = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=ordinary["cursor"])
        return ordinary, clinical

    def test_consent_split_projection_withdrawal_and_fresh_generation(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        clinical_types = {
            "schema_path", "schema_candidate", "schema_focus_check",
            "schema_step", "schema_origin", "schema_growth",
            "schema_healthy_adult", "schema_transfer",
            "schema_message_meta",
        }
        self.assertIn("session_meta", {
            row["record_type"] for row in ordinary["records"]})
        self.assertFalse(clinical_types.intersection(
            row["record_type"] for row in ordinary["records"]))
        self.assertTrue(clinical["records"])
        self.assertTrue(all(
            row["record_type"] in clinical_types
            for row in clinical["records"]))
        self.assertFalse(clinical["has_more"])

        wire = json.dumps([ordinary, clinical], ensure_ascii=False)
        for forbidden in (
                "PATH-PRIVATE-NEVER-WIRE", "STEP-PRIVATE-NEVER-WIRE",
                "META-PRIVATE-NEVER-WIRE", "META-ACTION-NEVER-WIRE",
                "practice_json", "payload_json", "technique_run",
                "LOCAL-PROVIDER-NEVER-WIRE", "LOCAL-MODEL-NEVER-WIRE",
                "chat_requests", "jobs"):
            self.assertNotIn(forbidden, wire)

        target = self._target_path()

        def apply_preference(connection):
            result = sync.apply_change_batch(connection, ordinary, DEVICE_B)
            state = connection.execute(
                "SELECT schema_clinical_sync_enabled,"
                "schema_clinical_sync_initialized,"
                "schema_clinical_sync_generation FROM session_meta"
            ).fetchone()
            with self.assertRaises(sync.ClinicalSyncConfirmationRequired):
                sync.apply_change_batch(connection, clinical, DEVICE_B)
            rows = connection.execute(
                "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
            cursor = sync.peer_cursor(connection, DEVICE_A)
            return result, tuple(state), rows, cursor

        first_result, pending, clinical_rows, cursor = self._with_database(
            target, apply_preference)
        self.assertGreater(first_result["applied"], 0)
        self.assertEqual(pending, (1, 0, 1))
        self.assertEqual(clinical_rows, 0)
        self.assertEqual(cursor, ordinary["cursor"])

        def confirm_and_apply(connection):
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            result = sync.apply_change_batch(connection, clinical, DEVICE_B)
            counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)
                ).fetchone()[0]
                for table in (
                    "schema_paths", "schema_candidate_queue",
                    "schema_focus_checks", "schema_path_steps",
                    "schema_origin", "schema_growth",
                    "healthy_adult_marks", "schema_transfer_records",
                    "message_meta_events")
            }
            return result, counts

        applied, counts = self._with_database(target, confirm_and_apply)
        self.assertEqual(applied["applied"], len(clinical["records"]))
        self.assertEqual(counts.pop("message_meta_events"), 2)
        self.assertTrue(all(value == 1 for value in counts.values()))

        # Withdrawal keeps the source's private physical rows but emits only
        # payload-free deletes; the receiver applies those without consent.
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_enabled=0,"
                "schema_clinical_sync_initialized=0,updated=? WHERE conv=?",
                ("2026-08-22 12:10:00", ids["conv"]),
            )
            sync.refresh_local_changes(connection, DEVICE_A)
            withdrawal = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])
            source_physical = connection.execute(
                "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
        self.assertEqual(source_physical, 1)
        tombstones = [
            row for row in withdrawal["records"]
            if row["record_type"] in clinical_types]
        self.assertTrue(tombstones)
        self.assertTrue(all(
            row["deleted_at"] is not None and row["payload"] is None
            for row in tombstones))

        def apply_withdrawal(connection):
            result = sync.apply_change_batch(
                connection, withdrawal, DEVICE_B)
            remaining = connection.execute(
                "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
            state = connection.execute(
                "SELECT schema_clinical_sync_enabled,"
                "schema_clinical_sync_initialized,"
                "schema_clinical_sync_generation FROM session_meta"
            ).fetchone()
            return result, remaining, tuple(state)

        _, remaining, disabled = self._with_database(
            target, apply_withdrawal)
        self.assertEqual(remaining, 0)
        self.assertEqual(disabled, (0, 0, 1))

        # Explicit re-enable rotates every live path identity.  It is a fresh
        # namespace, never a direct child revival of the hard tombstone.
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_enabled=1,"
                "schema_clinical_sync_initialized=1,"
                "schema_clinical_sync_generation=2,updated=? WHERE conv=?",
                ("2026-08-22 12:20:00", ids["conv"]),
            )
            app.rekey_schema_v4_path_generation(connection, ids["path"], 2)
            sync.refresh_local_changes(connection, DEVICE_A)
            preference_v2 = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=withdrawal["cursor"])
            clinical_v2 = sync.export_change_batch(
                connection, DEVICE_A,
                after_cursor=preference_v2["cursor"])
            new_path_public = connection.execute(
                "SELECT public_id FROM schema_paths WHERE id=?",
                (ids["path"],),
            ).fetchone()[0]
        self.assertNotEqual(new_path_public, ids["path_public"])
        self.assertTrue(clinical_v2["records"])

        def apply_generation_two(connection):
            sync.apply_change_batch(connection, preference_v2, DEVICE_B)
            with self.assertRaises(sync.ClinicalSyncConfirmationRequired):
                sync.apply_change_batch(connection, clinical_v2, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            applied = sync.apply_change_batch(
                connection, clinical_v2, DEVICE_B)
            # A stale third peer replay of generation one is acknowledged
            # content-free and cannot overwrite/recreate old rows.
            replay = sync.apply_change_batch(connection, clinical, DEVICE_B)
            physical = connection.execute(
                "SELECT public_id,clinical_generation FROM schema_paths"
            ).fetchall()
            conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0]
            return applied, replay, [tuple(row) for row in physical], conflicts

        applied_v2, replay, physical, conflicts = self._with_database(
            target, apply_generation_two)
        self.assertGreater(applied_v2["applied"], 0)
        self.assertEqual(replay["ignored"], len(clinical["records"]))
        self.assertEqual(physical, [(new_path_public, 2)])
        self.assertEqual(conflicts, 0)

    def test_v7_backtrack_lineage_statuses_and_environment_sources_roundtrip(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        self.assertEqual(clinical["version"], 8)
        initial = {
            row["record_type"]: row["payload"]
            for row in clinical["records"]
        }
        self.assertEqual(initial["schema_path"]["practice_status"], "active")
        self.assertEqual(initial["schema_origin"]["status"], "active")
        self.assertEqual(initial["schema_growth"]["status"], "active")
        self.assertEqual(
            initial["schema_growth"]["environment_status"], "active")
        self.assertEqual(
            initial["schema_growth"][
                "environment_source_user_message_public_id"], "b" * 32)
        self.assertEqual(
            initial["schema_growth"][
                "environment_source_assistant_message_public_id"], "a" * 32)
        self.assertEqual(
            initial["schema_healthy_adult"]["status"], "active")
        self.assertIsNone(
            initial["schema_healthy_adult"]["invalidated_at"])
        self.assertEqual(initial["schema_transfer"]["status"], "active")
        self.assertFalse({
            "schema_checkpoint", "schema_method_choice",
        }.intersection(initial))

        target = self._target_path()

        def install_initial(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_initialized=1")
            return sync.apply_change_batch(connection, clinical, DEVICE_B)

        self._with_database(target, install_initial)

        stamp = "2026-08-22 12:30:00"
        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET practice_status='invalidated',"
                "updated=? WHERE id=?", (stamp, ids["path"]))
            connection.execute(
                "UPDATE schema_origin SET status='invalidated',updated=? "
                "WHERE path=?", (stamp, ids["path"]))
            connection.execute(
                "UPDATE schema_growth SET status='invalidated',"
                "environment_status='invalidated',updated=? WHERE path=?",
                (stamp, ids["path"]),
            )
            connection.execute(
                "UPDATE healthy_adult_marks SET status='invalidated',"
                "invalidated_at=? WHERE path=?", (stamp, ids["path"]))
            connection.execute(
                "UPDATE schema_transfer_records SET status='invalidated',"
                "updated=? WHERE path=?", (stamp, ids["path"]))
            refreshed = sync.refresh_local_changes(connection, DEVICE_A)
            lineage = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])
        self.assertGreaterEqual(refreshed["updated"], 5)
        self.assertEqual(lineage["version"], 8)
        projected = {
            row["record_type"]: row["payload"]
            for row in lineage["records"]
        }
        self.assertEqual(set(projected), {
            "schema_path", "schema_origin", "schema_growth",
            "schema_healthy_adult", "schema_transfer",
        })
        for record in lineage["records"]:
            self.assertEqual(
                record["public_id"],
                sync._expected_schema_public_id(
                    record["record_type"], record["payload"]),
            )
        self.assertEqual(projected["schema_path"]["practice_status"],
                         "invalidated")
        self.assertEqual(projected["schema_origin"]["status"],
                         "invalidated")
        self.assertEqual(projected["schema_growth"]["status"],
                         "invalidated")
        self.assertEqual(projected["schema_growth"]["environment_status"],
                         "invalidated")
        self.assertEqual(projected["schema_healthy_adult"]["status"],
                         "invalidated")
        self.assertEqual(
            projected["schema_healthy_adult"]["invalidated_at"], stamp)
        self.assertEqual(projected["schema_transfer"]["status"],
                         "invalidated")

        malicious = copy.deepcopy(lineage)
        malicious["records"] = [next(
            row for row in malicious["records"]
            if row["record_type"] == "schema_healthy_adult")]
        malicious["records"][0]["payload"]["evidence"] = \
            "REMOTE-EVIDENCE-MUST-NOT-CHANGE"

        def reject_mutated_evidence(connection):
            with self.assertRaisesRegex(
                    sync.SyncError, "evidence fields are immutable"):
                sync.apply_change_batch(connection, malicious, DEVICE_B)
            connection.rollback()

        self._with_database(target, reject_mutated_evidence)

        def apply_lineage(connection):
            result = sync.apply_change_batch(connection, lineage, DEVICE_B)
            rows = {
                "path": connection.execute(
                    "SELECT practice_status FROM schema_paths"
                ).fetchone()[0],
                "origin": connection.execute(
                    "SELECT status FROM schema_origin").fetchone()[0],
                "growth": tuple(connection.execute(
                    "SELECT status,environment_status FROM schema_growth"
                ).fetchone()),
                "healthy": tuple(connection.execute(
                    "SELECT status,invalidated_at,evidence "
                    "FROM healthy_adult_marks").fetchone()),
                "transfer": connection.execute(
                    "SELECT status FROM schema_transfer_records"
                ).fetchone()[0],
            }
            return result, rows

        result, rows = self._with_database(target, apply_lineage)
        self.assertEqual(result["applied"], 5)
        self.assertEqual(rows["path"], "invalidated")
        self.assertEqual(rows["origin"], "invalidated")
        self.assertEqual(rows["growth"], ("invalidated", "invalidated"))
        self.assertEqual(rows["healthy"], (
            "invalidated", stamp, "Kullanıcının şefkatli cümlesi"))
        self.assertEqual(rows["transfer"], "invalidated")

    def test_v7_method_and_lineage_enums_are_narrow_and_local_tables_stay_out(self):
        self._seed_projection()
        _ordinary, clinical = self._export_two_phases()
        path_payload = copy.deepcopy(next(
            row["payload"] for row in clinical["records"]
            if row["record_type"] == "schema_path"))
        step_payload = copy.deepcopy(next(
            row["payload"] for row in clinical["records"]
            if row["record_type"] == "schema_step"))
        for step in ("method_select", "method_confirm"):
            path_payload["step"] = step
            step_payload["step"] = step
            sync._validate_payload("schema_path", path_payload)
            sync._validate_payload("schema_step", step_payload)
        for method_id in (
                "", "young:method:imagery-rescripting",
                "young:method:chair-dialogue",
                "young:method:limited-reparenting"):
            path_payload["method_node_id"] = method_id
            sync._validate_payload("schema_path", path_payload)
        path_payload["method_node_id"] = "young:method:unapproved-future"
        with self.assertRaisesRegex(
                sync.SyncError, "invalid enumerated payload field"):
            sync._validate_payload("schema_path", path_payload)
        path_payload["method_node_id"] = \
            "young:method:imagery-rescripting"
        path_payload["step"] = "future_unapproved_method_step"
        with self.assertRaisesRegex(
                sync.SyncError, "invalid enumerated payload field"):
            sync._validate_payload("schema_path", path_payload)

        growth_payload = copy.deepcopy(next(
            row["payload"] for row in clinical["records"]
            if row["record_type"] == "schema_growth"))
        growth_payload.pop(
            "environment_source_assistant_message_public_id")
        with self.assertRaisesRegex(
                sync.SyncError, "environment source pair is incomplete"):
            sync._validate_payload("schema_growth", growth_payload)

        origin_payload = copy.deepcopy(next(
            row["payload"] for row in clinical["records"]
            if row["record_type"] == "schema_origin"))
        origin_payload["status"] = "resurrected"
        with self.assertRaisesRegex(
                sync.SyncError, "invalid enumerated payload field"):
            sync._validate_payload("schema_origin", origin_payload)

        self.assertTrue({
            "schema_path_checkpoints", "schema_path_method_choices",
        } <= sync.DEVICE_LOCAL_CLINICAL_TABLES)
        self.assertFalse({
            "schema_checkpoint", "schema_method_choice",
        }.intersection(sync.RECORD_TYPES))

    def test_real_receiver_stage3_uses_authenticated_synced_pair_and_continues(self):
        self._seed_projection(stage="integrate", step="age_ladder")
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)
            provider, model = app._configured_provider_model_snapshot()
            connection.execute(
                "UPDATE session_meta SET schema_mode_enabled=1,"
                "schema_mode_initialized=1,schema_mode_provider=?,"
                "schema_mode_model=?,updated=?",
                (provider, model, app.now()))
            return int(connection.execute(
                "SELECT id FROM conversations").fetchone()[0])

        target_conv = self._with_database(target, install)
        source_path = app.DB_PATH
        app.DB_PATH = target
        serial = 0
        try:
            def dashboard():
                status, payload, _headers = HTTPTestCase.request(
                    self, "GET",
                    "/api/schema-path?conv_id={}".format(target_conv))
                self.assertEqual(status, 200, payload)
                return payload

            def deliver_real_prompt(request_id):
                """Finish one already-planned provider question atomically."""
                with app.DATA_WRITE_LOCK:
                    with app.db() as connection:
                        request_row = app.chat_request_row(
                            request_id, connection)
                        plan = json.loads(
                            request_row["schema_prompt_plan_json"])
                        connection.execute(
                            "UPDATE messages SET delivery_status='completed' "
                            "WHERE id=?", (request_row["user_message"],))
                        assistant_id = app._upsert_chat_assistant(
                            connection, request_row,
                            "Kısa ve doğal Kerem sorusu?", "completed")
                        stamp = app.now()
                        connection.execute(
                            "UPDATE chat_requests SET status='completed',"
                            "assistant_message=?,finished=?,updated=? "
                            "WHERE request_id=?",
                            (assistant_id, stamp, stamp, request_id))
                        connection.execute(
                            "UPDATE jobs SET status='succeeded',finished=?,"
                            "updated=? WHERE id=?",
                            (stamp, stamp, request_row["job"]))
                        completed = app.chat_request_row(
                            request_id, connection)
                        result = app.schema_v5_apply_prompt_completion(
                            connection, completed, {
                                "version": 1,
                                "intent_id": plan["intent_id"],
                            })
                        connection.execute(
                            "UPDATE chat_requests SET "
                            "schema_binding_result_json=? WHERE request_id=?",
                            (json.dumps(result, ensure_ascii=False,
                                        sort_keys=True), request_id))
                return result

            def answer(text):
                nonlocal serial
                serial += 1
                state = dashboard()
                binding = dict(state["next_card"]["chat_binding"])
                request_id = "schema-real-receiver-{:04d}".format(serial)
                _request_row, created = app.begin_chat_request(
                    target_conv, text, request_id=request_id,
                    schema_binding=binding)
                self.assertTrue(created)
                result = deliver_real_prompt(request_id)
                return result, dashboard()

            with mock.patch.object(app, "open_provider_url") as provider_call:
                state = dashboard()
                provider_call.assert_not_called()
            self.assertEqual((state["stage"], state["step"]),
                             ("integrate", "age_ladder"))
            self.assertEqual(state["active_path"]["status"], "paused")
            self.assertEqual(state["next_card"]["prompt_delivery"]
                             ["status"], "imported_waiting")
            self.assertIs(state["next_card"]["chat_binding"]
                          ["sync_import_control"], True)
            with app.db() as connection:
                self.assertEqual(connection.execute(
                    "SELECT transition_kind FROM schema_path_checkpoints "
                    "WHERE path=? ORDER BY seq DESC LIMIT 1",
                    (state["active_path"]["id"],)).fetchone()[0], "import")
            self.assertFalse(state["next_card"]["checkpoint"][
                "can_backtrack"])

            serial += 1
            resume_id = "schema-real-receiver-{:04d}".format(serial)
            _request, created = app.begin_chat_request(
                target_conv, "Devam", request_id=resume_id,
                schema_binding=dict(state["next_card"]["chat_binding"]))
            self.assertTrue(created)
            resumed = deliver_real_prompt(resume_id)
            self.assertEqual((resumed["stage"], resumed["step"]),
                             ("integrate", "age_ladder"))
            state = dashboard()
            self.assertEqual(state["active_path"]["status"], "active")
            self.assertEqual(state["next_card"]["prompt_delivery"]
                             ["status"], "completed")
            self.assertNotIn("sync_import_control",
                             state["next_card"]["chat_binding"])

            expected = (
                ("Geç", "environment_rescript"),
                ("Geç", "present_transfer"),
                ("Bugünkü konuşma gerildiğinde", "present_transfer"),
                ("Bir an durup ihtiyacımı söyleyebilirim",
                 "optional_practice"),
                ("Sınırımı tek cümleyle söylemek", "followup"),
                ("Geç", "complete"),
            )
            for text, expected_step in expected:
                result, state = answer(text)
                self.assertTrue(result["applied"], (text, result))
                self.assertEqual(result["step"], expected_step,
                                 (text, result))
            self.assertIsNone(state["active_path"])
            with app.db() as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM technique_runs").fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM schema_path_techniques"
                ).fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM chat_requests WHERE request_id="
                    "'schema-clinical-chat-request'"
                ).fetchone()[0], 0)
        finally:
            app.DB_PATH = source_path

    def test_receiver_dashboard_projects_only_current_stage3_lineage(self):
        """Sync bookkeeping statuses are not a second UI authority.

        The v7 RecordSpecs deliberately carry additive status/source columns
        so a peer can retire stale derived rows.  The chat-only dashboard,
        however, projects only current rows: invalidated artifacts disappear,
        while stage/checkpoint/binding remain the sole progression contract.
        Exercise the real GET handler so native/Web decoding cannot silently
        diverge from the helper used by reducers.
        """
        self._seed_projection(stage="integrate", step="age_ladder")
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)
            provider, model = app._configured_provider_model_snapshot()
            connection.execute(
                "UPDATE session_meta SET schema_mode_enabled=1,"
                "schema_mode_initialized=1,schema_mode_provider=?,"
                "schema_mode_model=?,updated=?",
                (provider, model, app.now()))
            return int(connection.execute(
                "SELECT id FROM conversations").fetchone()[0])

        target_conv = self._with_database(target, install)
        source_path = app.DB_PATH
        app.DB_PATH = target
        try:
            def dashboard():
                status, payload, _headers = HTTPTestCase.request(
                    self, "GET",
                    "/api/schema-path?conv_id={}".format(target_conv))
                self.assertEqual(status, 200, payload)
                return payload

            with mock.patch.object(app, "open_provider_url") as provider_call:
                active = dashboard()
                provider_call.assert_not_called()
            self.assertEqual((active["stage"], active["step"]),
                             ("integrate", "age_ladder"))
            self.assertEqual(active["active_path"]["status"], "paused")
            self.assertEqual(active["next_card"]["prompt_delivery"]
                             ["status"], "imported_waiting")
            # practice_status is safe progress state, but practice_json is
            # intentionally device-local. An imported active status therefore
            # cannot expose or fabricate a practice object on this device.
            self.assertIsNone(active["active_path"]["practice"])
            self.assertTrue(active["origin"]["recorded"])
            self.assertEqual(len(active["growth"]["stages"]), 1)
            self.assertEqual(active["healthy_adult"]["count"], 1)
            self.assertTrue(active["present_transfer"]["recorded"])
            binding = active["next_card"]["chat_binding"]
            self.assertRegex(
                binding["checkpoint_public_id"], r"^[0-9a-f]{32}$")
            self.assertGreaterEqual(binding["expected_checkpoint_seq"], 1)

            # These are sync-wire retirement fields, not parallel dashboard
            # state.  Current-only public helpers filter on them instead.
            self.assertNotIn("practice_status", active["active_path"])
            self.assertNotIn("status", active["origin"])
            self.assertNotIn("status", active["growth"]["stages"][0])
            self.assertNotIn(
                "environment_status", active["growth"]["stages"][0])
            for wire_only_key in (
                    "environment_before", "environment_rescripted",
                    "healthy_adult_words",
                    "environment_source_user_message_public_id",
                    "environment_source_assistant_message_public_id"):
                self.assertNotIn(
                    wire_only_key, active["growth"]["stages"][0])
            self.assertNotIn("status", active["healthy_adult"]["recent"][0])
            self.assertNotIn(
                "invalidated_at", active["healthy_adult"]["recent"][0])
            self.assertNotIn("status", active["present_transfer"])

            with app.db() as connection:
                path_id = active["active_path"]["id"]
                self.assertEqual(connection.execute(
                    "SELECT practice_status FROM schema_paths WHERE id=?",
                    (path_id,)).fetchone()[0], "active")
                environment = connection.execute(
                    "SELECT environment_status,"
                    "environment_source_user_message,"
                    "environment_source_assistant_message "
                    "FROM schema_growth WHERE path=?", (path_id,)
                ).fetchone()
                self.assertEqual(environment[0], "active")
                self.assertTrue(environment[1] and environment[2])
                stamp = app.now()
                connection.execute(
                    "UPDATE schema_growth SET "
                    "environment_status='invalidated',updated=? "
                    "WHERE path=?", (stamp, path_id))

            environment_retired = dashboard()
            self.assertEqual(len(environment_retired["growth"]["stages"]), 1)
            self.assertEqual(
                environment_retired["next_card"]["chat_binding"], binding)
            for wire_only_key in (
                    "environment_before", "environment_rescripted",
                    "healthy_adult_words",
                    "environment_status",
                    "environment_source_user_message_public_id",
                    "environment_source_assistant_message_public_id"):
                self.assertNotIn(
                    wire_only_key,
                    environment_retired["growth"]["stages"][0])

            with app.db() as connection:
                connection.execute(
                    "UPDATE schema_paths SET practice_status='invalidated',"
                    "updated=? WHERE id=?", (stamp, path_id))
                connection.execute(
                    "UPDATE schema_origin SET status='invalidated',"
                    "updated=? WHERE path=?", (stamp, path_id))
                connection.execute(
                    "UPDATE schema_growth SET status='invalidated',"
                    "updated=? WHERE path=?", (stamp, path_id))
                connection.execute(
                    "UPDATE healthy_adult_marks SET status='invalidated',"
                    "invalidated_at=? WHERE path=?", (stamp, path_id))
                connection.execute(
                    "UPDATE schema_transfer_records SET "
                    "status='invalidated',updated=? WHERE path=?",
                    (stamp, path_id))
                before = tuple(connection.execute(
                    "SELECT revision,(SELECT COUNT(*) FROM "
                    "schema_path_checkpoints WHERE path=schema_paths.id) "
                    "FROM schema_paths WHERE id=?", (path_id,)).fetchone())

            with mock.patch.object(app, "open_provider_url") as provider_call:
                retired = dashboard()
                repeated = dashboard()
                provider_call.assert_not_called()
            self.assertIsNone(retired["active_path"]["practice"])
            self.assertFalse(retired["origin"]["recorded"])
            self.assertEqual(retired["growth"]["stages"], [])
            self.assertEqual(retired["healthy_adult"], {
                "count": 0, "recent": []})
            self.assertEqual(retired["present_transfer"], {
                "recorded": False})
            self.assertEqual((retired["stage"], retired["step"]),
                             ("integrate", "age_ladder"))
            self.assertEqual(
                retired["next_card"]["chat_binding"],
                repeated["next_card"]["chat_binding"])
            with app.db() as connection:
                after = tuple(connection.execute(
                    "SELECT revision,(SELECT COUNT(*) FROM "
                    "schema_path_checkpoints WHERE path=schema_paths.id) "
                    "FROM schema_paths WHERE id=?", (path_id,)).fetchone())
                retained = tuple(connection.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM schema_origin WHERE path=?),"
                    "(SELECT COUNT(*) FROM schema_growth WHERE path=?),"
                    "(SELECT COUNT(*) FROM healthy_adult_marks WHERE path=?),"
                    "(SELECT COUNT(*) FROM schema_transfer_records "
                    "WHERE path=?)", (path_id, path_id, path_id, path_id)
                ).fetchone())
            self.assertEqual(after, before)
            self.assertEqual(retained, (1, 1, 1, 1))
        finally:
            app.DB_PATH = source_path

    def test_v7_turn_pair_wire_shape_and_immutable_binding_are_strict(self):
        self._seed_projection()
        ordinary, _clinical = self._export_two_phases()
        message_records = [
            row for row in ordinary["records"]
            if row["record_type"] == "message"
        ]
        self.assertEqual(len(message_records), 2)
        self.assertEqual({
            row["payload"]["turn_pair_public_id"]
            for row in message_records
        }, {app._chat_turn_pair_public_id(
            "schema-clinical-chat-request")})

        malformed = []
        missing = copy.deepcopy(ordinary)
        missing["records"] = [copy.deepcopy(message_records[0])]
        missing["records"][0]["payload"].pop("turn_pair_public_id")
        malformed.append((missing, "required logical record field"))

        extra = copy.deepcopy(ordinary)
        extra["records"] = [copy.deepcopy(message_records[0])]
        extra["records"][0]["payload"]["chat_request_id"] = "private"
        malformed.append((extra, "unknown logical record fields"))

        wrong_type = copy.deepcopy(ordinary)
        wrong_type["records"] = [copy.deepcopy(message_records[0])]
        wrong_type["records"][0]["payload"]["turn_pair_public_id"] = 7
        malformed.append((wrong_type, "text payload field"))

        noncanonical = copy.deepcopy(ordinary)
        noncanonical["records"] = [copy.deepcopy(message_records[0])]
        noncanonical["records"][0]["payload"][
            "turn_pair_public_id"] = "A" * 32
        malformed.append((noncanonical, "completed-turn pair identity"))

        duplicate_role = copy.deepcopy(ordinary)
        duplicate_role["records"] = copy.deepcopy(message_records)
        duplicate_role["records"][1]["payload"]["role"] = "user"
        malformed.append((duplicate_role, "pair role is duplicated"))

        for batch, error in malformed:
            with self.subTest(error=error):
                with self.assertRaisesRegex(sync.SyncError, error):
                    sync.validate_change_batch(batch)

        target = self._target_path()

        def install(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            row = connection.execute(
                "SELECT turn_pair_public_id FROM messages WHERE public_id=?",
                (message_records[0]["public_id"],),
            ).fetchone()
            return str(row[0]), sync.peer_cursor(connection, DEVICE_A)

        before = self._with_database(target, install)
        changed = copy.deepcopy(message_records[0])
        changed["revision"] = int(changed["revision"]) + 1
        changed["parent_origin_device_id"] = changed["origin_device_id"]
        changed["parent_revision"] = int(changed["revision"]) - 1
        changed["updated_at"] = "2026-08-22T12:10:00+00:00"
        changed["payload"]["turn_pair_public_id"] = "f" * 32
        tampered = {
            "kind": sync.BATCH_KIND,
            "version": sync.BATCH_VERSION,
            "sender_device_id": DEVICE_A,
            "after_cursor": ordinary["cursor"],
            "cursor": ordinary["cursor"] + 1,
            "ack_cursor": 0,
            "has_more": False,
            "records": [changed],
        }

        with self.assertRaisesRegex(
                sync.SyncError, "immutable message turn-pair identity"):
            self._with_database(
                target,
                lambda connection: sync.apply_change_batch(
                    connection, tampered, DEVICE_B),
            )

        def read_after_rejection(connection):
            row = connection.execute(
                "SELECT turn_pair_public_id FROM messages WHERE public_id=?",
                (message_records[0]["public_id"],),
            ).fetchone()
            return str(row[0]), sync.peer_cursor(connection, DEVICE_A)

        self.assertEqual(
            self._with_database(target, read_after_rejection), before)

    def test_v7_pair_lineage_rejects_cross_pair_and_shuffled_stage3_passes(self):
        self._seed_projection(
            stage="integrate", step="age_ladder", include_second_pair=True)
        stamp = "2026-08-22 12:06:00"
        second_user_public = "d" * 32
        second_assistant_public = "e" * 32
        second_request_id = "schema-clinical-second-request"
        second_pair_public = app._chat_turn_pair_public_id(second_request_id)
        ordinary, clinical = self._export_two_phases()
        message_payloads = {
            row["public_id"]: row["payload"]
            for row in ordinary["records"]
            if row["record_type"] == "message"
        }
        self.assertEqual(
            message_payloads[second_user_public]["reply_to_public_id"],
            "a" * 32)
        self.assertEqual(
            message_payloads[second_assistant_public]["reply_to_public_id"],
            "a" * 32)
        self.assertEqual({
            message_payloads[second_user_public]["turn_pair_public_id"],
            message_payloads[second_assistant_public]["turn_pair_public_id"],
        }, {second_pair_public})

        shuffled = copy.deepcopy(ordinary)
        shuffled["records"] = list(reversed(shuffled["records"]))
        target = self._target_path()

        def install_shuffled(connection):
            result = sync.apply_change_batch(connection, shuffled, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            local_ids = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT public_id,id FROM messages WHERE public_id IN "
                    "(?,?,?,?)",
                    ("b" * 32, "a" * 32,
                     second_user_public, second_assistant_public),
                )
            }
            target_conv = int(connection.execute(
                "SELECT id FROM conversations WHERE public_id=?",
                ("c" * 32,),
            ).fetchone()[0])
            replies = tuple(str(row[0]) for row in connection.execute(
                "SELECT q.public_id FROM messages m "
                "LEFT JOIN messages q ON q.id=m.reply_to "
                "WHERE m.public_id IN (?,?) ORDER BY m.public_id",
                (second_user_public, second_assistant_public),
            ).fetchall())
            safe = (
                sync._schema_source_pair_is_safe(
                    connection, target_conv, local_ids["b" * 32],
                    local_ids["a" * 32]),
                sync._schema_source_pair_is_safe(
                    connection, target_conv, local_ids[second_user_public],
                    local_ids[second_assistant_public]),
                sync._schema_source_pair_is_safe(
                    connection, target_conv, local_ids["b" * 32],
                    local_ids[second_assistant_public]),
            )
            return result, target_conv, local_ids, replies, safe

        (install_result, target_conv, local_ids,
         replies, safe) = self._with_database(target, install_shuffled)
        self.assertGreater(install_result["applied"], 0)
        self.assertEqual(replies, ("a" * 32, "a" * 32))
        self.assertEqual(safe, (True, True, False))

        crossed = copy.deepcopy(clinical)
        crossed_origin = next(
            row for row in crossed["records"]
            if row["record_type"] == "schema_origin")
        crossed_origin["payload"][
            "source_assistant_message_public_id"] = second_assistant_public
        with self.assertRaisesRegex(
                sync.SyncError, "clinical sync source pair is not safe"):
            self._with_database(
                target,
                lambda connection: sync.apply_change_batch(
                    connection, crossed, DEVICE_B),
            )

        def after_cross_rejection(connection):
            return (
                sync.peer_cursor(connection, DEVICE_A),
                connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            )

        self.assertEqual(
            self._with_database(target, after_cross_rejection),
            (ordinary["cursor"], 0, 0))

        def apply_valid_and_check_guards(connection):
            result = sync.apply_change_batch(connection, clinical, DEVICE_B)
            stage3 = tuple(connection.execute(
                "SELECT stage,step FROM schema_paths").fetchone())
            first_user_id = local_ids["b" * 32]
            first_assistant_id = local_ids["a" * 32]
            self.assertTrue(sync._schema_source_pair_is_safe(
                connection, target_conv, first_user_id, first_assistant_id))
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat',?,'failed',?,?)",
                (target_conv, stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO chat_requests("
                "request_id,job,conv,user_message,assistant_message,status,"
                "created,updated) VALUES('receiver-shadow-request',?,?,?,?,"
                "'failed',?,?)",
                (job_id, target_conv, first_user_id, first_assistant_id,
                 stamp, stamp),
            )
            shadow_blocked = not sync._schema_source_pair_is_safe(
                connection, target_conv, first_user_id, first_assistant_id)
            connection.execute(
                "DELETE FROM chat_requests WHERE request_id="
                "'receiver-shadow-request'")
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            connection.execute(
                "UPDATE sync_records SET deleted_at=? WHERE "
                "record_type='message' AND local_id=?",
                (stamp, first_assistant_id),
            )
            tombstone_blocked = not sync._schema_source_pair_is_safe(
                connection, target_conv, first_user_id, first_assistant_id)
            connection.execute(
                "UPDATE sync_records SET deleted_at=NULL WHERE "
                "record_type='message' AND local_id=?",
                (first_assistant_id,),
            )
            connection.execute(
                "INSERT INTO safety_events(conv,source_message,kind,"
                "detector_context,status,created) "
                "VALUES(?,?,'test','source','released',?)",
                (target_conv, first_user_id, stamp),
            )
            safety_blocked = not sync._schema_source_pair_is_safe(
                connection, target_conv, first_user_id, first_assistant_id)
            return result, stage3, (
                shadow_blocked, tombstone_blocked, safety_blocked)

        valid, stage3, guards = self._with_database(
            target, apply_valid_and_check_guards)
        self.assertGreater(valid["applied"], 0)
        self.assertEqual(stage3, ("integrate", "age_ladder"))
        self.assertEqual(guards, (True, True, True))

    def test_v7_rejects_legacy_or_arbitrary_method_before_any_mutation(self):
        self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install_preference(connection):
            result = sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_initialized=1")
            return result, sync.peer_cursor(connection, DEVICE_A)

        _result, preference_cursor = self._with_database(
            target, install_preference)
        self.assertEqual(preference_cursor, ordinary["cursor"])

        invalid_batches = []
        for method_id in (
                "schema_imagery", "young:method:unapproved-future"):
            invalid = copy.deepcopy(clinical)
            path_record = next(
                row for row in invalid["records"]
                if row["record_type"] == "schema_path")
            path_record["payload"]["method_node_id"] = method_id
            invalid_batches.append(invalid)

        def reject_without_mutation(connection):
            for invalid in invalid_batches:
                before_changes = connection.total_changes
                before_cursor = sync.peer_cursor(connection, DEVICE_A)
                before_paths = connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
                with self.assertRaisesRegex(
                        sync.SyncError,
                        "invalid enumerated payload field"):
                    sync.apply_change_batch(connection, invalid, DEVICE_B)
                self.assertEqual(connection.total_changes, before_changes)
                self.assertEqual(
                    sync.peer_cursor(connection, DEVICE_A), before_cursor)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
                    before_paths)

        self._with_database(target, reject_without_mutation)

        def apply_canonical(connection):
            result = sync.apply_change_batch(connection, clinical, DEVICE_B)
            method_id = connection.execute(
                "SELECT method_node_id FROM schema_paths").fetchone()[0]
            return result, method_id

        result, method_id = self._with_database(target, apply_canonical)
        self.assertGreater(result["applied"], 0)
        self.assertEqual(
            method_id, "young:method:imagery-rescripting")

    def test_live_clinical_records_require_a_dedicated_batch(self):
        self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        ordinary_record = next(
            row for row in ordinary["records"]
            if row["record_type"] not in sync._SCHEMA_CLINICAL_RECORD_TYPES)
        clinical_record = next(
            row for row in clinical["records"]
            if row["deleted_at"] is None)
        mixed = dict(clinical)
        mixed["records"] = [ordinary_record, clinical_record]
        mixed["after_cursor"] = 0
        mixed["cursor"] = max(ordinary["cursor"], clinical["cursor"])
        mixed["ack_cursor"] = 0
        mixed["has_more"] = False

        target = self._target_path()

        def reject_without_mutation(connection):
            sync.initialize_sync(connection, DEVICE_B)
            before = {
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "conversations": connection.execute(
                    "SELECT COUNT(*) FROM conversations").fetchone()[0],
                "paths": connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
            }
            with self.assertRaisesRegex(
                    sync.SyncError, "dedicated clinical batch"):
                sync.apply_change_batch(connection, mixed, DEVICE_B)
            after = {
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "conversations": connection.execute(
                    "SELECT COUNT(*) FROM conversations").fetchone()[0],
                "paths": connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
            }
            return before, after

        before, after = self._with_database(target, reject_without_mutation)
        self.assertEqual(after, before)

    def test_concurrent_clinical_edits_pause_for_explicit_resolution(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install_initial(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)

        self._with_database(target, install_initial)

        with app.db() as connection:
            connection.execute(
                "UPDATE schema_paths SET focus_label=?,revision=9,updated=? "
                "WHERE id=?",
                ("SOURCE-CLINICAL-BRANCH", "2026-08-22 12:30:00",
                 ids["path"]),
            )
            sync.record_local_change(
                connection, "schema_path", ids["path"], DEVICE_A)
            source_edit = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])
        self.assertEqual(
            [row["record_type"] for row in source_edit["records"]],
            ["schema_path"])

        def create_target_branch_and_apply(connection):
            path_id = connection.execute(
                "SELECT id FROM schema_paths WHERE public_id=?",
                (ids["path_public"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE schema_paths SET focus_label=?,revision=9,updated=? "
                "WHERE id=?",
                ("TARGET-CLINICAL-BRANCH", "2026-08-22 12:31:00", path_id),
            )
            sync.record_local_change(
                connection, "schema_path", int(path_id), DEVICE_B)
            result = sync.apply_change_batch(
                connection, source_edit, DEVICE_B)
            label = connection.execute(
                "SELECT focus_label FROM schema_paths WHERE id=?",
                (path_id,),
            ).fetchone()[0]
            conflict = connection.execute(
                "SELECT id,record_type,reason,local_json,incoming_json,status "
                "FROM sync_conflicts WHERE record_type='schema_path'"
            ).fetchone()
            marker = connection.execute(
                "SELECT path_public_id,status,reason "
                "FROM schema_path_sync_conflicts"
            ).fetchone()
            return (
                result, label, tuple(conflict), tuple(marker),
                sync.local_cursor_high_water(connection),
            )

        result, label, conflict, marker, before_resolution_cursor = \
            self._with_database(
            target, create_target_branch_and_apply)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(label, "TARGET-CLINICAL-BRANCH")
        self.assertEqual(conflict[1:3], (
            "schema_path", "concurrent_schema_edit"))
        self.assertIn("TARGET-CLINICAL-BRANCH", conflict[3])
        self.assertIn("SOURCE-CLINICAL-BRANCH", conflict[4])
        self.assertEqual(conflict[5], "open")
        self.assertEqual(marker, (
            ids["path_public"], "open", "concurrent_schema_edit"))

        # Keeping this device's branch must first install the rejected remote
        # branch as the causal parent, then publish the selected payload as a
        # direct child.  Otherwise the next QR would recreate the same
        # clinical conflict forever instead of converging.
        original = app.DB_PATH
        app.DB_PATH = target
        try:
            with mock.patch.object(
                    sync_service, "_device_id", return_value=DEVICE_B), \
                    mock.patch.object(
                        sync_service, "_snapshot_callback", None):
                resolved = sync_service.resolve_conflict(
                    int(conflict[0]), "local")
            with app.db() as connection:
                resolution_batch = sync.export_change_batch(
                    connection, DEVICE_B,
                    after_cursor=before_resolution_cursor)
                target_state = connection.execute(
                    "SELECT p.focus_label,m.status FROM schema_paths p "
                    "JOIN schema_path_sync_conflicts m "
                    "ON m.path_public_id=p.public_id WHERE p.public_id=?",
                    (ids["path_public"],),
                ).fetchone()
                target_open = connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
                ).fetchone()[0]
        finally:
            app.DB_PATH = original

        self.assertEqual(resolved["conflicts"], [])
        self.assertEqual(tuple(target_state), (
            "TARGET-CLINICAL-BRANCH", "resolved"))
        self.assertEqual(target_open, 0)
        self.assertEqual(
            [row["record_type"] for row in resolution_batch["records"]],
            ["schema_path"])
        resolution = resolution_batch["records"][0]
        source_head = source_edit["records"][0]
        self.assertEqual(
            (resolution["parent_origin_device_id"],
             resolution["parent_revision"]),
            (source_head["origin_device_id"], source_head["revision"]),
        )
        self.assertEqual(
            resolution["payload"]["focus_label"],
            "TARGET-CLINICAL-BRANCH")

        with app.db() as connection:
            converged = sync.apply_change_batch(
                connection, resolution_batch, DEVICE_A)
            source_label = connection.execute(
                "SELECT focus_label FROM schema_paths WHERE id=?",
                (ids["path"],),
            ).fetchone()[0]
            source_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
            ).fetchone()[0]
        self.assertEqual(converged["conflicts"], 0)
        self.assertEqual(source_label, "TARGET-CLINICAL-BRANCH")
        self.assertEqual(source_conflicts, 0)

    def test_forged_schema_natural_id_is_rejected_before_any_mutation(self):
        self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install_preference(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")

        self._with_database(target, install_preference)

        path_forgery = json.loads(json.dumps(clinical))
        path_record = next(
            row for row in path_forgery["records"]
            if row["record_type"] == "schema_path")
        path_record["public_id"] = app._schema_natural_public_id(
            "path", "d" * 32, 1, 1)

        candidate_forgery = json.loads(json.dumps(clinical))
        candidate_record = next(
            row for row in candidate_forgery["records"]
            if row["record_type"] == "schema_candidate")
        payload = candidate_record["payload"]
        candidate_record["public_id"] = app._schema_natural_public_id(
            "candidate", payload["conversation_public_id"],
            payload["clinical_generation"],
            payload["source_user_message_public_id"],
            payload["source_assistant_message_public_id"],
            "emotional_deprivation", payload["mode_key"] or "-")

        def reject_without_retention(connection):
            before = (
                connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            )
            for forged in (path_forgery, candidate_forgery):
                with self.assertRaisesRegex(
                        sync.SyncError, "public identity is not canonical"):
                    sync.apply_change_batch(connection, forged, DEVICE_B)
            after = (
                connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            )
            clinical_rows = sum(
                connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "schema_paths", "schema_candidate_queue",
                    "schema_focus_checks", "schema_path_steps",
                    "schema_origin", "schema_growth",
                    "healthy_adult_marks", "schema_transfer_records",
                    "message_meta_events"))
            return before, after, clinical_rows

        before, after, clinical_rows = self._with_database(
            target, reject_without_retention)
        self.assertEqual(after, before)
        self.assertEqual(clinical_rows, 0)

    def test_private_and_undone_map_meta_leave_only_tombstones_on_peer(self):
        self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)
            return connection.execute(
                "SELECT COUNT(*) FROM message_meta_events").fetchone()[0]

        self.assertEqual(self._with_database(target, install), 2)

        with app.db() as connection:
            meta_rows = connection.execute(
                "SELECT id FROM message_meta_events ORDER BY id").fetchall()
            connection.execute(
                "UPDATE message_meta_events SET status='private' "
                "WHERE id=?", (meta_rows[0][0],))
            connection.execute(
                "UPDATE message_meta_events SET status='undone' "
                "WHERE id=?", (meta_rows[1][0],))
            sync.refresh_local_changes(connection, DEVICE_A)
            redaction = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])

        meta_records = [
            row for row in redaction["records"]
            if row["record_type"] == "schema_message_meta"]
        self.assertEqual(len(meta_records), 2)
        self.assertTrue(all(
            row["deleted_at"] is not None and row["payload"] is None
            for row in meta_records))

        def apply_redaction(connection):
            sync.apply_change_batch(connection, redaction, DEVICE_B)
            return (
                connection.execute(
                    "SELECT COUNT(*) FROM message_meta_events").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            )

        self.assertEqual(self._with_database(target, apply_redaction), (0, 0))

    def test_conversation_delete_tombstones_every_clinical_projection(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)

        self._with_database(target, install)

        with app.db() as connection:
            sync.record_local_delete(
                connection, "conversation", ids["conv"], DEVICE_A,
                physical=False)
            deletion = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])

        clinical_deletes = [
            row for row in deletion["records"]
            if row["record_type"] in sync._SCHEMA_CLINICAL_RECORD_TYPES]
        self.assertEqual(len(clinical_deletes), len(clinical["records"]))
        self.assertTrue(all(
            row["deleted_at"] is not None and row["payload"] is None
            for row in clinical_deletes))

        def apply_delete(connection):
            result = sync.apply_change_batch(connection, deletion, DEVICE_B)
            remaining = sum(
                connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "schema_paths", "schema_candidate_queue",
                    "schema_focus_checks", "schema_path_steps",
                    "schema_origin", "schema_growth",
                    "healthy_adult_marks", "schema_transfer_records",
                    "message_meta_events"))
            return result, remaining

        result, remaining = self._with_database(target, apply_delete)
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(remaining, 0)

    def test_local_safety_hold_pauses_without_ack_and_replays_after_clear(self):
        self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install_preference_and_hold(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            connection.execute(
                "UPDATE conversations SET safety_hold=1")
            with self.assertRaises(sync.ClinicalSyncSafetyPause):
                sync.apply_change_batch(connection, clinical, DEVICE_B)
            held = (
                connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
                sync.peer_cursor(connection, DEVICE_A),
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            )
            connection.execute(
                "UPDATE conversations SET safety_hold=0")
            result = sync.apply_change_batch(connection, clinical, DEVICE_B)
            return held, result, connection.execute(
                "SELECT COUNT(*) FROM schema_paths").fetchone()[0]

        held, result, path_count = self._with_database(
            target, install_preference_and_hold)
        self.assertEqual(held, (0, ordinary["cursor"], 0))
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(path_count, 1)

    def test_source_safety_hold_keeps_unsent_clinical_cursor_replayable(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (ids["conv"],))
            sync.record_local_change(
                connection, "conversation", ids["conv"], DEVICE_A)
            with self.assertRaises(sync.ClinicalSyncSafetyPause):
                sync.export_change_batch(
                    connection, DEVICE_A,
                    after_cursor=ordinary["cursor"])
            connection.execute(
                "UPDATE conversations SET safety_hold=0 WHERE id=?",
                (ids["conv"],))
            replay = sync.export_change_batch(
                connection, DEVICE_A,
                after_cursor=ordinary["cursor"])

        self.assertEqual(replay["cursor"], clinical["cursor"])
        self.assertEqual(replay["records"], clinical["records"])

    def test_released_source_safety_event_keeps_canonical_withdrawal_final(self):
        ids = self._seed_projection()
        stamp = "2026-08-22 12:05:00"

        with app.db() as connection:
            source_user = connection.execute(
                "SELECT id FROM messages WHERE conv=? AND public_id=?",
                (ids["conv"], "b" * 32),
            ).fetchone()[0]
            before = {
                (str(row[0]), int(row[1])): (str(row[2]), int(row[3]))
                for row in connection.execute(
                    "SELECT record_type,local_id,public_id,revision "
                    "FROM sync_records WHERE deleted_at IS NULL AND "
                    "record_type IN ({}) ORDER BY record_type,local_id".format(
                        ",".join(
                            "?" for _ in sync._SCHEMA_CLINICAL_RECORD_TYPES
                        )
                    ),
                    tuple(sorted(sync._SCHEMA_CLINICAL_RECORD_TYPES)),
                )
            }
            self.assertTrue(before)
            native_before = {
                identity: connection.execute(
                    "SELECT public_id FROM {} WHERE {}=?".format(
                        sync.RECORD_TYPES[identity[0]].table,
                        sync.RECORD_TYPES[identity[0]].primary_key,
                    ),
                    (identity[1],),
                ).fetchone()[0]
                for identity in before
            }
            event_id = connection.execute(
                "INSERT INTO safety_events("
                "conv,source_message,kind,detector_context,detector_version,"
                "status,created) VALUES(?,?,'crisis','turn',1,'active',?)",
                (ids["conv"], source_user, stamp),
            ).lastrowid
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (ids["conv"],),
            )

            active = sync.refresh_local_changes(connection, DEVICE_A)
            tombstones = {
                (str(row[0]), str(row[1])): (
                    int(row[2]), row[3], row[4]
                )
                for row in connection.execute(
                    "SELECT record_type,public_id,revision,local_id,deleted_at "
                    "FROM sync_records WHERE record_type IN ({}) "
                    "ORDER BY record_type,public_id".format(
                        ",".join(
                            "?" for _ in sync._SCHEMA_CLINICAL_RECORD_TYPES
                        )
                    ),
                    tuple(sorted(sync._SCHEMA_CLINICAL_RECORD_TYPES)),
                )
            }
            expected_public = {
                (record_type, value[0])
                for (record_type, _local_id), value in before.items()
            }
            self.assertEqual(set(tombstones), expected_public)
            self.assertEqual(active["policy_redacted"], len(before))
            self.assertTrue(all(
                local_id is None and deleted_at is not None
                for _revision, local_id, deleted_at in tombstones.values()
            ))
            self.assertEqual({
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    "SELECT record_type,public_id FROM sync_excluded_records "
                    "WHERE reason='policy_withdrawn' AND record_type IN ({})"
                    .format(
                        ",".join(
                            "?" for _ in sync._SCHEMA_CLINICAL_RECORD_TYPES
                        )
                    ),
                    tuple(sorted(sync._SCHEMA_CLINICAL_RECORD_TYPES)),
                )
            }, expected_public)

            connection.execute(
                "UPDATE safety_events SET status='released',resolved_at=? "
                "WHERE id=?", (stamp, event_id),
            )
            connection.execute(
                "UPDATE conversations SET safety_hold=0 WHERE id=?",
                (ids["conv"],),
            )
            released = sync.refresh_local_changes(connection, DEVICE_A)
            repeated = sync.refresh_local_changes(connection, DEVICE_A)

            self.assertEqual(released["policy_redacted"], 0)
            self.assertEqual(repeated["policy_redacted"], 0)
            self.assertEqual(repeated["added"], 0)
            self.assertEqual(repeated["updated"], 0)
            self.assertEqual(repeated["deleted"], 0)
            self.assertEqual({
                (str(row[0]), str(row[1])): (
                    int(row[2]), row[3], row[4]
                )
                for row in connection.execute(
                    "SELECT record_type,public_id,revision,local_id,deleted_at "
                    "FROM sync_records WHERE record_type IN ({}) "
                    "ORDER BY record_type,public_id".format(
                        ",".join(
                            "?" for _ in sync._SCHEMA_CLINICAL_RECORD_TYPES
                        )
                    ),
                    tuple(sorted(sync._SCHEMA_CLINICAL_RECORD_TYPES)),
                )
            }, tombstones)
            self.assertEqual({
                identity: connection.execute(
                    "SELECT public_id FROM {} WHERE {}=?".format(
                        sync.RECORD_TYPES[identity[0]].table,
                        sync.RECORD_TYPES[identity[0]].primary_key,
                    ),
                    (identity[1],),
                ).fetchone()[0]
                for identity in before
            }, native_before)

    def test_host_returns_clean_safety_pause_without_acknowledging(self):
        self.addCleanup(sync_service.reset_runtime_state)
        _, clinical = self._export_two_phases_after_seed()
        target = self._target_path()

        def install_preference_and_hold(connection):
            ordinary, _ = self._last_two_phases
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            connection.execute(
                "UPDATE conversations SET safety_hold=1")

        self._with_database(target, install_preference_and_hold)
        original = app.DB_PATH
        app.DB_PATH = target
        try:
            sync_service.reset_runtime_state()
            peer = sync_service.transport.PeerIdentity(
                device_id=DEVICE_A, fingerprint="f" * 64,
                name="Mac", platform="macos", address="192.168.1.20")
            response = sync_service._host_on_batch([clinical], peer)
            state = sync_service.status()
            with app.db() as connection:
                path_count = connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
                remote_cursor = sync.peer_cursor(connection, DEVICE_A)
        finally:
            app.DB_PATH = original

        self.assertTrue(response["clinical_safety_pause"])
        self.assertEqual(response["clinical_safety_device"], "computer")
        self.assertFalse(response["clinical_confirmation_required"])
        self.assertFalse(response["more"])
        self.assertEqual(response["apply"]["records"], 0)
        self.assertEqual(response["batch"]["records"], [])
        self.assertEqual(path_count, 0)
        self.assertEqual(remote_cursor, self._last_two_phases[0]["cursor"])
        self.assertTrue(state["last_summary"]["clinical_safety_pause"])

    def test_host_outbound_safety_pause_does_not_offer_clinical_cursor(self):
        self.addCleanup(sync_service.reset_runtime_state)
        ids = self._seed_projection()
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (ids["conv"],))
            sync.record_local_change(
                connection, "conversation", ids["conv"], DEVICE_A)
        sync_service.reset_runtime_state()
        peer = sync_service.transport.PeerIdentity(
            device_id=DEVICE_B, fingerprint="e" * 64,
            name="Android", platform="android", address="192.168.1.30")

        def empty_batch(ack_cursor):
            return {
                "kind": sync.BATCH_KIND, "version": sync.BATCH_VERSION,
                "sender_device_id": DEVICE_B, "after_cursor": 0,
                "cursor": 0, "ack_cursor": ack_cursor,
                "has_more": False, "records": [],
            }

        first = sync_service._host_on_batch([empty_batch(0)], peer)
        self.assertFalse(first["clinical_safety_pause"])
        self.assertTrue(first["batch"]["records"])
        offered_ordinary = first["batch"]["cursor"]
        second = sync_service._host_on_batch(
            [empty_batch(offered_ordinary)], peer)
        self.assertTrue(second["clinical_safety_pause"])
        self.assertEqual(second["clinical_safety_device"], "computer")
        self.assertEqual(second["batch"]["cursor"], offered_ordinary)
        self.assertEqual(second["batch"]["records"], [])
        with app.db() as connection:
            self.assertEqual(
                sync.peer_offered_cursor(connection, DEVICE_B),
                offered_ordinary)

    def test_host_returns_clean_confirmation_pause_without_acknowledging(self):
        self.addCleanup(sync_service.reset_runtime_state)
        _, clinical = self._export_two_phases_after_seed()
        target = self._target_path()

        def install_preference(connection):
            ordinary, _ = self._last_two_phases
            sync.apply_change_batch(connection, ordinary, DEVICE_B)

        self._with_database(target, install_preference)
        original = app.DB_PATH
        app.DB_PATH = target
        try:
            sync_service.reset_runtime_state()
            peer = sync_service.transport.PeerIdentity(
                device_id=DEVICE_A, fingerprint="f" * 64,
                name="Mac", platform="macos", address="192.168.1.20")
            response = sync_service._host_on_batch([clinical], peer)
            state = sync_service.status()
            with app.db() as connection:
                path_count = connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
                remote_cursor = sync.peer_cursor(connection, DEVICE_A)
        finally:
            app.DB_PATH = original

        self.assertTrue(response["clinical_confirmation_required"])
        self.assertEqual(response["clinical_confirmation_device"], "computer")
        self.assertFalse(response["more"])
        self.assertEqual(response["apply"]["records"], 0)
        self.assertEqual(response["batch"]["records"], [])
        self.assertEqual(path_count, 0)
        self.assertEqual(remote_cursor, self._last_two_phases[0]["cursor"])
        self.assertEqual(state["pending_clinical_confirmation_count"], 1)
        self.assertEqual(state["pending_clinical_confirmation_conv_ids"], [1])
        self.assertTrue(
            state["last_summary"]["clinical_confirmation_required"])

    def test_join_returns_local_confirmation_cta_as_partial_success(self):
        self.addCleanup(sync_service.reset_runtime_state)
        _, clinical = self._export_two_phases_after_seed()
        target = self._target_path()

        def install_preference(connection):
            ordinary, _ = self._last_two_phases
            sync.apply_change_batch(connection, ordinary, DEVICE_B)

        self._with_database(target, install_preference)
        invitation = {
            "v": 1, "scheme": "https", "host": "192.168.1.10",
            "port": 44321, "session_id": "unused",
            "pairing_secret": "unused", "cert_sha256": "a" * 64,
            "desktop_device_id": DEVICE_A, "expires_at": 4102444800,
            "path": "/v1",
        }

        class FakeClient:
            def run_batches(self, next_batch, apply_result, *, max_rounds):
                next_batch(None)
                apply_result({
                    "batch": clinical,
                    "more": True,
                    "apply": {"records": 0, "conflicts": 0},
                    "confirmation_required": False,
                    "clinical_confirmation_required": False,
                    "exact_equal": False,
                    "projection": None,
                    "live_count": None,
                })

            def close(self):
                pass

        original = app.DB_PATH
        app.DB_PATH = target
        try:
            sync_service.reset_runtime_state()
            with mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    return_value=invitation), mock.patch.object(
                    sync_service.transport, "pair_with_invitation",
                    return_value=(FakeClient(), {"ok": True})):
                result = sync_service.join(
                    "fresh-qr", device_name="Android", platform_name="android")
            with app.db() as connection:
                path_count = connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
        finally:
            app.DB_PATH = original

        self.assertTrue(result["ok"])
        self.assertFalse(result["exact_equal"])
        self.assertTrue(result["clinical_confirmation_required"])
        self.assertEqual(result["clinical_confirmation_device"], "this_device")
        self.assertIn("bu cihazda onaylayın", result[
            "clinical_confirmation_message"])
        self.assertEqual(result["pending_clinical_confirmation_conv_ids"], [1])
        self.assertEqual(result["pending_clinical_confirmation_count"], 1)
        self.assertEqual(path_count, 0)

    def test_join_returns_local_safety_pause_as_retryable_success(self):
        self.addCleanup(sync_service.reset_runtime_state)
        _, clinical = self._export_two_phases_after_seed()
        target = self._target_path()

        def install_preference_and_hold(connection):
            ordinary, _ = self._last_two_phases
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            connection.execute(
                "UPDATE conversations SET safety_hold=1")

        self._with_database(target, install_preference_and_hold)
        invitation = {
            "v": 1, "scheme": "https", "host": "192.168.1.10",
            "port": 44321, "session_id": "unused",
            "pairing_secret": "unused", "cert_sha256": "a" * 64,
            "desktop_device_id": DEVICE_A, "expires_at": 4102444800,
            "path": "/v1",
        }

        class FakeClient:
            def run_batches(self, next_batch, apply_result, *, max_rounds):
                next_batch(None)
                apply_result({
                    "batch": clinical, "more": True,
                    "apply": {"records": 0, "conflicts": 0},
                    "confirmation_required": False,
                    "clinical_confirmation_required": False,
                    "clinical_safety_pause": False,
                    "exact_equal": False, "projection": None,
                    "live_count": None,
                })

            def close(self):
                pass

        original = app.DB_PATH
        app.DB_PATH = target
        try:
            sync_service.reset_runtime_state()
            with mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    return_value=invitation), mock.patch.object(
                    sync_service.transport, "pair_with_invitation",
                    return_value=(FakeClient(), {"ok": True})):
                result = sync_service.join(
                    "fresh-qr", device_name="Android",
                    platform_name="android")
            with app.db() as connection:
                path_count = connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
                remote_cursor = sync.peer_cursor(connection, DEVICE_A)
        finally:
            app.DB_PATH = original

        self.assertTrue(result["ok"])
        self.assertFalse(result["exact_equal"])
        self.assertFalse(result["clinical_confirmation_required"])
        self.assertTrue(result["clinical_safety_pause"])
        self.assertEqual(result["clinical_safety_device"], "this_device")
        self.assertIn("güvenlik beklemesi", result[
            "clinical_safety_message"])
        self.assertEqual(result["pending_clinical_confirmation_count"], 0)
        self.assertEqual(path_count, 0)
        self.assertEqual(remote_cursor, self._last_two_phases[0]["cursor"])

    def test_join_surfaces_remote_safety_pause_without_consent_cta(self):
        self.addCleanup(sync_service.reset_runtime_state)
        target = self._target_path()
        self._with_database(
            target, lambda connection: sync.initialize_sync(
                connection, DEVICE_B))
        invitation = {
            "v": 1, "scheme": "https", "host": "192.168.1.10",
            "port": 44321, "session_id": "unused",
            "pairing_secret": "unused", "cert_sha256": "a" * 64,
            "desktop_device_id": DEVICE_A, "expires_at": 4102444800,
            "path": "/v1",
        }
        empty = {
            "kind": sync.BATCH_KIND, "version": sync.BATCH_VERSION,
            "sender_device_id": DEVICE_A, "after_cursor": 0,
            "cursor": 0, "ack_cursor": 0, "has_more": False,
            "records": [],
        }

        class FakeClient:
            def run_batches(self, next_batch, apply_result, *, max_rounds):
                next_batch(None)
                apply_result({
                    "batch": empty, "more": False,
                    "apply": {"records": 0, "conflicts": 0},
                    "confirmation_required": False,
                    "clinical_confirmation_required": False,
                    "clinical_safety_pause": True,
                    "exact_equal": False, "projection": None,
                    "live_count": None,
                })

            def close(self):
                pass

        original = app.DB_PATH
        app.DB_PATH = target
        try:
            sync_service.reset_runtime_state()
            with mock.patch.object(
                    sync_service.transport, "parse_invitation",
                    return_value=invitation), mock.patch.object(
                    sync_service.transport, "pair_with_invitation",
                    return_value=(FakeClient(), {"ok": True})):
                result = sync_service.join(
                    "fresh-qr", device_name="Android",
                    platform_name="android")
        finally:
            app.DB_PATH = original

        self.assertTrue(result["ok"])
        self.assertFalse(result["exact_equal"])
        self.assertFalse(result["clinical_confirmation_required"])
        self.assertIsNone(result["clinical_confirmation_device"])
        self.assertTrue(result["clinical_safety_pause"])
        self.assertEqual(result["clinical_safety_device"], "computer")
        self.assertIn("Bilgisayardaki güvenlik beklemesi", result[
            "clinical_safety_message"])
        self.assertEqual(result["pending_clinical_confirmation_count"], 0)

    def _seed_v5_shared_head_and_private_ledgers(self):
        """Create the smallest source-bound v5 head plus private journals."""
        stamp = "2026-08-23 12:00:00"
        conv_public = "5" * 32
        user_public = "6" * 32
        assistant_public = "7" * 32
        request_id = "sync-v8-flow5-provider-prompt"
        pair_public = app._chat_turn_pair_public_id(request_id)
        path_public = app._schema_natural_public_id(
            "path", conv_public, 1, 1)
        with app.db() as connection:
            conv_id = connection.execute(
                "INSERT INTO conversations(public_id,mode,therapist,title,"
                "created,updated) VALUES(?,'terapi','young','V5 sync',?,?)",
                (conv_public, stamp, stamp),
            ).lastrowid
            user_id = connection.execute(
                "INSERT INTO messages(public_id,conv,role,content,created,"
                "turn_pair_public_id) VALUES(?,?,'user','Evet',?,?)",
                (user_public, conv_id, stamp, pair_public),
            ).lastrowid
            assistant_id = connection.execute(
                "INSERT INTO messages(public_id,conv,role,content,created,"
                "turn_pair_public_id) VALUES(?,?,'assistant',"
                "'Bu anı düşününce en çok hangi sahne beliriyor?',?,?)",
                (assistant_public, conv_id, stamp, pair_public),
            ).lastrowid
            job_id = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat',?,'done',?,?)",
                (conv_id, stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,created,updated) "
                "VALUES(?,?,?,?,?,'completed',?,?)",
                (request_id, job_id, conv_id, user_id, assistant_id,
                 stamp, stamp),
            )
            connection.execute(
                "UPDATE chat_requests SET schema_prompt_protocol=?,"
                "schema_prompt_plan_json=?,schema_prompt_result_json=? "
                "WHERE request_id=?",
                (
                    "schema_path_chat_v5",
                    '{"private":"PROMPT-PLAN-V5-NEVER-WIRE"}',
                    '{"private":"PROMPT-RESULT-V5-NEVER-WIRE"}',
                    request_id,
                ),
            )
            connection.execute(
                "INSERT INTO session_meta(conv,schema_mode_enabled,"
                "schema_mode_initialized,schema_clinical_sync_enabled,"
                "schema_clinical_sync_initialized,"
                "schema_clinical_sync_generation,updated) "
                "VALUES(?,1,1,1,1,1,?)", (conv_id, stamp))
            path_id = connection.execute(
                "INSERT INTO schema_paths(public_id,conv,therapist,"
                "path_sequence,clinical_generation,phase,status,"
                "flow_version,stage,step,focus_source_user_public_id,"
                "focus_source_assistant_public_id,method_node_id,revision,"
                "created,updated) VALUES(?,?,'young',1,1,'focus','active',"
                "5,'origin','origin_sequence',?,?,"
                "'young:method:imagery-rescripting',3,?,?)",
                (path_public, conv_id, user_public, assistant_public,
                 stamp, stamp),
            ).lastrowid
            step_public = app._schema_natural_public_id(
                "step", path_public, "origin_sequence")
            connection.execute(
                "INSERT INTO schema_path_steps(public_id,path,conv,stage,"
                "step,status,revision,source_user_message,"
                "source_assistant_message,payload_json,created,updated) "
                "VALUES(?,?,?,'origin','origin_sequence','active',1,?,?,"
                "?, ?,?)",
                (step_public, path_id, conv_id, user_id, assistant_id,
                 '{"private":"STEP-V5-NEVER-WIRE"}', stamp, stamp),
            )
            checkpoint_id = connection.execute(
                "INSERT INTO schema_path_checkpoints(public_id,path,conv,seq,"
                "stage,step,prompt_key,status,transition_kind,"
                "anchor_user_message,anchor_assistant_message,"
                "prompt_request_id,created,updated) VALUES(?,?,?,1,'origin',"
                "'origin_sequence','age','active','start',?,?,?, ?,?)",
                ("8" * 32, path_id, conv_id, user_id, assistant_id,
                 request_id, stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO schema_path_method_choices(public_id,path,conv,"
                "seq,method_node_id,status,authored_by,source_user_message,"
                "source_assistant_message,created,updated) VALUES(?,?,?,1,"
                "'young:method:imagery-rescripting','selected','server_rule',"
                "?,?,?,?)",
                ("9" * 32, path_id, conv_id, user_id, assistant_id,
                 stamp, stamp),
            )
            connection.execute(
                "INSERT INTO schema_variable_trials(public_id,path,conv,seq,"
                "category,status,hypothetical_anchor,evidence_quote,effect,"
                "prompt_request_id,question_user_message,"
                "question_assistant_message,response_user_message,"
                "response_assistant_message,created,updated) VALUES(?,?,?,1,"
                "'support','driver','VARIABLE-V5-NEVER-WIRE','exact','decrease',"
                "?,?,?,?,?,?,?)",
                ("a1" * 16, path_id, conv_id,
                 "sync-v8-flow5-private-variable", user_id, assistant_id,
                 user_id, assistant_id, stamp, stamp),
            )
            connection.execute(
                "INSERT INTO schema_origin_answers(public_id,path,conv,seq,"
                "field,status,text_value,age_value,source_user_message,"
                "source_assistant_message,prompt_request_id,created,updated) "
                "VALUES(?,?,?,1,'age','active','ORIGIN-V5-NEVER-WIRE',9,"
                "?,?,?,?,?)",
                ("b1" * 16, path_id, conv_id, user_id, assistant_id,
                 "sync-v8-flow5-private-origin", stamp, stamp),
            )
            technique_id = connection.execute(
                "INSERT INTO schema_v5_technique_sessions(public_id,path,"
                "conv,seq,method_node_id,status,current_stage,stage_index,"
                "source_user_message,source_assistant_message,created,updated) "
                "VALUES(?,?,?,1,'young:method:imagery-rescripting','completed',"
                "'TECHNIQUE-V5-NEVER-WIRE',1,?,?,?,?)",
                ("c1" * 16, path_id, conv_id, user_id, assistant_id,
                 stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO schema_v5_technique_turns(public_id,session,path,"
                "conv,seq,stage,status,source_user_message,"
                "source_assistant_message,prompt_request_id,created) "
                "VALUES(?,?,?,?,1,'TURN-V5-NEVER-WIRE','completed',?,?,?,?)",
                ("d1" * 16, technique_id, path_id, conv_id, user_id,
                 assistant_id, "sync-v8-flow5-private-turn", stamp),
            )
            connection.execute(
                "INSERT INTO schema_v5_integration_answers(public_id,path,"
                "conv,seq,field,status,text_value,source_user_message,"
                "source_assistant_message,prompt_request_id,created,updated) "
                "VALUES(?,?,?,1,'healthy_voice','active',"
                "'INTEGRATION-V5-NEVER-WIRE',?,?,?,?,?)",
                ("e1" * 16, path_id, conv_id, user_id, assistant_id,
                 "sync-v8-flow5-private-integration", stamp, stamp),
            )
            self.assertGreater(checkpoint_id, 0)
            sync.initialize_sync(connection, DEVICE_A)
        return {
            "conv": conv_id, "path": path_id,
            "path_public": path_public,
        }

    def test_v8_flow5_shared_head_roundtrips_and_private_ledgers_do_not_leak(self):
        self._seed_v5_shared_head_and_private_ledgers()
        ordinary, clinical = self._export_two_phases()
        private_tables = {
            "schema_variable_trials", "schema_origin_answers",
            "schema_path_checkpoints", "schema_path_method_choices",
            "schema_v5_technique_sessions", "schema_v5_technique_turns",
            "schema_v5_integration_answers", "chat_requests",
        }
        self.assertTrue(
            private_tables - {"chat_requests"}
            <= sync.DEVICE_LOCAL_CLINICAL_TABLES)
        self.assertFalse(private_tables.intersection(
            spec.table for spec in sync.RECORD_TYPES.values()))
        self.assertEqual(sync.BATCH_VERSION, 8)
        self.assertEqual(ordinary["version"], 8)
        self.assertEqual(clinical["version"], 8)
        path_record = next(
            row for row in clinical["records"]
            if row["record_type"] == "schema_path")
        step_record = next(
            row for row in clinical["records"]
            if row["record_type"] == "schema_step")
        self.assertEqual(path_record["payload"]["flow_version"], 5)
        self.assertEqual(
            (path_record["payload"]["stage"],
             path_record["payload"]["step"]),
            ("origin", "origin_sequence"))
        self.assertEqual(
            path_record["payload"]["method_node_id"],
            "young:method:imagery-rescripting")
        self.assertEqual(
            (step_record["payload"]["stage"],
             step_record["payload"]["step"]),
            ("origin", "origin_sequence"))

        wire = json.dumps([ordinary, clinical], ensure_ascii=False)
        for forbidden in (
                "PROMPT-PLAN-V5-NEVER-WIRE",
                "PROMPT-RESULT-V5-NEVER-WIRE",
                "STEP-V5-NEVER-WIRE", "VARIABLE-V5-NEVER-WIRE",
                "ORIGIN-V5-NEVER-WIRE", "TECHNIQUE-V5-NEVER-WIRE",
                "TURN-V5-NEVER-WIRE", "INTEGRATION-V5-NEVER-WIRE",
                "schema_prompt_plan_json", "schema_prompt_result_json",
                "schema_variable_trials", "schema_origin_answers",
                "schema_path_checkpoints", "schema_path_method_choices",
                "schema_v5_technique_sessions",
                "schema_v5_technique_turns",
                "schema_v5_integration_answers"):
            self.assertNotIn(forbidden, wire)

        target = self._target_path()

        def install(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            result = sync.apply_change_batch(connection, clinical, DEVICE_B)
            shared = tuple(connection.execute(
                "SELECT flow_version,stage,step,method_node_id "
                "FROM schema_paths").fetchone())
            step = tuple(connection.execute(
                "SELECT stage,step FROM schema_path_steps").fetchone())
            private_counts = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)
                ).fetchone()[0]
                for table in (
                    "schema_variable_trials", "schema_origin_answers",
                    "schema_path_checkpoints", "schema_path_method_choices",
                    "schema_v5_technique_sessions",
                    "schema_v5_technique_turns",
                    "schema_v5_integration_answers")
            }
            request_count = connection.execute(
                "SELECT COUNT(*) FROM chat_requests").fetchone()[0]
            return result, shared, step, private_counts, request_count

        result, shared, step, private_counts, request_count = \
            self._with_database(target, install)
        self.assertGreater(result["applied"], 0)
        self.assertEqual(shared, (
            5, "origin", "origin_sequence",
            "young:method:imagery-rescripting"))
        self.assertEqual(step, ("origin", "origin_sequence"))
        self.assertTrue(all(value == 0 for value in private_counts.values()))
        self.assertEqual(request_count, 0)

    def test_v8_rejects_v7_envelope_and_invalid_v5_graph_before_mutation(self):
        self._seed_v5_shared_head_and_private_ledgers()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install_preference(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")

        self._with_database(target, install_preference)
        invalid_batches = []
        legacy_envelope = copy.deepcopy(clinical)
        legacy_envelope["version"] = 7
        invalid_batches.append((legacy_envelope, "protocol v8 required"))

        old_step = copy.deepcopy(clinical)
        path_record = next(
            row for row in old_step["records"]
            if row["record_type"] == "schema_path")
        path_record["payload"]["stage"] = "depth"
        path_record["payload"]["step"] = "current_impact"
        invalid_batches.append((old_step, "stage, step or method"))

        legacy_method = copy.deepcopy(clinical)
        path_record = next(
            row for row in legacy_method["records"]
            if row["record_type"] == "schema_path")
        path_record["payload"]["method_node_id"] = \
            "young:method:limited-reparenting"
        invalid_batches.append((legacy_method, "stage, step or method"))

        cross_flow_step = copy.deepcopy(clinical)
        step_record = next(
            row for row in cross_flow_step["records"]
            if row["record_type"] == "schema_step")
        step_record["payload"]["stage"] = "listen"
        step_record["payload"]["step"] = "current_impact"
        step_record["public_id"] = app._schema_natural_public_id(
            "step", step_record["payload"]["path_public_id"],
            "current_impact")
        invalid_batches.append((cross_flow_step, "does not belong"))

        def reject_all(connection):
            baseline = {
                "cursor": sync.peer_cursor(connection, DEVICE_A),
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "paths": connection.execute(
                    "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
                "total_changes": connection.total_changes,
            }
            for invalid, message in invalid_batches:
                with self.assertRaisesRegex(sync.SyncError, message):
                    sync.apply_change_batch(connection, invalid, DEVICE_B)
                current = {
                    "cursor": sync.peer_cursor(connection, DEVICE_A),
                    "records": connection.execute(
                        "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                    "changes": connection.execute(
                        "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                    "seen": connection.execute(
                        "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                    "paths": connection.execute(
                        "SELECT COUNT(*) FROM schema_paths").fetchone()[0],
                    "total_changes": connection.total_changes,
                }
                self.assertEqual(current, baseline)

        self._with_database(target, reject_all)

    def test_v8_reexports_and_accepts_legacy_flow4_projection(self):
        self._seed_projection(stage="depth", step="origin_or_unknown")
        ordinary, clinical = self._export_two_phases()
        path_record = next(
            row for row in clinical["records"]
            if row["record_type"] == "schema_path")
        self.assertEqual(clinical["version"], 8)
        self.assertEqual(path_record["payload"]["flow_version"], 4)
        sync.validate_change_batch(clinical)

    def test_v8_late_cross_flow_child_preflight_is_atomic(self):
        self._seed_v5_shared_head_and_private_ledgers()
        ordinary, clinical = self._export_two_phases()
        late = copy.deepcopy(clinical)
        step_record = next(
            row for row in late["records"]
            if row["record_type"] == "schema_step")
        late["records"] = [step_record]
        late["after_cursor"] = clinical["cursor"]
        late["cursor"] = clinical["cursor"] + 1
        late["has_more"] = False
        step_record["payload"]["stage"] = "listen"
        step_record["payload"]["step"] = "current_impact"
        step_record["public_id"] = app._schema_natural_public_id(
            "step", step_record["payload"]["path_public_id"],
            "current_impact")
        step_record["revision"] = 1
        step_record["parent_origin_device_id"] = None
        step_record["parent_revision"] = None
        # Pure wire validation cannot see an already-installed parent; the
        # database preflight below must close that later-batch boundary.
        sync.validate_change_batch(late)

        target = self._target_path()

        def install_and_reject(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)
            baseline = {
                "cursor": sync.peer_cursor(connection, DEVICE_A),
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "conflicts": connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
                "steps": connection.execute(
                    "SELECT COUNT(*) FROM schema_path_steps").fetchone()[0],
                "total_changes": connection.total_changes,
            }
            with self.assertRaisesRegex(
                    sync.SyncError, "does not belong to its path flow"):
                sync.apply_change_batch(connection, late, DEVICE_B)
            after = {
                "cursor": sync.peer_cursor(connection, DEVICE_A),
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "conflicts": connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
                "steps": connection.execute(
                    "SELECT COUNT(*) FROM schema_path_steps").fetchone()[0],
                "total_changes": connection.total_changes,
            }
            return baseline, after

        baseline, after = self._with_database(target, install_and_reject)
        self.assertEqual(after, baseline)

    def _export_two_phases_after_seed(self):
        self._seed_projection()
        self._last_two_phases = self._export_two_phases()
        return self._last_two_phases
