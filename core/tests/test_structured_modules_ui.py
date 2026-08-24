import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import PROJECT_DIR


class StructuredModulesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(PROJECT_DIR) / "index.html").read_text(
            encoding="utf-8")
        cls.adhd_markup = cls._between(
            '<div class="overlay guidedWorkspaceOverlay" '
            'id="adhdWorkspaceOverlay"',
            '<!-- Young/Kerem Genç: kullanıcı onaylı şema çalışma yolu -->')
        cls.schema_markup = cls._between(
            '<div class="overlay guidedWorkspaceOverlay" '
            'id="schemaPathOverlay"',
            '<!-- seans çerçevesi -->')
        cls.structured_script = cls._between(
            '/* ---------------- yapılandırılmış çalışma alanları '
            '---------------- */',
            '/* ---------------- adhd koçu: görev hatırlatıcıları '
            '---------------- */')
        cls.schema_v4_fixture_path = (
            Path(PROJECT_DIR) / "tests/fixtures/schema_path_v4_contract.json")
        cls.schema_v4_fixture_bytes = cls.schema_v4_fixture_path.read_bytes()
        cls.schema_v4_fixture = json.loads(
            cls.schema_v4_fixture_bytes.decode("utf-8"))

    @classmethod
    def _between(cls, start, end):
        begin = cls.html.index(start)
        finish = cls.html.index(end, begin)
        return cls.html[begin:finish]

    def test_workspace_ids_are_unique_and_menu_items_start_hidden(self):
        ids = [
            "mobileAdhdWorkspaceOpen", "mobileSchemaPathOpen",
            "composerQuickAdhd", "composerQuickSchema",
            "schemaPathBtn", "schemaModeToggle", "schemaHistoryStart",
            "schemaHistoryRetry", "schemaTurnAnnouncement",
            "adhdWorkspaceOverlay", "adhdTodayPanel", "adhdRoutinesPanel",
            "adhdNotebookPanel", "schemaPathOverlay", "schemaCandidateList",
            "schemaWorkForm", "schemaMethodChoiceForm", "schemaPracticeForm",
        ]
        for element_id in ids:
            self.assertEqual(
                len(re.findall(r'id=["\']' + re.escape(element_id) +
                               r'["\']', self.html)),
                1, element_id)
        self.assertRegex(
            self.html,
            r'id="mobileAdhdWorkspaceOpen"[^>]*role="menuitem" hidden')
        self.assertRegex(
            self.html,
            r'id="mobileSchemaPathOpen"[^>]*role="menuitem" hidden')
        self.assertRegex(
            self.html,
            r'id="composerQuickAdhd"[^>]*role="menuitem" hidden')
        self.assertRegex(
            self.html,
            r'id="composerQuickSchema"[^>]*role="menuitem" hidden')
        self.assertIn("adhd:'adhd',schema:'young'", self.structured_script)
        self.assertIn("androidNativeMobileContext()", self.structured_script)
        self.assertIn("document.body.classList.contains('nativeAndroid')",
                      self.structured_script)
        self.assertIn(
            "STRUCTURED_WORKSPACE_MASTER_IDS.adhd",
            self.structured_script)
        self.assertIn(
            "STRUCTURED_WORKSPACE_MASTER_IDS.schema",
            self.structured_script)
        self.assertIn("mobileHeaderWorkGroup", self.structured_script)
        self.assertIn("composerQuickWorkGroup", self.structured_script)

    def test_hidden_header_workspace_sibling_is_not_exposed_to_talkback(self):
        # Author-level ``display:grid`` on menu items otherwise overrides the
        # browser's default [hidden] rule whenever the contextual group itself
        # is visible (Young versus ADHD).  Keep the hidden sibling out of both
        # layout and the accessibility tree with an explicit strong rule.
        self.assertRegex(
            self.html,
            r"\.mobileHeaderMenuItem\[hidden\]\s*\{\s*"
            r"display\s*:\s*none\s*!important")

    def test_entering_safety_hold_immediately_hides_contextual_workspaces(self):
        setter = self.html[
            self.html.index("function setConversationSafetyHold(hold){"):
            self.html.index("function responseMessage", self.html.index(
                "function setConversationSafetyHold(hold){"))]
        self.assertIn("syncStructuredWorkspaceVisibility();", setter)
        self.assertIn("renderImageryWork();", setter)

    def test_chat_suggestion_is_server_gated_and_never_auto_writes(self):
        self.assertIn("/api/adhd/dashboard?conv_id=",
                      self.structured_script)
        self.assertIn("api('/api/adhd/suggestions',payload)",
                      self.structured_script)
        for label in ("Ritim oluştur", "Deftere ekle", "Sonra", "Hayır"):
            self.assertIn(label, self.structured_script)
        self.assertIn("value.requires_user_confirmation!==true",
                      self.structured_script)
        self.assertIn("value.creates_record!==false", self.structured_script)
        self.assertIn("response.creates_record!==false",
                      self.structured_script)
        accept = self.structured_script[
            self.structured_script.index(
                "async function resolveAdhdConversationSuggestion"):
            self.structured_script.index(
                "function renderAdhdConversationSuggestion")]
        self.assertIn("/api/adhd/suggestions", accept)
        self.assertNotIn("/api/adhd/habits", accept)
        self.assertNotIn("/api/adhd/journal", accept)
        self.assertIn("openAdhdSuggestionDraft", accept)
        self.assertIn("openAdhdRoutineForm()", self.structured_script)
        self.assertIn("openAdhdJournalForm()", self.structured_script)
        self.assertIn("$('adhdJournalSensitive').checked=true",
                      self.structured_script)
        self.assertIn("$('adhdJournalShare').checked=false",
                      self.structured_script)
        self.assertIn("ADHD_SUGGESTION_SNOOZE_SECONDS=3*24*60*60",
                      self.structured_script)
        self.assertIn("ADHD_SUGGESTION_UI_STORAGE_PREFIX",
                      self.structured_script)
        self.assertNotIn("evidence_excerpt", self.structured_script)

    def test_adhd_workspace_contract_and_privacy_defaults(self):
        self.assertIn('/api/adhd/dashboard?conv_id=', self.structured_script)
        for endpoint in (
                "/api/adhd/habits", "/api/adhd/events",
                "/api/adhd/journal"):
            self.assertIn(endpoint, self.structured_script)
        self.assertIn("request_id:structuredRequestId('adhd-habit')",
                      self.structured_script)
        self.assertIn('id="adhdRoutineTarget" type="number" min="1" '
                      'max="7"', self.adhd_markup)
        self.assertIn('value="2" required', self.adhd_markup)
        self.assertRegex(
            self.adhd_markup,
            r'id="adhdJournalSensitive" checked')
        self.assertRegex(
            self.adhd_markup,
            r'id="adhdJournalShare" disabled')
        self.assertIn(
            "share_with_coach:!sensitive&&$('adhdJournalShare').checked",
            self.structured_script)
        self.assertIn("const sensitive=entry?entry.sensitive!==false:true",
                      self.structured_script)
        self.assertIn("response.activities_paused", self.structured_script)
        self.assertIn("response.paused_reminder_ids", self.structured_script)
        self.assertIn("cancelReminderNotification(nativeId)",
                      self.structured_script)
        self.assertIn("setConversationSafetyHold(true)",
                      self.structured_script)

    def test_adhd_schedule_is_a_separate_explicit_action(self):
        self.assertIn('id="adhdScheduleConsent"', self.adhd_markup)
        self.assertIn('id="adhdScheduleSave" disabled', self.adhd_markup)
        self.assertIn('bildirim kendiliğinden kurulmaz', self.adhd_markup)
        routine_save = self.structured_script[
            self.structured_script.index('async function saveAdhdRoutine'):
            self.structured_script.index('async function mutateAdhdHabit')]
        self.assertNotIn('scheduleReminderNotificationFor', routine_save)
        schedule_save = self.structured_script[
            self.structured_script.index('async function saveAdhdSchedule'):
            self.structured_script.index('async function submitAdhdEvent')]
        self.assertIn("action:'schedule'", schedule_save)
        self.assertIn("$('adhdScheduleConsent').checked", schedule_save)
        self.assertIn('scheduleReminderNotificationFor(reminder)', schedule_save)
        start_now = self.structured_script[
            self.structured_script.index('async function startAdhdHabitNow'):
            self.structured_script.index('async function submitAdhdEvent')]
        self.assertIn("action:'start_now'", start_now)
        self.assertNotIn('scheduleReminderNotificationFor', start_now)
        self.assertIn('if(response&&response.reminder)', start_now)

    def test_adhd_has_one_today_action_and_non_shaming_review(self):
        for label in (
                "Yaptım", "Kısmen yaptım", "Bugün değil",
                "Aynı kalsın", "Daha küçük", "Bir artır", "Bir azalt",
                "Duraklat"):
            self.assertIn(label, self.structured_script)
        self.assertIn('Otomatik hedef artırımı yoktur', self.adhd_markup)
        self.assertIn('ceza veya kayıp yok', self.structured_script)
        self.assertNotIn('🔥', self.adhd_markup)
        self.assertNotIn('streak', self.adhd_markup.lower())
        for template in (
                "Defterle yaşa", "Başlama köprüsü", "Sürtünmeyi izle",
                "Birlikte başla"):
            self.assertIn(template, self.adhd_markup)
        self.assertIn("function applyAdhdRoutineTemplate",
                      self.structured_script)
        for friction in (
                "'start'", "'decision'", "'sustain'", "'finish'",
                "'emotion'", "'environment'"):
            self.assertIn(friction, self.structured_script)

    def test_notebook_types_notice_and_safe_text_rendering(self):
        for entry_type in (
                "capture", "daily_page", "friction", "freewrite",
                "weekly_review"):
            self.assertIn(f'value="{entry_type}"', self.adhd_markup)
        self.assertIn('Bu defter acil durumlar için izlenmez',
                      self.adhd_markup)
        self.assertIn("112'yi arayın", self.adhd_markup)
        self.assertNotIn('innerHTML', self.structured_script)
        self.assertIn('card.appendChild(guidedNode', self.structured_script)
        self.assertIn('.textContent=', self.structured_script)

    def test_schema_candidate_requires_user_evaluation_and_direct_evidence(self):
        for copy in (
                "Sizin doğrudan sözleriniz", "Uymayan örnek:",
                "Alternatif açıklama:", "Bunu zayıflatacak gözlem:"):
            self.assertIn(copy, self.structured_script)
        for decision in ("accept", "defer", "dismiss"):
            self.assertIn("'" + decision + "'", self.structured_script)
        self.assertIn("action:'review'", self.structured_script)
        self.assertIn("postSchemaPath('review_candidate'",
                      self.structured_script)
        self.assertIn("schemaCandidateEligible(candidate)",
                      self.structured_script)
        self.assertIn("schemaCandidateSourceTurn(candidate)",
                      self.structured_script)
        self.assertIn('Bu bir tanı veya kesin açıklama değil',
                      self.structured_script)
        self.assertNotIn('kökü kurut', self.schema_markup.lower())
        self.assertNotIn('tedavi edildi', self.schema_markup.lower())

    def test_schema_mode_is_exact_young_main_therapy_and_cross_platform(self):
        self.assertIn("schema:'young'", self.structured_script)
        self.assertIn("String(convData.submode||'')===''",
                      self.structured_script)
        self.assertIn("const schemaReady=structuredWorkspaceConversation(",
                      self.structured_script)
        self.assertIn("const schemaVisible=mobileChatViewport()&&schemaReady",
                      self.structured_script)
        # Üst şeritteki düğme artık paneli açmıyor, konuşmayı inceliyor;
        # bu yüzden telefonda da görünür (panel telefonda gizli).
        self.assertIn("syncSchemaReviewButton()", self.structured_script)
        self.assertIn("$('schemaPathBtn').onclick=reviewWholeConversation",
                      self.html)
        # Düğme yalnız Kerem'in şema modu açık görüşmesinde çıkar.
        review = self._between(
            "function schemaReviewAvailable",
            "async function reviewWholeConversation")
        self.assertIn("structuredWorkspaceConversation('young')", review)
        self.assertIn("schemaModeEnabled()", review)
        scan = self._between(
            "async function reviewWholeConversation",
            "function syncSchemaReviewButton")
        self.assertIn("scan_history", scan)
        # Gönderimden önce açık onay istenir.
        self.assertIn("confirm(", scan)
        self.assertRegex(self.html, r"\.topBtn\[hidden\]\s*\{\s*"
                         r"display\s*:\s*none\s*!important")

    def test_schema_mode_consent_is_future_only_and_provider_disclosed(self):
        for element_id in (
                "schemaModePanel", "schemaModeDisclosure",
                "schemaModeToggle", "schemaModeHint"):
            self.assertIn(f'id="{element_id}"', self.schema_markup)
        self.assertIn("schemaProviderConsentSnapshot()",
                      self.structured_script)
        self.assertIn("enabled:!!enabled,...(enabled?provider:{})",
                      self.structured_script)
        self.assertIn("schemaProviderDestination(provider)",
                      self.structured_script)
        self.assertIn("Geçmiş turlar bu onaya dahil değildir",
                      self.structured_script)
        self.assertIn("Bu onay yalnız gelecekteki turlar içindir",
                      self.structured_script)
        self.assertIn("pending_device_confirmation",
                      self.structured_script)
        self.assertIn("pending_provider_confirmation",
                      self.structured_script)
        self.assertIn("bulut sağlayıcınız ücret uygulayabilir",
                      self.structured_script)
        self.assertIn("siz onaylamadan çalışma yolu başlamaz",
                      self.structured_script)

    def test_turn_candidates_surface_in_a_fixed_card_not_a_forged_message(self):
        """Aday, input üstündeki sabit kartta görünür.

        Kart eskiden ustanın balonuna iliştiriliyordu; izin verisi geç
        gelince kart ölü bir "hazırlanıyor" durumunda kalıyordu. Sabit
        kart bu yarışı ortadan kaldırır.
        """
        # Başlık kartın işaretlemesinde, düğme metinleri betikte.
        self.assertIn("Bir çalışma olasılığı fark ettim", self.html)
        self.assertIn('id="schemaSuggestCard"', self.html)
        for copy in ("Bunu çalışalım", "Şimdilik değil"):
            self.assertIn(copy, self.structured_script)
        card = self._between(
            "function renderSchemaSuggestCard",
            "function dismissSchemaSuggestCard")
        # Kart sahte sohbet mesajı üretmez ve sessizce çalışma başlatmaz.
        self.assertNotIn("addBubble(", card)
        self.assertNotIn("postSchemaPath('start'", card)
        # İzin gelmeden kart hiç gösterilmez: ölü düğme yerine sessizlik.
        self.assertIn("schemaActionAllowed('review_candidate')", card)
        self.assertIn("card.hidden=true", card)

    def test_suggestion_card_is_dismissible_without_deciding(self):
        """× yalnız görünümü kapatır; sunucuya karar göndermez."""
        dismiss = self._between(
            "function dismissSchemaSuggestCard",
            "function lastUserMessageText")
        self.assertIn("schemaSuggestDismissed.add", dismiss)
        self.assertNotIn("postSchemaPath(", dismiss)
        self.assertNotIn("reviewSchemaCandidate(", dismiss)

    def test_multiple_suggestions_scroll_side_by_side(self):
        """Yatay şerit yalnız v3 geriye uyumluluğunda kalır."""
        card = self._between(
            "function renderSchemaSuggestCard",
            "function dismissSchemaSuggestCard")
        # En fazla üç: fazlası seçim değil, yük olur.
        self.assertIn("rows.slice(0,schemaProtocolV4()?1:3)", card)
        self.assertIn("more.hidden=schemaProtocolV4()", card)
        self.assertIn("yana kaydırarak", card)
        self.assertIn("schemaSuggestTrack", self.html)
        self.assertIn("scroll-snap-type:x mandatory", self.html)

    def test_each_suggestion_can_be_dismissed_on_its_own(self):
        """Her kartın kendi kapatma düğmesi var."""
        builder = self._between(
            "function buildSchemaSuggestCard",
            "function renderSchemaSuggestCard")
        self.assertIn("schemaSuggestItemClose", builder)
        self.assertIn("schemaSuggestDismissed.add", builder)
        # Kapatmak yalnız öneriyi susturur: bir daha gösterilmesin diye
        # sunucuya `dismiss_suggestion` gider. Bu bir klinik karar
        # değildir — aday kabul/ret kararı yazılmaz.
        self.assertIn("dismiss_suggestion", builder)
        # Kapatma dalı yalnız susturur; klinik karar (kabul/ret) yazmaz.
        kapat = builder[builder.index("close.onclick"):]
        kapat = kapat[:kapat.index("card.appendChild(head)")]
        self.assertIn("dismiss_suggestion", kapat)
        self.assertNotIn("review_candidate", kapat)

    def test_phase_steps_are_asked_in_chat_not_in_a_panel(self):
        """Faz geçişleri sohbetteki aşama kartında sorulur."""
        self.assertIn('id="schemaStepCard"', self.html)
        state = self._between(
            "function schemaStepCardState", "function renderSchemaStepCard")
        # Sunucunun önkoşulları arayüzde de biliniyor: karşılanmadan
        # ilerlet düğmesi gösterilmez, ne gerektiği yazılır.
        self.assertIn("current_trigger", state)
        self.assertIn("focus?.chosen", state)
        self.assertIn("method_id", state)
        self.assertIn("blocked", state)

    def test_precheck_methods_are_never_started_silently_from_chat(self):
        """Ön kontrol isteyen yöntem seçilince önce kısa kontrol sorulur.

        Yöntem artık sohbette listelenir (eskiden hiç listelenmiyordu),
        ama seçmek doğrudan başlatmaz: kontrol tamamlanmadan sunucuya
        `choose_method` gitmez.
        """
        card = self._between(
            "function renderSchemaStepCard",
            "function schemaModeInviteAvailable")
        self.assertIn("m.requires_precheck", card)
        self.assertIn("beginSchemaChatPrecheck(m)", card)
        # Ön kontrol dalı, gönderime ulaşmadan `return` ile çıkar.
        self.assertIn(
            "if(m.requires_precheck){beginSchemaChatPrecheck(m);return;}",
            card.replace("\n", "").replace(" ", ""))

    def test_chat_precheck_asks_every_required_field(self):
        """Sunucunun istediği altı alanın hiçbiri varsayılmaz."""
        finish = self._between(
            "async function finishSchemaChatPrecheck",
            "function schemaStepCardState")
        for field in ("orientation_confirmed", "reality_clear",
                      "sleep_activation_clear", "intensity",
                      "support_available", "stop_signal"):
            self.assertIn(field, finish)
        flow = self._between(
            "function renderSchemaChatPrecheck",
            "async function finishSchemaChatPrecheck")
        # Yönelim veya uyku net değilse çalışma bugün açılmaz.
        self.assertIn("cancelSchemaChatPrecheck()", flow)
        self.assertIn("Vazgeç", flow)

    def test_depth_steps_are_asked_in_chat_and_stay_optional(self):
        """Köken, büyütme ve Sağlıklı Yetişkin sohbette sorulur."""
        depth = self._between(
            "function schemaWorkDepthStep", "function schemaStepCardState")
        for action in ("record_origin", "add_growth_stage",
                       "record_growth", "mark_healthy_adult"):
            self.assertIn(action, depth)
        # Her adım atlanabilir; atlanan adım tekrar sorulmaz.
        self.assertIn("Şimdi değil", depth)
        self.assertIn("schemaDepthSkipped.add", depth)

    def test_origin_never_invents_an_age_or_scene(self):
        """Sahte anı yasağı: sahne yalnız kullanıcının kendi sözünden."""
        depth = self._between(
            "function schemaWorkDepthStep", "function schemaStepCardState")
        depth = depth.split(
            "/* --- Şema Çalışma Yolu v4:", 1)[0]
        # Arayüz yaş uydurmaz; yalnız kullanıcının son sözünü önerir.
        self.assertIn("scene:son.slice", depth.replace(" ", ""))
        self.assertNotIn("age:", depth)
        # "Hatırlamıyorum" tam bir cevaptır.
        self.assertIn("confidence:'unknown'", depth.replace(" ", ""))

    def test_schema_v5_fixture_and_chat_state_contract_are_pinned(self):
        self.assertEqual(
            hashlib.sha256(self.schema_v4_fixture_bytes).hexdigest(),
            "30e2cac7c8ced6e58a3f8860ea887f1f1e6f42cb888d21da6bcaad7803294197",
        )
        fixture = self.schema_v4_fixture
        self.assertEqual(fixture["protocol"], "schema_path_chat_v5")
        self.assertEqual(fixture["version"], 5)
        self.assertEqual(fixture["fixture_version"], 8)
        self.assertEqual(fixture["presentation"], "chat_only")
        self.assertEqual(fixture["contract"]["runtime"], {
            "protocol": "schema_path_chat_v5",
            "schema_version": 5,
            "path_flow_version": 5,
            "presentation": "chat_only",
            "sync_batch_version": 8,
            "fixture_version": 8,
        })

        candidate = fixture["card_examples"]["candidate_prompt"]
        self.assertEqual(candidate["kind"], "candidate_prompt")
        self.assertEqual(candidate["body"], "Bunu çalışmak ister misin?")
        self.assertTrue(candidate["context_line"].endswith(
            " tetiklenmiş olabilir."))
        self.assertEqual(
            [(item["action"], item["label"])
             for item in candidate["actions"]],
            [("accept_candidate_chat", "Evet"),
             ("reject_candidate_chat", "Hayır")])
        self.assertEqual(candidate["fields"], [])

        for name, card in fixture["card_examples"].items():
            if card["kind"] == "candidate_prompt":
                continue
            self.assertEqual(card["kind"], "chat_state", name)
            self.assertEqual(card["presentation"], "chat_only", name)
            self.assertEqual(
                (card["title"], card["context_line"], card["body"]),
                ("", "", ""), name)
            self.assertEqual(card["fields"], [], name)
            self.assertEqual(card["actions"], [], name)
        self.assertEqual(
            fixture["contract"]["card"]["post_yes_visible_action_values"],
            [])
        self.assertFalse(fixture["contract"]["post_yes_messages"]
                         ["visible_suffix_or_continuation"])
        self.assertFalse(fixture["contract"]["post_yes_messages"]
                         ["synthetic_assistant_message"])

        prompt = fixture["card_examples"]["completed_chat_state"]
        self.assertEqual(prompt["chat_binding"],
                         fixture["chat_schema_binding"])
        self.assertNotIn("step_data", prompt["chat_binding"])
        self.assertEqual(
            prompt["prompt_delivery"]["prompt_assistant_message_id"],
            prompt["chat_binding"]["prompt_assistant_message_id"])
        self.assertEqual(
            prompt["source"]["assistant_message_id"],
            prompt["chat_binding"]["prompt_assistant_message_id"])

        imported = fixture["card_examples"][
            "imported_waiting_chat_state"]
        self.assertEqual(imported["chat_binding"],
                         fixture["import_control_binding"])
        self.assertIs(imported["chat_binding"]["sync_import_control"], True)
        for key in (
                "prompt_request_id", "prompt_assistant_message_id",
                "prompt_assistant_message_public_id"):
            self.assertIn(key, imported["chat_binding"])
            self.assertIsNone(imported["chat_binding"][key])
        self.assertIsNone(imported["prompt_delivery"]["request_id"])
        self.assertEqual(
            imported["prompt_delivery"]["status"], "imported_waiting")
        self.assertEqual(
            fixture["contract"]["sync_import"]["dashboard_get_"
                    "message_job_request_delta"], [0, 0, 0])

        controls = fixture["contract"]["controls"]
        self.assertEqual(controls["visible_controls_after_yes"], [])
        self.assertEqual(controls["exact_commands"]["ground"],
                         ["şimdiye dön", "topraklan"])
        self.assertEqual(controls["exact_commands"]["back"], [
            "geri dön", "önceki adıma dön", "bir adım geri"])
        self.assertEqual(controls["exact_commands"]["stop"], [
            "bitir", "bitirelim", "çalışmayı bitir",
            "bu çalışmayı bırak"])
        self.assertFalse(controls["synthetic_acknowledgement"])
        self.assertTrue(controls["contextual_word_is_not_command"])

        runtime_text = json.dumps(
            fixture["card_examples"], ensure_ascii=False).casefold()
        for forbidden in (
                "0 ile 10", "0–10", "0 ile 7", "0–7", "yoğunluk",
                "şiddet", "seviye", "çalışalım mı", "onay",
                "desteğin var", "stop sinyali"):
            self.assertNotIn(forbidden, runtime_text)

        renderer = self._between(
            "function renderSchemaChatOnlyCard(",
            "function renderSchemaV4ActiveCard(")
        self.assertIn("schemaProtocolV5()&&kind==='chat_state'", renderer)
        self.assertNotIn("card.body", renderer)
        self.assertNotIn("card.actions", renderer)
        self.assertNotIn("guidedButton(", renderer)
        binding = self._between(
            "function schemaV5PromptDeliveryFor(",
            "async function refreshSchemaV5DurableMessages(")
        self.assertIn("'completed','imported_waiting'", binding)
        self.assertIn("sync_import_control", binding)
        self.assertIn("prompt_assistant_message_id", binding)


    def test_schema_v4_message_meta_is_stable_anchored_and_editable(self):
        meta = self._between(
            "function schemaV4MetaKey(",
            "function schemaV4ComposerBindingFor(")
        self.assertIn("meta.public_id||meta.id", meta)
        self.assertIn("messageBubbleById.get(anchorId)", meta)
        self.assertIn("source_assistant_message_id", meta)
        self.assertIn("undo_map_update", self.structured_script)
        self.assertIn("make_map_update_private", self.structured_script)
        self.assertIn("edit_map_update", self.structured_script)
        message_renderer = self._between(
            "function renderConversationMessage(",
            "function setBubbleContent(")
        self.assertIn("m.meta_events", message_renderer)
        self.assertIn("renderSchemaMessageMetaEvents", message_renderer)

    def test_schema_v4_bound_composer_is_idempotent_and_resumable(self):
        sender = self._between(
            "async function send(",
            "/* ---------------- seans bitir")
        self.assertIn("schema_binding:schemaBindingForSend", sender)
        self.assertIn("handleSchemaV4HttpError", sender)
        self.assertIn("applySchemaV4ServerProjection", sender)
        errors = self._between(
            "const SCHEMA_V4_ERROR_COPY=", "function schemaV4TechniqueLink(")
        self.assertIn("stale_technique_revision", errors)
        self.assertIn("schema_sync_conflict", errors)
        drafts = self._between(
            "function compactSchemaBinding(",
            "function mobileChatViewport(")
        self.assertIn("schema_binding:compactSchemaBinding", drafts)
        self.assertIn("JSON.stringify(left.schema_binding)", drafts)
        binding = self._between(
            "function schemaV4ComposerBindingFor(",
            "function renderSchemaV4ActiveCard(")
        for key in ("path_id", "step_id", "expected_revision",
                    "technique_link_id", "technique_link_public_id",
                    "expected_technique_revision", "step_data"):
            self.assertIn(key, binding)
        self.assertIn("schemaComposerBindingCollapsed=true",
                      self.html)

    def test_schema_v4_busy_release_rerenders_card_and_composer(self):
        """GET veya mutation sonrası kart busy DOM durumunda kalmamalı."""
        loader = self._between(
            "async function loadSchemaPathDashboard(",
            "async function postSchemaPath(")
        load_finally = loader[loader.rindex("}finally{"):]
        self.assertLess(load_finally.index("schemaPathBusy=false"),
                        load_finally.index("renderSchemaStepCard()"))

        mutation = self._between(
            "async function postSchemaPath(",
            "function resetSchemaTurnUi(")
        mutation_finally = mutation[mutation.rindex("}finally{"):]
        self.assertLess(mutation_finally.index("schemaPathBusy=false"),
                        mutation_finally.index("renderSchemaStepCard()"))
        for finalizer in (load_finally, mutation_finally):
            self.assertIn("renderSchemaModeAndHistory()", finalizer)
            self.assertIn("renderSchemaStepCard()", finalizer)

    def test_schema_v4_projection_order_rejects_late_checkpoint_regression(self):
        ordering = self._between(
            "function schemaV4ProjectionOrder(",
            "function schemaV4FieldDomId(")
        program = ordering + r"""
const path='99999999999999999999999999999999';
const projection=(revision,seq,publicId=path)=>({revision,
  active_path:{public_id:publicId,revision},
  next_card:{path_public_id:publicId,revision,checkpoint:{seq}}});
const current=projection(12,4);
if(!schemaV4ProjectionIsStale(projection(12,3),current))
  throw new Error('late lower checkpoint revived');
if(!schemaV4ProjectionIsStale(projection(11,99),current))
  throw new Error('late lower revision revived');
if(schemaV4ProjectionIsStale(projection(12,5),current)||
   schemaV4ProjectionIsStale(projection(13,1),current))
  throw new Error('new append-only checkpoint rejected');
if(schemaV4ProjectionIsStale(
   projection(1,1,'88888888888888888888888888888888'),current))
  throw new Error('new path compared to old path');
if(!schemaV4ProjectionIsStale({dashboard:projection(12,3)},current))
  throw new Error('wrapped SSE/status projection escaped ordering');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        loader = self._between(
            "async function loadSchemaPathDashboard(",
            "async function postSchemaPath(")
        self.assertIn(
            "schemaV4ProjectionIsStale(response,schemaPathDashboard)",
            loader)
        projection = self._between(
            "function applySchemaV4ServerProjection(",
            "function schemaStepCardState(")
        self.assertIn(
            "schemaV4ProjectionIsStale(source,schemaPathDashboard)",
            projection)

    def test_schema_v4_chat_candidate_yes_starts_atomically_and_no_is_pathless(self):
        actions = self._between(
            "const SCHEMA_V4_PREPATH_ACTIONS=",
            "const SCHEMA_V4_COMPOSER_TEXT_ACTIONS=")
        self.assertIn("'accept_candidate_chat'", actions)
        self.assertIn("'reject_candidate_chat'", actions)
        sender = self._between(
            "async function postSchemaV4CardAction(",
            "function setSchemaV4CardStatus(")
        pathless_at = sender.index(
            "SCHEMA_V4_PREPATH_ACTIONS.has(actionName)")
        mutation_at = sender.index("schemaV4MutationPayload(")
        self.assertLess(pathless_at, mutation_at)
        pathless = sender[pathless_at:mutation_at]
        self.assertIn("postSchemaPath(actionName,fields", pathless)
        self.assertNotIn("path_id", pathless)
        post = self._between(
            "async function postSchemaPath(", "function resetSchemaTurnUi(")
        self.assertIn("'accept_candidate_chat','reject_candidate_chat'", post)

        candidate = self._between(
            "function renderSchemaChatOnlyCandidate(",
            "function focusSchemaChatOnlyInteraction(")
        self.assertIn("schemaChatOnlyCandidateCopy(", candidate)
        self.assertIn("schemaChatOnlyCandidateUserContent(card)", candidate)
        copy_helper = self._between(
            "function schemaCandidateClipContext(",
            "function renderSchemaChatOnlyCandidate(")
        self.assertIn("source.quote", copy_helper)
        self.assertIn("Üzerinde çalışabileceğimiz konu: “", candidate)
        self.assertIn("Olası örüntü: ", candidate)
        self.assertIn("card.body", candidate)
        self.assertIn("['accept_candidate_chat','Evet','yes']", candidate)
        self.assertIn("['reject_candidate_chat','Hayır','no']", candidate)
        self.assertIn("schemaChatOnlyAnchorBubble(card)", candidate)
        self.assertIn("insertSchemaChatBubbleAttachment", candidate)
        self.assertNotIn("addBubble(", candidate)
        self.assertNotIn("progress", candidate)
        self.assertNotIn("card.context_line", candidate)
        self.assertNotIn("set_clinical_sync", candidate)
        self.assertNotIn("Bu bir tanı değildir.", candidate)
        compact = re.sub(r"\s+", "", self.html)
        self.assertIn(
            ".schemaTurnPrompt.schemaChatAttachment{width:auto;"
            "margin:9px00;padding:8px00;border:0;border-top:1pxsolid",
            compact,
        )
        self.assertIn("border-radius:0;background:transparent;", compact)
        self.assertIn("box-shadow:none", compact)
        anchor = self._between(
            "function schemaChatOnlyAnchorBubble(",
            "function schemaChatOnlyActionName(")
        self.assertIn("if(assistantId)return null", anchor)
        self.assertIn("messageBubbleById.get(userId)", anchor)
        self.assertIn("!user.closest('.row.user')", anchor)
        # Gecikmiş aday kendi eski kaynak çiftinde kalabilir. Evet'ten sonra
        # gelen çalışma sorusu ise yalnız sunucunun yeniden sabitlediği en son
        # gerçek Kerem balonunda açılır; eski balona bağlanırsa composer
        # fail-closed kalır.
        latest_guard = "String(card&&card.kind||'')==='chat_prompt'"
        self.assertIn(latest_guard, anchor)
        self.assertLess(anchor.index(latest_guard),
                        anchor.index("exact!==rows[rows.length-1]"))
        self.assertIn("exact!==rows[rows.length-1]", anchor)

        validator = self._between(
            "function schemaChatOnlyActionName(",
            "function renderSchemaChatOnlyCandidate(")
        program = validator + r"""
