import re
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class CurrentStateCheckinUISourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")

    def test_desktop_picker_stays_in_list_while_mobile_picker_is_a_sheet(self):
        self.assertEqual(
            len(re.findall(
                r'<section\b[^>]*data-current-state-surface=',
                self.html, re.DOTALL)), 2)
        desktop = self.html.index(
            'data-current-state-surface="desktop"')
        desktop_list = self.html.index('id="conversationViews"')
        mobile = self.html.index(
            'data-current-state-surface="mobile-sheet"')
        main_end = self.html.index('</main>')
        self.assertGreater(desktop, desktop_list)
        self.assertLess(desktop, self.html.index('id="sideToolsDisclosure"'))
        self.assertGreater(mobile, main_end)
        self.assertIn('id="mobileCurrentStateLayer" hidden', self.html)
        self.assertIn('role="dialog" aria-modal="true"', self.html)

    def test_three_independent_accessible_scales_are_present(self):
        for field, label in (
                ("mood", "Mod"), ("energy", "Enerji"),
                ("happiness", "Mutluluk")):
            self.assertRegex(
                self.html,
                r"id:'{}',label:'{}'".format(field, label))
        render_start = self.html.index("function renderCurrentStateCards()")
        render_end = self.html.index("function selectCurrentState(", render_start)
        render = self.html[render_start:render_end]
        self.assertIn("choices.setAttribute('role','radiogroup')", render)
        self.assertIn("button.setAttribute('role','radio')", render)
        self.assertIn(
            "button.setAttribute('aria-checked',selected?'true':'false')",
            render)
        self.assertIn("button.tabIndex=selected", render)
        self.assertIn("metric.label+' düzeyi'", self.html)
        self.assertIn("option.value+'/10'", self.html)
        for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
                    "Home", "End"):
            self.assertIn(key, render)
        self.assertIn("currentStateFocusRequest", render)
        self.assertIn("requestAnimationFrame", render)
        self.assertIn("focusWithoutScrolling(target)", render)
        self.assertIn('.currentStateChoice[aria-checked="true"]', self.html)
        self.assertIn(
            '.mobileCurrentState .currentStateChoice[aria-checked="true"]',
            self.html)
        self.assertNotIn(
            '.mobileCurrentState .currentStateChoice[aria-pressed="true"]',
            self.html)

    def test_selection_is_debounced_and_persisted_through_checkin_api(self):
        self.assertIn(
            "currentStateSaveTimer=setTimeout(", self.html)
        self.assertIn(
            "optionalApi('/api/checkin',payload,{quiet:false})", self.html)
        self.assertIn(
            "const result=await optionalApi('/api/checkin');", self.html)
        self.assertIn(
            "Promise.all([loadConvs(),loadCurrentStateCheckin()])", self.html)

    def test_mobile_picker_is_touch_friendly_without_moving_page_layout(self):
        self.assertIn(".mobileCurrentState .currentStateChoice{", self.html)
        self.assertRegex(
            self.html,
            re.compile(
                r"\.mobileCurrentState \.currentStateChoice\{\s*"
                r"height:44px",
                re.MULTILINE))
        self.assertIn(
            "#mobileCurrentStateLayer:not([hidden]){", self.html)
        self.assertIn(
            "position:fixed;z-index:47;inset:0", self.html)
        self.assertIn(
            "height:var(--mobile-vvh,100dvh)", self.html)
        self.assertIn(
            "#mobileHome.selecting #mobileHomeMore{display:none}",
            self.html)

    def test_mobile_home_and_chat_menus_do_not_expose_current_state(self):
        self.assertEqual(
            len(re.findall(
                r'<button[^>]+data-current-state-trigger(?:\s|>)',
                self.html, re.DOTALL)), 0)
        for trigger in ("mobileHomeStateBtn", "mobileChatStateBtn"):
            self.assertNotIn('id="{}"'.format(trigger), self.html)
        self.assertNotIn('aria-controls="mobileCurrentStateSheet"', self.html)
        self.assertIn(
            "body.sessionChromeHidden #mobileHeader{display:flex}",
            self.html)

    def test_mobile_sheet_has_all_non_blocking_dismiss_paths(self):
        self.assertIn(
            "$('mobileCurrentStateClose').onclick=()=>", self.html)
        self.assertIn(
            "$('mobileCurrentStateScrim').onclick=()=>", self.html)
        self.assertIn(
            "document.addEventListener('keydown',"
            "handleMobileCurrentStateKeydown,true)", self.html)
        self.assertRegex(
            self.html,
            re.compile(
                r"if\(event\.key==='Escape'\)\{\s*"
                r"event\.preventDefault\(\);\s*"
                r"event\.stopPropagation\(\);\s*"
                r"closeMobileCurrentState\(\{restoreFocus:true\}\)",
                re.MULTILINE))
        self.assertIn(
            "if(mobileCurrentStateIsOpen()){\n"
            "    closeMobileCurrentState({restoreFocus:true});\n"
            "    return true;\n"
            "  }\n  if(mobileHeaderMenuIsOpen())", self.html)

    def test_selection_keeps_all_three_scales_available_and_saves_debounced(self):
        select_start = self.html.index(
            "function selectCurrentState(metric,value){")
        save_start = self.html.index(
            "async function saveCurrentStateCheckin", select_start)
        body = self.html[select_start:save_start]
        self.assertNotIn("closeMobileCurrentState", body)
        self.assertIn(
            "currentStateSaveTimer=setTimeout(\n"
            "    ()=>saveCurrentStateCheckin(version),480)", body)

    def test_progress_history_handles_partial_status_rows(self):
        self.assertIn(
            "['mood','Mod'],['energy','Enerji'],"
            "['happiness','Mutluluk']", self.html)
        self.assertIn(
            "const value=normalizeCurrentStateValue(c[key]);", self.html)
        self.assertNotIn(
            "style=\"width:'+(c.mood*10)+'%\"", self.html)


if __name__ == "__main__":
    unittest.main()
