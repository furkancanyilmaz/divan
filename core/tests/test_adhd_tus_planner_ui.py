import hashlib
import json
import subprocess
import unittest
from pathlib import Path

from support import HTTPTestCase, PROJECT_DIR, app


class AdhdTusPlannerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(PROJECT_DIR)
        cls.html_path = cls.project / "index.html"
        cls.android_path = (
            cls.project.parent / "divan-android/app/src/main/python/index.html"
        )
        cls.catalog_path = cls.project / "assets/tus/catalog-v1.json"
        cls.android_catalog_path = (
            cls.project.parent
            / "divan-android/app/src/main/python/assets/tus/catalog-v1.json"
        )
        cls.android_gradle_path = (
            cls.project.parent / "divan-android/app/build.gradle.kts"
        )
        cls.html = cls.html_path.read_text(encoding="utf-8")
        cls.block = cls.between(
            "const ADHD_TUS_PROTOCOL=",
            "/* Kerem Genç: kullanıcı kanıtı"
        )

    @classmethod
    def between(cls, start, end):
        begin = cls.html.index(start)
        finish = cls.html.index(end, begin)
        return cls.html[begin:finish]

    def run_node(self, program):
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def pure_normalizer(self):
        return self.between(
            "const ADHD_TUS_PROTOCOL=",
            "function captureAdhdTusFocus("
        )

    def test_tus_is_chat_scoped_and_legacy_tab_stays_hidden(self):
        self.assertIn('id="adhdTusTab" role="tab"', self.html)
        self.assertIn('aria-controls="adhdTusPanel"', self.html)
        self.assertIn('id="adhdTusPanel"\n        role="tabpanel"', self.html)
        self.assertIn("tusTab.hidden=true", self.html)
        self.assertIn("const tusAvailable=false", self.html)
        self.assertIn("adhdTusLoadedConvId!==Number(convId)", self.html)
        self.assertIn("!adhdIdentity&&adhdWorkspaceTab==='tus'", self.html)
        self.assertIn('id="composerQuickTus" role="menuitem" hidden',
                      self.html)
        self.assertIn('<b>TUS Çalışma</b>', self.html)
        self.assertIn("$('composerQuickTus').onclick=()=>{void enterAdhdTusChat();}",
                      self.html)
        self.assertNotIn("showAdhdWorkspace('tus')", self.html)
        self.assertIn("@media(max-width:360px)", self.html)
        self.assertIn(".adhdTusOptions{grid-template-columns:1fr}", self.html)

    def test_chat_wire_is_strict_and_safety_cancel_only_is_narrow(self):
        program = self.pure_normalizer() + r"""
const question={id:'lesson',prompt:'Hangi ders?',total_options:1,
  filterable:true,has_more:false,options:[{id:'anatomy',label:'Anatomi'}]};
const prompt={message_id:41,
  message_public_id:'11111111111111111111111111111111',kind:'question',
  question_id:'lesson',planner_revision:3,ledger_revision:3,status:'open',
  safety_cancel_only:false};
const base={protocol:ADHD_TUS_CHAT_PROTOCOL,
  planner_protocol:ADHD_TUS_PROTOCOL,conv_id:7,revision:3,enabled:true,
  state:'question',history:[],question,plan:null,allowed_actions:['answer','cancel'],
  catalog:{available:true,fingerprint:'fp',lessons:13,question_areas:4371,
    reading_areas:3266},catalog_changed:false,notices:[],safety_hold:false,
  chat_surface:{protocol:ADHD_TUS_CHAT_PROTOCOL,requires_enter:false,prompt},
  new_messages:[]};
const normalized=normalizeAdhdTusPlanner(base,7);
if(normalized.wire_protocol!==ADHD_TUS_CHAT_PROTOCOL||
    normalized.chat_surface.prompt.message_id!==41||
    normalized.allowed_actions.join(',')!=='answer,cancel')
  throw new Error('chat wire was not preserved');
for(const changed of [
  {...base,protocol:ADHD_TUS_PROTOCOL},
  {...base,allowed_actions:['answer','root_shell']},
  {...base,chat_surface:{...base.chat_surface,prompt:{...prompt,
    message_public_id:'not-public'}}},
  {...base,chat_surface:{...base.chat_surface,prompt:{...prompt,
    ledger_revision:2}}},
  {...base,new_messages:[{id:'41',public_id:prompt.message_public_id,
    role:'assistant',content:'x',created:'now',delivery_status:'completed'}]}
]){
  let rejected=false;
  try{normalizeAdhdTusPlanner(changed,7);}catch(_){rejected=true;}
  if(!rejected)throw new Error('invalid chat projection accepted');
}
const safetyPrompt={...prompt,planner_revision:5,ledger_revision:3,
  safety_cancel_only:true};
const safety={...base,revision:5,state:'safety_hold',safety_hold:true,
  allowed_actions:['cancel'],chat_surface:{...base.chat_surface,
    prompt:safetyPrompt}};
const safe=normalizeAdhdTusPlanner(safety,7);
if(!safe.safety_hold||!safe.chat_surface.prompt.safety_cancel_only)
  throw new Error('cancel-only safety projection rejected');
for(const changed of [
  {...safety,allowed_actions:['cancel','answer']},
  {...safety,safety_hold:false,state:'question'},
  {...safety,chat_surface:{...safety.chat_surface,prompt:{...safetyPrompt,
    ledger_revision:6}}}
]){
  let rejected=false;
  try{normalizeAdhdTusPlanner(changed,7);}catch(_){rejected=true;}
  if(!rejected)throw new Error('widened safety projection accepted');
}
"""
        self.run_node(program)

    def test_chat_entry_and_search_use_only_chat_endpoint(self):
        loader = self.between(
            "async function loadAdhdTusChatSnapshot(",
            "function refreshAdhdTusPlanner(")
        self.assertIn("'/api/adhd/tus/chat?conv_id='", loader)
        self.assertNotIn("'/api/adhd/tus?conv_id='", loader)
        enter = self.between(
            "async function enterAdhdTusChat(",
            "/* Kerem Genç:")
        self.assertIn("loadAdhdTusChatSnapshot()", enter)
        self.assertIn("mutateAdhdTusChat('enter',{})", enter)
        mutation = self.between(
            "async function mutateAdhdTusChat(",
            "async function enterAdhdTusChat(")
        self.assertIn("api('/api/adhd/tus/chat',body,{quiet:true})", mutation)
        picker = self.between(
            "async function searchAdhdTusChatPicker(",
            "function adhdTusChatMutationBody(")
        self.assertIn("'/api/adhd/tus/chat?conv_id='", picker)
        self.assertNotIn("'/api/adhd/tus?conv_id='", picker)
        opener = self.between("async function openConv(", "async function newConv(")
        self.assertIn("void refreshAdhdConversationSurfacesAfterOpen(", opener)

    def test_prompt_attachment_is_exact_bubble_bound_and_composer_independent(self):
        anchor = self.between(
            "function adhdTusChatPromptBubble(",
            "function insertAdhdTusChatAttachment(")
        self.assertIn("messageBubbleById.get(Number(prompt.message_id))", anchor)
        self.assertIn("bubble.dataset.messagePublicId", anchor)
        self.assertIn("publicId===prompt.message_public_id", anchor)
        self.assertIn("function adhdTusChatPromptAttachment(", anchor)
        self.assertIn(":scope > .adhdTusChatAttachment", anchor)
        renderer = self.between(
            "function renderAdhdTusChatAttachment(",
            "function focusAdhdTusChatPrompt(")
        self.assertIn("clearAdhdTusChatAttachments()", renderer)
        self.assertIn("surface.requires_enter", renderer)
        self.assertIn("surface.prompt.safety_cancel_only", renderer)
        self.assertNotIn("addBubble(", renderer)
        self.assertNotIn("showAdhdWorkspace", renderer)
        self.assertIn("Normal composer", self.block)
        send = self.between("async function send(", "function selectedRadioValue(")
        self.assertNotIn("answerAdhdTus", send)
        self.assertNotIn("/api/adhd/tus/chat", send)
        self.assertIn("adhdTusMutationTokens.size||adhdTusChatLoading", send)
        self.assertIn("syncAdhdTusControls()", send)

    def test_chat_prompt_is_flat_and_does_not_highlight_or_mix_cards(self):
        compact = "".join(self.html.split())
        self.assertIn(
            ".adhdTusChatAttachment.adhdTusStepGroup{"
            "margin:1px00;padding:0;border:0;border-radius:0;"
            "background:transparent;overflow:visible}",
            compact,
        )
        focus = self.between(
            "function focusAdhdTusChatPrompt(",
            "function resetAdhdTusChatPicker(",
        )
        self.assertIn("revealChatElementNearest(attachment)", focus)
        self.assertNotIn("jumpToMessage(", focus)
        mutation = self.between(
            "async function mutateAdhdTusChat(",
            "async function enterAdhdTusChat(",
        )
        enter = self.between(
            "async function enterAdhdTusChat(",
            "/* Kerem Genç:",
        )
        self.assertIn("highlightTarget:false", mutation)
        self.assertIn("highlightTarget:false", enter)
        suggestion = self.between(
            "function clearAdhdConversationPrompt(",
            "let adhdDashboard=",
        )
        self.assertIn("function adhdTusConversationFlowOwnsChat()", suggestion)
        self.assertGreaterEqual(
            suggestion.count("adhdTusConversationFlowOwnsChat()"), 3)
        snapshot = self.between(
            "function applyAdhdTusSnapshot(",
            "async function loadAdhdTusPlanner(",
        )
        self.assertIn("adhdSuggestionRequestSequence++", snapshot)
        self.assertIn("clearAdhdConversationPrompt()", snapshot)
        ordered = self.between(
            "async function refreshAdhdConversationSurfacesAfterOpen(",
            "function refreshAdhdTusPlanner(",
        )
        self.assertIn("await loadAdhdTusChatSnapshot()", ordered)
        self.assertIn("!loaded||adhdTusConversationFlowOwnsChat()", ordered)
        self.assertIn("return refreshAdhdConversationSuggestion()", ordered)

    def test_chat_mutations_append_durable_pair_without_normal_full_reload(self):
        mutation = self.between(
            "async function mutateAdhdTusChat(",
            "async function enterAdhdTusChat(",
        )
        self.assertIn("captureChatViewportAnchor(", mutation)
        self.assertIn("deferChatAttachment:true", mutation)
        self.assertIn(
            "appendAdhdTusChatMessages(adhdTusPlanner.new_messages)",
            mutation,
        )
        self.assertIn("if(!appended.complete||!promptPresent)", mutation)
        self.assertIn(
            "!!adhdTusChatPromptAttachment(adhdTusPlanner.chat_surface)",
            mutation,
        )
        self.assertEqual(mutation.count("await openConv("), 1)
        self.assertIn("restoreChatViewportAnchor(viewportAnchor)", mutation)
        self.assertNotIn("scrollConversationToLatest(", mutation)
        self.assertNotIn("scrollIntoView(", mutation)
        self.assertLess(
            mutation.index("restoreChatViewportAnchor(viewportAnchor)"),
            mutation.index("focusAdhdTusChatPrompt(prompt.message_id)"),
        )
        finally_block = mutation[mutation.index("}finally{"):]
        self.assertNotIn("renderAdhdTusChatAttachment()", finally_block)

        appender = self.between(
            "function appendAdhdTusChatMessages(",
            "function focusAdhdTusChatPrompt(",
        )
        self.assertIn("messageBubbleById.get(id)", appender)
        self.assertIn("renderConversationMessage(message", appender)
        self.assertIn("if(id<=newest){complete=false;return;}", appender)
        focus = self.between(
            "function focusAdhdTusChatPrompt(",
            "function resetAdhdTusChatPicker(",
        )
        self.assertIn("const attachment=adhdTusChatPromptAttachment(surface)",
                      focus)
        self.assertIn("if(!attachment)return false", focus)

    def test_picker_preserves_input_node_focus_and_composition_contract(self):
        picker = self.between(
            "function renderAdhdTusChatPickerResults(",
            "function openAdhdTusChatPicker(")
        self.assertIn("const results=$('adhdTusChatPickerResults')", picker)
        self.assertIn("results.replaceChildren()", picker)
        self.assertNotIn("adhdTusChatPickerInput').replaceChildren", picker)
        search = self.between(
            "async function searchAdhdTusChatPicker(",
            "function adhdTusChatMutationBody(")
        self.assertIn("const focusWasInput=document.activeElement===input", search)
        self.assertIn("focusWithoutScrolling(input)", search)
        self.assertIn("input.setSelectionRange(start,end)", search)
        self.assertNotIn("renderAdhdTusChatAttachment()", search)
        self.assertNotIn("renderAdhdTusPlanner()", search)
        self.assertNotIn("input.addEventListener('input'", self.block)
        self.assertIn(
            "$('adhdTusChatPickerSubmit').addEventListener('pointerdown'",
            self.html)

    def test_android_tus_composer_is_stationary_and_picker_releases_ime(self):
        menu = self.between(
            "function syncComposerQuickMenu(",
            "function setComposerQuickMenu(")
        self.assertIn("const tusEnabled=", menu)
        self.assertIn("currentAdhdTusChatSurface()", menu)
        self.assertIn("tusSurface.prompt.status==='open'", menu)
        self.assertIn("inputBar.dataset.tusChatActive", menu)
        self.assertIn("fixedTusComposer", menu)
        self.assertIn("androidNativeMobileContext()", menu)
        self.assertIn("autoGrow()", menu)
        compact = "".join(self.html.split())
        self.assertIn(
            'body.nativeAndroid#inputBar[data-tus-chat-active="true"]#msg{'
            'height:44px!important;min-height:44px;max-height:44px;'
            'overflow-y:auto}',
            compact,
        )

        reset = self.between(
            "function resetAdhdTusChatPicker(",
            "function renderAdhdTusChatPickerResults(")
        self.assertIn(
            "overlayReturnFocus.delete('adhdTusChatPickerOverlay')", reset)
        self.assertIn("hideOverlay('adhdTusChatPickerOverlay')", reset)
        self.assertNotIn("overlay.classList.remove('show')", reset)
        self.assertIn("releaseAdhdTusChatPickerIme(overlay)", reset)

        hide = self.between("function hideOverlay(", "function requestOverlayDismiss(")
        self.assertIn("releaseAdhdTusChatPickerIme(overlay)", hide)

        release = self.between(
            "function releaseAdhdTusChatPickerIme(",
            "function hideOverlay(")
        self.assertIn("if(active&&overlay.contains(active))active.blur()", release)
        self.assertIn("DivanNative.hideKeyboard()", release)
        self.assertIn("settleMobileViewportAfterImeDismiss()", release)

        settle = self.between(
            "function settleMobileViewportAfterImeDismiss(",
            "function mobileHomeIsOpen(")
        self.assertIn("[0,120,300,560]", settle)
        self.assertIn("syncMobileViewportHeight()", settle)

        viewport = self.between(
            "function mobileTextEntryElement(",
            "function mobileHomeIsOpen(")
        self.assertIn("function resetAndroidMobileViewportHeight(", viewport)
        self.assertIn("function activateAndroidImeViewport(", viewport)
        self.assertIn("androidImeCssFallback=false", viewport)
        self.assertIn("DivanNative.mobileViewportHeight()", viewport)
        self.assertIn("function androidImeConfirmedHidden()", viewport)
        self.assertIn("androidViewportFillFallback", viewport)
        self.assertIn("root.style.setProperty('--mobile-vvh',nativeHeight+'px')",
                      viewport)
        self.assertIn("resetAndroidMobileViewportHeight({force:true})", viewport)
        self.assertIn("root.style.removeProperty('--mobile-vvh')", viewport)
        self.assertIn("document.body.classList.remove('workImeCompact')", viewport)
        self.assertIn("if(resetAndroidMobileViewportHeight())return", viewport)
        self.assertIn(
            "if(androidImeConfirmedHidden()&&\n"
            "      resetAndroidMobileViewportHeight({force:true}))return",
            viewport,
        )
        activate = self.between(
            "function activateAndroidImeViewport(",
            "function resetAndroidMobileViewportHeight(",
        )
        self.assertIn("if(androidImeConfirmedHidden())", activate)
        self.assertIn("androidImeCssFallback=true", activate)

        lifecycle = self.between(
            "if(window.visualViewport){",
            "addEventListener('pagehide',")
        self.assertIn("document.addEventListener('focusout'", lifecycle)
        self.assertIn("document.addEventListener('focusin'", lifecycle)
        self.assertIn("document.addEventListener('click'", lifecycle)
        self.assertIn("document.addEventListener('beforeinput'", lifecycle)
        self.assertIn("event.target===document.activeElement", lifecycle)
        self.assertIn("window.divanAndroidViewportChanged", lifecycle)
        self.assertIn("document.addEventListener('visibilitychange'", lifecycle)
        self.assertIn("addEventListener('pageshow'", lifecycle)

        picker_open = self.between(
            "function openAdhdTusChatPicker(",
            "async function searchAdhdTusChatPicker(")
        self.assertIn("const nativeMobile=androidNativeMobileContext()", picker_open)
        self.assertIn("if(nativeMobile)dismissMobileComposer()", picker_open)
        self.assertIn(
            "nativeMobile?'adhdTusChatPickerClose':'adhdTusChatPickerInput'",
            picker_open,
        )

    def test_native_hidden_ime_wins_over_stale_visual_viewport_every_sync(self):
        viewport_functions = self.between(
            "function androidImeConfirmedHidden(",
            "function settleMobileViewportAfterImeDismiss(",
        )
        program = r"""
let androidImeCssFallback=false,mobileViewportSettleSequence=0;
let imeVisible=false;
const values={};
const classList={add(){},remove(){},toggle(){}};
const root={classList,style:{
  setProperty(key,value){values[key]=value;},
  removeProperty(key){delete values[key];}
}};
const document={documentElement:root,body:{classList}};
const window={visualViewport:{height:491},innerHeight:491};
const DivanNative={
  mobileImeStateKnown(){return true;},
  mobileImeVisible(){return imeVisible;},
  mobileViewportHeight(){return 750;}
};
function androidNativeMobileContext(){return true;}
function mobileChatViewport(){return true;}
function mobileTextEntryElement(){return true;}
function clearMobileComposerAnchor(){}
function pinMobileRootScroll(){}
""" + viewport_functions + r"""
syncMobileViewportHeight();
if(values['--mobile-vvh']!=='750px')
  throw new Error('hidden IME did not force native height');
androidImeCssFallback=false;
activateAndroidImeViewport({});
syncMobileViewportHeight();
if(values['--mobile-vvh']!=='750px'||!androidImeCssFallback)
  throw new Error('focus revived stale hidden viewport');
imeVisible=true;
activateAndroidImeViewport({});
syncMobileViewportHeight();
if(values['--mobile-vvh']!=='491px'||androidImeCssFallback)
  throw new Error('visible IME did not use live visual viewport');
"""
        self.run_node(program)

        lock = self.between(
            "function enterAppLockedState(",
            "async function loadUnlockedShell(")
        self.assertIn(
            "resetAdhdTusChatPicker({restoreFocus:false})", lock)

    def test_chat_controls_lock_for_streaming_and_cancel_survives_safety(self):
        controls = self.between(
            "function syncAdhdTusControls(",
            "function resetAdhdTusPlanner(")
        self.assertIn("const interactionLocked=busy||streaming", controls)
        self.assertIn("[data-tus-chat-action]", controls)
        mutation = self.between(
            "async function mutateAdhdTusChat(",
            "async function enterAdhdTusChat(")
        self.assertIn("wireAction!=='cancel'&&!conversationReady", mutation)
        self.assertIn("!identityReady", mutation)
        self.assertIn("streaming||", mutation)

    def test_safety_transition_invalidates_stale_chat_controls(self):
        matcher = self.between(
            "function adhdTusSafetyProjectionMatchesConversation(",
            "function setAdhdTusWorkspaceStatus(")
        self.run_node(r"""
let convId=17,adhdTusLoadedConvId=17;
let convData={safety_hold:false};
let adhdTusPlanner={safety_hold:false};
""" + matcher + r"""
if(!adhdTusSafetyProjectionMatchesConversation())
  throw new Error('matching safety projection rejected');
convData.safety_hold=true;
if(adhdTusSafetyProjectionMatchesConversation())
  throw new Error('stale pre-safety projection accepted');
adhdTusPlanner.safety_hold=true;
if(!adhdTusSafetyProjectionMatchesConversation())
  throw new Error('fresh cancel-only projection rejected');
adhdTusLoadedConvId=18;
if(adhdTusSafetyProjectionMatchesConversation())
  throw new Error('foreign conversation projection accepted');
""")

        setter = self.between(
            "function setConversationSafetyHold(",
            "function responseMessage(")
        self.assertIn("const changed=", setter)
        self.assertIn("clearAdhdTusChatAttachments()", setter)
        self.assertIn("resetAdhdTusChatPicker({restoreFocus:false})", setter)
        self.assertIn("syncComposerQuickMenu()", setter)
        self.assertIn("void loadAdhdTusChatSnapshot()", setter)

        controls = self.between(
            "function syncAdhdTusControls(",
            "function resetAdhdTusPlanner(")
        self.assertIn("safetyProjectionMismatch", controls)
        self.assertIn(
            "control.disabled=interactionLocked||safetyProjectionMismatch",
            controls)

        surface = self.between(
            "function currentAdhdTusChatSurface(",
            "function adhdTusChatPromptBubble(")
        self.assertIn(
            "!adhdTusSafetyProjectionMatchesConversation()", surface)
        enter = self.between(
            "async function enterAdhdTusChat(",
            "/* Kerem Genç:")
        self.assertIn(
            "!adhdTusSafetyProjectionMatchesConversation()", enter)

    def test_one_question_flow_is_bounded_and_strict(self):
        program = self.pure_normalizer() + r"""
const raw={protocol:ADHD_TUS_PROTOCOL,conv_id:7,revision:3,enabled:true,
  state:'question',history:[{question_id:'activity',
    question:'Bugün nasıl çalışalım?',answer_id:'mixed',answer:'Karma'}],
  question:{id:'lesson',prompt:'Hangi ders?',total_options:2,
    filterable:false,has_more:false,options:[
      {id:'pharmacology',label:'Farmakoloji',description:'120 alan'},
      {id:'anatomy',label:'Anatomi'}]},plan:null,
  allowed_actions:['answer','restart','root_shell'],catalog:{available:true,
    fingerprint:'catalog-1',lessons:12,question_areas:340,reading_areas:280},
  notices:[],safety_hold:false};
const normalized=normalizeAdhdTusPlanner(raw,7);
if(normalized.question.id!=='lesson'||normalized.question.options.length!==2)
  throw new Error('one-question flow lost');
if(normalized.history.length!==1||normalized.history[0].answer!=='Karma')
  throw new Error('selected history lost');
if(normalized.allowed_actions.join(',')!=='answer,restart')
  throw new Error('unknown action admitted');
if(normalized.question.options.some(row=>Object.keys(row).some(
    key=>!['id','label','description'].includes(key))))
  throw new Error('option wire widened');
let rejected=false;
try{normalizeAdhdTusPlanner({...raw,protocol:'adhd_tus_planner_v2'},7);}
catch(_){rejected=true;}
if(!rejected)throw new Error('protocol mismatch accepted');
rejected=false;
try{normalizeAdhdTusPlanner({...raw,conv_id:8},7);}
catch(_){rejected=true;}
if(!rejected)throw new Error('conversation mismatch accepted');
"""
        self.run_node(program)

    def test_filterable_zero_result_is_valid_but_other_empty_wires_close(self):
        program = self.pure_normalizer() + r"""
const base={protocol:ADHD_TUS_PROTOCOL,conv_id:17,revision:4,enabled:true,
  state:'question',history:[],question:{id:'lesson',prompt:'Hangi ders?',
    options:[],total_options:0,filterable:true,has_more:false},plan:null,
  allowed_actions:['answer','restart'],catalog:{available:true,
    fingerprint:'catalog-1',lessons:13,question_areas:4371,
    reading_areas:3266},notices:[],safety_hold:false};
const filtered=normalizeAdhdTusPlanner(base,17);
if(filtered.question.options.length!==0||filtered.question.total_options!==0||
    !filtered.question.filterable||filtered.question.has_more)
  throw new Error('exact zero-result filter was not preserved');
for(const question of [
  {...base.question,filterable:false},
  {...base.question,options:undefined},
  {...base.question,options:[{id:'bad only'}]},
  {...base.question,total_options:1},
  {...base.question,has_more:true}
]){
  let rejected=false;
  try{normalizeAdhdTusPlanner({...base,question},17);}catch(_){rejected=true;}
  if(!rejected)throw new Error('invalid empty option wire accepted');
}
"""
        self.run_node(program)

        refresh_helper = self.between(
            "function refreshAdhdTusPlanner(",
            "async function mutateAdhdTusPlanner("
        )
        program = r"""
let adhdTusProtocolBlocked=true,adhdTusFilterQuery='eşleşmeyen',
  adhdTusOptionOffset=24,lastLoad=null;
function loadAdhdTusPlanner(options){lastLoad=options;return true;}
""" + refresh_helper + r"""
refreshAdhdTusPlanner({announce:true});
if(adhdTusFilterQuery!==''||adhdTusOptionOffset!==0||
    lastLoad.query!==''||lastLoad.announce!==true)
  throw new Error('protocol recovery retained the wedged query');
adhdTusProtocolBlocked=false;adhdTusFilterQuery='farma';lastLoad=null;
refreshAdhdTusPlanner({announce:false});
if(lastLoad.query!==null||lastLoad.announce!==false||
    adhdTusFilterQuery!=='farma')
  throw new Error('ordinary refresh unexpectedly cleared the filter');
"""
        self.run_node(program)
        self.assertIn("'Sonuç bulunamadı'", self.block)
        self.assertIn("'Tümünü göster','filter'", self.block)
        self.assertIn(
            "$('adhdTusRefresh').onclick=()=>refreshAdhdTusPlanner(",
            self.html
        )

    def test_zero_result_renderer_keeps_search_and_clear_recovery(self):
        renderer = self.between(
            "function renderAdhdTusQuestion(",
            "function adhdTusStepMeta("
        )
        program = r"""
class FakeNode{
  constructor(tag='',className='',text=''){
    this.tag=tag;this.className=className;this.textContent=text;
    this.childNodes=[];this.dataset={};this.attributes={};this.disabled=false;
  }
  appendChild(child){this.childNodes.push(child);return child;}
  append(...children){children.forEach(child=>this.appendChild(child));}
  setAttribute(name,value){this.attributes[name]=String(value);}
}
function guidedNode(tag,className='',text=''){
  return new FakeNode(tag,className,text);
}
function adhdTusDynamicButton(label,action,{onclick=null}={}){
  const button=guidedNode('button','',label);button.dataset.tusAction=action;
  button.onclick=onclick;return button;
}
function answerAdhdTusQuestion(){throw new Error('no option may be answered');}
let loadArgs=null;
function loadAdhdTusPlanner(options){loadArgs=options;return true;}
let adhdTusFilterQuery='eşleşmeyen ders',adhdTusOptionOffset=0;
const adhdTusPlanner={question:{id:'lesson',prompt:'Hangi ders?',options:[],
  total_options:0,filterable:true,has_more:false}};
""" + renderer + r"""
const root=guidedNode('div');renderAdhdTusQuestion(root);
const all=[];(function visit(node){all.push(node);node.childNodes.forEach(visit);})(root);
if(!all.some(node=>node.textContent==='Sonuç bulunamadı'&&
    node.attributes.role==='status'))
  throw new Error('zero-result status was not rendered');
const input=all.find(node=>node.id==='adhdTusFilterInput');
if(!input||input.value!=='eşleşmeyen ders')
  throw new Error('active search draft disappeared');
const clear=all.find(node=>node.tag==='button'&&
  node.textContent==='Tümünü göster');
if(!clear||typeof clear.onclick!=='function')
  throw new Error('clear recovery control missing');
clear.onclick();
if(!loadArgs||loadArgs.query!=='')
  throw new Error('clear recovery retained the filter query');
"""
        self.run_node(program)

    def test_raw_question_and_sentence_content_cannot_enter_model(self):
        program = self.pure_normalizer() + r"""
const secret='RAW-CONTENT-MUST-NOT-LEAK';
const raw={protocol:ADHD_TUS_PROTOCOL,conv_id:9,revision:1,enabled:true,
  state:'question',history:[],question:{id:'question_area',prompt:'Hangi alan?',
    options:[{id:'area-1',label:'Kardiyoloji',raw_question:secret,
      sentence_text:secret,content:secret,choices:[secret]}]},plan:null,
  allowed_actions:['answer'],catalog:{available:true,lessons:1,
    question_areas:1,reading_areas:1,raw_questions:[secret]},
  raw_question:secret,sentence_text:secret,notices:[]};
const normalized=normalizeAdhdTusPlanner(raw,9);
const serialized=JSON.stringify(normalized);
if(serialized.includes(secret))throw new Error('raw content leaked');
if(serialized.includes('raw_question')||serialized.includes('sentence_text')||
    serialized.includes('choices'))throw new Error('raw field leaked');
"""
        self.run_node(program)
        self.assertNotIn("source.question_text", self.block)
        self.assertNotIn("source.sentence_text", self.block)

    def test_stale_response_and_revision_are_rejected(self):
        program = self.pure_normalizer() + r"""
const snapshot={protocol:ADHD_TUS_PROTOCOL,conv_id:4,revision:8};
const base={target:4,sequence:12,currentSequence:12,currentConv:4,
  currentRevision:8,minimumRevision:0};
if(!adhdTusSnapshotAcceptable(snapshot,base))
  throw new Error('current snapshot rejected');
if(adhdTusSnapshotAcceptable(snapshot,{...base,sequence:11}))
  throw new Error('stale sequence accepted');
if(adhdTusSnapshotAcceptable(snapshot,{...base,currentConv:5}))
  throw new Error('stale conversation accepted');
if(adhdTusSnapshotAcceptable({...snapshot,revision:7},base))
  throw new Error('revision rollback accepted');
if(adhdTusSnapshotAcceptable(snapshot,{...base,minimumRevision:9}))
  throw new Error('stale mutation result accepted');
"""
        self.run_node(program)

    def test_process_death_reload_round_trips_server_state_only(self):
        program = self.pure_normalizer() + r"""
const state={protocol:ADHD_TUS_PROTOCOL,conv_id:21,revision:11,enabled:true,
  state:'active',history:[{question_id:'available_time',
    question:'Kaç dakikan var?',answer_id:'25',answer:'25 dakika'}],
  question:null,plan:{id:'plan-21',title:'Bugünkü kısa tur',summary:'Tek odak',
    steps:[{id:'step-1',title:'Malzemeyi aç',kind:'setup',status:'completed'},
      {id:'step-2',title:'Farmakoloji tekrarına geç',kind:'reading',
       status:'active',duration_minutes:7,quantity:8,unit:'cümle'},
      {id:'step-3',title:'Aynı alandan soru çöz',kind:'questions',
       status:'pending',quantity:6,unit:'soru'}]},
  allowed_actions:['pause','complete_step','finish'],
  catalog:{available:true,fingerprint:'fp',lessons:12,
    question_areas:340,reading_areas:280},notices:[],safety_hold:false};
const first=normalizeAdhdTusPlanner(state,21);
const afterDeath=normalizeAdhdTusPlanner(JSON.parse(JSON.stringify(state)),21);
if(JSON.stringify(first)!==JSON.stringify(afterDeath))
  throw new Error('process-death reload changed state');
if(afterDeath.plan.steps.filter(step=>step.status==='active').length!==1)
  throw new Error('current step lost');
"""
        self.run_node(program)

    def test_exact_backend_nulls_notices_and_catalog_recovery(self):
        program = self.pure_normalizer() + r"""
const notices={no_streak:'Seri yok.',no_debt:'Borç yok.',
  local_only:'Bu cihazda.',content_boundary:'Yalnız katalog.',ignored:'GİRME'};
const base={protocol:ADHD_TUS_PROTOCOL,conv_id:31,revision:0,
  enabled:false,state:'disabled',history:[],question:null,plan:null,
  allowed_actions:['set_mode'],catalog:{available:true,fingerprint:'fp',
    lessons:13,question_areas:20,reading_areas:19},notices,
  catalog_changed:false,safety_hold:false};
const initial=normalizeAdhdTusPlanner(base,31);
if(initial.revision!==0||initial.allowed_actions[0]!=='set_mode')
  throw new Error('initial revision zero lost');
if(initial.notices.join('|')!=='Seri yok.|Borç yok.|Bu cihazda.|Yalnız katalog.')
  throw new Error('notice map order/boundary lost');
if(JSON.stringify(initial).includes('GİRME'))throw new Error('unknown notice leaked');
const changed=normalizeAdhdTusPlanner({...base,enabled:true,state:'question',
  revision:4,catalog_changed:true,allowed_actions:['restart','set_mode']},31);
if(!changed.catalog_changed||changed.question!==null)
  throw new Error('catalog change recovery rejected');
const unavailable=normalizeAdhdTusPlanner({...base,enabled:true,
  state:'question',revision:2,catalog:{...base.catalog,available:false}},31);
if(unavailable.question!==null)throw new Error('unavailable catalog widened');
let rejected=false;
try{normalizeAdhdTusPlanner({...base,enabled:true,state:'question',revision:2},31);}
catch(_){rejected=true;}
if(!rejected)throw new Error('available catalog missing question accepted');
const plan=normalizeAdhdTusPlanner({...base,enabled:true,state:'active',
  revision:8,plan:{id:'plan-1',title:'Kısa tur',summary:'',steps:[{
    id:'step-1',title:'Başla',detail:null,kind:'setup',status:'active',
    duration_minutes:1,quantity:null,unit:null}]},
  allowed_actions:['pause','complete_step','finish','cancel']},31);
if(plan.plan.steps[0].detail!==''||plan.plan.steps[0].unit!==''||
    plan.plan.steps[0].quantity!==0)throw new Error('nullable step failed');
"""
        self.run_node(program)

    def test_focus_helper_restores_recreated_panel_input(self):
        focus_helpers = self.between(
            "function captureAdhdTusFocus(",
            "let adhdTusPlanner="
        )
        program = r"""
let focused=null;
const oldInput={id:'adhdTusFilterInput',value:'farma',selectionStart:5,
  selectionEnd:5,disabled:false};
const newInput={id:'adhdTusFilterInput',value:'',disabled:false,
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}};
const body={id:'body'},panel={contains(node){return node===oldInput;}};
const nodes={adhdTusPanel:panel,adhdTusFilterInput:oldInput};
const document={activeElement:oldInput,body,documentElement:{id:'html'}};
function $(id){return nodes[id]||null;}
function focusWithoutScrolling(node){focused=node;document.activeElement=node;}
""" + focus_helpers + r"""
const snapshot=captureAdhdTusFocus();
nodes.adhdTusFilterInput=newInput;document.activeElement=body;
restoreAdhdTusFocus(snapshot);
if(focused!==newInput||newInput.value!=='farma'||newInput.selectionStart!==5)
  throw new Error('focused draft not restored');
"""
        self.run_node(program)
        self.assertNotIn("msgBox.disabled", self.block)
        self.assertNotIn("schemaPathBusy", self.block)
        self.assertIn("{quiet:true}", self.block)
        self.assertIn("loadAdhdTusPlanner({background:true})", self.html)
        self.assertIn("if(adhdTusMutationTokens.size)return false;", self.block)
        background_loader = self.between(
            "async function loadAdhdTusPlanner(",
            "async function mutateAdhdTusPlanner("
        )
        self.assertNotIn("msgBox", background_loader)
        self.assertNotIn("beginAdhdTusMutation", background_loader)
        self.assertNotIn("adhdWorkspaceBusy", background_loader)
        self.assertIn("if(!background)", background_loader)
        self.assertIn("undefined,{quiet:true}", background_loader)

    def test_controls_cover_full_lifecycle_without_exposing_future_steps(self):
        for action in (
            "set_mode", "restart", "start", "pause", "resume",
            "complete_step", "finish"
        ):
            self.assertIn("'" + action + "'", self.block)
        self.assertIn("renderAdhdTusStepGroup(parent,'Sonraki adımlar',future)",
                      self.block)
        self.assertIn("const future=adhdTusPlanner.state==='completed'?[]:",
                      self.block)
        self.assertIn("source.plan.steps:[]).slice(0,20)", self.block)
        self.assertIn("guidedNode('details','adhdTusStepGroup')", self.block)
        self.assertNotIn("details.open=true", self.block)
        self.assertIn("mutateAdhdTusPlanner('pause',{},", self.block)
        self.assertIn("mutateAdhdTusPlanner('resume',{},", self.block)
        self.assertNotIn("mutateAdhdTusPlanner('pause',{plan_id", self.block)
        self.assertNotIn("mutateAdhdTusPlanner('resume',{plan_id", self.block)
        self.assertIn("'Planı bırak','cancel'", self.block)
        self.assertIn("question.options.filter", self.block)
        self.assertIn("visibleOptions.slice(adhdTusOptionOffset,", self.block)
        self.assertIn("adhdTusOptionOffset+pageSize", self.block)
        self.assertIn("'Diğer seçenekler','option-page'", self.block)
        question_render = self.between(
            "function renderAdhdTusQuestion(",
            "function adhdTusStepMeta("
        )
        self.assertNotIn("question.options.forEach", question_render)
        self.assertIn("if(adhdTusPlanner.catalog_changed)", self.block)
        self.assertIn("'Yeni katalogla baştan planla'", self.block)
        self.assertIn("adhdTusProtocolBlocked", self.block)
        self.assertIn("Değişiklikler kapalı tutuldu", self.block)
        self.assertIn("wireAction==='cancel'", self.block)
        self.assertIn("wireAction==='set_mode'&&extra.enabled===false", self.block)
        self.assertIn(
            "structuredWorkspaceIdentity(STRUCTURED_WORKSPACE_MASTER_IDS.adhd)",
            self.block
        )

    def test_common_android_clients_are_byte_identical(self):
        common = self.html_path.read_bytes()
        embedded = self.android_path.read_bytes()
        self.assertEqual(common, embedded)
        self.assertEqual(
            hashlib.sha256(common).hexdigest(),
            hashlib.sha256(embedded).hexdigest()
        )

    def test_android_catalog_is_frozen_metadata_only_and_packaged(self):
        expected_digest = (
            "88d868de90435a2cc38e1c41d35c25b20bddbaa6221b412715c4009735a12182"
        )
        common = self.catalog_path.read_bytes()
        embedded = self.android_catalog_path.read_bytes()
        self.assertEqual(common, embedded)
        self.assertEqual(hashlib.sha256(common).hexdigest(), expected_digest)
        catalog = json.loads(common)
        self.assertEqual(catalog["protocol"], "divan_tus_catalog_v1")
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(len(catalog["lessons"]), 13)
        self.assertEqual(len(catalog["question_areas"]), 4371)
        self.assertEqual(len(catalog["reading_areas"]), 3266)
        self.assertEqual(catalog["totals"]["question_count"], 58335)
        self.assertEqual(catalog["totals"]["sentence_count"], 304139)

        forbidden = {
            "answer", "answers", "choice", "choices", "content",
            "contents", "explanation", "explanations", "option",
            "options", "prompt", "question", "questions",
            "question_text", "raw", "sentence", "sentences",
            "sentence_text", "solution", "solutions", "stem", "text",
        }

        def all_keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key.lower()
                    yield from all_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from all_keys(child)

        self.assertTrue(forbidden.isdisjoint(all_keys(catalog)))
        gradle = self.android_gradle_path.read_text(encoding="utf-8")
        self.assertIn('include("assets/tus/**")', gradle)
        self.assertIn(expected_digest, gradle)
        self.assertIn('setOf("catalog-v1.json")', gradle)
        self.assertIn('include("**/*.db", "**/*.db-*", "**/*.sqlite",', gradle)
        self.assertIn(
            "file.canonicalFile != embeddedTusCatalog.canonicalFile", gradle
        )


