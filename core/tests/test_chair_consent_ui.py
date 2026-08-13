import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def function_source(name):
    match = re.search(
        r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{",
        HTML,
    )
    if not match:
        raise AssertionError("missing function {}".format(name))
    start = match.start()
    next_match = re.search(r"\n(?:async\s+)?function\s+\w+\s*\(", HTML[match.end():])
    end = match.end() + next_match.start() if next_match else len(HTML)
    return HTML[start:end]


class ChairConsentUITests(unittest.TestCase):

    def test_setup_collects_real_user_values_with_accessible_labels(self):
        self.assertIn('id="chairConsentForm"', HTML)
        self.assertRegex(
            HTML,
            r'<label class="chairConsentField" for="chairGoalText">',
        )
        self.assertRegex(
            HTML,
            r'<label class="chairConsentField" for="chairStopSignal">',
        )
        self.assertRegex(
            HTML,
            r'<label class="chairConsentCheck" for="chairOrientationOk">',
        )
        self.assertRegex(
            HTML,
            r'<label class="chairConsentCheck" for="chairFrameOk">',
        )
        self.assertIn('id="chairGoalText" maxlength="500"', HTML)
        self.assertIn('id="chairStopSignal" maxlength="80"', HTML)
        self.assertIn('id="chairConsentError"\n                role="alert" hidden', HTML)
        self.assertEqual(HTML.count('aria-describedby="chairConsentError"'), 4)

    def test_setup_never_preticks_or_injects_fake_consent(self):
        for identifier in ("chairOrientationOk", "chairFrameOk"):
            tag = re.search(
                r'<input\s+id="{}"[^>]*>'.format(identifier), HTML
            )
            self.assertIsNotNone(tag)
            self.assertNotRegex(tag.group(0), r"\schecked(?:\s|>|=)")
        for identifier in ("chairGoalText", "chairStopSignal"):
            tag = re.search(
                r'<input\s+id="{}"[^>]*>'.format(identifier), HTML
            )
            self.assertIsNotNone(tag)
            self.assertNotRegex(tag.group(0), r"\svalue=")

        submit = function_source("submitChairSetup")
        self.assertIn("const payload=chairConsentPayload", submit)
        self.assertIn("if(switching)", submit)
        self.assertIn("saveChairDraft();saveChairConsentDraft();", submit)
        self.assertIn("chairConsentDraftContext=''", submit)
        self.assertIn("if(switching)renderChairWork();", submit)
        self.assertIn("const wasHidden=$('chairPanel').hidden", submit)
        self.assertIn("openChairPanel({focus:false,suppressMobileFocus:true})", submit)
        self.assertIn("suppressMobileFocus:true", submit)
        self.assertIn("if(wasHidden)$('chairBegin').focus", submit)
        self.assertIn("openChairPanel({focus:true});", submit)
        self.assertIn("setChairMobileView('dialogue')", submit)
        self.assertIn("'begin',payload", submit)
        self.assertNotIn("'begin',{}", submit)
        self.assertNotRegex(
            HTML,
            r"chairAction\(\s*['\"]begin['\"]\s*,\s*\{\s*\}",
        )

    def test_generic_method_consent_forwards_the_actual_checkbox_value(self):
        start = function_source("startPendingMethod")
        self.assertIn("if(!$('methodConsentCheck').checked)", start)
        self.assertIn(
            "confirmed:$('methodConsentCheck').checked",
            start,
        )
        self.assertNotRegex(start, r"\bconfirmed\s*:\s*true\b")

    def test_begin_is_one_form_submission_and_generic_advance_uses_it(self):
        self.assertRegex(
            HTML,
            r'<button type="submit" form="chairConsentForm" class="primary"\s+id="chairBegin"',
        )
        self.assertEqual(
            HTML.count("$('chairConsentForm').addEventListener('submit',submitChairSetup)"),
            1,
        )
        self.assertNotIn("$('chairBegin').onclick", HTML)
        advance = function_source("advanceChairPhase")
        self.assertIn("if(caps.begin===true)\n    return submitChairSetup();", advance)

    def test_failed_start_keeps_draft_and_success_clears_it(self):
        submit = function_source("submitChairSetup")
        request_at = submit.index("const response=await chairAction")
        success_at = submit.index("if(response)")
        clear_at = submit.index("clearChairConsentDraft()")
        self.assertLess(request_at, success_at)
        self.assertLess(success_at, clear_at)
        self.assertIn("Yazdıklarınız korundu", submit)
        save = function_source("saveChairConsentDraft")
        self.assertIn("goal_text:$('chairGoalText').value", save)
        self.assertIn("stop_signal:$('chairStopSignal').value", save)
        self.assertIn("orientation_ok:$('chairOrientationOk').checked", save)
        self.assertIn("frame_ok:$('chairFrameOk').checked", save)
        self.assertIn("saveChairDraft();saveChairConsentDraft();", HTML)
        restore = function_source("restoreChairConsentDraft")
        self.assertIn("'aria-invalid','false'", restore)

    def test_render_only_shows_setup_for_unconsented_active_ready_work(self):
        render = function_source("renderChairWork")
        self.assertIn("const consented=chairConsentComplete();", render)
        self.assertIn("const showConsent=activeRunSelected&&preparing&&!finished&&!consented", render)
        self.assertIn("$('chairConsentForm').hidden=!showConsent", render)
        self.assertIn("$('chairBegin').style.display=showConsent?'':'none'", render)

    def test_mobile_inputs_do_not_trigger_ios_zoom(self):
        self.assertRegex(
            HTML,
            r"@media\(max-width:760px\)[\s\S]*?\.chairConsentField input,"
            r"\.chairCheckpointCard textarea\{\s*min-height:44px;font-size:16px",
        )

    def test_lifecycle_checkpoints_have_real_accessible_user_controls(self):
        self.assertIn('id="chairCheckpointForm"', HTML)
        self.assertIn('id="chairCheckpointOrientation" type="checkbox"', HTML)
        self.assertIn(
            'id="chairCheckpointIntensity" type="range" min="0"', HTML
        )
        self.assertIn('id="chairCheckpointNote" maxlength="2000"', HTML)
        self.assertIn('id="chairCheckpointConfirmed" type="checkbox"', HTML)
        self.assertEqual(HTML.count('aria-describedby="chairCheckpointError"'), 4)
        for identifier in (
            "chairCheckpointOrientation", "chairCheckpointConfirmed"
        ):
            tag = re.search(
                r'<input\s+id="{}"[^>]*>'.format(identifier), HTML
            )
            self.assertIsNotNone(tag)
            self.assertNotRegex(tag.group(0), r"\schecked(?:\s|>|=)")

    def test_lifecycle_actions_open_checkpoint_ui_instead_of_faking_consent(self):
        advance = function_source("advanceChairPhase")
        self.assertIn("openChairCheckpoint('ground')", advance)
        self.assertIn("openChairCheckpoint('reflect')", advance)
        self.assertIn("openChairCheckpoint('complete')", advance)
        self.assertNotRegex(
            HTML,
            r"chairAction\(\s*['\"](?:ground|reflect|complete)['\"]\s*,\s*\{\s*\}",
        )
        self.assertEqual(
            HTML.count(
                "$('chairCheckpointForm').addEventListener('submit',submitChairCheckpoint)"
            ),
            1,
        )

    def test_checkpoint_payload_is_derived_after_per_action_validation(self):
        payload = function_source("chairCheckpointPayload")
        self.assertIn("action==='ground'&&!orientation", payload)
        self.assertIn("action==='ground'&&!validIntensity", payload)
        self.assertIn("action==='reflect'&&!note", payload)
        self.assertIn("else if(!confirmed)", payload)
        confirmed_at = payload.index("const confirmed=$('chairCheckpointConfirmed').checked")
        wire_at = payload.index("const payload={checkpoint_confirmed:true}")
        self.assertLess(confirmed_at, wire_at)
        self.assertIn("payload.orientation_ok=true;payload.intensity=intensity", payload)

    def test_failed_checkpoint_preserves_fields_and_stop_bypasses_form(self):
        submit = function_source("submitChairCheckpoint")
        self.assertIn("if(response){closeChairCheckpoint();return response;}", submit)
        self.assertIn("Seçimleriniz korundu", submit)
        self.assertNotIn("closeChairCheckpoint()", submit.split("if(response)", 1)[0])
        stop_handler = re.search(
            r"\$\('techniqueStop'\)\.onclick=async\(\)=>\{([\s\S]*?)\n\};",
            HTML,
        )
        self.assertIsNotNone(stop_handler)
        self.assertIn("chairAction('stop',{}", stop_handler.group(1))
        self.assertNotIn("openChairCheckpoint('stop')", HTML)
        action = function_source("chairAction")
        self.assertIn("const emergencyStop=action==='stop'", action)
        self.assertIn("(!emergencyStop&&(chairBusy||streaming))", action)

    def test_mobile_panel_contains_its_own_always_reachable_emergency_stop(self):
        panel = re.search(
            r'<aside id="chairPanel"[\s\S]*?</aside>',
            HTML,
        )
        self.assertIsNotNone(panel)
        markup = panel.group(0)
        self.assertRegex(
            markup,
            r'<button\b[^>]*\bid="chairEmergencyStop"[^>]*>',
        )
        stop_tag = re.search(
            r'<button\b[^>]*\bid="chairEmergencyStop"[^>]*>',
            markup,
        ).group(0)
        self.assertIn('type="button"', stop_tag)
        self.assertRegex(stop_tag, r'aria-label="[^"]*(?:durdur|kapat)[^"]*"')

        binding_at = HTML.index("$('chairEmergencyStop').onclick")
        binding = HTML[binding_at:binding_at + 600]
        self.assertRegex(binding, r"chairAction\(\s*'stop',\{\}")
        self.assertNotIn("openChairCheckpoint('stop')", binding)

    def test_resume_requires_fresh_orientation_grounding_and_intensity_ui(self):
        for identifier in (
            "chairResumeForm", "chairResumeOrientation",
            "chairResumeGrounding", "chairResumeIntensity",
        ):
            self.assertIn('id="{}"'.format(identifier), HTML)
        payload = function_source("chairResumePayload")
        self.assertIn("$('chairResumeOrientation').checked", payload)
        self.assertIn("$('chairResumeGrounding').checked", payload)
        self.assertIn("Number($('chairResumeIntensity').value)", payload)
        self.assertIn(
            "return {checkpoint_confirmed:true,orientation_ok:true,intensity}",
            payload,
        )
        self.assertNotRegex(
            HTML,
            r"chairAction\(\s*['\"]resume['\"]\s*,\s*\{\s*\}",
        )


if __name__ == "__main__":
    unittest.main()
