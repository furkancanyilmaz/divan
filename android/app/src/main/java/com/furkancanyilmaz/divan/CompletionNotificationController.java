package com.furkancanyilmaz.divan;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.service.notification.StatusBarNotification;

import androidx.core.app.NotificationCompat;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Tamamlanan sohbetlerin tek bildirim çıkışı.
 *
 * <p>Bildirimler varsayılan olarak kapalı, içerik önizlemesi ayrıca opt-in'dir.
 * Güvenli zengin modda her görüşme kendi Android konuşma bildirimi olur;
 * nötr modda kişi, kullanıcı mesajı, geçmiş ve AI yanıtı hiçbir zaman Android
 * tepsisine taşınmaz.</p>
 */
public final class CompletionNotificationController {

    public static final String NEUTRAL_CHANNEL_ID =
            "divan_completion_v2";
    public static final String PREVIEW_CHANNEL_ID =
            "divan_completion_preview_v2";
    static final int SUMMARY_NOTIFICATION_ID = 2811;
    static final int CONVERSATION_NOTIFICATION_ID = 2812;
    private static final String SUMMARY_TAG = "divan.completion.summary";
    private static final int MAX_CONTEXTS_PER_FETCH = 50;

    private CompletionNotificationController() {
    }

    public static void ensureChannels(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        // Önceki HIGH/kimlik taşıyan kanallar artık kullanılmıyor. Aynı v2
        // kimliklerini yeniden oluşturmak kullanıcının mevcut kanal sessizliği
        // ve önem tercihlerini Android tarafında korur.
        manager.deleteNotificationChannel("divan_messages");
        manager.deleteNotificationChannel("divan_reminders");
        manager.deleteNotificationChannel("divan_neutral_updates");
        context.getApplicationContext().getSharedPreferences(
                "divan_notification_masters", Context.MODE_PRIVATE)
                .edit().clear().apply();

        NotificationChannel neutral = new NotificationChannel(
                NEUTRAL_CHANNEL_ID,
                "İçeriksiz Divan güncellemeleri",
                NotificationManager.IMPORTANCE_LOW);
        neutral.setDescription(
                "Yanıtın hazır olduğunu kişi ve içerik göstermeden bildirir");
        manager.createNotificationChannel(neutral);

        NotificationChannel preview = new NotificationChannel(
                PREVIEW_CHANNEL_ID,
                "Divan mesajları",
                NotificationManager.IMPORTANCE_DEFAULT);
        preview.setDescription(
                "Açık izninizle AI canlandırmasının son yanıtını gösterir");
        manager.createNotificationChannel(preview);
    }

    /** Sunucudaki terminal istek outbox'ını kapsam cursor'ıyla tüketir. */
    public static synchronized boolean deliverPending(
            Context context, int port, String token) {
        if (port <= 0 || token == null || token.isEmpty()) {
            return false;
        }
        long privacyGeneration =
                ChatNotificationController.notificationPrivacyGeneration();
        String scope = "main";
        long cursor = Math.min(
                NotificationDeliveryLedger.cursor(context, "main"),
                NotificationDeliveryLedger.cursor(context, "guest"));
        boolean allowPreview = NotificationPreferences.previewsEnabled(
                context);
        String path = "/api/notification-contexts?after_sequence="
                + cursor + "&limit=" + MAX_CONTEXTS_PER_FETCH
                + "&allow_preview=" + (allowPreview ? "1" : "0");
        String body = DivanLocalApi.get(port, token, path);
        if (body == null) {
            return false;
        }
        try {
            JSONObject payload = new JSONObject(body);
            scope = payload.optString("scope", "main");
            long actualCursor = NotificationDeliveryLedger.cursor(
                    context, scope);
            if (actualCursor != cursor) {
                path = "/api/notification-contexts?after_sequence="
                        + actualCursor + "&limit="
                        + MAX_CONTEXTS_PER_FETCH
                        + "&allow_preview="
                        + (allowPreview ? "1" : "0");
                body = DivanLocalApi.get(port, token, path);
                if (body == null) {
                    return false;
                }
                payload = new JSONObject(body);
                scope = payload.optString("scope", scope);
            }
            JSONArray contexts = payload.optJSONArray("contexts");
            if (contexts == null || contexts.length() == 0) {
                return false;
            }
            return process(context, scope, contexts, privacyGeneration);
        } catch (JSONException ignored) {
            return false;
        }
    }

