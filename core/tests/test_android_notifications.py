from pathlib import Path
import unittest

from support import PROJECT_DIR


class AndroidNotificationSourceContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.android = Path(PROJECT_DIR).parent / "divan-android"
        cls.java_root = (
            cls.android / "app/src/main/java/com/furkancanyilmaz/divan"
        )
        cls.main = (cls.java_root / "MainActivity.java").read_text()
        cls.preferences = (
            cls.java_root / "NotificationPreferences.java").read_text()
        cls.completion = (
            cls.java_root / "CompletionNotificationController.java"
        ).read_text()
        cls.conversation_support = (
            cls.java_root / "ConversationNotificationSupport.java"
        ).read_text()
        cls.ledger = (
            cls.java_root / "NotificationDeliveryLedger.java").read_text()
        cls.chat = (
            cls.java_root / "ChatNotificationController.java").read_text()
        cls.reply = (
            cls.java_root / "ChatReplyReceiver.java").read_text()
        cls.reply_outbox = (
            cls.java_root / "NotificationReplyOutbox.java").read_text()
        cls.reply_outbox_job = (
            cls.java_root / "NotificationReplyOutboxJobService.java"
        ).read_text()
        cls.application = (
            cls.java_root / "DivanApplication.java").read_text()
        cls.boot = (
            cls.java_root / "BootReminderRescheduler.java").read_text()
        cls.reminder = (
            cls.java_root / "ReminderReceiver.java").read_text()
        cls.keeper = (
            cls.java_root / "ResponseKeeperJobService.java").read_text()
        cls.local_api = (
            cls.java_root / "DivanLocalApi.java").read_text()
        cls.text_sanitizer = (
            cls.java_root / "NotificationTextSanitizer.java").read_text()
        cls.manifest = (
            cls.android / "app/src/main/AndroidManifest.xml"
        ).read_text()
        cls.gradle = (cls.android / "app/build.gradle.kts").read_text()
        cls.html = Path(PROJECT_DIR, "index.html").read_text()

    def test_completion_requires_opt_in_and_preview_is_separate(self):
        self.assertIn('getBoolean(COMPLETION_KEY, false)', self.preferences)
        self.assertIn('getBoolean(PREVIEW_KEY, false)', self.preferences)
        self.assertIn('getBoolean(\n                        INLINE_REPLY_KEY, false)',
                      self.preferences)
        self.assertIn('!NotificationPreferences.completionEnabled(context)',
                      self.completion)
        self.assertIn('NotificationPreferences.previewsEnabled(context)',
                      self.completion)
        self.assertIn('preview_allowed', self.completion)
        self.assertIn('&allow_preview=', self.completion)
        self.assertIn('NotificationTextSanitizer.plainAssistantText(',
                      self.completion)
        self.assertIn('NotificationCompat.MessagingStyle',
                      self.conversation_support)
        self.assertIn('.addMessage(new NotificationCompat.MessagingStyle',
                      self.conversation_support)
        self.assertNotIn('MAX_PREVIEW_CHARS', self.completion)
        self.assertNotIn('substring(0, MAX_PREVIEW', self.completion)
        self.assertIn('id="notificationPreviewToggle"', self.html)
        self.assertIn("notificationPreviewsEnabled", self.html)

    def test_outbox_is_bounded_request_based_and_ack_follows_notify(self):
        self.assertIn('/api/notification-contexts?after_sequence=',
                      self.completion)
        self.assertIn('MAX_DELIVERED_IDS = 96', self.ledger)
        self.assertIn('List<String> requestIds', self.completion)
        self.assertIn('"cancelled".equals(', self.completion)
        self.assertIn('|| NotificationDeliveryLedger.wasDelivered(',
                      self.completion)
        notify_at = self.completion.index('.postIfPrivacyStateCurrent(')
        ack_at = self.completion.index('NotificationDeliveryLedger.mark(',
                                       notify_at)
        self.assertLess(notify_at, ack_at)
        self.assertIn('CompletionNotificationController.deliverPending(',
                      self.keeper)
        self.assertNotIn('/api/notification-context"', self.keeper)

    def test_inline_reply_is_separate_idempotent_and_fail_closed(self):
        self.assertNotIn('MessagingStyle', self.chat)
        self.assertIn('androidx.core.app.RemoteInput', self.chat)
        self.assertIn('.addRemoteInput(remoteInput)', self.chat)
        self.assertIn('NotificationPreferences.inlineReplyEnabled(context)',
                      self.chat)
        self.assertIn('PendingIntent.FLAG_MUTABLE', self.chat)
        self.assertIn('PendingIntent.FLAG_ONE_SHOT', self.chat)
        self.assertIn('.setAuthenticationRequired(true)', self.chat)
        self.assertIn('ACTION_INLINE_REPLY', self.chat)
        self.assertIn('inlineReplyRequestId(', self.chat)
        self.assertIn('NotificationReplyOutbox.prepare(context)', self.chat)
        self.assertIn('reply_allowed', self.completion)
        self.assertIn('message_id', self.completion)
        self.assertNotIn('responseText.trim()', self.chat)
        self.assertNotIn('userText.trim()', self.chat)
        self.assertIn('RemoteInput.getResultsFromIntent', self.reply)
        self.assertIn('intent.setClipData(null)', self.reply)
        self.assertIn('NotificationReplyOutbox.enqueue(', self.reply)
        self.assertIn('NotificationReplyOutboxJobService.schedule(app)',
                      self.reply)
        self.assertIn('goAsync()', self.reply)
        self.assertIn('RECEIVER_FINISH_MS = 8_500L', self.reply)
        self.assertNotIn('DivanLocalApi', self.reply)
        self.assertNotIn('/api/notification-reply', self.reply)
        self.assertNotIn('com.chaquo.python', self.reply)
        self.assertNotIn('/api/chat-status', self.reply)
        self.assertNotIn('Thread.sleep', self.reply)
        self.assertNotIn('run_chat_request', self.reply)
        enqueue_at = self.reply.index('NotificationReplyOutbox.enqueue(')
        cancel_at = self.reply.index(
            'ChatNotificationController.cancelNotification(', enqueue_at)
        self.assertLess(enqueue_at, cancel_at)
        self.assertIn('setPublicVersion(', self.chat)
        self.assertIn('setPublicVersion(', self.completion)

        self.assertIn('notificationInlineReplyEnabled()', self.main)
        self.assertIn('notificationInlineReplyAvailable()', self.main)
        self.assertIn('setNotificationInlineReplyEnabled(boolean enabled)',
                      self.main)

    def test_schema_in_app_policy_disables_preview_and_remote_input(self):
        rich = self.completion[
            self.completion.index(
                'private static boolean canShowRichPreview('):
            self.completion.index(
                'private static int activeConversationCount(')]
        inline = self.completion[
            self.completion.index(
                'private static void addInlineReplyIfAllowed('):
            self.completion.index(
                'static PendingIntent openIntent(')]
        self.assertIn('item.optBoolean("requires_in_app", false)', rich)
        self.assertIn('item.optBoolean("requires_in_app", false)', inline)
        self.assertLess(
            rich.index('requires_in_app'), rich.index('preview_allowed'))
        self.assertLess(
            inline.index('requires_in_app'), inline.index('reply_allowed'))
        # İçeriksiz nötr bildirim kalabilir; hiçbir uygulama dışı yanıt
        # veya asistan metni bu zorunlu kapıyı aşamaz.
        self.assertNotIn('inlineReplyActionFor', rich)

        reminder_response = self.reminder[
            self.reminder.index(
                'boolean requiresInApp = response.optBoolean('):
            self.reminder.index('privacyGeneration);',
                                self.reminder.index(
                                    'boolean requiresInApp = response.optBoolean('))]
        self.assertIn('"requires_in_app", false', reminder_response)
        self.assertGreaterEqual(reminder_response.count('&& !requiresInApp'),
                                4)
        self.assertLess(reminder_response.index('requires_in_app'),
                        reminder_response.index('reply_allowed'))
        self.assertLess(reminder_response.index('requires_in_app'),
                        reminder_response.index('preview_allowed'))

    def test_inline_reply_outbox_is_keystore_encrypted_atomic_and_private(self):
        self.assertIn('getNoBackupFilesDir()', self.reply_outbox)
        self.assertIn('AndroidKeyStore', self.reply_outbox)
        self.assertIn('divan_notification_reply_outbox_v1',
                      self.reply_outbox)
        self.assertIn('AES/GCM/NoPadding', self.reply_outbox)
        self.assertIn('IV_BYTES = 12', self.reply_outbox)
        self.assertIn('TAG_BITS = 128', self.reply_outbox)
        self.assertIn('new GCMParameterSpec(TAG_BITS, iv)',
                      self.reply_outbox)
        self.assertIn('cipher.updateAAD(aad(digest))', self.reply_outbox)
        self.assertIn('.setRandomizedEncryptionRequired(true)',
                      self.reply_outbox)
        self.assertIn('.setUserAuthenticationRequired(false)',
                      self.reply_outbox)
        self.assertIn('new AtomicFile(target)', self.reply_outbox)
        self.assertIn('output.getFD().sync()', self.reply_outbox)
        self.assertIn('MAX_RECORDS = 32', self.reply_outbox)
        self.assertIn('if (target.isFile())', self.reply_outbox)
        self.assertIn('recoverAtomicTempsLocked(directory)',
                      self.reply_outbox)
        self.assertIn('reply\\\\.new', self.reply_outbox)
        self.assertNotIn('import android.content.SharedPreferences',
                         self.reply_outbox)
        self.assertNotIn('getSharedPreferences(', self.reply_outbox)
        self.assertNotIn('android.util.Log', self.reply_outbox)
        self.assertNotIn('import android.content.Intent', self.reply_outbox)
        self.assertIn('source_notification_tag', self.reply_outbox)
        self.assertIn('record.sourceNotificationTag', self.reply_outbox_job)

    def test_inline_reply_outbox_job_retries_and_only_deletes_terminal(self):
        self.assertIn('extends JobService', self.reply_outbox_job)
        self.assertIn('.setPersisted(true)', self.reply_outbox_job)
        self.assertIn('BACKOFF_POLICY_EXPONENTIAL', self.reply_outbox_job)
        self.assertIn('/api/notification-reply', self.reply_outbox_job)
        self.assertIn('response == null || response.code >= 500',
                      self.reply_outbox_job)
        self.assertIn('response.code >= 400 && response.code < 500',
                      self.reply_outbox_job)
        self.assertIn('accepted.optBoolean("accepted", false)',
                      self.reply_outbox_job)
        self.assertIn('record.requestId.equals(', self.reply_outbox_job)
        keeper_at = self.reply_outbox_job.index(
            'ResponseKeeperJobService.schedule(')
        delete_at = self.reply_outbox_job.index(
            'NotificationReplyOutbox.delete(record.file)', keeper_at)
        self.assertLess(keeper_at, delete_at)
        self.assertNotIn('SharedPreferences', self.reply_outbox_job)
        self.assertNotIn('android.util.Log', self.reply_outbox_job)

        self.assertIn('NotificationReplyOutboxJobService.scheduleIfPending',
                      self.application)
        self.assertIn('NotificationReplyOutbox.prepare(this)',
                      self.application)
        self.assertIn('NotificationReplyOutboxJobService.scheduleIfPending',
                      self.boot)
        self.assertIn('android:name=".DivanApplication"', self.manifest)
        self.assertIn(
            'android:name=".NotificationReplyOutboxJobService"',
            self.manifest)
        service_at = self.manifest.index(
            'android:name=".NotificationReplyOutboxJobService"')
        service_tail = self.manifest[service_at:service_at + 240]
        self.assertIn('android.permission.BIND_JOB_SERVICE', service_tail)

    def test_safety_409_is_retained_encrypted_and_requires_app_confirmation(self):
        safety_at = self.reply_outbox_job.index(
            'if (isSafetyNeedsAppResponse(')
        terminal_at = self.reply_outbox_job.index(
            'return terminalReject(record);', safety_at)
        self.assertLess(safety_at, terminal_at)
        self.assertIn(
            '"bu yanıt güvenli biçimde uygulama içinde ele alınmalı"',
            self.reply_outbox_job)
        self.assertIn(
            '"güvenlik takibi olan görüşme uygulamada açılmalı"',
            self.reply_outbox_job)
        retain_at = self.reply_outbox_job.index(
            'private DrainResult retainForApp(')
        retain_end = self.reply_outbox_job.index(
            'private DrainResult terminalReject(', retain_at)
        retain_tail = self.reply_outbox_job[retain_at:retain_end]
        self.assertIn('NotificationReplyOutbox.moveToNeedsApp(record)',
                      retain_tail)
        self.assertIn('dismissPendingIfRequestMatches(', retain_tail)
        self.assertIn('ChatNotificationController.showNeedsApp(',
                      retain_tail)
        self.assertNotIn('NotificationReplyOutbox.delete(record.file)',
                         retain_tail)

        self.assertIn('NEEDS_APP_SUFFIX = ".needs_app"',
                      self.reply_outbox)
        self.assertIn('static boolean moveToNeedsApp(Record record)',
                      self.reply_outbox)
        move_at = self.reply_outbox.index(
            'static boolean moveToNeedsApp(Record record)')
        move_tail = self.reply_outbox[move_at:move_at + 4300]
        self.assertIn('output.getFD().sync()', move_tail)
        self.assertIn('Record moved = read(target)', move_tail)
        self.assertIn('return delete(source)', move_tail)
        self.assertLess(move_tail.index('output.getFD().sync()'),
                        move_tail.rindex('return delete(source)'))
        self.assertIn('static boolean consumeNeedsApp(Record expected)',
                      self.reply_outbox)
        self.assertIn('expected.requestId.equals(current.requestId)',
                      self.reply_outbox)

        self.assertIn(
            '"Yanıtınızı güvenle ele almak için Divan’ı açın"', self.chat)
        needs_at = self.chat.index('public static void showNeedsApp(')
        needs_tail = self.chat[needs_at:needs_at + 1500]
        self.assertIn('Notification.VISIBILITY_PRIVATE', needs_tail)
        self.assertIn('safeBuilder(', needs_tail)
        self.assertNotIn('masterName', needs_tail)
        self.assertNotIn('message', needs_tail)

        self.assertIn('new AlertDialog.Builder(MainActivity.this)',
                      self.main)
        self.assertIn('.setPositiveButton("Mesaj alanına taşı"',
                      self.main)
        self.assertIn('.setNegativeButton("Şimdilik kalsın", null)',
                      self.main)
        restore_at = self.main.index(
            'private void restoreNeedsAppReplyDraft(')
        restore_tail = self.main[restore_at:restore_at + 4000]
        self.assertIn("box.value=", restore_tail)
        self.assertIn("saveConversationDraft(", restore_tail)
        self.assertIn('NotificationReplyOutbox.consumeNeedsApp(record)',
                      restore_tail)
        self.assertNotIn("document.getElementById('send')", restore_tail)
        self.assertNotIn('.click()', restore_tail)

    def test_non_safety_4xx_remains_terminal_and_success_is_exact_once(self):
        response_at = self.reply_outbox_job.index(
            'if (response.code >= 400 && response.code < 500)')
        response_tail = self.reply_outbox_job[response_at:response_at + 700]
        self.assertIn('if (isSafetyNeedsAppResponse(', response_tail)
        self.assertIn('return terminalReject(record);', response_tail)
        terminal_at = self.reply_outbox_job.index(
            'private DrainResult terminalReject(')
        terminal_tail = self.reply_outbox_job[terminal_at:terminal_at + 1500]
        self.assertIn('NotificationReplyOutbox.delete(record.file)',
                      terminal_tail)

        accepted_at = self.reply_outbox_job.index(
            'accepted.optBoolean("accepted", false)')
        accepted_tail = self.reply_outbox_job[accepted_at:accepted_at + 1800]
        self.assertIn('record.requestId.equals(', accepted_tail)
        self.assertIn('ResponseKeeperJobService.schedule(', accepted_tail)
        self.assertIn('NotificationReplyOutbox.delete(record.file)',
                      accepted_tail)
        self.assertLess(accepted_tail.index(
            'ResponseKeeperJobService.schedule('), accepted_tail.index(
            'NotificationReplyOutbox.delete(record.file)'))

    def test_needs_app_state_survives_restart_without_resend_loop(self):
        self.assertIn('static List<File> needsAppFiles(Context context)',
                      self.reply_outbox)
        pending_at = self.reply_outbox.index(
            'private static List<File> pendingFilesLocked(')
        pending_tail = self.reply_outbox[pending_at:pending_at + 550]
        self.assertIn('\\\\.reply', pending_tail)
        self.assertNotIn('needs_app', pending_tail)
        self.assertIn('repostNeedsAppNotifications(this)',
                      self.application)
        self.assertIn('repostNeedsAppNotifications(context)', self.boot)
        self.assertIn('queueNeedsAppConversationOpen();', self.main)
        self.assertIn('MainActivity.this::queueNeedsAppConversationOpen',
                      self.main)

    def test_sensitive_notification_purge_keeps_encrypted_outbox(self):
        self.assertIn('public static void purgeSensitiveNotifications(',
                      self.chat)
        self.assertIn('manager.cancelAll()', self.chat)
        self.assertIn('privacyGeneration++', self.chat)
        self.assertIn('public static boolean postIfPrivacyStateCurrent(',
                      self.chat)
        purge_at = self.chat.index(
            'public static void purgeSensitiveNotifications(')
        purge_tail = self.chat[purge_at:purge_at + 1800]
        self.assertNotIn('NotificationReplyOutbox', purge_tail)
        self.assertNotIn('delete(', purge_tail)
        self.assertIn('public void purgeSensitiveNotifications()', self.main)
        self.assertGreaterEqual(
            self.main.count(
                'ChatNotificationController.purgeSensitiveNotifications('),
            6)
        self.assertIn("'purgeSensitiveNotifications'", self.html)
        self.assertIn('if(pin)await purgeSensitiveNativeNotifications()',
                      self.html)
        self.assertIn('void purgeSensitiveNativeNotifications()', self.html)

    def test_pending_reply_is_closed_by_exact_terminal_request(self):
        self.assertIn('PENDING_REPLY_PREFERENCES', self.chat)
        self.assertIn('public static boolean dismissPendingIfRequestMatches(',
                      self.chat)
        self.assertIn('if (!requestId.equals(current))', self.chat)
        self.assertIn('manager.cancel(\n                    notificationTag(',
                      self.chat)
        self.assertIn('manager.notify(\n                notificationTag(',
                      self.chat)
        self.assertIn('NOTIFICATION_TAG_PREFIX', self.chat)
        self.assertIn('&& !current.equals(cleanRequestId)', self.chat)
        self.assertIn('NotificationDeliveryLedger.wasDelivered(', self.chat)
        self.assertIn('.postIfPrivacyStateCurrent(', self.completion)
        self.assertIn('.postIfPrivacyStateCurrent(', self.reminder)
        self.assertIn('notificationPrivacyGeneration()', self.completion)
        self.assertIn('notificationPrivacyGeneration()', self.reminder)
        self.assertIn('record.requestId);', self.reply_outbox_job)
        self.assertIn('"", requestId);', self.reply)
        self.assertIn('isTerminalStatus(status)', self.completion)
        self.assertIn('"completed".equals(status)', self.completion)
        self.assertIn('"failed".equals(status)', self.completion)
        self.assertIn('"cancelled".equals(status)', self.completion)
        dismiss_at = self.completion.index(
            '.dismissPendingIfRequestMatches(')
        visible_at = self.completion.index(
            'if (ChatNotificationController.isAppVisible()')
        self.assertLess(dismiss_at, visible_at)
        # API 24-25 setTimeoutAfter alamasa bile kalıcı request eşleşmesi
        # terminal sonuçta aynı notification id'sini kapatır.
        self.assertIn('Build.VERSION_CODES.O', self.chat)
        self.assertIn('.putString(pendingKey(conversationId), cleanRequestId)',
                      self.chat)
        self.assertIn('Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)',
                      self.boot)
        self.assertIn(
            'ChatNotificationController.purgeSensitiveNotifications(context)',
            self.boot)

    def test_reminder_receiver_delivers_ready_ai_once_and_stays_neutral(self):
        self.assertIn('/api/reminders/deliver', self.reminder)
        self.assertIn('/api/reminders/deliver-ack', self.reminder)
        self.assertIn('DivanLocalApi.postDetailed(', self.reminder)
        self.assertNotIn('com.chaquo.python', self.reminder)
        self.assertIn('goAsync()', self.reminder)
        self.assertIn('"generating".equals(state)', self.reminder)
        self.assertIn('message_id', self.reminder)
        self.assertIn('source_id', self.reminder)
        self.assertIn('reply_allowed', self.reminder)
        self.assertIn('payload.put("allow_preview",', self.reminder)
        self.assertIn('preview_allowed', self.reminder)
        self.assertIn('NotificationTextSanitizer.plainAssistantText(preview)',
                      self.reminder)
        self.assertIn(
            'ConversationNotificationSupport.applySingleAssistantMessage(',
            self.reminder)
        self.assertIn('NotificationCompat.CATEGORY_REMINDER', self.reminder)
        self.assertIn(
            'CompletionNotificationController.PREVIEW_CHANNEL_ID',
            self.reminder)
        self.assertNotIn('entry.put("title"', self.reminder)
        self.assertNotIn('entry.put("body"', self.reminder)
        self.assertIn('"Bir görev hatırlatıcınız var."', self.reminder)
        self.assertIn('"suppressed".equals(state)', self.reminder)
        self.assertIn('"cancelled".equals(state)', self.reminder)
        suppressed_at = self.reminder.index('"suppressed".equals(state)')
        neutral_at = self.reminder.index('boolean neutral = "neutral".equals(state)')
        self.assertLess(suppressed_at, neutral_at)
        self.assertIn('removeStored(context, safeId);',
                      self.reminder[suppressed_at:neutral_at])
        self.assertIn('"notification_reply_requires_app".equals(',
                      self.reply_outbox_job)
        code_at = self.reply_outbox_job.index(
            '"notification_reply_requires_app".equals(')
        legacy_at = self.reply_outbox_job.index(
            '"bu yanıt güvenli biçimde uygulama içinde ele alınmalı"')
        self.assertLess(code_at, legacy_at)
        self.assertIn('setAndAllowWhileIdle(', self.reminder)
        self.assertNotIn('SCHEDULE_EXACT_ALARM', self.manifest)

    def test_notification_preview_plain_text_has_only_platform_hard_limit(self):
        self.assertIn('ANDROID_TEXT_HARD_LIMIT = 5_000',
                      self.text_sanitizer)
        self.assertIn('NotificationCompat/Android framework',
                      self.text_sanitizer)
        self.assertIn('Tam metin için Divan\'ı açın.',
                      self.text_sanitizer)
        self.assertIn('Html.fromHtml(', self.text_sanitizer)
        self.assertIn('Html.FROM_HTML_MODE_LEGACY', self.text_sanitizer)
        self.assertIn('SCRIPT_STYLE', self.text_sanitizer)
        self.assertIn('MARKDOWN_LINK', self.text_sanitizer)
        self.assertIn('MARKDOWN_IMAGE', self.text_sanitizer)
        self.assertIn('MARKDOWN_REFERENCE', self.text_sanitizer)
        self.assertIn('MARKDOWN_REFERENCE_DEFINITION', self.text_sanitizer)
        self.assertIn('MARKDOWN_TABLE_DIVIDER', self.text_sanitizer)
        self.assertIn('source.replaceAll(', self.text_sanitizer)
        self.assertIn('plain.replace("```", "").replace("`", "")',
                      self.text_sanitizer)
        self.assertIn('plain.replace("**", "").replace("__", "")',
                      self.text_sanitizer)
        self.assertIn("plain = plain.replace('|', ' ');",
                      self.text_sanitizer)
        self.assertNotIn('160', self.completion)
        self.assertNotIn('truncate(message, 160)', self.chat)

    def test_permission_and_deep_link_flow_are_lifecycle_safe(self):
        self.assertIn("Build.VERSION_CODES.TIRAMISU", self.preferences)
        self.assertIn("Manifest.permission.POST_NOTIFICATIONS",
                      self.preferences)
        self.assertIn("PackageManager.PERMISSION_GRANTED", self.preferences)
        self.assertIn("manager.areNotificationsEnabled()", self.preferences)
        self.assertIn("channel.getImportance()", self.preferences)
        self.assertIn("NotificationManager.IMPORTANCE_NONE", self.preferences)
        self.assertIn('runOnUiThread(() -> {', self.main)
        self.assertIn('notificationPermissionForCompletion', self.main)
        self.assertIn('notificationPermissionForReminder', self.main)
        self.assertIn('notifyWebNotificationPermissionChanged', self.main)
        self.assertIn('webView.post(this::injectPendingConversationOpen)',
                      self.main)
        self.assertIn('public void appUnlocked()', self.main)
        self.assertIn("DivanNative.appUnlocked()", self.html)

    def test_release_and_notification_artifacts_are_private(self):
        self.assertIn('isDebuggable = false', self.gradle)
        self.assertIn('R.drawable.ic_stat_divan', self.completion)
        self.assertIn('R.drawable.ic_stat_divan', self.reminder)
        self.assertNotIn('R.drawable.ic_divan_launcher', self.completion)
        self.assertNotIn('R.drawable.ic_divan_launcher', self.reminder)
        self.assertNotIn('body.substring(', self.local_api)

    def test_rich_notification_has_whatsapp_like_person_semantics(self):
        support = self.conversation_support
        self.assertIn('new Person.Builder()\n                .setName("Siz")',
                      support)
        self.assertIn('.setKey("divan-self")', support)
        self.assertIn('.setBot(false)', support)
        self.assertIn('.setName(senderLabel)', support)
        self.assertIn('.setIcon(avatar)', support)
        self.assertIn('IconCompat.createWithBitmap(bitmap)', support)
        self.assertIn('.setBot(true)', support)
        self.assertIn('AI_DISCLOSURE = "AI canlandırması"', support)
        self.assertIn('new NotificationCompat.MessagingStyle(self)', support)
        self.assertIn('.setGroupConversation(false)', support)
        self.assertEqual(support.count('.addMessage('), 1)
        self.assertNotIn('.addHistoricMessage(', support)
        self.assertIn('.setCategory(NotificationCompat.CATEGORY_MESSAGE)',
                      support)
        self.assertIn('.setAllowSystemGeneratedContextualActions(false)',
                      support)
        # Kullanıcı mesajı/geçmişi Android stiline eklenemez.
        self.assertNotIn('user_content', self.completion)
        self.assertNotIn('userText', self.completion)
        self.assertNotIn('history', self.completion.lower())

    def test_api24_28_33_35_conversation_notification_contract(self):
        # API 24: MessagingStyle, RemoteInput ve grouping compat katmanında.
        self.assertIn('minSdk = 24', self.gradle)
        self.assertIn('NotificationCompat.MessagingStyle',
                      self.conversation_support)
        self.assertIn('.setGroup(GROUP_KEY)', self.conversation_support)
        self.assertIn('androidx.core.app.RemoteInput', self.chat)
        self.assertIn('NotificationCompat.PRIORITY_HIGH', self.completion)
        self.assertIn('NotificationCompat.DEFAULT_ALL', self.completion)
        # API 25+: dinamik conversation shortcut; API 28 Person compat;
        # API 29+: locus; API 33+ runtime izin kapısı. target 36, API 35'i
        # yeni davranışları devre dışı bırakmadan kapsar.
        self.assertIn('Build.VERSION_CODES.N_MR1',
                      self.conversation_support)
        self.assertIn('ShortcutManagerCompat.pushDynamicShortcut(',
                      self.conversation_support)
        self.assertIn('.setPerson(assistant)', self.conversation_support)
        self.assertIn('new LocusIdCompat(', self.conversation_support)
        self.assertIn('Build.VERSION_CODES.TIRAMISU', self.preferences)
        self.assertIn('targetSdk = 36', self.gradle)

    def test_two_conversations_use_collision_free_tags_and_silent_summary(self):
        support = self.conversation_support
        self.assertIn(
            'CONVERSATION_TAG_PREFIX =\n'
            '            "divan.completion.conversation.";', support)
        self.assertIn('return CONVERSATION_TAG_PREFIX + conversationId;',
                      support)
        self.assertNotIn('% 100000', support)
        self.assertIn('Map<Integer, JSONObject> latestByConversation',
                      self.completion)
        self.assertIn('richByConversation.entrySet()', self.completion)
        self.assertIn('CONVERSATION_NOTIFICATION_ID', self.completion)
        self.assertIn('manager.notify(notificationTag, notificationId,',
                      self.chat)
        self.assertIn('.setGroupSummary(true)', self.completion)
        self.assertIn('NotificationCompat.GROUP_ALERT_CHILDREN',
                      self.completion)
        self.assertIn('.setSilent(silent)', self.completion)
        self.assertIn('manager.getActiveNotifications()', self.completion)
        self.assertIn('activeRichCount + neutralCount > 1',
                      self.completion)
        # Aynı görüşmenin yeni terminal mesajı sabit tag/id'yi günceller ama
        # onlyAlertOnce yüzünden sessiz kalmaz.
        rich_at = self.completion.index(
            'private static Notification richConversationNotification(')
        neutral_at = self.completion.index(
            'private static Notification neutralNotification(', rich_at)
        self.assertNotIn('.setOnlyAlertOnce(true)',
                         self.completion[rich_at:neutral_at])
        # Zorunlu nötr kanal preflight'ı ilk child postundan öncedir.
        preflight = self.completion.index(
            'if (neutralCount > 0',
            self.completion.index('private static boolean process('))
        child_post = self.completion.index(
            '.postConversationIfPrivacyStateCurrent(', preflight)
        self.assertLess(preflight, child_post)

    def test_lock_privacy_transition_removes_rich_surfaces_and_remote_input(self):
        self.assertIn('dismissConversation(context, entry.getKey())',
                      self.completion)
        self.assertIn('removeConversationShortcut(', self.completion)
        self.assertIn('purgeConversationShortcuts(app)', self.chat)
        self.assertIn('manager.cancelAll()', self.chat)
        self.assertIn('!item.optBoolean("preview_allowed", false)',
                      self.completion)
        inline_method = self.completion[
            self.completion.index(
                'private static void addInlineReplyIfAllowed('):]
        self.assertIn('!item.optBoolean("preview_allowed", false)',
                      inline_method)
        neutral_method = self.completion[
            self.completion.index(
                'private static Notification neutralNotification('):
            self.completion.index(
                'private static Notification publicVersion(')]
        self.assertNotIn('inlineReplyActionFor', neutral_method)
        self.assertNotIn('applySingleAssistantMessage', neutral_method)

    def test_remote_reply_cancels_exact_tagged_source(self):
        self.assertIn('EXTRA_SOURCE_NOTIFICATION_TAG', self.chat)
        self.assertIn('safeNotificationTag(sourceNotificationTag)',
                      self.chat)
        self.assertIn('sourceNotificationTag,\n'
                      '                        sourceNotificationId',
                      self.reply)
        self.assertIn('record.sourceNotificationTag,',
                      self.reply_outbox_job)
        self.assertIn('PendingIntent.FLAG_ONE_SHOT', self.chat)
        self.assertIn('PendingIntent.FLAG_MUTABLE', self.chat)
        self.assertIn('.setSemanticAction(\n'
                      '                        NotificationCompat.Action.'
                      'SEMANTIC_ACTION_REPLY)', self.chat)
        self.assertIn('.setAuthenticationRequired(true)', self.chat)

    def test_no_legacy_preview_path_can_bypass_conversation_controller(self):
        self.assertNotIn('showScheduledMessage(', self.chat)
        self.assertNotIn('showResponse(', self.chat)
        self.assertNotIn('Notification.BigTextStyle', self.chat)
        self.assertNotIn('NotificationCompat.BigTextStyle', self.completion)
        self.assertNotIn('NotificationCompat.BigTextStyle', self.reminder)


if __name__ == "__main__":
    unittest.main()
