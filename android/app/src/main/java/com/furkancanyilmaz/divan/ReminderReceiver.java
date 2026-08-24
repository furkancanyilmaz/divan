package com.furkancanyilmaz.divan;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;

import androidx.core.app.NotificationCompat;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Kullanıcının açıkça kurduğu görev hatırlatıcıları.
 *
 * <p>Görüşmesiz görevler sabit, nötr bir bildirimdir. Görüşmeye bağlı ve
 * önceden AI tarafından hazırlanmış süre-sonu mesajları ise kısa bir yerel
 * POST ile tam vaktinde SQLite'a açığa çıkarılır; receiver model çalıştırmaz.
 * Görev/persona metni kilit ekranına, logcat'e veya SharedPreferences'a
 * yazılmaz.</p>
 */
public final class ReminderReceiver extends BroadcastReceiver {

    public static final String EXTRA_ID = "divan.reminder.id";
    public static final String EXTRA_CONV = "divan.reminder.conv";
    public static final String ACTION_PREFIX =
            "com.furkancanyilmaz.divan.REMINDER_";
    public static final String PREFS_KEY = "scheduled_reminders";

    private static final String PREFS_NAME = "divan_reminder_alarms_v2";
    private static final String LEGACY_PREFS_NAME = "divan_reminder_alarms";
    private static final String REMINDER_CHANNEL = "divan_reminders_v2";
    private static final int SUMMARY_NOTIFICATION_ID = 3401;
    private static final Object STORE_LOCK = new Object();
    private static final long RECEIVER_FINISH_MS = 8_500L;
    private static final long RETRY_BASE_MS = 30_000L;
    private static final long RETRY_MAX_MS = 15L * 60L * 1000L;
    private static final ExecutorService DELIVERY_EXECUTOR =
            Executors.newFixedThreadPool(2);
    private static final Set<String> DELIVERIES_IN_FLIGHT =
            ConcurrentHashMap.newKeySet();
    private static final ScheduledExecutorService FINISH_EXECUTOR =
            Executors.newSingleThreadScheduledExecutor();

    @Override
    public void onReceive(Context context, Intent intent) {
        String reminderId = intent == null
                ? null : intent.getStringExtra(EXTRA_ID);
        if ((reminderId == null || reminderId.isEmpty())
                && intent != null && intent.getAction() != null
                && intent.getAction().startsWith(ACTION_PREFIX)) {
            reminderId = intent.getAction().substring(ACTION_PREFIX.length());
        }
        String safeId = safeReminderActionId(reminderId);
        if (safeId.isEmpty()) {
            return;
        }
        JSONObject entry = readStoredEntry(context, safeId);
        if (entry == null) {
            // İptal edilmiş, eşitlemeyle silinmiş veya daha önce teslim
            // edilmiş bayat PendingIntent.
            return;
        }
        long conversationId = intent == null ? 0L
                : intent.getLongExtra(EXTRA_CONV, 0L);
        if (conversationId <= 0L && entry != null) {
            conversationId = entry.optLong("conv", 0L);
        }
        long reminderRowId = reminderRowId(safeId);
        long privacyGeneration =
                ChatNotificationController.notificationPrivacyGeneration();
        if (conversationId > 0L && reminderRowId > 0L) {
            if (!DELIVERIES_IN_FLIGHT.add(safeId)) {
                return;
            }
            Context app = context.getApplicationContext();
            PendingResult pending = goAsync();
            AtomicBoolean finished = new AtomicBoolean(false);
            FINISH_EXECUTOR.schedule(
                    () -> finishOnce(pending, finished),
                    RECEIVER_FINISH_MS,
                    TimeUnit.MILLISECONDS);
            long finalConversationId = conversationId;
            DELIVERY_EXECUTOR.execute(() -> {
                try {
                    deliverScheduledMessage(
                            app, safeId, reminderRowId,
                            finalConversationId, entry,
                            privacyGeneration);
                } finally {
                    DELIVERIES_IN_FLIGHT.remove(safeId);
                    finishOnce(pending, finished);
                }
            });
            return;
        }
        if (postNotification(
                context, safeId, conversationId, 1,
                0L, "", false, "", "", false,
                privacyGeneration)) {
            removeStored(context, safeId);
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
                REMINDER_CHANNEL,
                "Divan hatırlatıcıları",
                NotificationManager.IMPORTANCE_DEFAULT);
        channel.setDescription(
                "Açıkça kurduğunuz görevlerin zamanı geldiğinde nötr bildirim");
        manager.createNotificationChannel(channel);
    }

