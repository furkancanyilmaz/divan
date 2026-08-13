import json
import os
import sqlite3
from pathlib import Path
from unittest import mock

from support import HTTPTestCase, app


class PostprocessProviderSnapshotTests(HTTPTestCase):

    def set_provider(self, provider, model):
        app.set_setting("llm_provider", provider)
        app.set_setting("{}_model".format(provider), model)

    def approved_notes(self, therapist="freud", count=None):
        for index in range(count or app.FORMULATE_EVERY):
            conv_id = self.conversation(
                therapist=therapist,
                title="Onaylı not {}".format(index))
            stamp = "2026-07-20 11:{:02d}".format(index)
            with app.db() as conn:
                conn.execute(
                    "INSERT INTO notes("
                    "conv,mode,therapist,content,created,approved,scope,"
                    "sensitive,updated) VALUES("
                    "?,'terapi',?,?,?,1,'therapist',0,?)",
                    (conv_id, therapist, "not-{}".format(index),
                     stamp, stamp))

    def existing_postprocess_artifacts(self, conv_id, mode="terapi",
                                       therapist="freud"):
        stamp = "2026-07-20 12:00"
        with app.db() as conn:
            conn.execute(
                "INSERT INTO notes("
                "conv,mode,therapist,content,created,approved,scope,"
                "sensitive,updated) VALUES(?,?,?,?,?,1,'therapist',0,?)",
                (conv_id, mode, therapist, "mevcut-not", stamp, stamp))
            conn.execute(
                "INSERT INTO session_summaries("
                "conv,draft,status,created,updated"
                ") VALUES(?,'mevcut-özet','pending',?,?)",
                (conv_id, stamp, stamp))
            if mode == "terapi":
                conn.execute(
                    "INSERT INTO letters(conv,therapist,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, therapist, "mevcut-mektup", stamp))

    def test_create_is_idempotent_and_new_terminal_job_gets_new_snapshot(self):
        conv_id = self.conversation()
        self.set_provider("deepseek", "deepseek-snapshot-a")

        first = app.create_job("session_postprocess", conv_id)
        first_row = self.row("SELECT * FROM jobs WHERE id=?", (first,))
        self.assertEqual(
            (first_row["provider"], first_row["model"]),
            ("deepseek", "deepseek-snapshot-a"))

        self.set_provider("openai", "gpt-snapshot-b")
        self.assertEqual(
            app.create_job("session_postprocess", conv_id), first)
        unchanged = self.row("SELECT * FROM jobs WHERE id=?", (first,))
        self.assertEqual(
            (unchanged["provider"], unchanged["model"]),
            ("deepseek", "deepseek-snapshot-a"))

        app.update_job(first, "succeeded", "tamamlandı", 100, "")
        second = app.create_job("session_postprocess", conv_id)
        self.assertNotEqual(second, first)
        second_row = self.row("SELECT * FROM jobs WHERE id=?", (second,))
        self.assertEqual(
            (second_row["provider"], second_row["model"]),
            ("openai", "gpt-snapshot-b"))

    def test_retry_keeps_original_snapshot(self):
        conv_id = self.conversation()
        self.set_provider("deepseek", "deepseek-retry-a")
        job_id = app.create_job("session_postprocess", conv_id)
        app.update_job(job_id, "failed", "hata", 40, "provider_error")

        self.set_provider("anthropic", "claude-retry-b")
        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": job_id})

        self.assertEqual(status, 200)
        self.assertEqual(body["job_id"], job_id)
        row = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(
            (row["provider"], row["model"]),
            ("deepseek", "deepseek-retry-a"))

    def test_one_job_pins_note_formulation_summary_and_letter(self):
        self.approved_notes()
        conv_id = self.conversation(therapist="freud", ended=1)
        self.messages(conv_id, app.NOTE_MIN_MESSAGES)
        self.set_provider("deepseek", "deepseek-artifact-a")
        job_id = app.create_job("session_postprocess", conv_id)

        # Ayar hem iş başlamadan hem ilk model çağrısından sonra değişsin.
        self.set_provider("openai", "gpt-artifact-b")
        calls = []

        def complete(*_args, **kwargs):
            calls.append((kwargs.get("provider_id"),
                          kwargs.get("model_id"),
                          kwargs.get("max_tokens")))
            if len(calls) == 1:
                self.set_provider("anthropic", "claude-artifact-c")
            return "üretilen-artifact-{}".format(len(calls))

        with mock.patch.object(
                app, "ds_complete_continued", side_effect=complete),                 mock.patch.object(
                    app, "ds_complete", side_effect=complete),                 mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        self.assertEqual(len(calls), 4)
        self.assertEqual(
            {(provider, model) for provider, model, _ in calls},
            {("deepseek", "deepseek-artifact-a")})
        row = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(
            (row["provider"], row["model"]),
            ("deepseek", "deepseek-artifact-a"))
        self.assertIsNotNone(
            self.row("SELECT * FROM formulations ORDER BY id DESC LIMIT 1"))

    def test_lesson_concepts_use_the_same_job_snapshot(self):
        conv_id = self.conversation(
            mode="ders", therapist="freud", ended=1)
        self.messages(conv_id, app.NOTE_MIN_MESSAGES)
        self.set_provider("openai", "gpt-lesson-a")
        job_id = app.create_job("session_postprocess", conv_id)
        self.set_provider("deepseek", "deepseek-lesson-b")
        calls = []

        def complete(messages, *args, **kwargs):
            calls.append((kwargs.get("provider_id"),
                          kwargs.get("model_id")))
            first_content = messages[0]["content"] if messages else ""
            if "ders kavramları JSON" in first_content:
                return json.dumps([{
                    "term": "Aktarım",
                    "definition": "Ders bağlamındaki kısa tanım.",
                }], ensure_ascii=False)
            return "ders-artifact"

        with mock.patch.object(
                app, "ds_complete_continued", side_effect=complete),                 mock.patch.object(
                    app, "ds_complete", side_effect=complete),                 mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        self.assertEqual(len(calls), 3)
        self.assertEqual(set(calls), {("openai", "gpt-lesson-a")})
        self.assertIsNotNone(
            self.row("SELECT * FROM concepts WHERE conv=?", (conv_id,)))
        self.assertEqual(
            self.row("SELECT status FROM jobs WHERE id=?", (job_id,))
            ["status"],
            "succeeded")

    def test_legacy_blank_job_claims_current_pair_only_once(self):
        conv_id = self.conversation(ended=1)
        with app.db() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs("
                "kind,conv,status,stage,progress,created,updated"
                ") VALUES('session_postprocess',?,'queued','eski',0,'d','d')",
                (conv_id,)).lastrowid
        self.set_provider("deepseek", "deepseek-legacy-a")

        with mock.patch.object(app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)
        first = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(
            (first["provider"], first["model"]),
            ("deepseek", "deepseek-legacy-a"))

        self.set_provider("openai", "gpt-legacy-b")
        with app.db() as conn:
            conn.execute(
                "UPDATE jobs SET status='queued',finished=NULL WHERE id=?",
                (job_id,))
        with mock.patch.object(app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)
        second = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(
            (second["provider"], second["model"]),
            ("deepseek", "deepseek-legacy-a"))

    def test_partial_or_invalid_snapshot_never_falls_back(self):
        conv_id = self.conversation(ended=1)
        with app.db() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs("
                "kind,conv,status,provider,model,created,updated"
                ") VALUES('session_postprocess',?,'queued','deepseek','',"
                "'d','d')",
                (conv_id,)).lastrowid
        self.set_provider("openai", "gpt-must-not-run")

        with mock.patch.object(app, "ds_complete") as complete, \
                mock.patch("builtins.print"), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        complete.assert_not_called()
        row = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "provider_snapshot_invalid")
        self.assertEqual((row["provider"], row["model"]), ("deepseek", ""))

    def test_lmstudio_auto_is_resolved_and_persisted_once(self):
        conv_id = self.conversation(ended=1)
        self.messages(conv_id, app.NOTE_MIN_MESSAGES)
        self.set_provider("lmstudio", "auto")
        job_id = app.create_job("session_postprocess", conv_id)
        self.assertEqual(
            self.row("SELECT model FROM jobs WHERE id=?", (job_id,))["model"],
            "auto")
        # Snapshot auto olmasına rağmen sonradan yazılan model ayarı okunmamalı.
        app.set_setting("lmstudio_model", "later-setting-model")
        calls = []

        def complete(*_args, **kwargs):
            calls.append((kwargs.get("provider_id"),
                          kwargs.get("model_id")))
            app.set_setting("lmstudio_model", "changed-again")
            return "yerel-artifact"

        with mock.patch.object(
                app, "discover_local_models",
                return_value=["loaded-local-model"]) as discover, \
                mock.patch.object(
                    app, "ds_complete_continued", side_effect=complete), \
                mock.patch.object(
                    app, "ds_complete", side_effect=complete), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        discover.assert_called_once()
        self.assertEqual(
            set(calls), {("lmstudio", "loaded-local-model")})
        row = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(row["model"], "loaded-local-model")
        self.assertNotIn("secret", row.keys())
        self.assertNotIn("base_url", row.keys())

    def test_provider_request_honors_concrete_and_auto_local_pins(self):
        self.set_provider("lmstudio", "auto")
        payload = {
            "messages": [{"role": "user", "content": "Merhaba"}],
            "max_tokens": 10,
            "stream": False,
        }
        with mock.patch.object(
                app, "discover_local_models",
                side_effect=AssertionError("somut pin keşif yapmamalı")):
            request, config = app.provider_request(
                payload, provider_id="lmstudio",
                model_id="concrete-local-model")
        self.assertEqual(config["model"], "concrete-local-model")
        self.assertEqual(
            json.loads(request.data.decode("utf-8"))["model"],
            "concrete-local-model")

        app.set_setting("lmstudio_model", "later-explicit-setting")
        with mock.patch.object(
                app, "discover_local_models",
                return_value=["actually-loaded-model"]) as discover:
            request, config = app.provider_request(
                payload, provider_id="lmstudio", model_id="auto")
        discover.assert_called_once()
        self.assertEqual(config["model"], "actually-loaded-model")
        self.assertEqual(
            json.loads(request.data.decode("utf-8"))["model"],
            "actually-loaded-model")

    def test_formulation_failure_marks_job_failed_and_retry_keeps_snapshot(self):
        self.approved_notes(count=app.FORMULATE_EVERY)
        conv_id = self.conversation(therapist="freud", ended=1)
        self.messages(conv_id, app.NOTE_MIN_MESSAGES)
        self.existing_postprocess_artifacts(conv_id)
        self.set_provider("deepseek", "deepseek-formulation-pin")
        job_id = app.create_job("session_postprocess", conv_id)

        with mock.patch.object(
                app, "ds_complete",
                side_effect=app.ProviderError(
                    "provider_unavailable", "geçici sağlayıcı hatası")), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        failed = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("formulation_exception", failed["error_code"])
        self.assertIsNone(
            self.row("SELECT * FROM formulations ORDER BY id DESC LIMIT 1"))

        status, body, _ = self.request(
            "POST", "/api/job/retry", {"id": job_id})
        self.assertEqual(status, 200)
        self.assertEqual(body["job_id"], job_id)
        self.assertEqual(self.queued_job_id(), job_id)
        app.JOB_QUEUE.task_done()
        calls = []

        def complete(_messages, max_tokens=app.MAX_TOKENS_NOTE,
                     provider_id=None, model_id=None):
            calls.append((provider_id, model_id))
            return "yeniden denemede formülasyon"

        with mock.patch.object(
                app, "ds_complete", side_effect=complete), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        succeeded = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(succeeded["status"], "succeeded")
        self.assertEqual(
            (succeeded["provider"], succeeded["model"]),
            ("deepseek", "deepseek-formulation-pin"))
        self.assertEqual(
            set(calls), {("deepseek", "deepseek-formulation-pin")})
        self.assertIsNotNone(
            self.row("SELECT * FROM formulations ORDER BY id DESC LIMIT 1"))

    def test_concept_parse_failure_marks_job_failed_then_retry_succeeds(self):
        conv_id = self.conversation(
            mode="ders", therapist="freud", ended=1)
        self.messages(conv_id, app.NOTE_MIN_MESSAGES)
        self.existing_postprocess_artifacts(
            conv_id, mode="ders", therapist="freud")
        self.set_provider("openai", "gpt-concepts-pin")
        job_id = app.create_job("session_postprocess", conv_id)

        with mock.patch.object(
                app, "ds_complete", return_value="JSON olmayan yanıt"), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        failed = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("concepts_exception", failed["error_code"])

        status, _, _ = self.request(
            "POST", "/api/job/retry", {"id": job_id})
        self.assertEqual(status, 200)
        self.assertEqual(self.queued_job_id(), job_id)
        app.JOB_QUEUE.task_done()
        valid = json.dumps([{
            "term": "Aktarım",
            "definition": "Ders bağlamındaki kısa tanım.",
        }], ensure_ascii=False)
        calls = []

        def complete(_messages, max_tokens=app.MAX_TOKENS_NOTE,
                     provider_id=None, model_id=None):
            calls.append((provider_id, model_id))
            return valid

        with mock.patch.object(
                app, "ds_complete", side_effect=complete), \
                mock.patch.object(
                    app, "automatic_backup", return_value=None):
            app.postprocess_ended_session(conv_id, job_id)

        succeeded = self.row("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(succeeded["status"], "succeeded")
        self.assertEqual(set(calls), {("openai", "gpt-concepts-pin")})
        self.assertIsNotNone(
            self.row("SELECT * FROM concepts WHERE conv=?", (conv_id,)))

    def test_direct_artifact_calls_keep_legacy_silent_failure_results(self):
        self.approved_notes(count=app.FORMULATE_EVERY)
        with mock.patch.object(
                app, "ds_complete",
                side_effect=app.ProviderError(
                    "provider_unavailable", "geçici sağlayıcı hatası")), \
                mock.patch("builtins.print"):
            self.assertFalse(app.maybe_formulate("terapi", "freud"))

        lesson_id = self.conversation(mode="ders", therapist="freud")
        self.messages(lesson_id, app.NOTE_MIN_MESSAGES)
        with mock.patch.object(
                app, "ds_complete", return_value="JSON olmayan yanıt"), \
                mock.patch("builtins.print"):
            self.assertEqual(app.extract_concepts(lesson_id), 0)

    def test_provider_and_model_are_read_from_one_settings_snapshot(self):
        self.set_provider("deepseek", "deepseek-before")
        app.set_setting("openai_model", "gpt-before")
        real_db = app.db
        raced = {"done": False}

        class RacingReadConnection:
            def __init__(self):
                self.connection = sqlite3.connect(app.DB_PATH)
                self.connection.row_factory = sqlite3.Row
                self.connection.execute("PRAGMA busy_timeout=5000")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                self.connection.close()

            def execute(self, sql, params=()):
                cursor = self.connection.execute(sql, params)
                if (not raced["done"]
                        and sql.lstrip().upper().startswith("SELECT")):
                    raced["done"] = True
                    writer = sqlite3.connect(app.DB_PATH)
                    try:
                        writer.execute("PRAGMA busy_timeout=5000")
                        writer.execute(
                            "UPDATE settings SET value='openai' "
                            "WHERE key='llm_provider'")
                        writer.execute(
                            "UPDATE settings SET value='deepseek-after' "
                            "WHERE key='deepseek_model'")
                        writer.execute(
                            "UPDATE settings SET value='gpt-after' "
                            "WHERE key='openai_model'")
                        writer.commit()
                    finally:
                        writer.close()
                return cursor

        env = {
            "DIVAN_LLM_PROVIDER": "",
            "DEEPSEEK_MODEL": "",
            "OPENAI_MODEL": "",
        }
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(
                    app, "db", side_effect=RacingReadConnection):
            snapshot = app._new_postprocess_provider_snapshot()

        self.assertTrue(raced["done"])
        self.assertIn(snapshot, {
            ("deepseek", "deepseek-before"),
            ("openai", "gpt-after"),
        })
        # The writer really committed; the assertion above therefore rejects
        # old-provider/new-model and new-provider/old-model torn reads.
        with real_db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT value FROM settings WHERE key='llm_provider'"
                ).fetchone()["value"],
                "openai")

    def test_init_db_migrates_legacy_jobs_without_losing_rows(self):
        legacy_path = Path(self._tmp.name) / "legacy-jobs.db"
        connection = sqlite3.connect(str(legacy_path))
        connection.execute(
            "CREATE TABLE jobs("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,"
            "conv INTEGER,status TEXT DEFAULT 'queued',stage TEXT DEFAULT '',"
            "progress INTEGER DEFAULT 0,error_code TEXT DEFAULT '',"
            "created TEXT,started TEXT,finished TEXT,updated TEXT)")
        connection.execute(
            "INSERT INTO jobs(kind,conv,status,created,updated) "
            "VALUES('session_postprocess',7,'queued','eski','eski')")
        connection.commit()
        connection.close()
        current_path = app.DB_PATH
        try:
            app.DB_PATH = str(legacy_path)
            app.init_db()
            with app.db() as migrated:
                columns = {
                    row["name"] for row in migrated.execute(
                        "PRAGMA table_info(jobs)")}
                row = migrated.execute(
                    "SELECT * FROM jobs WHERE conv=7").fetchone()
        finally:
            app.DB_PATH = current_path

        self.assertTrue({"provider", "model"}.issubset(columns))
        self.assertIsNotNone(row)
        self.assertEqual((row["provider"], row["model"]), ("", ""))
