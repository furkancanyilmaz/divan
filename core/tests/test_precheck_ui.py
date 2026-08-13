import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class PrecheckUISourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")
        cls.compact = re.sub(r"\s+", "", cls.html)

    def test_every_passive_dismissal_uses_the_precheck_cancel_path(self):
        self.assertIn(
            "functionrequestOverlayDismiss(id){"
            "if(id==='precheckOverlay'){cancelPrecheck();return;}",
            self.compact,
        )
        self.assertIn(
            "if(overlay.dataset.blocking!=='true')"
            "requestOverlayDismiss(overlay.id);",
            self.compact,
        )
        self.assertGreaterEqual(
            self.html.count("requestOverlayDismiss(overlay.id)"), 2)
        self.assertIn("requestOverlayDismiss(open.id)", self.html)
        self.assertRegex(
            self.compact,
            r"functioncancelPrecheck\(\)\{"
            r"if\(precheckStarting\)return;"
            r"constrequest=pendingTherapyRequest;"
            r"pendingTherapyRequest=null;"
            r"hideOverlay\('precheckOverlay'\);"
            r"if\(request&&request\.text\)"
            r"\{msgBox\.value=request\.text;autoGrow\(\);\}",
        )

    def test_fine_tuning_is_sparse_and_start_is_single_flight(self):
        self.assertNotIn("precheckAnswers.fine", self.html)
        for key in ("mood", "anxiety", "intensity", "grounding"):
            with self.subTest(key=key):
                self.assertIn("precheckDirty[key]=true", self.html)
        self.assertIn(
            "if(!loadSelected&&!precheckDirty[dirtyKey])return;",
            self.compact,
        )
        self.assertIn(
            "asyncfunctionstartTherapyFromPrecheck(skip=false){"
            "if(precheckStarting)return;setPrecheckStarting(true);",
            self.compact,
        )
        self.assertIn(
            "}finally{setPrecheckStarting(false);}",
            self.compact,
        )

    def test_question_focus_does_not_target_an_editable_control(self):
        question = re.search(
            r'<div\b[^>]*\bid=["\']precheckQuestion["\'][^>]*>',
            self.html,
            flags=re.IGNORECASE)
        self.assertIsNotNone(question)
        self.assertRegex(question.group(0), r'\btabindex=["\']-1["\']')
        self.assertRegex(question.group(0), r'\baria-live=["\']polite["\']')
        self.assertIn(
            "renderPrecheckConversation({focusQuestion:true})",
            self.html,
        )
        self.assertIn("focusWithoutScrolling(question)", self.html)
        self.assertIn("keepPrecheckControlVisible(control)", self.html)

    def test_route_live_status_is_separate_from_its_radio_options(self):
        status = re.search(
            r'<p\b[^>]*\bid=["\']preRouteStatus["\'][^>]*>',
            self.html,
            flags=re.IGNORECASE)
        options = re.search(
            r'<div\b[^>]*\bid=["\']preRouteOptions["\'][^>]*>',
            self.html,
            flags=re.IGNORECASE)
        self.assertIsNotNone(status)
        self.assertIsNotNone(options)
        self.assertRegex(status.group(0), r'\brole=["\']status["\']')
        self.assertNotRegex(options.group(0), r'\brole=')

    def test_precheck_footer_and_schema_controls_are_mobile_safe(self):
        self.assertRegex(
            self.compact,
            r"\.precheckDialog\.modalBtns\{"
            r"display:flex;align-items:center;justify-content:flex-end;"
            r"flex-wrap:wrap;",
        )
        self.assertIn(
            "display:grid;grid-template-columns:repeat(2,minmax(0,1fr));",
            self.compact,
        )
        self.assertRegex(
            self.compact,
            r"\.schemaStrategySelect,\.schemaStrategyMore>summary,"
            r"\.schemaStrategyCarddetails>summary\{min-height:44px\}",
        )

    def test_schema_rerender_restores_focus_and_contextual_drafts(self):
        self.assertRegex(
            self.compact,
            r"chairSelectedStrategyId='';"
            r"if\(draft&&valid\.has\(String\(draft\.strategy_id\|\|''\)\)\)",
        )
        self.assertIn(
            "button.dataset.strategyId===String(id)",
            self.html,
        )
        self.assertIn(
            "focusWithoutScrolling(replacement||summary)",
            self.html,
        )
        self.assertIn(
            "guide.querySelectorAll('.schemaStrategyCard>details[open]')",
            self.html,
        )
        self.assertIn(
            "selected=kind==='imagery'?latestSchemaStrategy(kind):'';",
            self.compact,
        )


if __name__ == "__main__":
    unittest.main()
