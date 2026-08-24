package com.furkancanyilmaz.divan;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Cihaz yeniden başladığında kayıtlı görev hatırlatıcılarını yeniden kurar.
 * AlarmManager kayıtları yeniden başlatmada silindiği için bu alıcı,
 * SharedPreferences'taki kalıcı görev listesini okuyup alarmları tazeler;
 * süresi geçmiş görevlerin bildirimini hemen gösterir.
 */
public final class BootReminderRescheduler extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? null : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            return;
        }
        if (Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            // Etiketsiz eski sürüm bildirimleri yeni request/conv eşleşmesi
            // dışında kalmasın; yalnız bu paketin görünür bildirimleri gider.
            ChatNotificationController.purgeSensitiveNotifications(context);
        }
        ReminderReceiver.rescheduleAll(context);
        NotificationReplyOutboxJobService.scheduleIfPending(context);
        NotificationReplyOutbox.repostNeedsAppNotifications(context);
    }
}
