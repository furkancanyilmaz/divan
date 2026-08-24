from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from support import PROJECT_DIR


ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


class AndroidNativeShellSourceContractTests(unittest.TestCase):
    """Native shell contracts which are easy to regress in a WebView app."""

    @classmethod
    def setUpClass(cls):
        cls.android = Path(PROJECT_DIR).parent / "divan-android"
        cls.main_path = (
            cls.android
            / "app/src/main/java/com/furkancanyilmaz/divan/MainActivity.java"
        )
        cls.main = cls.main_path.read_text(encoding="utf-8")
        cls.manifest_path = cls.android / "app/src/main/AndroidManifest.xml"
        cls.manifest = cls.manifest_path.read_text(encoding="utf-8")
        cls.res = cls.android / "app/src/main/res"
        cls.gradle = (cls.android / "app/build.gradle.kts").read_text(
            encoding="utf-8")

    @staticmethod
    def method_body(source, signature):
        start = source.index(signature)
        brace = source.index("{", start)
        depth = 0
        for index in range(brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[brace + 1:index]
        raise AssertionError("Method body is not closed: " + signature)

    @staticmethod
    def style_items(path, style_name="Theme.Divan"):
        root = ET.parse(path).getroot()
        style = next(
            (
                element for element in root.findall("style")
                if element.attrib.get("name") == style_name
            ),
            None,
        )
        if style is None:
            raise AssertionError(
                "Style {!r} not found in {}".format(style_name, path))
        return {
            item.attrib["name"]: (item.text or "").strip()
            for item in style.findall("item")
        }

    def test_edge_to_edge_has_one_owner_and_does_not_double_apply_ime(self):
        self.assertEqual(
            self.main.count(
                "WindowCompat.setDecorFitsSystemWindows(getWindow(), false)"),
            1,
        )
        self.assertEqual(
            self.main.count("ViewCompat.setOnApplyWindowInsetsListener("),
            1,
        )
        listener = self.main.split(
            "ViewCompat.setOnApplyWindowInsetsListener(", 1)[1]
        listener = listener.split("ViewCompat.requestApplyInsets(root);", 1)[0]
        self.assertIn("WindowInsetsCompat.Type.systemBars()", listener)
        self.assertIn("WindowInsetsCompat.Type.displayCutout()", listener)
        self.assertIn("view.setPadding(safe.left, safe.top, safe.right, safe.bottom)",
                      listener)
        self.assertIn(".setInsets(safeTypes, Insets.NONE)", listener)
        self.assertIn("insets.isVisible(", listener)
        self.assertIn("WindowInsetsCompat.Type.ime()", listener)
        self.assertNotIn("getInsets(WindowInsetsCompat.Type.ime())", listener)
        self.assertNotIn("setInsets(WindowInsetsCompat.Type.ime()", listener)
        self.assertNotIn("setOnApplyWindowInsetsListener(webView", self.main)
        self.assertIn('android:windowSoftInputMode="adjustResize"',
                      self.manifest)

    def test_system_chrome_bridge_tracks_all_three_mobile_palettes(self):
        compatibility_body = self.method_body(
            self.main, "private void applySystemChrome(boolean dark)")
        palette_body = self.method_body(
            self.main,
            "private void applySystemChromeTheme(String requestedTheme)",
        )
        compatibility_bridge = self.method_body(
            self.main, "public void setSystemChrome(boolean dark)")
        palette_bridge = self.method_body(
            self.main, "public void setSystemChromeTheme(String theme)")

        self.assertRegex(
            self.main,
            r"@JavascriptInterface\s+public void setSystemChrome\(boolean dark\)",
        )
        self.assertIn("runOnUiThread(() -> applySystemChrome(dark))",
                      compatibility_bridge)
        self.assertIn(
            'applyAndPersistSystemChromeTheme(dark ? "dark" : "paper")',
                      compatibility_body)
        self.assertRegex(
            self.main,
            r"@JavascriptInterface\s+public void "
            r"setSystemChromeTheme\(String theme\)",
        )
        self.assertIn(
            "MainActivity.this.applyAndPersistSystemChromeTheme(",
            palette_bridge,
        )

        for theme in ("white", "paper", "dark"):
            self.assertIn(f'case "{theme}"', palette_body)
        self.assertIn("Color.rgb(255, 255, 255)", palette_body)
        self.assertIn("getColor(R.color.divan_background)", palette_body)
        self.assertIn("getColor(R.color.divan_ink)", palette_body)
        self.assertIn("getColor(R.color.divan_wine)", palette_body)
        self.assertIn("Color.rgb(25, 29, 32)", palette_body)
        self.assertIn("default:", palette_body)
        self.assertNotIn("Color.parseColor", palette_body)
        self.assertIn("getWindow().setStatusBarColor(background)",
                      palette_body)
        self.assertIn(
            "getWindow().setNavigationBarColor(navigationBackground)",
                      palette_body)
        self.assertIn("Build.VERSION.SDK_INT < Build.VERSION_CODES.O",
                      palette_body)
        self.assertIn("Build.VERSION.SDK_INT >= Build.VERSION_CODES.O",
                      palette_body)
        self.assertIn("setNavigationBarDividerColor(navigationBackground)",
                      palette_body)
        self.assertIn("controller.setAppearanceLightStatusBars(!dark)",
                      palette_body)
        self.assertIn("controller.setAppearanceLightNavigationBars(",
                      palette_body)
        self.assertIn(
            "!dark && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O",
            palette_body,
        )
        self.assertIn("root.setBackgroundColor(background)", palette_body)
        self.assertIn("webView.setBackgroundColor(background)", palette_body)
        self.assertIn("statusPanel.setBackgroundColor(background)",
                      palette_body)
        self.assertIn("statusText.setTextColor(foreground)", palette_body)
        self.assertIn("statusMark.setImageTintList(", palette_body)
        self.assertIn("styleRetryButton(accent)", palette_body)
        on_create = self.method_body(
            self.main, "protected void onCreate(Bundle savedInstanceState)")
        self.assertLess(on_create.index("setTheme(R.style.Theme_Divan)"),
                        on_create.index("super.onCreate(savedInstanceState)"))
        self.assertLess(
            on_create.index(
                "applySystemChromeTheme(savedSystemChromeTheme())"),
                        on_create.index("createLayout()"))

    def test_native_palette_is_normalized_and_persisted_before_web_load(self):
        normalize = self.method_body(
            self.main,
            "private String normalizeSystemChromeTheme("
            "String requestedTheme)",
        )
        saved = self.method_body(
            self.main, "private String savedSystemChromeTheme()")
        persist = self.method_body(
            self.main,
            "private void applyAndPersistSystemChromeTheme("
            "String requestedTheme)",
        )
        for allowed in ("white", "paper", "dark"):
            self.assertIn('"{}"'.format(allowed), normalize)
        self.assertIn('return "paper"', normalize)
        self.assertIn("NATIVE_VISUAL_PREFS", saved)
        self.assertIn("NATIVE_THEME_KEY", saved)
        self.assertIn("normalizeSystemChromeTheme", saved)
        self.assertIn("putString(NATIVE_THEME_KEY, theme)", persist)
        self.assertIn("applySystemChromeTheme(theme)", persist)

    def test_loading_and_error_surface_use_minimal_theme_aware_controls(self):
        layout = self.method_body(self.main, "private void createLayout()")
        palette = self.method_body(
            self.main,
            "private void applySystemChromeTheme(String requestedTheme)",
        )
        retry_style = self.method_body(
            self.main, "private void styleRetryButton(int accent)")
        retry_background = self.method_body(
            self.main, "private Drawable retryButtonBackground(int accent)")
        status = self.method_body(
            self.main,
            "private void showStatus(String message, boolean canRetry)",
        )

        self.assertIn("statusMark = new ImageView(this)", layout)
        self.assertIn("R.drawable.ic_divan_monochrome", layout)
        self.assertIn("ColorStateList.valueOf(nativeAccent)", layout)
        self.assertIn("root.setBackgroundColor(nativeBackground)", layout)
        self.assertIn("statusPanel.setBackgroundColor(nativeBackground)",
                      layout)
        self.assertIn("retryButton.setAllCaps(false)", layout)
        self.assertIn("retryButton.setMinHeight(dp(48))", layout)
        self.assertIn("styleRetryButton(nativeAccent)", layout)
        self.assertIn("statusMark.setImageTintList(", palette)
        self.assertIn("retryButton.setTextColor(accent)", retry_style)
        self.assertIn("retryButton.setBackgroundTintList(null)", retry_style)
        self.assertIn("GradientDrawable", retry_background)
        self.assertIn("RippleDrawable", retry_background)
        self.assertIn("outline.setStroke", retry_background)
        self.assertIn(
            "loadingProgress.setVisibility(canRetry ? View.GONE : "
            "View.VISIBLE)",
            status,
        )

    def test_notification_settings_bridge_uses_supported_android_intents(self):
        bridge = self.method_body(
            self.main, "public void openNotificationSettings()")
        self.assertRegex(
            self.main,
            r"@JavascriptInterface\s+public void openNotificationSettings\(\)",
        )
        self.assertIn("runOnUiThread(() ->", bridge)
        self.assertIn("Build.VERSION.SDK_INT >= Build.VERSION_CODES.O", bridge)
        self.assertIn("Settings.ACTION_APP_NOTIFICATION_SETTINGS", bridge)
        self.assertIn("Settings.EXTRA_APP_PACKAGE", bridge)
        self.assertIn("getPackageName()", bridge)
        self.assertIn("Settings.ACTION_APPLICATION_DETAILS_SETTINGS", bridge)
        self.assertIn('Uri.parse("package:" + getPackageName())', bridge)
        self.assertIn("startActivity(intent)", bridge)
        self.assertIn("catch (ActivityNotFoundException", bridge)

    def test_theme_attributes_live_only_in_compatible_api_qualifiers(self):
        base = self.style_items(
            self.res / "values/styles.xml", "Theme.DivanBase")
        self.assertEqual(base["android:windowBackground"],
                         "@color/divan_background")
        self.assertEqual(base["android:statusBarColor"],
                         "@color/divan_background")
        self.assertEqual(base["android:navigationBarColor"],
                         "@color/divan_background")
        self.assertEqual(base["android:windowLightStatusBar"], "true")

        starting = self.style_items(
            self.res / "values/styles.xml", "Theme.Divan.Starting")
        self.assertEqual(starting["android:windowBackground"],
                         "@drawable/divan_launch_screen")
        self.assertEqual(starting["android:statusBarColor"],
                         "@color/divan_launcher_background")
        self.assertEqual(starting["android:navigationBarColor"],
                         "@color/divan_launcher_background")
        self.assertEqual(starting["android:windowLightStatusBar"], "false")

        self.assertFalse((self.res / "values-v26/styles.xml").exists())
        v27 = self.style_items(self.res / "values-v27/styles.xml")
        v27_starting = self.style_items(
            self.res / "values-v27/styles.xml", "Theme.Divan.Starting")
        v28 = self.style_items(self.res / "values-v28/styles.xml")
        v29 = self.style_items(self.res / "values-v29/styles.xml")
        v31 = self.style_items(self.res / "values-v31/styles.xml")
        self.assertEqual(v27, {"android:windowLightNavigationBar": "true"})
        self.assertEqual(
            v27_starting["android:windowLightNavigationBar"], "false")
        self.assertEqual(v28["android:windowLayoutInDisplayCutoutMode"],
                         "shortEdges")
        self.assertNotIn("android:forceDarkAllowed", v28)
        self.assertEqual(v29["android:forceDarkAllowed"], "false")
        self.assertEqual(v29["android:enforceNavigationBarContrast"], "false")
        self.assertNotIn("android:windowSplashScreenBackground", v31)
        v31_starting = self.style_items(
            self.res / "values-v31/styles.xml", "Theme.Divan.Starting")
        self.assertEqual(
            v31_starting["android:windowSplashScreenBackground"],
            "@color/divan_launcher_background",
        )
        self.assertEqual(
            v31_starting["android:windowSplashScreenAnimatedIcon"],
                         "@drawable/ic_divan_foreground")

        manifest = ET.parse(self.manifest_path).getroot()
        application = manifest.find("application")
        activity = application.find("activity")
        self.assertEqual(activity.attrib[ANDROID_NS + "theme"],
                         "@style/Theme.Divan.Starting")
        launch = ET.parse(
            self.res / "drawable/divan_launch_screen.xml").getroot()
        self.assertEqual(launch.tag, "layer-list")
        items = launch.findall("item")
        self.assertEqual(items[0].attrib[ANDROID_NS + "drawable"],
                         "@color/divan_launcher_background")
        self.assertEqual(items[1].attrib[ANDROID_NS + "drawable"],
                         "@drawable/ic_divan_foreground")
        self.assertEqual(items[1].attrib[ANDROID_NS + "gravity"], "center")

    def test_launcher_has_adaptive_round_and_android_13_monochrome_layers(self):
        manifest = ET.parse(self.manifest_path).getroot()
        application = manifest.find("application")
        self.assertIsNotNone(application)
        self.assertEqual(application.attrib[ANDROID_NS + "icon"],
                         "@mipmap/ic_launcher")
        self.assertEqual(application.attrib[ANDROID_NS + "roundIcon"],
                         "@mipmap/ic_launcher_round")

        for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
            legacy = self.res / "mipmap-anydpi" / name
            self.assertEqual(ET.parse(legacy).getroot().tag, "vector")
        legacy_regular = ET.parse(
            self.res / "mipmap-anydpi/ic_launcher.xml").getroot()
        legacy_round = ET.parse(
            self.res / "mipmap-anydpi/ic_launcher_round.xml").getroot()
        self.assertEqual(
            legacy_regular.findall("path")[0].attrib[ANDROID_NS + "pathData"],
            "M0,0h108v108h-108z",
        )
        self.assertEqual(
            legacy_round.findall("path")[0].attrib[ANDROID_NS + "pathData"],
            "M54,4a50,50 0,1 1,0 100a50,50 0,1 1,0 -100z",
        )
        self.assertFalse((self.res / "values/mipmap.xml").exists())

        for api in (26, 33):
            for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
                path = self.res / "mipmap-anydpi-v{}".format(api) / name
                root = ET.parse(path).getroot()
                self.assertEqual(root.tag, "adaptive-icon")
                self.assertEqual(
                    root.find("background").attrib[ANDROID_NS + "drawable"],
                    "@color/divan_launcher_background",
                )
                self.assertEqual(
                    root.find("foreground").attrib[ANDROID_NS + "drawable"],
                    "@drawable/ic_divan_foreground",
                )
                monochrome = root.find("monochrome")
                if api == 33:
                    self.assertIsNotNone(monochrome)
                    self.assertEqual(
                        monochrome.attrib[ANDROID_NS + "drawable"],
                        "@drawable/ic_divan_monochrome",
                    )
                else:
                    self.assertIsNone(monochrome)

        foreground = ET.parse(
            self.res / "drawable/ic_divan_foreground.xml").getroot()
        monochrome = ET.parse(
            self.res / "drawable/ic_divan_monochrome.xml").getroot()
        foreground_paths = [
            element.attrib[ANDROID_NS + "pathData"]
            for element in foreground.findall("path")
        ]
        self.assertIn(
            "M30,51h48c3.3,0 6,2.7 6,6v13c0,2.2 -1.8,4 -4,4H28"
            "c-2.2,0 -4,-1.8 -4,-4V57c0,-3.3 2.7,-6 6,-6z",
            foreground_paths,
        )
        self.assertNotIn("M25,52h58", "".join(foreground_paths))
        self.assertIn("M33,40", monochrome.find("path").attrib[
            ANDROID_NS + "pathData"])

    def test_status_icon_is_separate_from_launcher_artwork(self):
        status_path = self.res / "drawable/ic_stat_divan.xml"
        launcher_path = self.res / "drawable/ic_divan_foreground.xml"
        self.assertTrue(status_path.is_file())
        self.assertTrue(launcher_path.is_file())
        self.assertNotEqual(status_path.read_bytes(), launcher_path.read_bytes())
        self.assertFalse(
            (self.res / "drawable/ic_divan_launcher.xml").exists())

        status = ET.parse(status_path).getroot()
        self.assertEqual(status.attrib[ANDROID_NS + "width"], "24dp")
        self.assertEqual(status.attrib[ANDROID_NS + "height"], "24dp")
        visible_fills = {
            path.attrib.get(ANDROID_NS + "fillColor", "")
            for path in status.findall("path")
            if path.attrib.get(ANDROID_NS + "fillColor") != "#00000000"
        }
        self.assertEqual(visible_fills, {"#FFFFFFFF"})

        java_root = (
            self.android
            / "app/src/main/java/com/furkancanyilmaz/divan"
        )
        for name in (
                "ChatNotificationController.java",
                "CompletionNotificationController.java",
                "ReminderReceiver.java"):
            source = (java_root / name).read_text(encoding="utf-8")
            with self.subTest(source=name):
                self.assertIn("R.drawable.ic_stat_divan", source)
                self.assertNotIn("R.mipmap.ic_launcher", source)

    def test_release_is_non_debuggable_and_keeps_installable_version(self):
        release = self.gradle.split("release {", 1)[1].split("}", 1)[0]
        self.assertIn("isDebuggable = false", release)
        self.assertRegex(self.gradle, r"versionCode\s*=\s*2026082215\b")
        self.assertRegex(
            self.gradle, r'versionName\s*=\s*"2026\.08\.22\.15"')
        self.assertIn('disable += "HighAppVersionCode"', self.gradle)
        self.assertIn("abortOnError = true", self.gradle)


if __name__ == "__main__":
    unittest.main()
