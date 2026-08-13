import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class NativeAdapterSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")
        cls.adapter_start = cls.html.index(
            "/* ---------------- ortak yerel uygulama köprüsü")
        cls.adapter_end = cls.html.index(
            "let THERAPISTS = [];", cls.adapter_start)
        cls.adapter = cls.html[cls.adapter_start:cls.adapter_end]
        cls.compact = re.sub(r"\s+", "", cls.adapter)

    def test_only_the_adapter_reads_platform_bridges(self):
        outside = (
            self.html[:self.adapter_start]
            + self.html[self.adapter_end:]
        )
        self.assertIn("const android=window.DivanAndroid||null;",
                      self.adapter)
        self.assertIn("window.webkit.messageHandlers.divanNative",
                      self.adapter)
        self.assertNotIn("window.DivanAndroid", outside)
        self.assertNotIn("window.webkit.messageHandlers", outside)

    def test_ios_bridge_uses_versioned_reply_promise_contract(self):
        self.assertIn(
            "constreply=ios.postMessage({version:1,method,payload});",
            self.compact,
        )
        self.assertIn("typeofreply.then!=='function'", self.compact)
        self.assertIn("Promise.resolve(reply).then(unwrapIosReply", self.compact)
        self.assertIn("if(reply.ok===false)", self.compact)
        self.assertIn(
            "Object.prototype.hasOwnProperty.call(reply,'result')",
            self.compact,
        )

    def test_public_adapter_is_frozen_allowlisted_and_android_compatible(self):
        for capability in (
            "setPendingWork", "showKeyboard", "hideKeyboard", "copyText",
            "saveText", "saveStoryImage", "shareStoryImages", "scanSyncQr",
            "completionNotifications", "haptic",
        ):
            self.assertIn("'" + capability + "'", self.adapter)
        self.assertIn("returnObject.freeze({", self.compact)
        self.assertIn(
            "try{returnPromise.resolve(android[method](...args));}",
            self.compact,
        )
        self.assertIn(
            "Object.defineProperty(window,'DivanNative'", self.compact)
        self.assertIn(
            "window.divanAndroidBack=window.divanNativeBack;", self.html)

    def test_shared_platform_state_drives_settings_sync_and_lifecycle(self):
        self.assertIn("API anahtarları iOS Anahtar Zinciri’nde tutulur",
                      self.html)
        self.assertIn("iPhone/iPad uygulaması", self.html)
        self.assertIn("device_name:DivanNative.deviceName", self.html)
        self.assertIn("platform:nativePlatform", self.html)
        self.assertIn(
            "document.visibilityState==='hidden'&&DivanNative.embedded",
            self.html,
        )
        self.assertIn(
            "await DivanNative.replyNotificationsEnabled()", self.html)
        self.assertIn(
            "await DivanNative.setReplyNotificationsEnabled(", self.html)


if __name__ == "__main__":
    unittest.main()
