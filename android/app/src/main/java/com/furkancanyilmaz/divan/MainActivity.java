package com.furkancanyilmaz.divan;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewTreeObserver;
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
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

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
    private static final String NATIVE_VISUAL_PREFS =
            "divan_native_visual";
    private static final String NATIVE_THEME_KEY = "chrome_theme";
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
    private volatile int mobileViewportHeightCss = 0;
    private volatile boolean mobileImeVisible = false;
    private volatile boolean mobileImeStateKnown = false;
    private int mobileViewportRefreshGeneration = 0;
    private LinearLayout statusPanel;
    private ImageView statusMark;
    private TextView statusText;
    private Button retryButton;
    private ProgressBar loadingProgress;
    private int nativeBackground = Color.rgb(247, 241, 230);
    private int nativeForeground = Color.rgb(58, 43, 39);
    private int nativeAccent = Color.rgb(87, 35, 48);
    private ValueCallback<Uri[]> fileChooserCallback;
    private PendingSave pendingSave;
    private GmsBarcodeScanner syncQrScanner;
    private boolean syncQrScanInProgress;
    private int serverPort = -1;
    private String sessionToken = "";
    private int sessionCookieGeneration = 0;
    private boolean mainFrameLoadFailed = false;
    private OnBackInvokedCallback backInvokedCallback;
    private volatile boolean activityVisible = false;
    private volatile int pendingWebWork = 0;
    private volatile int backgroundPollGeneration = 0;
    private volatile int pendingOpenConversationId = 0;
    private volatile boolean needsAppLookupInFlight = false;
    private volatile String needsAppPromptedRequestId = "";
    private volatile boolean notificationPermissionForCompletion = false;
    private volatile boolean notificationPermissionForReminder = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // The manifest's starting theme owns the branded launch window. The
        // real activity switches away from it before any content is inflated.
        setTheme(R.style.Theme_Divan);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // Keep conversation previews out of Android's recent-apps screen
            // without blocking deliberate in-app story export or screenshots.
            setRecentsScreenshotEnabled(false);
        }
        CompletionNotificationController.ensureChannels(this);
        ChatNotificationController.ensureChannel(this);
        ReminderReceiver.ensureChannel(this);
        // Uygulama açılışında görev alarmlarını kalıcı kayıttan tazele:
        // uygulama kapatılmış veya cihaz yeniden başlamışsa hatırlatıcılar
        // bu yolla kaybolmaz. (BootReminderRescheduler açılışsız durumları,
        // burası her normal açılışı kapsar.)
        ReminderReceiver.rescheduleAll(getApplicationContext());
        // Web başlığı sistem çubuklarının arkasına doğal biçimde uzanır;
        // güvenli alanı aşağıdaki tek inset dinleyicisi uygular.
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        applySystemChromeTheme(savedSystemChromeTheme());

        createLayout();
        configureWebView();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            backInvokedCallback = this::handleBackNavigation;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    backInvokedCallback);
        }
        SecretStore.initialize(getApplicationContext());
        handleConversationIntent(getIntent());
        startDivan();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleConversationIntent(intent);
        if (webView != null && webView.getVisibility() == View.VISIBLE) {
            webView.post(this::injectPendingConversationOpen);
        }
    }

    private void handleConversationIntent(Intent intent) {
        if (intent == null) {
            return;
        }
        int conversationId = intent.getIntExtra(
                ChatNotificationController.EXTRA_CONVERSATION_ID, 0);
        if (conversationId > 0) {
            pendingOpenConversationId = conversationId;
        }
    }

    private void injectPendingConversationOpen() {
        int conversationId = pendingOpenConversationId;
        if (conversationId <= 0 || webView == null) {
            return;
        }
        webView.evaluateJavascript(
                "window.divanOpenConversation"
                        + "?window.divanOpenConversation("
                        + conversationId + "):false",
                value -> {
                    if (!"true".equals(value)) {
                        // PIN kilidi veya henüz hazır olmayan web ekranı:
                        // kimliği tüketme; açılış/unlock sonrasında yeniden
                        // denenecek.
                        return;
                    }
                    if (pendingOpenConversationId == conversationId) {
                        pendingOpenConversationId = 0;
                    }
                    ChatNotificationController.dismiss(
                            MainActivity.this, conversationId);
                    CompletionNotificationController.dismiss(
                            MainActivity.this);
                    // divanOpenConversation fetch'i asenkrondur. Güvenlik
                    // kapısında kalan yanıtı ancak görüşme yerleşince ve PIN
                    // kilidi gerçekten açıldıktan sonra kullanıcıya sor.
                    webView.postDelayed(
                            () -> surfaceNeedsAppReply(conversationId),
                            350L);
                });
    }

    /**
     * Launcher açılışı da bildirim dokunuşu gibi bekleyen güvenlik yanıtını
     * ilgili görüşmeye götürür. Burada yalnız conv id belleğe alınır; mesaj
     * Intent, preference veya log'a kopyalanmaz.
     */
    private void queueNeedsAppConversationOpen() {
        if (needsAppLookupInFlight || webView == null) {
            return;
        }
        if (pendingOpenConversationId > 0) {
            injectPendingConversationOpen();
            return;
        }
        needsAppLookupInFlight = true;
        ioExecutor.execute(() -> {
            NotificationReplyOutbox.Record record =
                    NotificationReplyOutbox.firstNeedsApp(
                            getApplicationContext(), 0);
            int conversationId = record == null
                    ? 0 : record.conversationId;
            runOnUiThread(() -> {
                needsAppLookupInFlight = false;
                if (conversationId > 0
                        && pendingOpenConversationId <= 0) {
                    pendingOpenConversationId = conversationId;
                }
                injectPendingConversationOpen();
            });
        });
    }

    private void surfaceNeedsAppReply(int conversationId) {
        if (conversationId <= 0 || !activityVisible
                || isFinishing() || isDestroyed()) {
            return;
        }
        ioExecutor.execute(() -> {
            NotificationReplyOutbox.Record record =
                    NotificationReplyOutbox.firstNeedsApp(
                            getApplicationContext(), conversationId);
            if (record == null
                    || record.requestId.equals(
                    needsAppPromptedRequestId)) {
                return;
            }
            runOnUiThread(() -> {
                if (!activityVisible || isFinishing() || isDestroyed()
                        || record.requestId.equals(
                        needsAppPromptedRequestId)) {
                    return;
                }
                needsAppPromptedRequestId = record.requestId;
                new AlertDialog.Builder(MainActivity.this)
                        .setTitle("Gönderilmemiş yanıt")
                        .setMessage("Bildirimde yazdığınız yanıt güvenlik "
                                + "nedeniyle gönderilmedi. Mesajı gözden "
                                + "geçirmek için sohbet alanına taşıyalım "
                                + "mı?")
                        .setPositiveButton("Mesaj alanına taşı",
                                (dialog, which) ->
                                        restoreNeedsAppReplyDraft(record))
                        .setNegativeButton("Şimdilik kalsın", null)
                        .show();
            });
        });
    }

    /**
     * Açık kullanıcı onayından sonra metni normal sohbet taslağına koyar;
     * gönder düğmesine basılmaz. Böylece tehlike metni notification endpoint
     * güvenlik kapısını dolanmaz, normal sohbetin güvenlik akışından geçer.
     */
    private void restoreNeedsAppReplyDraft(
            NotificationReplyOutbox.Record record) {
        if (record == null || webView == null
                || record.conversationId <= 0) {
            return;
        }
        String quoted = JSONObject.quote(record.message);
        int conversationId = record.conversationId;
        String script = "(()=>{"
                + "if(typeof convId==='undefined'||Number(convId)!=="
                + conversationId + ")return 'unavailable';"
                + "const box=document.getElementById('msg');"
                + "if(!box)return 'unavailable';"
                + "if(String(box.value||'').trim())return 'occupied';"
                + "box.value=" + quoted + ";"
                + "box.dispatchEvent(new Event('input',{bubbles:true}));"
                + "if(typeof saveConversationDraft==='function')"
                + "saveConversationDraft(" + conversationId + ");"
                + "box.focus();return 'restored';})()";
        webView.evaluateJavascript(script, value -> {
            if (!"\"restored\"".equals(value)) {
                toast("Mesaj alanındaki mevcut taslak korunuyor. "
                        + "Boşalttıktan sonra yeniden deneyin.");
                return;
            }
            ioExecutor.execute(() -> {
                boolean consumed =
                        NotificationReplyOutbox.consumeNeedsApp(record);
                runOnUiThread(() -> {
                    if (!consumed) {
                        toast("Şifreli yanıt henüz kaldırılamadı; "
                                + "taslağınız sohbet alanında korunuyor.");
                        return;
                    }
                    needsAppPromptedRequestId = "";
                    ChatNotificationController.dismiss(
                            MainActivity.this, conversationId);
                    toast("Yanıt sohbet alanına alındı. Gözden geçirip "
                            + "Gönder’e dokunabilirsiniz.");
                });
            });
        });
    }

    private void createLayout() {
        root = new FrameLayout(this);
        root.setBackgroundColor(nativeBackground);

        webView = createWebView();
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        statusPanel = new LinearLayout(this);
        statusPanel.setOrientation(LinearLayout.VERTICAL);
        statusPanel.setGravity(Gravity.CENTER);
        statusPanel.setPadding(dp(32), dp(32), dp(32), dp(32));
        statusPanel.setBackgroundColor(nativeBackground);

        statusMark = new ImageView(this);
        statusMark.setImageResource(R.drawable.ic_divan_monochrome);
        statusMark.setImageTintList(ColorStateList.valueOf(nativeAccent));
        statusMark.setImportantForAccessibility(
                View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        statusPanel.addView(statusMark, new LinearLayout.LayoutParams(
                dp(88), dp(88)));

        loadingProgress = new ProgressBar(this);
        loadingProgress.setImportantForAccessibility(
                View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        if (loadingProgress.getIndeterminateDrawable() != null) {
            loadingProgress.getIndeterminateDrawable().setTint(
                    nativeAccent);
        }
        LinearLayout.LayoutParams progressParams =
                new LinearLayout.LayoutParams(dp(40), dp(40));
        progressParams.topMargin = dp(16);
        statusPanel.addView(loadingProgress, progressParams);

        statusText = new TextView(this);
        statusText.setText(R.string.loading_message);
        statusText.setTextColor(nativeForeground);
        statusText.setTextSize(17);
        statusText.setGravity(Gravity.CENTER);
        statusText.setLineSpacing(0, 1.1f);
        statusText.setMaxWidth(dp(440));
        statusText.setAccessibilityLiveRegion(
                View.ACCESSIBILITY_LIVE_REGION_POLITE);
        LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        textParams.topMargin = dp(16);
        statusPanel.addView(statusText, textParams);

        retryButton = new Button(this);
        retryButton.setText(R.string.retry);
        retryButton.setAllCaps(false);
        retryButton.setTextSize(15);
        retryButton.setMinWidth(0);
        retryButton.setMinimumWidth(0);
        retryButton.setMinHeight(dp(48));
        retryButton.setMinimumHeight(dp(48));
        retryButton.setElevation(0);
        retryButton.setStateListAnimator(null);
        styleRetryButton(nativeAccent);
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
            boolean nextImeVisible = insets.isVisible(
                    WindowInsetsCompat.Type.ime());
            boolean imeChanged = !mobileImeStateKnown
                    || mobileImeVisible != nextImeVisible;
            mobileImeVisible = nextImeVisible;
            mobileImeStateKnown = true;
            if (imeChanged) {
                if (nextImeVisible) {
                    dispatchMobileViewportState();
                } else {
                    // IME-hidden insets can arrive before MATCH_PARENT has
                    // regained its final height. Measure after layout.
                    view.post(this::refreshMobileViewportState);
                }
            }

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
        mobileViewportHeightCss = 0;
        mobileImeStateKnown = false;
        mobileViewportRefreshGeneration++;
        view.addOnLayoutChangeListener((changedView, left, top, right, bottom,
                                        oldLeft, oldTop, oldRight, oldBottom) -> {
            int nextHeightCss = measureMobileViewportHeightCss(view);
            if (mobileViewportHeightCss != nextHeightCss) {
                mobileViewportHeightCss = nextHeightCss;
                dispatchMobileViewportState();
            }
        });
        view.setBackgroundColor(nativeBackground);
        view.setVisibility(View.INVISIBLE);
        return view;
    }

    private int measureMobileViewportHeightCss(WebView current) {
        int heightPx = current == null ? 0 : Math.max(0, current.getHeight());
        float density = getResources().getDisplayMetrics().density;
        return density > 0f
                ? Math.max(0, Math.round(heightPx / density)) : 0;
    }

    /**
     * Foreground, lock-screen and IME transitions can leave WebView's JS
     * viewport stale even though the native child is already MATCH_PARENT.
     * Re-read both sources after the next layout and force a fresh JS signal.
     */
    private void refreshMobileViewportState() {
        WebView current = webView;
        FrameLayout currentRoot = root;
        if (current == null || currentRoot == null) {
            return;
        }
        int generation = ++mobileViewportRefreshGeneration;
        ViewTreeObserver observer = current.getViewTreeObserver();
        if (!observer.isAlive()) {
            current.post(this::refreshMobileViewportState);
            return;
        }
        observer.addOnPreDrawListener(new ViewTreeObserver.OnPreDrawListener() {
            @Override
            public boolean onPreDraw() {
                if (observer.isAlive()) {
                    observer.removeOnPreDrawListener(this);
                } else {
                    current.getViewTreeObserver().removeOnPreDrawListener(this);
                }
                if (generation != mobileViewportRefreshGeneration
                        || current != webView || currentRoot != root) {
                    return true;
                }
                WindowInsetsCompat insets =
                        ViewCompat.getRootWindowInsets(currentRoot);
                if (insets != null) {
                    mobileImeVisible = insets.isVisible(
                            WindowInsetsCompat.Type.ime());
                    mobileImeStateKnown = true;
                }
                mobileViewportHeightCss =
                        measureMobileViewportHeightCss(current);
                // Foregrounding must reassert the current values even when
                // neither equality-gated listener observed a change.
                dispatchMobileViewportState();
                return true;
            }
        });
        ViewCompat.requestApplyInsets(currentRoot);
        getWindow().getDecorView().requestLayout();
        currentRoot.requestLayout();
        current.requestLayout();
        current.invalidate();
    }

    private void dispatchMobileViewportState() {
        WebView current = webView;
        if (current == null || !mobileImeStateKnown) {
            return;
        }
        current.post(() -> {
            if (current != webView || !mobileImeStateKnown) {
                return;
            }
            boolean imeVisible = mobileImeVisible;
            current.evaluateJavascript(
                    "window.divanAndroidViewportChanged"
                            + "?window.divanAndroidViewportChanged("
                            + (imeVisible ? "true" : "false")
                            + "):false",
                    null);
        });
    }

    /** Eski iki durumlu köprünün geriye uyumlu uygulaması. */
    private void applySystemChrome(boolean dark) {
        applyAndPersistSystemChromeTheme(dark ? "dark" : "paper");
    }

    private String normalizeSystemChromeTheme(String requestedTheme) {
        String theme = requestedTheme == null
                ? "paper"
                : requestedTheme.trim().toLowerCase(Locale.ROOT);
        if ("white".equals(theme) || "dark".equals(theme)
                || "paper".equals(theme)) {
            return theme;
        }
        return "paper";
    }

    private String savedSystemChromeTheme() {
        return normalizeSystemChromeTheme(getSharedPreferences(
                NATIVE_VISUAL_PREFS, Context.MODE_PRIVATE).getString(
                        NATIVE_THEME_KEY, "paper"));
    }

    private void applyAndPersistSystemChromeTheme(String requestedTheme) {
        String theme = normalizeSystemChromeTheme(requestedTheme);
        // Cosmetic only: SharedPreferences keeps the native launch/error
        // surface aligned before the local WebView has finished loading.
        getSharedPreferences(NATIVE_VISUAL_PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString(NATIVE_THEME_KEY, theme)
                .apply();
        applySystemChromeTheme(theme);
    }

    /**
     * Mobil web temasını Android durum/gezinme çubukları ve yükleme
     * yüzeyiyle birebir eşler. Tanınmayan değerler sıcak kâğıda düşer;
     * Javascript köprüsünden keyfi renk kabul edilmez.
     */
    private void applySystemChromeTheme(String requestedTheme) {
        String theme = normalizeSystemChromeTheme(requestedTheme);
        int background;
        int foreground;
        int accent;
        boolean dark;
        switch (theme) {
            case "white":
                background = Color.rgb(255, 255, 255);
                foreground = Color.rgb(23, 25, 27);
                accent = Color.rgb(109, 37, 53);
                dark = false;
                break;
            case "dark":
                background = Color.rgb(25, 29, 32);
                foreground = Color.rgb(242, 240, 235);
                accent = Color.rgb(227, 163, 178);
                dark = true;
                break;
            case "paper":
            default:
                background = getColor(R.color.divan_background);
                foreground = getColor(R.color.divan_ink);
                accent = getColor(R.color.divan_wine);
                dark = false;
                break;
        }
        nativeBackground = background;
        nativeForeground = foreground;
        nativeAccent = accent;
        // API 24–25 cannot draw dark navigation-bar icons. A wine bar keeps
        // the legacy white controls legible; API 26+ can match the surface.
        boolean legacyLightNavigation = !dark
                && Build.VERSION.SDK_INT < Build.VERSION_CODES.O;
        int navigationBackground = legacyLightNavigation
                ? accent : background;
        getWindow().setStatusBarColor(background);
        getWindow().setNavigationBarColor(navigationBackground);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            getWindow().setNavigationBarDividerColor(navigationBackground);
        }
        WindowInsetsControllerCompat controller =
                WindowCompat.getInsetsController(
                        getWindow(), getWindow().getDecorView());
        controller.setAppearanceLightStatusBars(!dark);
        controller.setAppearanceLightNavigationBars(
                !dark && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O);
        if (root != null) {
            root.setBackgroundColor(background);
        }
        if (webView != null) {
            webView.setBackgroundColor(background);
        }
        if (statusPanel != null) {
            statusPanel.setBackgroundColor(background);
        }
        if (statusText != null) {
            statusText.setTextColor(foreground);
        }
        if (statusMark != null) {
            statusMark.setImageTintList(ColorStateList.valueOf(accent));
        }
        if (retryButton != null) {
            styleRetryButton(accent);
        }
        if (loadingProgress != null
                && loadingProgress.getIndeterminateDrawable() != null) {
            loadingProgress.getIndeterminateDrawable().setTint(accent);
        }
    }

    private void styleRetryButton(int accent) {
        if (retryButton == null) {
            return;
        }
        retryButton.setTextColor(accent);
        retryButton.setBackgroundTintList(null);
        retryButton.setBackground(retryButtonBackground(accent));
        retryButton.setPadding(dp(24), 0, dp(24), 0);
    }

    private Drawable retryButtonBackground(int accent) {
        GradientDrawable outline = new GradientDrawable();
        outline.setColor(Color.TRANSPARENT);
        outline.setCornerRadius(dp(24));
        outline.setStroke(Math.max(1, dp(1)), accent);
        int ripple = Color.argb(
                30, Color.red(accent), Color.green(accent), Color.blue(accent));
        return new RippleDrawable(
                ColorStateList.valueOf(ripple), outline, null);
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
        String baseUrl = "http://127.0.0.1:" + port + "/";
        CookieManager cookies = CookieManager.getInstance();
        int generation = ++sessionCookieGeneration;
        // Aynı ad/host/yoldaki bayat değer setCookie ile atomik biçimde
        // değiştirilir. removeSessionCookies eşzamansızdır; onu çağırıp hemen
        // yeni çerez kurmak, geciken silmenin taze çerezi de kaldırmasına ve
        // aralıklı 403 "uygulama oturumu doğrulanamadı" hatasına yol açar.
        // HttpOnly ayrıca belirteci yerel sayfanın JavaScript alanından uzak
        // tutar; SameSite sunucunun kendi oturum sözleşmesiyle aynıdır.
        String cookie = "divan_embedded_session=" + Uri.encode(token)
                + "; Path=/; HttpOnly; SameSite=Strict";
        cookies.setCookie(baseUrl, cookie, installed -> {
            if (generation != sessionCookieGeneration
                    || isFinishing() || isDestroyed()) {
                return;
            }
            if (!Boolean.TRUE.equals(installed)) {
                showStatus(
                        "Divan’ın güvenli uygulama oturumu hazırlanamadı.",
                        true);
                return;
            }
            cookies.flush();
            webView.loadUrl(baseUrl);
        });
    }

    private void showStatus(String message, boolean canRetry) {
        webView.setVisibility(View.INVISIBLE);
        statusPanel.setVisibility(View.VISIBLE);
        statusText.setText(message);
        loadingProgress.setVisibility(canRetry ? View.GONE : View.VISIBLE);
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
        boolean completionRequest = notificationPermissionForCompletion;
        boolean reminderRequest = notificationPermissionForReminder;
        notificationPermissionForCompletion = false;
        notificationPermissionForReminder = false;
        if (!granted && completionRequest) {
            NotificationPreferences.setCompletionEnabled(this, false);
            ChatNotificationController.purgeSensitiveNotifications(this);
        }
        if (granted) {
            CompletionNotificationController.ensureChannels(this);
            ReminderReceiver.ensureChannel(this);
            ReminderReceiver.rescheduleAll(getApplicationContext());
            ResponseKeeperJobService.schedule(getApplicationContext());
        } else if (completionRequest || reminderRequest) {
            toast("Bildirim izni verilmedi. Android ayarlarından daha sonra açabilirsiniz.");
        }
        notifyWebNotificationPermissionChanged(granted);
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
        ChatNotificationController.setAppVisible(true);
        backgroundPollGeneration++;
        ChatNotificationController.purgeSensitiveNotifications(this);
        boolean notificationsAllowed = notificationsPermitted();
        notifyWebNotificationPermissionChanged(notificationsAllowed);
        if (notificationsAllowed) {
            CompletionNotificationController.ensureChannels(this);
            ReminderReceiver.ensureChannel(this);
            // Kullanıcı Android ayarlarından izin verip döndüyse, daha önce
            // teslim edilemeyen nötr görev alarmlarını yeniden kur.
            ReminderReceiver.rescheduleAll(getApplicationContext());
        }
        if (pendingOpenConversationId > 0 && webView != null
                && webView.getVisibility() == View.VISIBLE) {
            webView.post(this::injectPendingConversationOpen);
        } else {
            queueNeedsAppConversationOpen();
        }
        refreshMobileViewportState();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            refreshMobileViewportState();
        }
    }

    @Override
    protected void onStop() {
        activityVisible = false;
        mobileViewportRefreshGeneration++;
        mobileViewportHeightCss = 0;
        mobileImeVisible = false;
        mobileImeStateKnown = false;
        ChatNotificationController.setAppVisible(false);
        // "Şimdilik kalsın" seçildiyse yeni bir gerçek uygulama dönüşünde
        // tekrar sorulabilir; aynı görünür Activity içinde döngü kurulmaz.
        needsAppPromptedRequestId = "";
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
        return NotificationPreferences.completionEnabled(this);
    }

    private boolean canPostCompletionNotification() {
        return completionNotificationsEnabled()
                && NotificationPreferences.systemPermissionGranted(this);
    }

    private boolean notificationsPermitted() {
        return NotificationPreferences.systemPermissionGranted(this);
    }

    private void requestNotificationPermission(
            boolean forCompletion, boolean forReminder) {
        runOnUiThread(() -> {
            notificationPermissionForCompletion |= forCompletion;
            notificationPermissionForReminder |= forReminder;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                    && checkSelfPermission(
                            Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(
                        new String[] {Manifest.permission.POST_NOTIFICATIONS},
                        REQUEST_NOTIFICATION_PERMISSION);
                return;
            }
            // İzin çalışma zamanında verilmiş olsa bile kullanıcı uygulama
            // bildirimlerini sistem ayarından bütünüyle kapatmış olabilir.
            boolean granted = NotificationPreferences
                    .systemPermissionGranted(this);
            notifyWebNotificationPermissionChanged(granted);
            if (!granted) {
                toast("Divan bildirimleri Android ayarlarında kapalı.");
            }
        });
    }

    private void notifyWebNotificationPermissionChanged(boolean granted) {
        if (webView == null) {
            return;
        }
        webView.post(() -> webView.evaluateJavascript(
                "window.divanAndroidNotificationPermissionChanged"
                        + "?window.divanAndroidNotificationPermissionChanged("
                        + (granted ? "true" : "false") + "):false",
                null));
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
            CompletionNotificationController.deliverPending(
                    this, serverPort, sessionToken);
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

    @Override
    protected void onDestroy() {
        backgroundPollGeneration++;
        sessionCookieGeneration++;
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
        if (isFinishing() || isDestroyed()) {
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
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            mainFrameLoadFailed = false;
            super.onPageStarted(view, url, favicon);
        }

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
            if (!mainFrameLoadFailed && isLocal(uri) && "/".equals(uri.getPath())
                    && uri.getQuery() == null) {
                CookieManager.getInstance().flush();
                view.clearHistory();
                showDivan();
                refreshMobileViewportState();
                queueNeedsAppConversationOpen();
            }
        }

        @Override
        public void onReceivedError(WebView view,
                                    WebResourceRequest request,
                                    WebResourceError error) {
            if (request.isForMainFrame()) {
                mainFrameLoadFailed = true;
                showStatus(
                        "Divan’ın yerel ekranına ulaşılamadı.\n"
                                + error.getDescription(),
                        true);
            }
        }

        @Override
        public void onReceivedHttpError(
                WebView view,
                WebResourceRequest request,
                WebResourceResponse errorResponse) {
            if (!request.isForMainFrame()) {
                return;
            }
            mainFrameLoadFailed = true;
            int status = errorResponse == null
                    ? 0 : errorResponse.getStatusCode();
            String suffix = status > 0 ? " (" + status + ")" : "";
            showStatus(
                    "Divan’ın güvenli yerel ekranı hazırlanamadı"
                            + suffix + ".",
                    true);
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
        /**
         * WebView'in native yerleşim yüksekliği CSS pikseli cinsindedir.
         * Samsung WebView IME kapandıktan sonra visualViewport ve 100dvh
         * değerlerini eski küçük yükseklikte tutabildiği için yalnız ölçüm
         * otoritesi olarak sunulur; inset veya padding uygulanmaz.
         */
        @JavascriptInterface
        public int mobileViewportHeight() {
            return Math.max(0, mobileViewportHeightCss);
        }

        @JavascriptInterface
        public boolean mobileImeVisible() {
            return mobileImeVisible;
        }

        @JavascriptInterface
        public boolean mobileImeStateKnown() {
            return mobileImeStateKnown;
        }

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
        public boolean notificationPreviewsEnabled() {
            return NotificationPreferences.previewsEnabled(
                    MainActivity.this);
        }

        @JavascriptInterface
        public boolean notificationInlineReplyEnabled() {
            return NotificationPreferences.inlineReplyEnabled(
                    MainActivity.this);
        }

        /**
         * UI kolaylığı için fail-closed anlık yeterlilik. Güvenlik kararı
         * yine notification-context ve POST kabulünde sunucuda tekrarlanır.
         */
        @JavascriptInterface
        public boolean notificationInlineReplyAvailable() {
            if (serverPort <= 0 || sessionToken.isEmpty()) {
                return false;
            }
            try {
                String body = DivanLocalApi.get(
                        serverPort,
                        sessionToken,
                        "/api/notification-reply-capability");
                return body != null
                        && new JSONObject(body).optBoolean(
                                "allowed", false);
            } catch (Exception ignored) {
                return false;
            }
        }

        @JavascriptInterface
        public boolean notificationPermissionGranted() {
            return notificationsPermitted();
        }

        @JavascriptInterface
        public void setReplyNotificationsEnabled(boolean enabled) {
            boolean wasEnabled = NotificationPreferences.completionEnabled(
                    MainActivity.this);
            boolean saved = NotificationPreferences.setCompletionEnabled(
                    MainActivity.this, enabled);
            runOnUiThread(() -> {
                if (!saved) {
                    toast("Bildirim tercihi kaydedilemedi.");
                    return;
                }
                if (wasEnabled && !enabled) {
                    backgroundPollGeneration++;
                    ChatNotificationController.purgeSensitiveNotifications(
                            MainActivity.this);
                    return;
                }
                if (!enabled) {
                    return;
                }
                CompletionNotificationController.ensureChannels(
                        MainActivity.this);
                requestNotificationPermission(true, false);
            });
        }

        @JavascriptInterface
        public void setNotificationPreviewsEnabled(boolean enabled) {
            boolean wasEnabled = NotificationPreferences.previewsEnabled(
                    MainActivity.this);
            boolean saved = NotificationPreferences.setPreviewsEnabled(
                    MainActivity.this, enabled);
            if (!saved) {
                toast("Bildirim önizleme tercihi kaydedilemedi.");
            } else if (wasEnabled && !enabled) {
                ChatNotificationController.purgeSensitiveNotifications(
                        MainActivity.this);
            }
        }

        @JavascriptInterface
        public void setNotificationInlineReplyEnabled(boolean enabled) {
            boolean wasEnabled = NotificationPreferences.inlineReplyEnabled(
                    MainActivity.this);
            boolean saved = NotificationPreferences.setInlineReplyEnabled(
                    MainActivity.this, enabled);
            runOnUiThread(() -> {
                if (!saved) {
                    toast("Bildirimden yanıt tercihi kaydedilemedi.");
                    return;
                }
                if (wasEnabled && !enabled) {
                    // Tepside daha önce hazırlanmış mutable eylem kalmasın.
                    ChatNotificationController.purgeSensitiveNotifications(
                            MainActivity.this);
                }
            });
        }

        @JavascriptInterface
        public void purgeSensitiveNotifications() {
            ChatNotificationController.purgeSensitiveNotifications(
                    MainActivity.this);
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
        public void appUnlocked() {
            ChatNotificationController.purgeSensitiveNotifications(
                    MainActivity.this);
            runOnUiThread(
                    MainActivity.this::queueNeedsAppConversationOpen);
        }

        @JavascriptInterface
        public void setSystemChrome(boolean dark) {
            runOnUiThread(() -> applySystemChrome(dark));
        }

        @JavascriptInterface
        public void setSystemChromeTheme(String theme) {
            final String requested = theme == null ? "paper" : theme;
            runOnUiThread(() ->
                    MainActivity.this.applyAndPersistSystemChromeTheme(
                            requested));
        }

        @JavascriptInterface
        public void openNotificationSettings() {
            runOnUiThread(() -> {
                Intent intent;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    intent = new Intent(
                            Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                            .putExtra(
                                    Settings.EXTRA_APP_PACKAGE,
                                    getPackageName());
                } else {
                    intent = new Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:" + getPackageName()));
                }
                try {
                    startActivity(intent);
                } catch (ActivityNotFoundException failure) {
                    toast("Android bildirim ayarları açılamadı.");
                }
            });
        }

        @JavascriptInterface
        public boolean scheduleReminderNotification(
                String id, String title, String body, long afterSeconds) {
            return scheduleReminderNotification(
                    id, title, body, afterSeconds, 0L);
        }

        @JavascriptInterface
        public boolean scheduleReminderNotification(
                String id, String title, String body, long afterSeconds,
                long conversationId) {
            if (!notificationsPermitted()) {
                requestNotificationPermission(false, true);
                return false;
            }
            return ReminderReceiver.schedule(
                    MainActivity.this, id, title, body, afterSeconds,
                    conversationId);
        }

        @JavascriptInterface
        public void cancelReminderNotification(String id) {
            ReminderReceiver.cancel(MainActivity.this, id);
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
