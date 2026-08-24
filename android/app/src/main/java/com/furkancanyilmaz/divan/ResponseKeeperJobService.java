package com.furkancanyilmaz.divan;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.os.Build;
import android.util.Base64;
import android.util.Log;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import java.io.File;
import java.security.SecureRandom;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Keeps an already accepted Divan response job moving after the activity is
 * no longer visible.
 *
 * <p>The authoritative request and response state lives in SQLite. This job
 * does not duplicate provider calls: it starts (or reuses) the same embedded
 * Python server, whose durable queue atomically resumes unfinished work. The
 * system JobScheduler supplies the process lifetime and wake lock while this
 * small monitor is active, without requiring a permanent foreground-service
 * notification.</p>
 */
public final class ResponseKeeperJobService extends JobService {
    private static final String TAG = "DivanResponseKeeper";
    private static final int JOB_ID = 0x444956;
    private static final long POLL_INTERVAL_MS = 4_000L;
    private static final long MAX_RUN_MS = 8L * 60L * 1_000L;
    private static final int MAX_PROBE_FAILURES = 3;
    private static final Object SCHEDULER_HANDSHAKE = new Object();
    private static long pendingSignalGeneration = 0L;
    private static boolean jobServiceRunning = false;
    private static boolean scheduleInFlight = false;

    private final ExecutorService executor =
            Executors.newSingleThreadExecutor();
    private final AtomicInteger runGeneration = new AtomicInteger();
    private volatile Future<?> runningTask;

    /**
     * Schedule idempotently. Expedited quota is used only for a real pending
     * response, and transparently falls back to an ordinary immediate job.
     */
    public static void schedule(Context context) {
        Context app = context.getApplicationContext();
        synchronized (SCHEDULER_HANDSHAKE) {
            // Every WebView signal is recorded even when Android already has
            // this job pending/running. The worker compares this generation
            // while finishing, so a signal racing with IDLE cannot disappear.
            pendingSignalGeneration++;
            if (jobServiceRunning || scheduleInFlight) {
                return;
            }
            scheduleInFlight = true;
        }
        try {
            scheduleSystemJob(app);
        } finally {
            synchronized (SCHEDULER_HANDSHAKE) {
                scheduleInFlight = false;
            }
        }
    }

    private static void scheduleSystemJob(Context app) {
        JobScheduler scheduler = (JobScheduler)
                app.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) {
            return;
        }

