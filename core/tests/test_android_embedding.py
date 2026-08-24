from http.cookies import SimpleCookie
import hashlib
from pathlib import Path
import re
import unittest
from urllib.parse import urlencode

from support import HTTPTestCase, PROJECT_DIR, app


class AndroidKeyboardInsetsSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.android = Path(PROJECT_DIR).parent / "divan-android"
        cls.java = (
            cls.android / "app/src/main/java/com/furkancanyilmaz/divan/"
            "MainActivity.java"
        ).read_text(encoding="utf-8")
        cls.manifest = (
            cls.android / "app/src/main/AndroidManifest.xml"
        ).read_text(encoding="utf-8")
        cls.secret_store = (
            cls.android / "app/src/main/java/com/furkancanyilmaz/divan/"
            "SecretStore.java"
        ).read_text(encoding="utf-8")
        cls.response_keeper = (
            cls.android / "app/src/main/java/com/furkancanyilmaz/divan/"
            "ResponseKeeperJobService.java"
        ).read_text(encoding="utf-8")
        cls.html = Path(PROJECT_DIR, "index.html").read_text(encoding="utf-8")

    def test_keyboard_resizes_webview_without_double_ime_padding(self):
        self.assertIn('android:windowSoftInputMode="adjustResize"',
                      self.manifest)
        self.assertIn("WindowInsetsCompat.Type.systemBars()", self.java)
        self.assertIn("WindowInsetsCompat.Type.displayCutout()", self.java)
        self.assertIn(".setInsets(safeTypes, Insets.NONE)", self.java)
        self.assertNotIn("getSystemWindowInsetBottom()", self.java)
        self.assertIn("insets.isVisible(", self.java)
        self.assertIn("WindowInsetsCompat.Type.ime()", self.java)
        self.assertNotIn("insets.getInsets(WindowInsetsCompat.Type.ime())",
                         self.java)
        self.assertIn("public void showKeyboard()", self.java)
        self.assertIn("keyboard.showSoftInput(", self.java)
        self.assertIn("webView.setOnScrollChangeListener(", self.java)
        self.assertIn("view.post(() -> view.scrollTo(0, 0))", self.java)

    def test_native_viewport_height_is_read_only_and_adds_no_ime_padding(self):
        self.assertIn(
            "private volatile int mobileViewportHeightCss = 0;", self.java)
        self.assertIn("view.addOnLayoutChangeListener(", self.java)
        self.assertIn("Math.round(heightPx / density)", self.java)
        self.assertIn("public int mobileViewportHeight()", self.java)
        self.assertIn("return Math.max(0, mobileViewportHeightCss);", self.java)
        self.assertIn("public boolean mobileImeVisible()", self.java)
        self.assertIn("public boolean mobileImeStateKnown()", self.java)
        self.assertIn("dispatchMobileViewportState()", self.java)
        self.assertIn("window.divanAndroidViewportChanged", self.java)
        self.assertNotIn("setPadding(0, 0, 0, mobileViewportHeightCss)",
                         self.java)
        self.assertIn("DivanNative.mobileViewportHeight()", self.html)
        self.assertIn("DivanNative.mobileImeVisible()", self.html)
        self.assertIn("DivanNative.mobileImeStateKnown()", self.html)

    def test_foreground_forces_post_layout_viewport_resample(self):
        refresh = self.java[
            self.java.index("private void refreshMobileViewportState()"):
            self.java.index("private void dispatchMobileViewportState()")
        ]
        self.assertIn("ViewCompat.requestApplyInsets(currentRoot)", refresh)
        self.assertIn("getWindow().getDecorView().requestLayout()", refresh)
        self.assertIn("currentRoot.requestLayout()", refresh)
        self.assertIn("current.requestLayout()", refresh)
        self.assertIn("addOnPreDrawListener", refresh)
        self.assertIn("ViewCompat.getRootWindowInsets(currentRoot)", refresh)
        self.assertIn("measureMobileViewportHeightCss(current)", refresh)
        self.assertIn("dispatchMobileViewportState()", refresh)
        resume = self.java[
            self.java.index("protected void onResume()"):
            self.java.index("protected void onStop()")
        ]
        self.assertIn("refreshMobileViewportState()", resume)
        self.assertIn("onWindowFocusChanged(boolean hasFocus)", resume)
        self.assertIn("if (hasFocus)", resume)
        page_finished = self.java[
            self.java.index("public void onPageFinished("):
            self.java.index("public void onReceivedError(")
        ]
        self.assertIn("refreshMobileViewportState()", page_finished)
        self.assertNotIn("dispatchMobileViewportState()", page_finished)
        self.assertIn("mobileImeStateKnown = false", self.java)

    def test_recents_preview_is_private_and_secret_writes_are_synchronous(self):
        self.assertIn("setRecentsScreenshotEnabled(false)", self.java)
        self.assertNotIn(".apply()", self.secret_store)
        self.assertGreaterEqual(self.secret_store.count(".commit()"), 3)

    def test_background_reply_watch_is_opt_in_and_back_keeps_activity_alive(self):
        self.assertIn("moveTaskToBack(true)", self.java)
        self.assertIn("if (isFinishing() && webView != null)", self.java)
        self.assertNotIn("webView.onPause()", self.java)
        self.assertIn("completionNotificationsEnabled()", self.java)
        self.assertIn("setReplyNotificationsEnabled(boolean enabled)",
                      self.java)
        self.assertIn("startBackgroundCompletionWatch(", self.java)
        self.assertIn('"/api/jobs"', self.java)
        self.assertIn("android.permission.POST_NOTIFICATIONS", self.manifest)
        self.assertIn('id="replyNotificationToggle"', self.html)
        self.assertIn("setReplyNotificationsEnabled(", self.html)
        self.assertIn("function signalNativePendingWork(minPending=0)",
                      self.html)
        self.assertIn(
            "Math.max(forced,pendingJobCount(),pendingChatDeliveryCount())",
            self.html,
        )
        self.assertIn("android.permission.RECEIVE_BOOT_COMPLETED",
                      self.manifest)
        self.assertIn(".ResponseKeeperJobService", self.manifest)

    def test_background_keeper_closes_idle_signal_race(self):
        self.assertIn("pendingSignalGeneration++",
                      self.response_keeper)
        self.assertIn("synchronized (SCHEDULER_HANDSHAKE)",
                      self.response_keeper)
        self.assertIn("ProbeState confirmed = probeJobs(bridge)",
                      self.response_keeper)
        self.assertIn(
            "pendingSignalGeneration != idleFinishSignal",
            self.response_keeper,
        )
        self.assertNotIn(
            "scheduler.getPendingJob(JOB_ID) != null",
            self.response_keeper,
        )

    def test_native_download_forwards_both_embedded_and_app_lock_cookies(self):
        self.assertIn("connection.setRequestProperty(\"Cookie\", "
                      "localCookieHeader())", self.java)
        self.assertIn("CookieManager.getInstance().getCookie(baseUrl)",
                      self.java)

    def test_embedded_session_cookie_is_http_only_and_installed_before_load(self):
        self.assertIn('"; Path=/; HttpOnly; SameSite=Strict"', self.java)
        self.assertIn("cookies.setCookie(baseUrl, cookie, installed -> {",
                      self.java)
        self.assertIn("Boolean.TRUE.equals(installed)", self.java)
        self.assertLess(
            self.java.index("cookies.setCookie(baseUrl, cookie, installed -> {"),
            self.java.index("webView.loadUrl(baseUrl);"),
        )
        self.assertNotIn(".removeSessionCookies(", self.java)

    def test_main_frame_failures_cannot_reveal_a_raw_http_error_page(self):
        self.assertIn("mainFrameLoadFailed = false", self.java)
        self.assertIn("public void onReceivedHttpError(", self.java)
        self.assertIn("if (!request.isForMainFrame())", self.java)
        self.assertIn("mainFrameLoadFailed = true", self.java)
        self.assertIn(
            'if (!mainFrameLoadFailed && isLocal(uri)',
            self.java,
        )

    def test_json_transfer_files_use_json_mime_in_native_file_picker(self):
        self.assertIn('endsWith(".json")', self.java)
        self.assertIn('"application/json" : "text/markdown"', self.java)


