import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class AndroidMobileUISourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = (Path(PROJECT_DIR) / "index.html").read_text(
            encoding="utf-8")
        cls.compact = re.sub(r"\s+", "", cls.html)

    def test_static_ids_are_unique(self):
        ids = re.findall(r'\bid=["\']([^"\']+)["\']', self.html)
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        self.assertEqual(duplicates, [])

    def test_home_header_has_only_minimal_logo_and_lowercase_wordmark(self):
        start = self.html.index('<header class="mobileHomeHeader">')
        end = self.html.index('</header>', start)
        header = self.html[start:end]
        self.assertIn('class="mobileHomeLogo"', header)
        self.assertIn('<h1 id="mobileHomeTitle" tabindex="-1">divan</h1>',
                      header)
        self.assertEqual(header.count('<button'), 0)
        self.assertNotIn('id="mobileHomeMore"', header)
        self.assertNotIn('http://', header)
        self.assertNotIn('https://', header)

    def test_home_wordmark_logo_and_bottom_navigation_are_minimal(self):
        self.assertIn(
            "font:500clamp(17px,calc(17px*var(--fs)),21px)/1.2"
            "system-ui,-apple-system,BlinkMacSystemFont,\"SegoeUI\",sans-serif;",
            self.compact,
        )
        for declaration in (
                "font-style:normal", "font-variant:normal",
                "letter-spacing:normal", "text-transform:none",
                "text-shadow:none"):
            self.assertIn(declaration, self.compact)
        self.assertIn(".mobileHomeLogo{width:29px;height:25px;", self.compact)
        self.assertIn('id="mobileHomeBottomNav"', self.html)
        self.assertIn('id="mobileHomeChatsTab"', self.html)
        self.assertIn('id="mobileHomePeopleTab"', self.html)
        self.assertIn('id="mobileHomeMore"', self.html)
        self.assertIn('<symbol id="ui-icon-more"', self.html)
        self.assertIn('href="#ui-icon-more"', self.html)
        self.assertIn("stroke-linecap:round;stroke-linejoin:round", self.html)

    def test_home_search_combines_message_and_master_results(self):
        for control in (
                "mobileHomeSearchBar", "mobileHomeSearchInput",
                "mobileHomeSearchClear", "mobileHomeSearchResults"):
            self.assertIn(f'id="{control}"', self.html)
        self.assertIn("function runMobileHomeSearch()", self.html)
        self.assertIn("api('/api/search?q='+encodeURIComponent(query))",
                      self.html)
        self.assertIn("+'&archived=1'", self.html)
        self.assertIn(
            "const people=[...THERAPISTS,...PHILOSOPHERS,...COACHES]",
                      self.html)
        self.assertIn("createMobileHomeConversationSearchResult", self.html)
        self.assertIn("createMobileHomePersonSearchResult", self.html)
        self.assertIn("newConversationForCurrentMaster(mode)", self.html)
        self.assertIn("setMobileHomeSearchActive(false,{clear:true})",
                      self.html)

    def test_new_master_picker_preserves_mode_and_clears_stale_intent(self):
        self.assertIn("let masterPickerPreferredMode = null;", self.html)
        picker = self.html[
            self.html.index("function resetMasterPickerIntent()"):
            self.html.index("$('therapistPickerButton').onclick=")]
        self.assertIn("masterPickerPurpose='browse'", picker)
        self.assertIn("masterPickerPreferredMode=null", picker)
        self.assertIn(
            "const openMasterPicker=(purpose='browse',preferredMode=null)",
            picker)
        self.assertIn("preferredMode==='ders'?'ders'", picker)
        self.assertIn("preferredMode==='terapi'?'terapi'", picker)
        grid = self.html[
            self.html.index("function renderTherapistGrid()"):
            self.html.index("/* ---------------- kenar çubuğu")]
        self.assertLess(grid.index("const preferredMode=masterPickerPreferredMode"),
                        grid.index("hideOverlay('therapistOverlay')"))
        self.assertIn("newConversationForCurrentMaster(preferredMode)", grid)
        self.assertIn("if(id==='therapistOverlay')resetMasterPickerIntent()",
                      self.html)
        self.assertIn("openMasterPicker('new','terapi')", self.html)
        self.assertIn("openMasterPicker('new','ders')", self.html)
        self.assertNotIn("mode='terapi';openMasterPicker('new')", self.html)
        self.assertNotIn("mode='ders';openMasterPicker('new')", self.html)
        lock = self.html[
            self.html.index("function enterAppLockedState()"):
            self.html.index("async function loadUnlockedShell()")]
        self.assertIn("resetMasterPickerIntent()", lock)
        self.assertIn("mobileStartChoiceMasterId=null", lock)

    def test_search_therapist_uses_choice_sheet_while_other_kinds_are_direct(self):
        for control in (
                "mobileStartChoiceOverlay", "mobileStartChoiceTitle",
                "mobileStartChoiceTherapy", "mobileStartChoiceLesson",
                "mobileStartChoiceCancel"):
            self.assertIn(f'id="{control}"', self.html)
        self.assertIn("Terapi seansı", self.html)
        self.assertIn("<strong>Ders</strong>", self.html)
        self.assertIn("Vazgeç", self.html)
        choice = self.html[
            self.html.index("function startConversationWithSearchMaster("):
            self.html.index("function createMobileHomeSearchResultAvatar(")]
        self.assertIn("masterKind(master.id)!=='therapist'", choice)
        self.assertIn("showOverlay('mobileStartChoiceOverlay',"
                      "'mobileStartChoiceTherapy')", choice)
        self.assertIn("hideOverlay('mobileStartChoiceOverlay')", choice)
        result = self.html[
            self.html.index("function createMobileHomePersonSearchResult("):
            self.html.index("function appendMobileHomeSearchSection(")]
        self.assertIn("if(masterType==='therapist')", result)
        self.assertIn("showMobileStartChoice(master)", result)
        self.assertIn("masterType==='philosopher'?'ders':'terapi'", result)
        self.assertIn("focusWithoutScrolling($('mobileHomeTitle'))", result)
        self.assertIn("requestOverlayDismiss('mobileStartChoiceOverlay')",
                      self.html)
        native_back = self.html[
            self.html.index("window.divanNativeBack=()=>{"):
            self.html.index("window.divanAndroidBack=", self.html.index(
                "window.divanNativeBack=()=>{"))]
        self.assertIn("document.querySelectorAll('.overlay.show')", native_back)
        self.assertIn("requestOverlayDismiss(overlay.id)", native_back)
        dialog_keys = self.html[
            self.html.index("function setupDialogs()"):
            self.html.index("setupDialogs();initTestHooks()")]
        self.assertIn("if(e.key==='Escape'", dialog_keys)
        self.assertIn("if(id==='mobileStartChoiceOverlay')"
                      "mobileStartChoiceMasterId=null", self.compact)
        self.assertIn(".mobileStartChoiceSheet{", self.html)
        self.assertIn(
            "@media(max-width:320px){#mobileHomeSearchBar{padding-left:9px;",
            self.compact)

    def test_home_uses_one_latest_row_per_master_without_inline_history(self):
        self.assertIn("function latestMobileConversationRows(rows)", self.html)
        latest = self.html[
            self.html.index("function latestMobileConversationRows(rows)"):
            self.html.index("function mobileConversationDisplayName(")]
        self.assertIn("mobileConversationRecency(a)", latest)
        self.assertNotIn("stateOrder", latest)
        self.assertIn("orderActiveConversationRows(representatives)", latest)
        loader = self.html[
            self.html.index("async function loadMobileHomeConversations()"):
            self.html.index("function mobileMasterHistoryStamp(")]
        self.assertIn("const latestRows=latestMobileConversationRows(orderedRows)",
                      loader)
        self.assertIn("latestRows.forEach(latest=>", loader)
        self.assertNotIn("group.rows.slice(1)", loader)
        self.assertNotIn("mobileConversationExpand", loader)
        entry = self.html[
            self.html.index("function createMobileConversationEntry(row)"):
            self.html.index("async function archiveSelectedMobileConversations")]
        self.assertNotIn("mobileConversationTitle", entry)
        self.assertIn("button.append(portrait,masterName,time,preview)", entry)

    def test_chat_overflow_owns_full_page_master_history(self):
        self.assertIn('id="mobileMasterHistoryOpen"', self.html)
        self.assertIn('id="mobileMasterHistoryOverlay"', self.html)
        self.assertIn('id="mobileMasterHistoryList" role="list"', self.html)
        self.assertIn('id="mobileMasterHistoryNew"', self.html)
        history = self.html[
            self.html.index("async function showMobileMasterHistory()"):
            self.html.index("function mobileHomeSearchText(")]
        self.assertIn("api('/api/conversations')", history)
        self.assertIn("api('/api/conversations?archived=1')", history)
        self.assertIn("mobileConversationGroupKey(row)===key", history)
        self.assertIn("await openConv(Number(row.id))", self.html)
        self.assertIn("newConversationForCurrentMaster(snapshot.mode)",
                      history)
        history_binding = self.html[
            self.html.index("$('mobileMasterHistoryOpen').onclick="):
            self.html.index("$('mobileMasterHistoryBack').onclick=")]
        self.assertIn("setMobileHeaderMenu(false)", history_binding)
        self.assertIn("focusWithoutScrolling($('mobileHeaderMore'))",
                      history_binding)
        self.assertIn("showMobileMasterHistory()", history_binding)

    def test_chat_identity_opens_safe_full_page_master_profile(self):
        identity = re.search(
            r'<button type="button" id="mobilePersonaIdentity"([\s\S]*?)'
            r'</button>', self.html)
        self.assertIsNotNone(identity)
        self.assertIn('aria-haspopup="dialog"', identity.group(0))
        self.assertIn('aria-controls="mobileMasterProfileOverlay"',
                      identity.group(0))
        for control in (
                "mobileMasterProfileOverlay", "mobileMasterProfileBack",
                "mobileMasterProfilePortrait", "mobileMasterProfileName",
                "mobileMasterProfileMeta", "mobileMasterProfileSubtitle",
                "mobileMasterProfileLifespan", "mobileMasterProfileStatus",
                "mobileMasterProfileError", "mobileMasterProfileRetry",
                "mobileMasterProfileViews", "mobileMasterProfileApproaches",
                "mobileMasterProfileBoundary"):
            self.assertIn(f'id="{control}"', self.html)
        self.assertIn("$('mobilePersonaIdentity').onclick="
                      "showMobileMasterProfile;", self.compact)
        self.assertIn(
            "requestOverlayDismiss('mobileMasterProfileOverlay')",
            self.html)
        self.assertIn("showOverlay('mobileMasterProfileOverlay',"
                      "'mobileMasterProfileBack')", self.compact)
        self.assertIn("if(id==='mobileMasterProfileOverlay'){", self.compact)
        self.assertIn("mobileMasterProfileRequestSequence++", self.compact)
        self.assertIn("mobileMasterProfileAbortController.abort()",
                      self.compact)

    def test_master_profile_api_rendering_is_bounded_deduplicated_and_honest(self):
        profile = self.html[
            self.html.index("const DEFAULT_MASTER_PROFILE_BOUNDARY="):
            self.html.index("function mobileHomeSearchText(")]
        self.assertIn("optionalApi(", profile)
        compact_profile = re.sub(r"\s+", "", profile)
        self.assertIn(
            "'/api/master-profile?id='+encodeURIComponent(id),null,",
            compact_profile)
        self.assertIn("quiet:true,signal:controller&&controller.signal",
                      compact_profile)
        self.assertIn("MOBILE_MASTER_PROFILE_TIMEOUT_MS", profile)
        self.assertIn("Promise.race([request,timeout])", profile)
        self.assertIn("String(data.id||'')!==id", profile)
        self.assertIn("mobileMasterProfileRequestSequence", profile)
        self.assertIn("mobileMasterProfileId!==id", profile)
        self.assertIn("item.textContent=copy", profile)
        self.assertNotIn("innerHTML", profile)
        self.assertIn("newSet()", re.sub(r"\s+", "", profile))
        self.assertIn("if(seen.has(key))returnfalse", re.sub(r"\s+", "", profile))
        self.assertIn("approachKeys", profile)
        self.assertIn("!approachKeys.has", profile)
        self.assertIn("subtitle.split(lifespan).join('')", profile)
        self.assertIn("$('mobileMasterProfileLifespan').hidden=!dated", profile)
        self.assertNotIn("missing.push('yaşam tarihleri')", profile)
        for heading in (
                "Terapi yöntemleri", "Felsefi soru ve metin yolları",
                "Koçluk odakları"):
            self.assertIn(heading, profile)
        self.assertIn("Divan bu boşlukları doldurmaz.", profile)
        self.assertIn("DEFAULT_MASTER_PROFILE_BOUNDARY", profile)

    def test_master_profile_targets_theme_and_reflow_contracts(self):
        for declaration in (
                "#mobilePersonaIdentity{cursor:pointer;",
                "background:transparent;background-image:none;",
                "#mobileMasterProfileBack{width:48px;height:48px;",
                "#mobileMasterProfileRetry{min-height:48px;",
                ".mobileMasterProfileScroll{flex:1;min-height:0;"
                "overflow-x:hidden;overflow-y:auto;",
                "#mobileMasterProfileOverlay.mobileMasterProfilePage{"
                "width:100%;max-width:none;",
                "#mobileMasterProfileScroll:focus{outline:0}",
                "height:var(--mobile-vvh,100dvh)",
                "font:clamp(14px,calc(14px*var(--fs)),21px)"):
            self.assertIn(declaration, self.compact)
        scroll = re.search(
            r'<div class="mobileMasterProfileScroll"\s+'
            r'id="mobileMasterProfileScroll"([^>]*)>', self.html)
        self.assertIsNotNone(scroll)
        self.assertIn('role="region"', scroll.group(0))
        self.assertIn('aria-label="Usta profil bilgileri"', scroll.group(0))
        self.assertIn('tabindex="0"', scroll.group(0))
        self.assertIn(
            "focusWithoutScrolling($('mobileMasterProfileScroll'))",
            self.html)
        self.assertIn(
            "focusWithoutScrolling($('mobileMasterProfileRetry'))",
            self.html)
        self.assertIn("@media(orientation:landscape)and(max-height:420px)",
                      self.compact)
        self.assertIn("background:var(--mobile-chat);background-image:none",
                      self.compact)
        self.assertIn("#mobilePersonaIdentity:focus-visible{",
                      self.html)

    def test_assistant_reply_swipe_has_axis_threshold_cancel_and_a11y_action(self):
        swipe = self.html[
            self.html.index("const ASSISTANT_REPLY_SWIPE_THRESHOLD=52"):
            self.html.index("function addResponseTools(")]
        self.assertIn("const ASSISTANT_REPLY_SWIPE_MAX=72", swipe)
        self.assertIn("Math.max(absX,absY)<11", swipe)
        self.assertIn("absY>11&&absY>absX*1.25", swipe)
        self.assertIn("dx<=0||absX<absY*1.12", swipe)
        self.assertIn("if(event&&event.cancelable)event.preventDefault()", swipe)
        self.assertIn("bubble.setPointerCapture(event.pointerId)", swipe)
        self.assertIn("pointercancel", swipe)
        self.assertIn("lostpointercapture", swipe)
        self.assertIn("'touchstart'", swipe)
        self.assertIn("'touchmove'", swipe)
        self.assertIn("'touchcancel'", swipe)
        self.assertIn("cancelMessageSelectionLongPress()", swipe)
        self.assertIn("reply.role!=='assistant'", swipe)
        self.assertIn("touch-action:pan-y", self.html)
        self.assertIn("replySwipeA11yAction", swipe)
        self.assertIn("Bu usta mesajını alıntılayarak yanıtla", swipe)
        self.assertIn("reply.textContent='Yanıtla'", self.html)
        self.assertIn(
            "reply.setAttribute('aria-label','Bu usta mesajına alıntılı yanıt ver')",
            self.html,
        )
        self.assertIn("reply_to:replyForSend&&replyForSend.id||null",
                      self.html)
        self.assertIn("body.reduceMotion *", self.html)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.html)

    def test_home_search_keyboard_focus_and_native_back_are_predictable(self):
        bindings = self.html[
            self.html.index("$('mobileHomeSearchInput').addEventListener('focus'"):
            self.html.index("$('mobileHomeSearchClear').onclick=") + 500]
        self.assertIn("event.key==='Escape'", bindings)
        self.assertIn("event.key==='ArrowDown'", bindings)
        self.assertIn("focusWithoutScrolling(first)", bindings)
        native_back = self.html[
            self.html.index("window.divanNativeBack=()=>{"):
            self.html.index("window.divanAndroidBack=", self.html.index(
                "window.divanNativeBack=()=>{"))]
        self.assertIn("if(mobileHomeSearchActive)", native_back)
        self.assertIn("setMobileHomeSearchActive(false,{clear:true})",
                      native_back)

    def test_home_tools_are_grouped_without_redundant_actions(self):
        for control in (
                "mobileHomeNewConversation", "mobileHomeNewLesson",
                "mobileLivingMapBtn", "mobileHomeNotes", "mobileHomeMemory",
                "mobileHomeArchivedConversations", "mobileHomeSettings"):
            self.assertIn(f'id="{control}"', self.html)
        for removed in (
                "mobileHomeStateBtn", "mobileConversationSelectBtn",
                "mobileHomeActiveConversations"):
            self.assertNotIn(f'id="{removed}"', self.html)
        self.assertIn('id="mobileHomeMenu" role="menu"', self.html)
        menu = self.html[
            self.html.index('id="mobileHomeMenu" role="menu"'):
            self.html.index('id="mobileConversationSelectionBar"')]
        for label in ("Başlat", "Kayıtlarım", "Uygulama"):
            self.assertIn(label, menu)
        for removed_copy in (
                "Anlık durum", "Konuşmaları seç", "Güncel konuşmalar"):
            self.assertNotIn(removed_copy, menu)
        self.assertIn("function setMobileHomeMenu(open", self.html)
        self.assertIn("if(list)list.inert=show;", self.compact)
        self.assertIn("if(fab)fab.inert=show;", self.compact)
        self.assertIn("if(mobileHomeMenuIsOpen()){", self.html)
        self.assertIn("function bindMobileConversationLongPress", self.html)
        self.assertIn("enterMobileConversationSelection(row)", self.html)
        for key in ("ArrowDown", "ArrowUp", "Home", "End", "Escape"):
            self.assertIn(key, self.html)

    def test_right_edge_swipe_and_mobile_drawer_entry_are_removed(self):
        self.assertNotIn("setupMobileDrawerGestures", self.html)
        self.assertNotIn("sideSwipeState", self.html)
        self.assertNotIn("const systemEdge", self.html)
        self.assertNotIn('id="composerQuickDrawer"', self.html)
        self.assertNotIn('id="composerQuickHome"', self.html)
        self.assertNotIn('id="composerQuickSettings"', self.html)
        self.assertIn("showMobileHome({focus:true});", self.html)
        self.assertIn("!mobileChatViewport();", self.compact)
        self.assertIn("side.toggleAttribute('inert',sideDisabled);",
                      self.compact)
        self.assertIn("main.toggleAttribute('inert',mainDisabled);",
                      self.compact)

    def test_settings_is_a_full_height_mobile_page_without_input_autofocus(self):
        self.assertIn('id="mobileSettingsBack"', self.html)
        self.assertIn('id="mobileSettingsTitle">Ayarlar', self.html)
        self.assertIn(
            "#settingsOverlay{align-items:stretch;justify-content:stretch;"
            "padding:0;background:var(--mobile-chat);background-image:none}",
            self.compact)
        self.assertIn(
            "height:var(--mobile-vvh,100dvh);min-height:0;max-height:none;",
            self.compact)
        self.assertIn(
            "scroll-padding-top:116px;scroll-padding-bottom:"
            "max(18px,env(safe-area-inset-bottom))", self.compact)
        self.assertIn(".settingsSaveBar{position:static;z-index:auto;",
                      self.compact)
        self.assertIn(
            "showOverlay('settingsOverlay',mobileChatViewport()?"
            "'mobileSettingsBack':undefined);", self.compact)
        self.assertIn(
            "$('mobileSettingsBack').onclick=()=>"
            "requestOverlayDismiss('settingsOverlay');", self.compact)

    def test_android_back_closes_settings_and_restores_home_menu_focus(self):
        settings_handler = self.html[
            self.html.index("$('mobileHomeSettings').onclick=async()=>{"):
            self.html.index("$('mobileSettingsBack').onclick=", self.html.index(
                "$('mobileHomeSettings').onclick=async()=>{"))]
        self.assertIn("closeMobileHomeMenuForNavigation();", settings_handler)
        self.assertIn("await showSettings();", settings_handler)

        navigation_helper = self.html[
            self.html.index("function closeMobileHomeMenuForNavigation()"):
            self.html.index("function setMobileHeaderMenu", self.html.index(
                "function closeMobileHomeMenuForNavigation()"))]
        self.assertIn("const trigger=$('mobileHomeMore');", navigation_helper)
        self.assertIn("focusWithoutScrolling(trigger);", navigation_helper)

        native_back = self.html[
            self.html.index("window.divanNativeBack=()=>{"):
            self.html.index("window.divanAndroidBack=", self.html.index(
                "window.divanNativeBack=()=>{"))]
        self.assertIn("const overlay=[...document.querySelectorAll('.overlay.show')].pop();",
                      native_back)
        self.assertIn("requestOverlayDismiss(overlay.id);", native_back)
        self.assertIn("return true;", native_back)

        hide_overlay = self.html[
            self.html.index("function hideOverlay(id){"):
            self.html.index("function requestOverlayDismiss", self.html.index(
                "function hideOverlay(id){"))]
        self.assertIn("const back = overlayReturnFocus.get(id);", hide_overlay)
        self.assertIn("focusWithoutScrolling(back);", hide_overlay)

    def test_global_sidebar_tools_have_a_mobile_settings_route(self):
        expected = {
            "notesBtn", "memoryBtn", "progressBtn", "livingMapBtn",
            "jobsBtn", "dreamsBtn", "lettersBtn",
            "journeyBtn", "conceptsBtn", "practiceLabBtn", "casesBtn",
            "hlBtn", "duetBtn", "councilBtn", "profileBtn",
            "backupBtn", "triageBtn",
        }
        routed = set(re.findall(
            r'data-mobile-side-target="([^"]+)"', self.html))
        self.assertTrue(expected.issubset(routed), expected - routed)
        self.assertNotIn("adhdBtn", routed)
        self.assertIn('id="mobileAdhdWorkspaceOpen"', self.html)
        self.assertIn('id="composerQuickAdhd"', self.html)
        self.assertIn("requestOverlayDismiss('settingsOverlay');", self.html)
        self.assertIn("setTimeout(()=>target.click(),0);", self.compact)

    def test_pin_selection_uses_atomic_backend_contract_and_visual_marker(self):
        self.assertIn('id="mobileConversationPinSelected"', self.html)
        self.assertIn("const action=shouldPin?'pin':'unpin';", self.html)
        self.assertIn(
            "api('/api/conversations/batch',{action,ids})", self.compact)
        self.assertIn("result.pinned!==shouldPin", self.html)
        self.assertIn("className='mobileConversationPinMark'", self.html)
        self.assertIn("button.classList.toggle('isPinned',!!row.pinned_at)",
                      self.html)
        sorter = self.html[
            self.html.index("function orderActiveConversationRows(rows)"):
            self.html.index("function mobileConversationGroupKey", self.html.index(
                "function orderActiveConversationRows(rows)"))]
        self.assertLess(sorter.index("pinOrder"), sorter.index("stateOrder"))
        self.assertIn("pinned_at", sorter)
        aggregate = self.html[
            self.html.index("function latestMobileConversationRows(rows)"):
            self.html.index("function mobileConversationDisplayName(")]
        self.assertIn("_mobileGroupPinned", aggregate)
        self.assertIn("_mobileGroupIds", aggregate)
        pinning = self.html[
            self.html.index("async function pinSelectedMobileConversations()"):
            self.html.index("function clearConversationListError")]
        self.assertIn("rows.flatMap(row=>", pinning)
        self.assertIn("row._mobileGroupIds", pinning)

    def test_archive_remains_reachable_after_drawer_removal(self):
        self.assertIn('id="mobileHomeArchivedConversations"', self.html)
        self.assertIn('id="mobileConversationScope"', self.html)
        self.assertIn("mobileConversationView==='archived'?'?archived=1':''",
                      self.compact)
        self.assertIn("const action=restoring?'restore':'archive';", self.html)
        self.assertIn("if(pin)pin.hidden=archived;", self.compact)

    def test_320_360_480_layout_contracts_exist(self):
        for width in (320, 360, 480):
            self.assertIn(f"@media(max-width:{width}px)", self.compact)
        self.assertIn(
            "@media(max-width:320px){#mobileHomeSearchBar{padding-left:9px;",
            self.compact)
        self.assertIn(
            "@media(max-width:360px){.mobileHomeHeader{padding-left:10px;",
            self.compact)
        self.assertIn(
            "@media(max-width:480px){#mobileHomeMenu{width:min(270px,",
            self.compact)

    def test_context_menus_settings_and_prompt_reflow_with_touch_targets(self):
        for contract in (
                ".mobileHomeMenuItem{width:100%;min-height:48px;",
                ".mobileHeaderMenuItem{width:100%;min-height:48px;",
                ".composerQuickItem{width:100%;min-height:52px;",
                ".mobileSettingsToolGroupsummary{min-height:52px;",
                ".adhdConversationPromptActionsbutton{min-width:0;"
                "min-height:48px;"):
            self.assertIn(contract, self.compact)
        self.assertIn(
            ".adhdConversationPromptActions{grid-template-columns:1fr}",
            self.compact)
        self.assertIn(
            "@media(orientation:landscape)and(max-height:420px)",
            self.compact)
        self.assertIn(
            ".adhdConversationPromptActions{grid-template-columns:"
            "repeat(4,minmax(0,1fr))}", self.compact)
        self.assertIn("calc(13px*var(--fs))", self.compact)
        self.assertIn('class="mobileSettingsToolGroup"', self.html)
        self.assertNotIn('data-mobile-side-target="adhdBtn"', self.html)

    def test_day_night_high_contrast_and_native_system_chrome_are_linked(self):
        for theme in ("white", "paper", "dark"):
            self.assertIn(f'body[data-mobile-theme="{theme}"]', self.html)
        self.assertIn('body.highContrast[data-mobile-theme="dark"]',
                      self.html)
        self.assertIn("document.body.classList.toggle('nightMode',dark)",
                      self.html)
        self.assertIn("setSystemChrome(dark)", self.html)
        self.assertIn("setSystemChromeTheme(theme)", self.html)
        self.assertIn(
            "const chromeTheme=mobileChatViewport()?mobileTheme:"
            "(dark?'dark':'paper');", self.html)
        self.assertIn("DivanNative.setSystemChromeTheme(chromeTheme)",
                      self.html)

    def test_mobile_theme_picker_is_three_choice_flat_and_persistent(self):
        self.assertIn('id="mobileThemePicker"', self.html)
        radios = re.findall(
            r'<input type="radio" name="mobileTheme" value="([^"]+)"',
            self.html)
        self.assertEqual(radios, ["white", "paper", "dark"])
        for label in ("Beyaz", "Sarı kâğıt", "Karanlık"):
            self.assertIn(label, self.html)
        self.assertIn("localStorage.setItem('mobileTheme',mobileTheme)",
                      self.html)
        self.assertIn("normalizeMobileTheme(localStorage.getItem('mobileTheme')",
                      self.html)
        self.assertEqual(self.html.count("data-live-setting"), 4)
        self.assertIn("!field.hasAttribute('data-live-setting')", self.html)
        self.assertIn("fontScale = Math.min(2,", self.html)

    def test_mobile_media_blocks_contain_no_gradients(self):
        marker = "@media(max-width:760px){"
        start = 0
        blocks = []
        while True:
            begin = self.html.find(marker, start)
            if begin < 0:
                break
            depth = 0
            for end in range(begin, len(self.html)):
                if self.html[end] == "{":
                    depth += 1
                elif self.html[end] == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append(self.html[begin:end + 1])
                        start = end + 1
                        break
        self.assertTrue(blocks)
        for block in blocks:
            self.assertNotIn("gradient", block)

    def test_chat_header_has_safe_area_and_48px_avatar(self):
        self.assertIn(
            "#mobilePersonaPortrait{width:48px;height:48px;min-width:48px;",
            self.compact)
        self.assertIn(
            "flex:00calc(64px+env(safe-area-inset-top))", self.compact)
        self.assertIn("position:relative;top:0;color:var(--ink);", self.compact)
        self.assertIn("(t.school?t.school+' · ':'')+'AI canlandırması'",
                      self.html)

    def test_notification_inline_reply_is_separate_and_fail_closed(self):
        self.assertIn('id="notificationInlineReplyToggle" disabled', self.html)
        self.assertIn("notificationInlineReplyEnabled", self.html)
        self.assertIn("setNotificationInlineReplyEnabled", self.html)
        self.assertIn("notificationInlineReplyAvailable", self.html)
        self.assertIn("capabilities.add('notificationInlineReply')", self.html)
        control = self.html[
            self.html.index("function syncNotificationInlineReplyControl()"):
            self.html.index("async function showSettings()")]
        self.assertIn("!notificationsEnabled||pinPending||!nativeAvailable",
                      re.sub(r"\s+", "", control))
        self.assertIn("providerSettings?.pin_set", control)
        save = self.html[
            self.html.index("$('settingsSave').onclick=async()=>{"):
            self.html.index("$('pinInput').oninput=", self.html.index(
                "$('settingsSave').onclick=async()=>{"))]
        self.assertIn("!$('notificationInlineReplyToggle').disabled", save)

    def test_keyboard_and_viewport_resize_keep_scroll_surfaces_stable(self):
        self.assertIn("interactive-widget=resizes-content", self.html)
        self.assertIn("font-size:max(16px,calc(15px * var(--fs)))!important",
                      self.html)
        self.assertIn("window.visualViewport.addEventListener('resize'",
                      self.html)
        self.assertIn("window.visualViewport.addEventListener('scroll'",
                      self.html)
        self.assertIn("pinMobileRootScroll();", self.html)
        self.assertIn("overscroll-behavior-y:contain", self.html)

    def test_notification_privacy_and_system_settings_route_are_explicit(self):
        self.assertIn("Kişi adı ile yanıt metni kilit ekranında görünebilir",
                      self.html)
        self.assertIn('id="notificationSettingsOpen"', self.html)
        self.assertIn("openNotificationSettings()", self.html)
        self.assertIn("DivanNative.openNotificationSettings()", self.html)
        start = self.html.index(
            "window.divanAndroidNotificationPermissionChanged=function")
        end = self.html.index("async function refreshAdhdAndResync", start)
        callback = self.html[start:end]
        self.assertNotIn("replyNotificationToggle", callback)
        self.assertIn("notificationSettingsOpen", callback)

    def test_schema_jobs_reach_the_android_lifecycle_keeper_immediately(self):
        """A queued Schema analysis must survive an immediate app background."""
        start = self.html.index("async function postSchemaPath(")
        end = self.html.index("function resetSchemaTurnUi(", start)
        mutation = self.html[start:end]
        for action in ("analyze_turn", "scan_history", "retry_scan"):
            self.assertIn("'{}'".format(action), mutation)
        self.assertIn("Number(response?.job_id)>0", mutation)
        self.assertIn("signalNativePendingWork(1)", mutation)
        self.assertIn("await loadJobs(false)", mutation)
        self.assertIn("scheduleJobPoll(", mutation)

        badge_start = self.html.index("function renderJobsBadge(")
        badge_end = self.html.index("function renderDiagnosticLog(",
                                   badge_start)
        self.assertIn("signalNativePendingWork()",
                      self.html[badge_start:badge_end])
        jobs_start = self.html.index("async function loadJobs(")
        jobs_end = self.html.index("function scheduleJobPoll(", jobs_start)
        self.assertIn("renderJobsBadge()", self.html[jobs_start:jobs_end])

    def test_schema_provider_consent_is_disclosed_per_android_device(self):
        start = self.html.index("function renderSchemaModeAndHistory(")
        end = self.html.index("function renderSchemaPathWorkspace(", start)
        consent = self.html[start:end]
        self.assertIn("pending_device_confirmation", consent)
        self.assertIn("pending_provider_confirmation", consent)
        self.assertIn("Bu cihazda metin gönderilmedi", consent)
        self.assertIn("sağlayıcısı veya model değişti", consent)
        self.assertIn("Onay bu cihaza", consent)
        self.assertIn("geçmiş turlar ayrı onay ister", consent)

    def test_schema_jobs_and_startup_failures_have_actionable_mobile_labels(self):
        kind_start = self.html.index("function jobKindLabel(")
        kind_end = self.html.index("function jobErrorLabel(", kind_start)
        kinds = self.html[kind_start:kind_end]
        self.assertIn("living_map_turn_analysis:", kinds)
        self.assertIn("Tek mesaj çifti için şema", kinds)
        self.assertIn("schema_turn_backfill:", kinds)
        self.assertIn("Kerem Genç geçmiş mesaj çiftleri", kinds)

        error_start = kind_end
        error_end = self.html.index("function renderJobs(", error_start)
        errors = self.html[error_start:error_end]
        for code in (
                "provider_changed", "schema_mode_off",
                "source_changed", "safety_hold", "analysis_busy",
                "analysis_not_retryable", "local_unreachable",
                "provider_timeout", "rate_limited"):
            self.assertIn("{}:".format(code), errors)
        render_start = error_end
        render_end = self.html.index("function renderJobsBadge(", render_start)
        self.assertIn("retry.textContent='Yeniden dene'",
                      self.html[render_start:render_end])

        startup_start = self.html.index("function createStartupRetryButton(")
        startup_end = self.html.index("(async ()=>{", startup_start)
        startup = self.html[startup_start:startup_end]
        self.assertIn("button.textContent='Yeniden bağlan'", startup)
        self.assertIn("mobileEmpty.setAttribute('role','alert')", startup)
        self.assertIn("Konuşmalar silinmedi", startup)

    def test_inline_schema_candidate_is_one_atomic_yes_no_row(self):
        candidate = self.html[
            self.html.index("function renderSchemaChatOnlyCandidate("):
            self.html.index("function focusSchemaChatOnlyInteraction(")]
        self.assertIn("schemaChatCandidatePrompt", candidate)
        self.assertIn("schemaChatOnlyCandidateCopy(", candidate)
        self.assertIn("schemaChatOnlyCandidateUserContent(card)", candidate)
        helper = self.html[
            self.html.index("function schemaChatOnlyCandidateCopy("):
            self.html.index("function renderSchemaChatOnlyCandidate(")]
        self.assertIn("source.quote", helper)
        self.assertIn("source.assistant_message_public_id", helper)
        self.assertIn("pair.indexOf(assistant)!==userIndex+1", helper)
        self.assertIn("Üzerinde çalışabileceğimiz konu: “", candidate)
        self.assertIn("Olası örüntü: ", candidate)
        self.assertIn("card.body", candidate)
        self.assertIn("['accept_candidate_chat','Evet','yes']", candidate)
        self.assertIn("['reject_candidate_chat','Hayır','no']", candidate)
        self.assertIn("postSchemaV4CardAction(envelope,card,{})", candidate)
        self.assertNotIn("startSchemaPath(", candidate)
        self.assertNotIn("addBubble(", candidate)
        self.assertNotIn("progress", candidate)
        self.assertNotIn("card.context_line", candidate)

    def test_adhd_tus_plus_entry_stays_inline_and_picker_keeps_ime_node(self):
        self.assertIn('id="composerQuickTus" role="menuitem" hidden',
                      self.html)
        visibility = self.html[
            self.html.index("function syncStructuredWorkspaceVisibility()"):
            self.html.index("function structuredRequestId(")]
        self.assertIn(
            "['mobileAdhdWorkspaceOpen','composerQuickAdhd',"
            "'composerQuickTus']", visibility)
        self.assertIn("const adhdVisible=nativeMobile&&adhdReady", visibility)
        self.assertIn("tusTab.hidden=true", visibility)
        self.assertIn("adhdTusLoadedConvId!==Number(convId)", visibility)
        self.assertNotIn("showAdhdWorkspace('tus')", self.html)
        entry = self.html[
            self.html.index("async function enterAdhdTusChat("):
            self.html.index("/* Kerem Genç:")]
        self.assertIn("loadAdhdTusChatSnapshot()", entry)
        self.assertIn("mutateAdhdTusChat('enter',{})", entry)
        picker = self.html[
            self.html.index("function renderAdhdTusChatPickerResults("):
            self.html.index("function adhdTusChatMutationBody(")]
        self.assertIn("results.replaceChildren()", picker)
        self.assertIn("focusWithoutScrolling(input)", picker)
        self.assertNotIn("input.replaceChildren", picker)

    def test_schema_focus_origin_growth_and_healthy_adult_are_mobile_actions(self):
        self.assertIn("function renderSchemaFocus()", self.html)
        self.assertIn("postSchemaPath('choose_focus'", self.html)
        self.assertIn("postSchemaPath('record_origin'", self.html)
        self.assertIn("postSchemaPath('add_growth_stage'", self.html)
        self.assertIn("postSchemaPath('mark_healthy_adult'", self.html)
        self.assertIn("Sağlıklı Yetişkin", self.html)
        workspace_start = self.html.index("function showSchemaPathWorkspace()")
        workspace_end = self.html.index(
            "function closeSchemaPathWorkspace()", workspace_start)
        workspace = self.html[workspace_start:workspace_end]
        self.assertIn(
            "structuredWorkspaceConversation('young')",
            workspace,
        )
        self.assertIn("await loadSchemaPathDashboard({background:true})",
                      workspace)
        chat_branch = workspace[
            workspace.index("if(schemaChatOnlyPresentation())"):
            workspace.index("if(androidNativeMobileContext())")]
        self.assertIn("renderSchemaPathWorkspace()", chat_branch)
        self.assertIn("showOverlay('schemaPathOverlay'", chat_branch)
        self.assertNotIn("hideOverlay('schemaPathOverlay')", chat_branch)
        native_start = workspace.index("if(androidNativeMobileContext())")
        native_branch = workspace[native_start:
            workspace.index("showOverlay('schemaPathOverlay'", native_start)]
        self.assertIn(".schemaModeInvite", native_branch)
        self.assertIn("$('schemaSuggestCard')", native_branch)
        self.assertIn("$('schemaStepCard')", native_branch)
        self.assertIn("button:not(:disabled)", native_branch)
        self.assertNotIn("showOverlay(", native_branch)

        invite_start = self.html.index("function renderSchemaModeInvite(")
        invite_end = self.html.index(
            "async function enableSchemaModeFromChat(", invite_start)
        invite = self.html[invite_start:invite_end]
        self.assertIn("schemaProviderDestination()", invite)
        self.assertIn("yalnız bundan sonra", invite)
        self.assertIn("Her çift", invite)
        self.assertIn("bulut sağlayıcınız ücret uygulayabilir", invite)
        self.assertIn("Geçmiş '+", invite)
        self.assertIn("'turlar ayrı onay ister.", invite)
        self.assertIn("yalnız “Evet”", invite)
        self.assertIn("çalışma sohbet içinde başlar", invite)

    def test_schema_v4_chat_only_hides_workspace_and_keeps_composer_ordinary(self):
        renderer = self.html[
            self.html.index("function renderSchemaChatOnlyCard("):
            self.html.index("function renderSchemaV4ActiveCard(")]
        for hidden in ("cardNode.hidden=true", "schemaStepProgress",
                       "schemaStepSource", "schemaClinicalSyncNotice",
                       "schemaStepFields", "schemaStepActions"):
            self.assertIn(hidden, renderer)
        self.assertIn("kind==='candidate_prompt'", renderer)
        self.assertIn("schemaProtocolV5()&&kind==='chat_state'", renderer)
        self.assertIn("syncSchemaV5PromptState(card)", renderer)
        self.assertIn("schemaComposerMode='disabled'", renderer)
        binding_strip = self.html[
            self.html.index("function renderSchemaComposerBinding("):
            self.html.index("function syncSchemaV4ComposerBinding(")]
        self.assertIn("if(schemaChatOnlyPresentation())", binding_strip)
        self.assertIn("strip.hidden=true", binding_strip)
        self.assertIn("msgBox.placeholder='Söyleyin…'", binding_strip)
        self.assertIn("schemaComposerBound','schemaComposerLocked",
                      binding_strip)
        self.assertNotIn("schemaChatContinuation", self.html)
        self.assertNotIn("schemaChatInlineControls", self.html)
        self.assertNotIn("renderSchemaChatOnlyContinuation", self.html)
        self.assertNotIn("schemaChatOnlyGroundControlValid", self.html)
        self.assertNotIn("schemaChatControl", self.html)
        candidate = self.html[
            self.html.index("function renderSchemaChatOnlyCandidate("):
            self.html.index("function focusSchemaChatOnlyInteraction(")]
        self.assertIn("schemaChatOnlyAnchorBubble(card)", candidate)
        self.assertIn("'Evet'", candidate)
        self.assertIn("'Hayır'", candidate)
        self.assertNotIn("schemaV4FieldControl", candidate)
        self.assertNotIn("addBubble(", candidate)
        meta = self.html[
            self.html.index("function schemaV4MetaCard("):
            self.html.index("function renderSchemaMessageMetaEvents(")]
        self.assertIn("['technique','map_update']", meta)
        self.assertNotIn("'progress'", meta)
        self.assertIn("min-height:44px", self.html)
        self.assertIn("body.nativeAndroid .schemaChatCandidateActions button",
                      self.html)
        self.assertRegex(
            self.html,
            r"\.schemaChatCandidateActions button\s*\{\s*"
            r"min-height:44px;min-width:44px",
        )

    def test_schema_v4_android_back_never_opens_or_collapses_hidden_workspace(self):
        back = self.html[
            self.html.index("window.divanNativeBack=()=>"):
            self.html.index("window.divanAndroidBack=window.divanNativeBack")]
        self.assertIn("!schemaChatOnlyPresentation()", back)
        self.assertIn("schemaComposerBindingCollapsed=true", back)
        self.assertNotIn("schemaComposerBinding=null", back)
        self.assertLess(back.index("!schemaChatOnlyPresentation()"),
                        back.index("schemaComposerBindingCollapsed=true"))

    def test_schema_v4_process_death_restores_bound_draft(self):
        draft = self.html[
            self.html.index("function conversationDraftPayload()"):
            self.html.index("function mobileChatViewport()")]
        self.assertIn("schema_binding:compactSchemaBinding", draft)
        self.assertIn("schemaComposerBinding=compactSchemaBinding(", draft)
        self.assertIn("renderSchemaComposerBinding();", draft)
        compact = self.html[
            self.html.index("function compactSchemaBinding("):
            self.html.index("function schemaJsonValueSafe(")]
        self.assertIn("result.path_public_id", compact)
        self.assertIn("result.source_user_message_id", compact)
        self.assertIn("result.source_assistant_message_id", compact)
        self.assertIn("result.prompt_request_id", compact)
        self.assertIn("result.prompt_assistant_message_id", compact)
        self.assertIn("result.prompt_assistant_message_public_id", compact)
        self.assertIn("Object.keys(rawStepData).length", compact)
        sender = self.html[
            self.html.index("async function send("):
            self.html.index("/* ---------------- seans bitir")]
        self.assertIn("schema_binding:schemaBindingForSend", sender)
        self.assertIn("schemaV5SilentAssistant", sender)
        self.assertIn("refreshSchemaV5DurableMessages", sender)
        self.assertIn("rememberChatDelivery", sender)
        self.assertIn("signalNativePendingWork", self.html)
        resume = self.html[
            self.html.index("function resumeConversationChatRequest("):
            self.html.index("function setDreamMode(")]
        self.assertIn("schemaV5PromptChatRequest(request)", resume)
        self.assertIn("return true", resume)
        self.assertNotIn("addBubble('assistant'", resume[
            resume.index("if(schemaV5PromptChatRequest(request))"):
            resume.index("let bubble=")])


if __name__ == "__main__":
    unittest.main()
