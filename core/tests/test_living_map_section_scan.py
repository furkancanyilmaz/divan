"""Yaşayan Harita bölüm taraması.

Değerler, Güçler ve Hedefler bölümleri boş kalıyordu: tarama promptu modele
`claim_type`'ın ne olabileceğini hiç söylemiyor, örnekte yalnız "pattern"
gösteriyordu. Buradaki testler hem türlerin öğretildiğini hem de bölüm
taramasının kendini çoğaltmadan, döngüye girmeden çalıştığını korur.
"""

from unittest import mock

from support import HTTPTestCase, app


class LivingMapSectionScanTests(HTTPTestCase):

    def prompt(self, **kwargs):
        messages = app._living_map_generation_messages(
            {"id": 1, "therapist": "freud"}, [], [], **kwargs)
        return messages[0]["content"]

    # --- Prompt modele türleri öğretiyor mu ---

    def test_prompt_lists_every_allowed_claim_type(self):
        text = self.prompt()
        for token in ("value", "need", "strength", "goal", "preference"):
            self.assertIn(token, text)
        # Harita yalnız sorunlardan oluşmaz.
        self.assertIn("yalnız sorunlardan oluşmaz", text)

    def test_prompt_does_not_pin_the_model_to_pattern_only(self):
        """Örnek şema tek türü dayatmamalı.

        Şema, kullanıcı mesajındaki OUTPUT_SCHEMA içinde taşınır.
        """
        messages = app._living_map_generation_messages(
            {"id": 1, "therapist": "freud"}, [], [])
        payload = messages[1]["content"]
        self.assertIn("pattern|value|need|strength|goal|preference", payload)

    def test_section_focus_reaches_the_prompt(self):
        text = self.prompt(scan_focus="strengths_exceptions")
        self.assertIn("Güçler ve istisnalar", text)
        self.assertIn("istisna", text.casefold())

    def test_focus_reorders_without_forbidding_other_types(self):
        """Odak sırayı değiştirir; kanıt neredeyse orada kalır."""
        text = self.prompt(scan_focus="values_needs")
        self.assertIn("Değerler ve ihtiyaçlar", text)
        self.assertIn("başka türden aday da üretebilirsin", text)

    def test_unknown_focus_is_ignored_in_the_prompt(self):
        text = self.prompt(scan_focus="uydurma_bolum")
        self.assertNotIn("Bu tarama", text)

    # --- Odak kataloğu ---

    def test_every_ui_section_has_a_scan_focus(self):
        for section in ("values_needs", "strengths_exceptions",
                        "goals_helpful", "cycles"):
            focus = app.living_map_scan_focus(section)
            self.assertIsNotNone(focus, section)
            self.assertTrue(focus["label"].strip(), section)
            self.assertTrue(focus["guidance"].strip(), section)
            self.assertTrue(focus["claim_types"], section)

    def test_focus_claim_types_are_real_living_map_types(self):
        for section, focus in app.LIVING_MAP_SCAN_FOCUS.items():
            for claim_type in focus["claim_types"]:
                self.assertIn(
                    claim_type, app.LIVING_MAP_CLAIM_TYPES, section)

    def test_unknown_focus_id_returns_none(self):
        self.assertIsNone(app.living_map_scan_focus("uydurma"))
        self.assertIsNone(app.living_map_scan_focus(""))

    # --- Döngüye girmeme ---

    def test_second_scan_does_not_open_a_competing_job(self):
        """Arka arkaya basmak ikinci bir tarama işi açmamalı."""
        first_id, first_created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro", "values_needs")
        self.assertTrue(first_created)
        second_id, second_created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro", "strengths_exceptions")
        self.assertFalse(second_created)
        self.assertEqual(first_id, second_id)

    def test_job_remembers_its_focus_across_queue_hops(self):
        """İş kuyruğa her dönüşünde aynı odakla sürmeli."""
        job_id, created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro", "goals_helpful")
        self.assertTrue(created)
        with app.db() as connection:
            row = connection.execute(
                "SELECT scan_focus FROM jobs WHERE id=?",
                (job_id,)).fetchone()
        self.assertEqual(row["scan_focus"], "goals_helpful")

    def test_scan_without_focus_keeps_the_previous_behaviour(self):
        job_id, created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro")
        self.assertTrue(created)
        with app.db() as connection:
            row = connection.execute(
                "SELECT scan_focus FROM jobs WHERE id=?",
                (job_id,)).fetchone()
        self.assertEqual(row["scan_focus"], "")

    def test_endpoint_rejects_an_invented_section(self):
        status, body, _ = self.request(
            "POST", "/api/living-map/backfill", {
                "consent": True, "provider_id": "deepseek",
                "model_id": "deepseek-v4-pro", "focus": "uydurma_bolum",
            })
        self.assertEqual(status, 400, body)

    def test_endpoint_still_requires_explicit_consent(self):
        status, body, _ = self.request(
            "POST", "/api/living-map/backfill", {
                "consent": False, "provider_id": "deepseek",
                "model_id": "deepseek-v4-pro", "focus": "values_needs",
            })
        self.assertEqual(status, 400, body)

    # --- Yarıda kalan tarama kaldığı yerden sürer ---

    def test_stalled_scan_is_resumed_not_restarted(self):
        """Başarısız tarama yeni iş açmaz; aynı iş sürdürülür.

        Aksi hâlde her düğmeye basışta sıfırdan başlanır ve kullanıcı
        "bir şeyler ters gitti" ekranından hiç çıkamaz.
        """
        job_id, created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro", "values_needs")
        self.assertTrue(created)
        with app.db() as connection:
            connection.execute(
                "UPDATE jobs SET status='failed',error_code='provider_error' "
                "WHERE id=?", (job_id,))

        status, body, _ = self.request(
            "POST", "/api/living-map/backfill", {
                "consent": True, "provider_id": "deepseek",
                "model_id": "deepseek-v4-pro", "focus": "values_needs",
            })
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("resumed"), body)
        self.assertEqual(body["job_id"], job_id)
        # Yeni bir iş açılmamalı.
        with app.db() as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE kind=?",
                (app.LIVING_MAP_BACKFILL_JOB_KIND,)).fetchone()["n"]
        self.assertEqual(total, 1)

    def test_resuming_can_switch_the_section_focus(self):
        """Sürdürürken başka bölüm seçilebilir; ilerleme korunur."""
        job_id, _ = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro", "values_needs")
        with app.db() as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted' WHERE id=?", (job_id,))
        status, body, _ = self.request(
            "POST", "/api/living-map/backfill", {
                "consent": True, "provider_id": "deepseek",
                "model_id": "deepseek-v4-pro",
                "focus": "strengths_exceptions",
            })
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("resumed"))
        with app.db() as connection:
            row = connection.execute(
                "SELECT scan_focus,status FROM jobs WHERE id=?",
                (job_id,)).fetchone()
        self.assertEqual(row["scan_focus"], "strengths_exceptions")
        self.assertIn(row["status"], ("queued", "running"))

    def test_a_running_scan_is_never_duplicated_by_resume(self):
        """Süren tarama varken sürdürme ikinci bir iş açmamalı."""
        job_id, created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro")
        self.assertTrue(created)
        status, body, _ = self.request(
            "POST", "/api/living-map/backfill", {
                "consent": True, "provider_id": "deepseek",
                "model_id": "deepseek-v4-pro",
            })
        self.assertEqual(status, 200, body)
        self.assertFalse(body.get("resumed"))
        self.assertEqual(body["job_id"], job_id)

    # --- A1: geçici hata kalıcı başarısızlık değildir ---

    def test_transient_provider_error_is_retried_not_failed(self):
        """Zaman aşımı/hız sınırı taramayı öldürmemeli.

        Otomatik tarama bu ayrımı zaten yapıyordu; geçmiş taraması her
        hatayı kalıcı sayıp kullanıcıyı hata ekranında bırakıyordu.
        """
        job_id, _ = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro")

        def patlat(*args, **kwargs):
            raise app.ProviderError("provider_timeout", "zaman aşımı")

        with mock.patch.object(app, "claim_postprocess_provider_snapshot",
                               side_effect=patlat):
            app.run_living_map_backfill_job(job_id)

        with app.db() as connection:
            row = connection.execute(
                "SELECT status,scan_attempt,error_code FROM jobs WHERE id=?",
                (job_id,)).fetchone()
        self.assertEqual(row["status"], "queued", dict(row))
        self.assertEqual(row["scan_attempt"], 1)
        self.assertEqual(row["error_code"], "provider_timeout")

    def test_permanent_error_still_fails(self):
        """Kalıcı hata (geçersiz anahtar) yeniden denenmemeli."""
        job_id, _ = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro")

        def patlat(*args, **kwargs):
            raise app.ProviderError("missing_api_key", "anahtar yok")

        with mock.patch.object(app, "claim_postprocess_provider_snapshot",
                               side_effect=patlat):
            app.run_living_map_backfill_job(job_id)

        with app.db() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "failed")

    def test_retries_are_bounded(self):
        """Sonsuz yeniden deneme olmamalı; sayaç dolunca durur."""
        job_id, _ = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro")
        app._living_map_backfill_record_attempt(
            job_id, app.LIVING_MAP_BACKFILL_MAX_ATTEMPTS)

        def patlat(*args, **kwargs):
            raise app.ProviderError("provider_timeout", "zaman aşımı")

        with mock.patch.object(app, "claim_postprocess_provider_snapshot",
                               side_effect=patlat):
            app.run_living_map_backfill_job(job_id)

        with app.db() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["status"], "failed")

    def test_manual_resume_clears_the_attempt_budget(self):
        """Elle sürdürme temiz bir şansla başlamalı."""
        job_id, _ = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro")
        app._living_map_backfill_record_attempt(job_id, 3)
        with app.db() as connection:
            connection.execute(
                "UPDATE jobs SET status='failed' WHERE id=?", (job_id,))
        app.retry_living_map_backfill_job(job_id)
        self.assertEqual(app._living_map_backfill_attempt(job_id), 0)

    def test_active_scan_focus_reaches_the_interface(self):
        """Arayüz hangi bölümün taranmakta olduğunu görebilmeli.

        Bu bilgi olmadan "Güçler" taranırken "Değerler" düğmesinin de
        kilitlenmesi bozuk görünüyordu.
        """
        job_id, created = app.create_living_map_backfill_job(
            "deepseek", "deepseek-v4-pro", "strengths_exceptions")
        self.assertTrue(created)
        status = app.living_map_analysis_status()
        self.assertEqual(status["job"]["id"], job_id)
        self.assertEqual(
            status["job"]["scan_focus"], "strengths_exceptions")