class AdhdTusRealWireUiTests(HTTPTestCase):
    """Feed exact Handler responses into the shipped client normalizer."""

    @classmethod
    def setUpClass(cls):
        cls.html = (Path(PROJECT_DIR) / "index.html").read_text(
            encoding="utf-8"
        )
        begin = cls.html.index("const ADHD_TUS_PROTOCOL=")
        finish = cls.html.index("function captureAdhdTusFocus(", begin)
        cls.normalizer = cls.html[begin:finish]
        focus_finish = cls.html.index("let adhdTusPlanner=", finish)
        cls.focus_helpers = cls.html[finish:focus_finish]

    def setUp(self):
        super().setUp()
        self.conv_id = self.conversation(therapist="adhd")
        self.snapshots = []
        self.request_number = 0

    def post(self, snapshot, action, **extra):
        self.request_number += 1
        payload = {
            "protocol": "adhd_tus_planner_v1",
            "conv_id": self.conv_id,
            "action": action,
            "expected_revision": snapshot["revision"],
            "request_id": "adhd-tus-ui-real-{:04d}".format(
                self.request_number
            ),
        }
        payload.update(extra)
        status, body, _ = self.request("POST", "/api/adhd/tus", payload)
        self.assertEqual(status, 200, body)
        self.snapshots.append(body)
        return body

    def assert_client_normalizes_all(self):
        encoded = json.dumps(
            self.snapshots, ensure_ascii=False, separators=(",", ":")
        )
        program = self.normalizer + "\nconst snapshots=" + encoded + r""";
for(const snapshot of snapshots){
  const normalized=normalizeAdhdTusPlanner(snapshot,snapshot.conv_id);
  if(normalized.revision!==snapshot.revision)
    throw new Error('wire revision changed');
  if(normalized.protocol!=='adhd_tus_planner_v1')
    throw new Error('wire protocol changed');
}
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_temp_db_http_flow_normalizes_and_uses_exact_mutations(self):
        status, snapshot, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id)
        )
        self.assertEqual(status, 200, snapshot)
        self.assertEqual(snapshot["protocol"], "adhd_tus_planner_v1")
        self.assertEqual(snapshot["revision"], 0)
        self.assertEqual(snapshot["state"], "disabled")
        self.assertTrue(snapshot["catalog"]["available"])
        self.snapshots.append(snapshot)

        snapshot = self.post(snapshot, "set_mode", enabled=True)
        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual(snapshot["state"], "question")

        while snapshot["state"] == "question":
            question = snapshot["question"]
            self.assertIsInstance(question, dict, snapshot)
            self.assertLessEqual(len(question["options"]), 40)
            option = next(
                (row for row in question["options"]
                 if row["id"] != "custom"),
                question["options"][0],
            )
            extra = {
                "question_id": question["id"],
                "option_id": option["id"],
            }
            snapshot = self.post(snapshot, "answer", **extra)

        self.assertEqual(snapshot["state"], "plan_ready")
        plan_id = snapshot["plan"]["id"]
        self.assertTrue(snapshot["plan"]["steps"])
        self.assertLessEqual(len(snapshot["plan"]["steps"]), 20)
        snapshot = self.post(snapshot, "start", plan_id=plan_id)
        self.assertEqual(snapshot["state"], "active")

        # pause/resume accept only the common envelope: plan_id would be an
        # unknown field under the frozen protocol.
        snapshot = self.post(snapshot, "pause")
        self.assertEqual(snapshot["state"], "paused")
        bad_payload = {
            "protocol": "adhd_tus_planner_v1", "conv_id": self.conv_id,
            "action": "resume", "expected_revision": snapshot["revision"],
            "request_id": "adhd-tus-ui-bad-resume", "plan_id": plan_id,
        }
        status, _, _ = self.request("POST", "/api/adhd/tus", bad_payload)
        self.assertEqual(status, 400)
        snapshot = self.post(snapshot, "resume")
        self.assertEqual(snapshot["state"], "active")
        snapshot = self.post(snapshot, "finish", plan_id=plan_id)
        self.assertEqual(snapshot["state"], "completed")
        self.assertTrue(any(
            step["status"] == "pending" for step in snapshot["plan"]["steps"]
        ))
        self.assert_client_normalizes_all()

    def test_real_zero_result_query_recovers_without_losing_filter_focus(self):
        status, snapshot, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id)
        )
        self.assertEqual(status, 200, snapshot)
        snapshot = self.post(snapshot, "set_mode", enabled=True)
        self.assertEqual(snapshot["question"]["id"], "activity")
        snapshot = self.post(
            snapshot, "answer", question_id="activity", option_id="mixed"
        )
        self.assertEqual(snapshot["question"]["id"], "lesson")
        self.assertTrue(snapshot["question"]["filterable"])

        query = "zzzz-divan-no-matching-lesson-zzzz"
        status, empty, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}&q={}".format(
                self.conv_id, query
            )
        )
        self.assertEqual(status, 200, empty)
        self.assertEqual(empty["question"]["options"], [])
        self.assertEqual(empty["question"]["total_options"], 0)
        self.assertTrue(empty["question"]["filterable"])
        self.assertFalse(empty["question"]["has_more"])

        status, recovered, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id)
        )
        self.assertEqual(status, 200, recovered)
        self.assertTrue(recovered["question"]["options"])
        self.assertGreater(recovered["question"]["total_options"], 0)
        self.snapshots.extend([empty, recovered])

        program = self.normalizer + self.focus_helpers + "\n" + (
            "const exactEmpty=" + json.dumps(
                empty, ensure_ascii=False, separators=(",", ":")
            ) + ";\nconst exactRecovered=" + json.dumps(
                recovered, ensure_ascii=False, separators=(",", ":")
            ) + ";\nconst query=" + json.dumps(query) + ";\n"
        ) + r"""
