package com.furkancanyilmaz.divan;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import androidx.core.app.RemoteInput;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Bildirimden gelen kısa yanıtı şifreli native outbox'a kabul ettirir.
 *
 * <p>Receiver Python veya HTTP başlatmaz, model çalıştırmaz ve polling
 * yapmaz. Yalnız Android Keystore ile uygulama-private atomik kayıt yapıp
 * persisted JobService'i uyandırır. PIN/misafir/güvenlik kararı daha sonra
 * sunucuda yeniden doğrulanır; tepside kalmış eski eylem kilidi aşamaz.</p>
 */
public final class ChatReplyReceiver extends BroadcastReceiver {

    private static final int MAX_REPLY_CHARS = 50_000;
    private static final long RECEIVER_FINISH_MS = 8_500L;
    private static final ExecutorService PERSIST_EXECUTOR =
            Executors.newFixedThreadPool(2);
    private static final ScheduledExecutorService FINISH_EXECUTOR =
            Executors.newSingleThreadScheduledExecutor();

    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null
                || intent.getAction() == null
                || !intent.getAction().startsWith(
                        ChatNotificationController.ACTION_INLINE_REPLY)
                || !NotificationPreferences.inlineReplyEnabled(context)) {
            return;
        }
        Bundle results = RemoteInput.getResultsFromIntent(intent);
        CharSequence supplied = results == null ? null
                : results.getCharSequence(
                        ChatNotificationController.EXTRA_REPLY_KEY);
        String message = String.valueOf(
                supplied == null ? "" : supplied).trim();
        if (results != null) {
            // Android'in teslim ettiği geçici Bundle'dan uygulama kopyasını
            // hemen kaldır; yeni bir Intent/Job extra oluşturulmaz.
            results.remove(ChatNotificationController.EXTRA_REPLY_KEY);
        }
        // RemoteInput sonuçları framework tarafından ClipData içinde taşınır.
        // Metni aldıktan sonra receiver Intent'inde de tutma.
        intent.setClipData(null);
        int conversationId = intent.getIntExtra(
                ChatNotificationController.EXTRA_CONVERSATION_ID, 0);
        long replyTo = intent.getLongExtra(
                ChatNotificationController.EXTRA_REPLY_TO_MESSAGE_ID, 0L);
        int sourceNotificationId = intent.getIntExtra(
                ChatNotificationController.EXTRA_SOURCE_NOTIFICATION_ID, 0);
        String sourceNotificationTag =
                ChatNotificationController.safeNotificationTag(
                        intent.getStringExtra(
                                ChatNotificationController
                                        .EXTRA_SOURCE_NOTIFICATION_TAG));
        String requestId = cleanRequestId(intent.getStringExtra(
                ChatNotificationController.EXTRA_REPLY_REQUEST_ID));
        String sourceId = cleanSourceId(intent.getStringExtra(
                ChatNotificationController.EXTRA_REPLY_SOURCE_ID));
        if (conversationId <= 0 || replyTo <= 0L
                || sourceNotificationId <= 0 || requestId.isEmpty()
                || sourceId.isEmpty() || message.isEmpty()
                || message.length() > MAX_REPLY_CHARS) {
            return;
        }

        Context app = context.getApplicationContext();
        PendingResult pending = goAsync();
        AtomicBoolean finished = new AtomicBoolean(false);
        FINISH_EXECUTOR.schedule(
                () -> finishOnce(pending, finished),
                RECEIVER_FINISH_MS,
                TimeUnit.MILLISECONDS);
        PERSIST_EXECUTOR.execute(() -> {
            try {
                // Tercih, bildirimin oluşturulmasından sonra kapatılmış
                // olabilir; kalıcı yazımdan önce bir kez daha denetle.
                if (!NotificationPreferences.inlineReplyEnabled(app)) {
                    return;
                }
                boolean persisted = NotificationReplyOutbox.enqueue(
                        app, conversationId, message, requestId, sourceId,
                        replyTo, sourceNotificationTag,
                        sourceNotificationId);
                if (persisted) {
                    // Bundan sonra süreç ölse bile ciphertext boot/app açılışı
                    // veya JobScheduler backoff penceresinde yeniden bulunur.
                    NotificationReplyOutboxJobService.schedule(app);
                    ChatNotificationController.cancelNotification(
                            app, sourceNotificationTag,
                            sourceNotificationId);
                    ChatNotificationController.showPending(
                            app, conversationId, "Divan", "", requestId);
                }
            } catch (Exception ignored) {
                // Metni veya Keystore ayrıntısını loglama. Kalıcı kayıt
                // kurulamadıysa nötr hata göster; plaintext saklanmaz.
                ChatNotificationController.cancelNotification(
                        app, sourceNotificationTag,
                        sourceNotificationId);
                ChatNotificationController.showError(
                        app, conversationId, "Divan", "", requestId);
            } finally {
                finishOnce(pending, finished);
            }
        });
    }

    private static void finishOnce(
            PendingResult pending, AtomicBoolean finished) {
        if (finished.compareAndSet(false, true)) {
            pending.finish();
        }
    }

    private static String cleanRequestId(String raw) {
        String value = String.valueOf(raw == null ? "" : raw).trim();
        return value.matches("[A-Za-z0-9][A-Za-z0-9._:\\-]{11,127}")
                ? value : "";
    }

    private static String cleanSourceId(String raw) {
        String value = String.valueOf(raw == null ? "" : raw).trim();
        if (value.isEmpty() || value.length() > 160
                || !value.matches("[A-Za-z0-9][A-Za-z0-9._:\\-]{0,159}")) {
            return "";
        }
        return value;
    }
}
