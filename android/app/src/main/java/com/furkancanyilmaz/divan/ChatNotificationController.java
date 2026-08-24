package com.furkancanyilmaz.divan;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.RemoteInput;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * Sohbet bildirimleri ve açıkça seçilmiş güvenli RemoteInput için ortak katman.
 *
 * <p>Yeni tamamlanma bildirimleri {@link CompletionNotificationController}
 * üzerinden gider. Bu sınıf artık kullanıcı mesajını veya konuşma geçmişini
 * Android bildirimine yazmaz. RemoteInput yalnız ayrı kullanıcı tercihi ve
 * sunucunun PIN/misafir/güvenlik kararıyla birlikte üretilir; kabul anında
 * sunucuda yeniden doğrulanır.</p>
 */
@SuppressLint("ApplySharedPref")
public final class ChatNotificationController {

    public static final String CHANNEL_ID = "divan_messages_v2";
    public static final String EXTRA_CONVERSATION_ID =
            "divan.chat.conversation_id";
    public static final String EXTRA_MASTER_NAME = "divan.chat.master_name";
    public static final String EXTRA_REPLY_KEY = "divan.chat.reply";
    public static final String EXTRA_REPLY_REQUEST_ID =
            "divan.chat.reply_request_id";
    public static final String EXTRA_REPLY_SOURCE_ID =
            "divan.chat.reply_source_id";
    public static final String EXTRA_REPLY_TO_MESSAGE_ID =
            "divan.chat.reply_to_message_id";
    public static final String EXTRA_SOURCE_NOTIFICATION_ID =
            "divan.chat.source_notification_id";
    public static final String EXTRA_SOURCE_NOTIFICATION_TAG =
            "divan.chat.source_notification_tag";
    public static final String ACTION_INLINE_REPLY =
            "com.furkancanyilmaz.divan.INLINE_REPLY";

    private static final int BASE_NOTIFICATION_ID = 0x5100;
    private static final String NOTIFICATION_TAG_PREFIX =
            "divan.chat.";
    private static final String MASTER_PREFERENCES =
            "divan_notification_masters";
    private static final String PENDING_REPLY_PREFERENCES =
            "divan_pending_reply_notifications";
    private static final Object PENDING_REPLY_LOCK = new Object();
    private static volatile boolean appVisible = false;
    private static long privacyGeneration = 0L;

    private ChatNotificationController() {
    }

    public static void setAppVisible(boolean visible) {
        appVisible = visible;
    }

    public static boolean isAppVisible() {
        return appVisible;
    }

    public static long notificationPrivacyGeneration() {
        synchronized (PENDING_REPLY_LOCK) {
            return privacyGeneration;
        }
    }

    /**
     * Uzun süren yerel/API hazırlığından sonra gelen bir bildirimi, arada
     * purge veya görünür-uygulama geçişi olduysa tepsiye geri sokmaz.
     */
    public static boolean postIfPrivacyStateCurrent(
            Context context, long expectedGeneration,
            int notificationId, Notification notification,
            boolean requireCompletionPreference) {
        return postIfPrivacyStateCurrent(
                context, expectedGeneration, null, notificationId,
                notification, requireCompletionPreference);
    }