    public static boolean schedule(
            Context context, String id, String title, String body,
            long afterSeconds) {
        return schedule(context, id, title, body, afterSeconds, 0L);
    }

    public static boolean schedule(
            Context context, String id, String title, String body,
            long afterSeconds, long conversationId) {
        String safeId = safeReminderActionId(id);
        if (safeId.isEmpty()) {
            return false;
        }
        long delayMs = Math.max(1000L, Math.min(
                afterSeconds, 366L * 24L * 3600L) * 1000L);
        long dueAtMs = System.currentTimeMillis() + delayMs;
        // title/body bilinçli olarak saklanmaz: görev metni cihaz tercihlerine
        // ve alarm PendingIntent'ine kopyalanmaz.
        store(context, safeId, dueAtMs, conversationId, 0, dueAtMs);
        return scheduleAlarm(context, safeId, dueAtMs, conversationId);
    }

    public static void cancel(Context context, String id) {
        String safeId = safeReminderActionId(id);
        if (safeId.isEmpty()) {
            return;
        }
        removeStored(context, safeId);
        AlarmManager alarms = (AlarmManager)
                context.getSystemService(Context.ALARM_SERVICE);
        if (alarms != null) {
            alarms.cancel(pendingIntent(context, safeId, 0L));
        }
        NotificationManager notifications = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (notifications != null) {
            notifications.cancel(
                    ConversationNotificationSupport.reminderTag(safeId),
                    notificationId(safeId));
        }
    }

    /** Boot/güncelleme/izin dönüşünde kayıtları yeniden kurar. */
    public static void rescheduleAll(Context context) {
        migrateLegacyStore(context);
        JSONObject stored = readStored(context);
        JSONArray names = stored.names();
        if (names == null) {
            return;
        }
        long now = System.currentTimeMillis();
        List<String> staleIds = new ArrayList<>();
        int overdueOffset = 0;
        for (int index = 0; index < names.length(); index++) {
            String id = names.optString(index, "");
            JSONObject entry = stored.optJSONObject(id);
            if (entry == null) {
                continue;
            }
            long due = entry.optLong("dueAtMs", 0L);
            long conv = entry.optLong("conv", 0L);
            long retryAt = Math.max(
                    due, entry.optLong("retryAtMs", due));
            if (due <= 0L) {
                staleIds.add(id);
                continue;
            }
            long alarmAt = retryAt <= now
                    ? now + 1_000L + (overdueOffset++ * 250L)
                    : retryAt;
            // Her gecikmiş kaydı kendi kimliğiyle teslim et. Tek bir özet
            // bildirimi, hazırlanmış AI mesajlarının sohbete yazılmasını
            // atlayamaz.
            scheduleAlarm(context, id, alarmAt, conv);
        }
        for (String id : staleIds) {
            removeStored(context, id);
        }
    }

