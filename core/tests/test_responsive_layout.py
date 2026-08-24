import re
import subprocess
import unittest
from pathlib import Path

from support import PROJECT_DIR


class ResponsiveLayoutSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")

    def css_block(self, selector):
        match = re.search(
            re.escape(selector) + r"\s*\{(?P<body>[^}]+)\}",
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, selector)
        return re.sub(r"\s+", "", match.group("body"))

    def between(self, start, end):
        left = self.html.index(start)
        return self.html[left:self.html.index(end, left)]

    def run_node(self, program):
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_flex_chain_can_shrink_inside_the_viewport(self):
        main = self.css_block("#main")
        self.assertIn("min-width:0", main)
        self.assertIn("overflow:hidden", main)

        topbar = self.css_block("#topbar")
        self.assertIn("min-width:0", topbar)
        self.assertIn("flex-wrap:wrap", topbar)

        title = self.css_block("#topTitle")
        self.assertIn("flex:11", title)
        self.assertIn("min-width:120px", title)

    def test_chat_rows_and_bubbles_cannot_push_user_text_offscreen(self):
        chat = self.css_block("#chat")
        self.assertIn("overflow-x:hidden", chat)

        row = self.css_block(".row")
        self.assertIn("width:100%", row)
        self.assertIn("min-width:0", row)

        bubble = self.css_block(".bubble")
        self.assertIn("min-width:0", bubble)
        self.assertIn("max-width:80%", bubble)
        self.assertIn("overflow-wrap:anywhere", bubble)
        self.assertIn(
            "margin-left:auto",
            self.css_block(".row.user .bubble"),
        )

    def test_chat_bubbles_are_borderless_and_softly_rounded(self):
        bubble = self.css_block(".bubble")
        self.assertIn("border:0", bubble)
        self.assertIn("border-radius:18px", bubble)

    def test_thinking_indicator_is_bubble_local_but_v5_never_synthesizes_it(self):
        compact = re.sub(r"\s+", "", self.html)
        thinking = self.css_block(".bubbleThinking")
        self.assertIn("display:inline-flex", thinking)
        self.assertIn("font-style:italic", thinking)
        self.assertIn(
            "constbubble=schemaV5SilentAssistant?null:addBubble('assistant',"
            "'<pclass=\"bubbleThinking\"role=\"status\"aria-atomic=\"true\">'+"
            "'Düşünüyor<spanclass=\"dots\"aria-hidden=\"true\"></span></p>');",
            compact,
        )
        self.assertIn(
            "if(schemaV5PromptChatRequest(request)){"
            "schemaComposerBinding=null;schemaComposerMode='disabled';",
            compact,
        )
        self.assertNotIn('id="thinking"', self.html)
        self.assertNotIn("$('thinking').style", self.html)
        self.assertNotIn(
            "border-left",
            self.css_block(".therapist .bubble"),
        )
        self.assertNotIn(
            "border-right",
            self.css_block(".user .bubble"),
        )

    def test_long_content_stays_inside_its_bubble(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            ".bubbleContent{min-width:0;max-width:100%;"
            "overflow-wrap:anywhere}",
            compact,
        )
        self.assertIn(
            ".bubblepre{max-width:100%;overflow-x:auto;white-space:pre}",
            compact,
        )
        self.assertIn(
            ".bubbletable{display:block;max-width:100%;overflow-x:auto}",
            compact,
        )
        self.assertIn(
            ".bubbleimg,.bubblevideo{max-width:100%;height:auto}",
            compact,
        )

    def test_composer_and_dynamic_bars_are_shrink_safe(self):
        input_inner = self.css_block("#inputInner")
        self.assertIn("width:100%", input_inner)
        self.assertIn("min-width:0", input_inner)
        self.assertIn("border-radius:28px", input_inner)
        self.assertIn("align-items:flex-end", input_inner)
        self.assertIn("min-width:0", self.css_block("#msg"))
        self.assertIn("min-width:0", self.css_block("#sessionPathBar"))
        self.assertIn("min-width:0", self.css_block("#workingAgreementBar"))
        self.assertIn("min-width:0", self.css_block("#techniqueBar"))

    def test_composer_uses_round_side_controls_and_send_hint(self):
        message = self.css_block("#msg")
        send = self.css_block("#send")
        focused = self.css_block("#inputInner:focus-within")
        self.assertIn("border:0", message)
        self.assertIn("max-height:132px", message)
        self.assertIn("height:42px", send)
        self.assertIn("width:42px", send)
        self.assertIn("border-radius:50%", send)
        self.assertNotIn("0001px", focused)
        self.assertIn("box-shadow:02px9px", focused)
        self.assertIn('enterkeyhint="enter"', self.html)
        self.assertIn('class="sendArrow"', self.html)
        self.assertIn('aria-label="Mesajı gönder"', self.html)

    def test_mobile_enter_is_newline_while_desktop_enter_sends(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "if(e.key==='Enter'&&!e.shiftKey&&!mobileChatViewport())",
            compact,
        )
        self.assertIn(
            "e.preventDefault();if(!streaming&&!chairBusy&&!imageryBusy)"
            "send();",
            compact,
        )

    def test_night_palette_keeps_text_and_actions_legible(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn("'--paper':'#1a1712'", compact)
        self.assertIn("'--ink':'#f0e7d5'", compact)
        self.assertIn("'--ink-soft':'#c2b397'", compact)
        self.assertIn("'--accent':'#e6aaaa'", compact)
        self.assertIn("'--gold':'#d8bd82'", compact)

    def test_ai_simulation_disclosure_is_persistent_and_living_aware(self):
        self.assertGreaterEqual(self.html.count("AI canlandırması"), 3)
        self.assertIn('id="personaSimulationNote"', self.html)
        self.assertIn("function personaAppearsLiving(", self.html)
        self.assertIn("Yaşayan kişi notu:", self.html)
        self.assertIn("simulationNote.hidden=!living", self.html)

    def test_settings_are_sectioned_sticky_and_provider_testable(self):
        compact = re.sub(r"\s+", "", self.html)
        for title in (
                "Model ve bağlantı",
                "Gizlilik, erişilebilirlik ve kilit",
                "Eşitleme, aktarım ve veriler"):
            self.assertIn(title, self.html)
        self.assertIn(".settingsSaveBar{position:sticky", compact)
        for provider in ("deepseek", "openai", "anthropic", "lmstudio"):
            self.assertIn(f'data-provider-test="{provider}"', self.html)
            self.assertIn(
                f'data-provider-test-status="{provider}"', self.html)
        self.assertIn("'/api/provider-test'", self.html)
        self.assertIn("const payload={provider,", self.html)
        self.assertIn("if(!String(payload.api_key||'').trim())", self.html)
        self.assertIn("delete payload.api_key", self.html)
        self.assertIn("result.latency_ms", self.html)
        self.assertIn("const providerInlineResults = new Map();", self.html)
        self.assertIn("function setProviderInlineResult(", self.html)
        self.assertIn("function restoreProviderInlineResults(", self.html)
        self.assertIn("restoreProviderInlineResults();", self.html)
        self.assertIn("providerStatus.setAttribute('role',"
                      "actionMessage?'alert':'status')", compact)
        self.assertNotIn("providerInlineResults.clear()", self.html)

    def test_os_reduced_motion_is_used_until_user_overrides_it(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn("@media(prefers-reduced-motion:reduce)", compact)
        self.assertIn(
            "constreducedMotionQuery=matchMedia("
            "'(prefers-reduced-motion:reduce)');",
            compact,
        )
        self.assertIn(
            "returnsaved===null?reducedMotionQuery.matches:saved==='1';",
            compact,
        )

    def test_focus_moves_between_mobile_surfaces_without_entering_composer(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "if(movedFromHome&&!document.querySelector('.overlay.show'))"
            "setTimeout(()=>focusWithoutScrolling($('mobileBackBtn')),0);",
            compact,
        )
        self.assertIn(
            "setTimeout(()=>focusWithoutScrolling($('therapistPickerButton')),0);",
            compact,
        )
        focus_start = self.html.index("function focusComposerForViewport()")
        focus_end = self.html.index("function anchorMobileResponseTurn(",
                                    focus_start)
        focus = self.html[focus_start:focus_end]
        self.assertIn("document.querySelector('.overlay.show')", focus)
        self.assertIn("$('side').classList.contains('open')", focus)
        self.assertIn("mobileHomeIsOpen()", focus)

    def test_catalog_close_and_settings_save_remain_reachable(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn('class="modal catalogModal"', self.html)
        self.assertIn('class="modalBtns catalogStickyActions"', self.html)
        self.assertIn("#therapistOverlay.catalogStickyActions{", compact)
        self.assertIn("position:sticky", self.css_block(
            "#therapistOverlay .catalogStickyActions"))

    def test_persona_catalog_names_and_schools_are_readable(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "#therapistGrid{display:grid;grid-template-columns:"
            "repeat(auto-fill,minmax(168px,1fr));grid-auto-rows:max-content;"
            "align-content:start;",
            compact,
        )

        select = self.css_block(".tcardSelect")
        self.assertIn("min-height:154px", select)
        self.assertIn("padding:12px10px13px", select)
        self.assertIn("flex-direction:column", select)

        name = self.css_block(".tcardName")
        self.assertIn("font-size:15px", name)
        self.assertIn("font-weight:700", name)
        self.assertIn("font-variant:normal", name)
        self.assertIn("line-height:1.25", name)

        school = self.css_block(".tcardSchool")
        self.assertIn("font-size:12.5px", school)
        self.assertIn("font-weight:600", school)
        self.assertIn("font-style:normal", school)
        self.assertIn("line-height:1.35", school)
        self.assertNotIn("opacity:", school)

        subtitle = self.css_block(".tcardSubtitle")
        self.assertIn("font-size:11.5px", subtitle)
        self.assertIn("color:var(--ink-soft)", subtitle)
        self.assertIn("line-height:1.35", subtitle)
        self.assertNotIn("opacity:", subtitle)
        self.assertNotIn(".tcardi{", compact)

    def test_persona_catalog_exposes_full_identity_and_selection_state(self):
        compact = re.sub(r"\s+", "", self.html)
        for class_name in ("tcardName", "tcardSchool", "tcardSubtitle"):
            self.assertIn(f'class="{class_name}"', self.html)
        self.assertIn('aria-hidden="true"style="', compact)
        self.assertIn(
            "[t.name,t.school,t.sub].filter(Boolean).join('—')", compact)
        self.assertIn('aria-current="', self.html)
        self.assertIn('aria-pressed="', self.html)
        contrast = self.css_block("body.highContrast #therapistOverlay")
        self.assertIn("--accent:#651616", contrast)
        self.assertIn("--gold:#6b5428", contrast)

    def test_critical_text_inputs_have_accessible_names(self):
        for fragment in (
            'id="searchInput" aria-label="Güncel konuşmalarda ara"',
            'id="memoryNewText" style="min-height:72px"\n    '
            'aria-label="Hatırlanmasını istediğiniz bilgi"',
            'id="summaryDraft" style="min-height:230px"\n    '
            'aria-label="Seans özeti taslağı"',
            '<label for="checkMood">',
            '<label for="checkNote">',
            'id="goalText" aria-label="Yeni hedef"',
            'id="unlockPin" type="password" inputmode="numeric" '
            'aria-label="Uygulama kilidi PIN kodu"',
            'id="conceptFilter" aria-label="Kavramlarda ara"',
            '<label for="deleteAllConfirm">',
        ):
            self.assertIn(fragment, self.html)

    def test_message_time_is_readable_visually_and_to_screen_readers(self):
        time_css = self.css_block(".messageTime")
        self.assertIn("font:11.5px/1.2", time_css)
        self.assertIn("opacity:.82", time_css)
        self.assertIn("time.title=readable", self.html)
        self.assertIn("time.setAttribute('aria-label',readable)", self.html)

    def test_send_button_moves_from_typing_to_ready_after_a_pause(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "functionmarkComposerTyping(){clearTimeout(sendTypingTimer);",
            compact,
        )
        self.assertIn(
            "sendTypingTimer=setTimeout(()=>"
            "syncComposerSendState(false),420);",
            compact,
        )
        self.assertIn(
            "button.classList.toggle('typing',!stopping&&hasText&&typing);",
            compact,
        )
        self.assertIn(
            "button.classList.toggle('ready',stopping||(!typing&&hasText));",
            compact,
        )

    def test_sidebar_and_work_panels_switch_before_the_chat_is_cramped(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertRegex(
            compact,
            r"@media\(max-width:1040px\)\{.*?#side\{"
            r"position:fixed;.*?width:min\(280px,100vw\);min-width:0",
        )
        self.assertIn(
            "destination&&matchMedia('(max-width:1040px)').matches",
            self.html,
        )
        self.assertRegex(
            compact,
            r"@media\(max-width:1600px\)\{#chairPanel,#imageryPanel\{"
            r"position:absolute;.*?width:min\(560px,94%\)",
        )

    def test_mobile_sidebar_keeps_conversations_as_the_scroll_surface(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertRegex(
            compact,
            r"@media\(max-width:1040px\)\{#side\{"
            r".*?height:100dvh;max-height:100dvh;"
            r".*?overflow:hidden;"
            r".*?-webkit-overflow-scrolling:touch;touch-action:pan-y;",
        )
        self.assertIn(
            "#side#sideConversationArea{flex:11auto;min-height:96px}",
            compact,
        )
        self.assertIn(
            "#side#convList{flex:11auto;overflow-y:auto;min-height:0}",
            compact,
        )

    def test_desktop_sidebar_keeps_header_and_settings_fixed(self):
        side = self.css_block("#side")
        self.assertIn("overflow:hidden", side)
        self.assertIn("overscroll-behavior-y:contain", side)
        self.assertIn("scrollbar-width:thin", side)
        compact = re.sub(r"\s+", "", self.html)
        self.assertNotIn("#side>*{flex-shrink:0}", compact)
        self.assertIn(
            "#sideConversationArea{flex:11auto;min-height:96px;"
            "display:flex;flex-direction:column;overflow:hidden;",
            compact,
        )
        self.assertIn(
            "#convList{flex:11auto;min-height:72px;overflow-y:auto;",
            compact,
        )
        self.assertIn(
            "#sideUtilityArea{flex:01auto;min-height:0;"
            "max-height:min(44dvh,430px);overflow-y:auto;"
            "overscroll-behavior:contain;",
            compact,
        )

    def test_desktop_sidebar_keeps_only_essentials_visible(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn('<divclass="sideBtnGrid"id="sidePrimaryBtns"', compact)
        self.assertIn('<detailsid="sideToolsDisclosure">', compact)
        self.assertIn('<detailsid="sideStateDisclosure"', compact)
        self.assertNotIn('<detailsid="sideToolsDisclosure"open', compact)
        self.assertNotIn('<detailsid="sideStateDisclosure"open', compact)
        self.assertIn('id="sideToolsPanel"', self.html)
        self.assertIn('id="sideToolsBadge"', self.html)

        tools_start = self.html.index('<details id="sideToolsDisclosure">')
        tools_end = self.html.index('</details>', tools_start)
        tools = self.html[tools_start:tools_end]
        primary_start = tools.index('id="sidePrimaryBtns"')
        primary_end = tools.index('id="sideSecondaryBtns"', primary_start)
        primary = tools[primary_start:primary_end]
        for element_id in (
                "notesBtn", "memoryBtn", "progressBtn", "livingMapBtn"):
            self.assertIn(f'id="{element_id}"', primary)

        for element_id in (
                "jobsBtn", "dreamsBtn", "lettersBtn", "journeyBtn",
                "conceptsBtn", "practiceLabBtn", "casesBtn", "hlBtn",
                "duetBtn", "councilBtn", "profileBtn", "backupBtn",
                "triageBtn"):
            self.assertIn(f'id="{element_id}"', tools)

        settings = self.html.index('id="settingsBtn"')
        self.assertGreater(settings, tools_end)
        self.assertGreater(settings, self.html.index('id="searchBox"'))
        self.assertIn('<footer id="sideFooter">', self.html)
        self.assertIn(
            "#sideToolsDisclosure[open].sideToolsChevron"
            "{transform:rotate(180deg)}",
            compact,
        )
        self.assertIn(
            "#sideToolsDisclosure:not([open])>#sideToolsPanel{display:none}",
            compact,
        )
        self.assertIn(
            "$('sideToolsBadge').classList.toggle('show',n>0||failed>0);",
            compact,
        )

    def test_mobile_chat_header_uses_one_keyboard_accessible_overflow(self):
        header_start = self.html.index('<header id="mobileHeader"')
        header_end = self.html.index('</header>', header_start)
        header = self.html[header_start:header_end]
        self.assertLess(header.index('id="mobileBackBtn"'),
                        header.index('id="mobilePersonaIdentity"'))
        self.assertLess(header.index('id="mobilePersonaIdentity"'),
                        header.index('id="mobileHeaderMore"'))
        self.assertLess(header.index('id="mobileHeaderMore"'),
                        header.index('id="mobileHeaderMenu"'))
        self.assertIn('role="menu"', header)
        self.assertNotIn('id="mobileChatStateBtn"', header)
        for control in ("mobileConversationSearchToggle",
                        "mobileSessionChromeToggle",
                        "mobileAdhdWorkspaceOpen",
                        "mobileSchemaPathOpen"):
            self.assertGreater(header.index(f'id="{control}"'),
                               header.index('id="mobileHeaderMenu"'))
        self.assertIn("function setMobileHeaderMenu(open", self.html)
        self.assertIn("if(event.key==='Escape')", self.html)
        self.assertIn("event.target.closest('#mobileHeaderMenu,#mobileHeaderMore')",
                      self.html)
        for key in ("ArrowDown", "ArrowUp", "Home", "End"):
            self.assertIn(key, self.html)

    def test_editable_overlays_warn_before_discarding_changes(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn("'settingsOverlay','profileOverlay'", compact)
        self.assertIn("functioneditableOverlaySnapshot(overlay)", compact)
        self.assertIn("functionoverlayHasUnsavedChanges(id)", compact)
        self.assertIn("Kaydedilmemişdeğişikliklervar.", compact)
        self.assertIn("requestOverlayDismiss('settingsOverlay')", self.html)
        self.assertIn("requestOverlayDismiss('profileOverlay')", self.html)

    def test_mobile_chat_uses_a_compact_fixed_initial_badge(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            ".row{padding:08px;gap:6px;margin-bottom:12px}",
            compact,
        )
        self.assertIn(".row.user{margin-bottom:8px}", compact)
        self.assertIn(".row:last-child{margin-bottom:0}", compact)
        self.assertIn(
            ".therapist.avatar{width:26px;height:26px;min-width:26px;"
            "margin-top:4px;font-size:8px;line-height:1;"
            "letter-spacing:-.25px;white-space:nowrap}",
            compact,
        )
        self.assertIn(
            ".therapist.bubble{max-width:calc(100%-32px)}",
            compact,
        )
        self.assertIn(
            ".row.user.bubble{max-width:92%;padding:8px12px;"
            "line-height:1.5}",
            compact,
        )

    def test_mobile_response_closes_keyboard_and_keeps_its_start_readable(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "functiondismissMobileComposer(){"
            "if(!mobileChatViewport())returnfalse;"
            "setComposerQuickMenu(false);clearMobileComposerAnchor();"
            "msgBox.blur();",
            compact,
        )
        self.assertIn("DivanNative.supports('hideKeyboard')", compact)
        self.assertIn(
            "voidDivanNative.hideKeyboard().catch(()=>{});",
            compact,
        )
        self.assertIn(
            "constuserBubble=addBubble('user',md(text),{",
            compact,
        )
        self.assertIn("anchorMobileResponseTurn(userBubble);", compact)
        self.assertIn(
            "if(shouldFollow&&chatFollowLatestIntent&&"
            "interactionSequence===chatViewportInteractionSequence){"
            "followChatToLatest();",
            compact,
        )
        response_anchor = self.between(
            "function anchorMobileResponseTurn(", "function T(")
        self.assertNotIn("setTimeout(settle", response_anchor)
        self.assertIn("markNewResponseBelow();", compact)
        self.assertIn(
            "if(!$('endSessionOverlay').classList.contains('show'))"
            "focusComposerForViewport();",
            compact,
        )

    def test_mobile_input_focus_keeps_latest_message_above_keyboard(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "setChatScrollTop(chat.scrollHeight-chat.clientHeight);",
            compact,
        )
        self.assertIn("functioncaptureMobileComposerScrollPolicy(", compact)
        self.assertIn("composerScrollPolicy='preserve';", compact)
        self.assertIn(
            "composerReadingAnchor=captureChatViewportAnchor();", compact)
        restore_anchor = self.between(
            "function restoreChatViewportAnchor(",
            "function captureConversationReloadViewport(",
        )
        self.assertIn("chat.style.scrollBehavior='auto';", restore_anchor)
        self.assertIn("chat.style.overflowAnchor='none';", restore_anchor)
        self.assertIn(
            "if(composerScrollPolicy==='follow')"
            "alignLatestMessageAboveComposer();"
            "elserestoreMobileComposerReadingPosition();",
            compact,
        )
        self.assertIn(
            "msgBox.addEventListener('pointerdown',"
            "prepareMobileComposerAnchor,{passive:true});",
            compact,
        )
        self.assertIn(
            "window.visualViewport.addEventListener("
            "'resize',syncMobileImeViewport);",
            compact,
        )
        self.assertIn(
            "window.visualViewport.addEventListener("
            "'scroll',syncMobileImeViewport);",
            compact,
        )
        self.assertIn(
            "msgBox.addEventListener('click',reopenMobileComposer);",
            compact,
        )
        self.assertIn("DivanNative.supports('showKeyboard')", compact)
        self.assertIn(
            "voidDivanNative.showKeyboard().catch(()=>{});",
            compact,
        )
        self.assertIn(
            'content="width=device-width,initial-scale=1,'
            'viewport-fit=cover,interactive-widget=resizes-content"',
            compact,
        )
        self.assertIn(
            "#composerPlusBtn{display:inline-grid;place-items:center;"
            "width:44px;height:44px;min-width:44px;",
            compact,
        )
        self.assertIn(
            "#send{width:44px;height:44px;min-width:44px;"
            "background:var(--divan-brand);background-image:none;",
            compact,
        )
        self.assertIn(
            "#inputBar{padding:4px8pxmax(8px,"
            "env(safe-area-inset-bottom));background:var(--mobile-chat);"
            "background-image:none}",
            compact,
        )
        self.assertIn(
            "#chat{padding-bottom:4px;scroll-padding-bottom:12px;"
            "overscroll-behavior-y:contain;"
            "-webkit-overflow-scrolling:touch;touch-action:pan-y;"
            "background:var(--mobile-chat);background-image:none}",
            compact,
        )
        self.assertIn(
            "#inputInner{max-width:none;gap:2px;padding:2px3px;"
            "border-radius:25px;background:var(--mobile-surface);"
            "background-image:none;",
            compact,
        )
        self.assertIn(
            "#msg{min-height:44px;max-height:112px;padding:12px5px8px;"
            "font-size:max(16px,calc(15px*var(--fs)))}",
            compact,
        )

    def test_mobile_plus_menu_has_only_message_context_and_end_actions(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn('id="composerPlusBtn"', self.html)
        self.assertIn('aria-haspopup="menu"', self.html)
        self.assertIn('aria-controls="composerQuickMenu"', self.html)
        self.assertIn('id="composerQuickDream"', self.html)
        self.assertIn('id="composerQuickAdhd"', self.html)
        self.assertIn('id="composerQuickSchema"', self.html)
        self.assertIn('id="composerQuickEnd"', self.html)
        for removed in ("composerQuickChrome", "composerQuickHome",
                        "composerQuickSettings"):
            self.assertNotIn(f'id="{removed}"', self.html)
        for label in ("Mesaj", "Bu görüşmeye özel", "Görüşme"):
            self.assertIn(label, self.html)
        self.assertIn("#sessionChromeToggle{width:44px;height:44px;"
                      "min-width:44px;display:none!important}", compact)
        self.assertIn("#dreamBtn{display:none!important}", compact)
        self.assertIn("#menuBtn{display:none}", compact)
        self.assertIn(
            "setDreamMode(!dreamMode);focusWithoutScrolling(msgBox);"
            "reopenMobileComposer();",
            compact,
        )
        self.assertIn("awaitendSession();", compact)
        self.assertIn("showAdhdWorkspace('today');", compact)
        self.assertIn("showSchemaPathWorkspace();", compact)
        self.assertIn("if(first)setTimeout(()=>focusWithoutScrolling(first),0)",
                      compact)

    def test_mobile_drawer_has_no_edge_swipe_and_home_owns_navigation(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertRegex(
            compact,
            r"@media\(max-width:1040px\)\{#side\{"
            r"position:fixed;z-index:45;left:auto;right:0;"
            r".*?transform:translateX\(calc\(100%\+12px\)\)",
        )
        self.assertIn("border-right:0;border-left:4pxdoublevar(--gold-dim)",
                      compact)
        self.assertNotIn("constsystemEdge=24;", compact)
        self.assertNotIn("sideSwipeState", self.html)
        self.assertNotIn("setupMobileDrawerGestures", self.html)
        self.assertIn("setupResponsiveSideDrawer();", compact)
        self.assertIn("!mobileChatViewport();", compact)

    def test_mobile_header_persists_outside_collapsible_session_chrome(self):
        compact = re.sub(r"\s+", "", self.html)
        header_index = self.html.index('<header id="mobileHeader"')
        topbar_index = self.html.index('<div id="topbar">')
        self.assertLess(header_index, topbar_index)
        self.assertIn('id="mobileBackBtn"', self.html)
        self.assertIn('id="mobilePersonaIdentity"', self.html)
        self.assertIn('id="mobilePersonaPortrait"', self.html)
        self.assertIn('id="mobilePersonaName"', self.html)
        header_markup = self.html[header_index:topbar_index]
        self.assertNotIn("mobileBrand", header_markup)
        self.assertNotIn(">divan<", header_markup)
        self.assertIn("#mobileHeader{display:none}", compact)
        self.assertIn(
            "#mobileBackBtn{flex:0048px;width:48px;height:48px;"
            "display:grid;place-items:center;",
            compact,
        )
        self.assertIn(
            "#mobilePersonaPortrait{width:48px;height:48px;min-width:48px;",
            compact,
        )
        self.assertIn(
            "#mobileHeader{display:flex;"
            "flex:00calc(64px+env(safe-area-inset-top));",
            compact,
        )
        self.assertIn("background:var(--mobile-header);background-image:none;",
                      compact)
        self.assertIn(
            "body.sessionChromeHidden#mobileHeader{display:flex}",
            compact,
        )
        self.assertIn(
            "applyMasterPortraitBackground("
            "$('mobilePersonaPortrait'),t,t.initials,false);",
            self.html,
        )
        self.assertIn("$('mobileBackBtn').onclick=()=>{", self.html)
        self.assertIn("else showMobileHome({focus:true});", self.html)
        self.assertIn(
            "if(mobileChatViewport()&&!mobileHomeIsOpen()){"
            "showMobileHome({focus:true});returntrue;}",
            compact,
        )

    def test_mobile_home_shows_latest_master_rows_search_and_master_picker(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn('id="mobileHome"', self.html)
        self.assertIn('id="mobileConversationList"', self.html)
        self.assertIn('id="mobileNewConversationFab"', self.html)
        self.assertIn('<h1 id="mobileHomeTitle" tabindex="-1">divan</h1>',
                      self.html)
        self.assertIn('class="mobileHomeLogo"', self.html)
        header_start = self.html.index('<header class="mobileHomeHeader">')
        header_end = self.html.index('</header>', header_start)
        header = self.html[header_start:header_end]
        self.assertNotIn('id="mobileHomeMore"', header)
        self.assertEqual(header.count("<button"), 0)
        self.assertIn('id="mobileHomeBottomNav"', self.html)
        self.assertIn('id="mobileHomeSearchBar" role="search"', self.html)
        self.assertIn('id="mobileHomeSearchInput"', self.html)
        self.assertIn('id="mobileHomeSearchResults"', self.html)
        self.assertIn('id="mobileHomeMore"', self.html)
        self.assertIn('id="mobileHomeMenu" role="menu"', self.html)
        self.assertNotIn('id="mobileConversationSelectBtn"', self.html)
        self.assertIn("functionbindMobileConversationLongPress", compact)
        self.assertIn("#mobileHome{display:none}", compact)
        self.assertIn(
            "#mobileHome[hidden],#conversationScreen[hidden]"
            "{display:none!important}",
            compact,
        )
        self.assertIn("body.mobileHomeOpen#mobileHome{display:flex}", compact)
        self.assertIn(
            "$('mobileNewConversationFab').onclick="
            "()=>openMasterPicker('new');",
            compact,
        )
        self.assertIn("constrows=awaitapi('/api/conversations'+", compact)
        self.assertIn("functiongroupMobileConversations(rows)", compact)
        self.assertIn("functionlatestMobileConversationRows(rows)", compact)
        self.assertIn(
            "constlatestRows=latestMobileConversationRows(orderedRows);",
            compact,
        )
        self.assertIn("latestRows.forEach(latest=>", compact)
        self.assertNotIn("group.rows.slice(1).forEach", compact)
        self.assertIn("openConv(row.id);", compact)
        self.assertIn("showMobileConversation();", compact)
        self.assertIn("focusComposerForViewport();", compact)
        self.assertIn("scrollConversationToLatest();", compact)

    def test_mobile_back_detaches_without_cancelling_background_answer(self):
        self.assertIn("window.divanNativeBack=()=>", self.html)
        self.assertIn(
            "window.divanAndroidBack=window.divanNativeBack;", self.html)
        header_back_start = self.html.index(
            "$('mobileBackBtn').onclick=")
        header_back_end = self.html.index(
            "$('mobileNewConversationFab').onclick", header_back_start)
        header_back = self.html[header_back_start:header_back_end]
        self.assertIn("showMobileHome", header_back)
        self.assertNotIn("/api/chat/cancel", header_back)

        android_back_start = self.html.index(
            "if(mobileChatViewport()&&!mobileHomeIsOpen()){")
        android_back_end = self.html.index("return true;", android_back_start)
        android_back = self.html[android_back_start:android_back_end]
        self.assertIn("showMobileHome", android_back)
        self.assertNotIn("/api/chat/cancel", android_back)

        home_start = self.html.index("function showMobileHome(")
        home_end = self.html.index("function syncMobileScreenForViewport(",
                                   home_start)
        home = self.html[home_start:home_end]
        self.assertIn("detachActiveChatStream()", home)
        detach_start = self.html.index(
            "function detachActiveChatStream()")
        detach_end = self.html.index(
            "async function cancelActiveChatRequest(", detach_start)
        detach = self.html[detach_start:detach_end]
        self.assertIn("controller.abort()", detach)
        self.assertNotIn("/api/chat/cancel", detach)

    def test_reopening_the_same_chat_preserves_its_inflight_bubble(self):
        start = self.html.index("async function openConv(id,options={}){")
        end = self.html.index("const sequence=++openSequence;", start)
        opening = re.sub(r"\s+", "", self.html[start:end])

        # The same active conversation must take a fast path before the
        # general cross-conversation cancellation branch. Re-fetching it
        # clears the live bubble and turns a harmless mobile Back into Stop.
        self.assertIn(
            "if(streaming&&Number(id)===Number(convId)"
            "&&!options.forceReload){",
            opening,
        )
        self.assertIn("showMobileConversation();", opening)
        same_chat_guard = opening.index("if(streaming")
        detach = opening.find("detachActiveChatStream()")
        self.assertTrue(detach < 0 or same_chat_guard < detach)

    def test_mobile_home_reports_and_refreshes_background_answers(self):
        entry_start = self.html.index(
            "function createMobileConversationEntry(")
        entry_end = self.html.index(
            "async function archiveSelectedMobileConversations", entry_start)
        entry = re.sub(r"\s+", "", self.html[entry_start:entry_end])
        self.assertRegex(
            entry,
            r"streaming&&[^;{}]*row\.id[^;{}]*convId",
        )
        self.assertIn("row.chat_status", entry)
        self.assertIn("row.chat_partial", entry)
        self.assertIn("yazıyor…", entry)
        self.assertIn("aria-busy", entry)

        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = re.sub(r"\s+", "", self.html[send_start:send_end])
        self.assertIn("refreshConversationLists();", send)

    def test_mobile_root_is_locked_while_the_keyboard_resizes_chat(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "html,body{width:100%;height:var(--mobile-vvh,100dvh);"
            "max-height:var(--mobile-vvh,100dvh);"
            "overflow:hidden;overscroll-behavior:none}",
            compact,
        )
        self.assertIn(
            "body{position:fixed;inset:0;background:var(--mobile-chat)}",
            compact,
        )
        self.assertIn("functionpinMobileRootScroll(){", compact)
        self.assertIn("functionsyncMobileViewportHeight(){", compact)
        self.assertIn(
            "root.style.setProperty('--mobile-vvh',height+'px');",
            compact,
        )
        self.assertIn(
            "if(height>0)root.style.setProperty('--mobile-vvh',height+'px');",
            compact,
        )
        self.assertIn(
            "if(resetAndroidMobileViewportHeight())return;",
            compact,
        )
        self.assertIn(
            "html.androidViewportFillFallback{height:100%;max-height:100%}",
            compact,
        )
        self.assertIn(
            "html.androidViewportFillFallbackbody{height:auto;max-height:none}",
            compact,
        )
        self.assertIn(
            "window.visualViewport.addEventListener("
            "'resize',syncMobileImeViewport);",
            compact,
        )

    def test_ended_mobile_conversation_offers_a_new_session_with_same_master(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn("functionrenderMobileEndedAction(){", compact)
        self.assertIn("button.dataset.testid='new-with-same-master';", compact)
        self.assertIn("button.onclick=startNewFromEndedConversation;", compact)
        self.assertIn("newConversationForCurrentMaster(previous.mode);",
                      compact)

    def test_repeated_mobile_focus_bottom_aligns_short_conversations(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "#chat.composerAnchored{display:flex;flex-direction:column;"
            "overflow-anchor:none}",
            compact,
        )
        self.assertIn(
            '#chat.composerAnchored::before{content:"";flex:100}',
            compact,
        )
        self.assertIn(
            "functionprepareMobileComposerAnchor(){"
            "if(!mobileChatViewport())return;"
            "syncMobileViewportHeight();"
            "captureMobileComposerScrollPolicy({refresh:true});}",
            compact,
        )
        self.assertIn(
            "functionreopenMobileComposer(){"
            "if(!mobileChatViewport())return;"
            "syncMobileViewportHeight();pinMobileRootScroll();"
            "captureMobileComposerScrollPolicy();"
            "focusWithoutScrolling(msgBox);"
            "scheduleMobileComposerAnchor();",
            compact,
        )
        self.assertIn("composerFollowSuspended=true;", compact)
        self.assertIn("!composerFollowSuspended", compact)
        self.assertIn(
            "-webkit-tap-highlight-color:transparent;"
            "touch-action:manipulation",
            compact,
        )

    def test_mobile_chat_scroll_policy_preserves_reader_intent(self):
        chat_helpers = self.between(
            "function chatDistanceFromBottom()",
            "function revealChatElementNearest(",
        )
        composer_helpers = self.between(
            "function setMobileComposerAnchor(",
            "let keyboardFocusIntent=",
        )
        bubble_content = self.between(
            "function setBubbleContent(",
            "function clearConversationSearchMarks(",
        )
        program = r"""
let unseenResponseContent=false;
let chatFollowLatestIntent=true,chatFollowResumeBlocked=false;
let composerAnchorActive=false,composerScrollPolicy='idle';
let composerReadingAnchor=null,composerFollowSuspended=false;
let composerAnchorSequence=0,composerAnchorSettleTimer=null;
let chatViewportInteractionSequence=0;
let convId=7,convData={id:7};
const msgBox={};
const classNames=new Set();
const classList={
  toggle(name,on){if(on)classNames.add(name);else classNames.delete(name);},
  contains(name){return classNames.has(name);},add(name){classNames.add(name);},
  remove(name){classNames.delete(name);}
};
const row={isConnected:true,contentTop:340,
  getBoundingClientRect(){
    const top=this.contentTop-chat.scrollTop;
    return {top,bottom:top+80,height:80};
  },
  querySelector(){return null;}
};
const buttonClasses=new Set();
const latestButton={label:'',classList:{
  toggle(name,on){if(on)buttonClasses.add(name);else buttonClasses.delete(name);}
},setAttribute(){}};
const searchBar={hidden:true};
const chat={scrollHeight:1200,clientHeight:400,scrollTop:800,
  style:{scrollBehavior:'smooth',overflowAnchor:''},classList,
  querySelector(selector){return selector==='.row'?row:null;},
  querySelectorAll(selector){return selector===':scope > .row'?[row]:[];},
  getBoundingClientRect(){return {top:0,bottom:this.clientHeight};}
};
const document={activeElement:null,body:{classList},
  contains(node){return node===row;},
  createElement(){throw new Error('unexpected element creation');}
};
function $(id){
  if(id==='scrollToLatestBtn')return latestButton;
  if(id==='conversationSearchBar')return searchBar;
  return null;
}
function setUiButtonLabel(id,label){latestButton.label=label;}
function mobileChatViewport(){return true;}
function pinMobileRootScroll(){}
function syncMobileViewportHeight(){}
function scheduleConversationSearch(){}
const raf=[];
let nextTimer=0;
const timers=new Map();
function requestAnimationFrame(callback){raf.push(callback);return raf.length;}
function setTimeout(callback){const id=++nextTimer;timers.set(id,callback);return id;}
function clearTimeout(id){timers.delete(id);}
function flush(){
  let guard=0;
  while((raf.length||timers.size)&&guard++<30){
    while(raf.length)raf.shift()();
    const pending=[...timers.values()];timers.clear();
    pending.forEach(callback=>callback());
  }
  if(guard>=30)throw new Error('settle loop did not finish');
}
""" + chat_helpers + composer_helpers + bubble_content + r"""
// IME opens while already at the latest message: keep the latest row pinned.
prepareMobileComposerAnchor();
if(composerScrollPolicy!=='follow')throw new Error('bottom intent not captured');
document.activeElement=msgBox;
chat.clientHeight=240;
scheduleMobileComposerAnchor();flush();
if(chat.scrollTop!==960||chatDistanceFromBottom()!==0)
  throw new Error('latest message was not pinned above composer');

// IME opens while reading history: restore the visible row, never jump down.
clearMobileComposerAnchor();
document.activeElement=null;
chat.scrollHeight=1200;chat.clientHeight=400;chat.scrollTop=300;
row.contentTop=340;
prepareMobileComposerAnchor();
if(composerScrollPolicy!=='preserve')throw new Error('reader intent not captured');
document.activeElement=msgBox;
chat.clientHeight=240;chat.scrollTop=390;
scheduleMobileComposerAnchor();flush();
if(chat.scrollTop!==300||row.getBoundingClientRect().top!==40)
  throw new Error('older-message anchor was not preserved');

// A streaming response follows only while follow-latest intent is still true.
clearMobileComposerAnchor();
document.activeElement=null;
chatFollowLatestIntent=true;chatFollowResumeBlocked=false;
chatViewportInteractionSequence=0;unseenResponseContent=false;
chat.scrollHeight=1200;chat.clientHeight=400;chat.scrollTop=800;
const content={innerHTML:''};
const bubble={querySelector(){return content;},prepend(){}};
setBubbleContent(bubble,'first');chat.scrollHeight=1400;flush();
if(chat.scrollTop!==1000||unseenResponseContent)
  throw new Error('near-bottom response did not follow');

// Reading older messages keeps its offset and surfaces the unseen response.
chatFollowLatestIntent=false;chatFollowResumeBlocked=true;
unseenResponseContent=false;buttonClasses.clear();latestButton.label='';
chat.scrollHeight=1200;chat.clientHeight=400;chat.scrollTop=300;
setBubbleContent(bubble,'second');chat.scrollHeight=1400;flush();
if(chat.scrollTop!==300||!unseenResponseContent||
    !buttonClasses.has('show')||latestButton.label!=='Yeni yanıta in')
  throw new Error('older reader was moved or unseen response was hidden');

// A user gesture invalidates pending IME settling before its delayed pass.
clearMobileComposerAnchor();
chatFollowLatestIntent=true;chatFollowResumeBlocked=false;
chat.scrollHeight=1200;chat.clientHeight=400;chat.scrollTop=800;
document.activeElement=null;prepareMobileComposerAnchor();
document.activeElement=msgBox;chat.clientHeight=240;
scheduleMobileComposerAnchor();
chatViewportInteractionSequence++;
clearMobileComposerAnchor();composerFollowSuspended=true;
flush();
if(chat.scrollTop!==800)throw new Error('cancelled settle yanked the reader');
"""
        self.run_node(program)

    def test_background_reload_and_durable_messages_preserve_reader(self):
        compact = re.sub(r"\s+", "", self.html)
        add_bubble = self.between(
            "function addBubble(", "function renderSchemaBindingResult(")
        self.assertIn(
            "constlocalOutgoing=role==='user'&&"
            "shareMeta?.local_outgoing===true;",
            re.sub(r"\s+", "", add_bubble),
        )
        self.assertNotIn("role==='user'||", add_bubble)
        self.assertIn("local_outgoing:true,", compact)

        open_conversation = self.between(
            "async function openConv(", "function selectedRadioValue(")
        reload_compact = re.sub(r"\s+", "", open_conversation)
        self.assertIn(
            "if((options.fromChatStatus||options.preserveView)&&"
            "Number(id)===Number(convId))",
            reload_compact,
        )
        self.assertIn(
            "reloadViewport=captureConversationReloadViewport({"
            "markUnseen:!!options.fromChatStatus});",
            reload_compact,
        )
        self.assertIn(
            "awaitloadMessageTarget(reloadViewport.messageId);",
            reload_compact,
        )
        self.assertIn(
            "restoreConversationReloadViewport(reloadViewport);",
            reload_compact,
        )

    def test_message_times_are_outside_shareable_content_and_use_saved_values(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(".messageTime{", self.html)
        self.assertIn("functionmessageTimeLabel(value)", compact)
        self.assertIn("functionsetBubbleTime(bubble,created)", compact)
        self.assertIn("b.appendChild(content);", compact)
        self.assertIn("if(created)setBubbleTime(b,created);", compact)
        self.assertIn(
            "functionrenderConversationMessage(message,order=0)", compact
        )
        self.assertIn("content:m.content,created:m.created,order,", compact)
        self.assertIn("setBubbleTime(bubble,assistantCreatedAt);", compact)
        self.assertIn(
            "created:r.closing_created||localMessageCreated()",
            compact,
        )

    def test_master_picker_does_not_open_the_mobile_keyboard(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "showOverlay('therapistOverlay',mobileChatViewport()?"
            "(catalogKind==='philosopher'?'philosopherCatalogTab':"
            "'therapistCatalogTab'):'therapistSearch');",
            compact,
        )

    def test_only_chat_content_and_editable_fields_can_be_text_selected(self):
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            "body{font-family:var(--font);color:var(--ink);display:flex;"
            "overflow:hidden;background:var(--paper);transition:background.4s;"
            "-webkit-user-select:none;user-select:none;",
            compact,
        )
        self.assertIn(
            '.bubbleContent,input,textarea,[contenteditable="true"]{'
            "-webkit-user-select:text;user-select:text}",
            compact,
        )
        self.assertIn(
            "#composerPlusBtn.menuOpen{color:var(--accent);"
            "background:transparent;transform:rotate(45deg)}",
            compact,
        )

    def test_structured_work_panels_wrap_their_composers(self):
        composer = self.css_block(".chairComposerRow")
        self.assertIn("min-width:0", composer)
        self.assertIn("flex-wrap:wrap", composer)
        label = self.css_block(".chairComposerRow label")
        self.assertIn("flex:11", label)
        self.assertIn("white-space:normal", label)
        self.assertIn("overflow-x:hidden", self.css_block(".chairLog"))
        self.assertIn("overflow-x:hidden", self.css_block(".imageryLog"))


if __name__ == "__main__":
    unittest.main()
