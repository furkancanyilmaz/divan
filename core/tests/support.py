import io
import json
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import server as app  # noqa: E402


class DatabaseTestCase(unittest.TestCase):
    """Every test gets a brand-new SQLite database and job queue."""

    def setUp(self):
        self._old_db_path = app.DB_PATH
        self._old_job_queue = app.JOB_QUEUE
        self._old_worker_started = app.JOB_WORKER_STARTED
        self._old_data_generation = app.DATA_GENERATION
        self._old_session_token = app.EMBEDDED_SESSION_TOKEN
        self._old_secret_reader = app.SECRET_STORE_READER
        self._old_secret_writer = app.SECRET_STORE_WRITER
        self._old_unlock_sessions = dict(app.APP_UNLOCK_SESSIONS)
        self._old_unlock_failures = {
            key: dict(value) for key, value in app.APP_UNLOCK_FAILURES.items()
        }
        self._old_chat_cancel_events = dict(app.CHAT_CANCEL_EVENTS)
        self._old_chat_active_responses = dict(app.CHAT_ACTIVE_RESPONSES)
        self._old_chat_retry_timers = dict(app.CHAT_RETRY_TIMERS)
        self._old_living_map_autoscan_timers = dict(
            app.LIVING_MAP_AUTOSCAN_TIMERS)
        self._tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = str(Path(self._tmp.name) / "test-freud.db")
        app.JOB_QUEUE = queue.Queue()
        app.JOB_WORKER_STARTED = False
        app.DATA_GENERATION = 0
        app.EMBEDDED_SESSION_TOKEN = ""
        app.reset_app_unlock_state()
        with app.CHAT_CANCEL_LOCK:
            for timer in app.CHAT_RETRY_TIMERS.values():
                timer.cancel()
            app.CHAT_CANCEL_EVENTS.clear()
            app.CHAT_ACTIVE_RESPONSES.clear()
            app.CHAT_RETRY_TIMERS.clear()
        with app.LIVING_MAP_AUTOSCAN_TIMER_LOCK:
            for timer in app.LIVING_MAP_AUTOSCAN_TIMERS.values():
                timer.cancel()
            app.LIVING_MAP_AUTOSCAN_TIMERS.clear()
        app.configure_secret_store(None, None, migrate=False)
        self._network_patch = mock.patch.object(
            app.urllib.request, "urlopen",
            side_effect=AssertionError("tests must never access the network"))
        self._network_patch.start()
        app.init_db()

    def tearDown(self):
        self._network_patch.stop()
        app.DB_PATH = self._old_db_path
        app.JOB_QUEUE = self._old_job_queue
        app.JOB_WORKER_STARTED = self._old_worker_started
        app.DATA_GENERATION = self._old_data_generation
        app.EMBEDDED_SESSION_TOKEN = self._old_session_token
        app.reset_app_unlock_state()
        app.APP_UNLOCK_SESSIONS.update(self._old_unlock_sessions)
        app.APP_UNLOCK_FAILURES.update(self._old_unlock_failures)
        with app.CHAT_CANCEL_LOCK:
            for timer in app.CHAT_RETRY_TIMERS.values():
                timer.cancel()
            app.CHAT_CANCEL_EVENTS.clear()
            app.CHAT_CANCEL_EVENTS.update(self._old_chat_cancel_events)
            app.CHAT_ACTIVE_RESPONSES.clear()
            app.CHAT_ACTIVE_RESPONSES.update(
                self._old_chat_active_responses)
            app.CHAT_RETRY_TIMERS.clear()
            app.CHAT_RETRY_TIMERS.update(
                self._old_chat_retry_timers)
        with app.LIVING_MAP_AUTOSCAN_TIMER_LOCK:
            for timer in app.LIVING_MAP_AUTOSCAN_TIMERS.values():
                timer.cancel()
            app.LIVING_MAP_AUTOSCAN_TIMERS.clear()
            app.LIVING_MAP_AUTOSCAN_TIMERS.update(
                self._old_living_map_autoscan_timers)
        app.configure_secret_store(
            self._old_secret_reader, self._old_secret_writer, migrate=False)
        self._tmp.cleanup()

    def conversation(self, mode="terapi", therapist="freud", submode=None,
                     ended=0, title=None, source_mode=0, case_id=None,
                     created="2026-07-20 10:00", updated="2026-07-20 10:00"):
        title = title or ("Yeni seans" if mode == "terapi" else "Yeni ders")
        with app.db() as conn:
            cur = conn.execute(
                "INSERT INTO conversations("
                "mode,submode,therapist,title,ended,source_mode,case_id,"
                "created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (mode, submode, therapist, title, ended, source_mode, case_id,
                 created, updated),
            )
            return cur.lastrowid

    def messages(self, conv_id, count, prefix="mesaj"):
        with app.db() as conn:
            for index in range(count):
                conn.execute(
                    "INSERT INTO messages(conv,role,content,created) "
                    "VALUES(?,?,?,?)",
                    (conv_id, "user" if index % 2 == 0 else "assistant",
                     "{}-{:02d}".format(prefix, index),
                     "2026-07-20 10:{:02d}".format(index % 60)),
                )

    def row(self, sql, params=()):
        with app.db() as conn:
            return conn.execute(sql, params).fetchone()

    def rows(self, sql, params=()):
        with app.db() as conn:
            return conn.execute(sql, params).fetchall()

    def conversation_row(self, conv_id):
        return self.row("SELECT * FROM conversations WHERE id=?", (conv_id,))

    def queued_job_id(self):
        item = app.JOB_QUEUE.get_nowait()
        self.assertIsInstance(item, tuple)
        generation, job_id = item
        self.assertEqual(generation, app.data_generation())
        return job_id

    def system_prompt(self, conv_id):
        conv = self.conversation_row(conv_id)
        notes = app.context_notes(conv, conv_id)
        formulation = app.latest_formulation(conv["mode"], conv["therapist"])
        return app.build_system_prompt(conv, notes, formulation,
                                       app.get_setting("profile"))


class HTTPTestCase(DatabaseTestCase):
    """Exercise the real Handler in memory, without opening any socket."""

    def setUp(self):
        super().setUp()
        self._worker_patch = mock.patch.object(
            app, "start_job_worker", return_value=None)
        self._worker_patch.start()

    def tearDown(self):
        self._worker_patch.stop()
        super().tearDown()

    def request(self, method, path, payload=None, headers=None):
        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler = object.__new__(app.Handler)
        handler.path = path
        handler.command = method
        handler.request_version = "HTTP/1.1"
        handler.requestline = "{} {} HTTP/1.1".format(method, path)
        handler.client_address = ("127.0.0.1", 0)
        handler.server = None
        handler.close_connection = False
        request_headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Host": "127.0.0.1:{}".format(app.PORT),
        }
        request_headers.update(headers or {})
        handler.headers = request_headers
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()
        else:
            raise AssertionError("unsupported test method: " + method)

        raw_response = handler.wfile.getvalue()
        head, raw_body = raw_response.split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1").split("\r\n")
        status = int(lines[0].split()[1])
        response_headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                response_headers[key.strip()] = value.strip()
        content_type = response_headers.get("Content-Type", "")
        if "application/json" in content_type:
            parsed = json.loads(raw_body.decode("utf-8"))
        elif "application/octet-stream" in content_type:
            parsed = raw_body
        else:
            parsed = raw_body.decode("utf-8", errors="replace")
        return status, parsed, response_headers

    def unlock_cookie(self, pin):
        status, body, headers = self.request(
            "POST", "/api/unlock", {"pin": pin})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
        self.assertTrue(cookie)
        return cookie
