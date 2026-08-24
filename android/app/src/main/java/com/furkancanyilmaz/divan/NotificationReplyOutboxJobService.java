package com.furkancanyilmaz.divan;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

import org.json.JSONObject;

import java.io.File;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Şifreli bildirim yanıtı outbox'ını kalıcı sohbet kuyruğuna aktarır.
 *
 * <p>JobInfo yalnız sabit zamanlama bilgisi taşır; kullanıcı metni ve sohbet
 * bağlamı şifreli dosyadan okunur. Ağ/sunucu kesintisi ve 5xx geçicidir.
 * Sıradan 4xx retleri fail-closed terminaldir. Güvenlik kapısının uygulamada
 * ele alınmasını istediği iki 409 yanıtı ise silinmez: ciphertext ayrı bir
 * {@code needs_app} durumuna taşınır ve ancak kullanıcı kilitli olmayan
 * normal sohbet kutusuna geri almayı onaylarsa çözülür. Başarılı kabulde aynı
 * request kimliği sunucuda exact-once sınırı olur.</p>
 */
public final class NotificationReplyOutboxJobService extends JobService {

    private static final int JOB_ID = 0x44524f; // DRO
    private static final long BACKOFF_MS = 30_000L;
    private static final int MAX_RECORDS_PER_RUN = 32;
    private final ExecutorService executor =
            Executors.newSingleThreadExecutor();
    private final AtomicInteger generation = new AtomicInteger();
    private volatile Future<?> running;

    /** Pending içerik varsa normal, persisted JobScheduler penceresi kurar. */
    public static boolean scheduleIfPending(Context context) {
        if (context == null
                || !NotificationReplyOutbox.hasPending(context)) {
            return true;
        }
        return schedule(context);
    }

