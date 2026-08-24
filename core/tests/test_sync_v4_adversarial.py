"""Adversarial release gates for protocol-v4 equality confirmation.

These tests deliberately avoid user content.  They exercise only protocol
state, cursors and opaque projection proofs.
"""

from unittest import mock
import copy

from support import DatabaseTestCase, app

import sync_engine
import sync_service


LOCAL_DEVICE = "a" * 32
REMOTE_DEVICE = "b" * 32


def _invitation():
    return {
        "v": 1,
        "scheme": "https",
        "host": "192.168.1.10",
        "port": 44321,
        "session_id": "unused",
        "pairing_secret": "unused",
        "cert_sha256": "c" * 64,
        "desktop_device_id": REMOTE_DEVICE,
        "expires_at": 4102444800,
        "path": "/v1",
    }


def _empty_host_batch(ack_cursor=0):
    return {
        "kind": sync_engine.BATCH_KIND,
        "version": sync_engine.BATCH_VERSION,
        "sender_device_id": REMOTE_DEVICE,
        "after_cursor": 0,
        "cursor": 0,
        "ack_cursor": ack_cursor,
        "has_more": False,
        "records": [],
    }


class SyncV4AdversarialTests(DatabaseTestCase):

    def _join_with(self, client):
        with mock.patch.object(
                sync_service.transport, "parse_invitation",
                return_value=_invitation()), mock.patch.object(
                sync_service.transport, "pair_with_invitation",
                return_value=(client, {"ok": True})), mock.patch.object(
                sync_service, "_device_id", return_value=LOCAL_DEVICE):
            return sync_service.join(
                "scanned-code", device_name="Test device",
                platform_name="android")

    def test_client_does_not_accept_exact_without_sending_confirmation(self):
        self.conversation(title="Opaque row")

        class PrematureExactClient:
            def run_batches(self, next_batch, apply_result, *, max_rounds):
                items, done = next_batch(None)
                assert done is True
                assert len(items) == 1
                outbound = items[0]
                with app.db() as connection:
                    claimed_projection = sync_engine.projection_summary(
                        connection)
                apply_result({
                    "batch": _empty_host_batch(outbound["cursor"]),
                    "more": False,
                    "apply": {
                        "records": len(outbound["records"]),
                        "conflicts": 0,
                        "auto_merged": 0,
                    },
                    # A malformed/old/hostile peer must not be able to turn a
                    # bare boolean into the UI's "same on both devices" claim.
                    "confirmation_required": False,
                    "exact_equal": True,
                    "projection": claimed_projection,
                    "live_count": 1,
                })

            def close(self):
                pass

        try:
            result = self._join_with(PrematureExactClient())
        except sync_service.SyncServiceError:
            return
        self.assertFalse(result["exact_equal"])
        self.assertFalse(result["summary"]["exact_equal"])

    def test_client_rechecks_local_projection_after_confirmation(self):
        conversation_id = self.conversation(title="Before proof")

        class StaleProofClient:
            def run_batches(inner_self, next_batch, apply_result, *, max_rounds):
                first_items, first_done = next_batch(None)
                assert first_done is True
                first_outbound = first_items[0]
                first_result = {
                    "batch": _empty_host_batch(first_outbound["cursor"]),
                    "more": True,
                    "apply": {
                        "records": len(first_outbound["records"]),
                        "conflicts": 0,
                        "auto_merged": 0,
                    },
                    "confirmation_required": True,
                    "exact_equal": False,
                    "live_count": None,
                }
                apply_result(first_result)

                final_items, final_done = next_batch(first_result)
                assert final_done is True
                assert any(
                    item.get("kind") == sync_service.PROJECTION_CONFIRM_KIND
                    for item in final_items)
                stale_projection = next(
                    item["projection"] for item in final_items
                    if item.get("kind") == sync_service.PROJECTION_CONFIRM_KIND)

                # The proof now in flight describes the old head.  Model a
                # local/background write which lands before the host's final
                # response.  It is enrolled so even the shadow projection has
                # changed; accepting the host's stale boolean is indefensible.
                with app.db() as connection:
                    connection.execute(
                        "UPDATE conversations SET title=?,updated=? WHERE id=?",
                        ("After proof", "2026-08-17 21:00", conversation_id),
                    )
                    sync_engine.record_local_change(
                        connection, "conversation", conversation_id,
                        LOCAL_DEVICE,
                        updated_at="2026-08-17T21:00:00+00:00")

                apply_result({
                    "batch": _empty_host_batch(final_items[0]["cursor"]),
                    "more": False,
                    "apply": {
                        "records": 0,
                        "conflicts": 0,
                        "auto_merged": 0,
                    },
                    "confirmation_required": False,
                    "exact_equal": True,
                    "projection": stale_projection,
                    "live_count": 1,
                })

            def close(self):
                pass

        try:
            result = self._join_with(StaleProofClient())
        except sync_service.SyncServiceError:
            return
        self.assertFalse(result["exact_equal"])
        self.assertFalse(result["summary"]["exact_equal"])

    def test_host_rejects_noncanonical_confirmation_shapes(self):
        self.addCleanup(sync_service.reset_runtime_state)
        sync_service.reset_runtime_state()
        self.conversation(title="Opaque row")
        sync_service._prepare_database(refresh=True)
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE,
            fingerprint="f" * 64,
            name="Peer",
            platform="android",
            address="192.168.1.20",
        )
        empty = _empty_host_batch()
        with app.db() as connection:
            proof = sync_engine.projection_summary(connection)

        hostile = [
            {**proof, "pending": True},
            {**proof, "live_count": True},
            {**proof, "digest": proof["digest"].upper()},
            {**proof, "type_counts": {"unknown": proof["live_count"]}},
            {**proof, "unexpected": 0},
        ]
        for malformed in hostile:
            with self.subTest(shape=sorted(malformed)):
                confirmation = {
                    "kind": sync_service.PROJECTION_CONFIRM_KIND,
                    "sender_device_id": REMOTE_DEVICE,
                    "projection": malformed,
                }
                with self.assertRaises(sync_service.SyncServiceError):
                    sync_service._host_on_batch([empty, confirmation], peer)

    def test_unoffered_ack_cannot_permanently_skip_host_records(self):
        self.addCleanup(sync_service.reset_runtime_state)
        sync_service.reset_runtime_state()
        self.conversation(title="Opaque row")
        sync_service._prepare_database(refresh=True)
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE,
            fingerprint="f" * 64,
            name="Peer",
            platform="android",
            address="192.168.1.20",
        )
        with app.db() as connection:
            high_water = sync_engine.local_cursor_high_water(connection)
        self.assertGreater(high_water, 0)

        # The peer has not received any host batch in this session.  Claiming
        # the current high-water mark must either be rejected or remain
        # provisional; it must never suppress those records on a fresh QR.
        dishonest = _empty_host_batch(high_water)
        try:
            sync_service._host_on_batch([dishonest], peer)
        except sync_service.SyncServiceError:
            return

        sync_service.reset_runtime_state()
        retry = sync_service._host_on_batch([_empty_host_batch(0)], peer)
        self.assertGreater(len(retry["batch"]["records"]), 0)

    def test_offered_unconfirmed_cursor_resumes_but_stays_provisional(self):
        self.addCleanup(sync_service.reset_runtime_state)
        sync_service.reset_runtime_state()
        self.conversation(title="Opaque row")
        sync_service._prepare_database(refresh=True)
        peer = sync_service.transport.PeerIdentity(
            device_id=REMOTE_DEVICE,
            fingerprint="f" * 64,
            name="Peer",
            platform="android",
            address="192.168.1.20",
        )

        first = sync_service._host_on_batch([_empty_host_batch(0)], peer)
        offered = first["batch"]["cursor"]
        self.assertGreater(offered, 0)
        with app.db() as connection:
            self.assertEqual(
                sync_engine.peer_ack_cursor(connection, REMOTE_DEVICE), 0)
            self.assertGreaterEqual(
                sync_engine.peer_offered_cursor(connection, REMOTE_DEVICE),
                offered)

        # Model a dropped final response/new QR.  The peer may acknowledge a
        # cursor genuinely offered in the previous runtime, but it remains a
        # provisional acknowledgement until both projections prove equality.
        sync_service.reset_runtime_state()
        resumed = sync_service._host_on_batch(
            [_empty_host_batch(offered)], peer)
        self.assertEqual(resumed["batch"]["records"], [])
        self.assertTrue(resumed["confirmation_required"])
        with app.db() as connection:
            self.assertEqual(
                sync_engine.peer_ack_cursor(connection, REMOTE_DEVICE), 0)
            proof = sync_engine.projection_summary(connection)

        confirmed = sync_service._host_on_batch([
            _empty_host_batch(offered),
            {
                "kind": sync_service.PROJECTION_CONFIRM_KIND,
                "sender_device_id": REMOTE_DEVICE,
                "projection": proof,
            },
        ], peer)
        self.assertTrue(confirmed["exact_equal"])
        with app.db() as connection:
            self.assertEqual(
                sync_engine.peer_ack_cursor(connection, REMOTE_DEVICE),
                offered)

    def test_eleven_legacy_conflicts_are_drained_without_open_rows(self):
        note_ids = []
        for index in range(11):
            conversation_id = self.conversation(
                title="Opaque session {:02d}".format(index))
            with app.db() as connection:
                note_ids.append(int(connection.execute(
                    "INSERT INTO notes("
                    "conv,mode,therapist,content,created,updated) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        conversation_id, "terapi", "freud",
                        "local-{:02d}".format(index),
                        "2026-08-17 10:00", "2026-08-17 10:00",
                    ),
                ).lastrowid))

        with app.db() as connection:
            sync_engine.initialize_sync(connection, LOCAL_DEVICE)
            exported = sync_engine.export_change_batch(
                connection, LOCAL_DEVICE)
            notes = [
                record for record in exported["records"]
                if record["record_type"] == "note"
            ]
            self.assertEqual(len(notes), 11)
            for index, local in enumerate(notes):
                incoming = copy.deepcopy(local)
                incoming.update({
                    "origin_device_id": REMOTE_DEVICE,
                    "revision": 1,
                    "parent_origin_device_id": None,
                    "parent_revision": None,
                    "updated_at": "2026-08-17T11:{:02d}:00+00:00".format(
                        index),
                })
                incoming["payload"]["content"] = "remote-{:02d}".format(
                    index)
                incoming["payload"]["updated"] = (
                    "2026-08-17 11:{:02d}".format(index))
                self.assertTrue(sync_engine._queue_conflict(
                    connection, local, incoming,
                    "concurrent_clinical_edit"))
                sync_engine._mark_seen(connection, incoming)
                sync_engine._append_change(connection, incoming)

            refreshed = sync_engine.refresh_local_changes(
                connection, LOCAL_DEVICE)
            open_count = connection.execute(
                "SELECT COUNT(*) FROM sync_conflicts WHERE status='open'"
            ).fetchone()[0]
            remote_count = connection.execute(
                "SELECT COUNT(*) FROM notes WHERE content LIKE 'remote-%'"
            ).fetchone()[0]

        self.assertEqual(refreshed["auto_merged"], 11)
        self.assertEqual(open_count, 0)
        self.assertEqual(remote_count, 11)

    def test_physical_adhd_event_delete_cannot_be_resurrected(self):
        conversation_id = self.conversation(
            therapist="adhd", title="Opaque session")
        with app.db() as connection:
            habit_id = int(connection.execute(
                "INSERT INTO adhd_habits("
                "source_conv,title,target_per_week,preferred_days_json,"
                "status,review_after,is_guest,created,updated) "
                "VALUES(?,?,3,'[]','active',1780000000,0,?,?)",
                (
                    conversation_id, "Opaque habit",
                    "2026-08-17 09:00", "2026-08-17 09:00",
                ),
            ).lastrowid)
            event_id = int(connection.execute(
                "INSERT INTO adhd_habit_events("
                "habit,scheduled_for,status,effort_minutes,friction,"
                "created,updated) VALUES(?,?,'done',5,'start',?,?)",
                (
                    habit_id, 1780000100.0,
                    "2026-08-17 09:01", "2026-08-17 09:06",
                ),
            ).lastrowid)
            sync_engine.initialize_sync(connection, LOCAL_DEVICE)
            initial = sync_engine.export_change_batch(
                connection, LOCAL_DEVICE)
            live = copy.deepcopy(next(
                record for record in initial["records"]
                if record["record_type"] == "adhd_habit_event"))
            tombstone = sync_engine.record_local_delete(
                connection, "adhd_habit_event", event_id, LOCAL_DEVICE,
                deleted_at="2026-08-17T10:00:00+00:00",
                physical=True,
            )[0]

            forged_child = copy.deepcopy(live)
            forged_child.update({
                "revision": tombstone["revision"] + 1,
                "origin_device_id": REMOTE_DEVICE,
                "parent_origin_device_id": tombstone["origin_device_id"],
                "parent_revision": tombstone["revision"],
                "updated_at": "2099-08-17T10:01:00+00:00",
            })
            forged_child["payload"]["updated"] = "2099-08-17 10:01"
            batch = {
                "kind": sync_engine.BATCH_KIND,
                "version": sync_engine.BATCH_VERSION,
                "sender_device_id": REMOTE_DEVICE,
                "after_cursor": 0,
                "cursor": 1,
                "ack_cursor": 0,
                "has_more": False,
                "records": [forged_child],
            }
            merged = sync_engine.apply_change_batch(
                connection, batch, LOCAL_DEVICE)
            physical_count = connection.execute(
                "SELECT COUNT(*) FROM adhd_habit_events").fetchone()[0]
            head = connection.execute(
                "SELECT deleted_at FROM sync_records WHERE "
                "record_type='adhd_habit_event' AND public_id=?",
                (live["public_id"],),
            ).fetchone()

        self.assertEqual(merged["applied"], 0)
        self.assertEqual(physical_count, 0)
        self.assertIsNotNone(head["deleted_at"])


if __name__ == "__main__":
    import unittest
    unittest.main()
