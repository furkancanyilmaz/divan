"""Lifecycle bridge between the Android activity and Divan's Python server."""

import importlib
import os
import threading

from java import jclass


_lock = threading.RLock()
_httpd = None
_thread = None
_token = ""
_server = None


def _keystore_get(key):
    store = jclass("com.furkancanyilmaz.divan.SecretStore")
    return str(store.get(str(key)) or "")


def _keystore_put(key, value):
    store = jclass("com.furkancanyilmaz.divan.SecretStore")
    store.put(str(key), str(value or ""))


def start_server(home_dir, requested_token):
    """Start once per Android process and return ``port|launch-token``."""
    global _httpd, _thread, _token, _server
    with _lock:
        if _httpd is not None and _thread is not None and _thread.is_alive():
            return "{}|{}".format(_httpd.server_address[1], _token)

        private_dir = os.path.abspath(str(home_dir))
        os.makedirs(private_dir, exist_ok=True)
        db_path = os.path.join(private_dir, "freud.db")
        os.environ["DIVAN_DB_PATH"] = db_path
        os.environ["DIVAN_SESSION_TOKEN"] = str(requested_token)

        _server = importlib.import_module("server")
        _server.DB_PATH = db_path
        _server.init_db()
        _server.configure_secret_store(
            _keystore_get, _keystore_put, migrate=True)

        _token = str(requested_token)
        _httpd = _server.create_server(
            host="127.0.0.1",
            port=0,
            db_path=db_path,
            session_token=_token,
        )
        _thread = threading.Thread(
            target=_httpd.serve_forever,
            daemon=True,
            name="divan-local-http",
        )
        _thread.start()
        return "{}|{}".format(_httpd.server_address[1], _token)


def active_job_state():
    """Return a compact state for Android's lifecycle keeper.

    This reads the durable queue directly instead of relying on WebView timers
    or a limited recent-jobs response. A provider which is temporarily absent
    is distinguished so Android can release its wake lock and retry with
    system backoff.
    """
    with _lock:
        server_module = _server
    if server_module is None:
        return "unavailable"
    connection = None
    try:
        connection = server_module.db()
        rows = connection.execute(
            "SELECT DISTINCT status FROM jobs WHERE status IN "
            "('queued','pending','running','processing','retrying',"
            "'waiting_provider')"
        ).fetchall()
    except Exception:
        return "unavailable"
    finally:
        if connection is not None:
            connection.close()
    statuses = {str(row["status"] or "") for row in rows}
    if statuses.intersection({
            "queued", "pending", "running", "processing", "retrying"}):
        return "active"
    if "waiting_provider" in statuses:
        return "waiting_provider"
    return "idle"


def stop_server():
    """Explicit shutdown hook for development and instrumentation tests."""
    global _httpd, _thread
    with _lock:
        if _httpd is not None:
            _httpd.shutdown()
            _httpd.server_close()
        _httpd = None
        _thread = None