    private static boolean process(
            Context context, String scope, JSONArray contexts,
            long privacyGeneration) {
        long maxSequence = 0L;
        List<String> requestIds = new ArrayList<>();
        Map<Integer, JSONObject> latestByConversation =
                new LinkedHashMap<>();
        int invalidNeutralCount = 0;

        for (int index = 0; index < contexts.length(); index++) {
            JSONObject item = contexts.optJSONObject(index);
            if (item == null) {
                continue;
            }
            long sequence = item.optLong("sequence", 0L);
            maxSequence = Math.max(maxSequence, sequence);
            String requestId = item.optString("request_id", "");
            if (!requestId.isEmpty()) {
                requestIds.add(requestId);
            }
            String status = item.optString("status", "");
            if (sequence > 0L && isTerminalStatus(status)) {
                ChatNotificationController.dismissPendingIfRequestMatches(
                        context,
                        item.optInt("conversation_id", 0),
                        requestId);
            }
            if ("cancelled".equals(status)
                    || NotificationDeliveryLedger.wasDelivered(
                            context, requestId)) {
                continue;
            }
            int conversationId = item.optInt("conversation_id", 0);
            if (conversationId <= 0) {
                invalidNeutralCount++;
                continue;
            }
            // Aynı görüşmede birden fazla terminal istek geldiyse yalnız en
            // yeni sonuç görünür; cursor hepsini birlikte ve tam bir kez ack'ler.
            latestByConversation.remove(conversationId);
            latestByConversation.put(conversationId, item);
        }
        if (maxSequence <= 0L) {
            return false;
        }

        if (ChatNotificationController.isAppVisible()
                || !NotificationPreferences.completionEnabled(context)
                || latestByConversation.isEmpty()
                && invalidNeutralCount == 0) {
            NotificationDeliveryLedger.mark(
                    context, scope, maxSequence, requestIds);
            return false;
        }
        ensureChannels(context);
        if (!NotificationPreferences.systemPermissionGranted(context)) {
            return false;
        }

        Map<Integer, JSONObject> richByConversation =
                new LinkedHashMap<>();
        List<JSONObject> neutral = new ArrayList<>();
        for (Map.Entry<Integer, JSONObject> entry
                : latestByConversation.entrySet()) {
            JSONObject item = entry.getValue();
            if (canShowRichPreview(context, item)) {
                richByConversation.put(entry.getKey(), item);
            } else {
                // PIN/guest/safety/preview-off kararı eski zengin child ve
                // launcher conversation yüzeyini de hemen nötrleştirir.
                dismissConversation(context, entry.getKey());
                ConversationNotificationSupport.removeConversationShortcut(
                        context, entry.getKey());
                neutral.add(item);
            }
        }

        int neutralCount = neutral.size() + invalidNeutralCount;
        // Gerekli bütün kanalları tek bir child bile post etmeden önce
        // denetle. Böylece zengin+nötr bir batch yarım teslim edilip cursor
        // geride bırakılmaz.
        if (neutralCount > 0
                && !NotificationPreferences.channelEnabled(
                        context, NEUTRAL_CHANNEL_ID)) {
            return false;
        }

        boolean postedAny = false;
        for (Map.Entry<Integer, JSONObject> entry
                : richByConversation.entrySet()) {
            int conversationId = entry.getKey();
            JSONObject item = entry.getValue();
            Notification notification = richConversationNotification(
                    context, item);
            boolean posted = ChatNotificationController
                    .postConversationIfPrivacyStateCurrent(
                            context,
                            privacyGeneration,
                            ConversationNotificationSupport.conversationTag(
                                    conversationId),
                            CONVERSATION_NOTIFICATION_ID,
                            notification,
                            conversationId,
                            item.optString("master_name", ""));
            if (!posted) {
                return abortOrConsume(
                        context, scope, maxSequence, requestIds);
            }
            postedAny = true;
        }

        int activeRichCount = activeConversationCount(
                context, richByConversation.size());
        boolean needsGroupSummary = activeRichCount > 0
                && activeRichCount + neutralCount > 1;
        boolean neutralRequired = neutralCount > 0;
        if (neutralRequired || needsGroupSummary) {
            if (NotificationPreferences.channelEnabled(
                    context, NEUTRAL_CHANNEL_ID)) {
                JSONObject lastNeutral = neutral.isEmpty()
                        ? null : neutral.get(neutral.size() - 1);
                int totalCount = activeRichCount + neutralCount;
                Notification summary = neutralNotification(
                        context,
                        lastNeutral,
                        needsGroupSummary ? totalCount : neutralCount,
                        needsGroupSummary,
                        needsGroupSummary);
                boolean posted = ChatNotificationController
                        .postIfPrivacyStateCurrent(
                                context,
                                privacyGeneration,
                                SUMMARY_TAG,
                                SUMMARY_NOTIFICATION_ID,
                                summary,
                                true);
                if (!posted) {
                    return abortOrConsume(
                            context, scope, maxSequence, requestIds);
                }
                postedAny = true;
            } else if (neutralRequired) {
                // Kullanıcı içeriksiz kanalın sistem ayarını kapattıysa bu
                // bağlamı "zengin" kanala kaçırmayız ve cursor'ı atlamayız.
                return false;
            }
        } else {
            // Önceki iki-sohbet özetini, tepside artık tek child kaldığında
            // bayat sayaç olarak bırakma.
            dismiss(context);
        }

        NotificationDeliveryLedger.mark(
                context, scope, maxSequence, requestIds);
        return postedAny;
    }

