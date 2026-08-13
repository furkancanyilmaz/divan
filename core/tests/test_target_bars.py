from pathlib import Path
import re
import unittest

from support import app


class SessionChromeUISourceTests(unittest.TestCase):

    def setUp(self):
        self.source = (
            Path(app.DIR) / "index.html"
        ).read_text(encoding="utf-8")

    def test_desktop_triangle_controls_all_session_header_regions(self):
        self.assertIn('id="sessionChromeToggle"', self.source)
        self.assertIn(
            'aria-controls="topbarContents personaSimulationNote '
            'sessionPathBar workingAgreementBar techniqueBar"',
            self.source,
        )
        self.assertIn('data-testid="session-chrome-toggle"', self.source)
        self.assertIn("Üst alanları gizle", self.source)
        self.assertIn("Üst alanları göster", self.source)
        tag = re.search(
            r'<button\b(?=[^>]*\bid="sessionChromeToggle")(?P<tag>[^>]*)>',
            self.source,
        )
        self.assertIsNotNone(tag)
        self.assertIn('type="button"', tag.group("tag"))
        self.assertIn('aria-expanded="false"', tag.group("tag"))
        icon = self.source[tag.end():tag.end() + 500]
        self.assertIn("<svg", icon)
        self.assertIn("sessionChromeTriangle", icon)
        self.assertNotIn("visibilitySlash", icon)
        self.assertEqual(
            len(re.findall(r'\bid="sessionPathBar"', self.source)), 1
        )
        self.assertEqual(
            len(re.findall(r'\bid="workingAgreementBar"', self.source)), 1
        )

    def test_mobile_header_has_a_separate_accessible_triangle(self):
        start = self.source.index('<header id="mobileHeader"')
        end = self.source.index("</header>", start)
        header = self.source[start:end]
        self.assertIn('id="mobileSessionChromeToggle"', header)
        self.assertIn('data-testid="mobile-session-chrome-toggle"', header)
        tag = re.search(
            r'<button\b(?=[^>]*\bid="mobileSessionChromeToggle")'
            r'(?P<tag>[^>]*)>',
            header,
        )
        self.assertIsNotNone(tag)
        self.assertIn('type="button"', tag.group("tag"))
        self.assertIn('role="menuitemcheckbox"', tag.group("tag"))
        self.assertIn('aria-checked="false"', tag.group("tag"))
        self.assertIn(
            'aria-controls="topbarContents personaSimulationNote sessionPathBar '
            'workingAgreementBar techniqueBar"',
            tag.group("tag"),
        )
        icon = header[tag.end():tag.end() + 500]
        self.assertIn("sessionChromeTriangle", icon)
        self.assertRegex(self.source,
                         r"\.mobileHeaderMenuItem\s*\{[^}]*min-height:44px")

    def test_collapsed_state_hides_menu_targets_and_technique_stage(self):
        self.assertRegex(
            self.source,
            re.compile(
                r"body\.sessionChromeHidden\s+#sessionPathBar\.show,\s*"
                r"body\.sessionChromeHidden\s+#workingAgreementBar\.show,\s*"
                r"body\.sessionChromeHidden\s+#techniqueBar\.show,\s*"
                r"body\.sessionChromeHidden\s+\.personaSimulationNote\.show"
                r"\s*\{\s*display:none\s*\}"
            ),
        )
        self.assertRegex(
            self.source,
            r"body\.sessionChromeHidden\s+#topbarContents\s*\{\s*display:none\s*\}",
        )
        self.assertNotRegex(
            self.source,
            r"body\.sessionChromeHidden\s+#safetyBanner",
        )
        self.assertRegex(
            self.source,
            r"#sessionChromeToggle\s*\{[^}]*width:44px;"
            r"height:44px;min-width:44px;display:none!important",
        )
        self.assertIn(
            "body.sessionChromeHidden #topbar{display:none}",
            self.source,
        )

    def test_choice_is_persistent_defaults_hidden_and_applies_to_all_dialogues(self):
        self.assertIn(
            "localStorage.getItem('sessionChromeHidden')",
            self.source,
        )
        self.assertIn(
            "localStorage.setItem('sessionChromeHidden',hidden?'1':'0')",
            self.source,
        )
        self.assertIn("applySessionChromeVisibility(open);", self.source)
        self.assertIn("function toggleSessionChrome()", self.source)
        self.assertIn("applySessionChromeVisibility(true);", self.source)
        function = re.search(
            r"function sessionChromeIsHidden\(\)\{(?P<body>.*?)\n\}",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(function)
        body = function.group("body")
        self.assertIn("localStorage.getItem('targetBarsHidden')", body)
        self.assertRegex(
            re.sub(r"\s+", "", body),
            r"(?:returntrue;|"
            r"returnlocalStorage\.getItem\('targetBarsHidden'\)!=='0';)$",
        )

    def test_apply_function_synchronizes_visual_and_accessible_state(self):
        function = re.search(
            r"function applySessionChromeVisibility\(open=false\)\{"
            r"(?P<body>.*?)\n\}",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(function)
        body = function.group("body")
        self.assertIn(
            "document.body.classList.toggle('sessionChromeHidden',hidden);",
            body,
        )
        self.assertIn("mobileSessionChromeToggle", body)
        self.assertIn(
            "desktopToggle.setAttribute('aria-expanded',hidden?'false':'true');",
            body,
        )
        self.assertIn(
            "mobileToggle.setAttribute('aria-checked',hidden?'false':'true');",
            body,
        )

    def test_every_open_conversation_including_ended_lessons_can_expand_header(self):
        function = re.search(
            r"function toggleSessionChrome\(\)\{(?P<body>.*?)\n\}",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(function)
        body = function.group("body")
        self.assertIn("if(!convData)return;", body)
        self.assertNotIn("clinicalConversation(convData)", body)
        self.assertNotIn("!convData.ended", body)
        self.assertIn("applySessionChromeVisibility(true);", body)

    def test_preference_is_reapplied_during_every_header_render(self):
        function = re.search(
            r"function updateTopButtons\(\)\{(?P<body>.*?)\n\}",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(function)
        self.assertRegex(
            function.group("body"),
            r"applySessionChromeVisibility\(open\);[\s\S]*?"
            r"renderSessionPathBar\(\);renderWorkingAgreement\(\)",
        )


class TechniqueBarUISourceTests(unittest.TestCase):

    def setUp(self):
        self.source = (
            Path(app.DIR) / "index.html"
        ).read_text(encoding="utf-8")

    def function_slice(self, start_marker, end_marker):
        try:
            start = self.source.index(start_marker)
        except ValueError:
            self.fail("Beklenen başlangıç bulunamadı: {}".format(start_marker))
        try:
            end = self.source.index(end_marker, start)
        except ValueError:
            self.fail("Beklenen bitiş bulunamadı: {}".format(end_marker))
        return self.source[start:end]

    def test_phase_select_is_interactive_without_allowing_free_phase_jumps(self):
        tag = re.search(
            r'<select\b(?=[^>]*\bid="techniquePhase")(?P<tag>[^>]*)>',
            self.source,
        )
        self.assertIsNotNone(tag)
        self.assertNotIn("disabled", tag.group("tag"))
        render = self.function_slice(
            "function renderTechniqueBar(){",
            "async function updateTechniqueRun(",
        )
        self.assertIn("$('techniquePhase').disabled=", render)
        self.assertRegex(
            render,
            r"(?:option|o)\.disabled\s*=\s*"
            r"[^;\n]*(?:phase|current)[^;\n]*(?:next|nextPhase)",
        )

    def test_phase_select_and_primary_button_share_one_progress_action(self):
        self.assertIn("function advanceActiveTechnique()", self.source)
        self.assertRegex(
            self.source,
            r"\$\('techniquePhase'\)\.addEventListener\('change',"
            r"[\s\S]*?advanceActiveTechnique\(\)",
        )
        self.assertRegex(
            self.source,
            r"\$\('techniqueAdvance'\)\.onclick\s*=\s*"
            r"advanceActiveTechnique",
        )

    def test_primary_progress_action_handles_consent_pause_and_modalities(self):
        action = self.function_slice(
            "function advanceActiveTechnique(){",
            "$('techniqueGround').onclick=",
        )
        self.assertRegex(
            action,
            r"status===['\"]proposed['\"][\s\S]*?"
            r"reopenProposedConsent\(\)",
        )
        self.assertRegex(
            action,
            r"status===['\"]paused['\"][\s\S]*?"
            r"updateTechniqueRun\(['\"]resume['\"]\)",
        )
        self.assertIn("isChairTechnique(activeTechnique)", action)
        self.assertIn("advanceChairPhase()", action)
        self.assertIn("isImageryTechnique(activeTechnique)", action)
        self.assertIn("imageryCapabilities()", action)
        self.assertIn("updateTechniqueRun('advance')", action)

    def test_primary_button_copy_matches_proposed_and_paused_actions(self):
        render = self.function_slice(
            "function renderTechniqueBar(){",
            "async function updateTechniqueRun(",
        )
        self.assertIn("status==='proposed'?'Onayı gözden geçir'", render)
        self.assertRegex(
            render,
            r"status===['\"]paused['\"]\s*\?\s*['\"]Devam et['\"]",
        )
