package com.furkancanyilmaz.divan;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Small Android Keystore-backed store for provider API keys.
 *
 * Only encrypted ciphertext and a per-value IV are written to preferences.
 * The AES key itself is non-exportable and remains in Android Keystore.
 */
public final class SecretStore {
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String KEY_ALIAS = "divan_provider_keys_v1";
    private static final String PREFS = "divan_encrypted_secrets";
    private static final String PREFIX = "v1:";

    private static SharedPreferences preferences;

    private SecretStore() {
    }

    public static synchronized void initialize(Context context) {
        if (preferences == null) {
            preferences = context.getApplicationContext()
                    .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        }
    }

    public static synchronized String get(String name) {
        requireInitialized();
        String encoded = preferences.getString(name, "");
        if (encoded == null || encoded.isEmpty()) {
            return "";
        }
        try {
            String[] parts = encoded.split(":", 3);
            if (parts.length != 3 || !("v1".equals(parts[0]))) {
                throw new IllegalArgumentException("Unknown secret format");
            }
            byte[] iv = Base64.decode(parts[1], Base64.NO_WRAP);
            byte[] encrypted = Base64.decode(parts[2], Base64.NO_WRAP);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        } catch (Exception exception) {
            // A restored preference cannot be decrypted with a different
            // device's Keystore key. Remove it instead of returning ciphertext.
            preferences.edit().remove(name).commit();
            return "";
        }
    }

    public static synchronized void put(String name, String value) {
        requireInitialized();
        String clean = value == null ? "" : value;
        if (clean.isEmpty()) {
            if (!preferences.edit().remove(name).commit()) {
                throw new IllegalStateException(
                        "API anahtarı güvenli alandan kaldırılamadı");
            }
            return;
        }
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] encrypted = cipher.doFinal(
                    clean.getBytes(StandardCharsets.UTF_8));
            String record = PREFIX
                    + Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)
                    + ":"
                    + Base64.encodeToString(encrypted, Base64.NO_WRAP);
            if (!preferences.edit().putString(name, record).commit()) {
                throw new IllegalStateException(
                        "API anahtarı güvenli alana kaydedilemedi");
            }
        } catch (Exception exception) {
            throw new IllegalStateException(
                    "API anahtarı güvenli alana kaydedilemedi", exception);
        }
    }

    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance(KEYSTORE);
        store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(
                    KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
            generator.init(new KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT
                            | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null))
                .getSecretKey();
    }

    private static void requireInitialized() {
        if (preferences == null) {
            throw new IllegalStateException("SecretStore is not initialized");
        }
    }
}
