import json
from unittest import mock

from support import DatabaseTestCase, app
import test_schema_clinical_sync as _clinical_tests

import sync_engine as sync
import sync_service


DEVICE_A = _clinical_tests.DEVICE_A
DEVICE_B = _clinical_tests.DEVICE_B


class SyncV6ReleaseAuditTests(DatabaseTestCase):
    """Adversarial release gates for the consented Schema v4 projection."""

    _target_path = _clinical_tests.SchemaClinicalSyncTests._target_path
    _with_database = _clinical_tests.SchemaClinicalSyncTests._with_database
    _seed_projection = _clinical_tests.SchemaClinicalSyncTests._seed_projection
    _export_two_phases = \
        _clinical_tests.SchemaClinicalSyncTests._export_two_phases

    def _installed_concurrent_path_conflict(self):
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
            connection.execute(
                "UPDATE schema_paths SET focus_label=?,revision=9,updated=? "
                "WHERE id=?",
                ("SOURCE-RELEASE-BRANCH", "2026-08-22 13:00:00",
                 ids["path"]),
            )
            sync.record_local_change(
                connection, "schema_path", ids["path"], DEVICE_A)
            source_edit = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])

        def branch_and_conflict(connection):
            path_id = connection.execute(
                "SELECT id FROM schema_paths WHERE public_id=?",
                (ids["path_public"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE schema_paths SET focus_label=?,revision=9,updated=? "
                "WHERE id=?",
                ("TARGET-RELEASE-BRANCH", "2026-08-22 13:01:00",
                 path_id),
            )
            sync.record_local_change(
                connection, "schema_path", int(path_id), DEVICE_B)
            merged = sync.apply_change_batch(
                connection, source_edit, DEVICE_B)
            conflict_id = connection.execute(
                "SELECT id FROM sync_conflicts WHERE status='open' "
                "AND record_type='schema_path'"
            ).fetchone()[0]
            return int(conflict_id), merged

        conflict_id, merged = self._with_database(
            target, branch_and_conflict)
        self.assertEqual(merged["conflicts"], 1)
        return target, ids, conflict_id, clinical

    def _resolve_target_conflict(self, target, conflict_id, resolution):
        original = app.DB_PATH
        app.DB_PATH = target
        try:
            with mock.patch.object(
                    sync_service, "_device_id", return_value=DEVICE_B), \
                    mock.patch.object(
                        sync_service, "_snapshot_callback", None):
                return sync_service.resolve_conflict(
                    conflict_id, resolution)
        finally:
            app.DB_PATH = original

    def _target_path_state(self, target, public_id):
        def read(connection):
            row = connection.execute(
                "SELECT focus_label FROM schema_paths WHERE public_id=?",
                (public_id,),
            ).fetchone()
            head = connection.execute(
                "SELECT revision,origin_device_id,deleted_at,payload_hash "
                "FROM sync_records WHERE record_type='schema_path' "
                "AND public_id=?",
                (public_id,),
            ).fetchone()
            conflict = connection.execute(
                "SELECT status FROM sync_conflicts WHERE "
                "record_type='schema_path' AND public_id=?",
                (public_id,),
            ).fetchone()
            return (
                row[0] if row else None,
                tuple(head) if head else None,
                conflict[0] if conflict else None,
            )

        return self._with_database(target, read)

    def test_remote_conflict_resolution_fails_closed_after_consent_off(self):
        target, ids, conflict_id, _ = \
            self._installed_concurrent_path_conflict()

        def withdraw_without_refresh(connection):
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_enabled=0,"
                "schema_clinical_sync_initialized=0 WHERE conv=("
                "SELECT id FROM conversations WHERE public_id=?)",
                ("c" * 32,),
            )

        self._with_database(target, withdraw_without_refresh)
        with self.assertRaises(sync_service.SyncServiceError):
            self._resolve_target_conflict(target, conflict_id, "remote")
        after = self._target_path_state(target, ids["path_public"])
        self.assertEqual(after[0], "TARGET-RELEASE-BRANCH")
        self.assertIsNotNone(after[1][2])
        self.assertIsNone(after[2])

        def no_remote_payload(connection):
            change_count = connection.execute(
                "SELECT COUNT(*) FROM sync_changes WHERE "
                "COALESCE(payload_json,'') LIKE '%SOURCE-RELEASE-BRANCH%'"
            ).fetchone()[0]
            conflict_count = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "incoming_json LIKE '%SOURCE-RELEASE-BRANCH%'"
            ).fetchone()[0]
            seen_count = connection.execute(
                "SELECT COUNT(*) FROM sync_seen_versions WHERE "
                "record_type='schema_path' AND public_id=? "
                "AND origin_device_id=? AND revision=9",
                (ids["path_public"], DEVICE_A),
            ).fetchone()[0]
            return change_count, conflict_count, seen_count

        self.assertEqual(
            self._with_database(target, no_remote_payload), (0, 0, 0))

    def test_remote_conflict_resolution_fails_closed_during_safety_hold(self):
        target, ids, conflict_id, _ = \
            self._installed_concurrent_path_conflict()

        self._with_database(
            target,
            lambda connection: connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE public_id=?",
                ("c" * 32,),
            ),
        )
        with self.assertRaises(sync_service.SyncServiceError):
            self._resolve_target_conflict(target, conflict_id, "remote")
        after = self._target_path_state(target, ids["path_public"])
        self.assertEqual(after[0], "TARGET-RELEASE-BRANCH")
        self.assertIsNone(after[2])

        def no_remote_payload(connection):
            change_count = connection.execute(
                "SELECT COUNT(*) FROM sync_changes WHERE "
                "COALESCE(payload_json,'') LIKE '%SOURCE-RELEASE-BRANCH%'"
            ).fetchone()[0]
            conflict_count = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "incoming_json LIKE '%SOURCE-RELEASE-BRANCH%'"
            ).fetchone()[0]
            seen_count = connection.execute(
                "SELECT COUNT(*) FROM sync_seen_versions WHERE "
                "record_type='schema_path' AND public_id=? "
                "AND origin_device_id=? AND revision=9",
                (ids["path_public"], DEVICE_A),
            ).fetchone()[0]
            return change_count, conflict_count, seen_count

        self.assertEqual(
            self._with_database(target, no_remote_payload), (0, 0, 0))

    def _installed_active_path_collision(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()
        target_path_public = app._schema_natural_public_id(
            "path", "c" * 32, 1, 2)

        def create_other_active_path(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            conv_id = connection.execute(
                "SELECT id FROM conversations WHERE public_id=?",
                ("c" * 32,),
            ).fetchone()[0]
            path_id = connection.execute(
                "INSERT INTO schema_paths("
                "public_id,conv,therapist,path_sequence,clinical_generation,"
                "phase,status,flow_version,stage,step,focus_schema_key,"
                "focus_mode_key,focus_label,focus_evidence,revision,"
                "created,updated) VALUES(?,?,'young',2,1,'focus','active',4,"
                "'listen','candidate_review','local_schema','local_mode',"
                "'TARGET-ACTIVE-PATH','TARGET-ACTIVE-EVIDENCE',1,?,?)",
                (
                    target_path_public, conv_id,
                    "2026-08-22 13:20:00", "2026-08-22 13:20:00",
                ),
            ).lastrowid
            sync.record_local_change(
                connection, "schema_path", int(path_id), DEVICE_B)
            path_only = json.loads(json.dumps(clinical))
            path_only["records"] = [
                record for record in path_only["records"]
                if record["record_type"] == "schema_path"
            ]
            merged = sync.apply_change_batch(
                connection, path_only, DEVICE_B)
            conflict_id = connection.execute(
                "SELECT id FROM sync_conflicts WHERE status='open' "
                "AND reason='concurrent_schema_path'"
            ).fetchone()[0]
            return int(conflict_id), merged, path_only

        conflict_id, merged, path_only = self._with_database(
            target, create_other_active_path)
        self.assertEqual(merged["conflicts"], 1)
        return target, ids, conflict_id, target_path_public, path_only

    def _schema_path_state(self, database_path):
        def read(connection):
            return (
                [tuple(row) for row in connection.execute(
                    "SELECT public_id,status FROM schema_paths "
                    "ORDER BY public_id").fetchall()],
                int(connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts "
                    "WHERE status='open'").fetchone()[0]),
            )

        if database_path == app.DB_PATH:
            with app.db() as connection:
                return read(connection)
        return self._with_database(database_path, read)

    def _drain_target_with_restart_after_stopped_path(
            self, target, *, expected_loser_public_id):
        """Apply one-record QR chunks and replay from cursor zero once.

        Resetting the sender cursor immediately after the losing path's
        stopped descendant models a crash before the chosen live branch is
        delivered.  Every batch is applied in a fresh DB context, like a
        process-death/retry boundary.
        """
        cursor = 0
        restarted = False
        stopped_seen = False
        original_active_loser_batch = None
        summaries = []
        final_cursor = 0
        iterations = 0
        while True:
            iterations += 1
            self.assertLess(iterations, 500, "one-row replay did not drain")

            def export(connection):
                return sync.export_change_batch(
                    connection, DEVICE_B, after_cursor=cursor, limit=1)

            batch = self._with_database(target, export)
            for record in batch["records"]:
                payload = record.get("payload") or {}
                if (record["record_type"] == "schema_path"
                        and record["public_id"] == expected_loser_public_id
                        and payload.get("status") in ("active", "paused")
                        and original_active_loser_batch is None):
                    original_active_loser_batch = json.loads(
                        json.dumps(batch))
            with app.db() as connection:
                summaries.append(sync.apply_change_batch(
                    connection, batch, DEVICE_A))
            final_cursor = int(batch["cursor"])
            just_stopped = any(
                record["record_type"] == "schema_path"
                and record["public_id"] == expected_loser_public_id
                and (record.get("payload") or {}).get("status") == "stopped"
                for record in batch["records"])
            if just_stopped and not restarted:
                stopped_seen = True
                restarted = True
                cursor = 0
                continue
            cursor = final_cursor
            if not batch["has_more"]:
                break

        self.assertTrue(stopped_seen, "losing-path stop was not transferred")
        self.assertTrue(restarted, "cursor restart boundary was not exercised")
        self.assertIsNotNone(
            original_active_loser_batch,
            "original active losing branch was not observed")

        def exhausted(connection):
            return sync.export_change_batch(
                connection, DEVICE_B, after_cursor=final_cursor, limit=1)

        empty = self._with_database(target, exhausted)
        self.assertEqual(empty["records"], [])
        self.assertFalse(empty["has_more"])
        with app.db() as connection:
            second = sync.apply_change_batch(connection, empty, DEVICE_A)
        self.assertEqual(second["applied"], 0)
        self.assertEqual(second["conflicts"], 0)
        self.assertEqual(second["deferred"], 0)
        return original_active_loser_batch, summaries

    def test_active_path_collision_remote_choice_converges(self):
        target, ids, conflict_id, _, _ = \
            self._installed_active_path_collision()
        resolved = self._resolve_target_conflict(
            target, conflict_id, "remote")
        self.assertTrue(resolved["ok"])

        def target_state(connection):
            paths = [tuple(row) for row in connection.execute(
                "SELECT public_id,status FROM schema_paths ORDER BY public_id"
            ).fetchall()]
            open_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
            ).fetchone()[0]
            return paths, open_conflicts

        target_paths, target_conflicts = self._with_database(
            target, target_state)
        self.assertEqual(target_conflicts, 0)
        self.assertEqual(
            [public_id for public_id, status in target_paths
             if status in ("active", "paused")],
            [ids["path_public"]],
        )

        cursor = 0
        while True:
            def export(connection):
                return sync.export_change_batch(
                    connection, DEVICE_B, after_cursor=cursor)

            batch = self._with_database(target, export)
            with app.db() as connection:
                sync.apply_change_batch(connection, batch, DEVICE_A)
            cursor = batch["cursor"]
            if not batch["has_more"]:
                break

        with app.db() as connection:
            source_paths = [tuple(row) for row in connection.execute(
                "SELECT public_id,status FROM schema_paths ORDER BY public_id"
            ).fetchall()]
            source_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
            ).fetchone()[0]
        self.assertEqual(source_conflicts, 0)
        self.assertEqual(source_paths, target_paths)

    def test_active_path_collision_local_choice_converges(self):
        target, ids, conflict_id, target_path_public, _ = \
            self._installed_active_path_collision()
        resolved = self._resolve_target_conflict(
            target, conflict_id, "local")
        self.assertTrue(resolved["ok"])

        def target_state(connection):
            paths = [tuple(row) for row in connection.execute(
                "SELECT public_id,status FROM schema_paths ORDER BY public_id"
            ).fetchall()]
            open_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
            ).fetchone()[0]
            return paths, open_conflicts

        target_paths, target_conflicts = self._with_database(
            target, target_state)
        self.assertEqual(target_conflicts, 0)
        self.assertEqual(
            [public_id for public_id, status in target_paths
             if status in ("active", "paused")],
            [target_path_public],
        )
        self.assertIn((ids["path_public"], "stopped"), target_paths)

        cursor = 0
        while True:
            def export(connection):
                return sync.export_change_batch(
                    connection, DEVICE_B, after_cursor=cursor)

            batch = self._with_database(target, export)
            with app.db() as connection:
                sync.apply_change_batch(connection, batch, DEVICE_A)
            cursor = batch["cursor"]
            if not batch["has_more"]:
                break

        with app.db() as connection:
            source_paths = [tuple(row) for row in connection.execute(
                "SELECT public_id,status FROM schema_paths ORDER BY public_id"
            ).fetchall()]
            source_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
            ).fetchone()[0]
        self.assertEqual(source_conflicts, 0)
        self.assertEqual(source_paths, target_paths)

    def test_remote_path_choice_limit_one_crash_replay_never_resurrects_loser(
            self):
        target, ids, conflict_id, target_path_public, source_active = \
            self._installed_active_path_collision()
        self.assertTrue(self._resolve_target_conflict(
            target, conflict_id, "remote")["ok"])

        old_target_active, summaries = \
            self._drain_target_with_restart_after_stopped_path(
                target, expected_loser_public_id=target_path_public)
        target_state = self._schema_path_state(target)
        source_state = self._schema_path_state(app.DB_PATH)
        self.assertEqual(source_state, target_state)
        self.assertEqual(source_state[1], 0)
        self.assertEqual(
            [public_id for public_id, status in source_state[0]
             if status in ("active", "paused")],
            [ids["path_public"]],
        )
        self.assertTrue(any(summary["ignored"] for summary in summaries))

        # Both peers may receive an old QR packet after the explicit choice.
        # Neither the original source branch nor the rejected target branch
        # may reopen a manual conflict or revive the stopped loser.
        with app.db() as connection:
            replayed = sync.apply_change_batch(
                connection, old_target_active, DEVICE_A)
        self.assertEqual(replayed["conflicts"], 0)
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, source_active, DEVICE_B),
        )
        self.assertEqual(self._schema_path_state(app.DB_PATH), source_state)
        self.assertEqual(self._schema_path_state(target), target_state)

    def test_local_path_choice_limit_one_crash_replay_never_resurrects_loser(
            self):
        target, ids, conflict_id, target_path_public, source_active = \
            self._installed_active_path_collision()
        self.assertTrue(self._resolve_target_conflict(
            target, conflict_id, "local")["ok"])

        old_target_active, summaries = \
            self._drain_target_with_restart_after_stopped_path(
                target, expected_loser_public_id=ids["path_public"])
        target_state = self._schema_path_state(target)
        source_state = self._schema_path_state(app.DB_PATH)
        self.assertEqual(source_state, target_state)
        self.assertEqual(source_state[1], 0)
        self.assertEqual(
            [public_id for public_id, status in source_state[0]
             if status in ("active", "paused")],
            [target_path_public],
        )
        self.assertTrue(any(summary["ignored"] for summary in summaries))

        with app.db() as connection:
            replayed = sync.apply_change_batch(
                connection, old_target_active, DEVICE_A)
        self.assertEqual(replayed["conflicts"], 0)
        self._with_database(
            target,
            lambda connection: sync.apply_change_batch(
                connection, source_active, DEVICE_B),
        )
        self.assertEqual(self._schema_path_state(app.DB_PATH), source_state)
        self.assertEqual(self._schema_path_state(target), target_state)

    def test_withdrawal_scrubs_different_id_path_conflict_payload(self):
        target, ids, _, target_path_public, _ = \
            self._installed_active_path_collision()

        def withdraw_and_refresh(connection):
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_enabled=0,"
                "schema_clinical_sync_initialized=0")
            sync.refresh_local_changes(connection, DEVICE_B)
            retained_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "incoming_json LIKE '%Kullanıcının exact sözü%'"
            ).fetchone()[0]
            retained_changes = connection.execute(
                "SELECT COUNT(*) FROM sync_changes WHERE "
                "COALESCE(payload_json,'') LIKE '%Kullanıcının exact sözü%'"
            ).fetchone()[0]
            retained_seen = connection.execute(
                "SELECT COUNT(*) FROM sync_seen_versions WHERE "
                "record_type='schema_path' AND public_id=?",
                (ids["path_public"],),
            ).fetchone()[0]
            incoming_physical = connection.execute(
                "SELECT COUNT(*) FROM schema_paths WHERE public_id=?",
                (ids["path_public"],),
            ).fetchone()[0]
            local_physical = connection.execute(
                "SELECT focus_label FROM schema_paths WHERE public_id=?",
                (target_path_public,),
            ).fetchone()[0]
            return (
                retained_conflicts, retained_changes, retained_seen,
                incoming_physical, local_physical,
            )

        retained = self._with_database(target, withdraw_and_refresh)
        self.assertEqual(retained[:4], (0, 0, 0, 0))
        self.assertEqual(retained[4], "TARGET-ACTIVE-PATH")

    def _ordinary_policy_change_after_collision(self, *, safety_hold=False):
        target, ids, _, _, source_active = \
            self._installed_active_path_collision()
        incoming_path_revision = next(
            int(record["revision"])
            for record in source_active["records"]
            if record["record_type"] == "schema_path"
            and record["public_id"] == ids["path_public"])

        with app.db() as connection:
            if safety_hold:
                local_id = ids["conv"]
                connection.execute(
                    "UPDATE conversations SET safety_hold=1,updated=? "
                    "WHERE id=?", ("2026-08-22 14:00:00", local_id))
                sync.record_local_change(
                    connection, "conversation", local_id, DEVICE_A)
            else:
                local_id = ids["conv"]
                connection.execute(
                    "UPDATE session_meta SET "
                    "schema_clinical_sync_enabled=0,"
                    "schema_clinical_sync_initialized=0,updated=? "
                    "WHERE conv=?",
                    ("2026-08-22 14:00:00", ids["conv"]),
                )
                sync.record_local_change(
                    connection, "session_meta", local_id, DEVICE_A)
            policy_batch = sync.export_change_batch(
                connection, DEVICE_A,
                after_cursor=int(source_active["cursor"]))
        self.assertTrue(policy_batch["records"])
        self.assertTrue(all(
            record["record_type"] not in sync._SCHEMA_CLINICAL_RECORD_TYPES
            or record["deleted_at"] is not None
            for record in policy_batch["records"]), policy_batch["records"])

        def apply_and_inspect(connection):
            result = sync.apply_change_batch(
                connection, policy_batch, DEVICE_B)
            retained_conflicts = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open' "
                "AND record_type IN ({})".format(
                    ",".join("?" for _ in sync._SCHEMA_CLINICAL_RECORD_TYPES)),
                tuple(sync._SCHEMA_CLINICAL_RECORD_TYPES),
            ).fetchone()[0]
            private_payloads = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "incoming_json LIKE '%Kullanıcının exact sözü%'"
            ).fetchone()[0]
            retained_changes = connection.execute(
                "SELECT COUNT(*) FROM sync_changes WHERE "
                "COALESCE(payload_json,'') "
                "LIKE '%Kullanıcının exact sözü%'"
            ).fetchone()[0]
            retained_seen = connection.execute(
                "SELECT COUNT(*) FROM sync_seen_versions WHERE "
                "record_type='schema_path' AND public_id=? "
                "AND origin_device_id=? AND revision=?",
                (ids["path_public"], DEVICE_A, incoming_path_revision),
            ).fetchone()[0]
            return (
                result, int(retained_conflicts), int(private_payloads),
                int(retained_changes), int(retained_seen),
            )

        return self._with_database(target, apply_and_inspect)

    def test_incoming_withdrawal_atomically_scrubs_waiting_clinical_conflict(
            self):
        _, retained, private_payloads, changes, seen = \
            self._ordinary_policy_change_after_collision(safety_hold=False)
        # A withdrawal keeps the content-free seen identity for the retired
        # live version alongside its canonical tombstone.  That opaque marker
        # prevents an older peer from reviving the branch.
        self.assertEqual((retained, private_payloads, changes), (0, 0, 0))
        self.assertEqual(seen, 1)

    def test_incoming_safety_hold_atomically_scrubs_waiting_clinical_conflict(
            self):
        _, retained, private_payloads, changes, seen = \
            self._ordinary_policy_change_after_collision(safety_hold=True)
        self.assertEqual(
            (retained, private_payloads, changes, seen), (0, 0, 0, 0))

    def test_deferred_clinical_rows_never_bypass_exact_pair_or_consent(self):
        self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()
        without_messages = json.loads(json.dumps(ordinary))
        without_messages["records"] = [
            record for record in without_messages["records"]
            if record["record_type"] != "message"
        ]

        def attempt(connection):
            sync.apply_change_batch(connection, without_messages, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            before_reject = {
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "conflicts": connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            }
            with self.assertRaisesRegex(
                    sync.SyncError, "source dependency is unavailable"):
                sync.apply_change_batch(connection, clinical, DEVICE_B)
            counts_before_withdrawal = {
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
            after_reject = {
                "records": connection.execute(
                    "SELECT COUNT(*) FROM sync_records").fetchone()[0],
                "changes": connection.execute(
                    "SELECT COUNT(*) FROM sync_changes").fetchone()[0],
                "seen": connection.execute(
                    "SELECT COUNT(*) FROM sync_seen_versions").fetchone()[0],
                "conflicts": connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts").fetchone()[0],
            }
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_enabled=0,"
                "schema_clinical_sync_initialized=0")
            sync.refresh_local_changes(connection, DEVICE_B)
            counts_after_withdrawal = {
                table: connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)
                ).fetchone()[0]
                for table in counts_before_withdrawal
            }
            return (
                before_reject, after_reject,
                counts_before_withdrawal, counts_after_withdrawal,
            )

        before_reject, after_reject, clinical_before, clinical_after = \
            self._with_database(target, attempt)
        self.assertEqual(after_reject, before_reject)
        self.assertTrue(all(
            value == 0 for value in clinical_before.values()), clinical_before)
        self.assertTrue(all(
            value == 0 for value in clinical_after.values()), clinical_after)

    def _stage_legacy_clinical_conflict(
            self, connection, *, reason, consent_enabled, safety_hold):
        conv_public = "r" * 32
        path_public = app._schema_natural_public_id(
            "path", conv_public, 1, 1)
        stamp = "2026-08-22 13:15:00"
        incoming = {
            "record_type": "schema_path",
            "public_id": path_public,
            "revision": 1,
            "origin_device_id": DEVICE_A,
            "parent_origin_device_id": None,
            "parent_revision": None,
            "updated_at": stamp,
            "deleted_at": None,
            "payload": {
                "conversation_public_id": conv_public,
                "therapist": "young",
                "path_sequence": 1,
                "phase": "focus",
                "status": "active",
                "clinical_generation": 1,
                "flow_version": 4,
                "stage": "listen",
                "step": "candidate_review",
                "focus_evidence": "LEGACY-CLINICAL-PRIVATE-SENTINEL",
                "revision": 1,
                "created": stamp,
                "updated": stamp,
            },
        }
        conv_id = connection.execute(
            "INSERT INTO conversations(public_id,mode,therapist,title,"
            "safety_hold,created,updated) VALUES(?,'terapi','young',"
            "'Release audit',?,?,?)",
            (conv_public, 1 if safety_hold else 0, stamp, stamp),
        ).lastrowid
        connection.execute(
            "INSERT INTO session_meta("
            "conv,schema_clinical_sync_enabled,"
            "schema_clinical_sync_initialized,"
            "schema_clinical_sync_generation,updated) "
            "VALUES(?,?,?,?,?)",
            (
                conv_id, 1 if consent_enabled else 0,
                1 if consent_enabled else 0, 1, stamp,
            ),
        )
        sync.initialize_sync(connection, DEVICE_B, bootstrap=False)
        connection.execute(
            "INSERT INTO sync_conflicts("
            "record_type,public_id,reason,local_json,incoming_json,"
            "incoming_event_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                "schema_path", path_public, reason, "{}",
                json.dumps(incoming, sort_keys=True),
                "legacy-release-audit-event-{}".format(reason), stamp,
            ),
        )
        return path_public

    def test_deferred_clinical_rows_never_replay_during_safety_hold(self):
        with app.db() as connection:
            path_public = self._stage_legacy_clinical_conflict(
                connection, reason="missing_dependency",
                consent_enabled=True, safety_hold=True)
            result = sync.initialize_sync(connection, DEVICE_B)
            path_count = connection.execute(
                "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
            retained = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "incoming_json LIKE '%LEGACY-CLINICAL-PRIVATE-SENTINEL%'"
            ).fetchone()[0]
            head = connection.execute(
                "SELECT COUNT(*) FROM sync_records WHERE "
                "record_type='schema_path' AND public_id=? "
                "AND deleted_at IS NULL",
                (path_public,),
            ).fetchone()[0]
        self.assertEqual(result["deferred_applied"], 0)
        self.assertEqual((path_count, head, retained), (0, 0, 0))

    def test_legacy_auto_merge_cannot_install_clinical_content_without_consent(self):
        with app.db() as connection:
            self._stage_legacy_clinical_conflict(
                connection, reason="concurrent_clinical_edit",
                consent_enabled=False, safety_hold=False)
            result = sync.initialize_sync(connection, DEVICE_B)
            path_count = connection.execute(
                "SELECT COUNT(*) FROM schema_paths").fetchone()[0]
            retained = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE "
                "incoming_json LIKE '%LEGACY-CLINICAL-PRIVATE-SENTINEL%'"
            ).fetchone()[0]
        self.assertEqual(result["auto_merged"], 0)
        self.assertEqual(path_count, 0)
        self.assertEqual(retained, 0)

    def test_payload_free_tombstones_remain_applicable_while_held(self):
        ids = self._seed_projection()
        ordinary, clinical = self._export_two_phases()
        target = self._target_path()

        def install_and_hold(connection):
            sync.apply_change_batch(connection, ordinary, DEVICE_B)
            connection.execute(
                "UPDATE session_meta SET "
                "schema_clinical_sync_initialized=1")
            sync.apply_change_batch(connection, clinical, DEVICE_B)
            connection.execute(
                "UPDATE conversations SET safety_hold=1")

        self._with_database(target, install_and_hold)
        with app.db() as connection:
            connection.execute(
                "UPDATE session_meta SET schema_clinical_sync_enabled=0,"
                "schema_clinical_sync_initialized=0 WHERE conv=?",
                (ids["conv"],),
            )
            sync.refresh_local_changes(connection, DEVICE_A)
            withdrawal = sync.export_change_batch(
                connection, DEVICE_A, after_cursor=clinical["cursor"])
        clinical_tombstones = [
            record for record in withdrawal["records"]
            if record["record_type"] in sync._SCHEMA_CLINICAL_RECORD_TYPES]
        self.assertTrue(clinical_tombstones)
        self.assertTrue(all(
            record["payload"] is None and record["deleted_at"] is not None
            for record in clinical_tombstones))

        def apply_tombstones(connection):
            result = sync.apply_change_batch(
                connection, withdrawal, DEVICE_B)
            remaining = sum(
                connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]
                for table in (
                    "schema_paths", "schema_candidate_queue",
                    "schema_focus_checks", "schema_path_steps",
                    "schema_origin", "schema_growth",
                    "healthy_adult_marks", "schema_transfer_records",
                    "message_meta_events")
            )
            return result, remaining

        result, remaining = self._with_database(target, apply_tombstones)
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