    /**
     * Önceden üretilmiş zamanlanmış mesajı transaction içinde sohbete
     * açtırır. Bu yol yalnız SQLite teslimini bekler; model çağrısı endpoint
     * içinde yapılmaz.
     */
    private static void deliverScheduledMessage(
            Context context, String safeId, long reminderRowId,
            long storedConversationId, JSONObject storedEntry,
            long privacyGeneration) {
        try {
            String[] server = DivanLocalApi.startServer(context);
            if (server.length != 2) {
                retryDelivery(context, safeId, storedEntry);
                return;
            }
            JSONObject payload = new JSONObject();
            payload.put("id", reminderRowId);
            payload.put("allow_preview",
                    NotificationPreferences.previewsEnabled(context));
            DivanLocalApi.Result result = DivanLocalApi.postDetailed(
                    Integer.parseInt(server[0]),
                    server[1],
                    "/api/reminders/deliver",
                    payload.toString(),
                    2_000,
                    3_500);
            if (result == null) {
                retryDelivery(context, safeId, storedEntry);
                return;
            }
            if (result.code == 404 || result.code == 410) {
                // Sunucuda silinen/iptal edilen hatırlatıcıya ait bayat alarm.
                removeStored(context, safeId);
                return;
            }
            JSONObject response = result.body.isEmpty()
                    ? new JSONObject() : new JSONObject(result.body);
            String state = response.optString("state", "");
            if ("suppressed".equals(state) || "cancelled".equals(state)) {
                // Safety hold, user pause/delete or server-side cancellation
                // invalidates the already scheduled native alarm.  It must
                // disappear silently: turning it into a generic reminder
                // would contradict the user's explicit stop decision.
                removeStored(context, safeId);
                return;
            }
            if (result.code == 202 || "generating".equals(state)) {
                // Henüz tamamlanmamış içerikten asla assistant mesajı veya
                // bildirim metni üretme; hazır olduğunda aynı id ile dene.
                retryDelivery(context, safeId, storedEntry);
                return;
            }
            if (result.code < 200 || result.code >= 300) {
                retryDelivery(context, safeId, storedEntry);
                return;
            }
            long responseConversation = response.optLong(
                    "conversation_id", storedConversationId);
            if (responseConversation != storedConversationId) {
                // Yanlış görüşmeye yazma olasılığında fail closed.
                removeStored(context, safeId);
                return;
            }
            long messageId = response.optLong("message_id", 0L);
            String sourceId = response.optString("source_id", "");
            boolean deliveredAi = messageId > 0L
                    && ("completed".equals(state)
                    || "delivered".equals(state)
                    || "revealed".equals(state)
                    || response.optBoolean("delivered", false));
            boolean neutral = "neutral".equals(state)
                    || response.optBoolean("neutral", false);
            if (!deliveredAi && !neutral) {
                retryDelivery(context, safeId, storedEntry);
                return;
            }
            // A deep Schema step is an authoritative in-app interaction.
            // Fail closed even if an older/mixed server response accidentally
            // leaves the legacy preview/reply booleans enabled.
            boolean requiresInApp = response.optBoolean(
                    "requires_in_app", false);
            boolean posted = postNotification(
                    context,
                    safeId,
                    storedConversationId,
                    1,
                    deliveredAi ? messageId : 0L,
                    deliveredAi ? sourceId : "",
                    deliveredAi
                            && !requiresInApp
                            && response.optBoolean(
                                    "reply_allowed", false),
                    deliveredAi && !requiresInApp
                            ? response.optString("master_name", "") : "",
                    deliveredAi && !requiresInApp
                            ? response.optString("preview", "") : "",
                    deliveredAi
                            && !requiresInApp
                            && response.optBoolean(
                                    "preview_allowed", false),
                    privacyGeneration);
            if (!posted) {
                retryDelivery(context, safeId, storedEntry);
                return;
            }

            JSONObject ack = new JSONObject();
            ack.put("id", reminderRowId);
            ack.put("source_id", sourceId);
            ack.put("message_id", deliveredAi ? messageId : 0L);
            DivanLocalApi.Result acknowledged = DivanLocalApi.postDetailed(
                    Integer.parseInt(server[0]),
                    server[1],
                    "/api/reminders/deliver-ack",
                    ack.toString(),
                    1_500,
                    2_000);
            if (acknowledged != null && acknowledged.code >= 200
                    && acknowledged.code < 300) {
                removeStored(context, safeId);
            } else {
                // Aynı notificationId bir sonraki denemede mevcut bildirimi
                // değiştirir; DB mesajı client_event_id ile yinelenmez.
                retryDelivery(context, safeId, storedEntry);
            }
        } catch (Exception ignored) {
            retryDelivery(context, safeId, storedEntry);
        }
    }

