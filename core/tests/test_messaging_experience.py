import re
import unittest
from pathlib import Path

from support import PROJECT_DIR


class MessagingExperienceSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = Path(PROJECT_DIR, "index.html").read_text(
            encoding="utf-8")
        cls.compact = re.sub(r"\s+", "", cls.html)

    def function_body(self, name, next_name):
        start = self.html.index("function " + name)
        end = self.html.index("function " + next_name, start)
        return self.html[start:end]

    def test_archived_conversations_open_read_only_without_restore(self):
        self.assertIn(
            "return !!data&&(!!data.ended||!!data.archived_at);",
            self.html,
        )
        load_start = self.html.index("async function loadConvs()")
        load_end = self.html.index("function setMode(", load_start)
        load = self.html[load_start:load_end]
        self.assertIn("openConv(r.id)", load)
        self.assertNotIn("if(!archived)openConv", load)
        self.assertIn(
            "$('inputBar').style.display = readOnly ? 'none' : '';",
            self.html,
        )
        self.assertIn(
            "chatRequestCanRetry(request)&&!conversationReadOnly()",
            self.html,
        )

    def test_each_conversation_has_a_local_draft_with_quoted_reply(self):
        self.assertIn(
            "const DRAFT_STORAGE_PREFIX = "
            "'divanConversationDraft:v1:';",
            self.html,
        )
        self.assertIn("function saveConversationDraft(", self.html)
        self.assertIn("function restoreConversationDraft(", self.html)
        self.assertIn("reply:compactReply(pendingReply)", self.html)
        self.assertIn("msgBox.addEventListener('input',()=>{", self.html)
        self.assertIn("scheduleConversationDraft();", self.html)
        self.assertIn(
            "addEventListener('pagehide',()=>{"
            "saveConversationDraft();"
            "persistChatDeliveries();",
            self.compact,
        )
        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = self.html[send_start:send_end]
        self.assertIn(
            "settleConversationDraftForRequest("
            "\n      requestConvId,requestState.requestId)",
            send,
        )

    def test_stable_message_targets_and_quoted_reply_are_rendered(self):
        for control in (
            'id="composerReplyPreview"',
            'id="storySelectionReply"',
            'className=\'messageReplyQuote\'',
        ):
            self.assertIn(control, self.html)
        self.assertIn("const messageBubbleById = new Map();", self.html)
        self.assertIn("bubble.dataset.messageId=String(id)", self.html)
        self.assertIn("messageBubbleById.set(id,bubble)", self.html)
        self.assertIn(
            "reply_to:replyForSend&&replyForSend.id||null",
            self.html,
        )
        self.assertIn("reply_preview_content:m.reply_preview_content",
                      self.html)
        self.assertIn("jumpToMessage(normalized.id)", self.html)

    def test_conversation_open_locks_composer_and_rolls_back_safely(self):
        opening = self.function_body("openConv(", "newConv(")
        compact = re.sub(r"\s+", "", opening)
        self.assertIn("setConversationOpening(id);", opening)
        self.assertIn(
            "constdata=awaitapi('/api/conversation?id='+"
            "encodeURIComponent(id)+'&limit='+CONVERSATION_PAGE_LIMIT);",
            compact,
        )
        self.assertLess(
            compact.index("constdata=awaitapi("),
            compact.index("if(streaming)detachActiveChatStream();"),
        )
        self.assertIn(
            "Görüşme açılamadı; mevcut konuşma ve taslağınız korundu.",
            opening,
        )
        self.assertIn("setConversationOpening(null);", opening)
        self.assertIn("openingConversationId!==null", self.html)
        self.assertIn(
            "$('inputBar').setAttribute('aria-busy',"
            "opening||schemaBusy?'true':'false');",
            re.sub(r"\s+", "", self.html),
        )
        send = self.function_body("send(", "selectedRadioValue(")
        self.assertIn("if(openingConversationId!==null)", send)

    def test_old_assistant_messages_get_source_bound_tools_and_repairs(self):
        opening = self.function_body("openConv(", "newConv(")
        self.assertIn("renderConversationMessage(message,index)", opening)
        renderer = self.function_body(
            "renderConversationMessage(", "setBubbleContent(")
        self.assertIn("if(m.role==='assistant'){", renderer)
        self.assertIn("addResponseTools(bubble,m);", renderer)
        tools = self.function_body("messageToolReference(", "openConv(")
        self.assertIn("bubble.dataset.messageId", tools)
        self.assertIn("cleanStoryText", tools)
        self.assertIn("send(prompt,guidance,null,reference)", tools)
        self.assertIn("openRepairFlow(null,reference)", tools)
        self.assertIn("source_message_id:", self.html)
        self.assertIn("source_quote:", self.html)
        self.assertIn('id="repairSourcePreview"', self.html)
        self.assertIn('id="repairConfirmPartial"', self.html)
        self.assertIn("fit==='partial'?'not_yet'", self.compact)

    def test_carryover_repair_state_never_projects_a_chat_header_banner(self):
        self.assertNotIn(
            "Önceki görüşmede yarım kalan bir düzeltme var",
            self.html,
        )
        self.assertIn(
            '<section id="carryoverRepair" hidden inert aria-hidden="true">',
            self.html,
        )
        renderer = self.function_body(
            "renderWorkingAgreement(", "showWorkTools(")
        self.assertIn("$('carryoverRepair').hidden=true;", renderer)
        self.assertNotIn(
            "hidden=!sessionWork.carryover_repair",
            renderer,
        )

        # The source state and recovery controls are intentionally retained;
        # this change only suppresses their former top-of-chat projection.
        apply_work = self.function_body(
            "applySessionWork(", "loadSessionWork(")
        self.assertIn(
            "sessionWork.carryover_repair=carryoverRepair||null",
            apply_work,
        )
        self.assertIn(
            "openRepairFlow(sessionWork.carryover_repair)",
            self.html,
        )
        self.assertIn("$('carryoverRepairSkip').onclick", self.html)

    def test_long_conversations_open_recent_page_and_offer_manual_history(self):
        self.assertIn("const CONVERSATION_PAGE_LIMIT = 80;", self.html)
        self.assertIn('id="messageHistoryControl"', self.html)
        self.assertIn('id="loadOlderMessagesBtn"', self.html)
        self.assertIn("Daha eski mesajları yükle", self.html)
        self.assertIn('aria-describedby="messageHistoryStatus"', self.html)
        opening = self.function_body("openConv(", "newConv(")
        compact = re.sub(r"\s+", "", opening)
        self.assertIn(
            "'/api/conversation?id='+encodeURIComponent(id)+"
            "'&limit='+CONVERSATION_PAGE_LIMIT",
            compact,
        )
        self.assertIn("initializeMessageHistory(data);", opening)
        self.assertIn("}elsescrollConversationToLatest();", compact)

    def test_older_page_loader_is_retryable_stale_safe_and_non_destructive(self):
        loader = self.function_body("loadOlderMessages(", "openConv(")
        compact = re.sub(r"\s+", "", loader)
        self.assertIn("if(state.loading||!state.hasMore", loader)
        self.assertIn("'&before_id='+encodeURIComponent(beforeId)", loader)
        self.assertIn("messageHistoryState.requestToken!==requestToken", loader)
        self.assertIn("Number(convId)!==requestedConv", loader)
        self.assertIn("messageBubbleById.has(id)", loader)
        self.assertIn("state.loading=false;renderMessageHistoryControl()",
                      loader)
        self.assertIn("Mevcut sohbet korundu; yeniden deneyebilirsiniz.",
                      loader)
        for destructive in (
                "openConv(", "clearChatMessages(", "restoreConversationDraft(",
                "resetStoryFlow(", "scrollConversationToLatest(",
                "msgBox.value", "pendingReply=", "conversationDraftRevision",
                "setOpenMessageActionsBubble(null)"):
            self.assertNotIn(destructive, loader)
        self.assertIn("$('loadOlderMessagesBtn').onclick=loadOlderMessages;",
                      self.html)

    def test_prepend_preserves_existing_nodes_scroll_and_message_identity(self):
        prepend = self.function_body(
            "prependConversationMessages(", "loadOlderMessages(")
        self.assertIn("const anchor=existingRows.find", prepend)
        self.assertIn("anchor.getBoundingClientRect().top", prepend)
        self.assertIn("const olderRows=document.createDocumentFragment()",
                      prepend)
        self.assertIn("olderRows.appendChild(row)", prepend)
        self.assertIn("chat.insertBefore(olderRows,insertionPoint)", prepend)
        self.assertIn("chat.scrollTop+=current-anchorOffset", prepend)
        self.assertIn("const previousBusy=chat.getAttribute('aria-busy')",
                      prepend)
        self.assertIn("chat.setAttribute('aria-busy',previousBusy)", prepend)
        self.assertIn("rebuildMessageDateSeparators();", prepend)
        self.assertIn("renderConversationMessage(message,index-rows.length)",
                      prepend)
        self.assertNotIn("storySelected.clear", prepend)
        self.assertNotIn("messageBubbleById.clear", prepend)
        self.assertNotIn("preserved.appendChild", prepend)
        self.assertNotIn("scheduleConversationSearch()", prepend)
        self.assertIn("runConversationSearch({preserveScroll:true})", prepend)
        self.assertIn("cancelAnchorSettling", prepend)
        renderer = self.function_body(
            "renderConversationMessage(", "setBubbleContent(")
        self.assertIn("id:m.id,message_id:m.message_id", renderer)
        self.assertIn("reply_to:m.reply_to??m.reply_to_message_id", renderer)
        self.assertIn("addResponseTools(bubble,m)", renderer)

    def test_final_history_page_keeps_completion_status_and_focus_target(self):
        control = self.function_body(
            "renderMessageHistoryControl(", "resetMessageHistoryState(")
        self.assertIn("const completed=sameConversation&&"
                      "messageHistoryState.complete", control)
        self.assertIn("control.hidden=!(active||completed)", control)
        self.assertIn("Konuşmanın başına ulaşıldı", control)
        self.assertIn("button.setAttribute('aria-disabled'", control)
        loader = self.function_body("loadOlderMessages(", "loadMessageTarget(")
        self.assertIn("state.complete=!state.hasMore", loader)

    def test_global_search_target_can_page_until_message_id_is_loaded(self):
        target = self.function_body("loadMessageTarget(", "openConv(")
        self.assertIn("while(!messageBubbleById.has(target)&&"
                      "messageHistoryState.hasMore", target)
        self.assertIn("await loadOlderMessages()", target)
        opening = self.function_body("openConv(", "newConv(")
        self.assertIn("await loadMessageTarget(options.targetMessageId)",
                      opening)

    def test_conversation_list_failure_preserves_items_and_offers_retry(self):
        mobile = self.function_body(
            "loadMobileHomeConversations(", "loadConvs(")
        failure = mobile[mobile.index("}catch(_){"):]
        self.assertNotIn("list.textContent=''", failure)
        self.assertIn(
            "showConversationListError(list,loadMobileHomeConversations)",
            mobile,
        )
        helper = self.function_body(
            "showConversationListError(", "loadMobileHomeConversations(")
        self.assertIn("ekrandaki geçmiş korunuyor", helper)
        self.assertIn("button.textContent='Yeniden dene'", helper)
        desktop = self.function_body("loadConvs(", "setMode(")
        self.assertIn("showConversationListError(list,loadConvs)", desktop)

    def test_generic_technique_advance_confirms_user_checkpoint(self):
        update = self.function_body(
            "updateTechniqueRun(", "openMethodConsent(")
        self.assertIn("payload.checkpoint_confirmed=true", update)
        self.assertIn("if(action==='advance')showToast(", update)

    def test_response_actions_open_only_for_the_activated_message(self):
        self.assertIn(
            ".responseTools{display:none;flex-wrap:wrap;",
            self.compact,
        )
        self.assertIn(
            ".bubble.messageActionsOpen>.responseTools{display:flex}",
            self.compact,
        )
        disclosure = self.function_body(
            "setOpenMessageActionsBubble(", "messageTextSelectionActive(")
        self.assertIn(
            "openMessageActionsBubble.classList.remove("
            "'messageActionsOpen')",
            disclosure,
        )
        self.assertIn(
            "previousTools.setAttribute('aria-hidden','true')",
            disclosure,
        )
        self.assertIn("next.classList.add('messageActionsOpen')",
                      disclosure)
        # Pro mod rozeti araç çubuğu olmadan da açılabildiği için
        # `tools` artık boş olabilir; niyet aynı: açılan balonun araç
        # çubuğu görünür işaretlenir.
        self.assertIn("const tools=messageActionTools(next)", disclosure)
        self.assertIn(
            "if(tools)tools.setAttribute('aria-hidden','false')",
            disclosure,
        )
        self.assertIn(
            "if(openMessageActionsBubble&&"
            "!(event.target.closest&&event.target.closest('.bubble')))"
            "setOpenMessageActionsBubble(null);",
            self.compact,
        )
        clearing = self.function_body("clearChatMessages(", "jumpToMessage(")
        self.assertIn("setOpenMessageActionsBubble(null);", clearing)
        self.assertIn("chat.replaceChildren();", clearing)
        self.assertLess(clearing.index("setOpenMessageActionsBubble(null)"),
                        clearing.index("chat.replaceChildren()"))

    def test_response_action_reveal_preserves_message_interactions(self):
        click_start = self.html.index("chat.addEventListener('click',")
        click_end = self.html.index(
            "document.addEventListener('pointerdown',", click_start)
        click_handler = self.html[click_start:click_end]
        self.assertIn("storySelecting", click_handler)
        self.assertIn("suppressStoryMessageClickUntil", click_handler)
        self.assertIn("MESSAGE_ACTION_INTERACTIVE_SELECTOR", click_handler)
        self.assertIn("messageTextSelectionActive(bubble)", click_handler)
        self.assertNotIn("preventDefault()", click_handler)
        self.assertIn(
            "'a,button,input,textarea,select,label,summary,audio,video,'",
            self.html,
        )
        self.assertIn("bubble.tabIndex=0;", self.html)
        self.assertIn(
            "bubble.setAttribute('aria-expanded','false')",
            self.html,
        )
        self.assertIn(
            "tools.setAttribute('role','toolbar')",
            self.html,
        )
        self.assertIn(
            "if(storySelecting||!['Enter',' '].includes(event.key))return;",
            self.html,
        )
        self.assertIn(
            "if(event.key==='Escape'&&openMessageActionsBubble)",
            self.html,
        )
        self.assertIn(
            "setOpenMessageActionsBubble(null);"
            "dismissMobileComposer();",
            self.compact,
        )

    def test_search_can_target_messages_in_open_or_archived_history(self):
        self.assertIn('id="conversationSearchBar" role="search"', self.html)
        self.assertIn("function runConversationSearch(", self.html)
        self.assertIn("messageBubbleById.get(Number(targetMessageId))",
                      self.html)
        self.assertIn(
            "(archivedSearch?'&archived=1':'')",
            self.html,
        )
        self.assertIn("targetMessageId:r.message_id||null", self.html)
        self.assertIn(
            "openConversationSearch(options.searchTerm,"
            "options.targetMessageId)",
            self.compact,
        )

    def test_dates_smart_scroll_and_accessible_log_are_present(self):
        self.assertIn('id="chat" data-testid="chat" role="log"',
                      self.html)
        self.assertIn("function appendMessageDateSeparator(", self.html)
        self.assertIn("separator.setAttribute('role','separator')",
                      self.html)
        self.assertIn("row.setAttribute('role','article')", self.html)
        self.assertIn('id="scrollToLatestBtn"', self.html)
        self.assertIn("function chatIsNearBottom(", self.html)
        self.assertIn("function markNewResponseBelow(", self.html)
        self.assertIn("'Yeni yanıta in':'En yeniye in'", self.html)
        self.assertIn('href="#ui-icon-arrow-down"', self.html)

    def test_copy_selection_is_not_limited_by_story_export_limits(self):
        toggle = self.function_body(
            "toggleStoryBubble(", "updateStorySelectionBar(")
        self.assertNotIn("STORY_MAX_MESSAGES", toggle)
        self.assertNotIn("STORY_MAX_CHARS", toggle)
        self.assertIn(
            "$('storySelectionCopy').disabled=count===0;",
            self.html,
        )
        self.assertIn(
            "$('storySelectionContinue').disabled=count===0||!storyFits;",
            self.html,
        )
        self.assertIn("Kopyalama sınırdan etkilenmez.", self.html)

    def test_durable_chat_detaches_navigation_but_cancels_explicit_stop(self):
        self.assertIn("request_id:requestState.requestId", self.html)
        self.assertIn("function detachActiveChatStream()", self.html)
        self.assertIn("function cancelActiveChatRequest(", self.html)
        detach = self.function_body(
            "detachActiveChatStream()", "cancelActiveChatRequest(")
        self.assertIn("controller.abort()", detach)
        self.assertNotIn("/api/chat/cancel", detach)
        cancel = self.function_body(
            "cancelActiveChatRequest(", "renderChatRequestFailure(")
        self.assertIn("/api/chat/cancel", cancel)
        self.assertIn("const verified=", cancel)
        self.assertIn("response.cancelled===true", cancel)
        self.assertIn(
            "Durdurma doğrulanamadı; yanıt arka planda sürebilir.",
            cancel,
        )
        self.assertIn("pollChatRequestStatus(state,350)", cancel)
        self.assertIn("if(!verified)", cancel)
        self.assertIn("/api/chat-status?request_id=", self.html)
        self.assertIn("/api/chat/retry", self.html)
        self.assertIn("data.chat_request||convData.chat_request", self.html)
        self.assertIn("fixedStatus&&fixedStatus!=='completed'", self.html)
        self.assertIn(
            "requestTerminalStatus&&requestTerminalStatus!=='completed'",
            self.html,
        )

    def test_home_list_surfaces_and_refreshes_background_generation(self):
        self.assertIn("row.chat_request_id", self.html)
        self.assertIn("row.chat_status", self.html)
        self.assertIn("row.chat_partial", self.html)
        self.assertIn("'yazıyor…'", self.html)
        self.assertIn("scheduleConversationListStatusRefresh(", self.html)
        self.assertIn("loadMobileHomeConversations();", self.html)

    def test_ambiguous_send_disconnect_checks_same_request_before_recovery(self):
        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = self.html[send_start:send_end]
        self.assertIn("let definiteRejection=false;", send)
        self.assertIn("definiteRejection=r.status>=400", send)
        self.assertIn("}else if(!definiteRejection){", send)
        self.assertIn("requestState.uncertain=true;", send)
        self.assertIn("request_id:requestState.requestId", send)
        self.assertIn("pollChatRequestStatus(requestState,250)", send)
        self.assertIn("saveConversationDraft(requestConvId);", send)
        self.assertIn("outgoingDraftRevision", send)
        self.assertIn("function fetchChatRequestStatus(", self.html)
        self.assertIn("kind:'not_found'", self.html)
        self.assertIn("state.notFoundCount<12", self.html)
        self.assertIn("recoverUnacceptedChatRequest(state)", self.html)
        self.assertIn(
            "if(state.uncertain){"
            "state.uncertain=false;state.accepted=true;",
            self.compact,
        )

    def test_delayed_post_reuses_request_id_only_for_unchanged_draft(self):
        self.assertIn(
            "recovered_request:"
            "compactRecoveredChatDraft(recoveredChatDraft)",
            self.compact,
        )
        matching = self.function_body(
            "recoveredChatAttemptMatches(", "invalidateRecoveredChatDraft(")
        for comparison in (
            "left.conv_id===right.conv_id",
            "left.text===right.text",
            "left.guidance===right.guidance",
            "left.method_id===right.method_id",
            "left.method_key===right.method_key",
        ):
            self.assertIn(comparison, matching)
        self.assertIn(
            "(left.reply&&left.reply.id||null)==="
            "(right.reply&&right.reply.id||null)",
            re.sub(r"\s+", "", matching),
        )
        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = self.html[send_start:send_end]
        self.assertIn(
            "?reusableRequest.request_id:createChatRequestId();",
            re.sub(r"\s+", "", send),
        )
        recover = self.function_body(
            "recoverUnacceptedChatRequest(", "retryChatRequest(")
        self.assertIn("saveUncertainChatAttempt(state)", recover)
        saved_attempt = self.function_body(
            "saveUncertainChatAttempt(", "restoreConversationDraft(")
        self.assertIn("request_id:state.requestId", saved_attempt)
        self.assertIn("guidance:state.outgoingGuidance", saved_attempt)
        self.assertIn("draft_revision:state.outgoingDraftRevision",
                      saved_attempt)
        self.assertIn(
            "recovered.request_id===known.request_id",
            self.compact,
        )
        self.assertIn(
            "msgBox.addEventListener('input',()=>{"
            "conversationDraftRevision++;"
            "invalidateRecoveredChatDraft();",
            self.compact,
        )
        set_reply = self.function_body(
            "setPendingReply(", "conversationDraftPayload(")
        self.assertIn("if(save){", set_reply)
        self.assertIn("conversationDraftRevision++;", set_reply)
        self.assertIn("invalidateRecoveredChatDraft();", set_reply)

    def test_silent_sse_eof_polls_instead_of_completing_partial_bubble(self):
        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = self.html[send_start:send_end]
        self.assertIn("let sawTerminalEvent=false;", send)
        self.assertIn("sawTerminalEvent=true;", send)
        eof_guard = send.index("if(!sawTerminalEvent){")
        polling_branch = send.index("if(continueByPolling){", eof_guard)
        success_branch = send.index(
            "stopChatStatusPolling();", polling_branch + 1)
        guard = send[eof_guard:polling_branch]
        self.assertIn("continueByPolling=true;", guard)
        self.assertIn("requestState.controller=null;", guard)
        self.assertIn("Yanıtın tamamlanma durumu doğrulanıyor", guard)
        self.assertLess(eof_guard, polling_branch)
        self.assertLess(polling_branch, success_branch)

    def test_fallback_replace_event_does_not_duplicate_partial_stream(self):
        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = self.html[send_start:send_end]
        self.assertIn(
            "ev.type==='replace'||"
            "(ev.type==='delta'&&ev.replace===true)",
            re.sub(r"\s+", "", send),
        )
        self.assertIn("acc=String(ev.text??ev.content??'');", send)
        replace_start = send.index("if(ev.type==='replace'")
        delta_start = send.index("} else if(ev.type==='delta'){",
                                 replace_start)
        replace = send[replace_start:delta_start]
        self.assertIn("requestState.acc=acc", replace)
        self.assertIn("setBubbleContent(bubble", replace)
        self.assertNotIn("acc +=", replace)

    def test_server_side_5xx_after_post_is_treated_as_ambiguous_delivery(self):
        send_start = self.html.index("async function send(")
        send_end = self.html.index(
            "/* ---------------- seans bitir", send_start)
        send = self.html[send_start:send_end]
        self.assertIn(
            "definiteRejection=r.status>=400&&r.status<500&&"
            "![408,425,429].includes(r.status);",
            re.sub(r"\s+", "", send),
        )
        self.assertIn("}else if(!definiteRejection){", send)
        self.assertIn("requestState.uncertain=true;", send)

    def test_provider_error_codes_are_not_rendered_raw(self):
        self.assertIn("function chatRequestFailureMessage(", self.html)
        for code in (
            "auth_failed",
            "local_unavailable",
            "quota_exhausted",
            "rate_limited",
            "provider_stream_interrupted",
        ):
            self.assertIn(code + ":", self.html)
        failure = self.function_body(
            "renderChatRequestFailure(", "retryChatRequest(")
        self.assertIn("chatRequestFailureMessage(request)", failure)
        self.assertNotIn("message.textContent=request.error", failure)

    def test_chat_delivery_registry_survives_navigation_and_reload(self):
        self.assertIn(
            "const CHAT_DELIVERY_STORAGE_KEY = "
            "'divanChatDeliveries:v1';",
            self.html,
        )
        for function in (
            "persistChatDeliveries",
            "restoreChatDeliveries",
            "rememberChatDelivery",
            "reconcileChatDeliveries",
            "scheduleChatDeliverySweep",
        ):
            self.assertIn("function " + function + "(", self.html)
        unlocked = self.function_body(
            "loadUnlockedShell()", "verifyAppUnlockSession(")
        self.assertIn("restoreChatDeliveries()", unlocked)
        self.assertIn("scheduleChatDeliverySweep(80)", unlocked)
        detach = self.function_body(
            "detachActiveChatStream()", "cancelActiveChatRequest(")
        self.assertIn("rememberChatDelivery({", detach)
        self.assertIn("scheduleChatDeliverySweep(120)", detach)
        self.assertNotIn("/api/chat/cancel", detach)
        self.assertEqual(detach.count("setChatStreamingState(false)"), 1)
        self.assertIn(
            "addEventListener('pagehide',()=>{"
            "saveConversationDraft();"
            "persistChatDeliveries();"
            "signalNativePendingWork();",
            self.compact,
        )
        self.assertIn(
            "addEventListener('online',()=>{"
            "scheduleChatDeliverySweep(0);",
            self.compact,
        )
        reconcile = self.function_body(
            "reconcileChatDelivery(", "reconcileChatDeliveries(")
        self.assertIn("fetchChatRequestStatus(delivery.request_id)",
                      reconcile)
        self.assertNotIn("if(!navigator.onLine)", reconcile)

    def test_uncertain_navigation_keeps_original_message_as_a_draft(self):
        save = self.function_body(
            "saveUncertainChatAttempt(", "restoreConversationDraft(")
        for value in (
            "text:state.outgoingText",
            "reply:state.outgoingReply",
            "guidance:state.outgoingGuidance",
            "method_id:state.method_id",
            "method_key:state.method_key",
        ):
            self.assertIn(value, save)
        self.assertIn("writeConversationDraft(key,{", save)
        detach = self.function_body(
            "detachActiveChatStream()", "cancelActiveChatRequest(")
        self.assertIn("saveUncertainChatAttempt(state)", detach)
        reconcile = self.function_body(
            "reconcileChatDelivery(", "reconcileChatDeliveries(")
        self.assertIn(
            "settleConversationDraftForRequest("
            "delivery.conv_id,delivery.request_id)",
            re.sub(r"\s+", "", reconcile),
        )

    def test_status_poll_has_a_deadline_and_sweep_cannot_stick(self):
        status = self.function_body(
            "fetchChatRequestStatus(", "removeOptimisticChatTurn(")
        self.assertIn("const controller=new AbortController();", status)
        self.assertIn(
            "setTimeout(()=>controller.abort(),CHAT_STATUS_TIMEOUT_MS)",
            status,
        )
        self.assertIn("{signal:controller.signal}", status)
        self.assertIn("kind:error&&error.name==='AbortError'?'timeout':'network'",
                      re.sub(r"\s+", "", status))
        self.assertIn("finally{\n    clearTimeout(timeout);", status)
        sweep = self.function_body(
            "reconcileChatDeliveries(", "chatRequestFailureMessage(")
        self.assertIn("Promise.allSettled(", sweep)
        self.assertIn("chatDeliverySweepRunning=false;", sweep)
        self.assertIn("scheduleChatDeliverySweep(nextDelay)", sweep)

    def test_new_composer_text_survives_settling_sent_snapshot(self):
        input_start = self.html.index("msgBox.addEventListener('input',()=>{")
        input_end = self.html.index("});", input_start)
        composer_input = self.html[input_start:input_end]
        self.assertIn("conversationDraftRevision++;", composer_input)
        self.assertLess(
            composer_input.index("conversationDraftRevision++;"),
            composer_input.index("scheduleConversationDraft();"),
        )
        settle = self.function_body(
            "settleConversationDraftForRequest(", "saveUncertainChatAttempt(")
        self.assertIn("const newerComposerDraft=revision>sentRevision;",
                      settle)
        self.assertIn(
            "if(recovered.composer_owned&&!newerComposerDraft)", settle)
        self.assertIn("next.text='';next.reply=null;", settle)
        save = self.function_body(
            "saveConversationDraft(", "scheduleConversationDraft(")
        self.assertNotIn("activeChatRequest", save)
        restore = self.function_body(
            "restoreConversationDraft(", "mobileChatViewport(")
        self.assertIn("settleConversationDraftForRequest(", restore)
        self.assertIn("conversationDraftRevision=Math.max(", restore)

    def test_waiting_provider_is_nonterminal_and_clearly_named(self):
        self.assertIn("'waiting_provider'", self.html)
        self.assertIn(
            "LM Studio bekleniyor · açıldığında otomatik devam edecek.",
            self.html,
        )
        self.assertIn("'yerel model bekleniyor…'", self.html)
        self.assertIn("waiting_provider:'Yerel model bekleniyor'",
                      self.html)
        self.assertIn("request.waiting_for_provider===true", self.html)
        self.assertIn("chatRequestAutomaticRetry(request)", self.html)
        reconcile = self.function_body(
            "reconcileChatDelivery(", "reconcileChatDeliveries(")
        self.assertIn(
            "chatRequestIsPending(request)||"
            "chatRequestAutomaticRetry(request)",
            re.sub(r"\s+", "", reconcile),
        )
        delivery = self.function_body(
            "renderChatDeliveryStatus(", "compactChatDelivery(")
        self.assertIn("cancelActiveChatRequest()", delivery)
        self.assertIn("cancel.textContent='Durdur'", delivery)

    def test_retry_reuses_the_durable_request_without_duplicate_user_turn(self):
        legacy = self.function_body(
            "retryChatDeliveryInBackground(", "scheduleChatDeliveryListRefresh(")
        self.assertIn("request_id:delivery.request_id", legacy)
        self.assertIn("/api/chat/retry", legacy)
        self.assertNotIn("/api/chat'", legacy)
        self.assertIn("CHAT_DELIVERY_LEGACY_RETRY_DELAYS", self.html)
        self.assertIn("chatRequestUsesServerRetries(request)", self.html)
        failure = self.function_body(
            "renderChatRequestFailure(", "fetchChatRequestStatus(")
        self.assertIn("Şimdi yeniden dene", failure)
        self.assertIn("Yanıt henüz teslim edilemedi.", self.html)

    def test_native_pending_signal_cannot_be_cleared_by_stale_job_count(self):
        native = self.function_body(
            "signalNativePendingWork(", "syncChatDeliveriesFromConversationRows(")
        self.assertIn(
            "Math.max(forced,pendingJobCount(),pendingChatDeliveryCount())",
            re.sub(r"\s+", "", native),
        )
        self.assertIn("functionsignalNativePendingWork(minPending=0)",
                      re.sub(r"\s+", "", native))
        render_jobs = self.function_body(
            "renderJobsBadge()", "loadJobs(")
        self.assertIn("signalNativePendingWork()", render_jobs)
        self.assertNotIn("setPendingWork(n)", render_jobs)

    def test_settings_offer_private_selected_conversation_transfer(self):
        for control in (
            'id="transferOpenBtn"',
            'id="transferOverlay"',
            'id="transferConversationList"',
            'id="transferExportBtn"',
            'id="transferImportFile"',
            'id="transferImportConsent"',
            'id="transferImportBtn"',
            'id="transferOpenArchive"',
        ):
            self.assertIn(control, self.html)
        for warning in (
            "mesaj metinlerini içerir",
            "şifreli değildir",
            "API anahtarları",
            "profil, notlar, hafıza ve formülasyonlar",
            "Arşiv’e, salt okunur olarak",
        ):
            self.assertIn(warning, self.html)
        self.assertIn("api('/api/transfer/export',{ids})", self.html)
        self.assertIn(
            "api('/api/transfer/preview',{bundle})",
            self.html,
        )
        self.assertIn(
            "api('/api/transfer/import',{", self.html,
        )
        self.assertIn("file.size>4*1024*1024", self.html)
        self.assertIn("transferImportBundle=bundle", self.html)
        self.assertNotIn(
            "localStorage.setItem('transfer", self.html)
        self.assertIn(
            "!transferImportBundle||"
            "!$('transferImportConsent').checked",
            self.compact,
        )
        self.assertIn("item.textContent=(row.title", self.html)
        self.assertIn("setConversationView('archived')", self.html)
        self.assertIn(
            ".transferModal{overflow-y:auto;"
            "-webkit-overflow-scrolling:touch}",
            self.compact,
        )


if __name__ == "__main__":
    unittest.main()
