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
            "completionNotifications", "setSystemChrome",
            "setSystemChromeTheme",
            "openNotificationSettings", "purgeSensitiveNotifications",
            "mobileViewportHeight", "mobileImeVisible",
            "mobileImeStateKnown", "haptic",
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
        self.assertIn(
            "returncall('setSystemChrome',{dark:value},[value]);",
            self.compact,
        )
        self.assertIn(
            "returncall('setSystemChromeTheme',{theme:value},[value]);",
            self.compact,
        )
        self.assertIn("constdark=value==='dark';", self.compact)
        self.assertIn(
            "returncall('setSystemChrome',{dark},[dark]);",
            self.compact,
        )
        self.assertIn(
            "returncall('openNotificationSettings',{},[]);",
            self.compact,
        )
        self.assertIn(
            "returncall('purgeSensitiveNotifications',{},[]).then(()=>true);",
            self.compact,
        )
        self.assertIn(
            "Math.round(Number(android.mobileViewportHeight())||0)",
            self.compact,
        )
        self.assertIn("return!!android.mobileImeVisible();", self.compact)
        self.assertIn("return!!android.mobileImeStateKnown();", self.compact)

    def test_sensitive_notification_purge_tracks_lock_pin_guest_and_safety(self):
        self.assertIn("function purgeSensitiveNativeNotifications()",
                      self.html)
        lock = self.html[
            self.html.index("function enterAppLockedState()"):
            self.html.index("async function loadUnlockedShell()")]
        self.assertIn("void purgeSensitiveNativeNotifications()", lock)
        save = self.html[
            self.html.index("$('settingsSave').onclick=async()=>{"):
            self.html.index("$('pinInput').oninput=", self.html.index(
                "$('settingsSave').onclick=async()=>{"))]
        self.assertIn("if(pin)await purgeSensitiveNativeNotifications()",
                      save)
        self.assertGreaterEqual(
            self.html.count(
                "if(settings.guest_mode)void purgeSensitiveNativeNotifications()"),
            1)
        safety = self.html[
            self.html.index("function setConversationSafetyHold(hold)"):
            self.html.index("function responseMessage(")]
        self.assertIn("const entered=next&&!!convData&&!convData.safety_hold",
                      safety)
        self.assertIn("if(entered)void purgeSensitiveNativeNotifications()",
                      safety)
        self.assertIn(
            "if(convData&&(convData.safety_hold||convData.is_guest))",
            self.html)
        self.assertNotIn("convData.safety_hold=1", self.html)

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
