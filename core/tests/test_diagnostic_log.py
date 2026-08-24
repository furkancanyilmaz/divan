"""Tanı günlüğü: Android'de görünmeyen hataları okunur kılar.

`print()` çıktısı Android'de hiçbir yere ulaşmıyordu; bir iş düştüğünde
sebebini görmek imkânsızdı. Bu günlük kalıcıdır ve arayüzden okunur.

MAHREMİYET SINIRI: günlüğe yalnız teknik ayrıntı girer — kullanıcı
mesajı, usta yanıtı veya sağlayıcı anahtarı ASLA.
"""

from support import HTTPTestCase, app


class DiagnosticLogTests(HTTPTestCase):
    def test_failed_job_is_logged_automatically(self):
        conv = self.conversation(therapist="young")
        with app.db() as connection:
            job = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('living_map_autoscan',?,'running','t','t')",
                (conv,)).lastrowid
        app.update_job(job, "failed", "Tarama tamamlanamadı", None,
                       "missing_api_key")
        with app.db() as connection:
            row = connection.execute(
                "SELECT source,code,conv FROM diagnostic_log "
                "ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["source"], "living_map_autoscan")
        self.assertEqual(row["code"], "missing_api_key")
        self.assertEqual(row["conv"], conv)

    def test_successful_job_is_not_logged(self):
        conv = self.conversation(therapist="young")
        with app.db() as connection:
            job = connection.execute(
                "INSERT INTO jobs(kind,conv,status,created,updated) "
                "VALUES('living_map_autoscan',?,'running','t','t')",
                (conv,)).lastrowid
        app.update_job(job, "succeeded", "tamamlandı", 100, None)
        with app.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM diagnostic_log").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_api_keys_are_redacted(self):
        app.log_diagnostic("test", "key", "anahtar sk-proj-ABCD12345678 var")
        app.log_diagnostic("test", "auth", "Bearer gizli-token-12345")
        with app.db() as connection:
            rows = [r["detail"] for r in connection.execute(
                "SELECT detail FROM diagnostic_log ORDER BY id")]
        for detail in rows:
            self.assertIn("[gizlendi]", detail)
        self.assertNotIn("sk-proj-ABCD12345678", " ".join(rows))
        self.assertNotIn("gizli-token-12345", " ".join(rows))

    def test_logging_never_raises(self):
        # Günlük tutmak asıl işi bozmamalı.
        app.log_diagnostic(None, None, None)
        app.log_diagnostic("x" * 500, "y" * 500, "z" * 5000, conv="bozuk")

    def test_log_is_capped(self):
        for index in range(app.DIAGNOSTIC_LOG_LIMIT + 25):
            app.log_diagnostic("test", "kod", "kayıt {}".format(index))
        with app.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM diagnostic_log").fetchone()["n"]
        self.assertLessEqual(count, app.DIAGNOSTIC_LOG_LIMIT + 1)

    def test_endpoint_returns_entries(self):
        app.log_diagnostic("test", "ornek", "ayrıntı")
        status, payload, _ = self.request("GET", "/api/diagnostic-log")
        self.assertEqual(status, 200)
        self.assertTrue(payload["entries"])
        self.assertEqual(payload["entries"][0]["code"], "ornek")

    def test_clear_endpoint_empties_the_log(self):
        app.log_diagnostic("test", "ornek", "ayrıntı")
        status, payload, _ = self.request(
            "POST", "/api/diagnostic-log/clear", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        with app.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM diagnostic_log").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_client_toast_errors_are_recorded(self):
        """Ekranda görünen 'bir şey ters gitti' uyarısı iz bırakmalı."""
        status, payload, _ = self.request(
            "POST", "/api/diagnostic-log/client",
            {"detail": "Yaşayan Harita taraması başarısız: zaman aşımı"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        with app.db() as connection:
            row = connection.execute(
                "SELECT source,code,detail FROM diagnostic_log "
                "ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["source"], "arayüz")
        self.assertIn("zaman aşımı", row["detail"])

    def test_client_endpoint_tolerates_empty_body(self):
        status, payload, _ = self.request(
            "POST", "/api/diagnostic-log/client", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_failed_requests_record_which_endpoint_broke(self):
        """Hangi isteğin düştüğü günlüğe yazılmalı.

        Yalnız genel 'bir şey ters gitti' uyarısı vardı; sebebi
        bulmak için istek yolu ve durum kodu gerekiyor.
        """
        html = open("index.html", encoding="utf-8").read()
        self.assertIn("function apiHatasiniKaydet(", html)
        # Üç kırılma yolu da kaydedilir.
        self.assertIn("apiHatasiniKaydet(path,'ulasilamadi'", html)
        self.assertIn("apiHatasiniKaydet(path,'bozuk_yanit'", html)
        self.assertIn("apiHatasiniKaydet(path,'http_'+r.status", html)
        # Sorgu dizesi atılır: kullanıcı içeriği günlüğe girmesin.
        self.assertIn("String(path||'').split('?')[0]", html)
