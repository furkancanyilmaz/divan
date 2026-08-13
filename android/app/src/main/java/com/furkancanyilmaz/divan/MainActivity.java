package com.furkancanyilmaz.divan;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public final class MainActivity extends Activity {
    private static final int REQUEST_OPEN_FILE = 4101;
    private static final int REQUEST_SAVE_FILE = 4102;
    private static final int REQUEST_NOTIFICATION_PERMISSION = 4103;
    private static final int MAX_NATIVE_TEXT_BYTES = 32 * 1024 * 1024;
    private static final int MAX_CLIPBOARD_TEXT_BYTES = 256 * 1024;
    private static final int MAX_STORY_PAGES = 8;
    private static final int MAX_STORY_ENCODED_CHARS = 12 * 1024 * 1024;
    private static final int MAX_STORY_IMAGE_BYTES = 8 * 1024 * 1024;
    private static final int MAX_STORY_TOTAL_BYTES = 40 * 1024 * 1024;
    private static final int MAX_STORY_PAYLOAD_CHARS =
            MAX_STORY_PAGES * MAX_STORY_ENCODED_CHARS + 1024;
    private static final long STORY_CACHE_LIFETIME_MS =
            24L * 60L * 60L * 1000L;
    private static final String PNG_DATA_PREFIX =
            "data:image/png;base64,";
    private static final String APP_PREFERENCES = "divan_android_settings";
    private static final String REPLY_NOTIFICATIONS_KEY =
            "neutral_completion_notifications";
    private static final String REPLY_NOTIFICATION_CHANNEL =
            "divan_neutral_updates";
    private static final int REPLY_NOTIFICATION_ID = 2811;
    private static final byte[] PNG_SIGNATURE = new byte[] {
            (byte) 0x89, 0x50, 0x4e, 0x47,
            0x0d, 0x0a, 0x1a, 0x0a
    };

    private final ExecutorService ioExecutor =
            Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService backgroundExecutor =
            Executors.newSingleThreadScheduledExecutor();

    private FrameLayout root;
    private WebView webView;
    private LinearLayout statusPanel;
    private TextView statusText;
    private Button retryButton;
    private ValueCallback<Uri[]> fileChooserCallback;
    private PendingSave pendingSave;
    private GmsBarcodeScanner syncQrScanner;
    private boolean syncQrScanInProgress;
    private int serverPort = -1;
    private String sessionToken = "";
    private OnBackInvokedCallback backInvokedCallback;
    private volatile boolean activityVisible = false;
    private volatile int pendingWebWork = 0;
    private volatile int backgroundPollGeneration = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // Keep conversation previews out of Android's recent-apps screen
            // without blocking deliberate in-app story export or screenshots.
            setRecentsScreenshotEnabled(false);
        }
        createReplyNotificationChannel();
        getWindow().setStatusBarColor(Color.rgb(23, 18, 15));
        getWindow().setNavigationBarColor(Color.rgb(23, 18, 15));

        createLayout();
        configureWebView();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            backInvokedCallback = this::handleBackNavigation;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    backInvokedCallback);
        }
        SecretStore.initialize(getApplicationContext());
        startDivan();
    }

    private void createLayout() {
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(23, 18, 15));

        webView = createWebView();
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        statusPanel = new LinearLayout(this);
        statusPanel.setOrientation(LinearLayout.VERTICAL);
        statusPanel.setGravity(Gravity.CENTER);
        statusPanel.setPadding(dp(32), dp(32), dp(32), dp(32));
        statusPanel.setBackgroundColor(Color.rgb(23, 18, 15));

        ProgressBar progress = new ProgressBar(this);
        if (progress.getIndeterminateDrawable() != null) {
            progress.getIndeterminateDrawable().setTint(
                    Color.rgb(215, 178, 124));
        }
        statusPanel.addView(progress, new LinearLayout.LayoutParams(
                dp(48), dp(48)));

        statusText = new TextView(this);
        statusText.setText(R.string.loading_message);
        statusText.setTextColor(Color.rgb(234, 223, 200));
        statusText.setTextSize(18);
        statusText.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        textParams.topMargin = dp(20);
        statusPanel.addView(statusText, textParams);

        retryButton = new Button(this);
        retryButton.setText(R.string.retry);
        retryButton.setTextColor(Color.rgb(234, 223, 200));
        retryButton.setVisibility(View.GONE);
        retryButton.setOnClickListener(view -> startDivan());
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        retryParams.topMargin = dp(18);
        statusPanel.addView(retryButton, retryParams);

        root.addView(statusPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        ViewCompat.setOnApplyWindowInsetsListener(root, (view, insets) -> {
            int safeTypes = WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.displayCutout();
            Insets safe = insets.getInsets(safeTypes);
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom);

            // The native frame has already applied these safe areas. Zero
            // only those types before forwarding the update to WebView, so
            // CSS doesn't add them a second time. IME insets stay untouched:
            // WebView can resize its viewport once, without a keyboard-height
            // padding being added to the native frame as well.
            return new WindowInsetsCompat.Builder(insets)
                    .setInsets(safeTypes, Insets.NONE)
                    .build();
        });
        ViewCompat.requestApplyInsets(root);
    }

    private WebView createWebView() {
        WebView view = new WebView(this);
        view.setBackgroundColor(Color.rgb(23, 18, 15));
        view.setVisibility(View.INVISIBLE);
        return view;
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setGeolocationEnabled(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(
                settings.getUserAgentString() + " DivanAndroid/1");
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        webView.setOnScrollChangeListener(
                (view, scrollX, scrollY, oldScrollX, oldScrollY) -> {
                    // Mesaj listesi kendi içinde kayar. IME bazen bunun yerine
                    // WebView kökünü pan eder ve sabit başlığı ekranın dışına
                    // iter; yalnız bu kök kaydırmayı geri topluyoruz.
                    if (scrollX != 0 || scrollY != 0) {
                        view.post(() -> view.scrollTo(0, 0));
                    }
                });

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.setSafeBrowsingEnabled(true);
        }
        boolean debuggable = (getApplicationInfo().flags
                & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        WebView.setWebContentsDebuggingEnabled(debuggable);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, false);

        webView.addJavascriptInterface(new NativeExports(), "DivanAndroid");
        webView.setWebViewClient(new LocalOnlyWebViewClient());
        webView.setWebChromeClient(new DivanWebChromeClient());
        webView.setDownloadListener((url, userAgent, contentDisposition,
                                     mimeType, contentLength) -> {
            Uri uri = Uri.parse(url);
            if (isLocal(uri)) {
                beginUrlSave(uri);
            } else {
                openExternal(uri);
            }
        });
    }

    private void startDivan() {
        showStatus("Divan’ın güvenli yerel alanı hazırlanıyor…", false);
        ioExecutor.execute(() -> {
            try {
                String requestedToken = randomToken();
                File dataDirectory = new File(
                        getNoBackupFilesDir(), "divan-data");
                PyObject result = Python.getInstance()
                        .getModule("android_entry")
                        .callAttr("start_server",
                                dataDirectory.getAbsolutePath(),
                                requestedToken);
                String[] launch = result.toString().split("\\|", 2);
                if (launch.length != 2) {
                    throw new IllegalStateException(
                            "Yerel sunucu adresi alınamadı");
                }
                int port = Integer.parseInt(launch[0]);
                String token = launch[1];
                runOnUiThread(() -> openDivan(port, token));
            } catch (Throwable throwable) {
                String message = deepestMessage(throwable);
                runOnUiThread(() -> showStatus(
                        "Divan başlatılamadı.\n" + message, true));
            }
        });
    }

    private void openDivan(int port, String token) {
        serverPort = port;
        sessionToken = token;
        String launchUrl = "http://127.0.0.1:" + port
                + "/?_divan_session=" + Uri.encode(token);
        webView.loadUrl(launchUrl);
    }

    private void showStatus(String message, boolean canRetry) {
        webView.setVisibility(View.INVISIBLE);
        statusPanel.setVisibility(View.VISIBLE);
        statusText.setText(message);
        retryButton.setVisibility(canRetry ? View.VISIBLE : View.GONE);
    }

    private void showDivan() {
        statusPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
    }

    private boolean isLocal(Uri uri) {
        if (uri == null || serverPort <= 0
                || !"http".equalsIgnoreCase(uri.getScheme())
                || uri.getPort() != serverPort) {
            return false;
        }
        String host = uri.getHost();
        return "127.0.0.1".equals(host)
                || "localhost".equalsIgnoreCase(host);
    }

    private boolean handleNavigation(Uri uri) {
        if (isLocal(uri)) {
            String path = uri.getPath() == null ? "" : uri.getPath();
            if ("/api/backup".equals(path)
                    || "/api/export-json".equals(path)) {
                beginUrlSave(uri);
                return true;
            }
            return false;
        }
        openExternal(uri);
        return true;
    }

    private void openExternal(Uri uri) {
        if (uri == null) {
            return;
        }
        String scheme = uri.getScheme();
        if (!("https".equalsIgnoreCase(scheme)
                || "http".equalsIgnoreCase(scheme)
                || "mailto".equalsIgnoreCase(scheme)
                || "tel".equalsIgnoreCase(scheme))) {
            toast("Bu bağlantı güvenli olmadığı için açılmadı.");
            return;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException exception) {
            toast("Bağlantıyı açabilecek bir uygulama bulunamadı.");
        }
    }

    private void beginUrlSave(Uri uri) {
        if (!isLocal(uri)) {
            return;
        }
        String date = new SimpleDateFormat(
                "yyyy-MM-dd", Locale.US).format(new Date());
        boolean json = "/api/export-json".equals(uri.getPath());
        String name = json
                ? "divan-veriler-" + date + ".json"
                : "divan-yedek-" + date + ".db";
        String mime = json ? "application/json"
                : "application/octet-stream";
        beginSave(PendingSave.fromUrl(name, mime, uri.toString()));
    }

    private void beginSave(PendingSave save) {
        if (pendingSave != null) {
            toast("Önce açık dosya kaydetme işlemini tamamlayın.");
            return;
        }
        pendingSave = save;
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(save.mimeType);
        intent.putExtra(Intent.EXTRA_TITLE, safeFileName(save.fileName));
        try {
            startActivityForResult(intent, REQUEST_SAVE_FILE);
        } catch (ActivityNotFoundException exception) {
            pendingSave = null;
            toast("Dosya kaydetme ekranı açılamadı.");
        }
    }

    private void writePendingSave(Uri destination, PendingSave save) {
        try (OutputStream output = getContentResolver()
                .openOutputStream(destination, "w")) {
            if (output == null) {
                throw new IllegalStateException("Dosya açılamadı");
            }
            if (save.bytes != null) {
                output.write(save.bytes);
            } else {
                copyLocalUrl(save.url, output);
            }
            output.flush();
            toast("Dosya kaydedildi.");
        } catch (Exception exception) {
            try {
                getContentResolver().delete(destination, null, null);
            } catch (Exception ignored) {
                // Some document providers do not support delete.
            }
            toast("Dosya kaydedilemedi: " + deepestMessage(exception));
        }
    }

    private void copyLocalUrl(String source, OutputStream output)
            throws Exception {
        URL url = new URL(source);
        HttpURLConnection connection =
                (HttpURLConnection) url.openConnection();
        connection.setConnectTimeout(10_000);
        connection.setReadTimeout(120_000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Cookie", localCookieHeader());
        connection.setRequestProperty("Accept", "*/*");
        try {
            int status = connection.getResponseCode();
            if (status != HttpURLConnection.HTTP_OK) {
                throw new IllegalStateException(
                        "Yerel sunucu " + status + " yanıtı verdi");
            }
            try (InputStream input = connection.getInputStream()) {
                byte[] buffer = new byte[64 * 1024];
                int read;
                while ((read = input.read(buffer)) >= 0) {
                    output.write(buffer, 0, read);
                }
            }
        } finally {
            connection.disconnect();
        }
    }

    private String localCookieHeader() {
        String baseUrl = "http://127.0.0.1:" + serverPort + "/";
        String cookies = CookieManager.getInstance().getCookie(baseUrl);
        String embedded = "divan_embedded_session=" + sessionToken;
        if (cookies == null || cookies.trim().isEmpty()) {
            return embedded;
        }
        if (!cookies.contains("divan_embedded_session=")) {
            return cookies + "; " + embedded;
        }
        return cookies;
    }

    @Override
    protected void onActivityResult(
            int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_OPEN_FILE) {
            ValueCallback<Uri[]> callback = fileChooserCallback;
            fileChooserCallback = null;
            if (callback != null) {
                callback.onReceiveValue(
                        WebChromeClient.FileChooserParams.parseResult(
                                resultCode, data));
            }
            return;
        }
        if (requestCode == REQUEST_SAVE_FILE) {
            PendingSave save = pendingSave;
            pendingSave = null;
            if (save != null && resultCode == RESULT_OK && data != null
                    && data.getData() != null) {
                Uri destination = data.getData();
                ioExecutor.execute(() ->
                        writePendingSave(destination, save));
            }
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(
                requestCode, permissions, grantResults);
        if (requestCode != REQUEST_NOTIFICATION_PERMISSION) {
            return;
        }
        boolean granted = grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (!granted) {
            getSharedPreferences(APP_PREFERENCES, Context.MODE_PRIVATE)
                    .edit()
                    .putBoolean(REPLY_NOTIFICATIONS_KEY, false)
                    .commit();
            toast("Bildirim izni verilmedi; nötr bildirim seçeneği kapatıldı.");
        }
    }

    @Override
    @SuppressLint("GestureBackNavigation")
    public void onBackPressed() {
        handleBackNavigation();
    }

    private void handleBackNavigation() {
        if (webView == null || webView.getVisibility() != View.VISIBLE) {
            moveTaskToBack(true);
            return;
        }
        webView.evaluateJavascript(
                "window.divanAndroidBack"
                        + "?window.divanAndroidBack():false",
                value -> {
                    if (!"true".equals(value)) {
                        moveTaskToBack(true);
                    }
                });
    }

    @Override
    protected void onResume() {
        super.onResume();
        activityVisible = true;
        backgroundPollGeneration++;
        NotificationManager manager = (NotificationManager)
                getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.cancel(REPLY_NOTIFICATION_ID);
        }
    }

    @Override
    protected void onStop() {
        activityVisible = false;
        if (pendingWebWork > 0) {
            ResponseKeeperJobService.schedule(getApplicationContext());
        }
        if (canPostCompletionNotification()) {
            startBackgroundCompletionWatch(pendingWebWork > 0);
        }
        // Deliberately do not pause or destroy WebView/Python here. Back
        // navigation moves the task behind the current app, so an accepted
        // local response job can finish while Divan is not visible.
        super.onStop();
    }

    private boolean completionNotificationsEnabled() {
        return getSharedPreferences(APP_PREFERENCES, Context.MODE_PRIVATE)
                .getBoolean(REPLY_NOTIFICATIONS_KEY, false);
    }

    private boolean canPostCompletionNotification() {
        return completionNotificationsEnabled()
                && (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
                || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED);
    }

    private void createReplyNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = (NotificationManager)
                getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                REPLY_NOTIFICATION_CHANNEL,
                getString(R.string.notification_channel_name),
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(
                getString(R.string.notification_channel_description));
        manager.createNotificationChannel(channel);
    }

    private void startBackgroundCompletionWatch(boolean alreadyPending) {
        int generation = ++backgroundPollGeneration;
        backgroundExecutor.execute(() ->
                pollBackgroundCompletion(generation, alreadyPending, 225));
    }

    private void pollBackgroundCompletion(
            int generation, boolean sawPending, int attemptsRemaining) {
        if (activityVisible || generation != backgroundPollGeneration
                || !canPostCompletionNotification()
                || attemptsRemaining <= 0) {
            return;
        }
        Boolean pending = hasActiveLocalJobs();
        if (pending == null) {
            return;
        }
        if (pending) {
            backgroundExecutor.schedule(
                    () -> pollBackgroundCompletion(
                            generation, true, attemptsRemaining - 1),
                    4, TimeUnit.SECONDS);
        } else if (sawPending) {
            showNeutralCompletionNotification();
        }
    }

    private Boolean hasActiveLocalJobs() {
        if (serverPort <= 0 || sessionToken.isEmpty()) {
            return null;
        }
        HttpURLConnection connection = null;
        try {
            URL url = new URL(
                    "http://127.0.0.1:" + serverPort + "/api/jobs");
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(4_000);
            connection.setReadTimeout(5_000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Cookie", localCookieHeader());
            connection.setRequestProperty("Accept", "application/json");
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) {
                return null;
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream input = connection.getInputStream()) {
                byte[] buffer = new byte[8 * 1024];
                int read;
                int total = 0;
                while ((read = input.read(buffer)) >= 0) {
                    total += read;
                    if (total > 1024 * 1024) {
                        return null;
                    }
                    output.write(buffer, 0, read);
                }
            }
            JSONObject response = new JSONObject(
                    output.toString(StandardCharsets.UTF_8.name()));
            JSONArray jobs = response.optJSONArray("jobs");
            if (jobs == null) {
                return null;
            }
            for (int index = 0; index < jobs.length(); index++) {
                JSONObject job = jobs.optJSONObject(index);
                String status = job == null
                        ? "" : job.optString("status", "");
                if ("queued".equals(status)
                        || "waiting_provider".equals(status)
                        || "running".equals(status)) {
                    return true;
                }
            }
            return false;
        } catch (Exception ignored) {
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void showNeutralCompletionNotification() {
        if (activityVisible || !canPostCompletionNotification()) {
            return;
        }
        Intent open = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent contentIntent = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT
                        | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT
                >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, REPLY_NOTIFICATION_CHANNEL)
                : new Notification.Builder(this);
        Notification notification = builder
                .setSmallIcon(R.drawable.ic_divan_launcher)
                .setContentTitle(getString(R.string.notification_ready_title))
                .setContentText(getString(R.string.notification_ready_text))
                .setContentIntent(contentIntent)
                .setCategory(Notification.CATEGORY_STATUS)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setAutoCancel(true)
                .setOnlyAlertOnce(true)
                .build();
        NotificationManager manager = (NotificationManager)
                getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify(REPLY_NOTIFICATION_ID, notification);
        }
    }

    @Override
    protected void onDestroy() {
        backgroundPollGeneration++;
        if (pendingWebWork > 0) {
            ResponseKeeperJobService.schedule(getApplicationContext());
        }
        backgroundExecutor.shutdownNow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && backInvokedCallback != null) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(
                    backInvokedCallback);
            backInvokedCallback = null;
        }
        if (fileChooserCallback != null) {
            fileChooserCallback.onReceiveValue(null);
            fileChooserCallback = null;
        }
        if (isFinishing() && webView != null) {
            webView.removeJavascriptInterface("DivanAndroid");
            webView.stopLoading();
            webView.destroy();
        }
        super.onDestroy();
    }

    private String randomToken() {
        byte[] bytes = new byte[32];
        new SecureRandom().nextBytes(bytes);
        return Base64.encodeToString(
                bytes, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private int dp(int value) {
        return Math.round(value
                * getResources().getDisplayMetrics().density);
    }

    private void toast(String message) {
        runOnUiThread(() -> Toast.makeText(
                MainActivity.this, message, Toast.LENGTH_LONG).show());
    }

    private void startSyncQrScan() {
        if (syncQrScanInProgress) {
            dispatchSyncScanError("scan_in_progress");
            return;
        }
        if (isFinishing()
                || (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1
                && isDestroyed())) {
            dispatchSyncScanError("scanner_unavailable");
            return;
        }
        try {
            if (syncQrScanner == null) {
                GmsBarcodeScannerOptions options =
                        new GmsBarcodeScannerOptions.Builder()
                                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                                .enableAutoZoom()
                                .build();
                syncQrScanner = GmsBarcodeScanning.getClient(this, options);
            }
            syncQrScanInProgress = true;
            syncQrScanner.startScan()
                    .addOnSuccessListener(barcode -> runOnUiThread(() -> {
                        syncQrScanInProgress = false;
                        String rawValue = barcode == null
                                ? "" : barcode.getRawValue();
                        dispatchSyncCode(rawValue == null ? "" : rawValue);
                    }))
                    .addOnCanceledListener(() -> runOnUiThread(() -> {
                        syncQrScanInProgress = false;
                        dispatchSyncCode("");
                    }))
                    .addOnFailureListener(exception -> runOnUiThread(() -> {
                        syncQrScanInProgress = false;
                        dispatchSyncScanError("scan_failed");
                        toast("QR tarayıcı açılamadı; kodu elle girebilirsiniz.");
                    }));
        } catch (RuntimeException exception) {
            syncQrScanInProgress = false;
            dispatchSyncScanError("scanner_unavailable");
            toast("QR tarayıcı bu cihazda kullanılamıyor; kodu elle "
                    + "girebilirsiniz.");
        }
    }

    private void dispatchSyncCode(String rawValue) {
        if (webView != null) {
            webView.evaluateJavascript(
                    buildSyncCallbackScript(
                            "onDivanSyncCode", rawValue),
                    null);
        }
    }

    private void dispatchSyncScanError(String errorCode) {
        if (webView != null) {
            webView.evaluateJavascript(
                    buildSyncCallbackScript(
                            "onDivanSyncScanError", errorCode),
                    null);
        }
    }

    static String buildSyncCallbackScript(
            String callbackName, String value) {
        if (!("onDivanSyncCode".equals(callbackName)
                || "onDivanSyncScanError".equals(callbackName))) {
            throw new IllegalArgumentException("Unsupported sync callback");
        }
        // JSONObject.quote prevents scanned content from becoming executable
        // JavaScript. Escape the two Unicode line separators explicitly for
        // compatibility with older Android WebView JavaScript parsers.
        String quoted = JSONObject.quote(value == null ? "" : value)
                .replace("\u2028", "\\u2028")
                .replace("\u2029", "\\u2029");
        return "(function(){if(typeof window." + callbackName
                + "==='function'){window." + callbackName
                + "(" + quoted + ");}})();";
    }

    private static String safeFileName(String value) {
        String clean = value == null ? "divan-dosya"
                : value.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").trim();
        return clean.isEmpty() ? "divan-dosya" : clean;
    }

    private static String deepestMessage(Throwable throwable) {
        Throwable current = throwable;
        while (current.getCause() != null
                && current.getCause() != current) {
            current = current.getCause();
        }
        String message = current.getMessage();
        if (message == null || message.trim().isEmpty()) {
            message = current.getClass().getSimpleName();
        }
        return message;
    }

    private static byte[] decodeStoryPng(String dataUrl) {
        if (dataUrl == null || !dataUrl.startsWith(PNG_DATA_PREFIX)) {
            throw new IllegalArgumentException(
                    "Yalnızca PNG hikâye görselleri kabul edilir.");
        }
        String encoded = dataUrl.substring(PNG_DATA_PREFIX.length());
        if (encoded.isEmpty()
                || encoded.length() > MAX_STORY_ENCODED_CHARS
                || !encoded.matches("[A-Za-z0-9+/]*={0,2}")) {
            throw new IllegalArgumentException(
                    "Hikâye görselinin kodlaması geçersiz.");
        }
        byte[] bytes;
        try {
            bytes = Base64.decode(encoded, Base64.NO_WRAP);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException(
                    "Hikâye görseli çözülemedi.", exception);
        }
        if (bytes.length == 0 || bytes.length > MAX_STORY_IMAGE_BYTES) {
            throw new IllegalArgumentException(
                    "Hikâye görseli izin verilen boyutu aşıyor.");
        }
        if (bytes.length < PNG_SIGNATURE.length) {
            throw new IllegalArgumentException(
                    "Hikâye görseli geçerli bir PNG değil.");
        }
        for (int index = 0; index < PNG_SIGNATURE.length; index++) {
            if (bytes[index] != PNG_SIGNATURE[index]) {
                throw new IllegalArgumentException(
                        "Hikâye görseli geçerli bir PNG değil.");
            }
        }
        return bytes;
    }

    private File storyShareDirectory() {
        File directory = new File(getCacheDir(), "shared-stories");
        if (!directory.exists() && !directory.mkdirs()) {
            throw new IllegalStateException(
                    "Geçici paylaşım alanı hazırlanamadı.");
        }
        if (!directory.isDirectory()) {
            throw new IllegalStateException(
                    "Geçici paylaşım alanı kullanılamıyor.");
        }
        return directory;
    }

    private void pruneStoryShareCache(File directory) {
        File[] files = directory.listFiles();
        if (files == null) {
            return;
        }
        long cutoff = System.currentTimeMillis() - STORY_CACHE_LIFETIME_MS;
        for (File file : files) {
            if (file.isFile() && file.lastModified() < cutoff) {
                // Best effort: another app may still hold a temporary grant.
                file.delete();
            }
        }
    }

    private ArrayList<Uri> createStoryShareUris(String jsonDataUrls)
            throws Exception {
        if (jsonDataUrls == null
                || jsonDataUrls.length() > MAX_STORY_PAYLOAD_CHARS) {
            throw new IllegalArgumentException(
                    "Hikâye paylaşım paketi çok büyük.");
        }
        JSONArray pages = new JSONArray(jsonDataUrls);
        if (pages.length() < 1 || pages.length() > MAX_STORY_PAGES) {
            throw new IllegalArgumentException(
                    "Bir defada 1–8 hikâye sayfası paylaşılabilir.");
        }
        ArrayList<byte[]> decoded = new ArrayList<>();
        int totalBytes = 0;
        for (int index = 0; index < pages.length(); index++) {
            byte[] bytes = decodeStoryPng(pages.getString(index));
            totalBytes += bytes.length;
            if (totalBytes > MAX_STORY_TOTAL_BYTES) {
                throw new IllegalArgumentException(
                        "Hikâye paylaşım paketi izin verilen boyutu aşıyor.");
            }
            decoded.add(bytes);
        }

        File directory = storyShareDirectory();
        pruneStoryShareCache(directory);
        ArrayList<File> createdFiles = new ArrayList<>();
        ArrayList<Uri> uris = new ArrayList<>();
        try {
            for (byte[] bytes : decoded) {
                File file = File.createTempFile(
                        "divan-hikaye-", ".png", directory);
                createdFiles.add(file);
                try (FileOutputStream output = new FileOutputStream(file)) {
                    output.write(bytes);
                    output.flush();
                }
                uris.add(FileProvider.getUriForFile(
                        this,
                        getPackageName() + ".fileprovider",
                        file));
            }
            return uris;
        } catch (Exception exception) {
            for (File file : createdFiles) {
                file.delete();
            }
            throw exception;
        }
    }

    private void launchStoryShare(ArrayList<Uri> uris) {
        if (uris == null || uris.isEmpty()) {
            toast("Paylaşılacak hikâye görseli bulunamadı.");
            return;
        }
        boolean multiple = uris.size() > 1;
        Intent share = new Intent(
                multiple ? Intent.ACTION_SEND_MULTIPLE : Intent.ACTION_SEND);
        share.setType("image/png");
        if (multiple) {
            share.putParcelableArrayListExtra(
                    Intent.EXTRA_STREAM, uris);
        } else {
            share.putExtra(Intent.EXTRA_STREAM, uris.get(0));
        }
        ClipData clipData = ClipData.newUri(
                getContentResolver(), "Divan hikâyesi", uris.get(0));
        for (int index = 1; index < uris.size(); index++) {
            clipData.addItem(new ClipData.Item(uris.get(index)));
        }
        share.setClipData(clipData);
        share.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(Intent.createChooser(
                    share, "Hikâyeyi paylaş"));
        } catch (ActivityNotFoundException exception) {
            toast("Görsel paylaşabilecek bir uygulama bulunamadı.");
        }
    }

    private final class LocalOnlyWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(
                WebView view, WebResourceRequest request) {
            return handleNavigation(request.getUrl());
        }

        @SuppressWarnings("deprecation")
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return handleNavigation(Uri.parse(url));
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(
                WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (isLocal(uri)) {
                return super.shouldInterceptRequest(view, request);
            }
            return new WebResourceResponse(
                    "text/plain",
                    "UTF-8",
                    new ByteArrayInputStream(new byte[0]));
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            Uri uri = Uri.parse(url);
            if (isLocal(uri) && "/".equals(uri.getPath())
                    && uri.getQuery() == null) {
                CookieManager.getInstance().flush();
                view.clearHistory();
                showDivan();
            }
        }

        @Override
        public void onReceivedError(WebView view,
                                    WebResourceRequest request,
                                    WebResourceError error) {
            if (request.isForMainFrame()) {
                showStatus(
                        "Divan’ın yerel ekranına ulaşılamadı.\n"
                                + error.getDescription(),
                        true);
            }
        }

        @Override
        public boolean onRenderProcessGone(
                WebView view, RenderProcessGoneDetail detail) {
            // A WebView renderer may be reclaimed independently while the
            // durable Python job is still running. Consuming this callback
            // prevents Android from terminating the whole app; a fresh
            // renderer reloads the same loopback session and recovers the
            // persisted conversation/job state.
            if (view != webView) {
                view.destroy();
                return true;
            }
            if (fileChooserCallback != null) {
                fileChooserCallback.onReceiveValue(null);
                fileChooserCallback = null;
            }
            root.removeView(view);
            view.destroy();

            webView = createWebView();
            root.addView(webView, 0, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT));
            configureWebView();
            showStatus("Sohbet ekranı güvenle yeniden kuruluyor…", false);
            if (serverPort > 0 && !sessionToken.isEmpty()) {
                openDivan(serverPort, sessionToken);
            } else {
                startDivan();
            }
            return true;
        }
    }

    private final class DivanWebChromeClient extends WebChromeClient {
        @Override
        public boolean onShowFileChooser(
                WebView webView,
                ValueCallback<Uri[]> filePathCallback,
                FileChooserParams fileChooserParams) {
            if (fileChooserCallback != null) {
                fileChooserCallback.onReceiveValue(null);
            }
            fileChooserCallback = filePathCallback;
            Intent intent;
            try {
                intent = fileChooserParams.createIntent();
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                startActivityForResult(intent, REQUEST_OPEN_FILE);
                return true;
            } catch (ActivityNotFoundException exception) {
                fileChooserCallback = null;
                toast("Dosya seçme ekranı açılamadı.");
                return false;
            }
        }
    }

    private final class NativeExports {
        @JavascriptInterface
        public void copyText(String content) {
            String text = String.valueOf(content);
            if (text.getBytes(StandardCharsets.UTF_8).length
                    > MAX_CLIPBOARD_TEXT_BYTES) {
                toast("Seçim panoya kopyalanamayacak kadar büyük.");
                return;
            }
            runOnUiThread(() -> {
                ClipboardManager clipboard = (ClipboardManager)
                        getSystemService(Context.CLIPBOARD_SERVICE);
                if (clipboard == null) {
                    toast("Pano bu cihazda kullanılamıyor.");
                    return;
                }
                clipboard.setPrimaryClip(ClipData.newPlainText(
                        "Divan mesajları", text));
            });
        }

        @JavascriptInterface
        public void saveText(String fileName, String content) {
            byte[] bytes = String.valueOf(content)
                    .getBytes(StandardCharsets.UTF_8);
            if (bytes.length > MAX_NATIVE_TEXT_BYTES) {
                toast("Bu metin tek dosyada kaydedilemeyecek kadar büyük.");
                return;
            }
            String safeName = safeFileName(fileName);
            String mimeType = safeName.toLowerCase(Locale.US).endsWith(".json")
                    ? "application/json" : "text/markdown";
            runOnUiThread(() -> beginSave(PendingSave.fromBytes(
                    safeName, mimeType, bytes)));
        }

        @JavascriptInterface
        public void saveStoryImage(String fileName, String dataUrl) {
            ioExecutor.execute(() -> {
                try {
                    byte[] bytes = decodeStoryPng(dataUrl);
                    String safeName = safeFileName(fileName);
                    if (!safeName.toLowerCase(Locale.US).endsWith(".png")) {
                        safeName += ".png";
                    }
                    String finalName = safeName;
                    runOnUiThread(() -> beginSave(PendingSave.fromBytes(
                            finalName, "image/png", bytes)));
                } catch (Exception exception) {
                    toast("Hikâye kaydedilemedi: "
                            + deepestMessage(exception));
                }
            });
        }

        @JavascriptInterface
        public void shareStoryImages(String jsonDataUrls) {
            ioExecutor.execute(() -> {
                try {
                    ArrayList<Uri> uris =
                            createStoryShareUris(jsonDataUrls);
                    runOnUiThread(() -> launchStoryShare(uris));
                } catch (Exception exception) {
                    toast("Hikâye paylaşılamadı: "
                            + deepestMessage(exception));
                }
            });
        }

        @JavascriptInterface
        public String platform() {
            return "android";
        }

        @JavascriptInterface
        public void scanSyncQr() {
            runOnUiThread(MainActivity.this::startSyncQrScan);
        }

        @JavascriptInterface
        public boolean replyNotificationsEnabled() {
            return completionNotificationsEnabled();
        }

        @JavascriptInterface
        public void setReplyNotificationsEnabled(boolean enabled) {
            boolean saved = getSharedPreferences(
                    APP_PREFERENCES, Context.MODE_PRIVATE)
                    .edit()
                    .putBoolean(REPLY_NOTIFICATIONS_KEY, enabled)
                    .commit();
            runOnUiThread(() -> {
                if (!saved) {
                    toast("Bildirim tercihi kaydedilemedi.");
                    return;
                }
                if (!enabled) {
                    backgroundPollGeneration++;
                    NotificationManager manager = (NotificationManager)
                            getSystemService(Context.NOTIFICATION_SERVICE);
                    if (manager != null) {
                        manager.cancel(REPLY_NOTIFICATION_ID);
                    }
                    return;
                }
                createReplyNotificationChannel();
                if (Build.VERSION.SDK_INT
                        >= Build.VERSION_CODES.TIRAMISU
                        && checkSelfPermission(
                                Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(
                            new String[] {
                                Manifest.permission.POST_NOTIFICATIONS
                            },
                            REQUEST_NOTIFICATION_PERMISSION);
                }
            });
        }

        @JavascriptInterface
        public void setPendingWork(int count) {
            pendingWebWork = Math.max(0, count);
            if (pendingWebWork > 0) {
                ResponseKeeperJobService.schedule(
                        getApplicationContext());
            }
            if (!activityVisible && pendingWebWork > 0
                    && canPostCompletionNotification()) {
                startBackgroundCompletionWatch(true);
            }
        }

        @JavascriptInterface
        public void hideKeyboard() {
            runOnUiThread(() -> {
                InputMethodManager keyboard = (InputMethodManager)
                        getSystemService(Context.INPUT_METHOD_SERVICE);
                if (keyboard != null) {
                    keyboard.hideSoftInputFromWindow(
                            webView.getWindowToken(), 0);
                }
            });
        }

        @JavascriptInterface
        public void showKeyboard() {
            runOnUiThread(() -> {
                if (!webView.hasFocus()) {
                    webView.requestFocus();
                }
                webView.postDelayed(() -> {
                    InputMethodManager keyboard = (InputMethodManager)
                            getSystemService(Context.INPUT_METHOD_SERVICE);
                    if (keyboard != null) {
                        keyboard.showSoftInput(
                                webView, InputMethodManager.SHOW_IMPLICIT);
                    }
                }, 60);
            });
        }
    }

    private static final class PendingSave {
        final String fileName;
        final String mimeType;
        final String url;
        final byte[] bytes;

        private PendingSave(
                String fileName, String mimeType, String url, byte[] bytes) {
            this.fileName = fileName;
            this.mimeType = mimeType;
            this.url = url;
            this.bytes = bytes;
        }

        static PendingSave fromUrl(
                String fileName, String mimeType, String url) {
            return new PendingSave(fileName, mimeType, url, null);
        }

        static PendingSave fromBytes(
                String fileName, String mimeType, byte[] bytes) {
            return new PendingSave(fileName, mimeType, null, bytes);
        }
    }
}
