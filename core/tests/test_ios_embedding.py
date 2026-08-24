from pathlib import Path
import hashlib
import unittest

from support import PROJECT_DIR


class IOSLaunchContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ios_root = Path(PROJECT_DIR).parent / "divan-ios"
        cls.runtime = (
            cls.ios_root / "Divan/Runtime/DivanEmbeddedPythonRuntime.m"
        ).read_text(encoding="utf-8")
        cls.server = Path(PROJECT_DIR, "server.py").read_text(
            encoding="utf-8")
        cls.bundler = (
            cls.ios_root / "Scripts/prepare_python_bundle.sh"
        ).read_text(encoding="utf-8")
        cls.verifier = (
            cls.ios_root / "Scripts/verify_bundle.sh"
        ).read_text(encoding="utf-8")
        cls.config = (
            cls.ios_root / "Config/Base.xcconfig"
        ).read_text(encoding="utf-8")
        cls.packager = (
            cls.ios_root / "Scripts/package_unsigned_ipa.sh"
        ).read_text(encoding="utf-8")
        cls.readme = (
            cls.ios_root / "README.md"
        ).read_text(encoding="utf-8")

    def test_native_launch_url_matches_one_use_cookie_exchange_parameter(self):
        self.assertIn(
            '@"http://127.0.0.1:%ld/?_divan_session=%@"',
            self.runtime,
        )
        self.assertNotIn('/?token=%@', self.runtime)
        self.assertIn(
            'query.get("_divan_session")',
            self.server,
        )

    def test_native_bundle_uses_keychain_and_never_packages_desktop_database(self):
        module = (
            self.ios_root / "Divan/Runtime/DivanPythonModule.m"
        ).read_text(encoding="utf-8")
        self.assertIn("kSecAttrAccessibleWhenUnlockedThisDeviceOnly", module)
        self.assertNotIn("freud.db", self.bundler)
        self.assertIn("configure_identity_store", (
            self.ios_root / "DivanPython/ios_entry.py"
        ).read_text(encoding="utf-8"))

    def test_privacy_manifests_exports_and_sensitive_snapshots_are_native(self):
        project = (
            self.ios_root / "Divan.xcodeproj/project.pbxproj"
        ).read_text(encoding="utf-8")
        bridge = (
            self.ios_root / "Divan/Web/DivanNativeBridge.swift"
        ).read_text(encoding="utf-8")
        app_source = (
            self.ios_root / "Divan/DivanApp.swift"
        ).read_text(encoding="utf-8")
        manifest = (
            self.ios_root / "Divan/Resources/PrivacyInfo.xcprivacy"
        ).read_text(encoding="utf-8")
        self.assertIn("PrivacyInfo.xcprivacy in Resources", project)
        self.assertIn("NSPrivacyAccessedAPICategoryUserDefaults", manifest)
        self.assertIn("PythonPrivacyInfo.xcprivacy", self.bundler)
        self.assertIn("purgeStaleTemporaryExports()", bridge)
        self.assertIn("scenePhase != .active", app_source)
        self.assertIn(
            "--exclude 'divan-tanitim-kapak-3248x2014.png'",
            self.bundler,
        )

    def test_private_attachment_downloads_stay_native_and_same_origin(self):
        web_view = (
            self.ios_root / "Divan/Web/DivanWebView.swift"
        ).read_text(encoding="utf-8")
        bridge = (
            self.ios_root / "Divan/Web/DivanNativeBridge.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("WKDownloadDelegate", web_view)
        self.assertIn("Content-Disposition", web_view)
        self.assertIn("LoopbackURLPolicy.isSameOrigin", web_view)
        self.assertIn("willPerformHTTPRedirection", web_view)
        self.assertIn("presentDownloadedFile", bridge)
        self.assertIn("maximumDownloadedFileBytes", bridge)
        self.assertIn("FileProtectionType.complete", bridge)

    def test_ios_text_entry_prevents_focus_zoom_and_hides_form_toolbar(self):
        web_view = (
            self.ios_root / "Divan/Web/DivanWebView.swift"
        ).read_text(encoding="utf-8")
        page = Path(PROJECT_DIR, "index.html").read_text(encoding="utf-8")
        self.assertIn(
            "webView.inputAssistantItem.leadingBarButtonGroups = []",
            web_view,
        )
        self.assertIn(
            "webView.inputAssistantItem.trailingBarButtonGroups = []",
            web_view,
        )
        self.assertIn(
            "font-size:max(16px,calc(15px * var(--fs)))",
            page,
        )
        self.assertIn(
            "font-size:max(16px,calc(15px * var(--fs)))!important",
            page,
        )
        self.assertNotIn("user-scalable=no", page)
        self.assertNotIn("maximum-scale=1", page)

    def test_startup_connection_recovers_without_hiding_local_history(self):
        page = Path(PROJECT_DIR, "index.html").read_text(encoding="utf-8")
        compact = "".join(page.split())
        self.assertIn("constAPI_GET_RETRY_DELAYS=[250,750,1500]", compact)
        self.assertIn("r=awaitfetchApiResponse(path,opt)", compact)
        self.assertIn("catch(error){renderStartupFailure(error);}", compact)
        self.assertIn("Görüşmeleryerelveritabanındaduruyor.", compact)
        self.assertIn("button.textContent='Yenidenbağlan'", compact)
        self.assertIn(
            "if(!appLocked&&!MASTERS.length){location.reload();return;}",
            compact,
        )

    def test_ios_data_directory_declares_and_reapplies_file_protection(self):
        backend = (
            self.ios_root / "Divan/Runtime/CPythonServerBackend.swift"
        ).read_text(encoding="utf-8")
        config = (
            self.ios_root / "Config/Base.xcconfig"
        ).read_text(encoding="utf-8")
        entitlements = (
            self.ios_root / "Divan/Divan.entitlements"
        ).read_text(encoding="utf-8")
        self.assertIn("completeUntilFirstUserAuthentication", backend)
        self.assertIn('appendingPathComponent("yedekler"', backend)
        self.assertIn("protectExistingContents", backend)
        self.assertIn("isExcludedFromBackup = true", backend)
        self.assertIn("CODE_SIGN_ENTITLEMENTS", config)
        self.assertIn("com.apple.developer.default-data-protection", entitlements)

    def test_bundle_verifier_rejects_missing_visual_assets_and_blank_app_icon(self):
        self.assertIn("app/assets/portraits/manifest.json", self.verifier)
        self.assertIn("app/assets/portraits/freud.jpg", self.verifier)
        self.assertIn("app/assets/imagery/manifest.json", self.verifier)
        self.assertIn("manifest.get(\"card_count\") != 24", self.verifier)
        self.assertIn("source_data != packaged_data", self.verifier)
        self.assertIn("AppIcon60x60@2x.png", self.verifier)
        self.assertIn("CFBundleIconName", self.verifier)
        self.assertIn("Uygulama simgesi tamamen siyah veya boş.", self.verifier)

        icon = (
            self.ios_root
            / "Divan/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png"
        )
        known_blank_digest = (
            "21732f7fb04677779d5167292f05a21ca0343c320fe98ac86456f7bea9e224cc"
        )
        self.assertNotEqual(
            hashlib.sha256(icon.read_bytes()).hexdigest(),
            known_blank_digest,
        )

    def test_ios_release_version_and_output_name_are_consistent(self):
        self.assertIn("MARKETING_VERSION = 2026.8.17", self.config)
        self.assertIn("CURRENT_PROJECT_VERSION = 8", self.config)
        info_plist = (
            self.ios_root / "Divan/Resources/Info.plist"
        ).read_text(encoding="utf-8")
        self.assertIn("$(MARKETING_VERSION)", info_plist)
        self.assertIn("$(CURRENT_PROJECT_VERSION)", info_plist)
        self.assertIn('RELEASE_LABEL="2026.08.17.5"', self.verifier)
        self.assertIn(
            'EXPECTED_MARKETING_VERSION="2026.8.17"',
            self.verifier,
        )
        self.assertIn('EXPECTED_BUILD_VERSION="8"', self.verifier)
        self.assertIn("CFBundleShortVersionString raw", self.verifier)
        self.assertIn("CFBundleVersion raw", self.verifier)
        self.assertIn(
            "Divan-iOS-2026.08.17.5-Standalone-Unsigned.ipa",
            self.packager,
        )
        self.assertIn("Divan **2026.08.17.5**", self.readme)
        self.assertIn("`2026.8.17` pazarlama sürümü", self.readme)
        self.assertIn("`7` derleme numarası", self.readme)

    def test_ios_build_guards_exact_common_sources_and_sync_v5(self):
        for required in (
                "server.py", "index.html", "secure_sync_transport.py",
                "sync_engine.py", "sync_service.py", "sync_qr.py",
                "qrcodegen.py"):
            with self.subTest(required=required):
                self.assertIn(required, self.bundler)
                self.assertIn("app/{}".format(required), self.verifier)
        self.assertIn(
            'cmp -s "$SOURCE_ROOT/$file" "$APP_DESTINATION/$file"',
            self.bundler,
        )
        self.assertIn(
            'cmp -s "$SOURCE_ROOT/$file" "$APP_PATH/app/$file"',
            self.verifier,
        )
        self.assertIn("BATCH_VERSION[[:space:]]*=", self.bundler)
        self.assertIn("BATCH_VERSION[[:space:]]*=", self.verifier)

        source_sync = Path(PROJECT_DIR, "sync_engine.py").read_text(
            encoding="utf-8")
        self.assertIn("BATCH_VERSION = 8", source_sync)

    def test_ios_build_rejects_databases_and_embedded_keys(self):
        for label, script in (
                ("bundler", self.bundler),
                ("verifier", self.verifier)):
            with self.subTest(script=label):
                self.assertIn("-name '*.db'", script)
                self.assertIn("-name '*.db-*'", script)
                self.assertIn("sk-(proj-)?[A-Za-z0-9_-]{20,}", script)
                self.assertIn("PRIVATE KEY", script)
        self.assertIn(
            'find "$APP_DESTINATION" "$PACKAGES_DESTINATION"',
            self.bundler,
        )
        self.assertIn('"$PROJECT_DIR/Divan"', self.bundler)
        self.assertIn("-name '*.swift'", self.bundler)
        self.assertIn('"$APP_PATH/app" "$APP_PATH/app_packages"',
                      self.verifier)
        self.assertIn("kullanıcı verisi olmadan kopyalar", self.readme)
        self.assertIn("DB/API anahtarı korumalarını", self.readme)


if __name__ == "__main__":
    unittest.main()