let focused=null;
const oldInput={id:'adhdTusFilterInput',value:query,
  selectionStart:query.length,selectionEnd:query.length,disabled:false};
const newInput={id:'adhdTusFilterInput',value:'',disabled:false,
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}};
const body={id:'body'},panel={contains(node){return node===oldInput;}};
const nodes={adhdTusPanel:panel,adhdTusFilterInput:oldInput};
const document={activeElement:oldInput,body,documentElement:{id:'html'}};
function $(id){return nodes[id]||null;}
function focusWithoutScrolling(node){focused=node;document.activeElement=node;}
const zero=normalizeAdhdTusPlanner(exactEmpty,exactEmpty.conv_id);
if(zero.question.options.length||zero.question.total_options!==0)
  throw new Error('real zero-result response failed normalization');
const savedFocus=captureAdhdTusFocus();
nodes.adhdTusFilterInput=newInput;document.activeElement=body;
restoreAdhdTusFocus(savedFocus);
if(focused!==newInput||newInput.value!==query||
    newInput.selectionStart!==query.length)
  throw new Error('real zero-result render lost the active filter draft');
const full=normalizeAdhdTusPlanner(exactRecovered,exactRecovered.conv_id);
if(!full.question.options.length||full.question.total_options<1)
  throw new Error('unfiltered recovery response remained wedged');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_client_normalizes_all()

    def test_real_safety_hold_still_allows_explicit_mode_off(self):
        status, snapshot, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id)
        )
        self.assertEqual(status, 200, snapshot)
        self.snapshots.append(snapshot)
        snapshot = self.post(snapshot, "set_mode", enabled=True)
        while snapshot["state"] == "question":
            question = snapshot["question"]
            option = next(
                (row for row in question["options"]
                 if row["id"] != "custom"),
                question["options"][0],
            )
            snapshot = self.post(
                snapshot, "answer", question_id=question["id"],
                option_id=option["id"]
            )
        plan_id = snapshot["plan"]["id"]
        snapshot = self.post(snapshot, "start", plan_id=plan_id)
        with app.db() as connection:
            connection.execute(
                "UPDATE conversations SET safety_hold=1 WHERE id=?",
                (self.conv_id,),
            )
            self.assertTrue(app.pause_adhd_tus_plan(
                connection, self.conv_id
            ))
        status, snapshot, _ = self.request(
            "GET", "/api/adhd/tus?conv_id={}".format(self.conv_id)
        )
        self.assertEqual(status, 200, snapshot)
        self.assertTrue(snapshot["safety_hold"])
        self.assertEqual(snapshot["state"], "paused")
        self.assertIn("set_mode", snapshot["allowed_actions"])
        self.assertIn("cancel", snapshot["allowed_actions"])
        self.snapshots.append(snapshot)
        snapshot = self.post(snapshot, "set_mode", enabled=False)
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["state"], "disabled")
        self.assertTrue(snapshot["safety_hold"])
        self.assert_client_normalizes_all()


if __name__ == "__main__":
    unittest.main()
