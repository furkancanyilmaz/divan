import json

from unittest import mock

from support import HTTPTestCase, app


V5_TABLES = (
    "schema_variable_trials",
    "schema_origin_answers",
    "schema_v5_technique_sessions",
    "schema_v5_technique_turns",
    "schema_v5_integration_answers",
)


class SchemaV5PrivacyTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        self.conv = self.conversation(therapist="young")
        self._serial = 0

    def _pair(self, label):
        self._serial += 1
        stamp = "2026-08-23 12:{:02d}".format(self._serial)
        with app.db() as connection:
            user = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'user',?,?)",
                (self.conv, "user-{}".format(label), stamp),
            ).lastrowid
            assistant = connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,'assistant',?,?)",
                (self.conv, "assistant-{}".format(label), stamp),
            ).lastrowid
        return user, assistant

    def _seed_v5_graph(self):
        stamp = app.now()
        variable_question = self._pair("variable-question")
        variable_response = self._pair("variable-response")
        origin = self._pair("origin")
        session_source = self._pair("session-source")
        technique_turn = self._pair("technique-turn")
        integration = self._pair("integration")
        unrelated = self._pair("unrelated")
        with app.db() as connection:
            path = connection.execute(
                "INSERT INTO schema_paths(public_id,conv,therapist,"
                "flow_version,stage,step,status,practice_json,"
                "practice_status,created,updated) VALUES(?,?, 'young',5,"
                "'integrate','integration_practice','active',?,"
                "'active',?,?)",
                ("privacy-v5-path", self.conv,
                 json.dumps({"private": "V5-PRACTICE-COPY"}),
                 stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO schema_variable_trials(public_id,path,conv,seq,"
                "category,status,hypothetical_anchor,evidence_quote,effect,"
                "prompt_request_id,question_user_message,"
                "question_assistant_message,response_user_message,"
                "response_assistant_message,created,updated) VALUES(?,?,?,0,"
                "'place','driver',?,?,?,?,?,?,?,?,?,?)",
                ("privacy-variable", path, self.conv,
                 "V5-HYPOTHETICAL-COPY", "V5-EVIDENCE-COPY", "decrease",
                 "privacy-variable-request", variable_question[0],
                 variable_question[1], variable_response[0],
                 variable_response[1], stamp, stamp),
            )
            connection.execute(
                "INSERT INTO schema_origin_answers(public_id,path,conv,seq,"
                "field,status,text_value,source_user_message,"
                "source_assistant_message,prompt_request_id,created,updated) "
                "VALUES(?,?,?,0,'place','active',?,?,?,?,?,?)",
                ("privacy-origin", path, self.conv, "V5-ORIGIN-COPY",
                 origin[0], origin[1], "privacy-origin-request", stamp,
                 stamp),
            )
            session = connection.execute(
                "INSERT INTO schema_v5_technique_sessions(public_id,path,"
                "conv,seq,method_node_id,status,current_stage,stage_index,"
                "source_user_message,source_assistant_message,created,updated)"
                " VALUES(?,?,?,0,'young:method:imagery-rescripting',"
                "'active','notice',1,?,?,?,?)",
                ("privacy-session", path, self.conv, session_source[0],
                 session_source[1], stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO schema_v5_technique_turns(public_id,session,path,"
                "conv,seq,stage,status,source_user_message,"
                "source_assistant_message,prompt_request_id,created) VALUES("
                "?,?,?,?,0,'scene_boundary','completed',?,?,?,?)",
                ("privacy-technique-turn", session, path, self.conv,
                 technique_turn[0], technique_turn[1],
                 "privacy-technique-request", stamp),
            )
            connection.execute(
                "INSERT INTO schema_v5_integration_answers(public_id,path,"
                "conv,seq,field,status,text_value,source_user_message,"
                "source_assistant_message,prompt_request_id,created,updated) "
                "VALUES(?,?,?,0,'healthy_voice','active',?,?,?,?,?,?)",
                ("privacy-integration", path, self.conv,
                 "V5-INTEGRATION-COPY", integration[0], integration[1],
                 "privacy-integration-request", stamp, stamp),
            )
            # These are the compatibility projections written by the v5
            # reducer.  They must not retain a second copy after source forget.
            connection.execute(
                "INSERT INTO schema_origin(path,conv,source_user_message,"
                "source_assistant_message,scene,unmet_need,confidence,created,"
                "updated) VALUES(?,?,?,?,?,'V5-NEED-COPY','reported',?,?)",
                (path, self.conv, origin[0], origin[1],
                 "V5-SCENE-COPY", stamp, stamp),
            )
            connection.execute(
                "INSERT INTO schema_growth(path,conv,source_user_message,"
                "source_assistant_message,difference,environment_rescripted,"
                "healthy_adult_words,environment_status,created,updated) "
                "VALUES(?,?,?,?,?,?,?,'active',?,?)",
                (path, self.conv, integration[0], integration[1],
                 "V5-DIFFERENCE-COPY", "V5-ENVIRONMENT-COPY",
                 "V5-HEALTHY-COPY", stamp, stamp),
            )
            connection.execute(
                "INSERT INTO healthy_adult_marks(conv,path,evidence,"
                "source_message,source_assistant_message,created) "
                "VALUES(?,?,?,?,?,?)",
                (self.conv, path, "V5-MARK-COPY", integration[0],
                 integration[1], stamp),
            )
            job = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('chat_response',?,'succeeded',?,?)",
                (self.conv, stamp, stamp),
            ).lastrowid
            connection.execute(
                "INSERT INTO chat_requests(request_id,job,conv,user_message,"
                "assistant_message,status,guidance,partial_content,"
                "best_partial_content,schema_path,schema_step_id,"
                "schema_binding_json,schema_binding_result_json,"
                "schema_prompt_protocol,schema_prompt_intent,"
                "schema_prompt_plan_json,schema_prompt_result_json,"
                "created,updated) VALUES(?,?,?,?,?,'completed',?,?,?,?,?,?,?,?,"
                "?,?,?,?,?)",
                ("privacy-chat-request", job, self.conv, integration[0],
                 integration[1], "V5-GUIDANCE-SECRET",
                 "V5-PARTIAL-SECRET", "V5-BEST-PARTIAL-SECRET", path,
                 "integration_practice", "{\"secret\":\"V5-BINDING-SECRET\"}",
                 "{\"secret\":\"V5-BINDING-RESULT-SECRET\"}",
                 app.SCHEMA_PATH_V5_PROTOCOL, "integration_practice",
                 "{\"secret\":\"V5-PROMPT-PLAN-SECRET\"}",
                 "{\"secret\":\"V5-PROMPT-RESULT-SECRET\"}", stamp,
                 stamp),
            )
        return {
            "path": path,
            "origin_user": origin[0],
            "origin_assistant": origin[1],
            "unrelated_user": unrelated[0],
            "unrelated_assistant": unrelated[1],
        }

    def test_fk_off_conversation_delete_erases_every_v5_ledger_and_prompt_copy(self):
        self._seed_v5_graph()

        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            app.delete_conversation_data(connection, self.conv)

        for table in V5_TABLES + ("chat_requests",):
            with self.subTest(table=table):
                self.assertEqual(
                    self.row("SELECT COUNT(*) AS n FROM {}".format(table))["n"],
                    0,
                )
        self.assertIsNone(self.conversation_row(self.conv))

    def test_source_message_forget_redacts_and_invalidates_v5_without_other_message_loss(self):
        seeded = self._seed_v5_graph()
        count_before = self.row(
            "SELECT COUNT(*) AS n FROM messages WHERE conv=?", (self.conv,)
        )["n"]

        with app.db() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "DELETE FROM messages WHERE id=?", (seeded["origin_user"],)
            )

        self.assertEqual(
            self.row("SELECT COUNT(*) AS n FROM messages WHERE conv=?",
                     (self.conv,))["n"],
            count_before - 1,
        )
        self.assertIsNotNone(self.row(
            "SELECT id FROM messages WHERE id=?",
            (seeded["origin_assistant"],),
        ))
        self.assertIsNotNone(self.row(
            "SELECT id FROM messages WHERE id=?",
            (seeded["unrelated_user"],),
        ))
        self.assertIsNotNone(self.row(
            "SELECT id FROM messages WHERE id=?",
            (seeded["unrelated_assistant"],),
        ))

        for table in V5_TABLES:
            with self.subTest(table=table):
                rows = self.rows("SELECT * FROM {}".format(table))
                self.assertTrue(rows, table)
                self.assertTrue(all(row["status"] == "invalidated"
                                    for row in rows), table)
        self.assertEqual(tuple(self.row(
            "SELECT hypothetical_anchor,evidence_quote,effect FROM "
            "schema_variable_trials")), ("", "", ""))
        self.assertEqual(tuple(self.row(
            "SELECT text_value,age_value FROM schema_origin_answers")),
            ("", None))
        self.assertEqual(
            self.row("SELECT text_value FROM schema_v5_integration_answers")[0],
            "",
        )
        request = self.row(
            "SELECT * FROM chat_requests WHERE request_id='privacy-chat-request'"
        )
        self.assertEqual(request["schema_binding_json"], "{}")
        self.assertEqual(request["schema_binding_result_json"], "null")
        self.assertEqual(request["schema_prompt_plan_json"], "{}")
        self.assertEqual(request["schema_prompt_result_json"], "{}")
        self.assertEqual(request["partial_content"], "")
        self.assertEqual(request["best_partial_content"], "")
        self.assertEqual(request["guidance"], "")
        rendered = json.dumps(
            [dict(row) for table in V5_TABLES
             for row in self.rows("SELECT * FROM {}".format(table))],
            ensure_ascii=False,
        )
        rendered += json.dumps([
            dict(row) for table in (
                "schema_origin", "schema_growth", "healthy_adult_marks",
                "schema_paths", "chat_requests",
            ) for row in self.rows("SELECT * FROM {}".format(table))
        ], ensure_ascii=False)
        self.assertNotIn("-COPY", rendered)
        self.assertNotIn("-SECRET", rendered)

    def test_export_includes_user_v5_ledgers_but_never_hidden_provider_state(self):
        self._seed_v5_graph()

        status, exported, _headers = self.request("GET", "/api/export-json")

        self.assertEqual(status, 200, exported)
        self.assertEqual(exported["version"], 6)
        self.assertEqual(exported["privacy_version"], 1)
        for table in V5_TABLES:
            with self.subTest(table=table):
                self.assertIn(table, exported["data"])
                self.assertEqual(len(exported["data"][table]), 1)
        rendered = json.dumps(exported, ensure_ascii=False)
        self.assertIn("V5-EVIDENCE-COPY", rendered)
        self.assertIn("V5-ORIGIN-COPY", rendered)
        self.assertIn("V5-INTEGRATION-COPY", rendered)
        for private_value in (
            "V5-GUIDANCE-SECRET",
            "V5-PARTIAL-SECRET",
            "V5-BEST-PARTIAL-SECRET",
            "V5-BINDING-SECRET",
            "V5-BINDING-RESULT-SECRET",
            "V5-PROMPT-PLAN-SECRET",
            "V5-PROMPT-RESULT-SECRET",
        ):
            self.assertNotIn(private_value, rendered)
        self.assertNotIn("chat_requests", exported["data"])

    def test_delete_all_explicitly_erases_v5_and_chat_request_rows(self):
        self._seed_v5_graph()
        original_db = app.db

        def foreign_keys_off_db():
            connection = original_db()
            connection.execute("PRAGMA foreign_keys=OFF")
            return connection

        # Exercise the endpoint itself with FK enforcement disabled for both
        # application and sync-metadata connections.  The explicit table order
        # must own privacy erasure; cascades are only a defence in depth.
        app.sync_service.configure(
            foreign_keys_off_db, lambda: app.DB_PATH, app.DATA_WRITE_LOCK,
            snapshot_callback=app.create_restore_snapshot,
            mutation_callback=app.bump_data_generation,
            idle_callback=app.device_sync_idle,
        )
        try:
            with mock.patch.object(app, "db", side_effect=foreign_keys_off_db), \
                    mock.patch.object(app, "clear_automatic_backups"), \
                    mock.patch.object(app, "clear_restore_snapshots"):
                status, body, _headers = self.request(
                    "POST", "/api/delete-all",
                    {"confirm": "TÜM VERİLERİ SİL"},
                )
        finally:
            app.sync_service.configure(
                original_db, lambda: app.DB_PATH, app.DATA_WRITE_LOCK,
                snapshot_callback=app.create_restore_snapshot,
                mutation_callback=app.bump_data_generation,
                idle_callback=app.device_sync_idle,
            )

        self.assertEqual(status, 200, body)
        for table in V5_TABLES + ("chat_requests", "messages",
                                  "conversations"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.row("SELECT COUNT(*) AS n FROM {}".format(table))["n"],
                    0,
                )
        with open(app.DB_PATH, "rb") as database_file:
            database_bytes = database_file.read()
        self.assertNotIn(b"V5-EVIDENCE-COPY", database_bytes)
        self.assertNotIn(b"V5-PROMPT-PLAN-SECRET", database_bytes)
