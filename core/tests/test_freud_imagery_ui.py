import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class FreudImageryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(PROJECT_DIR) / "index.html").read_text(
            encoding="utf-8")
        cls.markup = cls._between(
            "<!-- Freud: kullanıcının seçtiği literal görsellerle serbest "
            "çağrışım -->",
            "<!-- seans çerçevesi -->")
        cls.script = cls._between(
            "/* Freud: 24 literal kart, açık çerçeve ve yalnız kullanıcı "
            "tarafından kayıt. */",
            "/* ADHD koçu: ritimler, denemeler ve kullanıcı kontrollü "
            "defter. */")

    @classmethod
    def _between(cls, start, end):
        begin = cls.html.index(start)
        finish = cls.html.index(end, begin)
        return cls.html[begin:finish]

    def test_contextual_entry_points_start_hidden_and_are_unique(self):
        ids = (
            "mobileFreudImageryOpen", "composerQuickFreudImagery",
            "freudImageryOverlay", "freudImageryBack", "freudImageryStop",
            "freudImageryConsentForm", "freudImageryModelConsent",
            "freudImagerySuggest", "freudImageryAssociationForm",
            "freudImageryAssociationSave", "freudImageryClear",
        )
        for element_id in ids:
            self.assertEqual(
                len(re.findall(r'id=["\']' + re.escape(element_id) +
                               r'["\']', self.html)),
                1, element_id)
        self.assertRegex(
            self.html,
            r'id="mobileFreudImageryOpen"[^>]*role="menuitem" hidden')
        self.assertRegex(
            self.html,
            r'id="composerQuickFreudImagery"[^>]*role="menuitem" hidden')
        self.assertIn(
            ".mobileHeaderMenuItem[hidden]{display:none!important}",
            self.html)

    def test_gate_is_freud_main_active_and_consented(self):
        gate = self.html[
            self.html.index("function freudImageryTechniqueReady(){"):
            self.html.index("function syncStructuredWorkspaceVisibility(){")]
        for contract in (
                "STRUCTURED_WORKSPACE_MASTER_IDS.freud",
                "String(convData.submode||'')!==''",
                "String(activeTechnique.status||'').toLowerCase()!=="
                "'active'",
                "!activeTechnique.consent_at",
                "FREUD_FREE_ASSOCIATION_NODE_ID",
                "freud:method:free-association",
                "freud:serbest-cagrsm"):
            self.assertIn(contract, gate if contract.startswith("String(") or
                          contract.startswith("!") or
                          contract.startswith("STRUCTURED") or
                          contract.startswith("FREUD") else self.html)
        visibility = self.html[
            self.html.index("function syncStructuredWorkspaceVisibility(){"):
            self.html.index("function structuredRequestId")]
        self.assertIn("androidNativeMobileContext()", visibility)
        self.assertIn("freudImageryTechniqueReady()", visibility)
        self.assertIn("const freudVisible=mobileChatViewport()&&freudReady",
                      visibility)
        self.assertIn("button.hidden=!freudVisible", visibility)
        self.assertIn("hideOverlay('freudImageryOverlay')", visibility)

    def test_ios_mobile_and_desktop_launchers_share_the_exact_gate(self):
        visibility = self.html[
            self.html.index("function syncStructuredWorkspaceVisibility(){"):
            self.html.index("function structuredRequestId")]
        self.assertIn(
            "const nativeMobile=androidNativeMobileContext();", visibility)
        self.assertIn(
            "const freudVisible=mobileChatViewport()&&freudReady;",
            visibility)
        render = self.html[
            self.html.index("function renderImageryWork(){"):
            self.html.index("function applyImageryResponse")]
        self.assertIn(
            "const freudDeck=freudImageryTechniqueReady()&&!mobileChatViewport()",
            render)
        self.assertIn("setUiButtonLabel('imageryBtn','Görsel çağrışım')",
                      render)
        self.assertIn(
            "$('imageryBtn').setAttribute('aria-controls',"
            "'freudImageryOverlay')", render)
        handler = self.html[
            self.html.index("$('imageryBtn').onclick = ()=>{"):
            self.html.index("$('imageryCollapse').onclick")]
        self.assertIn(
            "if(freudImageryTechniqueReady())showFreudImageryWorkspace()",
            handler)
        self.assertIn("else if(imageryWork&&imageryWork.available)", handler)

    def test_explicit_frame_and_stop_are_always_present(self):
        for element_id in (
                "freudImageryOrientation", "freudImageryFrame",
                "freudImageryReality", "freudImageryStopSignal"):
            self.assertIn(f'id="{element_id}"', self.markup)
        self.assertIn("2–24 karakter", self.markup)
        self.assertIn("projektif test veya", self.markup)
        self.assertIn("Rorschach değildir", self.markup)
        self.assertRegex(
            self.markup,
            r'id="freudImageryStop"[^>]*aria-label="Görsel çağrışım '
            r'çalışmasını durdur"')
        consent = self.script[
            self.script.index("async function consentFreudImagery"):
            self.script.index("async function requestFreudImagerySuggestions")]
        for field in (
                "orientation_confirmed:true", "frame_confirmed:true",
                "reality_confirmed:true", "stop_signal:"):
            self.assertIn(field, consent)
        self.assertIn("action:'stop'", self.script)

    def test_all_cards_are_literal_safe_and_navigable(self):
        self.assertIn("FREUD_IMAGERY_CARD_LIMIT=24", self.script)
        self.assertIn("payload.cards.slice(0,FREUD_IMAGERY_CARD_LIMIT)",
                      self.script)
        self.assertIn('role="list" aria-label="24 görsel çağrışım kartı"',
                      self.markup)
        self.assertIn("title:String(value.title", self.script)
        self.assertIn("description:String(value.description", self.script)
        self.assertIn("alt:String(value.alt", self.script)
        self.assertIn("image.alt=card.alt", self.script)
        self.assertIn("description=guidedNode('small','',card.description)",
                      self.script)
        self.assertNotIn("innerHTML", self.script)
        self.assertIn(".textContent", self.script)

    def test_model_suggestions_require_separate_consent_and_never_select(self):
        self.assertIn("FREUD_IMAGERY_SUGGESTION_LIMIT=3", self.script)
        self.assertIn('id="freudImageryModelConsent"', self.markup)
        self.assertIn('id="freudImagerySuggest" disabled', self.markup)
        suggest = self.script[
            self.script.index("async function requestFreudImagerySuggestions"):
            self.script.index("async function saveFreudImageryAssociation")]
        self.assertIn("'/api/freud-imagery/suggest'", suggest)
        self.assertIn("model_consent:true", suggest)
        self.assertIn("if(response.selected!==false)", suggest)
        self.assertIn("Hiçbir kart seçilmedi", suggest)
        self.assertNotIn("chooseFreudImageryCard(", suggest)
        self.assertNotIn("action:'select'", suggest)

    def test_selection_is_draft_then_separate_save(self):
        choose = self.script[
            self.script.index("function chooseFreudImageryCard"):
            self.script.index("function renderFreudImagerySelection")]
        self.assertNotIn("freudImageryApi(", choose)
        self.assertIn("markGuidedFormDirty", choose)
        self.assertIn("focusWithoutScrolling($('freudImageryAssociation'))",
                      choose)
        save = self.script[
            self.script.index("async function saveFreudImageryAssociation"):
            self.script.index("async function clearFreudImagerySelection")]
        self.assertIn("'/api/freud-imagery/selection'", save)
        self.assertIn("action:'select'", save)
        self.assertIn("association", save)
        self.assertRegex(
            self.markup,
            r'id="freudImageryAssociationSave" disabled>Çağrışımı kaydet')

    def test_clear_is_confirmed_and_uses_physical_clear_contract(self):
        clear = self.script[
            self.script.index("async function clearFreudImagerySelection"):
            self.script.index("async function stopFreudImageryWorkspace")]
        self.assertIn("confirm('Kaydedilmiş kart ve çağrışım kalıcı olarak "
                      "silinsin mi?')", clear)
        self.assertIn("action:'clear'", clear)
        self.assertIn("revision:freudImageryRevision()", clear)

    def test_clear_button_reenables_after_load_or_mutation_finishes(self):
        busy = self.script[
            self.script.index("function setFreudImageryBusy"):
            self.script.index("function freudImageryRequestIsCurrent")]
        sync = self.script[
            self.script.index("function syncFreudImageryClearState"):
            self.script.index("async function loadFreudImagery")]
        self.assertIn("syncFreudImageryClearState()", busy)
        self.assertIn("!payload.selection", sync)
        self.assertIn("!payload.capabilities.clear", sync)

    def test_async_mutations_ignore_stale_conversation_and_closed_panel(self):
        guard = self.script[
            self.script.index("function freudImageryRequestIsCurrent"):
            self.script.index("async function freudImageryApi")]
        self.assertIn("requestConv===Number(convId)", guard)
        self.assertIn("classList.contains('show')", guard)
        names = (
            "consentFreudImagery", "requestFreudImagerySuggestions",
            "saveFreudImageryAssociation", "clearFreudImagerySelection",
            "stopFreudImageryWorkspace",
        )
        positions = [self.script.index("async function " + name)
                     for name in names]
        positions.append(len(self.script))
        for index, name in enumerate(names):
            body = self.script[positions[index]:positions[index + 1]]
            self.assertIn("const requestConv=Number(convId);", body, name)
            self.assertIn(
                "const sequence=++freudImageryRequestSequence;", body, name)
            self.assertIn(
                "freudImageryRequestIsCurrent(requestConv,sequence)",
                body, name)
        api = self.script[
            self.script.index("async function freudImageryApi"):
            self.script.index("function freudImageryCardButton")]
        self.assertIn(
            "data&&data.safety_hold&&requestConv===Number(convId)", api)
        hide = self.html[
            self.html.index("if(id==='freudImageryOverlay'){"):
            self.html.index("const back = overlayReturnFocus", self.html.index(
                "if(id==='freudImageryOverlay'){"))]
        self.assertIn("freudImageryStopping=false", hide)
        self.assertIn("freudImageryPayload=null", hide)
        self.assertIn("freudImagerySavedBody", hide)
        self.assertIn("freudImageryAssociation').value=''", hide)
        self.assertIn("$('freudImageryStop').disabled=false", hide)

    def test_loading_error_retry_back_focus_and_responsive_contract(self):
        for element_id in (
                "freudImageryLoading", "freudImageryError",
                "freudImageryRetry", "freudImageryBack",
                "freudImageryScroll"):
            self.assertIn(f'id="{element_id}"', self.markup)
        self.assertIn("requestOverlayDismiss('freudImageryOverlay')",
                      self.script)
        self.assertIn("showOverlay('freudImageryOverlay','freudImageryBack')",
                      self.script)
        self.assertIn("overlayReturnFocus.set('freudImageryOverlay'",
                      self.script)
        self.assertIn("@media(max-width:360px)", self.html)
        self.assertIn(
            "@media(orientation:landscape) and (max-height:420px)",
            self.html)
        self.assertRegex(
            self.html,
            r"\.freudImageryCard\{[^}]*min-height:44px")


if __name__ == "__main__":
    unittest.main()