class EmbeddedSessionTests(HTTPTestCase):

    def setUp(self):
        super().setUp()
        app.EMBEDDED_SESSION_TOKEN = "android-launch-token"

    def test_launch_token_is_exchanged_for_http_only_cookie(self):
        status, _, headers = self.request(
            "GET", "/?" + urlencode({
                "_divan_session": "android-launch-token",
            }))

        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        cookie = SimpleCookie()
        cookie.load(headers["Set-Cookie"])
        morsel = cookie[app.EMBEDDED_SESSION_COOKIE]
        self.assertEqual(morsel.value, "android-launch-token")
        self.assertTrue(morsel["httponly"])
        self.assertEqual(morsel["samesite"].lower(), "strict")

    def test_embedded_api_rejects_missing_cookie(self):
        status, body, _ = self.request("GET", "/api/settings")

        self.assertEqual(status, 403)
        self.assertIn("oturumu", body["error"])

    def test_embedded_cookie_allows_get_and_same_origin_post(self):
        headers = {
            "Cookie": "{}={}".format(
                app.EMBEDDED_SESSION_COOKIE, "android-launch-token"),
            "Origin": "http://127.0.0.1:{}".format(app.PORT),
        }
        status, settings, _ = self.request(
            "GET", "/api/settings", headers=headers)
        self.assertEqual(status, 200)
        self.assertIn("version", settings)

        status, body, _ = self.request(
            "POST", "/api/settings", {"simple_mode": True}, headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])