    static boolean schedule(Context context) {
        Context app = context.getApplicationContext();
        JobScheduler scheduler = (JobScheduler)
                app.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) {
            return false;
        }
        ComponentName component = new ComponentName(
                app, NotificationReplyOutboxJobService.class);
        JobInfo job = new JobInfo.Builder(JOB_ID, component)
                .setPersisted(true)
                .setMinimumLatency(0L)
                .setOverrideDeadline(1_000L)
                .setBackoffCriteria(
                        BACKOFF_MS, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .build();
        try {
            return scheduler.schedule(job) == JobScheduler.RESULT_SUCCESS;
        } catch (RuntimeException ignored) {
            // İçerik loglanmaz; dosya uygulama/boot açılışında yeniden bulunur.
            return false;
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        if (!NotificationReplyOutbox.hasPending(getApplicationContext())) {
            return false;
        }
        int run = generation.incrementAndGet();
        running = executor.submit(() -> drain(params, run));
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        generation.incrementAndGet();
        Future<?> task = running;
        if (task != null) {
            task.cancel(true);
        }
        // Şifreli dosyalar silinmediği sürece JobScheduler backoff uygular.
        return NotificationReplyOutbox.hasPending(getApplicationContext());
    }

    @Override
    public void onDestroy() {
        generation.incrementAndGet();
        Future<?> task = running;
        if (task != null) {
            task.cancel(true);
        }
        executor.shutdownNow();
        super.onDestroy();
    }

    private void drain(JobParameters params, int run) {
        boolean retry = false;
        try {
            String[] server;
            try {
                server = DivanLocalApi.startServer(
                        getApplicationContext());
            } catch (Exception failure) {
                server = new String[0];
            }
            if (server.length != 2) {
                retry = true;
            } else {
                int port = Integer.parseInt(server[0]);
                String token = server[1];
                List<File> pending = NotificationReplyOutbox.pendingFiles(
                        getApplicationContext());
                int processed = 0;
                for (File file : pending) {
                    if (generation.get() != run
                            || Thread.currentThread().isInterrupted()) {
                        retry = true;
                        break;
                    }
                    if (processed++ >= MAX_RECORDS_PER_RUN) {
                        retry = true;
                        break;
                    }
                    DrainResult result = deliverOne(
                            file, port, token);
                    if (result == DrainResult.TRANSIENT) {
                        retry = true;
                    }
                }
            }
        } catch (Exception ignored) {
            // Hata ayrıntıları plaintext veya yerel token taşıyabilir.
            retry = true;
        } finally {
            boolean pending = NotificationReplyOutbox.hasPending(
                    getApplicationContext());
            if (generation.get() == run) {
                jobFinished(params, retry || pending);
            }
        }
    }

    private DrainResult deliverOne(File file, int port, String token) {
        NotificationReplyOutbox.Record record;
        try {
            record = NotificationReplyOutbox.read(file);
        } catch (Exception corrupt) {
            // Tag/schema bozuksa içerik kullanılamaz; fail-closed temizle.
            if (!NotificationReplyOutbox.delete(file)) {
                return DrainResult.TRANSIENT;
            }
            ChatNotificationController.showError(
                    getApplicationContext(), 0, "Divan", "", "");
            return DrainResult.TERMINAL;
        }

        try {
            JSONObject payload = new JSONObject();
            payload.put("conversation_id", record.conversationId);
            payload.put("message", record.message);
            payload.put("request_id", record.requestId);
            payload.put("source_id", record.sourceId);
            payload.put("reply_to", record.replyTo);
            DivanLocalApi.Result response = DivanLocalApi.postDetailed(
                    port,
                    token,
                    "/api/notification-reply",
                    payload.toString(),
                    4_000,
                    6_000);
            if (response == null || response.code >= 500
                    || response.code < 200
                    || response.code >= 300 && response.code < 400) {
                return DrainResult.TRANSIENT;
            }
            if (response.code >= 400 && response.code < 500) {
                if (isSafetyNeedsAppResponse(
                        response.code, response.body)) {
                    return retainForApp(record);
                }
                return terminalReject(record);
            }
            JSONObject accepted = response.body.isEmpty()
                    ? new JSONObject() : new JSONObject(response.body);
            if (!accepted.optBoolean("accepted", false)
                    || !record.requestId.equals(
                            accepted.optString("request_id", ""))) {
                // Belirsiz 2xx, kesin kabul sayılmaz; ciphertext korunur.
                return DrainResult.TRANSIENT;
            }

            // HTTP cevabı ancak SQLite commit'inden sonra gelir. Cevap
            // kaybolursa aynı request id sonraki POST'ta duplicate kabul olur.
            ResponseKeeperJobService.schedule(getApplicationContext());
            if (!NotificationReplyOutbox.delete(record.file)) {
                return DrainResult.TRANSIENT;
            }
            ChatNotificationController.cancelNotification(
                    getApplicationContext(),
                    record.sourceNotificationTag,
                    record.sourceNotificationId);
            ChatNotificationController.showPending(
                    getApplicationContext(), record.conversationId,
                    "Divan", "", record.requestId);
            return DrainResult.ACCEPTED;
        } catch (Exception ignored) {
            return DrainResult.TRANSIENT;
        }
    }

    /**
     * Makine-okunur güvenlik kodu birincil sözleşmedir. İki eski sabit metin
     * yalnız daha önce paketlenmiş sunucularla geriye uyumluluk içindir.
     * Diğer bağlam/çakışma 409'ları terminal kalır; geniş bir "güven"
     * eşleşmesi yanlış yanıtları sonsuza kadar saklamaz.
     */
    static boolean isSafetyNeedsAppResponse(int code, String body) {
        if (code != 409 || body == null || body.isEmpty()) {
            return false;
        }
        try {
            JSONObject response = new JSONObject(body);
            if ("notification_reply_requires_app".equals(
                    response.optString("error_code", ""))) {
                return true;
            }
            String error = response.optString("error", "");
            return "bu yanıt güvenli biçimde uygulama içinde ele alınmalı"
                    .equals(error)
                    || "güvenlik takibi olan görüşme uygulamada açılmalı"
                    .equals(error);
        } catch (Exception ignored) {
            return false;
        }
    }

    private DrainResult retainForApp(
            NotificationReplyOutbox.Record record) {
        // Önce yeni şifreli durum fsync edilir; başarısızsa pending kaynak
        // yerinde kalır ve JobScheduler backoff ile tekrar dener.
        if (!NotificationReplyOutbox.moveToNeedsApp(record)) {
            return DrainResult.TRANSIENT;
        }
        ChatNotificationController.cancelNotification(
                getApplicationContext(),
                record.sourceNotificationTag,
                record.sourceNotificationId);
        ChatNotificationController.dismissPendingIfRequestMatches(
                getApplicationContext(), record.conversationId,
                record.requestId);
        ChatNotificationController.showNeedsApp(
                getApplicationContext(), record.conversationId,
                record.requestId);
        return DrainResult.NEEDS_APP;
    }

    private DrainResult terminalReject(
            NotificationReplyOutbox.Record record) {
        if (!NotificationReplyOutbox.delete(record.file)) {
            return DrainResult.TRANSIENT;
        }
        ChatNotificationController.cancelNotification(
                getApplicationContext(),
                record.sourceNotificationTag,
                record.sourceNotificationId);
        boolean dismissed =
                ChatNotificationController.dismissPendingIfRequestMatches(
                        getApplicationContext(), record.conversationId,
                        record.requestId);
        if (dismissed) {
            ChatNotificationController.showError(
                    getApplicationContext(), record.conversationId,
                    "Divan", "", record.requestId);
        }
        return DrainResult.TERMINAL;
    }

    private enum DrainResult {
        ACCEPTED,
        NEEDS_APP,
        TERMINAL,
        TRANSIENT
    }
}