const source={user_message_id:11,
  user_message_public_id:'11111111111111111111111111111111',
  assistant_message_id:12,
  assistant_message_public_id:'22222222222222222222222222222222'};
const candidate={public_id:'33333333333333333333333333333333'};
const payload={claim_id:7,candidate_public_id:candidate.public_id,
  source_user_message_id:source.user_message_id,
  source_user_message_public_id:source.user_message_public_id,
  source_assistant_message_id:source.assistant_message_id,
  source_assistant_message_public_id:source.assistant_message_public_id};
const card={source,candidate,actions:[
  {action:'accept_candidate_chat',payload:{...payload}},
  {action:'reject_candidate_chat',payload:{...payload}}]};
if(!schemaChatOnlyCandidateAction(card,'accept_candidate_chat'))
  throw new Error('valid candidate rejected');
card.actions[0].payload.source_assistant_message_id=99;
if(schemaChatOnlyCandidateAction(card,'accept_candidate_chat')!==null)
  throw new Error('mismatched source accepted');
card.actions[0].payload={...payload,claim_id:'7'};
if(schemaChatOnlyCandidateAction(card,'accept_candidate_chat')!==null)
  throw new Error('non-canonical claim id accepted');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

        copy_program = copy_helper + r"""
const good={source:{quote:'  Toplantıda sözüm kesilince geri çekiliyorum.  '},
  candidate:{schema_label:'Terk Edilme / İstikrarsızlık',mode_label:''}};
const loaded='Toplantıda sözüm kesilince geri çekiliyorum.';
const copy=schemaChatOnlyCandidateCopy(good,loaded);
if(!copy||copy.quote!=='Toplantıda sözüm kesilince geri çekiliyorum.'||
    copy.pattern!=='Terk Edilme / İstikrarsızlık')
  throw new Error('trusted source quote was not preserved');
for(const source of [{}, {quote:''}, {quote:{text:'uydurma'}},
  {quote:'x'.repeat(701)}, {quote:'sakıncalı\u0000metin'},
  {quote:'sakıncalı\u0080metin'}, {quote:'sahte\u202Ebağlam'}]){
  if(schemaChatOnlyCandidateCopy({...good,source},loaded)!==null)
    throw new Error('invalid source quote was accepted');
}
if(schemaChatOnlyCandidateCopy(good,'Farklı ama güvenli bir cümle')!==null)
  throw new Error('mismatched loaded user bubble was accepted');
if(schemaChatOnlyCandidateCopy({...good,source:{quote:'geçerli'},
    candidate:{schema_label:'',mode_label:''}},'geçerli')!==null)
  throw new Error('label-less candidate was accepted');
const longText='baş '.repeat(190)+'SON';
const clipped=schemaCandidateClipContext(longText,700);
if([...clipped].length>700||!clipped.includes('kayıt bağlam için kısaltıldı'))
  throw new Error('server-compatible 700 character clipping failed');
if(!schemaChatOnlyCandidateCopy({...good,source:{quote:clipped}},longText))
  throw new Error('exact clipped loaded bubble was rejected');
const pythonTrimSource='a'.repeat(451)+'\u001c'+
  'm'.repeat(90)+'\u001c'+'z'.repeat(212);
const pythonTrimExpected='a'.repeat(451)+
  '\n… [kayıt bağlam için kısaltıldı] …\n'+'z'.repeat(212);
if(schemaCandidateClipContext(pythonTrimSource,700)!==pythonTrimExpected)
  throw new Error('Python rstrip/lstrip parity was lost');
"""
        result = subprocess.run(
            ["node", "-e", copy_program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_v4_pause_stop_and_reject_do_not_require_form_fields(self):
        field_actions = self._between(
            "const SCHEMA_V4_FIELD_ACTIONS=",
            "const SCHEMA_V4_COMPOSER_TEXT_ACTIONS=")
        for action in ("'rate_current_situation'",
                       "'record_variable_check'",
                       "'start_chat_technique'", "'assign_practice'"):
            self.assertIn(action, field_actions)
        for escape in ("'pause'", "'stop'", "'skip_step'",
                       "'reject_candidate'"):
            self.assertNotIn(escape, field_actions)

    def test_schema_v5_has_no_post_start_question_or_direct_controls(self):
        self.assertNotIn("schemaChatContinuation", self.html)
        self.assertNotIn("schemaChatInlineControls", self.html)
        self.assertNotIn("renderSchemaChatOnlyContinuation", self.html)
        self.assertNotIn("schemaChatOnlyGroundControlValid", self.html)
        renderer = self._between(
            "function renderSchemaChatOnlyCard(",
            "function renderSchemaV4ActiveCard(")
        self.assertIn("schemaProtocolV5()&&kind==='chat_state'", renderer)
        self.assertIn("syncSchemaV5PromptState(card)", renderer)
        self.assertNotIn("card.body", renderer)
        self.assertNotIn("card.actions", renderer)
        self.assertNotIn("guidedButton(", renderer)
        candidate = self._between(
            "function renderSchemaChatOnlyCandidate(",
            "function focusSchemaChatOnlyInteraction(")
        self.assertIn("'Evet'", candidate)
        self.assertIn("'Hayır'", candidate)
        self.assertIn("Bunu çalışmak ister misin?", candidate)

    def test_schema_v5_completed_prompt_requires_exact_latest_durable_pair(self):
        compact = self._between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        helpers = self._between(
            "function schemaV5PromptDeliveryFor(",
            "function schemaV4ChatOnlyComposerBindingFor(")
        program = r"""
function compactSchemaStepData(value){return value||{};}
""" + compact + r"""
const pathPublic='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const userPublic='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const assistantPublic='cccccccccccccccccccccccccccccccc';
const checkpointPublic='dddddddddddddddddddddddddddddddd';
const requestId='schema-v5-prompt-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';
let schemaPathDashboard={active_path:{id:9,public_id:pathPublic,
  revision:7,flow_version:5,status:'active',stage:'listen',
  step:'current_impact'},interaction_policy:{
    composer_surface:'ordinary_chat',inline_controls_only:false,
    composer_mode:'bound',composer_allowed:true,
    composer_binding_required:true,bound_step_id:'current_impact'}};
function schemaProtocolV5(){return true;}
function schemaChatOnlyCard(){return true;}
function schemaPathId(){return 9;}
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
let laterAssistant=null;
const chat={querySelectorAll(selector){
  if(selector==='.row .bubble')return laterAssistant
    ?[user,assistant,laterAssistant]:[user,assistant];
  if(selector==='.row.therapist .bubble')return laterAssistant
    ?[assistant,laterAssistant]:[assistant];
  return [];
}};
const messageBubbleById=new Map([[21,user],[22,assistant]]);
const binding={protocol:'schema_path_chat_v5',path_id:9,
  path_public_id:pathPublic,step_id:'current_impact',expected_revision:7,
  checkpoint_public_id:checkpointPublic,expected_checkpoint_seq:4,
  prompt_request_id:requestId,prompt_assistant_message_id:22,
  prompt_assistant_message_public_id:assistantPublic,
  source_user_message_id:21,source_user_message_public_id:userPublic,
  source_assistant_message_id:22,
  source_assistant_message_public_id:assistantPublic};
const card={id:'card',kind:'chat_state',presentation:'chat_only',
  status:'active',path_id:9,path_public_id:pathPublic,
  stage:'listen',step:'current_impact',revision:7,
  title:'',context_line:'',body:'',fields:[],actions:[],
  checkpoint:{public_id:checkpointPublic,seq:4,
    prompt_key:'current_impact',method_id:null,status:'active',
    can_backtrack:false,backtrack_pending:false,
    pending_target_public_id:null},
  prompt_delivery:{request_id:requestId,status:'completed',
    prompt_assistant_message_id:22,
    prompt_assistant_message_public_id:assistantPublic,error_code:null},
  source:{user_message_id:21,user_message_public_id:userPublic,
    assistant_message_id:22,
    assistant_message_public_id:assistantPublic},
  chat_binding:{...binding}};
""" + helpers + r"""
if(!schemaV5ChatStateComposerBindingFor(card))
  throw new Error('exact durable prompt pair rejected');
if(schemaV5PromptDeliveryFor({...card,body:'UI sorusu'})!==null)
  throw new Error('visible card question accepted');
if(compactSchemaBinding({...binding,step_data:{answer:'x'}})!==null)
  throw new Error('visible form snapshot accepted');
if(compactSchemaBinding({...binding,technique_link_id:2})!==null)
  throw new Error('legacy technique identity accepted');
card.prompt_delivery={request_id:requestId,status:'running',
  prompt_assistant_message_id:null,
  prompt_assistant_message_public_id:null,error_code:null};
if(schemaV5ChatStateComposerBindingFor(card)!==null)
  throw new Error('running prompt opened composer');
card.prompt_delivery={request_id:requestId,status:'completed',
  prompt_assistant_message_id:22,
  prompt_assistant_message_public_id:assistantPublic,error_code:null};
assistant.dataset.messagePublicId='ffffffffffffffffffffffffffffffff';
if(schemaV5ChatStateComposerBindingFor(card)!==null)
  throw new Error('public id mismatch opened composer');
assistant.dataset.messagePublicId=assistantPublic;
laterAssistant={dataset:{messageId:'23'},
  closest(selector){return selector==='.row.therapist'?{}:null;},
  querySelector(){return null;}};
if(schemaV5ChatStateComposerBindingFor(card)!==null)
  throw new Error('detached non-latest prompt opened composer');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_v5_projection_never_regresses_completed_prompt(self):
        helpers = self._between(
            "function schemaV4ProjectionOrder(",
            "function schemaV4FieldDomId(")
        program = r"""
const schemaPathDashboard={};
""" + helpers + r"""
const path='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const current={active_path:{public_id:path,revision:8},revision:8,
  next_card:{path_public_id:path,revision:8,
    checkpoint:{seq:6},prompt_delivery:{request_id:'prompt-request-0001',
      status:'completed'}}};
const queued={active_path:{public_id:path,revision:8},revision:8,
  next_card:{path_public_id:path,revision:8,
    checkpoint:{seq:6},prompt_delivery:{request_id:'prompt-request-0001',
      status:'running'}}};
if(!schemaV4ProjectionIsStale(queued,current))
  throw new Error('completed prompt regressed to running');
const swapped={...queued,next_card:{...queued.next_card,
  prompt_delivery:{request_id:'prompt-request-0002',status:'completed'}}};
if(!schemaV4ProjectionIsStale(swapped,current))
  throw new Error('same checkpoint changed prompt identity');
const next={active_path:{public_id:path,revision:8},revision:8,
  next_card:{path_public_id:path,revision:8,
    checkpoint:{seq:7},prompt_delivery:{request_id:'prompt-request-0003',
      status:'queued'}}};
if(schemaV4ProjectionIsStale(next,current))
  throw new Error('newer checkpoint was rejected');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_v4_direct_controls_pin_exact_path_public_identity(self):
        mutation = self._between(
            "function schemaV4SourceFields(",
            "function schemaV4ErrorMessage(")
        program = r"""
const SCHEMA_V4_MAP_ACTIONS=new Set([
  'undo_map_update','make_map_update_private','edit_map_update']);
const SCHEMA_V4_SOURCE_ACTIONS=new Set([]);
const SCHEMA_V4_TECHNIQUE_ACTIONS=new Set(['ground_chat_technique']);
const schemaPathDashboard={active_path:{id:9,
  public_id:'33333333333333333333333333333333'},step:'imagery_work'};
const convId=1;
function schemaPathId(){return 9;}
function structuredRequestId(){return 'schema-card-fixture-0001';}
function schemaV4CardRevision(){return 13;}
function schemaV4StructuredPayload(_name,payload,values){
  return {...(payload||{}),...(values||{})};
}
function schemaV4TechniqueLink(){return null;}
""" + mutation + r"""
const pause=schemaV4MutationPayload(
  {action:'pause',payload:{}},{path_id:9,revision:13},{});
if(pause.path_public_id!=='33333333333333333333333333333333')
  throw new Error('pause public lineage missing');
const ground=schemaV4MutationPayload({action:'ground_chat_technique',payload:{
  step_id:'imagery_work',technique_link_id:5,
  technique_link_public_id:'55555555555555555555555555555555',
  expected_technique_revision:3,control_only:true}},
  {path_id:9,revision:13},{});
if(ground.path_public_id!==pause.path_public_id||
   ground.control_only!==true||ground.intensity!==undefined)
  throw new Error('ground request drifted');
const mismatch=schemaV4MutationPayload({action:'stop',payload:{}},
  {path_id:9,path_public_id:'44444444444444444444444444444444',
   revision:13},{});
if(mismatch.path_public_id!=='')
  throw new Error('mismatched public lineage accepted');
const pathless=schemaV4MutationPayload({action:'edit_map_update',payload:{
  meta_event_id:51,meta_event_public_id:
    '22222222222222222222222222222222'}},
  {path_id:null,path_public_id:''},{note:'not'});
if(Object.prototype.hasOwnProperty.call(pathless,'path_public_id'))
  throw new Error('pathless map gained path lineage');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        sender = self._between(
            "async function postSchemaV4CardAction(",
            "function setSchemaV4CardStatus(")
        self.assertIn("payload.path_public_id", sender)
        self.assertIn("^[a-f0-9]{32}$", sender)

    def test_schema_v4_request_projection_executes_with_typed_values(self):
        compact = self._between(
            "function compactSchemaBinding(",
            "function compactRecoveredChatDraft(")
        structured = self._between(
            "function schemaV4StructuredPayload(",
            "function schemaV4SourceFields(")
        initial = self._between(
            "function schemaV4FieldInitialValue(",
            "function schemaV4FieldControl(")
        program = compact + structured + initial + r"""
const binding=compactSchemaBinding({path_id:9,step_id:'imagery_work',
  protocol:'schema_path_chat_v4',step_data:{orientation_ok:true,intensity:3},
  expected_revision:12,technique_link_id:5,
  technique_link_public_id:'55555555555555555555555555555555',
  expected_technique_revision:3});
if(JSON.stringify(binding)!==JSON.stringify({protocol:'schema_path_chat_v4',
  path_id:9,step_id:'imagery_work',expected_revision:12,technique_link_id:5,
  technique_link_public_id:'55555555555555555555555555555555',
  expected_technique_revision:3,
  step_data:{orientation_ok:true,intensity:3}}))throw new Error('binding');
const start=schemaV4StructuredPayload('start_chat_technique',
  {candidate_queue_public_id:'stable'}, {method_id:'method',
  orientation_confirmed:true,reality_clear:true,
  sleep_activation_clear:true,intensity:4,support_available:false,
  stop_signal:'dur'});
if(start.candidate_queue_public_id!=='stable'||start.method_id!=='method'||
   start.support_available!==false||start.intensity!==4||start.precheck)
  throw new Error('precheck');
const submit=schemaV4StructuredPayload('submit_chat_technique',{},
  {content:'metin',intensity:3,choice:'çocuk'});
if(submit.content!=='metin'||submit.intensity!==3||
   submit.step_data.choice!=='çocuk'||submit.choice!==undefined)
  throw new Error('technique');
const baseline=schemaV4FieldInitialValue({actions:[{payload:{
  baseline_burden:7}}]},'baseline_burden',{});
if(baseline!==undefined)throw new Error('baseline');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_v4_chat_only_binding_round_trips_exactly_without_step_data(self):
        compact = self._between(
            "function compactSchemaBinding(",
            "function compactRecoveredChatDraft(")
        program = compact + r"""
const raw={protocol:'schema_path_chat_v4',path_id:9,
  path_public_id:'99999999999999999999999999999999',
  step_id:'origin_or_unknown',expected_revision:12,
  checkpoint_public_id:'77777777777777777777777777777777',
  expected_checkpoint_seq:4,
  source_user_message_id:101,
  source_user_message_public_id:'11111111111111111111111111111111',
  source_assistant_message_id:102,
  source_assistant_message_public_id:'22222222222222222222222222222222'};
const binding=compactSchemaBinding(raw);
if(!binding||binding.path_public_id!==raw.path_public_id||
   binding.checkpoint_public_id!==raw.checkpoint_public_id||
   binding.expected_checkpoint_seq!==4||
   binding.source_user_message_id!==101||
   binding.source_assistant_message_id!==102||
   Object.prototype.hasOwnProperty.call(binding,'step_data'))
  throw new Error('chat-only binding');
if(compactSchemaBinding({...raw,step_data:{age:7}})!==null)
  throw new Error('step_data leaked');
if(compactSchemaBinding({...raw,source_assistant_message_id:0})!==null)
  throw new Error('source was not pinned');
if(compactSchemaBinding({...raw,expected_checkpoint_seq:'4'})!==null||
   compactSchemaBinding({...raw,checkpoint_public_id:''})!==null)
  throw new Error('checkpoint was not pinned');
if(compactSchemaBinding({...raw,
   source_user_message_public_id:''})!==null)
  throw new Error('public source was not pinned');
if(compactSchemaBinding({...raw,path_id:'9'})!==null||
   compactSchemaBinding({...raw,source_user_message_id:'101'})!==null)
  throw new Error('non-canonical numeric source accepted');
const technique=compactSchemaBinding({...raw,technique_link_id:5,
  technique_link_public_id:'55555555555555555555555555555555',
  expected_technique_revision:3});
if(!technique||technique.technique_link_id!==5||
   technique.expected_technique_revision!==3)
  throw new Error('technique source was not pinned');
if(compactSchemaBinding({...raw,technique_link_id:5})!==null)
  throw new Error('partial technique source was accepted');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_v4_radio_types_and_untouched_range_execute(self):
        typed = self._between(
            "function schemaV4ScalarEncoding(",
            "function schemaV4MarkFieldTouched(")
        reader = self._between(
            "function schemaV4ReadFieldValues(",
            "function schemaV4FieldDraft(")
        program = typed + "\nconst SCHEMA_V4_TRUE_GATE_FIELDS=new Set([" \
            "'orientation_ok','reality_clear']);\n" + reader + r"""
function radio(field,value){return {type:'radio',checked:true,required:true,
  dataset:{schemaFieldId:field,schemaTypedValue:JSON.stringify(value),
    schemaTouched:'true'},setCustomValidity(){},reportValidity(){}};}
function box(items){return {querySelector(){return null;},
  querySelectorAll(){return items;}};}
const keepGoing=schemaV4ReadFieldValues(box([
  radio('continue_ladder',false)]),{report:false});
if(keepGoing.continue_ladder!==false)throw new Error('bool false');
const participant=schemaV4ReadFieldValues(box([
  radio('participant_id',2)]),{report:false});
if(participant.participant_id!==2||typeof participant.participant_id!=='number')
  throw new Error('numeric radio');
const support=schemaV4ReadFieldValues(box([
  radio('support_available',false)]),{report:false});
if(support.support_available!==false)throw new Error('support false');
const range={type:'range',required:true,value:'5',
  dataset:{schemaFieldId:'intensity',schemaTouched:'false'},
  checkValidity(){return true;},setCustomValidity(){},reportValidity(){}};
if(schemaV4ReadFieldValues(box([range]),{report:false})!==null)
  throw new Error('untouched range');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_v4_bound_primary_is_hidden_chat_only_and_failure_is_durable(self):
        renderer = self._between(
            "function renderSchemaChatOnlyCard(",
            "function renderSchemaV4ActiveCard(")
        for hidden in (
                "cardNode.hidden=true", "schemaStepProgress",
                "schemaStepSource", "schemaClinicalSyncNotice",
                "schemaStepFields", "schemaStepActions"):
            self.assertIn(hidden, renderer)
        self.assertIn("kind==='candidate_prompt'", renderer)
        self.assertIn("schemaProtocolV5()&&kind==='chat_state'", renderer)
        self.assertIn("schemaV5PromptDeliveryFor(card)", renderer)
        self.assertIn("schemaComposerMode='disabled'", renderer)
        self.assertIn("syncSchemaV4ComposerBinding(card)", renderer)
        self.assertIn("syncSchemaV5PromptState(card)", renderer)
        self.assertNotIn("card.body", renderer)
        self.assertNotIn("card.actions", renderer)
        self.assertNotIn("schemaV4FieldControl", renderer)

        binding = self._between(
            "function schemaV4ChatOnlyComposerBindingFor(",
            "function schemaV4ComposerBindingFor(")
        for pin in ("path_public_id", "source_user_message_id",
                    "source_assistant_message_id",
                    "source_user_message_public_id",
                    "source_assistant_message_public_id", "ordinary_chat",
                    "inline_controls_only"):
            self.assertIn(pin, binding)
        self.assertIn("card.chat_binding", binding)
        self.assertIn("schemaV4TechniqueLink(stepId)", binding)
        self.assertIn("binding.technique_link_public_id", binding)
        compact = self._between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        program = compact + "\n" + binding + r"""
const schemaPathDashboard={interaction_policy:{
  composer_surface:'ordinary_chat',inline_controls_only:true,
  composer_mode:'bound',composer_allowed:true,
  composer_binding_required:true,bound_step_id:'imagery_work'},
  active_path:{id:9,public_id:'99999999999999999999999999999999',
    revision:12,method_id:'young:method:imagery-rescripting'}};
function schemaChatOnlyCard(){return true;}
function schemaProtocolV5(){return false;}
function schemaPathId(){return 9;}
function schemaV4CardRevision(){return 12;}
let activeLink=null;
function schemaV4TechniqueLink(){return activeLink;}
const source={user_message_id:101,
  user_message_public_id:'11111111111111111111111111111111',
  assistant_message_id:102,
  assistant_message_public_id:'22222222222222222222222222222222'};
const wire={protocol:'schema_path_chat_v4',path_id:9,
  path_public_id:schemaPathDashboard.active_path.public_id,
  step_id:'imagery_work',expected_revision:12,
  checkpoint_public_id:'77777777777777777777777777777777',
  expected_checkpoint_seq:4,
  source_user_message_id:101,
  source_user_message_public_id:source.user_message_public_id,
  source_assistant_message_id:102,
  source_assistant_message_public_id:source.assistant_message_public_id};
const card={kind:'chat_prompt',status:'active',fields:[],path_id:9,
  path_public_id:schemaPathDashboard.active_path.public_id,
  step:'imagery_work',revision:12,source,chat_binding:wire,
  checkpoint:{public_id:wire.checkpoint_public_id,seq:4,
    prompt_key:'technique_turn',method_id:'young:method:imagery-rescripting',
    status:'active',can_backtrack:true,backtrack_pending:false,
    pending_target_public_id:null}};
if(!schemaV4ChatOnlyComposerBindingFor(card))
  throw new Error('exact hidden binding rejected');
card.checkpoint={...card.checkpoint,seq:3};
if(schemaV4ChatOnlyComposerBindingFor(card)!==null)
  throw new Error('stale checkpoint accepted');
card.checkpoint={...card.checkpoint,seq:4};
card.source={...source,assistant_message_public_id:
  'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'};
if(schemaV4ChatOnlyComposerBindingFor(card)!==null)
  throw new Error('mismatched public source accepted');
card.source=source;
activeLink={id:5,public_id:'55555555555555555555555555555555',
  technique_revision:3};
if(schemaV4ChatOnlyComposerBindingFor(card)!==null)
  throw new Error('missing active technique pin accepted');
card.chat_binding={...wire,technique_link_id:5,
  technique_link_public_id:activeLink.public_id,
  expected_technique_revision:3};
if(!schemaV4ChatOnlyComposerBindingFor(card))
  throw new Error('exact active technique pin rejected');

activeLink=null;
const setStep=(step,checkpointMethod,pathMethod)=>{
  schemaPathDashboard.interaction_policy.bound_step_id=step;
  schemaPathDashboard.active_path.method_id=pathMethod;
  card.step=step;card.chat_binding={...wire,step_id:step};
  card.checkpoint={...card.checkpoint,method_id:checkpointMethod};
};
setStep('method_select',null,null);
if(!schemaV4ChatOnlyComposerBindingFor(card))
  throw new Error('method selection prompt rejected');
setStep('method_confirm','young:method:chair-dialogue',null);
if(!schemaV4ChatOnlyComposerBindingFor(card))
  throw new Error('explicit method confirmation prompt rejected');
setStep('method_confirm',null,null);
if(schemaV4ChatOnlyComposerBindingFor(card)!==null)
  throw new Error('confirmation opened without proposal');
setStep('origin_or_unknown','young:method:chair-dialogue',null);
if(schemaV4ChatOnlyComposerBindingFor(card)!==null)
  throw new Error('origin opened before method confirmation');
setStep('origin_or_unknown','young:method:chair-dialogue',
  'young:method:chair-dialogue');
if(!schemaV4ChatOnlyComposerBindingFor(card))
  throw new Error('confirmed method branch rejected');
setStep('origin_or_unknown','young:method:unknown',
  'young:method:unknown');
if(schemaV4ChatOnlyComposerBindingFor(card)!==null)
  throw new Error('unknown method lineage accepted');
"""
        result = subprocess.run(
            ["node", "-e", program], capture_output=True,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        sender = self._between(
            "async function send(", "/* ---------------- seans bitir")
        self.assertIn("schemaV4ComposerBindingFor(card,{report:true})", sender)
        self.assertIn("renderSchemaBindingResult(userBubble", sender)
        message_renderer = self._between(
            "function renderConversationMessage(",
            "function setBubbleContent(")
        self.assertIn("m.schema_binding_result", message_renderer)
        result = self._between(
            "function renderSchemaBindingResult(",
            "function renderConversationMessage(")
        self.assertIn("schemaChatBindingNotice", result)
        self.assertNotIn("Güncel kartı aç", result[
            result.index("if(schemaChatOnlyPresentation())"):
            result.index("compactExisting?.remove();")])

    def test_schema_v4_hidden_binding_draft_and_policy_fail_closed(self):
        drafts = self._between(
            "function conversationDraftPayload()",
            "function mobileChatViewport()")
        self.assertIn("schema_binding:compactSchemaBinding", drafts)
        self.assertIn("schemaComposerBinding=compactSchemaBinding", drafts)
        compact = self._between(
            "function compactSchemaBinding(",
            "function schemaJsonValueSafe(")
        self.assertIn("result.path_public_id", compact)
        self.assertIn("result.source_user_message_id", compact)
        self.assertIn("result.source_assistant_message_id", compact)
        self.assertIn("Object.keys(rawStepData).length", compact)
        policy = self._between(
            "function schemaV4PolicyMode(",
            "function schemaV4BoundAction(")
        self.assertIn("composer_allowed!==true", policy)
        self.assertIn("composer_allowed!==false", policy)
        self.assertIn("return 'disabled'", policy)

    def test_schema_v4_privacy_and_clinical_sync_are_independent(self):
        projection = self._between(
            "function applySchemaInteractionPrivacy(",
            "function schemaV4MetaKey(")
        self.assertIn("policy.requires_in_app===true", projection)
        self.assertIn("purgeSensitiveNativeNotifications", projection)
        sync = self._between(
            "async function setSchemaClinicalSync(",
            "function schemaHistoryJobPending(")
        self.assertIn("set_clinical_sync", sync)
        self.assertIn("confirmed:true", sync)
        self.assertNotIn("provider_id", sync)
        post = self._between(
            "async function postSchemaPath(",
            "function resetSchemaTurnUi(")
        self.assertIn("'set_clinical_sync'", post)
        self.assertIn("Bu çalışma yalnız bu cihazda tutuluyor",
                      self.structured_script)
        self.assertIn("device_confirmation_required",
                      self.structured_script)
        self.assertIn("clinical_sync", self.structured_script)
        self.assertIn("schemaClinicalSyncInlineToggle",
                      self.structured_script)
        chat_renderer = self._between(
            "function renderSchemaChatOnlyCandidate(",
            "function renderSchemaV4ActiveCard(")
        self.assertNotIn("schemaClinicalSyncInlineToggle", chat_renderer)
        self.assertNotIn("setSchemaClinicalSync", chat_renderer)

    def test_schema_v4_chat_only_keeps_chat_clean_and_tools_history_read_only(self):
        workspace = self._between(
            "function renderSchemaPathWorkspace(",
            "document.addEventListener('divan:techniquechange'")
        chat_branch = workspace[
            workspace.index("if(schemaChatOnlyPresentation())"):
            workspace.index("if(schemaProtocolV4())")]
        self.assertIn("$('schemaPathSteps').hidden=true", chat_branch)
        self.assertIn("$('schemaV4Details').hidden=false", chat_branch)
        self.assertIn("salt okunur geçmişini", chat_branch)
        self.assertIn("schemaV4DetailsProgress", chat_branch)
        self.assertNotIn("hideOverlay('schemaPathOverlay')", chat_branch)
        show = self._between(
            "async function showSchemaPathWorkspace(",
            "let schemaChatDashboardConv=")
        self.assertLess(show.index("await loadSchemaPathDashboard"),
                        show.index("if(schemaChatOnlyPresentation())"))
        chat_show = show[
            show.index("if(schemaChatOnlyPresentation())"):
            show.index("if(androidNativeMobileContext())")]
        self.assertIn("renderSchemaPathWorkspace()", chat_show)
        self.assertIn("showOverlay('schemaPathOverlay'", chat_show)
        self.assertNotIn("renderSchemaStepCard", chat_show)
        meta = self._between(
            "function schemaV4MetaCard(",
            "function renderSchemaMessageMetaEvents(")
        self.assertIn("['technique','map_update']", meta)
        self.assertNotIn("['technique','map_update','progress']", meta)
        self.assertIn('@media(max-height:570px) and (orientation:landscape)',
                      self.html)
        self.assertIn("min-height:44px", self.html)
        self.assertIn('role="status" aria-live="polite"',
                      self.schema_markup)

    def test_suggestion_comes_with_the_reply_not_a_second_call(self):
        """Öneri için ayrı model isteği atılmaz.

        İkinci istek sohbet yanıtıyla aynı anda sağlayıcıya gidiyor,
        hız sınırına takılıyor ve kullanıcı beklerken hata görüyordu.
        """
        auto = self._between(
            "function autoAnalyzeSchemaTurns",
            "async function analyzeSchemaUserMessage")
        # Otomatik ikinci çağrı gövdesi boş: istek atılmıyor.
        self.assertNotIn("analyzeSchemaUserMessage(", auto)
        self.assertNotIn("api(", auto)
        # Elle inceleme yolu duruyor ve onayını koruyor.
        self.assertIn("analyze_turn", self.structured_script)

    def test_active_path_locks_and_queues_other_candidates(self):
        self.assertIn(
            "Bu çalışma bitince diğerlerini başka görüşmede ele alacağız.",
            self.structured_script)
        self.assertIn("const locked=!!schemaPathId()", self.structured_script)
        self.assertIn("queued_candidates", self.structured_script)
        self.assertIn("active_path_notice", self.structured_script)
        self.assertIn("postSchemaPath('start',{claim_id:claimId}",
                      self.structured_script)

    def test_single_completed_user_turn_has_accessible_explicit_analysis(self):
        for copy in (
                "Şema ve harita için incele",
                "Şema ve harita için incelendi",
                "Kullanıcı mesajı işlemleri"):
            self.assertIn(copy, self.structured_script)
        self.assertIn("schemaUserBubbleHasCompletedPair(bubble)",
                      self.structured_script)
        self.assertIn(".row.user .bubble", self.structured_script)
        self.assertIn(".row.therapist", self.structured_script)
        self.assertIn("action:'analyze_turn'", self.structured_script)
        self.assertIn("user_message_id:id", self.structured_script)
        self.assertIn("consent:true,...provider", self.structured_script)
        self.assertIn("processing_user_message_ids", self.structured_script)
        self.assertIn("schemaTurnAnalyzedMessageIds.has(id)",
                      self.structured_script)
        self.assertIn("bindMessageActionDisclosure(bubble,tools)",
                      self.structured_script)
        self.assertIn("setOpenMessageActionsBubble(null)",
                      self.structured_script)

    def test_schema_history_scans_completed_turns_with_progress_and_retry(self):
        for element_id in (
                "schemaHistoryCoverage", "schemaHistoryConsentInput",
                "schemaHistoryStart", "schemaHistoryRetry",
                "schemaHistoryProgressBar"):
            self.assertIn(f'id="{element_id}"', self.schema_markup)
        for action in ("scan_history", "retry_scan"):
            self.assertIn("postSchemaPath('" + action, self.structured_script)
        for field in (
                "eligible_turns", "analyzed_turns", "remaining_turns",
                "failed_turns", "safety_skipped_turns"):
            self.assertIn("analysis." + field, self.structured_script)
        self.assertIn("provider_id:providerId,model_id:modelId",
                      self.structured_script)
        self.assertIn("tamamlanmış mesaj çiftinin", self.structured_script)
        self.assertIn("tur tur gönderileceğini", self.structured_script)
        self.assertRegex(
            self.html,
            r"\.guidedConsent\[hidden\][^\{]*\{\s*display:none!important")

    def test_schema_gates_private_partial_guest_ended_and_safety(self):
        self.assertIn("!convData.ended&&!convData.archived_at",
                      self.structured_script)
        self.assertIn("!convData.is_guest", self.structured_script)
        self.assertIn("!convData.safety_hold", self.structured_script)
        self.assertIn("candidate.completed_pair===false",
                      self.structured_script)
        self.assertIn("['private','excluded']", self.structured_script)
        self.assertIn("['partial','incomplete','streaming','failed']",
                      self.structured_script)
        self.assertIn("clearSchemaTurnMessageActions()",
                      self.structured_script)

    def test_schema_turn_cards_reflow_at_small_zoomed_and_landscape_sizes(self):
        self.assertRegex(
            self.html,
            r"\.schemaTurnActions button\s*\{[^}]*min-height:48px")
        self.assertRegex(
            self.html,
            r"@media\(max-width:360px\)[\s\S]*?"
            r"\.schemaTurnActions\s*\{grid-template-columns:1fr\}")
        self.assertRegex(
            self.html,
            r"@media\(orientation:landscape\) and \(max-height:420px\)"
            r"[\s\S]*?\.schemaTurnActions\s*\{grid-template-columns:"
            r"repeat\(3,minmax\(0,1fr\)\)\}")
        self.assertIn("calc(11px * var(--fs))", self.html)

    def test_schema_origin_is_optional_and_advance_is_server_gated(self):
        self.assertIn('Geçmişe gitmek isteğe bağlıdır', self.schema_markup)
        self.assertIn('id="schemaSkipOrigin"', self.schema_markup)
        self.assertIn("kind:'skip_origin'", self.structured_script)
        self.assertIn("if(schemaActionAllowed('advance'))",
                      self.structured_script)
        # Araştırmadan sonra doğrudan yönteme değil, önce odak seçimine
        # geçilir: üzerinde çalışılacak modu kullanıcı seçer.
        self.assertIn("postSchemaPath('advance',{to_phase:'focus'}",
                      self.structured_script)
        self.assertIn("focus:['method','Yöntemlere bak']",
                      self.structured_script)
        self.assertIn("function renderSchemaPhaseActions",
                      self.structured_script)
        self.assertIn("practice:['followup','Takibe geç']",
                      self.structured_script)
        self.assertIn('await loadSchemaPathDashboard()', self.structured_script)

    def test_enhanced_schema_methods_are_blocked_by_precheck(self):
        for key in (
                "orientation_confirmed", "reality_clear",
                "sleep_activation_clear", "intensity", "support_available",
                "stop_signal"):
            self.assertIn(key, self.structured_script)
        self.assertIn("const unsafe=enhanced&&(reality==='no'||sleep==='no')",
                      self.structured_script)
        self.assertIn(
            "$('schemaMethodChoiceContinue').disabled=unsafe||!complete",
            self.structured_script)
        self.assertIn('gerçek bir ruh sağlığı uzmanına ulaşın',
                      self.schema_markup)
        self.assertIn("fields.precheck={", self.structured_script)
        self.assertIn("confirmed:true", self.structured_script)
        self.assertIn("method.node_id!==undefined?method.node_id",
                      self.structured_script)
        self.assertIn('openMethodConsent(catalogMethod)',
                      self.structured_script)
        self.assertIn("action==='stop'\n    ?structuredWorkspaceIdentity('young')",
                      self.structured_script)

    def test_schema_practice_is_opt_in_single_variable_and_no_notification(self):
        self.assertIn('Değiştireceğim tek şey', self.schema_markup)
        self.assertIn('id="schemaPracticeConsent"', self.schema_markup)
        self.assertIn('id="schemaPracticeSave" disabled', self.schema_markup)
        self.assertIn('id="schemaPracticeSkip"', self.schema_markup)
        practice = self.structured_script[
            self.structured_script.index('async function saveSchemaPractice'):
            self.structured_script.index('async function skipSchemaPractice')]
        self.assertIn("postSchemaPath('assign_practice'", practice)
        self.assertIn('target_per_week', practice)
        self.assertNotIn('/api/reminders', practice)
        self.assertNotIn('scheduleReminderNotificationFor', practice)
        self.assertIn("kind:'skip_practice',value:'selected'",
                      self.structured_script)
        self.assertIn('id="schemaPracticeFrequency" type="number" min="1" '
                      'max="5"', self.schema_markup)
        self.assertIn("$('schemaWorkForm').addEventListener('submit',"
                      "saveSchemaWork)", self.html)

    def test_chat_card_actions_preserve_viewport_without_forced_smooth_scroll(self):
        focus = self._between(
            "function focusSchemaChatOnlyInteraction(",
            "function renderSchemaChatOnlyCard(",
        )
        self.assertIn("revealChatElementNearest(", focus)
        self.assertNotIn("scrollIntoView(", focus)

        post = self._between(
            "async function postSchemaPath(",
            "function resetSchemaTurnUi(",
        )
        self.assertIn("captureChatViewportAnchor(document.activeElement)", post)
        self.assertIn("restoreChatViewportAnchor(viewportAnchor)", post)

        card_post = self._between(
            "async function postSchemaV4CardAction(",
            "function setSchemaV4CardStatus(",
        )
        self.assertIn("captureChatViewportAnchor(activeCard", card_post)
        self.assertIn("restoreChatViewportAnchor(viewportAnchor)", card_post)

        dashboard = self._between(
            "async function loadSchemaPathDashboard(",
            "async function postSchemaPath(",
        )
        self.assertIn("const captureBackgroundViewport=()=>{", dashboard)
        self.assertIn("viewportAnchor=captureChatViewportAnchor(", dashboard)
        self.assertGreaterEqual(dashboard.count("captureBackgroundViewport()"),
                                2)
        self.assertIn("restoreChatViewportAnchor(viewportAnchor)", dashboard)

        suggestion = self._between(
            "function renderAdhdConversationSuggestion(",
            "async function refreshAdhdConversationSuggestion(",
        )
        self.assertLess(suggestion.index("const wasNearBottom=chatIsNearBottom()"),
                        suggestion.index(
                            "clearAdhdConversationPrompt({preserveViewport:false})"))
        self.assertIn("restoreChatViewportAnchor(viewportAnchor)", suggestion)
        self.assertIn("if(!replacingPrompt&&wasNearBottom)", suggestion)

        helpers = self._between(
            "function captureChatViewportAnchor(",
            "function createChatRequestId(",
        )
        self.assertIn("chat.style.overflowAnchor='none'", helpers)
        self.assertIn("chat.style.scrollBehavior='auto'", helpers)
        self.assertIn("function revealChatElementNearest(", helpers)

    def test_full_screen_responsive_keyboard_and_touch_contract(self):
        self.assertIn('@media(max-width:760px)', self.html)
        self.assertIn('height:var(--mobile-vvh,100dvh)', self.html)
        self.assertIn('@media(max-width:360px)', self.html)
        self.assertIn('@media(orientation:landscape) and (max-height:420px)',
                      self.html)
        self.assertRegex(
            self.html,
            r'\.guidedPrimaryButton[^\{]*\{[^}]*min-height:44px')
        self.assertIn('calc(12px * var(--fs))', self.html)
        self.assertIn('role="tablist"', self.adhd_markup)
        self.assertIn("event.key==='ArrowLeft'", self.html)
        self.assertIn("requestOverlayDismiss('adhdWorkspaceOverlay')",
                      self.html)
        self.assertIn("requestOverlayDismiss('schemaPathOverlay')",
                      self.html)

    def test_embedded_javascript_parses(self):
        scripts = re.findall(r'<script>(.*?)</script>', self.html, re.S)
        self.assertTrue(scripts)
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", encoding="utf-8") as handle:
            handle.write("\n".join(scripts))
            handle.flush()
            result = subprocess.run(
                ["node", "--check", handle.name], capture_output=True,
                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
