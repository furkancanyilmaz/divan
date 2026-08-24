import hashlib
import subprocess
import unittest
from pathlib import Path

from support import PROJECT_DIR


class SchemaV5ClientWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(PROJECT_DIR)
        cls.html_path = cls.project / "index.html"
        cls.android_html_path = (
            cls.project.parent / "divan-android/app/src/main/python/index.html"
        )
        cls.html = cls.html_path.read_text(encoding="utf-8")

    @classmethod
    def between(cls, start, end):
        begin = cls.html.index(start)
        finish = cls.html.index(end, begin)
        return cls.html[begin:finish]

    def run_node(self, program):
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_common_and_android_embedded_clients_are_byte_identical(self):
        common = self.html_path.read_bytes()
        embedded = self.android_html_path.read_bytes()
        self.assertEqual(common, embedded)
        self.assertEqual(
            hashlib.sha256(common).hexdigest(),
            hashlib.sha256(embedded).hexdigest())

    def test_import_control_binding_preserves_explicit_null_wire(self):
        compact = self.between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        program = compact + r"""
function compactSchemaStepData(value){return value||{};}
const base={protocol:'schema_path_chat_v5',sync_import_control:true,
  path_id:9,path_public_id:'a'.repeat(32),step_id:'variable_explore',
  expected_revision:7,checkpoint_public_id:'b'.repeat(32),
  expected_checkpoint_seq:2,prompt_request_id:null,
  prompt_assistant_message_id:null,
  prompt_assistant_message_public_id:null,source_user_message_id:21,
  source_user_message_public_id:'c'.repeat(32),
  source_assistant_message_id:22,
  source_assistant_message_public_id:'d'.repeat(32)};
const normalized=compactSchemaBinding(base);
if(!normalized||normalized.sync_import_control!==true)
  throw new Error('import control rejected');
for(const key of ['prompt_request_id','prompt_assistant_message_id',
    'prompt_assistant_message_public_id']){
  if(!Object.prototype.hasOwnProperty.call(normalized,key)||
      normalized[key]!==null)throw new Error('null identity not preserved '+key);
}
const missing={...base};delete missing.prompt_request_id;
if(compactSchemaBinding(missing)!==null)
  throw new Error('missing request null accepted');
if(compactSchemaBinding({...base,prompt_request_id:'prompt-request-0001'})!==null)
  throw new Error('fabricated request accepted');
if(compactSchemaBinding({...base,sync_import_control:false})!==null)
  throw new Error('false import marker accepted');
const completed={...base};delete completed.sync_import_control;
completed.prompt_request_id='prompt-request-0001';
completed.prompt_assistant_message_id=22;
completed.prompt_assistant_message_public_id='d'.repeat(32);
if(!compactSchemaBinding(completed))
  throw new Error('completed binding rejected');
if(compactSchemaBinding({...completed,sync_import_control:false})!==null)
  throw new Error('ambiguous completed/import shape accepted');
"""
        self.run_node(program)

    def test_process_death_round_trips_import_control_draft_exactly(self):
        compact = self.between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        recovered = self.between(
            "function compactRecoveredChatDraft(",
            "function invalidateRecoveredChatDraft(")
        program = r"""
function compactSchemaStepData(value){return value||{};}
function compactReply(value){return value&&value.id?value:null;}
""" + compact + recovered + r"""
const binding={protocol:'schema_path_chat_v5',sync_import_control:true,
  path_id:9,path_public_id:'a'.repeat(32),step_id:'variable_explore',
  expected_revision:7,checkpoint_public_id:'b'.repeat(32),
  expected_checkpoint_seq:2,prompt_request_id:null,
  prompt_assistant_message_id:null,
  prompt_assistant_message_public_id:null,source_user_message_id:21,
  source_user_message_public_id:'c'.repeat(32),
  source_assistant_message_id:22,
  source_assistant_message_public_id:'d'.repeat(32)};
const draft=compactRecoveredChatDraft({request_id:'chat-process-death-0001',
  conv_id:4,text:'Devam',reply:null,guidance:'',method_id:null,
  method_key:null,schema_binding:binding,draft_revision:3,
  composer_owned:true});
const revived=compactRecoveredChatDraft(JSON.parse(JSON.stringify(draft)));
if(!revived||revived.schema_binding.sync_import_control!==true)
  throw new Error('import binding lost on process death');
for(const key of ['prompt_request_id','prompt_assistant_message_id',
    'prompt_assistant_message_public_id']){
  if(!Object.prototype.hasOwnProperty.call(revived.schema_binding,key)||
      revived.schema_binding[key]!==null)
    throw new Error('process death changed null identity '+key);
}
if(!recoveredChatAttemptMatches(revived,{conv_id:4,text:'Devam',
    reply:null,guidance:'',method_id:null,method_key:null,
    schema_binding:binding}))
  throw new Error('exact recovered control request not reusable');
if(recoveredChatAttemptMatches(revived,{conv_id:4,text:'Devam',
    reply:null,guidance:'',method_id:null,method_key:null,
    schema_binding:{...binding,expected_checkpoint_seq:3}}))
  throw new Error('stale checkpoint reused recovered request id');
"""
        self.run_node(program)

    def test_imported_and_paused_states_open_controls_without_prompt_authority(self):
        compact = self.between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        helpers = self.between(
            "function schemaV5PromptDeliveryFor(",
            "async function refreshSchemaV5DurableMessages(")
        program = r"""
function compactSchemaStepData(value){return value||{};}
""" + compact + r"""
const pathPublic='a'.repeat(32),userPublic='b'.repeat(32),
  assistantPublic='c'.repeat(32),checkpointPublic='d'.repeat(32);
const user={dataset:{messagePublicId:userPublic,deliveryStatus:'completed'},
  closest(selector){return selector==='.row.user'?{}:null;},
  querySelector(){return null;}};
const assistant={dataset:{messagePublicId:assistantPublic,
    deliveryStatus:'completed'},
  closest(selector){return selector==='.row.therapist'?{}:null;},
  querySelector(selector){
    return selector==='.bubbleContent'?{textContent:'Senkron kaynak'}:null;
  }};
const laterUser={dataset:{messageId:'23'},
  closest(selector){return selector==='.row.user'?{}:null;},
  querySelector(){return null;}};
let bubbles=[user,assistant,laterUser];
const chat={querySelectorAll(selector){
  if(selector==='.row .bubble')return bubbles;
  if(selector==='.row.therapist .bubble')return [assistant];
  return [];
}};
const messageBubbleById=new Map([[21,user],[22,assistant]]);
function schemaProtocolV5(){return true;}
function schemaChatOnlyCard(){return true;}
function schemaPathId(){return 9;}
let convId=4,activeChatRequest=null;
const chatDeliveries=new Map();
const source={user_message_id:21,user_message_public_id:userPublic,
  assistant_message_id:22,assistant_message_public_id:assistantPublic};
const controlBinding={protocol:'schema_path_chat_v5',
  sync_import_control:true,path_id:9,path_public_id:pathPublic,
  step_id:'variable_explore',expected_revision:7,
  checkpoint_public_id:checkpointPublic,expected_checkpoint_seq:2,
  prompt_request_id:null,prompt_assistant_message_id:null,
  prompt_assistant_message_public_id:null,source_user_message_id:21,
  source_user_message_public_id:userPublic,source_assistant_message_id:22,
  source_assistant_message_public_id:assistantPublic};
const checkpoint={public_id:checkpointPublic,seq:2,prompt_key:'scenario',
  method_id:null,status:'paused',can_backtrack:false,
  backtrack_pending:false,pending_target_public_id:null};
let schemaPathDashboard={active_path:{id:9,public_id:pathPublic,revision:7,
    flow_version:5,status:'paused',stage:'explore',step:'variable_explore',
    resume_required:true,
    pause_reason:'sync_import_resume_required'},interaction_policy:{
    composer_surface:'ordinary_chat',inline_controls_only:false,
    composer_mode:'bound',composer_allowed:true,
    composer_binding_required:true,bound_step_id:'variable_explore',
    reason:'prompt_delivery_imported_waiting'}};
const imported={kind:'chat_state',presentation:'chat_only',status:'paused',
  path_id:9,path_public_id:pathPublic,stage:'explore',
  step:'variable_explore',revision:7,
  title:'',context_line:'',body:'',fields:[],actions:[],checkpoint,source,
  prompt_delivery:{request_id:null,status:'imported_waiting',
    prompt_assistant_message_id:null,
    prompt_assistant_message_public_id:null,error_code:null},
  chat_binding:controlBinding};
""" + helpers + r"""
if(!schemaV5ChatStateComposerBindingFor(imported))
  throw new Error('import control composer stayed closed');
chatDeliveries.set('chat-process-death-0001',{
  conv_id:4,status:'running',uncertain:false});
if(schemaV5ChatStateComposerBindingFor(imported)!==null)
  throw new Error('pending recovered resume allowed a duplicate command');
chatDeliveries.clear();
if(schemaV5PromptDeliveryFor({...imported,body:'UI sorusu'})!==null)
  throw new Error('visible imported question accepted');
if(schemaV5ChatStateComposerBindingFor({...imported,
    prompt_delivery:{...imported.prompt_delivery,request_id:'old-request-0001'}})!==null)
  throw new Error('import acquired fabricated request');
schemaPathDashboard.active_path.pause_reason='manual_pause';
if(schemaV5ChatStateComposerBindingFor(imported)!==null)
  throw new Error('non-import pause accepted imported authority');
schemaPathDashboard.active_path.pause_reason='sync_import_resume_required';
if(schemaV5ChatStateComposerBindingFor({...imported,source:{...source,
    assistant_message_public_id:'e'.repeat(32)}})!==null)
  throw new Error('tampered import source pin accepted');
messageBubbleById.clear();
if(!schemaV5ChatStateComposerBindingFor(imported))
  throw new Error('paginated/process-death control source stayed locked');

// A local pause keeps the completed prompt identity, but the typed pause
// message is now newer. It may authorize only backend lifecycle controls.
const completedBinding={...controlBinding};
delete completedBinding.sync_import_control;
completedBinding.prompt_request_id='prompt-request-0001';
completedBinding.prompt_assistant_message_id=22;
completedBinding.prompt_assistant_message_public_id=assistantPublic;
const paused={...imported,chat_binding:completedBinding,
  prompt_delivery:{request_id:'prompt-request-0001',status:'completed',
    prompt_assistant_message_id:22,
    prompt_assistant_message_public_id:assistantPublic,error_code:null}};
schemaPathDashboard.active_path.pause_reason='manual_pause';
if(!schemaV5ChatStateComposerBindingFor(paused))
  throw new Error('typed resume/control composer stayed closed');
"""
        self.run_node(program)

    def test_active_clinical_answer_requires_exact_latest_durable_prompt(self):
        compact = self.between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        helpers = self.between(
            "function schemaV5PromptDeliveryFor(",
            "async function refreshSchemaV5DurableMessages(")
        program = r"""
function compactSchemaStepData(value){return value||{};}
""" + compact + r"""
const pathPublic='a'.repeat(32),userPublic='b'.repeat(32),
  assistantPublic='c'.repeat(32),checkpointPublic='d'.repeat(32);
const user={dataset:{messageId:'21',messagePublicId:userPublic,
    deliveryStatus:'saved'},
  closest(selector){return selector==='.row.user'?{}:null;},
  querySelector(){return null;}};
const assistant={dataset:{messageId:'22',messagePublicId:assistantPublic,
    deliveryStatus:'completed'},
  closest(selector){return selector==='.row.therapist'?{}:null;},
  querySelector(selector){
    return selector==='.bubbleContent'?{textContent:'Gerçek Kerem sorusu'}:null;
  }};
let bubbles=[user,assistant],assistants=[assistant];
const chat={querySelectorAll(selector){
  if(selector==='.row .bubble')return bubbles;
  if(selector==='.row.therapist .bubble')return assistants;
  return [];
}};
const messageBubbleById=new Map([[21,user],[22,assistant]]);
function schemaProtocolV5(){return true;}
function schemaChatOnlyCard(){return true;}
function schemaPathId(){return 9;}
let schemaPathDashboard={active_path:{id:9,public_id:pathPublic,revision:7,
    flow_version:5,status:'active',stage:'explore',
    step:'variable_explore'},interaction_policy:{
    composer_surface:'ordinary_chat',inline_controls_only:false,
    composer_mode:'bound',composer_allowed:true,
    composer_binding_required:true,bound_step_id:'variable_explore'}};
const binding={protocol:'schema_path_chat_v5',path_id:9,
  path_public_id:pathPublic,step_id:'variable_explore',expected_revision:7,
  checkpoint_public_id:checkpointPublic,expected_checkpoint_seq:2,
  prompt_request_id:'prompt-request-0001',prompt_assistant_message_id:22,
  prompt_assistant_message_public_id:assistantPublic,
  source_user_message_id:21,source_user_message_public_id:userPublic,
  source_assistant_message_id:22,
  source_assistant_message_public_id:assistantPublic};
const card={kind:'chat_state',presentation:'chat_only',status:'active',
  path_id:9,path_public_id:pathPublic,stage:'explore',
  step:'variable_explore',revision:7,
  title:'',context_line:'',body:'',fields:[],actions:[],
  checkpoint:{public_id:checkpointPublic,seq:2,prompt_key:'scenario',
    method_id:null,status:'active',can_backtrack:false,
    backtrack_pending:false,pending_target_public_id:null},
  source:{user_message_id:21,user_message_public_id:userPublic,
    assistant_message_id:22,assistant_message_public_id:assistantPublic},
  prompt_delivery:{request_id:'prompt-request-0001',status:'completed',
    prompt_assistant_message_id:22,
    prompt_assistant_message_public_id:assistantPublic,error_code:null},
  chat_binding:binding};
""" + helpers + r"""
if(!schemaV5ChatStateComposerBindingFor(card))
  throw new Error('exact latest durable prompt rejected');
const later={dataset:{messageId:'23'},
  closest(selector){return selector==='.row.user'?{}:null;},
  querySelector(){return null;}};
bubbles=[user,assistant,later];
if(schemaV5ChatStateComposerBindingFor(card)!==null)
  throw new Error('non-latest prompt retained clinical authority');
bubbles=[user,assistant];
assistant.querySelector=selector=>selector==='.bubbleContent'
  ?{textContent:''}:null;
if(schemaV5ChatStateComposerBindingFor(card)!==null)
  throw new Error('empty assistant prompt gained authority');
"""
        self.run_node(program)

    def test_import_boundary_does_not_regress_to_late_local_delivery(self):
        projection = self.between(
            "function schemaV4ProjectionOrder(",
            "function schemaV4FieldDomId(")
        program = r"""
const schemaPathDashboard={};
""" + projection + r"""
const path='a'.repeat(32);
const imported={active_path:{public_id:path,revision:7},revision:7,
  next_card:{path_public_id:path,revision:7,checkpoint:{seq:2},
    prompt_delivery:{request_id:null,status:'imported_waiting'}}};
const late={active_path:{public_id:path,revision:7},revision:7,
  next_card:{path_public_id:path,revision:7,checkpoint:{seq:2},
    prompt_delivery:{request_id:'prompt-request-0001',status:'running'}}};
if(!schemaV4ProjectionIsStale(late,imported))
  throw new Error('late local request replaced import boundary');
const resumed={active_path:{public_id:path,revision:8},revision:8,
  next_card:{path_public_id:path,revision:8,checkpoint:{seq:3},
    prompt_delivery:{request_id:'prompt-request-0002',status:'completed'}}};
if(schemaV4ProjectionIsStale(resumed,imported))
  throw new Error('newer real resume rejected');
"""
        self.run_node(program)

    def test_v5_renderer_has_only_candidate_buttons_and_no_synthetic_prompt(self):
        candidate = self.between(
            "function renderSchemaChatOnlyCandidate(",
            "function focusSchemaChatOnlyInteraction(")
        renderer = self.between(
            "function renderSchemaChatOnlyCard(",
            "function renderSchemaV4ActiveCard(")
        sender = self.between(
            "async function send(",
            "/* ---------------- seans bitir")
        self.assertIn("'Evet'", candidate)
        self.assertIn("'Hayır'", candidate)
        self.assertIn("Bunu çalışmak ister misin?", candidate)
        self.assertNotIn("addBubble(", candidate)
        self.assertIn("schemaProtocolV5()&&kind==='chat_state'", renderer)
        self.assertNotIn("card.body", renderer)
        self.assertNotIn("card.actions", renderer)
        self.assertNotIn("guidedButton(", renderer)
        self.assertIn("const bubble = schemaV5SilentAssistant?null:addBubble(",
                      sender)
        self.assertIn("refreshSchemaV5DurableMessages(", sender)

    def test_background_schema_refresh_is_quiet_and_not_composer_blocking(self):
        sync = self.between(
            "function syncComposerSendState(",
            "function markComposerTyping(")
        blockers = self.between(
            "function beginSchemaPathComposerBlock(",
            "let schemaPendingMethod")
        loader = self.between(
            "async function loadSchemaPathDashboard(",
            "async function postSchemaPath(")
        api = self.between(
            "async function api(",
            "const API_GET_RETRY_DELAYS")
        toast = self.between(
            "function showToast(",
            "function purgeSensitiveNativeNotifications(")

        program = r"""
let activeElement=null,toastTimer=null,lastClientError=null;
const document={get activeElement(){return activeElement;}};
let viewportCaptureCount=0,viewportRestoreCount=0;
const chat={querySelector(){return null;}};
function captureChatViewportAnchor(){viewportCaptureCount++;return {};}
function restoreChatViewportAnchor(snapshot){
  if(snapshot)viewportRestoreCount++;
}
const noopClassList={toggle(){},add(){},remove(){}};
const toastNode={textContent:'',classList:noopClassList,setAttribute(){}};
const overlay={setAttribute(){}};
const inputBar={dataset:{},setAttribute(){}};
const sendButton={classList:noopClassList,disabled:false,title:'',
  setAttribute(){}};
const msgBox={value:'kullanıcı taslağı',_disabled:false};
Object.defineProperty(msgBox,'disabled',{get(){return this._disabled;},
  set(value){this._disabled=!!value;if(this._disabled&&activeElement===this)
    activeElement=null;}});
function $(id){return id==='toast'?toastNode:id==='schemaPathOverlay'?overlay:
  id==='send'?sendButton:id==='inputBar'?inputBar:null;}
function compactSchemaBinding(value){return value;}
function schemaChatOnlyPresentation(){return true;}
function optionalApi(){return Promise.resolve({});}
function responseMessage(status,data){return data&&data.error||'HTTP '+status;}
let diagnosticCount=0,lockedCount=0;
function apiHatasiniKaydet(){diagnosticCount++;}
function enterAppLockedState(){lockedCount++;}
let transport='success',disabledAtForegroundRequest=false;
const dashboard={interaction_policy:{},active_path:{id:4},
  candidates:[],allowed_actions:[]};
async function fetchApiResponse(){
  if(transport==='failure')throw new TypeError('loopback unavailable');
  disabledAtForegroundRequest=disabledAtForegroundRequest||msgBox.disabled;
  return {ok:true,status:200,text:async()=>JSON.stringify(dashboard)};
}
let openingConversationId=null,streaming=false,chairBusy=false,
  imageryBusy=false,activeChatRequest=null;
let schemaComposerMode='bound';
let schemaComposerBinding={protocol:'schema_path_chat_v5'};
let conversationDraftRevision=17;
let schemaCardDraft={card_id:'active-card',revision:9,
  values:{note:'korunan kart taslağı'}};
let schemaPathBusy=false,schemaPathComposerBlockers=new Set(),
  schemaPathComposerBlockerSequence=0;
let convId=92,schemaPathRequestSequence=0,schemaPathDashboardConvId=92,
  schemaPathDashboard={...dashboard};
function structuredWorkspaceConversation(){return true;}
function setSchemaPathStatus(){}
function schemaV4ProjectionIsStale(){return false;}
function normalizeSchemaPathDashboard(value){return value;}
function applySchemaInteractionPrivacy(){}
function syncSchemaAnalyzedMessageIds(){}
function renderSchemaPathWorkspace(){syncComposerSendState();}
function syncSchemaTurnMessageActions(){}
function renderSchemaInlineCandidates(){syncComposerSendState();}
function schemaNoticeText(){return '';}
function renderSchemaModeAndHistory(){}
function renderSchemaStepCard(){syncComposerSendState();}
Object.defineProperty(globalThis,'navigator',{
  value:{onLine:true},configurable:true});
""" + toast + api + blockers + sync + loader + r"""
(async()=>{
  const draftSnapshot=JSON.stringify(schemaCardDraft);
  activeElement=msgBox;
  if(!await loadSchemaPathDashboard({background:true}))
    throw new Error('background success rejected');
  if(msgBox.disabled||activeElement!==msgBox||
      msgBox.value!=='kullanıcı taslağı'||conversationDraftRevision!==17||
      JSON.stringify(schemaCardDraft)!==draftSnapshot)
    throw new Error('successful background poll disturbed composer');

  transport='failure';toastNode.textContent='';activeElement=msgBox;
  if(await loadSchemaPathDashboard({background:true}))
    throw new Error('background failure accepted');
  if(msgBox.disabled||activeElement!==msgBox||
      msgBox.value!=='kullanıcı taslağı'||conversationDraftRevision!==17||
      JSON.stringify(schemaCardDraft)!==draftSnapshot)
    throw new Error('failed background poll disturbed composer');
  if(toastNode.textContent||diagnosticCount!==1||lockedCount!==0)
    throw new Error('background failure was noisy or unlogged');

  transport='success';activeElement=msgBox;disabledAtForegroundRequest=false;
  if(!await loadSchemaPathDashboard({background:false}))
    throw new Error('foreground success rejected');
  if(!disabledAtForegroundRequest||msgBox.disabled||activeElement!==null)
    throw new Error('foreground load did not retain fail-closed blocking');
  if(msgBox.value!=='kullanıcı taslağı'||conversationDraftRevision!==17||
      JSON.stringify(schemaCardDraft)!==draftSnapshot)
    throw new Error('foreground load changed draft');
  if(viewportCaptureCount!==2||viewportRestoreCount!==2)
    throw new Error('background viewport transaction was not paired');

  activeElement=msgBox;
  const mutation=beginSchemaPathComposerBlock('mutation');
  syncComposerSendState();
  if(!msgBox.disabled||activeElement!==null)
    throw new Error('mutation did not block composer');
  endSchemaPathComposerBlock(mutation);syncComposerSendState();
  if(msgBox.disabled)throw new Error('mutation blocker did not release');
})().catch(error=>{console.error(error);process.exit(1);});
"""
        self.run_node(program)

    def test_schema_poll_and_mutation_wiring_uses_correct_busy_class(self):
        loader = self.between(
            "async function loadSchemaPathDashboard(",
            "async function postSchemaPath(")
        history_poll = self.between(
            "function scheduleSchemaHistoryPoll(",
            "function renderSchemaModeAndHistory(")
        prompt_poll = self.between(
            "function syncSchemaV5PromptState(",
            "function schemaV4ChatOnlyComposerBindingFor(")
        durable_refresh = self.between(
            "async function refreshSchemaV5DurableMessages(",
            "function syncSchemaV5PromptState(")
        post_path = self.between(
            "async function postSchemaPath(",
            "function resetSchemaTurnUi(")
        post_card = self.between(
            "async function postSchemaV4CardAction(",
            "function setSchemaV4CardStatus(")

        self.assertIn("const composerBlocker=background?null:", loader)
        self.assertIn("{quiet:background}", loader)
        self.assertIn("loadSchemaPathDashboard({background:true})", history_poll)
        self.assertIn("loadSchemaPathDashboard({background:true})", prompt_poll)
        self.assertIn("undefined,{quiet:true}", durable_refresh)
        for mutation in (post_path, post_card):
            self.assertIn("beginSchemaPathComposerBlock(", mutation)
            self.assertIn("endSchemaPathComposerBlock(composerBlocker)", mutation)
            self.assertIn("syncComposerSendState()", mutation)


if __name__ == "__main__":
    unittest.main()
