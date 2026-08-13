from pathlib import Path
import unittest

from support import PROJECT_DIR


class AndroidSyncQrEmbeddingTests(unittest.TestCase):

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
        cls.gradle = (
            cls.android / "app/build.gradle.kts"
        ).read_text(encoding="utf-8")

    def test_official_permissionless_code_scanner_is_embedded(self):
        self.assertIn(
            'implementation("com.google.android.gms:'
            'play-services-code-scanner:16.1.0")',
            self.gradle,
        )
        self.assertIn(
            'android:name="com.google.mlkit.vision.DEPENDENCIES"',
            self.manifest,
        )
        self.assertIn('android:value="barcode_ui"', self.manifest)
        self.assertNotIn(
            'android.permission.CAMERA',
            self.manifest,
        )

    def test_javascript_bridge_starts_qr_only_scanner(self):
        self.assertIn("public void scanSyncQr()", self.java)
        bridge_start = self.java.index("public void scanSyncQr()")
        annotation = self.java.rfind(
            "@JavascriptInterface", 0, bridge_start)
        self.assertGreater(annotation, bridge_start - 100)
        self.assertIn(
            ".setBarcodeFormats(Barcode.FORMAT_QR_CODE)",
            self.java,
        )
        self.assertIn(".enableAutoZoom()", self.java)
        self.assertIn("syncQrScanner.startScan()", self.java)
        self.assertIn("barcode.getRawValue()", self.java)
        self.assertIn(".addOnCanceledListener(", self.java)
        self.assertIn(".addOnFailureListener(", self.java)

    def test_scan_result_is_json_quoted_before_javascript_callback(self):
        self.assertIn(
            'buildSyncCallbackScript(\n'
            '                            "onDivanSyncCode", rawValue)',
            self.java,
        )
        self.assertIn("JSONObject.quote(", self.java)
        self.assertIn('.replace("\\u2028", "\\\\u2028")', self.java)
        self.assertIn('.replace("\\u2029", "\\\\u2029")', self.java)
        self.assertIn(
            '"onDivanSyncScanError".equals(callbackName)',
            self.java,
        )
        self.assertIn('dispatchSyncCode("");', self.java)
        self.assertNotIn(
            'window.onDivanSyncCode(" + rawValue',
            self.java,
        )

