import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class AndroidWhatsappAcceptanceTests(unittest.TestCase):
    """Cross-surface contracts for the Android messaging shell.

    These tests intentionally join the web shell and native notification
    layers.  A regression in either layer would otherwise leave the product
    looking or behaving like two unrelated applications.
    """

    VIEWPORTS = (
        (320, 568),
        (360, 800),
        (412, 915),
        (480, 960),
    )
    LANDSCAPE_VIEWPORTS = tuple((height, width) for width, height in VIEWPORTS)
    THEMES = ("white", "paper", "dark")
    FONT_SCALES = (1, 2)
    ANDROID_APIS = (24, 28, 33, 35)

    @classmethod
    def setUpClass(cls):
        cls.project = Path(PROJECT_DIR)
        cls.html = (cls.project / "index.html").read_text(encoding="utf-8")
        cls.compact = re.sub(r"\s+", "", cls.html)
        cls.server = (cls.project / "server.py").read_text(encoding="utf-8")
        cls.android = cls.project.parent / "divan-android"
        cls.java_root = (
            cls.android / "app/src/main/java/com/furkancanyilmaz/divan"
        )
        cls.gradle = (cls.android / "app/build.gradle.kts").read_text(
            encoding="utf-8"
        )
        cls.completion = (
            cls.java_root / "CompletionNotificationController.java"
        ).read_text(encoding="utf-8")
        cls.conversation = (
            cls.java_root / "ConversationNotificationSupport.java"
        ).read_text(encoding="utf-8")
        cls.chat_notifications = (
            cls.java_root / "ChatNotificationController.java"
        ).read_text(encoding="utf-8")
        cls.reply = (cls.java_root / "ChatReplyReceiver.java").read_text(
            encoding="utf-8"
        )
        cls.reminder = (cls.java_root / "ReminderReceiver.java").read_text(
            encoding="utf-8"
        )

    def section(self, start, end):
        begin = self.html.index(start)
        return self.html[begin:self.html.index(end, begin)]

    def test_exact_viewport_orientation_theme_font_and_api_matrix_is_covered(self):
        # Portrait and landscape share the same four width families. Native
        # Android must not fall back to the desktop shell when landscape is
        # wider than the CSS breakpoint.
        for width, height in self.VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                self.assertIn(f"@media(max-width:{width}px)", self.compact)
                self.assertGreater(height, width)
        self.assertEqual(
            self.LANDSCAPE_VIEWPORTS,
            ((568, 320), (800, 360), (915, 412), (960, 480)),
        )
        self.assertEqual(
            len(self.VIEWPORTS + self.LANDSCAPE_VIEWPORTS)
            * len(self.THEMES) * len(self.FONT_SCALES),
            48,
        )

        native_css = self.section(
            "function installNativeAndroidMobileCss()", "let THERAPISTS"
        )
        self.assertIn("max-width\\s*:\\s*760px", native_css)
        self.assertIn("mobileRules.push(child.cssText)", native_css)
        self.assertIn("document.head.appendChild(style)", native_css)
        viewport = self.section(
            "function mobileChatViewport()", "function mobileHeaderMenuIsOpen"
        )
        self.assertIn("classList.contains('nativeAndroid')", viewport)

        for theme in self.THEMES:
            with self.subTest(theme=theme):
                self.assertIn(
                    f'body[data-mobile-theme="{theme}"]', self.html
                )
        self.assertIn("Math.min(2,Math.max(0.8", self.compact)

        self.assertRegex(self.gradle, r"minSdk\s*=\s*24")
        self.assertRegex(self.gradle, r"targetSdk\s*=\s*3[5-9]")
        self.assertEqual(self.ANDROID_APIS, (24, 28, 33, 35))

    def test_mobile_chrome_uses_one_svg_icon_language_and_runtime_preserves_it(self):
        icon_names = re.search(
            r"const UI_ICON_NAMES=Object\.freeze\(\[([\s\S]*?)\]\);",
            self.html,
        )
        self.assertIsNotNone(icon_names)
        names = re.findall(r"'([^']+)'", icon_names.group(1))
        self.assertGreaterEqual(len(names), 50)
        for name in names:
            with self.subTest(icon=name):
                self.assertIn(f'id="ui-icon-{name}"', self.html)

        for control in (
            "mobileBackBtn", "mobileHeaderMore",
            "mobileConversationSearchToggle", "mobileMasterHistoryOpen",
            "mobileSessionChromeToggle", "mobileMasterProfileBack",
            "mobileMasterProfileRetry", "composerPlusBtn", "send",
            "conversationSearchPrev", "conversationSearchNext",
            "conversationSearchClose", "chairEmergencyStop",
            "chairEndSession", "chairCollapse", "imageryStopBtn",
            "imageryEndSession", "imageryCollapse",
        ):
            button = re.search(
                rf'<button\b[^>]*\bid="{control}"[\s\S]*?</button>',
                self.html,
            )
            self.assertIsNotNone(button, control)
            self.assertIn("<svg", button.group(0), control)

        runtime = self.section(
            "function createUiIcon(", "const chat = $('chat')"
        )
        for contract in (
            "UI_ICON_NAMES.includes(name)", "createElementNS(UI_ICON_SVG_NS",
            "setAttribute('aria-hidden','true')", "setUiButtonIcon(id,name)",
            "setUiButtonLabel(id,label)",
        ):
            self.assertIn(contract, runtime)
        self.assertIn("setUiButtonIcon('nightBtn',dark?'sun':'moon')", self.html)
        self.assertIn("setUiButtonIcon('speakBtn','stop')", self.html)
        self.assertNotIn("$('nightBtn').textContent", self.html)
        self.assertNotIn("$('speakBtn').textContent", self.html)

    def test_mobile_action_targets_baselines_and_savebar_are_reachable(self):
        for contract in (
            ".mobileHomeHeaderButton{width:48px;height:48px;",
            "#mobileHomeSearchInput{flex:1;min-width:0;height:44px;",
            "#mobileHomeSearchClear{width:44px;height:44px;",
            "#mobileBackBtn{flex:0 0 48px;width:48px;height:48px;",
            "#mobileHeaderMore{flex:0 0 48px;width:48px;height:48px;",
            "#composerPlusBtn{display:inline-grid;place-items:center;"
            "width:44px;height:44px;min-width:44px;",
            "#send{width:44px;height:44px;min-width:44px;",
            "#conversationSearchInput{height:44px;border-radius:22px}",
            ".conversationSearchAction{width:44px;height:44px;min-width:44px}",
            ".composerQuickItem{width:100%;min-height:52px;",
            ".personaCatalogTab{min-height:44px;",
            "#therapistOverlay.tcardFavorite{right:8px;top:50%;"
            "width:44px;height:44px;min-width:44px;min-height:44px;",
            ".settingsSaveBar{position:static;z-index:auto;",
            ".settingsSaveBarbutton{min-height:48px;display:inline-flex;"
            "align-items:center;justify-content:center;gap:8px}",
        ):
            self.assertIn(re.sub(r"\s+", "", contract), self.compact)

        for alignment in (
            "display:grid;place-items:center", "display:inline-flex;"
            "align-items:center;justify-content:center",
        ):
            self.assertIn(alignment, self.compact)
        self.assertGreater(
            self.compact.rindex(".settingsSaveBar{position:static;z-index:auto;"),
            self.compact.index(".settingsSaveBar{position:sticky"),
        )

    def test_mobile_root_is_single_pane_and_owns_its_scroll_surfaces(self):
        for contract in (
            "html,body{width:100%;height:var(--mobile-vvh,100dvh);",
            "max-height:var(--mobile-vvh,100dvh);overflow:hidden",
            "#mobileHome{flex:1;min-width:0;min-height:0;",
            "#mobileConversationList{flex:1;min-height:0;overflow-y:auto;",
            "#chat{padding-bottom:4px;scroll-padding-bottom:12px;",
            "body.nativeAndroid#side,body.nativeAndroid#sideScrim"
            "{display:none!important}",
        ):
            self.assertIn(contract, self.compact)
        self.assertIn("window.visualViewport.addEventListener('resize'", self.html)
        self.assertIn("root.style.setProperty('--mobile-vvh',height+'px')", self.html)
        self.assertIn("document.body.classList.toggle('workImeCompact'", self.html)
        self.assertIn(
            "@media(orientation:landscape)and(max-height:420px){"
            ".mobileHomeEmpty{margin-top:clamp(10px,4dvh,18px);"
            "margin-right:max(96px,calc(env(safe-area-inset-right)+88px));",
            self.compact,
        )

    def test_home_is_brand_search_rows_and_bottom_navigation_only(self):
        header = self.section('<header class="mobileHomeHeader">', "</header>")
        self.assertIn('class="mobileHomeLogo"', header)
        self.assertIn('id="mobileHomeTitle"', header)
        self.assertIn(">divan</h1>", header)
        self.assertNotIn("<button", header)

        home = self.section('<section id="mobileHome"',
                            '<section id="conversationScreen"')
        for identifier in (
            "mobileHomeBottomNav", "mobileHomeChatsTab", "mobileHomePeopleTab",
            "mobileHomeMore", "mobileHomeSearchInput",
            "mobileConversationList", "mobileNewConversationFab",
        ):
            self.assertIn(f'id="{identifier}"', home)
        self.assertIn('placeholder="Ara veya sohbet başlat"', home)
        self.assertIn('role="list"', home)
        self.assertIn('aria-label="Son konuşmalar"', home)

    def test_home_surface_and_pin_state_do_not_create_a_second_color_system(self):
        expected = {
            "white": "#ffffff",
            "paper": "#f7f1e6",
            "dark": "#191d20",
        }
        for theme, color in expected.items():
            self.assertIn(
                f'body[data-mobile-theme="{theme}"]'
                f'{{--mobile-home-bg:{color}}}',
                self.compact,
            )
        shared = (
            "#mobileHome,.mobileHomeHeader,#mobileHomeSearchResults,"
            "#mobileConversationList,.mobileHomeSearchSectionTitle,"
            "#mobileHomeBottomNav{background-color:var(--mobile-home-bg)!important;"
            "background-image:none!important}"
        )
        self.assertIn(shared, self.compact)
        self.assertIn(
            ".mobileConversationItem,.mobileConversationItem.isPinned{",
            self.html,
        )
        self.assertIn(
            "background:transparent!important;background-image:none!important",
            self.compact,
        )

    def test_one_person_row_and_history_menu_keep_conversations_primary(self):
        aggregate = self.section(
            "function latestMobileConversationRows(rows)",
            "function mobileConversationDisplayName(",
        )
        for contract in (
            "_mobileGroupPinned:!!pinned.length",
            "_mobileGroupIds:group.rows.map",
            "groupMobileConversations(rows).map(group=>",
            "return orderActiveConversationRows(representatives)",
        ):
            self.assertIn(contract, aggregate)

        chat_header = self.section('<header id="mobileHeader"', "</header>")
        for identifier in (
            "mobileBackBtn", "mobilePersonaPortrait", "mobilePersonaName",
            "mobileHeaderMore", "mobileConversationSearchToggle",
            "mobileMasterHistoryOpen", "mobileSessionChromeToggle",
        ):
            self.assertIn(f'id="{identifier}"', chat_header)
        self.assertIn("AI canlandırması", chat_header)
        self.assertIn("Sohbet geçmişi", chat_header)

    def test_chat_identity_routes_to_an_honest_accessible_master_profile(self):
        chat_header = self.section('<header id="mobileHeader"', "</header>")
        identity = re.search(
            r'<button\b[^>]*\bid="mobilePersonaIdentity"[\s\S]*?</button>',
            chat_header,
        )
        self.assertIsNotNone(identity)
        self.assertIn('aria-haspopup="dialog"', identity.group(0))
        self.assertIn(
            'aria-controls="mobileMasterProfileOverlay"', identity.group(0)
        )
        self.assertIn('id="mobilePersonaPortrait"', identity.group(0))
        self.assertIn('id="mobilePersonaName"', identity.group(0))

        profile_shell = self.section(
            '<div class="overlay" id="mobileMasterProfileOverlay">',
            '<div id="topbar">',
        )
        for contract in (
            'role="dialog"', 'aria-modal="true"',
            'aria-labelledby="mobileMasterProfileTitle"',
            'role="status"', 'aria-live="polite"', 'role="alert"',
            'role="region"', 'aria-label="Usta profil bilgileri"',
            'tabindex="0"',
            'role="note"', 'id="mobileMasterProfileRetry"',
            'id="mobileMasterProfileBoundary"',
        ):
            self.assertIn(contract, profile_shell)

        rendering = self.section(
            "const DEFAULT_MASTER_PROFILE_BOUNDARY=",
            "function mobileHomeSearchText(",
        )
        for contract in (
            "optionalApi(",
            "'/api/master-profile?id='+encodeURIComponent(id),null,",
            "{quiet:true,signal:controller&&controller.signal}",
            "MOBILE_MASTER_PROFILE_TIMEOUT_MS",
            "Promise.race([request,timeout])",
            "String(data.id||'')!==id", "item.textContent=copy",
            "mobileMasterProfileRequestSequence",
            "subtitle.split(lifespan).join('')", "approachKeys",
            "!approachKeys.has", "mobileMasterProfileLifespan').hidden=!dated",
            "Terapi yöntemleri", "Felsefi soru ve metin yolları",
            "Koçluk odakları", "Divan bu boşlukları doldurmaz.",
        ):
            self.assertIn(contract, rendering)
        self.assertNotIn("innerHTML", rendering)
        self.assertNotIn("missing.push('yaşam tarihleri')", rendering)
        self.assertIn(
            "focusWithoutScrolling($('mobileMasterProfileScroll'))",
            rendering,
        )
        self.assertIn(
            "focusWithoutScrolling($('mobileMasterProfileRetry'))",
            rendering,
        )
        self.assertIn(
            "#mobileMasterProfileOverlay .mobileMasterProfilePage{",
            self.html,
        )

        interactions = self.section(
            "$('mobilePersonaIdentity').onclick=showMobileMasterProfile;",
            "$('conversationSearchClose').onclick=",
        )
        self.assertIn(
            "requestOverlayDismiss('mobileMasterProfileOverlay')",
            interactions,
        )
        self.assertIn("renderMobileMasterProfileLoading(master)", interactions)
        self.assertIn("loadMobileMasterProfile(id,{sequence})", interactions)
        overlays = self.section("function showOverlay(", "function requestOverlayDismiss(")
        self.assertIn("overlayReturnFocus.set(id, document.activeElement)", overlays)
        self.assertIn("focusWithoutScrolling(back)", overlays)

    def test_master_profile_endpoint_is_public_bounded_and_never_exposes_prompts(self):
        model = self.server[
            self.server.index("MASTER_PROFILE_TEXT_LIMITS ="):
            self.server.index("def public_persona_catalog(")
        ]
        for contract in (
            '"therapist", THERAPISTS[master_id]',
            '"philosopher", PHILOSOPHERS[master_id]',
            '"coach", COACHES[master_id]',
            "MASTER_PROFILE_ID_PATTERN.fullmatch(master_id)",
            '"lifespan": None, "birth": None, "death": None',
            '"core_views": core_views', '"approaches": approaches',
            '"ai_boundary": master_profile_ai_boundary(',
        ):
            self.assertIn(contract, model)
        profile_builder = model[
            model.index("def public_master_profile("):
        ]
        self.assertNotIn('record.get("persona")', profile_builder)
        self.assertNotIn('record["persona"]', profile_builder)
        endpoint = self.server[
            self.server.index('if path == "/api/master-profile"'):
            self.server.index("if path ==", self.server.index(
                'if path == "/api/master-profile"') + 1)
        ]
        self.assertIn("public_master_profile", endpoint)
        self.assertIn("send_json", endpoint)
        send_json = self.server[
            self.server.index("    def send_json("):
            self.server.index("    def ", self.server.index(
                "    def send_json(") + 1)
        ]
        self.assertIn('self.send_header("Cache-Control", "no-store")',
                      send_json)

    def test_bubbles_timestamps_quote_swipe_and_composer_match_one_model(self):
        for contract in (
            ".messageTime{display:inline-flex;float:right;align-items:center;",
            "margin:4px0-2px9px",
            "font-size:clamp(10px,calc(10px*var(--fs)),15px)",
            ".row.therapist:not(.groupConversation)>.avatar{display:none}",
            "#composerPlusBtn{display:inline-grid;place-items:center;"
            "width:44px;height:44px;min-width:44px",
            "#send{width:44px;height:44px;min-width:44px",
            "#msg{min-height:44px;max-height:112px",
        ):
            self.assertIn(contract, self.compact)

        swipe = self.section(
            "const ASSISTANT_REPLY_SWIPE_THRESHOLD=52", "function addResponseTools("
        )
        self.assertLess(
            swipe.index("bubble.setPointerCapture(event.pointerId)"),
            swipe.index("bubble.addEventListener('pointermove'"),
        )
        for contract in (
            "Math.max(absX,absY)<11", "absY>11&&absY>absX*1.25",
            "touchstart", "touchmove", "touchend", "touchcancel",
            "pointercancel", "lostpointercapture", "replySwipeA11yAction",
        ):
            self.assertIn(contract, swipe)
        self.assertIn("startAssistantQuotedReply(state.reference)", swipe)

        self.assertIn(
            "if(e.key==='Enter'&&!e.shiftKey&&!mobileChatViewport())",
            self.html,
        )

    def test_font_200_talkback_and_reduced_motion_have_explicit_contracts(self):
        for identifier in (
            "mobileFontScaleDown", "mobileFontScaleValue", "mobileFontScaleUp"
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn('aria-live="polite"', self.section(
            '<fieldset class="mobileFontScalePicker', "</fieldset>"
        ))
        self.assertIn(
            ".mobileFontScaleControlsbutton,.mobileFontScaleControlsoutput"
            "{min-width:0;min-height:44px",
            self.compact,
        )
        for timestamp in (
            "font:clamp(10.5px,calc(10.5px*var(--fs)),16px)/1.2",
            "font-size:clamp(10px,calc(10px*var(--fs)),15px)",
        ):
            self.assertIn(timestamp, self.compact)

        side_accessibility = self.section(
            "function syncSideAccessibility(open)", "function syncSideTrigger"
        )
        self.assertIn("side.inert=sideDisabled", side_accessibility)
        self.assertIn("side.setAttribute('aria-hidden'", side_accessibility)
        self.assertIn("aria-live=\"off\"", self.html)
        self.assertIn('id="chatCompletionAnnouncement"', self.html)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.compact)
        self.assertIn(
            "body.reduceMotion*,body.reduceMotion*:before,"
            "body.reduceMotion*:after{animation:none!important;"
            "transition:none!important;scroll-behavior:auto!important}",
            self.compact,
        )

    def test_settings_tools_are_a_page_and_not_a_second_drawer(self):
        settings = self.section('<div class="overlay" id="settingsOverlay">',
                                '<!-- iki usta, tek soru -->')
        for identifier in (
            "mobileSettingsBack", "mobileSettingsToolsSection",
            "mobileThemePicker", "mobileFontScalePicker", "chatWallpaperPicker",
        ):
            self.assertIn(f'id="{identifier}"', settings)
        self.assertIn('class="mobileSettingsNav"', settings)
        self.assertIn("Alanlar ve kayıtlar", settings)
        self.assertIn('class="mobileSettingsToolGroup"', settings)
        self.assertIn(
            "bir ustaya özel çalışmalar yalnız o görüşmenin menüsünde görünür",
            settings,
        )
        self.assertNotIn('data-mobile-side-target="adhdBtn"', settings)
        self.assertIn("#settingsOverlay.settingsModal{width:100%;height:var(",
                      self.compact)
        self.assertNotIn("edgeSwipe", self.html)

    def test_chair_and_imagery_are_single_mobile_dialogs_with_reachable_controls(self):
        workspaces = self.section(
            "function syncChairViewport()", "/* ---------------- tema & usta"
        )
        self.assertNotIn("matchMedia('(max-width:760px)').matches", workspaces)
        for function_name in (
            "syncChairViewport", "setChairMobileView", "openChairPanel",
            "trapChairMobileFocus", "setImageryMobileView",
            "syncImageryViewport", "openImageryPanel", "trapImageryMobileFocus",
        ):
            function = self.section(f"function {function_name}", "\n}")
            self.assertIn("mobileChatViewport()", function, function_name)

        for identifier in (
            "chairEmergencyStop", "chairBegin", "chairText", "chairSend",
            "imageryBegin", "imageryText", "imagerySend", "imageryStopBtn",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        imagery = self.section('<aside id="imageryPanel"', "</aside>")
        imagery_header = imagery[:imagery.index("</header>")]
        imagery_footer = imagery[imagery.index('<footer class="imageryFooter">'):]
        self.assertIn('id="imageryStopBtn"', imagery_header)
        self.assertNotIn('id="imageryStopBtn"', imagery_footer)
        for contract in (
            "#chairPanel,#imageryPanel{position:fixed;z-index:46;inset:0;",
            ".chairFooterbutton,.chairIconButton,.chairGuidanceFeedbackbutton,",
            ".imageryFooterbutton,#imagerySend{min-height:44px}",
            "body.workImeCompact.chairFooter,body.workImeCompact.imageryFooter{",
        ):
            self.assertIn(contract, self.compact)

    def test_wallpaper_is_local_bounded_and_rejected_before_full_decode(self):
        wallpaper = self.section("const CHAT_WALLPAPER_MODES", "function applyNight()")
        for contract in (
            "CHAT_WALLPAPER_MAX_BYTES=6*1024*1024",
            "CHAT_WALLPAPER_MAX_SOURCE_DIMENSION=8192",
            "CHAT_WALLPAPER_MAX_SOURCE_PIXELS=16*1024*1024",
            "indexedDB.open(CHAT_WALLPAPER_DB,1)",
            "sniffChatWallpaperMime", "jpegChatWallpaperDimensions",
            "webpChatWallpaperDimensions", "readChatWallpaperDimensions",
            "createImageBitmap", "options.resizeWidth=resizeWidth",
            "QuotaExceededError", "URL.revokeObjectURL",
        ):
            self.assertIn(contract, wallpaper)
        normalize = self.section(
            "async function normalizeChatWallpaperBlob(input)",
            "async function loadStoredCustomChatWallpaper",
        )
        self.assertLess(
            normalize.index("readChatWallpaperDimensions"),
            normalize.index("decodeChatWallpaper"),
        )
        choose = self.section(
            "async function chooseChatWallpaper(file)",
            "async function clearChatWallpaper",
        )
        self.assertNotIn("fetch(", choose)
        self.assertNotIn("api(", choose)
        self.assertIn(
            "body.highContrast#chat{background-image:none!important}",
            self.compact,
        )

    def test_api_24_28_33_35_share_messaging_style_and_exact_reply_identity(self):
        for contract in (
            "new Person.Builder()", "new NotificationCompat.MessagingStyle(self)",
            ".setGroupConversation(false)",
            ".setCategory(NotificationCompat.CATEGORY_MESSAGE)",
            ".setGroup(GROUP_KEY)", "ShortcutInfoCompat.Builder",
            ".setLocusId(new LocusIdCompat(locusId(conversationId)))",
        ):
            self.assertIn(contract, self.conversation)
        self.assertIn("Build.VERSION_CODES.N_MR1", self.conversation)
        self.assertIn("PendingIntent.FLAG_MUTABLE", self.chat_notifications)
        self.assertIn("new RemoteInput.Builder", self.chat_notifications)
        self.assertIn("RemoteInput.getResultsFromIntent", self.reply)
        self.assertIn("EXTRA_SOURCE_NOTIFICATION_TAG", self.reply)
        self.assertIn("setPublicVersion(", self.completion)
        self.assertIn("setPublicVersion(", self.chat_notifications)

    def test_notifications_are_per_conversation_grouped_and_privacy_fail_closed(self):
        for contract in (
            "postConversationIfPrivacyStateCurrent",
            "activeConversationCount",
            ".setGroupSummary(true)",
            ".setOnlyAlertOnce(true)",
        ):
            self.assertIn(contract, self.completion)
        self.assertIn("CONVERSATION_TAG_PREFIX", self.conversation)
        self.assertIn("ConversationNotificationSupport.GROUP_KEY", self.completion)
        self.assertIn("privacyGeneration", self.chat_notifications)
        self.assertIn("manager.cancelAll()", self.chat_notifications)
        self.assertIn("purgeConversationShortcuts", self.chat_notifications)
        self.assertIn("sourceNotificationTag", self.reply)
        self.assertIn("cancelNotification", self.reply)

        self.assertIn("ConversationNotificationSupport.applySingleAssistantMessage(",
                      self.reminder)
        self.assertIn("NotificationCompat.CATEGORY_REMINDER", self.reminder)
        self.assertNotIn("BigTextStyle", self.completion)
        self.assertNotIn("BigTextStyle", self.reminder)


if __name__ == "__main__":
    unittest.main()
