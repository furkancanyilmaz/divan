package com.furkancanyilmaz.divan;

import android.content.Context;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import android.util.Base64;
import android.util.Log;

/**
 * Yerel Divan sunucusuna (gömülü Python) karşı küçük, senkron HTTP
 * yardımcıları. Bildirim yanıtı akışları Activity dışında da aynı
 * dayanıklı API yolunu kullanır.
 */
public final class DivanLocalApi {

    private DivanLocalApi() {
    }

    /** Gömülü sunucuyu başlatır (tekrar çağrıda aynısını döner) ve
     * {@code {port, token}} döner. */
    public static String[] startServer(Context context) {
        SecretStore.initialize(context.getApplicationContext());
        String requestedToken = randomToken();
        File dataDirectory = new File(
                context.getNoBackupFilesDir(), "divan-data");
        PyObject bridge = Python.getInstance()
                .getModule("android_entry");
        String[] launch = bridge.callAttr(
                "start_server",
                dataDirectory.getAbsolutePath(),
                requestedToken).toString().split("\\|", 2);
        if (launch.length != 2) {
            throw new IllegalStateException(
                    "Yerel sunucu adresi alınamadı");
        }
        return launch;
    }

    public static String get(
            int port, String token, String path) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(
                    "http://127.0.0.1:" + port + path);
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(4_000);
            connection.setReadTimeout(6_000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty(
                    "Cookie", "divan_embedded_session=" + token);
            connection.setRequestProperty("Accept", "application/json");
            int code = connection.getResponseCode();
            if (code != HttpURLConnection.HTTP_OK) {
                return null;
            }
            return readBody(connection.getInputStream());
        } catch (Exception ignored) {
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    /** İkili içerik (örn. portre görseli) indirir. */
    public static byte[] getBytes(
            int port, String token, String path) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(
                    "http://127.0.0.1:" + port + path);
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(4_000);
            connection.setReadTimeout(6_000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty(
                    "Cookie", "divan_embedded_session=" + token);
            int code = connection.getResponseCode();
            if (code != HttpURLConnection.HTTP_OK) {
                return null;
            }
            try (InputStream input = connection.getInputStream()) {
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                byte[] buffer = new byte[8 * 1024];
                int count;
                int total = 0;
                while ((count = input.read(buffer)) > 0) {
                    total += count;
                    if (total > 512 * 1024) {
                        return null;
                    }
                    output.write(buffer, 0, count);
                }
                return output.toByteArray();
            }
        } catch (Exception ignored) {
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public static boolean post(
            int port, String token, String path, String jsonBody) {
        Result result = postDetailed(port, token, path, jsonBody);
        return result != null && result.code >= 200 && result.code < 300;
    }

    /** Yanıt gövdesini de taşır; ağ hatasında null döner. */
    public static Result postDetailed(
            int port, String token, String path, String jsonBody) {
        return postDetailed(
                port, token, path, jsonBody, 4_000, 8_000);
    }

    /**
     * Kısa ömürlü receiver'lar için sınırlı zaman aşımıyla POST. Gövde veya
     * sağlayıcı içeriği hiçbir koşulda logcat'e yazılmaz.
     */
    public static Result postDetailed(
            int port, String token, String path, String jsonBody,
            int connectTimeoutMs, int readTimeoutMs) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(
                    "http://127.0.0.1:" + port + path);
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(Math.max(
                    250, Math.min(connectTimeoutMs, 8_000)));
            connection.setReadTimeout(Math.max(
                    250, Math.min(readTimeoutMs, 8_000)));
            connection.setInstanceFollowRedirects(false);
            connection.setRequestMethod("POST");
            connection.setRequestProperty(
                    "Cookie", "divan_embedded_session=" + token);
            connection.setRequestProperty(
                    "Content-Type", "application/json");
            connection.setRequestProperty("Accept", "application/json");
            connection.setDoOutput(true);
            byte[] bytes = jsonBody.getBytes(StandardCharsets.UTF_8);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
            int code = connection.getResponseCode();
            InputStream input = code >= 200 && code < 300
                    ? connection.getInputStream()
                    : connection.getErrorStream();
            String body = input == null ? "" : readBody(input);
            if (code < 200 || code >= 300) {
                // API hata gövdesi terapi veya görev metni taşıyabilir;
                // release logcat'e içerik kopyalama.
                Log.w("DivanLocalApi", "POST " + path + " -> " + code);
            }
            return new Result(code, body);
        } catch (Exception failure) {
            Log.w("DivanLocalApi", "POST " + path + " failed: "
                    + failure.getClass().getSimpleName());
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public static final class Result {
        public final int code;
        public final String body;

        Result(int code, String body) {
            this.code = code;
            this.body = body == null ? "" : body;
        }
    }

    private static String readBody(InputStream input) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (InputStream stream = input) {
            byte[] buffer = new byte[8 * 1024];
            int count;
            while ((count = stream.read(buffer)) > 0) {
                output.write(buffer, 0, count);
            }
        }
        return output.toString(StandardCharsets.UTF_8.name());
    }

    private static String randomToken() {
        byte[] bytes = new byte[32];
        new SecureRandom().nextBytes(bytes);
        return Base64.encodeToString(
                bytes, Base64.URL_SAFE
                        | Base64.NO_WRAP | Base64.NO_PADDING);
    }
}