    private static void retryDelivery(
            Context context, String id, JSONObject prior) {
        JSONObject current = readStoredEntry(context, id);
        if (current == null) {
            return;
        }
        int attempts = Math.max(
                prior == null ? 0 : prior.optInt("attempts", 0),
                current.optInt("attempts", 0)) + 1;
        int shift = Math.min(5, Math.max(0, attempts - 1));
        long delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS << shift);
        long retryAt = System.currentTimeMillis() + delay;
        long due = current.optLong("dueAtMs", retryAt);
        long conv = current.optLong("conv", 0L);
        store(context, id, due, conv, attempts, retryAt);
        scheduleAlarm(context, id, retryAt, conv);
    }

    private static long reminderRowId(String safeId) {
        String value = String.valueOf(safeId == null ? "" : safeId);
        if (value.startsWith("reminder-")) {
            value = value.substring("reminder-".length());
        }
        try {
            long parsed = Long.parseLong(value);
            return parsed > 0L ? parsed : 0L;
        } catch (NumberFormatException ignored) {
            return 0L;
        }
    }

    private static void finishOnce(
            PendingResult pending, AtomicBoolean finished) {
        if (finished.compareAndSet(false, true)) {
            pending.finish();
        }
    }

    private static boolean scheduleAlarm(
            Context context, String id, long dueAtMs,
            long conversationId) {
        AlarmManager alarms = (AlarmManager)
                context.getSystemService(Context.ALARM_SERVICE);
        if (alarms == null) {
            // Kalıcı kayıt durur; uygulama/boot açılışında yeniden denenir.
            return true;
        }
        PendingIntent pending = pendingIntent(
                context, id, conversationId);
        try {
            // ADHD/öz bakım hatırlatıcıları alarm saati veya tıbbi acil durum
            // değildir. Özel exact-alarm izni istemek yerine Doze uyumlu
            // yaklaşık teslim kullanılır.
            alarms.setAndAllowWhileIdle(
                    AlarmManager.RTC_WAKEUP, dueAtMs, pending);
            return true;
        } catch (SecurityException failure) {
            return false;
        }
    }

    private static boolean postNotification(
            Context context, String reminderId, long conversationId,
            int count, long messageId, String sourceId,
            boolean replyAllowed, String masterName, String preview,
            boolean previewAllowed, long privacyGeneration) {
        // Uygulama açıkken web görünümü due kaydını ele alır; ikinci bir OS
        // bildirimi üretme.
        if (ChatNotificationController.isAppVisible()) {
            return true;
        }
        String neutralText = count > 1
                ? count + " görev hatırlatıcınız var."
                : "Bir görev hatırlatıcınız var.";
        boolean safePreview = previewAllowed
                && NotificationPreferences.previewsEnabled(context)
                && messageId > 0L
                && conversationId > 0L
                && conversationId <= Integer.MAX_VALUE;
        String text = safePreview
                ? NotificationTextSanitizer.plainAssistantText(preview)
                : neutralText;
        if (text.isEmpty()) {
            safePreview = false;
            text = neutralText;
        }
        if (!safePreview && messageId > 0L
                && conversationId > 0L
                && conversationId <= Integer.MAX_VALUE) {
            CompletionNotificationController.dismissConversation(
                    context, (int) conversationId);
            ConversationNotificationSupport.removeConversationShortcut(
                    context, (int) conversationId);
        }
        ensureChannel(context);
        CompletionNotificationController.ensureChannels(context);
        String channelId = safePreview
                ? CompletionNotificationController.PREVIEW_CHANNEL_ID
                : REMINDER_CHANNEL;
        if (!NotificationPreferences.channelEnabled(context, channelId)) {
            return false;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return false;
        }
        PendingIntent open = openIntent(context, conversationId);
        Notification publicVersion = builder(context, REMINDER_CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentTitle("Divan")
                .setContentText("Bir hatırlatıcınız var.")
                .setContentIntent(open)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setAutoCancel(true)
                .build();
        int notificationId = safePreview
                ? CompletionNotificationController
                        .CONVERSATION_NOTIFICATION_ID
                : notificationId(reminderId);
        String notificationTag = safePreview
                ? ConversationNotificationSupport.conversationTag(
                        (int) conversationId)
                : ConversationNotificationSupport.reminderTag(reminderId);
        NotificationCompat.Builder notificationBuilder = builder(
                context, channelId)
                .setSmallIcon(R.drawable.ic_stat_divan)
                .setContentTitle("Divan")
                .setContentText(text)
                .setContentIntent(open)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setPublicVersion(publicVersion)
                .setAutoCancel(true);
        if (safePreview) {
            ConversationNotificationSupport.applySingleAssistantMessage(
                    context,
                    notificationBuilder,
                    (int) conversationId,
                    masterName,
                    text,
                    System.currentTimeMillis());
        } else {
            notificationBuilder.setCategory(
                    NotificationCompat.CATEGORY_REMINDER);
        }
        if (safePreview && replyAllowed && messageId > 0L) {
            NotificationCompat.Action reply =
                    ChatNotificationController.inlineReplyActionFor(
                            context,
                            (int) conversationId,
                            sourceId,
                            messageId,
                            notificationTag,
                            notificationId);
            if (reply != null) {
                notificationBuilder.addAction(reply);
            }
        }
        Notification notification = notificationBuilder.build();
        boolean posted = safePreview
                ? ChatNotificationController
                        .postConversationIfPrivacyStateCurrent(
                                context,
                                privacyGeneration,
                                notificationTag,
                                notificationId,
                                notification,
                                (int) conversationId,
                                masterName)
                : ChatNotificationController
                        .postIfPrivacyStateCurrent(
                                context,
                                privacyGeneration,
                                notificationTag,
                                notificationId,
                                notification,
                                false);
        // Uygulama bu dar yarış penceresinde görünür olduysa web görünümü
        // due kaydını tüketir; OS bildirimi için tekrar alarm kurma.
        return posted || ChatNotificationController.isAppVisible();
    }

    private static NotificationCompat.Builder builder(
            Context context, String channelId) {
        NotificationCompat.Builder builder =
                new NotificationCompat.Builder(context, channelId);
        if (CompletionNotificationController.PREVIEW_CHANNEL_ID.equals(
                channelId)) {
            builder.setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setDefaults(NotificationCompat.DEFAULT_ALL);
        } else {
            builder.setPriority(NotificationCompat.PRIORITY_DEFAULT);
        }
        return builder;
    }

    private static int notificationId(String reminderId) {
        return "summary".equals(reminderId)
                ? SUMMARY_NOTIFICATION_ID
                : SUMMARY_NOTIFICATION_ID
                + Math.floorMod(reminderId.hashCode(), 100000);
    }

    private static PendingIntent openIntent(
            Context context, long conversationId) {
        Intent open = new Intent(context, MainActivity.class)
                .setAction(Intent.ACTION_VIEW)
                .setData(Uri.parse(
                        conversationId > 0
                                ? "divan://notification/conversation/"
                                        + conversationId
                                : "divan://notification/reminders"))
                .setPackage(context.getPackageName())
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (conversationId > 0 && conversationId <= Integer.MAX_VALUE) {
            open.putExtra(
                    ChatNotificationController.EXTRA_CONVERSATION_ID,
                    (int) conversationId);
        }
        int requestCode = conversationId > 0
                ? (int) (conversationId % Integer.MAX_VALUE)
                : SUMMARY_NOTIFICATION_ID;
        return PendingIntent.getActivity(
                context, requestCode, open,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
    }

    private static PendingIntent pendingIntent(
            Context context, String id, long conversationId) {
        Intent intent = new Intent(context, ReminderReceiver.class)
                .setAction(ACTION_PREFIX + id)
                .putExtra(EXTRA_ID, id)
                .putExtra(EXTRA_CONV, conversationId);
        return PendingIntent.getBroadcast(
                context,
                Math.floorMod(id.hashCode(), Integer.MAX_VALUE),
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
    }

    /** Eski sürümde düz metin tutulan görevleri yalnız id/zaman/kapsamla taşı. */
    private static void migrateLegacyStore(Context context) {
        synchronized (STORE_LOCK) {
            SharedPreferences legacy = context.getApplicationContext()
                    .getSharedPreferences(
                            LEGACY_PREFS_NAME, Context.MODE_PRIVATE);
            String raw = legacy.getString(PREFS_KEY, "{}");
            JSONObject values;
            try {
                values = new JSONObject(raw);
            } catch (JSONException ignored) {
                values = new JSONObject();
            }
            JSONArray names = values.names();
            if (names != null) {
                AlarmManager alarms = (AlarmManager)
                        context.getSystemService(Context.ALARM_SERVICE);
                for (int index = 0; index < names.length(); index++) {
                    String id = safeReminderActionId(
                            names.optString(index, ""));
                    JSONObject entry = values.optJSONObject(id);
                    if (id.isEmpty() || entry == null) {
                        continue;
                    }
                    long dueAtMs = entry.optLong("dueAtMs", 0L);
                    store(context, id, dueAtMs,
                            entry.optLong("conv", 0L), 0, dueAtMs);
                    if (alarms != null) {
                        Intent old = new Intent(
                                context, ReminderReceiver.class)
                                .setAction(ACTION_PREFIX + id);
                        PendingIntent oldPending = PendingIntent.getBroadcast(
                                context, 0, old,
                                PendingIntent.FLAG_NO_CREATE
                                        | PendingIntent.FLAG_IMMUTABLE);
                        if (oldPending != null) {
                            alarms.cancel(oldPending);
                            oldPending.cancel();
                        }
                    }
                }
            }
            // Hassas eski title/body kopyalarını ancak migration commit'i
            // tamamlandıktan sonra sil.
            legacy.edit().clear().commit();
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(
                PREFS_NAME, Context.MODE_PRIVATE);
    }

    private static JSONObject readStored(Context context) {
        synchronized (STORE_LOCK) {
            String raw = prefs(context).getString(PREFS_KEY, "{}");
            try {
                return new JSONObject(raw);
            } catch (JSONException ignored) {
                return new JSONObject();
            }
        }
    }

    private static JSONObject readStoredEntry(Context context, String id) {
        return readStored(context).optJSONObject(id);
    }

    private static void store(
            Context context, String id, long dueAtMs,
            long conversationId, int attempts, long retryAtMs) {
        synchronized (STORE_LOCK) {
            JSONObject stored = readStored(context);
            JSONObject entry = new JSONObject();
            try {
                entry.put("dueAtMs", dueAtMs);
                entry.put("conv", conversationId);
                entry.put("attempts", Math.max(0, attempts));
                entry.put("retryAtMs", Math.max(dueAtMs, retryAtMs));
                stored.put(id, entry);
            } catch (JSONException ignored) {
                return;
            }
            prefs(context).edit()
                    .putString(PREFS_KEY, stored.toString())
                    .commit();
        }
    }

    private static void removeStored(Context context, String id) {
        synchronized (STORE_LOCK) {
            JSONObject stored = readStored(context);
            if (!stored.has(id)) {
                return;
            }
            stored.remove(id);
            prefs(context).edit()
                    .putString(PREFS_KEY, stored.toString())
                    .commit();
        }
    }

    private static String safeReminderActionId(String raw) {
        String value = String.valueOf(raw == null ? "" : raw)
                .replaceAll("[^A-Za-z0-9._-]", "");
        return value.length() <= 64 ? value : value.substring(0, 64);
    }
}
