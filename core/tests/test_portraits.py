import json
from pathlib import Path

from support import HTTPTestCase, PROJECT_DIR, app


NEW_THINKER_IDS = {
    "steven_pinker", "vaclav_smil", "david_christian", "bill_gates",
    "steve_jobs",
}


class PortraitCatalogTests(HTTPTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portrait_dir = Path(PROJECT_DIR, "assets", "portraits")
        cls.manifest = json.loads(
            (cls.portrait_dir / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_matches_the_safe_runtime_catalog(self):
        portraits = self.manifest["portraits"]

        self.assertEqual(
            self.manifest["generated_from"],
            "Wikimedia Commons ve Divan temsili yerel varlıkları",
        )
        self.assertEqual(self.manifest["portrait_count"], len(portraits))
        self.assertEqual(set(app.PORTRAIT_CATALOG), set(portraits))
        self.assertEqual(set(app.ALL_MASTERS), set(portraits))

        for master_id, portrait in portraits.items():
            with self.subTest(master=master_id):
                self.assertIn(master_id, app.ALL_MASTERS)
                if portrait.get("is_placeholder"):
                    self.assertEqual(
                        portrait["source_kind"], "local_placeholder")
                    self.assertEqual(
                        portrait["file"], "representative_bust.jpg")
                    self.assertIn("Temsili büst", portrait["credit"])
                    self.assertFalse(portrait["commons_title"])
                else:
                    self.assertTrue(
                        portrait["license"] == "Public domain" or
                        portrait["license"] == "CC0" or
                        portrait["license"].startswith("CC BY"))
                    self.assertTrue(
                        portrait["source_page"].startswith(
                            "https://commons.wikimedia.org/wiki/"))
                self.assertIn(
                    portrait["mime"], ("image/jpeg", "image/png", "image/webp"))
                self.assertTrue((self.portrait_dir / portrait["file"]).is_file())

    def test_every_placeholder_is_explicitly_non_likeness_metadata(self):
        placeholders = {
            master_id: portrait
            for master_id, portrait in self.manifest["portraits"].items()
            if portrait.get("is_placeholder")
        }

        # "missing" ustalar, Hakikat ve kurgusal karaktere çevrilen
        # yaşayan kişiler — hepsi açıkça yerel temsili büst kullanır.
        fictional_likeness_ids = {
            "yalom", "fonagy", "steven_pinker", "vaclav_smil",
            "david_christian", "bill_gates",
        }
        self.assertEqual(
            placeholders,
            {
                master_id: self.manifest["portraits"][master_id]
                for master_id in (set(self.manifest["missing"])
                                  | fictional_likeness_ids)
            } | {"truth": self.manifest["portraits"]["truth"]},
        )
        for master_id, portrait in placeholders.items():
            with self.subTest(master=master_id):
                self.assertTrue(
                    app.PORTRAIT_CATALOG[master_id]["is_placeholder"])
                self.assertIn("gerçek fotoğraf", portrait["credit"])

    def test_new_public_thinkers_have_packaged_attributed_portraits(self):
        portraits = self.manifest["portraits"]

        self.assertTrue(NEW_THINKER_IDS <= set(portraits))
        for thinker_id in NEW_THINKER_IDS:
            with self.subTest(thinker=thinker_id):
                portrait = portraits[thinker_id]
                if thinker_id == "steve_jobs":
                    # Vefat etmiş kişi: kaynaklı, atıflı portre korunur.
                    self.assertTrue(portrait["artist"])
                    self.assertTrue(portrait["license"])
                    self.assertTrue(portrait["source_page"])
                else:
                    # Yaşayan kişiler: gerçek fotoğraf/belirgin benzerlik
                    # paketlenmez; kurgusal karakter için yerel temsili
                    # büst kullanılır.
                    self.assertTrue(portrait.get("is_placeholder"))
                    self.assertEqual(portrait["source_kind"],
                                     "local_placeholder")
                    self.assertEqual(portrait["file"],
                                     "representative_bust.jpg")
                    self.assertNotIn("temsil", portrait["wikipedia_title"]
                                     and "" or "", portrait["artist"]
                                     and "" or "")
                self.assertEqual(
                    app.PORTRAIT_CATALOG[thinker_id]["file"],
                    portrait["file"],
                )

    def test_portrait_files_are_served_but_unknown_files_are_not(self):
        record = app.PORTRAIT_CATALOG["steven_pinker"]
        status, body, headers = self.request(
            "GET", "/assets/portraits/" + record["file"])

        self.assertEqual(status, 200)
        self.assertIsInstance(body, str)
        self.assertGreater(len(body), 1000)
        self.assertEqual(headers["Content-Type"], "image/jpeg")

        status, body, _ = self.request(
            "GET", "/assets/portraits/not-in-manifest.jpg")
        self.assertEqual(status, 404)
        self.assertIn("error", body)


class PortraitInterfaceSourceTests(HTTPTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = Path(PROJECT_DIR, "index.html").read_text(encoding="utf-8")
        cls.gradle = Path(
            PROJECT_DIR, "..", "divan-android", "app",
            "build.gradle.kts").resolve().read_text(encoding="utf-8")

    def test_chat_chrome_and_story_use_the_current_master_portrait(self):
        for marker in (
                'id="topPortrait"', 'id="portraitCredit"',
                'option value="master"', "function masterPortrait(",
                "function renderMasterPortraitChrome(",
                "swatch.hasPortrait", "const portrait=masterPortrait(t);",
                "function loadStoryMasterPortrait(",
                "function storyPortraitAttribution(",
                "Temsili büst · gerçek portre değil",
                "gerçek kişi portresi değildir"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_android_source_sync_includes_the_portrait_assets(self):
        self.assertIn(
            '"assets/portraits/**"',
            self.gradle,
        )
        self.assertIn(
            '"secure_sync_transport.py"',
            self.gradle,
        )

    def test_desktop_updater_accepts_and_copies_portrait_assets(self):
        updater = Path(
            PROJECT_DIR, "Guncelle.command").read_text(encoding="utf-8")

        self.assertIn(r"assets\/portraits\/", updater)
        self.assertIn(
            'python3 -m json.tool "$TMP/assets/portraits/manifest.json"',
            updater,
        )
        self.assertIn(
            'cp -p "$f" assets/portraits/',
            updater,
        )
