import multiprocessing
import os
import tempfile
import time
import unittest


def _host_process(database_path, output):
    import server as host_app
    import sync_service as host_sync

    try:
        host_app.DB_PATH = database_path
        host_app.init_db()
        with host_app.db() as connection:
            conv_id = connection.execute(
                "INSERT INTO conversations("
                "mode,therapist,title,created,updated,ended) "
                "VALUES(?,?,?,?,?,?)",
                (
                    "terapi", "ferenczi", "Bilgisayar kaydı",
                    "2026-07-30 09:00", "2026-07-30 09:00", 1,
                ),
            ).lastrowid
            connection.execute(
                "INSERT INTO messages(conv,role,content,created) "
                "VALUES(?,?,?,?)",
                (
                    conv_id, "user", "Bilgisayar mesajı",
                    "2026-07-30 09:01",
                ),
            )
            connection.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                ("openai_api_key", "host-secret"),
            )
        invitation = host_sync.start_host(
            advertised_host="127.0.0.1", ttl_seconds=30)
        output.put(("invitation", invitation["pairing_code"]))
        deadline = time.monotonic() + 20
        while (host_sync.status()["host_running"] and
               time.monotonic() < deadline):
            time.sleep(0.05)
        with host_app.db() as connection:
            titles = [
                row[0] for row in connection.execute(
                    "SELECT title FROM conversations ORDER BY title")]
            messages = [
                row[0] for row in connection.execute(
                    "SELECT content FROM messages ORDER BY content")]
            secret = connection.execute(
                "SELECT value FROM settings WHERE key='openai_api_key'"
            ).fetchone()[0]
        host_sync.shutdown()
        output.put(("result", {
            "titles": titles, "messages": messages, "secret": secret,
        }))
    except Exception as error:
        output.put(("error", "{}: {}".format(
            type(error).__name__, str(error))))


class DeviceSyncEndToEndTests(unittest.TestCase):
    def test_two_processes_merge_over_the_real_pinned_tls_channel(self):
        import server as client_app
        import sync_service as client_sync

        old_path = client_app.DB_PATH
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            host_path = os.path.join(directory, "host.db")
            client_path = os.path.join(directory, "client.db")
            output = context.Queue()
            process = context.Process(
                target=_host_process, args=(host_path, output))
            process.start()
            try:
                kind, value = output.get(timeout=20)
                self.assertEqual(kind, "invitation", value)

                client_app.DB_PATH = client_path
                client_app.init_db()
                with client_app.db() as connection:
                    conv_id = connection.execute(
                        "INSERT INTO conversations("
                        "mode,therapist,title,created,updated,ended) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            "terapi", "young", "Telefon kaydı",
                            "2026-07-30 10:00", "2026-07-30 10:00", 1,
                        ),
                    ).lastrowid
                    connection.execute(
                        "INSERT INTO messages("
                        "conv,role,content,created) VALUES(?,?,?,?)",
                        (
                            conv_id, "user", "Telefon mesajı",
                            "2026-07-30 10:01",
                        ),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO settings(key,value) "
                        "VALUES(?,?)",
                        ("openai_api_key", "client-secret"),
                    )

                summary = client_sync.join(
                    value, device_name="Test telefonu",
                    platform_name="android")
                self.assertTrue(summary["ok"])

                kind, host_result = output.get(timeout=20)
                self.assertEqual(kind, "result", host_result)
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)

                with client_app.db() as connection:
                    client_titles = [
                        row[0] for row in connection.execute(
                            "SELECT title FROM conversations ORDER BY title")]
                    client_messages = [
                        row[0] for row in connection.execute(
                            "SELECT content FROM messages ORDER BY content")]
                    client_secret = connection.execute(
                        "SELECT value FROM settings "
                        "WHERE key='openai_api_key'").fetchone()[0]

                expected_titles = ["Bilgisayar kaydı", "Telefon kaydı"]
                expected_messages = [
                    "Bilgisayar mesajı", "Telefon mesajı"]
                self.assertEqual(client_titles, expected_titles)
                self.assertEqual(host_result["titles"], expected_titles)
                self.assertEqual(client_messages, expected_messages)
                self.assertEqual(
                    host_result["messages"], expected_messages)
                self.assertEqual(client_secret, "client-secret")
                self.assertEqual(host_result["secret"], "host-secret")
            finally:
                client_sync.shutdown()
                client_app.DB_PATH = old_path
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
