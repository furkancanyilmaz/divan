"""Yaşayan Harita çıkarımı aynı yanıtta gelir ([[HARITA]]).

Önceden harita ayrı bir model çağrısıyla doluyordu. Artık teknik, mod
önerisi ve faz ile birlikte TEK yanıtta geliyor: ikinci çağrı yok.

Kullanıcı kararı: gelen her çıkarım onay beklemeden 'uyuyor'
(confirmed) işaretlenir; kullanıcı haritadan geri alabilir.
"""

from support import HTTPTestCase, app


class LivingMapMarkerParseTests(HTTPTestCase):
    def test_all_four_markers_come_from_one_reply(self):
        raw = ("Mesafe sizi koruyor.\n"
               "[[TEKNIK]] normalleştirme | bilmemeyi meşrulaştırdım\n"
               "[[MOD]] detached_protector | mesafeliyim mecbur\n"
               "[[HARITA]] dongu | yakınlık artınca mesafe koyuyor\n"
               "[[FAZ]] focus | kalıp netleşti")
        text, suggestions, phase, technique, notes, _ = (
            app.split_schema_markers(raw))
        self.assertEqual(text, "Mesafe sizi koruyor.")
        self.assertEqual(technique["technique"], "normalleştirme")
        self.assertEqual(suggestions[0]["mode_key"], "detached_protector")
        self.assertEqual(phase["to_phase"], "focus")
        self.assertEqual(notes[0]["section"], "cycles")
        for mark in app.SCHEMA_ALL_MARKS:
            self.assertNotIn(mark, text)

    def test_every_category_maps_to_a_section(self):
        beklenen = {
            "dongu": "cycles",
            "deger_ihtiyac": "values_needs",
            "guc": "strengths_exceptions",
            "hedef": "goals_helpful",
        }
        for kategori, bolum in beklenen.items():
            notes = app.collect_map_notes(
                "[[HARITA]] {} | kullanıcının sözü".format(kategori))
            self.assertEqual(notes[0]["section"], bolum, kategori)

    def test_unknown_category_is_dropped_not_leaked(self):
        text, _, _, _, notes, _ = app.split_schema_markers(
            "Merhaba.\n[[HARITA]] uydurma | bir şey")
        self.assertEqual(text, "Merhaba.")
        self.assertEqual(notes, [])

    def test_note_without_evidence_is_skipped(self):
        self.assertEqual(app.collect_map_notes("[[HARITA]] dongu | "), [])

    def test_notes_are_capped_and_deduplicated(self):
        tekrar = "\n".join(
            ["[[HARITA]] dongu | aynı çıkarım"] * 3)
        self.assertEqual(len(app.collect_map_notes(tekrar)), 1)
        cok = "\n".join(
            "[[HARITA]] dongu | çıkarım {}".format(i) for i in range(6))
        self.assertEqual(
            len(app.collect_map_notes(cok)), app.SCHEMA_MAP_MAX)


class LivingMapMarkerWriteTests(HTTPTestCase):
    stamp = "2026-08-20 18:30"

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        provider, model = app._configured_provider_model_snapshot()
        with app.db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO session_meta("
                "conv,schema_mode_enabled,schema_mode_initialized,"
                "schema_mode_provider,schema_mode_model,updated) "
                "VALUES(?,1,1,?,?,?)",
                (self.conv, provider, model, self.stamp))

    def write_reply(self, reply):
        with app.db() as connection:
            provider, model = app._configured_provider_model_snapshot()
            user_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'user',"
                "'yakınlık artınca mesafe koyuyorum',?,"
                "'completed')", (self.conv, self.stamp)).lastrowid
            job = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'running',?,?)",
                (self.conv, self.stamp, self.stamp)).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,conv,user_message,"
                "status,provider,model,job,created,updated) VALUES("
                "'req-harita-000001',?,?,'running',?,?,?,?,?)",
                (self.conv, user_id, provider, model, job,
                 self.stamp, self.stamp))
            row = connection.execute(
                "SELECT * FROM chat_requests WHERE "
                "request_id='req-harita-000001'").fetchone()
            assistant = app._upsert_chat_assistant(
                connection, row, reply, "completed")
            connection.execute(
                "UPDATE chat_requests SET status='completed',"
                "assistant_message=? WHERE request_id='req-harita-000001'",
                (assistant,))
            return user_id, assistant

    def test_note_lands_in_the_map_as_confirmed(self):
        user_id, assistant_id = self.write_reply(
            "Mesafe sizi koruyor.\n"
            "[[HARITA]] dongu | yakınlık artınca mesafe koyuyor")
        with app.db() as connection:
            row = connection.execute(
                "SELECT id,claim_type,statement,status,scope,sensitive,"
                "reviewed_evidence_id,source_assistant_message "
                "FROM psych_claims WHERE source_conv=?",
                (self.conv,)).fetchone()
            evidence = connection.execute(
                "SELECT o.source_message,e.review_status FROM "
                "psych_claim_evidence e JOIN psych_observations o "
                "ON o.id=e.observation WHERE e.claim=?", (row["id"],)
            ).fetchone()
        self.assertEqual(row["claim_type"], "pattern")
        self.assertEqual(row["statement"], "yakınlık artınca mesafe koyuyor")
        # Kullanıcı isteği: onay beklemeden doğrudan uyuyor.
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(row["sensitive"], 0)
        self.assertGreater(row["reviewed_evidence_id"], 0)
        self.assertEqual(row["source_assistant_message"], assistant_id)
        self.assertEqual(evidence["source_message"], user_id)
        self.assertEqual(evidence["review_status"], "accepted")

    def test_ungrounded_map_marker_is_not_written(self):
        self.write_reply(
            "Yanıt.\n[[HARITA]] dongu | çocukken terk edildi")
        self.assertEqual(self.row(
            "SELECT COUNT(*) AS n FROM psych_claims WHERE source_conv=?",
            (self.conv,))["n"], 0)

    def test_later_safety_or_partial_pair_invalidates_turn_marker(self):
        user_id, assistant_id = self.write_reply(
            "Yanıt.\n[[HARITA]] dongu | yakınlık artınca mesafe koyuyorum")
        self.assertEqual(len(
            app.living_map_payload("young")["sections"]["cycles"]), 1)
        with app.db() as connection:
            connection.execute(
                "INSERT INTO safety_events(conv,source_message,kind,created) "
                "VALUES(?,?,'crisis',?)", (self.conv, user_id, self.stamp))
        payload = app.living_map_payload("young")
        self.assertEqual(payload["sections"]["cycles"], [])
        self.assertEqual(payload["counts"]["retired"], 1)

        with app.db() as connection:
            connection.execute(
                "DELETE FROM safety_events WHERE conv=?", (self.conv,))
            connection.execute(
                "UPDATE messages SET delivery_status='partial' WHERE id=?",
                (assistant_id,))
        self.assertEqual(
            app.living_map_payload("young")["sections"]["cycles"], [])

    def test_map_note_is_not_written_without_schema_mode(self):
        # Şema modu kapalı bir görüşmede harita yazılmamalı.
        other = self.conversation(therapist="freud")
        with app.db() as connection:
            message_id = connection.execute(
                "INSERT INTO messages(conv,role,content,created,"
                "delivery_status) VALUES(?,'assistant','x',?,'completed')",
                (other, self.stamp)).lastrowid
            app._record_message_technique(
                connection, other, message_id, None, None,
                [{"category": "dongu", "section": "cycles",
                  "claim_type": "pattern", "note": "sızmamalı"}])
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM psych_claims WHERE source_conv=?",
                (other,)).fetchone()["n"]
        self.assertEqual(count, 0)
