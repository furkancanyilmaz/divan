import json
import re
import subprocess
import unittest
from pathlib import Path

from support import PROJECT_DIR


class AndroidWhatsappFamiliarThemeSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = (Path(PROJECT_DIR) / "index.html").read_text(
            encoding="utf-8")
        cls.compact = re.sub(r"\s+", "", cls.html)

    def section(self, start, end):
        first = self.html.index(start)
        return self.html[first:self.html.index(end, first)]

    def test_home_header_is_brand_only_and_navigation_is_at_bottom(self):
        header = self.section(
            '<header class="mobileHomeHeader">', '</header>')
        self.assertIn('class="mobileHomeLogo"', header)
        self.assertIn('>divan</h1>', header)
        self.assertNotIn('<button', header)
        self.assertNotIn('mobileHomeMore', header)
        self.assertIn('id="mobileHomeBottomNav"', self.html)
        for control in (
                "mobileHomeChatsTab", "mobileHomePeopleTab",
                "mobileHomeMore", "mobileHomeMenuScrim"):
            self.assertIn(f'id="{control}"', self.html)
        self.assertIn(
            "#mobileHomeBottomNav{position:absolute;z-index:23;",
            self.compact)
        self.assertIn(
            "bottom:calc(68px+env(safe-area-inset-bottom))", self.compact)

    def test_home_header_list_search_and_nav_share_exact_surface_token(self):
        for theme, color in (
                ("white", "#ffffff"), ("paper", "#f7f1e6"),
                ("dark", "#191d20")):
            self.assertIn(
                f'body[data-mobile-theme="{theme}"]'
                f'{{--mobile-home-bg:{color}}}',
                self.compact)
        shared = (
            "#mobileHome,.mobileHomeHeader,#mobileHomeSearchResults,"
            "#mobileConversationList,.mobileHomeSearchSectionTitle,"
            "#mobileHomeBottomNav{"
            "background-color:var(--mobile-home-bg)!important;"
            "background-image:none!important}"
        )
        self.assertIn(shared, self.compact)
        self.assertIn(
            ".mobileConversationItem,.mobileConversationItem.isPinned{",
            self.html)
        self.assertIn(
            "background:transparent!important;background-image:none!important",
            self.compact)

    def test_pin_is_a_person_group_property_without_a_tinted_row(self):
        aggregate = self.section(
            "function latestMobileConversationRows(rows)",
            "function mobileConversationDisplayName(")
        for contract in (
                "group.rows.filter(row=>!!row.pinned_at)",
                "_mobileGroupPinned:!!pinned.length",
                "_mobileGroupIds:group.rows.map"):
            self.assertIn(contract, aggregate)
        pinning = self.section(
            "async function pinSelectedMobileConversations()",
            "function clearConversationListError")
        self.assertIn("rows.flatMap(row=>", pinning)
        self.assertIn("row._mobileGroupIds", pinning)
        sorter = self.section(
            "function orderActiveConversationRows(rows)",
            "function mobileConversationGroupKey")
        self.assertLess(sorter.index("pinOrder"), sorter.index("stateOrder"))

    def test_native_android_keeps_mobile_shell_in_landscape_and_hides_sidebar(self):
        bootstrap = self.section(
            "function installNativeAndroidMobileCss()",
            "let THERAPISTS")
        self.assertIn("DivanNative.platform!=='android'", bootstrap)
        self.assertIn("max-width\\s*:\\s*760px", bootstrap)
        self.assertIn("mobileRules.push(child.cssText)", bootstrap)
        self.assertIn("document.head.appendChild(style)", bootstrap)
        viewport = self.section(
            "function mobileChatViewport()", "function mobileHeaderMenuIsOpen")
        self.assertIn("classList.contains('nativeAndroid')", viewport)
        self.assertIn(
            "body.nativeAndroid#side,body.nativeAndroid#sideScrim"
            "{display:none!important}", self.compact)
        accessibility = self.section(
            "function syncSideAccessibility(open)",
            "function syncSideTrigger")
        self.assertIn("mobileChatViewport()", accessibility)
        self.assertIn("side.inert=sideDisabled", accessibility)
        self.assertIn("aria-hidden", accessibility)

    def test_native_android_workspaces_share_the_mobile_viewport_contract(self):
        workspaces = self.section(
            "function syncChairViewport()", "/* ---------------- tema & usta")
        self.assertNotIn("matchMedia('(max-width:760px)').matches", workspaces)
        for function_name in (
                "syncChairViewport", "setChairMobileView",
                "openChairPanel", "collapseChairPanel",
                "trapChairMobileFocus", "setImageryMobileView",
                "syncImageryViewport", "openImageryPanel",
                "collapseImageryPanel", "trapImageryMobileFocus"):
            function = self.section(
                f"function {function_name}", "\n}")
            self.assertIn("mobileChatViewport()", function, function_name)
        resize = self.section(
            "addEventListener('resize',()=>{", "$('sessionPathOpen')")
        self.assertIn("syncChairViewport();syncImageryViewport();", resize)

    def test_reply_swipe_has_down_capture_touch_fallback_and_live_animation(self):
        swipe = self.section(
            "const ASSISTANT_REPLY_SWIPE_THRESHOLD=52",
            "function addResponseTools(")
        self.assertLess(
            swipe.index("bubble.setPointerCapture(event.pointerId)"),
            swipe.index("bubble.addEventListener('pointermove'"))
        self.assertIn("Math.max(absX,absY)<11", swipe)
        self.assertIn("absY>11&&absY>absX*1.25", swipe)
        self.assertIn("state.distance+'px'", swipe)
        self.assertIn("progress*7", swipe)
        for event in (
                "touchstart", "touchmove", "touchend", "touchcancel",
                "pointercancel", "lostpointercapture"):
            self.assertIn(event, swipe)
        self.assertIn("replySwipeA11yAction", swipe)
        self.assertIn(
            ".row.therapist.replySwipeTracking.bubble.replySwipeEnabled"
            "{transition:none", self.compact)
        self.assertIn(
            "touch-action:pan-ypinch-zoom", self.compact)

    def test_wallpaper_is_validated_downsampled_and_stored_as_indexeddb_blob(self):
        for control in (
                "chatWallpaperPicker", "chatWallpaperChoose",
                "chatWallpaperClear", "chatWallpaperFile",
                "chatWallpaperStatus"):
            self.assertIn(f'id="{control}"', self.html)
        wallpaper = self.section(
            "const CHAT_WALLPAPER_MODES",
            "function applyNight()")
        for contract in (
                "CHAT_WALLPAPER_MAX_BYTES=6*1024*1024",
                "CHAT_WALLPAPER_MAX_DIMENSION=4096",
                "CHAT_WALLPAPER_MAX_PIXELS=12*1024*1024",
                "CHAT_WALLPAPER_MAX_SOURCE_DIMENSION=8192",
                "CHAT_WALLPAPER_MAX_SOURCE_PIXELS=16*1024*1024",
                "indexedDB.open(CHAT_WALLPAPER_DB,1)",
                "sniffChatWallpaperMime",
                "bytes[0]===0x89", "bytes[0]===0xff",
                "ascii.slice(0,4)==='RIFF'",
                "jpegChatWallpaperDimensions",
                "webpChatWallpaperDimensions",
                "readChatWallpaperDimensions",
                "createImageBitmap", "context.drawImage",
                "options.resizeWidth=resizeWidth",
                "canvasWallpaperBlob", "QuotaExceededError",
                "URL.createObjectURL", "URL.revokeObjectURL"):
            self.assertIn(contract, wallpaper)
        normalize = self.section(
            "async function normalizeChatWallpaperBlob(input)",
            "async function loadStoredCustomChatWallpaper")
        self.assertLess(
            normalize.index("readChatWallpaperDimensions"),
            normalize.index("decodeChatWallpaper"))
        choose = self.section(
            "async function chooseChatWallpaper(file)",
            "async function clearChatWallpaper")
        self.assertNotIn("api(", choose)
        self.assertNotIn("fetch(", choose)
        self.assertNotIn("readAsDataURL", wallpaper)
        self.assertNotIn("localStorage.setItem('chatWallpaperImage", wallpaper)
        self.assertIn(
            "awaitclearChatWallpaper({announce:false})", self.compact)

    def test_wallpaper_dimension_bomb_is_rejected_before_decode(self):
        helpers = self.section(
            "async function sniffChatWallpaperMime(blob)",
            "function decodeChatWallpaper(blob")
        normalize = self.section(
            "async function normalizeChatWallpaperBlob(input)",
            "async function loadStoredCustomChatWallpaper")
        probe = f"""
const CHAT_WALLPAPER_MAX_BYTES=6*1024*1024;
const CHAT_WALLPAPER_MAX_DIMENSION=4096;
const CHAT_WALLPAPER_MAX_PIXELS=12*1024*1024;
const CHAT_WALLPAPER_MAX_SOURCE_DIMENSION=8192;
const CHAT_WALLPAPER_MAX_SOURCE_PIXELS=16*1024*1024;
{helpers}
let decodeCalls=0;
async function decodeChatWallpaper(){{decodeCalls++;throw new Error('decoded');}}
async function canvasWallpaperBlob(){{throw new Error('canvas');}}
{normalize}
(async()=>{{
  const bytes=new Uint8Array(24);
  bytes.set([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a],0);
  bytes.set([0x49,0x48,0x44,0x52],12);
  const view=new DataView(bytes.buffer);
  view.setUint32(16,65535);view.setUint32(20,65535);
  const input=new Blob([bytes],{{type:'image/png'}});
  const dimensions=await readChatWallpaperDimensions(input,'image/png');
  let error='';
  try{{await normalizeChatWallpaperBlob(input);}}catch(reason){{
    error=String(reason&&reason.message||reason);
  }}
  process.stdout.write(JSON.stringify({{dimensions,decodeCalls,error}}));
}})().catch(error=>{{console.error(error);process.exit(1);}});
"""
        result = subprocess.run(
            ["node", "-e", probe], check=True, text=True,
            capture_output=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["dimensions"], {"width": 65535, "height": 65535})
        self.assertEqual(payload["decodeCalls"], 0)
        self.assertIn("güvenle işlenemeyecek kadar büyük", payload["error"])

    def test_wallpaper_presets_are_images_and_high_contrast_removes_them(self):
        self.assertIn(
            'body[data-chat-wallpaper="dots"]#chat{'
            'background-image:url("data:image/svg+xml,', self.compact)
        self.assertIn(
            'body[data-chat-wallpaper="lines"]#chat{'
            'background-image:url("data:image/svg+xml,', self.compact)
        self.assertIn(
            "body.highContrast#chat{background-image:none!important}",
            self.compact)

    def test_streaming_log_announces_only_completion_not_each_token(self):
        chat = self.section(
            '<div id="chat" data-testid="chat" role="log"',
            '<button type="button" id="scrollToLatestBtn"')
        self.assertIn('aria-live="off"', chat)
        self.assertIn('aria-relevant="additions"', chat)
        self.assertIn('id="chatCompletionAnnouncement"', chat)
        self.assertIn("function announceChatCompletion()", self.html)
        self.assertIn("Ustanın yanıtı hazır.", self.html)

    def test_master_picker_is_a_flat_single_row_catalog_on_mobile(self):
        for declaration in (
                "#therapistOverlay#therapistGrid{display:block;",
                "grid-template-columns:52pxminmax(0,1fr)",
                "grid-template-rows:autoautoauto",
                "text-overflow:ellipsis;white-space:nowrap",
                "#therapistOverlay.tcard:hover{transform:none;box-shadow:none}"):
            self.assertIn(declaration, self.compact)

    def test_320_360_412_480_and_200_percent_font_contracts(self):
        for width in (320, 360, 412, 480):
            self.assertIn(f"@media(max-width:{width}px)", self.compact)
        self.assertIn("fontScale=Math.min(2,Math.max(0.8", self.compact)
        self.assertIn(
            "font-size:clamp(11.5px,calc(11.5px*var(--fs)),18px)",
            self.compact)
        for control in (
                "mobileFontScalePicker", "mobileFontScaleDown",
                "mobileFontScaleValue", "mobileFontScaleUp"):
            self.assertIn(f'id="{control}"', self.html)
        font_controls = self.section(
            '<fieldset class="mobileFontScalePicker', '</fieldset>')
        self.assertIn('aria-live="polite"', font_controls)
        self.assertIn('aria-atomic="true"', font_controls)
        self.assertIn("%80 ile %200", font_controls)
        self.assertIn(
            ".mobileFontScaleControlsbutton,.mobileFontScaleControlsoutput"
            "{min-width:0;min-height:44px", self.compact)
        self.assertIn(
            ".chatWallpaperOptions{grid-template-columns:repeat(2,minmax(0,1fr))}",
            self.compact)
        for timestamp in (
                "font:clamp(10.5px,calc(10.5px*var(--fs)),16px)/1.2",
                "font-size:clamp(10px,calc(10px*var(--fs)),15px)"):
            self.assertIn(timestamp, self.compact)
        self.assertIn('placeholder="Ara veya sohbet başlat"', self.html)
        scale = self.section("function applyFontScale()", "applyFontScale();")
        self.assertIn("mobileValue.textContent=Math.round(fontScale*100)+'%'", scale)
        self.assertIn("mobileDown.disabled=fontScale<=0.8", scale)
        self.assertIn("mobileUp.disabled=fontScale>=2", scale)

    def test_single_person_chat_hides_repeated_message_avatars(self):
        self.assertIn(
            ".row.therapist:not(.groupConversation)>.avatar{display:none}",
            self.compact)
        bubble = self.section("function addBubble(role, html", "function renderConversationMessage")
        self.assertIn("row.classList.toggle('groupConversation'", bubble)
        self.assertIn("convData.submode==='konsey'", bubble)

    def test_imagery_stop_stays_in_fixed_header_above_scrollable_ime_actions(self):
        imagery = self.section(
            '<aside id="imageryPanel"', '</aside>')
        header = imagery[:imagery.index('</header>')]
        footer = imagery[
            imagery.index('<footer class="imageryFooter">'):
            imagery.index('</footer>')]
        self.assertIn('id="imageryStopBtn"', header)
        self.assertIn('class="chairIconButton chairEmergencyStop"', header)
        self.assertIn(
            'aria-label="İmgelem çalışmasını hemen burada bırak"', header)
        self.assertNotIn('id="imageryStopBtn"', footer)
        self.assertLess(
            imagery.index('id="imageryStopBtn"'),
            imagery.index('class="imageryColumns"'))
        self.assertIn(
            "#chairPanel,#imageryPanel{position:fixed;z-index:46;inset:0;"
            "width:100%;height:var(--mobile-vvh,100dvh);",
            self.compact)
        self.assertIn(
            "body.workImeCompact.chairFooter,"
            "body.workImeCompact.imageryFooter{"
            "flex-wrap:nowrap;overflow-x:auto;",
            self.compact)
        self.assertIn(
            "#imageryStopBtn{flex:00auto;min-height:44px;"
            "white-space:nowrap;font-size:clamp(12px,"
            "calc(12px*var(--fs)),16px)}",
            self.compact)
        viewport = self.section(
            "function syncMobileViewportHeight()", "function mobileHomeIsOpen")
        self.assertIn("height<560", viewport)
        self.assertIn("workImeCompact", viewport)
        # 320×568 portrait uses the fixed header; 568×320 enters the IME/
        # short-height contract. Both retain a 44px stop at 200% scale.
        self.assertIn("@media(max-width:320px)", self.compact)
        self.assertIn("fontScale=Math.min(2,Math.max(0.8", self.compact)
        render = self.section(
            "function renderImageryWork()", "function applyImageryResponse")
        self.assertIn(
            "$('imageryStopBtn').disabled=readOnly||finished", render)
        self.assertIn(
            "$('imageryStopBtn').style.display=readOnly||finished?'none':''",
            render)
        self.assertNotIn("style.display=caps.stop", render)
        self.assertIn(
            "$('imageryStopBtn').onclick=()=>imageryAction(", self.compact)

    def test_master_history_secondary_text_respects_font_scale(self):
        for contract in (
                ".mobileMasterHistorySection{padding:10px14px5px;"
                "color:var(--ink-soft);font:600clamp(11px,"
                "calc(11px*var(--fs)),17px)/1.2",
                ".mobileMasterHistoryTime{color:var(--ink-soft);"
                "font:clamp(10.5px,calc(10.5px*var(--fs)),16px)/1.2",
                ".mobileMasterHistoryMeta{grid-column:1/3;"
                "color:var(--ink-soft);opacity:.84;font:clamp(10.5px,"
                "calc(10.5px*var(--fs)),16px)/1.2"):
            self.assertIn(contract, self.compact)

    def test_568x320_and_native_800x360_empty_state_clear_the_fab(self):
        short_landscape = (
            "@media(orientation:landscape)and(max-height:420px){"
            ".mobileHomeEmpty{"
            "margin-top:clamp(10px,4dvh,18px);"
            "margin-right:max(96px,calc(env(safe-area-inset-right)+88px));"
            "margin-bottom:12px;"
            "margin-left:max(12px,env(safe-area-inset-left));"
            "padding:12px14px}"
        )
        self.assertIn(short_landscape, self.compact)
        # The rule is height/orientation based rather than width-bound, so it
        # covers both 568×320 and a native-Android 800×360 landscape shell.
        self.assertNotIn(
            "@media(max-width:760px)and(orientation:landscape)and"
            "(max-height:420px)", self.compact)
        viewport = self.section(
            "function mobileChatViewport()", "function mobileHeaderMenuIsOpen")
        self.assertIn("classList.contains('nativeAndroid')", viewport)
        self.assertIn(
            "#mobileNewConversationFab{bottom:max(82px,"
            "calc(env(safe-area-inset-bottom)+76px));width:54px;height:54px",
            self.compact)
        # The 320px portrait branch remains independent of the landscape-only
        # clearance and therefore keeps its original full-width reflow.
        portrait = self.section(
            "@media(max-width:320px){", "@media(orientation:landscape)")
        self.assertNotIn("mobileHomeEmpty", portrait)

    def test_message_actions_are_contextual_bottom_sheet_and_back_closes(self):
        self.assertIn(
            ".bubble.messageActionsOpen>.responseTools{position:fixed;",
            self.compact)
        self.assertIn(
            ".bubble.messageActionsOpen:before{content:\"\";position:fixed;",
            self.compact)
        native_back = self.section(
            "window.divanNativeBack=()=>{", "window.divanAndroidBack=")
        self.assertIn("if(openMessageActionsBubble)", native_back)
        self.assertIn("setOpenMessageActionsBubble(null)", native_back)


if __name__ == "__main__":
    unittest.main()
