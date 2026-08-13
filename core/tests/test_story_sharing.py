import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class StorySharingSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")
        cls.android = Path(PROJECT_DIR).parent / "divan-android"
        cls.java = (
            cls.android / "app/src/main/java/com/furkancanyilmaz/divan/"
            "MainActivity.java"
        ).read_text(encoding="utf-8")
        cls.manifest = (
            cls.android / "app/src/main/AndroidManifest.xml"
        ).read_text(encoding="utf-8")
        cls.paths = (
            cls.android / "app/src/main/res/xml/share_file_paths.xml"
        ).read_text(encoding="utf-8")
        cls.gradle = (
            cls.android / "app/build.gradle.kts"
        ).read_text(encoding="utf-8")

    def test_mobile_story_builder_has_selection_and_story_sized_canvas(self):
        self.assertIn('id="storyBtn"', self.html)
        self.assertIn('id="storySelectionBar"', self.html)
        self.assertIn('id="storyOverlay"', self.html)
        self.assertIn(
            '<canvas id="storyCanvas" width="1080" height="1920"',
            self.html,
        )
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn("aspect-ratio:9/16", compact)
        self.assertIn("height:100dvh", compact)
        self.assertIn("env(safe-area-inset-bottom)", self.html)
        self.assertIn("overflow-y:auto", compact)
        self.assertIn(
            ".storyControlPane{max-height:none;overflow:visible",
            compact,
        )
        self.assertIn("modal.scrollTop=0", compact)

    def test_long_press_starts_mobile_message_multi_selection(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "functionbindMessageSelectionLongPress(bubble){",
            compact,
        )
        self.assertIn(
            "bubble.addEventListener('pointerdown'",
            compact,
        )
        self.assertIn("setTimeout(()=>", compact)
        self.assertRegex(
            compact,
            r"setTimeout\(\(\)=>.*?startStorySelection\(bubble\).*?,"
            r"(?:5[0-9]{2}|6[0-4][0-9])\)",
        )
        self.assertIn("Math.hypot(", self.html)
        for event_name in (
            "pointerup",
            "pointercancel",
            "pointerleave",
            "lostpointercapture",
        ):
            self.assertIn("'{}'".format(event_name), self.html)
        self.assertRegex(
            compact,
            r"bubble\.addEventListener\('contextmenu',event=>\{"
            r"if\(mobileChatViewport\(\)\)event\.preventDefault\(\);?\}\)",
        )
        self.assertIn(
            "bindMessageSelectionLongPress(bubble);",
            self.html,
        )

    def test_message_selection_actions_live_at_the_top_and_offer_copy_story(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn('id="storySelectionCopy"', self.html)
        self.assertIn('id="storySelectionContinue"', self.html)
        bar = re.search(
            r"#storySelectionBar\s*\{(?P<body>[^}]+)\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(bar)
        css = re.sub(r"\s+", "", bar.group("body"))
        self.assertIn("position:fixed", css)
        self.assertIn("top:", css)
        self.assertNotRegex(css, r"(?:^|;)bottom:0(?:;|$)")
        self.assertRegex(
            self.html,
            r'id="storySelectionCopy"[^>]*'
            r'aria-label="[^"]*[Kk]opyala[^"]*"',
        )
        self.assertRegex(
            self.html,
            r'id="storySelectionContinue"[^>]*'
            r'aria-label="[^"]*[Hh]ikâye[^"]*"',
        )
        self.assertIn(
            "$('storySelectionCopy').onclick=copyStorySelection;",
            compact,
        )
        self.assertIn(
            "$('storySelectionContinue').onclick=continueStorySelection;",
            compact,
        )

    def test_copy_uses_selected_ephemeral_messages_in_conversation_order(self):
        function = re.search(
            r"async function copyStorySelection\(\)\{(?P<body>.*?)\n\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(function)
        body = function.group("body")
        self.assertIn("storySelected", body)
        self.assertIn("chat.querySelectorAll('.bubble')", body)
        self.assertIn("bubbleShareMeta.get(bubble)", body)
        self.assertIn("cleanStoryText(", body)
        self.assertIn("navigator.clipboard", body)
        self.assertIn("document.execCommand('copy')", body)
        self.assertNotIn("localStorage", body)
        self.assertNotIn("api(", body)

    def test_long_press_selects_the_origin_then_taps_toggle_more_messages(self):
        start = re.search(
            r"function startStorySelection\((?P<args>[^)]*)\)"
            r"\{(?P<body>.*?)\n\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(start)
        self.assertIn("bubble", start.group("args"))
        self.assertRegex(
            start.group("body"),
            r"toggleStoryBubble\(bubble,\s*true\)",
        )
        ensure = re.search(
            r"function ensureStoryPick\(bubble\)\{(?P<body>.*?)\n\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(ensure)
        self.assertIn("toggleStoryBubble(target)", ensure.group("body"))

    def test_story_has_requested_appearance_and_privacy_controls(self):
        for control in (
            "storyTheme",
            "storyFont",
            "storyLayout",
            "storyIdentity",
            "storyPortrait",
            "storyPortraitChoose",
            "storyPortraitFile",
            "storySize",
            "storyShowTitle",
            "storyShowDate",
            "storyShowBrand",
            "storyShowNumbers",
        ):
            self.assertIn('id="{}"'.format(control), self.html)
        for theme in ("divan", "parchment", "night", "emerald"):
            self.assertIn('<option value="{}">'.format(theme), self.html)
        self.assertIn("Görüntü bu cihazda oluşturulur", self.html)
        self.assertIn("Terapi konuşmaları hassas olabilir", self.html)
        self.assertIn(
            '<option value="generic">Ben / Usta</option>',
            self.html,
        )
        self.assertIn(
            '<option value="bust">Divan büstü</option>',
            self.html,
        )
        self.assertIn(
            '<option value="hidden">Portreyi ve adı gizle</option>',
            self.html,
        )

    def test_story_header_identifies_the_current_master(self):
        self.assertIn("function drawStoryIdentityHeader(", self.html)
        self.assertIn("function drawStoryBust(", self.html)
        self.assertIn("function drawStoryMonogram(", self.html)
        self.assertIn("function drawStoryPhoto(", self.html)
        self.assertIn("master&&master.name?master.name", self.html)
        self.assertIn("master&&master.school?master.school", self.html)
        self.assertIn(
            "drawStoryIdentityHeader(ctx,options,palette);",
            self.html,
        )

    def test_raw_messages_stay_ephemeral_and_out_of_the_dom(self):
        self.assertIn("const bubbleShareMeta = new WeakMap();", self.html)
        self.assertIn("bubbleShareMeta.set(bubble,{", self.html)
        self.assertNotIn("dataset.storyContent", self.html)
        self.assertNotIn("localStorage.setItem('storyMessages'", self.html)
        self.assertNotIn("localStorage.setItem('storyPortraitImage'", self.html)
        self.assertIn(
            "localStorage.setItem('storyAppearance',JSON.stringify({",
            self.html,
        )
        self.assertIn(
            "functionrenderConversationMessage(message,order=0)",
            re.sub(r"\s+", "", self.html),
        )
        self.assertIn(
            "content:m.content,created:m.created,order,",
            re.sub(r"\s+", "", self.html),
        )

    def test_custom_portrait_is_local_ephemeral_and_bounded(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn("letstoryPortraitImage=null;", compact)
        self.assertIn(
            "constSTORY_MAX_PORTRAIT_BYTES=5*1024*1024;",
            compact,
        )
        self.assertIn(
            "constallowed=['image/png','image/jpeg','image/webp'];",
            compact,
        )
        self.assertIn("URL.createObjectURL(file)", self.html)
        self.assertIn("URL.revokeObjectURL(objectUrl)", self.html)
        self.assertIn(
            'accept="image/png,image/jpeg,image/webp"',
            self.html,
        )

    def test_story_cleaning_is_pure_and_limits_work(self):
        function = re.search(
            r"function cleanStoryText\(value\)\{(?P<body>.*?)\n\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(function)
        self.assertNotIn("stripMarker", function.group("body"))
        self.assertIn("⟨durak:", function.group("body"))
        self.assertIn("const STORY_MAX_MESSAGES = 20;", self.html)
        self.assertIn("const STORY_MAX_CHARS = 20000;", self.html)
        self.assertIn("const STORY_MAX_PAGES = 8;", self.html)
        self.assertIn("wrapStoryText", self.html)
        self.assertIn("storyGraphemes", self.html)
        self.assertIn("hasMore", self.html)

    def test_story_appears_when_native_sharing_is_available(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "functionstoryNativeAvailable(){consttestMode="
            "newURLSearchParams(location.search).get('test')==='1';"
            "returntestMode||DivanNative.supports('shareStoryImages');}",
            compact,
        )
        self.assertIn(
            "$('storyBtn').style.display=open&&mainMsgs>0&&"
            "storyNativeAvailable()&&!streaming?'':'none';",
            compact,
        )
        self.assertIn(
            'body[data-state="streaming"]#storyBtn{display:none!important}',
            compact,
        )
        self.assertIn("if(storySelecting){", self.html)
        self.assertIn("cancelStorySelection();", self.html)
        self.assertIn("resetStoryFlow();", self.html)

    def test_android_bridge_accepts_only_bounded_png_pages(self):
        self.assertIn(
            'private static final String PNG_DATA_PREFIX =',
            self.java,
        )
        self.assertIn('"data:image/png;base64,"', self.java)
        self.assertIn("MAX_STORY_PAGES = 8", self.java)
        self.assertIn("MAX_STORY_IMAGE_BYTES = 8 * 1024 * 1024", self.java)
        self.assertIn("MAX_STORY_TOTAL_BYTES = 40 * 1024 * 1024", self.java)
        self.assertIn("PNG_SIGNATURE", self.java)
        self.assertIn("decodeStoryPng", self.java)
        self.assertIn("@JavascriptInterface", self.java)
        self.assertIn("void shareStoryImages(String jsonDataUrls)", self.java)
        self.assertIn("void copyText(String content)", self.java)
        self.assertIn("MAX_CLIPBOARD_TEXT_BYTES", self.java)
        self.assertIn("ClipboardManager", self.java)
        self.assertIn(
            "void saveStoryImage(String fileName, String dataUrl)",
            self.java,
        )

    def test_android_shares_cache_uris_with_temporary_read_access(self):
        self.assertIn("androidx.core.content.FileProvider", self.manifest)
        self.assertIn('android:exported="false"', self.manifest)
        self.assertIn('android:grantUriPermissions="true"', self.manifest)
        self.assertIn('@xml/share_file_paths', self.manifest)
        self.assertIn("<cache-path", self.paths)
        self.assertIn('path="shared-stories/"', self.paths)
        self.assertNotIn("external-path", self.paths)
        self.assertNotIn("READ_EXTERNAL_STORAGE", self.manifest)
        self.assertNotIn("WRITE_EXTERNAL_STORAGE", self.manifest)
        self.assertIn("Intent.ACTION_SEND_MULTIPLE", self.java)
        self.assertIn("Intent.ACTION_SEND", self.java)
        self.assertIn('share.setType("image/png")', self.java)
        self.assertIn("Intent.FLAG_GRANT_READ_URI_PERMISSION", self.java)
        self.assertIn("ClipData.newUri", self.java)
        self.assertIn("FileProvider.getUriForFile", self.java)
        self.assertIn(
            'implementation("androidx.core:core:1.17.0")',
            self.gradle,
        )


if __name__ == "__main__":
    unittest.main()