class ExternalSecretStoreTests(HTTPTestCase):

    def test_provider_keys_are_migrated_and_no_longer_live_in_sqlite(self):
        app.set_setting("openai_api_key", "legacy-openai-key")
        secrets = {}

        app.configure_secret_store(
            lambda key: secrets.get(key, ""),
            lambda key, value: (
                secrets.pop(key, None) if not value
                else secrets.__setitem__(key, value)),
        )

        self.assertEqual(secrets["openai_api_key"], "legacy-openai-key")
        self.assertEqual(app.get_setting("openai_api_key"),
                         "legacy-openai-key")
        self.assertIsNone(self.row(
            "SELECT value FROM settings WHERE key='openai_api_key'"))

        status, _, _ = self.request(
            "POST", "/api/settings", {
                "provider": "openai",
                "openai_api_key": "new-openai-key",
            })
        self.assertEqual(status, 200)
        self.assertEqual(secrets["openai_api_key"], "new-openai-key")
        self.assertIsNone(self.row(
            "SELECT value FROM settings WHERE key='openai_api_key'"))

        status, _, _ = self.request(
            "POST", "/api/settings", {"clear_openai_api_key": True})
        self.assertEqual(status, 200)
        self.assertNotIn("openai_api_key", secrets)


class AndroidPackagingConsistencyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.android = Path(PROJECT_DIR).parent / "divan-android"
        cls.gradle = (
            cls.android / "app/build.gradle.kts"
        ).read_text(encoding="utf-8")
        cls.command = (
            cls.android / "Android_APK_Hazirla.command"
        ).read_text(encoding="utf-8")
        cls.readme = (
            cls.android / "README.md"
        ).read_text(encoding="utf-8")

    def test_android_release_version_and_output_name_are_consistent(self):
        self.assertIn("versionCode = 2026082215", self.gradle)
        self.assertIn('versionName = "2026.08.22.15"', self.gradle)
        self.assertIn('VERSION="2026.08.22.15"', self.command)
        self.assertIn(
            "./gradlew clean verifyDivanEmbedding lintRelease assembleRelease",
            self.command,
        )
        self.assertIn('Divan-Android-$VERSION.apk', self.command)
        self.assertIn("Divan-Android-2026.08.22.15.apk", self.readme)
        self.assertIn("versionCode 2026082215", self.readme)

    def test_android_readme_describes_tus_as_an_adhd_chat_mode(self):
        self.assertIn("**+ → TUS Çalışma**", self.readme)
        self.assertIn("ayrı bir çalışma alanına geçmez", self.readme)
        self.assertIn("sohbet balonlarında sorar", self.readme)
        self.assertIn("yanıtları da aynı konuşmada balon", self.readme)
        self.assertIn(
            "uzun ders ve konu listeleri küçük bir seçim penceresi",
            self.readme,
        )
        self.assertIn("(popup) olarak açılabilir", self.readme)

    def test_android_build_guards_exact_common_sources_fixture_and_sync_v8(self):
        for required in (
                '"server.py"', '"index.html"',
                '"secure_sync_transport.py"', '"sync_engine.py"',
                '"sync_service.py"', '"sync_qr.py"', '"qrcodegen.py"'):
            with self.subTest(required=required):
                self.assertIn(required, self.gradle)
        self.assertIn("val verifyDivanEmbedding", self.gradle)
        self.assertIn("dependsOn(syncDivanSources)", self.gradle)
        self.assertIn("val expectedCommonSha256 = mapOf(", self.gradle)
        self.assertIn("sha256(source) == expectedDigest", self.gradle)
        self.assertIn("sha256(embedded) == expectedDigest", self.gradle)
        self.assertIn("source.readBytes().contentEquals", self.gradle)
        self.assertIn("expectedSchemaPathContractSha256", self.gradle)
        self.assertIn(
            "30e2cac7c8ced6e58a3f8860ea887f1f1e6f42cb888d21da6bcaad7803294197",
            self.gradle,
        )
        self.assertIn("sha256(schemaPathContractFixture) ==", self.gradle)
        self.assertIn('include("assets/imagery/**")', self.gradle)
        self.assertIn("sourceCards.size == 24", self.gradle)
        self.assertIn('String(header, 8, 4, Charsets.US_ASCII) == "WEBP"',
                      self.gradle)
        self.assertIn("BATCH_VERSION\\s*=\\s*8", self.gradle)
        self.assertIn("dependsOn(verifyDivanEmbedding)", self.gradle)

        source_sync = Path(PROJECT_DIR, "sync_engine.py").read_text(
            encoding="utf-8")
        self.assertIn("BATCH_VERSION = 8", source_sync)
        self.assertIn("Eşitleme protokolü v8", self.readme)
        self.assertIn("schema_path_chat_v5", self.readme)
        self.assertNotIn("eşitleme protokolünün v5", self.readme)

        expected = dict(re.findall(
            r'"([^"\\]+)"\s+to\s+"([0-9a-f]{64})"',
            self.gradle,
        ))
        self.assertEqual(set(expected), {
            "server.py", "index.html", "secure_sync_transport.py",
            "sync_engine.py", "sync_service.py", "sync_qr.py",
            "qrcodegen.py",
        })
        embedded_root = self.android / "app/src/main/python"
        for name, digest in expected.items():
            with self.subTest(name=name):
                source = Path(PROJECT_DIR, name)
                embedded = embedded_root / name
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                                 digest)
                self.assertEqual(source.read_bytes(), embedded.read_bytes())

    def test_android_build_rejects_databases_and_embedded_keys(self):
        self.assertIn("fileTree(androidPackageSourceRoot)", self.gradle)
        self.assertIn('include("**/*.db", "**/*.db-*"', self.gradle)
        self.assertIn("forbiddenDatabases.isEmpty()", self.gradle)
        self.assertIn('"**/*.java", "**/*.kt", "**/*.xml"', self.gradle)
        self.assertIn("sk-(?:proj-)?[A-Za-z0-9_-]{20,}", self.gradle)
        self.assertIn("secretMatches.isEmpty()", self.gradle)
        self.assertIn("kullanıcı veritabanı", self.readme)
        self.assertIn("API anahtarı", self.readme)