        ComponentName component = new ComponentName(
                app, ResponseKeeperJobService.class);
        int result = JobScheduler.RESULT_FAILURE;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            try {
                result = scheduler.schedule(baseJob(component)
                        .setExpedited(true)
                        .build());
            } catch (RuntimeException failure) {
                Log.w(TAG,
                        "Hızlandırılmış Android işi kullanılamadı",
                        failure);
            }
            if (result == JobScheduler.RESULT_SUCCESS) {
                return;
            }
        }
        try {
            result = scheduler.schedule(baseJob(component)
                    .setMinimumLatency(0)
                    .setOverrideDeadline(1_000L)
                    .build());
        } catch (RuntimeException failure) {
            Log.w(TAG, "Android arka plan işi kurulamadı", failure);
            result = JobScheduler.RESULT_FAILURE;
        }
        if (result != JobScheduler.RESULT_SUCCESS) {
            Log.w(TAG, "Android arka plan yanıt işi planlanamadı");
        }
    }

    private static JobInfo.Builder baseJob(ComponentName component) {
        return new JobInfo.Builder(JOB_ID, component)
                .setPersisted(true)
                .setBackoffCriteria(
                        15_000L, JobInfo.BACKOFF_POLICY_EXPONENTIAL);
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        synchronized (SCHEDULER_HANDSHAKE) {
            jobServiceRunning = true;
        }
        int generation = runGeneration.incrementAndGet();
        runningTask = executor.submit(
                () -> keepResponseAlive(params, generation));
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        runGeneration.incrementAndGet();
        synchronized (SCHEDULER_HANDSHAKE) {
            jobServiceRunning = false;
        }
        Future<?> task = runningTask;
        if (task != null) {
            task.cancel(true);
        }
        // The durable SQLite row remains authoritative; ask Android to give
        // it another execution window if this one was interrupted.
        return true;
    }

    @Override
    public void onDestroy() {
        runGeneration.incrementAndGet();
        synchronized (SCHEDULER_HANDSHAKE) {
            jobServiceRunning = false;
        }
        executor.shutdownNow();
        super.onDestroy();
    }

    private void keepResponseAlive(
            JobParameters params, int generation) {
        boolean reschedule = false;
        long idleFinishSignal = -1L;
        int serverPort = -1;
        String sessionToken = "";
        try {
            SecretStore.initialize(getApplicationContext());
            String requestedToken = randomToken();
            File dataDirectory = new File(
                    getNoBackupFilesDir(), "divan-data");
            PyObject bridge = Python.getInstance()
                    .getModule("android_entry");
            String[] launch = bridge.callAttr("start_server",
                    dataDirectory.getAbsolutePath(), requestedToken)
                    .toString().split("\\|", 2);
            if (launch.length == 2) {
                serverPort = Integer.parseInt(launch[0]);
                sessionToken = launch[1];
            }
            long deadline = System.currentTimeMillis() + MAX_RUN_MS;
            int failures = 0;
            int initialIdleProbes = 0;
            boolean sawActive = false;
            long observedSignal = signalGeneration();

            while (runGeneration.get() == generation
                    && System.currentTimeMillis() < deadline) {
                long currentSignal = signalGeneration();
                if (currentSignal != observedSignal) {
                    observedSignal = currentSignal;
                    initialIdleProbes = 0;
                    sawActive = false;
                }
                ProbeState state = probeJobs(bridge);
                // Sohbet yanıtı bittiği anda bildir; seans notu, yaşayan
                // harita veya başka bir artalan işinin de bitmesini bekleme.
                // Outbox cursor'ı bu ucuz yoklamayı idempotent yapar.
                CompletionNotificationController.deliverPending(
                        getApplicationContext(), serverPort, sessionToken);
                if (state == null) {
                    failures++;
                    if (failures >= MAX_PROBE_FAILURES) {
                        reschedule = true;
                        break;
                    }
                } else {
                    failures = 0;
                    if (state == ProbeState.IDLE) {
                        // JavaScript deliberately signals Android before the
                        // POST starts, so a fast JobService may briefly beat
                        // the SQLite insert. Give that hand-off three probes;
                        // after an active row has been seen, one idle result
                        // is enough to finish.
                        initialIdleProbes++;
                        if (sawActive || initialIdleProbes >= 3) {
                            // Confirm against the durable queue immediately
                            // before the lifecycle handshake. A new signal
                            // during this read changes the generation and the
                            // finalizer converts completion into reschedule.
                            long beforeConfirm = signalGeneration();
                            ProbeState confirmed = probeJobs(bridge);
                            long afterConfirm = signalGeneration();
                            if (beforeConfirm != afterConfirm) {
                                observedSignal = afterConfirm;
                                initialIdleProbes = 0;
                                sawActive = false;
                                continue;
                            }
                            if (confirmed == ProbeState.ACTIVE) {
                                observedSignal = afterConfirm;
                                initialIdleProbes = 0;
                                sawActive = true;
                                continue;
                            }
                            if (confirmed
                                    == ProbeState.WAITING_PROVIDER) {
                                reschedule = true;
                                break;
                            }
                            if (confirmed == null) {
                                failures++;
                                if (failures >= MAX_PROBE_FAILURES) {
                                    reschedule = true;
                                    break;
                                }
                                continue;
                            }
                            idleFinishSignal = afterConfirm;
                            reschedule = false;
                            break;
                        }
                    } else {
                        initialIdleProbes = 0;
                    }
                    if (state == ProbeState.WAITING_PROVIDER) {
                        // An unavailable local/cloud provider should not hold
                        // a wake lock continuously. Persist the scheduler job
                        // with exponential backoff; its next window starts the
                        // durable Python queue again.
                        reschedule = true;
                        break;
                    }
                    if (state == ProbeState.ACTIVE) {
                        sawActive = true;
                    }
                }
                Thread.sleep(POLL_INTERVAL_MS);
            }
            if (runGeneration.get() == generation
                    && System.currentTimeMillis() >= deadline) {
                reschedule = true;
            }
            if (!reschedule && idleFinishSignal >= 0) {
                // Yalnız terminal sohbet isteklerinden oluşan kalıcı outbox
                // işlenir. Başka bir seans/harita işi eski bir sohbet
                // bildirimini yanlışlıkla tetikleyemez.
                CompletionNotificationController.deliverPending(
                        getApplicationContext(), serverPort, sessionToken);
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            reschedule = true;
        } catch (Throwable failure) {
            Log.w(TAG, "Arka plan yanıt koruması yeniden denenecek",
                    failure);
            reschedule = true;
        } finally {
            finishJob(params, generation, reschedule,
                    idleFinishSignal);
        }
    }

    private long signalGeneration() {
        synchronized (SCHEDULER_HANDSHAKE) {
            return pendingSignalGeneration;
        }
    }

    static String lastDelivered(Context context) {
        return NotificationDeliveryLedger.latestDelivered(context);
    }

    /**
     * Bir yanıtın bildirime taşındığını kalıcı olarak işaretler.
     * {@link ChatReplyReceiver} bildirimden gelen yanıtı kendisi
     * gösterdiğinde burayı da işaretler; böylece aynı cevap arka plan işi
     * tarafından ikinci kez bildirime düşmez.
     */
    static void markDelivered(Context context, String requestId) {
        if (requestId == null || requestId.isEmpty()) {
            return;
        }
        NotificationDeliveryLedger.markRequest(context, requestId);
    }

    private void finishJob(
            JobParameters params, int generation, boolean reschedule,
            long idleFinishSignal) {
        synchronized (SCHEDULER_HANDSHAKE) {
            if (runGeneration.get() != generation) {
                return;
            }
            boolean signalArrivedDuringIdleFinish =
                    idleFinishSignal >= 0
                    && pendingSignalGeneration != idleFinishSignal;
            jobServiceRunning = false;
            // Keep jobFinished in the same handshake as the generation
            // comparison. A later schedule() call therefore either makes
            // this run reschedule, or observes no running service and submits
            // a fresh system job; there is no unguarded gap between them.
            jobFinished(
                    params,
                    reschedule || signalArrivedDuringIdleFinish);
        }
    }

    private ProbeState probeJobs(PyObject bridge) {
        try {
            String state = bridge.callAttr(
                    "active_job_state").toString();
            if ("active".equals(state)) {
                return ProbeState.ACTIVE;
            }
            if ("waiting_provider".equals(state)) {
                return ProbeState.WAITING_PROVIDER;
            }
            return "idle".equals(state) ? ProbeState.IDLE : null;
        } catch (Exception ignored) {
            return null;
        }
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        new SecureRandom().nextBytes(bytes);
        return Base64.encodeToString(
                bytes, Base64.URL_SAFE
                        | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private enum ProbeState {
        ACTIVE,
        WAITING_PROVIDER,
        IDLE
    }
}
