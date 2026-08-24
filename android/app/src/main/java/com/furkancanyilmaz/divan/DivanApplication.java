package com.furkancanyilmaz.divan;

import com.chaquo.python.android.PyApplication;

/** Uygulama süreci açıldığında yarım kalmış şifreli teslimleri kurtarır. */
public final class DivanApplication extends PyApplication {

    @Override
    public void onCreate() {
        super.onCreate();
        if (NotificationPreferences.inlineReplyEnabled(this)) {
            // Süreç açılışında hazırlayarak BroadcastReceiver cold path'inde
            // donanımsal anahtar üretimi bırakma.
            NotificationReplyOutbox.prepare(this);
        }
        NotificationReplyOutboxJobService.scheduleIfPending(this);
        // Güvenlik 409'unda saklanan ciphertext tekrar POST edilmez; süreç
        // yeniden açıldığında yalnız nötr, görüşmeye giden eylem geri kurulur.
        NotificationReplyOutbox.repostNeedsAppNotifications(this);
    }
}
