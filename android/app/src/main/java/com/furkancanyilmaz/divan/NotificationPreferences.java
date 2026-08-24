package com.furkancanyilmaz.divan;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

/**
 * Android bildirimlerinin tek tercih ve izin kapısı.
 *
 * <p>Bildirim izni, Divan'ın içerik gösterebileceği anlamına gelmez.
 * Tamamlanma bildirimi ile hassas içerik önizlemesi birbirinden ayrı,
 * varsayılanı kapalı tercihlerdir.</p>
 */
public final class NotificationPreferences {

    static final String PREFERENCES = "divan_android_settings";
    static final String COMPLETION_KEY =
            "neutral_completion_notifications";
    static final String PREVIEW_KEY =
            "notification_content_previews";
    static final String INLINE_REPLY_KEY =
            "notification_inline_reply";

    private NotificationPreferences() {
    }

    private static SharedPreferences preferences(Context context) {
        return context.getApplicationContext().getSharedPreferences(
                PREFERENCES, Context.MODE_PRIVATE);
    }

    public static boolean completionEnabled(Context context) {
        return preferences(context).getBoolean(COMPLETION_KEY, false);
    }

    public static boolean previewsEnabled(Context context) {
        return completionEnabled(context)
                && preferences(context).getBoolean(PREVIEW_KEY, false);
    }

    /**
     * Bildirimden serbest metin yanıtı, tamamlanma bildiriminden ve içerik
     * önizlemesinden ayrı bir açık tercihtir. Sunucu tarafındaki PIN, misafir
     * ve güvenlik kapıları bunun üstüne ayrıca uygulanır.
     */
    public static boolean inlineReplyEnabled(Context context) {
        return completionEnabled(context)
                && preferences(context).getBoolean(
                        INLINE_REPLY_KEY, false);
    }

    public static boolean setCompletionEnabled(
            Context context, boolean enabled) {
        return preferences(context).edit()
                .putBoolean(COMPLETION_KEY, enabled)
                .commit();
    }

    public static boolean setPreviewsEnabled(
            Context context, boolean enabled) {
        return preferences(context).edit()
                .putBoolean(PREVIEW_KEY, enabled)
                .commit();
    }

    public static boolean setInlineReplyEnabled(
            Context context, boolean enabled) {
        return preferences(context).edit()
                .putBoolean(INLINE_REPLY_KEY, enabled)
                .commit();
    }

    /** Sistem ana bildirimi tamamen engelliyorsa false. */
    public static boolean systemPermissionGranted(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && context.checkSelfPermission(
                        Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            return false;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        return manager != null && manager.areNotificationsEnabled();
    }

    /** Oluşturulmuş belirli bir kanal kullanıcı tarafından kapatılmış mı? */
    public static boolean channelEnabled(
            Context context, String channelId) {
        if (!systemPermissionGranted(context)) {
            return false;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return true;
        }
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        NotificationChannel channel = manager == null
                ? null : manager.getNotificationChannel(channelId);
        return channel == null
                || channel.getImportance() != NotificationManager.IMPORTANCE_NONE;
    }
}