    /**
     * Etiketli sürüm, aynı int kimliğini kullanan iki görüşmenin birbirini
     * ezmesini önler. Android NotificationManager kimliği (tag,id) çiftidir.
     */
    public static boolean postIfPrivacyStateCurrent(
            Context context, long expectedGeneration,
            String notificationTag, int notificationId,
            Notification notification,
            boolean requireCompletionPreference) {
        if (context == null || notification == null) {
            return false;
        }
        Context app = context.getApplicationContext();
        synchronized (PENDING_REPLY_LOCK) {
            if (expectedGeneration != privacyGeneration
                    || appVisible
                    || requireCompletionPreference
                    && !NotificationPreferences.completionEnabled(app)) {
                return false;
            }
            NotificationManager manager = (NotificationManager)
                    app.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) {
                return false;
            }
            if (notificationTag == null || notificationTag.isEmpty()) {
                try {
                    manager.notify(notificationId, notification);
                } catch (RuntimeException ignored) {
                    return false;
                }
            } else {
                try {
                    manager.notify(notificationTag, notificationId,
                            notification);
                } catch (RuntimeException ignored) {
                    return false;
                }
            }
            return true;
        }
    }

    /**
     * Zengin conversation shortcut'ı ile bildirimi aynı privacy-generation
     * kritik bölümünde yayımlar. Böylece PIN/kilit purge'ünden sonra yarışan
     * bir builder kişi adını launcher yüzeyine geri koyamaz.
     */
    public static boolean postConversationIfPrivacyStateCurrent(
            Context context, long expectedGeneration,
            String notificationTag, int notificationId,
            Notification notification, int conversationId,
            String masterName) {
        if (context == null || notification == null
                || conversationId <= 0) {
            return false;
        }
        Context app = context.getApplicationContext();
        synchronized (PENDING_REPLY_LOCK) {
            if (expectedGeneration != privacyGeneration
                    || appVisible
                    || !NotificationPreferences.previewsEnabled(app)) {
                return false;
            }
            NotificationManager manager = (NotificationManager)
                    app.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) {
                return false;
            }
            ConversationNotificationSupport.publishConversationShortcut(
                    app, conversationId, masterName);
            try {
                manager.notify(notificationTag, notificationId,
                        notification);
                return true;
            } catch (RuntimeException ignored) {
                ConversationNotificationSupport.removeConversationShortcut(
                        app, conversationId);
                return false;
            }
        }
    }

    public static void ensureChannel(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Sohbet işlemleri",
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(
                "Yalnız bildirimden başlatılmış eski sohbet işlemlerinin durumu");
        manager.createNotificationChannel(channel);
    }

    /** Eski inline-reply alındığında hassas metni göstermeyen bekleme durumu. */
    public static void showPending(
            Context context, int conversationId, String masterName,
            String userText, String requestId) {
        if (context == null || conversationId <= 0) {
            return;
        }
        Context app = context.getApplicationContext();
        String cleanRequestId = cleanRequestId(requestId);
        if (cleanRequestId.isEmpty()) {
            return;
        }
        synchronized (PENDING_REPLY_LOCK) {
            // Tercih/kilit geçişiyle veya ekranda tüketimle yarışan bir iş,
            // purge sonrasında aynı durum bildirimini yeniden üretmesin.
            if (appVisible
                    || !NotificationPreferences.inlineReplyEnabled(app)
                    || NotificationDeliveryLedger.wasDelivered(
                            app, cleanRequestId)) {
                dismissPendingLocked(
                        app, conversationId, cleanRequestId);
                return;
            }
            SharedPreferences pending = pendingReplies(app);
            String current = pending.getString(
                    pendingKey(conversationId), "");
            // Aynı görüşmenin daha yeni/başka bir isteğini eski bir persisted
            // işin geç sonucu asla ezmesin.
            if (!current.isEmpty()
                    && !current.equals(cleanRequestId)) {
                return;
            }
            Notification.Builder builder = safeBuilder(
                    app, conversationId,
                    "Yanıt hazırlanıyor. Tamamlandığında haber vereceğiz.");
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                builder.setTimeoutAfter(3L * 60L * 1000L);
            }
            if (!notify(app, conversationId, builder)) {
                return;
            }
            // Bildirimi yalnız eşleşme kaydı kalıcılaştıysa bırak. Böylece
            // API 24-25'te timeout bulunmasa da terminal sonuç kesin kapatır.
            if (!pending.edit()
                    .putString(pendingKey(conversationId), cleanRequestId)
                    .commit()) {
                cancelConversationNotification(app, conversationId);
            }
        }
    }

    public static void showError(
            Context context, int conversationId, String masterName,
            String message, String requestId) {
        if (context == null) {
            return;
        }
        Context app = context.getApplicationContext();
        String cleanRequestId = cleanRequestId(requestId);
        synchronized (PENDING_REPLY_LOCK) {
            if (appVisible
                    || !NotificationPreferences.inlineReplyEnabled(app)) {
                return;
            }
            if (conversationId > 0) {
                String current = pendingReplies(app).getString(
                        pendingKey(conversationId), "");
                // Başka bir RemoteInput isteğinin bekleme durumunu hata
                // bildirimiyle değiştirme.
                if (!current.isEmpty()
                        && !current.equals(cleanRequestId)) {
                    return;
                }
            }
            Notification.Builder builder = safeBuilder(
                    app, conversationId,
                    "Yanıt tamamlanamadı. Uygulamayı açarak yeniden deneyebilirsiniz.");
            notify(app, conversationId, builder);
        }
    }

    /**
     * Güvenlik kapısında otomatik teslim edilmeyen şifreli yanıt için nötr
     * ve PRIVATE uygulamaya dönüş bildirimi. Kullanıcı metni, terapist adı ve
     * request kimliği Notification/Intent içine girmez; content intent yalnız
     * kesin görüşme kimliğini taşır.
     */
    public static void showNeedsApp(
            Context context, int conversationId, String requestId) {
        if (context == null || conversationId <= 0
                || cleanRequestId(requestId).isEmpty()) {
            return;
        }
        Context app = context.getApplicationContext();
        synchronized (PENDING_REPLY_LOCK) {
            Notification.Builder builder = safeBuilder(
                    app, conversationId,
                    "Yanıtınızı güvenle ele almak için Divan’ı açın");
            builder.setCategory(Notification.CATEGORY_STATUS)
                    .setVisibility(Notification.VISIBILITY_PRIVATE);
            notify(app, conversationId, builder);
        }
    }

    public static void dismiss(Context context, int conversationId) {
        if (context == null || conversationId <= 0) {
            return;
        }
        Context app = context.getApplicationContext();
        synchronized (PENDING_REPLY_LOCK) {
            cancelConversationNotification(app, conversationId);
            pendingReplies(app).edit()
                    .remove(pendingKey(conversationId))
                    .commit();
        }
    }

    /**
     * Yalnız aynı görüşme ve aynı idempotent istek için gösterilmiş bekleme
     * durumunu kapatır. Başka bir görüşme veya aynı görüşmenin daha yeni
     * isteği hiçbir zaman etkilenmez.
     */
    public static boolean dismissPendingIfRequestMatches(
            Context context, int conversationId, String requestId) {
        if (context == null || conversationId <= 0) {
            return false;
        }
        String cleanRequestId = cleanRequestId(requestId);
        if (cleanRequestId.isEmpty()) {
            return false;
        }
        synchronized (PENDING_REPLY_LOCK) {
            return dismissPendingLocked(
                    context.getApplicationContext(), conversationId,
                    cleanRequestId);
        }
    }

    /**
     * Bu paketin tepsisinde daha önce gösterilmiş bütün Divan bildirimlerini
     * temizler. Android NotificationManager.cancelAll çağrısını otomatik
     * olarak çağıran uygulama paketiyle sınırlar. Şifreli kullanıcı-yanıtı
     * outbox'ı veya sohbet/veritabanı kayıtları bu işlemde değiştirilmez.
     */
    public static void purgeSensitiveNotifications(Context context) {
        if (context == null) {
            return;
        }
        Context app = context.getApplicationContext();
        synchronized (PENDING_REPLY_LOCK) {
            privacyGeneration++;
            NotificationManager manager = (NotificationManager)
                    app.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.cancelAll();
            }
            pendingReplies(app).edit().clear().commit();
            app.getSharedPreferences(
                    MASTER_PREFERENCES, Context.MODE_PRIVATE)
                    .edit().clear().commit();
            ConversationNotificationSupport.purgeConversationShortcuts(app);
        }
    }

    private static boolean dismissPendingLocked(
            Context context, int conversationId, String requestId) {
        SharedPreferences pending = pendingReplies(context);
        String current = pending.getString(
                pendingKey(conversationId), "");
        if (!requestId.equals(current)) {
            return false;
        }
        cancelConversationNotification(context, conversationId);
        pending.edit().remove(pendingKey(conversationId)).commit();
        return true;
    }

    private static SharedPreferences pendingReplies(Context context) {
        return context.getApplicationContext().getSharedPreferences(
                PENDING_REPLY_PREFERENCES, Context.MODE_PRIVATE);
    }

    private static String pendingKey(int conversationId) {
        return String.valueOf(conversationId);
    }

    private static String cleanRequestId(String raw) {
        String value = String.valueOf(raw == null ? "" : raw).trim();
        if (value.isEmpty() || value.length() > 160
                || !value.matches(
                        "[A-Za-z0-9][A-Za-z0-9._:\\-]{0,159}")) {
            return "";
        }
        return value;
    }

    private static void cancelConversationNotification(
            Context context, int conversationId) {
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.cancel(
                    notificationTag(conversationId),
                    notificationId(conversationId));
        }
    }

    private static Notification.Builder safeBuilder(
            Context context, int conversationId, String text) {
        ensureChannel(context);
        PendingIntent open = openConversation(context, conversationId);
        Notification publicVersion = builder(context)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentTitle("Divan")
                .setContentText("Divan'da yeni bir güncelleme var.")
                .setContentIntent(open)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setAutoCancel(true)
                .build();
        return builder(context)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentTitle("Divan")
                .setContentText(text)
                .setContentIntent(open)
                .setCategory(Notification.CATEGORY_STATUS)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(publicVersion)
                .setAutoCancel(true)
                .setOnlyAlertOnce(true)
                .setPriority(Notification.PRIORITY_LOW);
    }

    private static Notification.Builder builder(Context context) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(context, CHANNEL_ID)
                : new Notification.Builder(context);
    }

    private static PendingIntent openConversation(
            Context context, int conversationId) {
        Intent open = new Intent(context, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(EXTRA_CONVERSATION_ID, conversationId);
        return PendingIntent.getActivity(
                context,
                conversationId,
                open,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
    }

    /**
     * Tek bir tamamlanmış asistan mesajına bağlı, yeniden doğrulanan yanıt
     * eylemi. Çağıran sunucunun {@code reply_allowed} kararını uygulamış olsa
     * bile kullanıcı tercihini burada bir kez daha kontrol ederiz.
     */
    public static NotificationCompat.Action inlineReplyActionFor(
            Context context, int conversationId, String sourceId,
            long replyToMessageId, int sourceNotificationId) {
        return inlineReplyActionFor(
                context, conversationId, sourceId, replyToMessageId,
                null, sourceNotificationId);
    }

    public static NotificationCompat.Action inlineReplyActionFor(
            Context context, int conversationId, String sourceId,
            long replyToMessageId, String sourceNotificationTag,
            int sourceNotificationId) {
        if (context == null || conversationId <= 0
                || replyToMessageId <= 0L
                || sourceNotificationId <= 0
                || !NotificationPreferences.inlineReplyEnabled(context)) {
            return null;
        }
        // İlk Keystore anahtar üretimini RemoteInput receiver'ın 10 saniyelik
        // cold path'ine bırakma. Hazırlanamazsa yanıt eylemi hiç gösterilmez.
        if (!NotificationReplyOutbox.prepare(context)) {
            return null;
        }
        String cleanSource = String.valueOf(
                sourceId == null ? "" : sourceId).trim();
        if (cleanSource.isEmpty() || cleanSource.length() > 160) {
            return null;
        }
        String replyRequestId = inlineReplyRequestId(
                conversationId, replyToMessageId, cleanSource);
        RemoteInput remoteInput = new RemoteInput.Builder(EXTRA_REPLY_KEY)
                .setLabel("Yanıtınız")
                .setAllowFreeFormInput(true)
                .build();
        Intent reply = new Intent(context, ChatReplyReceiver.class)
                .setPackage(context.getPackageName())
                .setAction(ACTION_INLINE_REPLY + "." + replyRequestId)
                .putExtra(EXTRA_CONVERSATION_ID, conversationId)
                .putExtra(EXTRA_REPLY_REQUEST_ID, replyRequestId)
                .putExtra(EXTRA_REPLY_SOURCE_ID, cleanSource)
                .putExtra(EXTRA_REPLY_TO_MESSAGE_ID, replyToMessageId)
                .putExtra(EXTRA_SOURCE_NOTIFICATION_ID,
                        sourceNotificationId)
                .putExtra(EXTRA_SOURCE_NOTIFICATION_TAG,
                        safeNotificationTag(sourceNotificationTag));
        int flags = PendingIntent.FLAG_UPDATE_CURRENT
                | PendingIntent.FLAG_ONE_SHOT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // RemoteInput sonuçlarını sistemin açık Intent'e ekleyebilmesi
            // için Android 12+ üzerinde yalnız bu açık PendingIntent mutable.
            flags |= PendingIntent.FLAG_MUTABLE;
        }
        PendingIntent pending = PendingIntent.getBroadcast(
                context,
                Math.floorMod(replyRequestId.hashCode(), Integer.MAX_VALUE),
                reply,
                flags);
        return new NotificationCompat.Action.Builder(
                R.drawable.ic_stat_divan,
                "Yanıtla",
                pending)
                .addRemoteInput(remoteInput)
                .setAllowGeneratedReplies(false)
                .setSemanticAction(
                        NotificationCompat.Action.SEMANTIC_ACTION_REPLY)
                .setAuthenticationRequired(true)
                .setShowsUserInterface(false)
                .build();
    }

    static String inlineReplyRequestId(
            int conversationId, long replyToMessageId, String sourceId) {
        String material = conversationId + "|" + replyToMessageId
                + "|" + String.valueOf(sourceId);
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(material.getBytes(StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder("notify-reply-");
            // 192 bit, request kimliği çakışmalarını pratikte olanaksız kılar
            // ve sunucunun 128 karakter sınırının epey altında kalır.
            for (int index = 0; index < 24; index++) {
                value.append(String.format("%02x", digest[index] & 0xff));
            }
            return value.toString();
        } catch (Exception impossible) {
            // SHA-256 bütün desteklenen Android sürümlerinde zorunludur.
            return "notify-reply-"
                    + Integer.toHexString(material.hashCode())
                    + "-" + conversationId + "-" + replyToMessageId;
        }
    }

    public static void cancelNotification(
            Context context, int notificationId) {
        cancelNotification(context, null, notificationId);
    }

    public static void cancelNotification(
            Context context, String notificationTag,
            int notificationId) {
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null && notificationId > 0) {
            if (notificationTag == null || notificationTag.isEmpty()) {
                manager.cancel(notificationId);
            } else {
                manager.cancel(notificationTag, notificationId);
            }
        }
    }

    static String safeNotificationTag(String raw) {
        String value = String.valueOf(raw == null ? "" : raw).trim();
        if (value.length() > 160
                || !value.matches("[A-Za-z0-9][A-Za-z0-9._:\\-]{0,159}")) {
            return "";
        }
        return value;
    }

    private static boolean notify(
            Context context, int conversationId,
            Notification.Builder builder) {
        if (!NotificationPreferences.channelEnabled(context, CHANNEL_ID)) {
            return false;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return false;
        }
        manager.notify(
                notificationTag(conversationId),
                notificationId(conversationId), builder.build());
        return true;
    }

    private static String notificationTag(int conversationId) {
        return NOTIFICATION_TAG_PREFIX + conversationId;
    }

    private static int notificationId(int conversationId) {
        return BASE_NOTIFICATION_ID + Math.abs(conversationId % 100000);
    }

}