    private static boolean abortOrConsume(
            Context context, String scope, long maxSequence,
            List<String> requestIds) {
        // Uygulama görünür olduysa veya tercih kapanmışsa sonuç kullanıcıya
        // uygulamada ulaştı/istenmiyor; daha sonra eski bildirim üretme.
        if (ChatNotificationController.isAppVisible()
                || !NotificationPreferences.completionEnabled(context)) {
            NotificationDeliveryLedger.mark(
                    context, scope, maxSequence, requestIds);
        }
        return false;
    }

    private static boolean canShowRichPreview(
            Context context, JSONObject item) {
        if (!NotificationPreferences.previewsEnabled(context)
                || !NotificationPreferences.channelEnabled(
                        context, PREVIEW_CHANNEL_ID)
                || item.optBoolean("requires_in_app", false)
                || !item.optBoolean("preview_allowed", false)
                || !"completed".equals(item.optString("status", ""))) {
            return false;
        }
        return !NotificationTextSanitizer.plainAssistantText(
                item.optString("content", "")).isEmpty();
    }

    private static int activeConversationCount(
            Context context, int fallback) {
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return Math.max(0, fallback);
        }
        try {
            int count = 0;
            for (StatusBarNotification active
                    : manager.getActiveNotifications()) {
                String tag = active.getTag();
                if (tag != null
                        && tag.startsWith(
                                ConversationNotificationSupport
                                        .CONVERSATION_TAG_PREFIX)
                        && active.getId()
                                == CONVERSATION_NOTIFICATION_ID) {
                    count++;
                }
            }
            return count;
        } catch (RuntimeException ignored) {
            return Math.max(0, fallback);
        }
    }

    private static boolean isTerminalStatus(String status) {
        return "completed".equals(status)
                || "failed".equals(status)
                || "interrupted".equals(status)
                || "cancelled".equals(status);
    }

    private static Notification richConversationNotification(
            Context context, JSONObject item) {
        int conversationId = item.optInt("conversation_id", 0);
        String content = NotificationTextSanitizer.plainAssistantText(
                item.optString("content", ""));
        String master = item.optString("master_name", "").trim();
        PendingIntent open = openIntent(context, conversationId);
        long messageTime = System.currentTimeMillis();
        NotificationCompat.Builder builder = builder(
                context, PREVIEW_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentIntent(open)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setPublicVersion(publicVersion(context, open))
                .setAutoCancel(true)
                .setSortKey(String.format(
                        Locale.ROOT, "%020d",
                        item.optLong("sequence", 0L)));
        ConversationNotificationSupport.applySingleAssistantMessage(
                context, builder, conversationId, master, content,
                messageTime);
        addInlineReplyIfAllowed(
                builder,
                context,
                item,
                ConversationNotificationSupport.conversationTag(
                        conversationId));
        return builder.build();
    }

    private static Notification neutralNotification(
            Context context, JSONObject last, int count,
            boolean groupSummary, boolean silent) {
        int conversationId = !groupSummary && count == 1 && last != null
                ? last.optInt("conversation_id", 0) : 0;
        String status = last == null
                ? "" : last.optString("status", "");
        String text;
        if (count > 1) {
            text = count + " yanıt işlemi sonuçlandı.";
        } else if (last != null && !"completed".equals(status)) {
            text = "Yanıt tamamlanamadı. Divan'ı açarak yeniden deneyebilirsiniz.";
        } else {
            text = "Yanıtınız hazır.";
        }
        PendingIntent open = openIntent(context, conversationId);
        NotificationCompat.Builder builder = builder(
                context, NEUTRAL_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentTitle("Divan")
                .setContentText(text)
                .setContentIntent(open)
                .setCategory(NotificationCompat.CATEGORY_STATUS)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setPublicVersion(publicVersion(context, open))
                .setAutoCancel(true)
                .setOnlyAlertOnce(true)
                .setNumber(Math.max(1, count));
        if (groupSummary) {
            builder.setGroup(ConversationNotificationSupport.GROUP_KEY)
                    .setGroupSummary(true)
                    .setGroupAlertBehavior(
                            NotificationCompat.GROUP_ALERT_CHILDREN)
                    .setSilent(silent);
        }
        // Nötr bildirim bilinçli olarak MessagingStyle, Person, shortcut,
        // locus ve RemoteInput almaz; PIN/guest/safety burada fail-closed'dur.
        return builder.build();
    }

    private static Notification publicVersion(
            Context context, PendingIntent open) {
        return builder(context, NEUTRAL_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentTitle("Divan")
                .setContentText("Divan'da yeni bir güncelleme var.")
                .setContentIntent(open)
                .setCategory(NotificationCompat.CATEGORY_STATUS)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setAutoCancel(true)
                .build();
    }

    private static NotificationCompat.Builder builder(
            Context context, String channelId) {
        NotificationCompat.Builder builder =
                new NotificationCompat.Builder(context, channelId);
        if (PREVIEW_CHANNEL_ID.equals(channelId)) {
            // API 24-25'te kanal yoktur; normal sohbet mesajı gibi bir kez
            // uyarması için compat priority/defaults gerekir. Aynı tag/id'ye
            // gelen yeni terminal yanıt onlyAlertOnce kullanmaz.
            builder.setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setDefaults(NotificationCompat.DEFAULT_ALL);
        } else {
            builder.setPriority(NotificationCompat.PRIORITY_LOW);
        }
        return builder;
    }

    private static void addInlineReplyIfAllowed(
            NotificationCompat.Builder builder, Context context,
            JSONObject item, String sourceNotificationTag) {
        if (item == null
                || !"completed".equals(item.optString("status", ""))
                // Odak kararları ve derin şema adımları yalnız uygulama
                // içinde yanıtlanır. Sunucunun yetkili bayrağı, eski alanlar
                // yanlışlıkla true kalsa bile RemoteInput'u kapatır.
                || item.optBoolean("requires_in_app", false)
                || !item.optBoolean("preview_allowed", false)
                || !item.optBoolean("reply_allowed", false)) {
            return;
        }
        int conversationId = item.optInt("conversation_id", 0);
        long replyTo = item.optLong("message_id", 0L);
        String sourceId = item.optString("request_id", "");
        NotificationCompat.Action action =
                ChatNotificationController.inlineReplyActionFor(
                        context,
                        conversationId,
                        sourceId,
                        replyTo,
                        sourceNotificationTag,
                        CONVERSATION_NOTIFICATION_ID);
        if (action != null) {
            builder.addAction(action);
        }
    }

    static PendingIntent openIntent(
            Context context, int conversationId) {
        Intent open = new Intent(context, MainActivity.class)
                .setAction(Intent.ACTION_VIEW)
                .setData(Uri.parse(
                        conversationId > 0
                                ? "divan://notification/conversation/"
                                        + conversationId
                                : "divan://notification/home"))
                .setPackage(context.getPackageName())
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (conversationId > 0) {
            open.putExtra(
                    ChatNotificationController.EXTRA_CONVERSATION_ID,
                    conversationId);
        }
        return PendingIntent.getActivity(
                context,
                conversationId > 0
                        ? conversationId : SUMMARY_NOTIFICATION_ID,
                open,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
    }

    public static void dismissConversation(
            Context context, int conversationId) {
        if (context == null || conversationId <= 0) {
            return;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.cancel(
                    ConversationNotificationSupport.conversationTag(
                            conversationId),
                    CONVERSATION_NOTIFICATION_ID);
        }
    }

    public static void dismiss(Context context) {
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.cancel(SUMMARY_TAG, SUMMARY_NOTIFICATION_ID);
            // v2.6 ve öncesindeki etiketsiz tek bildirim de temizlenir.
            manager.cancel(SUMMARY_NOTIFICATION_ID);
        }
    }
}
