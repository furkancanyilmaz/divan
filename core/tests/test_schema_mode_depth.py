"""Şema mod çalışmasının derinliği.

Köken (ilk beliriş), yaş yaş büyütme, Sağlıklı Yetişkin kanıtı ve
sandalyeye taşınan odak. Buradaki testler klinik sınırları korur:
sahte anı yasağı, tanı yasağı ve "seçim kullanıcıda" kuralı.
"""

from support import app
from test_schema_path import SchemaPathTests


class SchemaModeDepthTests(SchemaPathTests):

    def path_in_work(self):
        """Odak seçilmiş, çalışma aşamasında bir yol kur."""
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Mesaj gelmeyince içim daraldı"),
                ("need", "Güvende hissetmek"))):
            self.assertEqual(self.post({
                "action": "record", "conv_id": self.conv, "path_id": path_id,
                "kind": kind, "value": value,
                "request_id": "depth-record-{:04d}".format(index),
            })[0], 200)
        self.assertEqual(self.to_method(path_id, "depth-0001")[0], 200)
        self.assertEqual(self.post({
            "action": "choose_method", "conv_id": self.conv,
            "path_id": path_id,
            "method_id": "young:method:empathic-confrontation",
            "confirmed": True, "request_id": "depth-method-0001",
        })[0], 200)
        return path_id

    def path_in_focus_chosen(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        for index, (kind, value) in enumerate((
                ("current_trigger", "Bugünkü olay"), ("need", "Korunmak"))):
            self.assertEqual(self.post({
                "action": "record", "conv_id": self.conv, "path_id": path_id,
                "kind": kind, "value": value,
                "request_id": "focus-only-{:04d}".format(index),
            })[0], 200)
        self.assertEqual(self.post({
            "action": "advance", "conv_id": self.conv, "path_id": path_id,
            "to_phase": "focus", "request_id": "focus-only-adv",
        })[0], 200)
        self.assertEqual(self.post({
            "action": "offer_focus", "conv_id": self.conv, "path_id": path_id,
            "candidates": [{"mode_key": "detached_protector"}],
            "request_id": "focus-only-offer",
        })[0], 200)
        self.assertEqual(self.post({
            "action": "choose_focus", "conv_id": self.conv,
            "path_id": path_id, "mode_key": "detached_protector",
            "request_id": "focus-only-choose",
        })[0], 200)
        return path_id

    # --- Köken: sahte anı yasağı ---

    def test_origin_records_only_what_the_user_reported(self):
        path_id = self.path_in_focus_chosen()
        status, body = self.post({
            "action": "record_origin", "conv_id": self.conv,
            "path_id": path_id, "confidence": "reported",
            "age": 7, "scene": "Okulda kimse yanıma oturmadı",
            "unmet_need": "Görülmek",
            "request_id": "depth-origin-0001",
        })
        self.assertEqual(status, 200, body)
        origin = body["origin"]
        self.assertTrue(origin["recorded"])
        self.assertEqual(origin["age"], 7)
        self.assertEqual(origin["confidence"], "reported")

    def test_unknown_origin_is_a_complete_answer(self):
        """Kullanıcı hatırlamıyorsa çalışma yaşsız yürür."""
        path_id = self.path_in_focus_chosen()
        status, body = self.post({
            "action": "record_origin", "conv_id": self.conv,
            "path_id": path_id, "confidence": "unknown",
            "age": 7, "scene": "model bunu uydurdu",
            "request_id": "origin-unknown-0001",
        })
        self.assertEqual(status, 200, body)
        # "Bilmiyorum" seçildiğinde yaş saklanmaz.
        self.assertIsNone(body["origin"]["age"])

    def test_origin_cannot_be_authored_by_the_model(self):
        """Sahte anı yasağı: köken yalnız kullanıcının anlatımından."""
        path_id = self.path_in_focus_chosen()
        status, body = self.post({
            "action": "record_origin", "conv_id": self.conv,
            "path_id": path_id, "confidence": "reported", "age": 6,
            "authored_by": "model",
            "request_id": "origin-model-0001",
        })
        self.assertEqual(status, 409, body)

    def test_origin_requires_a_chosen_mode(self):
        self.completed_turns(3)
        claim = self.candidate(status="confirmed")
        path_id = self.legacy_start_fixture(claim)[1]["active_path"]["id"]
        status, body = self.post({
            "action": "record_origin", "conv_id": self.conv,
            "path_id": path_id, "confidence": "reported",
            "request_id": "origin-nofocus-0001",
        })
        self.assertNotEqual(status, 200, body)

    def test_impossible_ages_are_rejected(self):
        path_id = self.path_in_focus_chosen()
        for age in (-1, 200):
            status, _ = self.post({
                "action": "record_origin", "conv_id": self.conv,
                "path_id": path_id, "confidence": "reported", "age": age,
                "request_id": "origin-bad-{}".format(age + 500),
            })
            self.assertEqual(status, 400)

    # --- Yaş yaş büyütme ---

    def test_growth_stage_compares_then_and_now(self):
        path_id = self.path_in_work()
        status, body = self.post({
            "action": "add_growth_stage", "conv_id": self.conv,
            "path_id": path_id, "age": 7, "request_id": "growth-add-0001",
        })
        self.assertEqual(status, 200, body)
        stage_id = body["growth"]["stages"][0]["id"]
        # Tek yanı dolu basamak karşılaştırılabilir sayılmaz.
        status, body = self.post({
            "action": "record_growth", "conv_id": self.conv,
            "path_id": path_id, "stage_id": stage_id,
            "then_response": "Sessizce odama giderdim",
            "request_id": "growth-then-0001",
        })
        self.assertEqual(status, 200, body)
        self.assertFalse(body["growth"]["stages"][0]["comparable"])
        status, body = self.post({
            "action": "record_growth", "conv_id": self.conv,
            "path_id": path_id, "stage_id": stage_id,
            "now_response": "Bu sefer ne olduğunu sordum",
            "request_id": "growth-now-0001",
        })
        self.assertEqual(status, 200, body)
        self.assertTrue(body["growth"]["stages"][0]["comparable"])
        self.assertEqual(body["growth"]["comparable_count"], 1)

    def test_growth_stages_are_bounded(self):
        path_id = self.path_in_work()
        for index in range(app.SCHEMA_GROWTH_MAX_STAGES):
            self.assertEqual(self.post({
                "action": "add_growth_stage", "conv_id": self.conv,
                "path_id": path_id, "age": 6 + index,
                "request_id": "growth-cap-{:04d}".format(index),
            })[0], 200)
        status, _ = self.post({
            "action": "add_growth_stage", "conv_id": self.conv,
            "path_id": path_id, "age": 40,
            "request_id": "growth-cap-over",
        })
        self.assertEqual(status, 409)

    # --- Sağlıklı Yetişkin ---

    def test_healthy_adult_marks_are_evidence_not_a_score(self):
        path_id = self.path_in_work()
        status, body = self.post({
            "action": "mark_healthy_adult", "conv_id": self.conv,
            "path_id": path_id, "evidence": "Bu sefer hayır dedim",
            "request_id": "depth-healthy-0001",
        })
        self.assertEqual(status, 200, body)
        healthy = body["healthy_adult"]
        self.assertEqual(healthy["count"], 1)
        self.assertEqual(
            healthy["recent"][0]["evidence"], "Bu sefer hayır dedim")
        # Kanıt kullanıcının kendi cümlesidir: boş geçilemez.
        self.assertEqual(self.post({
            "action": "mark_healthy_adult", "conv_id": self.conv,
            "path_id": path_id, "evidence": "   ",
            "request_id": "depth-healthy-empty-01",
        })[0], 400)

    # --- Sandalyeye taşınan odak ---

    def test_chair_context_names_the_chosen_mode(self):
        path_id = self.path_in_focus_chosen()
        with app.db() as connection:
            context = app.schema_chair_focus_context(connection, self.conv)
        self.assertIn("Kopuk Korungan", context)
        self.assertIn("çalışmayı seçtiği mod", context)

    def test_chair_context_forbids_inventing_an_origin(self):
        """Köken anlatılmadıysa usta yaş uydurmamaya açıkça bağlanır."""
        path_id = self.path_in_focus_chosen()
        with app.db() as connection:
            context = app.schema_chair_focus_context(connection, self.conv)
        self.assertIn("UYDURMA", context)

    def test_chair_context_carries_the_reported_origin(self):
        path_id = self.path_in_focus_chosen()
        self.assertEqual(self.post({
            "action": "record_origin", "conv_id": self.conv,
            "path_id": path_id, "confidence": "reported", "age": 9,
            "scene": "Kimse sormadı", "unmet_need": "Fark edilmek",
            "request_id": "origin-chair-0001",
        })[0], 200)
        with app.db() as connection:
            context = app.schema_chair_focus_context(connection, self.conv)
        self.assertIn("yaş 9", context)
        self.assertIn("Kimse sormadı", context)
        self.assertIn("uydurma", context.casefold())

    def test_coping_chair_is_labelled_with_the_chosen_mode(self):
        """Sandalyeler otomatik kurulur; başa çıkma sandalyesi seçili modun
        adını taşır, kullanıcıdan mod doldurması istenmez."""
        self.path_in_focus_chosen()
        with app.db() as connection:
            label = app.schema_chosen_mode_label(connection, self.conv)
        self.assertEqual(label, "Kopuk Korungan / Kaçınan")
