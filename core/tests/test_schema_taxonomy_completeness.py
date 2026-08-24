"""Young taksonomisinin eksiksizliği.

Katalog bir *tanı listesi değildir*; kavramları ortak bir dille adlandırmak
ve modelin katalog dışına çıkıp klinik görünümlü etiket uydurmasını
engellemek içindir. Bu testler taksonominin sessizce daralmasını önler.
"""

from support import HTTPTestCase, app


class SchemaTaxonomyCompletenessTests(HTTPTestCase):

    def test_five_schema_domains_are_present(self):
        labels = [row["label"] for row in app.SCHEMA_DOMAINS]
        self.assertEqual(len(labels), 5)
        for expected in (
                "Ayrılma ve Reddedilme",
                "Zedelenmiş Özerklik ve Performans",
                "Zedelenmiş Sınırlar",
                "Diğerleri Yönelimlilik",
                "Aşırı Tetikte Olma ve Baskılama"):
            self.assertIn(expected, labels)

    def test_all_eighteen_schemas_are_present_and_mapped_to_a_domain(self):
        rows = app.schema_definition_rows()
        self.assertEqual(len(rows), 18)
        domain_ids = {row["id"] for row in app.SCHEMA_DOMAINS}
        for row in rows:
            self.assertIn(row["domain_id"], domain_ids, row["schema_id"])
            # Her şema tanınma ipucu taşımalı: etiket tek başına yetmez.
            self.assertTrue(row["recognize"].strip(), row["schema_id"])
            self.assertTrue(row["domain_label"].strip(), row["schema_id"])

    def test_each_domain_carries_its_unmet_need(self):
        """Şema alanı, altındaki karşılanmamış ihtiyaçla birlikte anlaşılır."""
        for row in app.SCHEMA_DOMAINS:
            self.assertTrue(row["need"].strip(), row["id"])

    def test_every_mode_family_is_represented(self):
        groups = {row["group"] for row in app.SCHEMA_STRATEGY_LIBRARY}
        for expected in ("Çocuk modları", "Eleştirel ebeveyn modları",
                         "Başa çıkma modları", "Sağlıklı modlar"):
            self.assertIn(expected, groups)

    def test_three_coping_styles_map_only_to_real_modes(self):
        styles = {row["id"] for row in app.SCHEMA_COPING_STYLES}
        self.assertEqual(
            styles, {"surrender", "avoidance", "overcompensation"})
        known = {row["id"] for row in app.SCHEMA_STRATEGY_LIBRARY}
        for style in app.SCHEMA_COPING_STYLES:
            self.assertTrue(style["modes"], style["id"])
            for mode_id in style["modes"]:
                self.assertIn(mode_id, known, style["id"])

    def test_mode_records_are_clinically_complete(self):
        """Her mod tanıma, anlama, soru, adım ve sınır bilgisi taşımalı."""
        required = (
            "label", "group", "chair_label", "recognize", "understand",
            "question", "healthy_adult_bridge", "real_world_bridge", "avoid")
        for row in app.SCHEMA_STRATEGY_LIBRARY:
            for field in required:
                self.assertTrue(
                    str(row.get(field) or "").strip(),
                    "{} -> {}".format(row["id"], field))
            self.assertTrue(row["steps"], row["id"])
            self.assertTrue(row["stage_ids"], row["id"])

    def test_healthy_modes_are_resources_not_work_targets(self):
        """Sağlıklı Yetişkin ve Mutlu Çocuk odak olarak sunulmaz."""
        offerable = app.schema_focus_offerable_modes()
        self.assertNotIn("healthy_adult", offerable)
        self.assertNotIn("happy_child", offerable)
        # Sağlıklı modlar yine de katalogda durur: güçlendirilecek kaynaktır.
        known = {row["id"] for row in app.SCHEMA_STRATEGY_LIBRARY}
        self.assertIn("healthy_adult", known)
        self.assertIn("happy_child", known)

    def test_coping_modes_declare_their_style(self):
        """Başa çıkma modları hangi tarza ait olduğunu bildirmeli."""
        for mode_id in ("detached_protector", "compliant_surrender",
                        "perfectionistic_overcontroller"):
            card = app.schema_focus_candidate_card(mode_id)
            self.assertIn(
                card["coping_style"],
                ("surrender", "avoidance", "overcompensation"), mode_id)

    def test_model_is_offered_every_schema_not_just_four(self):
        """Model 18 şemanın hepsini adlandırabilmeli.

        Katalog 4 şemayla sınırlıyken model kalanları adlandıramıyor ve
        en yakın etikete zorlanıyordu; yanlış etiketlerin kaynağı buydu.
        """
        catalog = app.SCHEMA_CANDIDATE_CATALOG
        self.assertEqual(len(catalog), 18)
        labels = set(catalog.values())
        for expected in ("Duygusal Yoksunluk", "Güvensizlik / Kötüye Kullanılma",
                         "Başarısızlık", "Kendini Feda",
                         "Karamsarlık / Olumsuzluk", "Cezalandırıcılık"):
            self.assertIn(expected, labels)

    def test_legacy_schema_keys_are_never_renamed(self):
        """Eski anahtarlar kalıcıdır: kayıtlar ve eşitleme onlara bağlı."""
        for key in ("schema_abandonment", "schema_defectiveness",
                    "schema_subjugation", "unrelenting_standards"):
            self.assertIn(key, app.SCHEMA_CANDIDATE_CATALOG, key)

    def test_no_schema_is_offered_twice_under_two_keys(self):
        """Aynı şema iki kimlikle sunulmamalı; model onları ayrı sanar."""
        labels = list(app.SCHEMA_CANDIDATE_CATALOG.values())
        self.assertEqual(len(labels), len(set(labels)))
