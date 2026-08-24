package com.furkancanyilmaz.divan;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;

import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Bildirimden gönderilen kullanıcı metninin şifreli, yerel teslim kutusu.
 *
 * <p>Metin hiçbir zaman SharedPreferences, JobInfo, Intent extra, log veya
 * komut satırına kopyalanmaz. Tam zarf Android Keystore'daki ayrı bir AES-GCM
 * anahtarıyla şifrelenip {@code noBackupFilesDir} altında request başına
 * atomik olarak saklanır. Dosya adı yalnız request kimliğinin SHA-256
 * özetidir; aynı request kimliğinde ilk kalıcı kayıt kazanır.</p>
 */
final class NotificationReplyOutbox {

    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String KEY_ALIAS =
            "divan_notification_reply_outbox_v1";
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final String DIRECTORY = "notification-reply-outbox-v1";
    private static final String SUFFIX = ".reply";
    /**
     * Sunucunun güvenlik kapısında uygulamaya yönlendirdiği ama kullanıcının
     * henüz normal sohbet kutusuna geri almadığı şifreli yanıtlar. Uzantı
     * yalnız teslim durumunu açıklar; dosya adı request özetidir ve içerik
     * aynı AES-GCM zarfı olarak kalır.
     */
    private static final String NEEDS_APP_SUFFIX = ".needs_app";
    private static final int MAGIC = 0x4456524f; // DVRO
    private static final int SCHEMA = 1;
    private static final int IV_BYTES = 12;
    private static final int TAG_BITS = 128;
    private static final int MAX_RECORDS = 32;
    private static final int MAX_ENVELOPE_BYTES = 128 * 1024;
    private static final Object LOCK = new Object();
    private static final SecureRandom RANDOM = new SecureRandom();

    private NotificationReplyOutbox() {
    }

    /** Anahtarı bildirim eylemi gösterilmeden önce hazırlar. */
    static boolean prepare(Context context) {
        if (context == null) {
            return false;
        }
        synchronized (LOCK) {
            try {
                secretKey();
                File directory = directory(context);
                return directory.isDirectory() || directory.mkdirs();
            } catch (Exception ignored) {
                // Hata metni Keystore sağlayıcı ayrıntısı taşıyabilir.
                return false;
            }
        }
    }

    /**
     * Tam zarfı şifreleyip fsync ile kalıcılaştırır. Aynı request dosyası
     * varsa mevcut kayıt değiştirilmez; sunucudaki idempotency sınırıyla aynı
     * "ilk yazım kazanır" kuralı korunur.
     */
    static boolean enqueue(
            Context context, int conversationId, String message,
            String requestId, String sourceId, long replyTo,
            int sourceNotificationId) throws Exception {
        return enqueue(context, conversationId, message, requestId,
                sourceId, replyTo, "", sourceNotificationId);
    }

    static boolean enqueue(
            Context context, int conversationId, String message,
            String requestId, String sourceId, long replyTo,
            String sourceNotificationTag,
            int sourceNotificationId) throws Exception {
        validate(conversationId, message, requestId, sourceId, replyTo,
                sourceNotificationTag, sourceNotificationId);
        synchronized (LOCK) {
            File directory = directory(context);
            if (!directory.isDirectory() && !directory.mkdirs()) {
                throw new IllegalStateException("outbox kullanılamıyor");
            }
            String digest = digest(requestId);
            File target = new File(directory, digest + SUFFIX);
            File needsApp = new File(directory,
                    digest + NEEDS_APP_SUFFIX);
            // Önceki süreç AtomicFile rename adımında öldüyse tamamlanmış
            // ciphertext .new/.bak dosyasını yeniden görünür yap.
            recoverAtomicTempsLocked(directory);
            if (needsApp.isFile()) {
                try {
                    Record existing = read(needsApp);
                    if (requestId.equals(existing.requestId)) {
                        // Güvenlik kapısında uygulamaya yönlendirilmiş aynı
                        // yanıtı yeni bir RemoteInput tekrar kuyruğa sokmasın.
                        return true;
                    }
                } catch (Exception corrupt) {
                    // Geçersiz ciphertext aşağıdaki yeni kaydı engellemesin.
                }
                if (!delete(needsApp)) {
                    throw new IllegalStateException(
                            "bozuk uygulama yanıtı temizlenemedi");
                }
            }
            if (target.isFile()) {
                try {
                    Record existing = read(target);
                    if (requestId.equals(existing.requestId)) {
                        // Farklı bir ikinci metin bile ilk zarfı ezemez.
                        return true;
                    }
                } catch (Exception corrupt) {
                    // Tamamlanmamış/tahrif edilmiş ciphertext yeni, geçerli
                    // kullanıcı gönderimini sonsuza dek bloke etmesin.
                }
                if (!delete(target)) {
                    throw new IllegalStateException(
                            "bozuk outbox kaydı temizlenemedi");
                }
            }
            if (allFilesLocked(directory).size() >= MAX_RECORDS) {
                throw new IllegalStateException("outbox kapasitesi dolu");
            }

            JSONObject envelope = new JSONObject();
            envelope.put("schema", SCHEMA);
            envelope.put("conversation_id", conversationId);
            envelope.put("message", message);
            envelope.put("request_id", requestId);
            envelope.put("source_id", sourceId);
            envelope.put("reply_to", replyTo);
            envelope.put("source_notification_tag",
                    ChatNotificationController.safeNotificationTag(
                            sourceNotificationTag));
            envelope.put("source_notification_id", sourceNotificationId);
            envelope.put("created_at", System.currentTimeMillis());
            byte[] plaintext = envelope.toString().getBytes(
                    StandardCharsets.UTF_8);
            if (plaintext.length > MAX_ENVELOPE_BYTES) {
                Arrays.fill(plaintext, (byte) 0);
                throw new IllegalArgumentException("outbox kaydı çok büyük");
            }

            byte[] iv = new byte[IV_BYTES];
            RANDOM.nextBytes(iv);
            byte[] ciphertext = null;
            byte[] encoded = null;
            try {
                Cipher cipher = Cipher.getInstance(TRANSFORMATION);
                cipher.init(Cipher.ENCRYPT_MODE, secretKey(),
                        new GCMParameterSpec(TAG_BITS, iv));
                cipher.updateAAD(aad(digest));
                ciphertext = cipher.doFinal(plaintext);
                ByteArrayOutputStream bytes = new ByteArrayOutputStream(
                        16 + iv.length + ciphertext.length);
                try (DataOutputStream output = new DataOutputStream(bytes)) {
                    output.writeInt(MAGIC);
                    output.writeByte(SCHEMA);
                    output.writeByte(iv.length);
                    output.writeInt(ciphertext.length);
                    output.write(iv);
                    output.write(ciphertext);
                }
                encoded = bytes.toByteArray();
                AtomicFile atomic = new AtomicFile(target);
                FileOutputStream output = null;
                try {
                    output = atomic.startWrite();
                    output.write(encoded);
                    output.getFD().sync();
                    atomic.finishWrite(output);
                    output = null;
                } catch (Exception failure) {
                    if (output != null) {
                        atomic.failWrite(output);
                    }
                    throw failure;
                }
                return true;
            } finally {
                Arrays.fill(plaintext, (byte) 0);
                Arrays.fill(iv, (byte) 0);
                if (ciphertext != null) {
                    Arrays.fill(ciphertext, (byte) 0);
                }
                if (encoded != null) {
                    Arrays.fill(encoded, (byte) 0);
                }
            }
        }
    }

    static boolean hasPending(Context context) {
        if (context == null) {
            return false;
        }
        synchronized (LOCK) {
            try {
                return !pendingFilesLocked(directory(context)).isEmpty();
            } catch (RuntimeException ignored) {
                return false;
            }
        }
    }

    static List<File> pendingFiles(Context context) {
        if (context == null) {
            return new ArrayList<>();
        }
        synchronized (LOCK) {
            try {
                return new ArrayList<>(pendingFilesLocked(
                        directory(context)));
            } catch (RuntimeException ignored) {
                return new ArrayList<>();
            }
        }
    }

    static boolean hasNeedsApp(Context context) {
        if (context == null) {
            return false;
        }
        synchronized (LOCK) {
            try {
                return !needsAppFilesLocked(directory(context)).isEmpty();
            } catch (RuntimeException ignored) {
                return false;
            }
        }
    }

    static List<File> needsAppFiles(Context context) {
        if (context == null) {
            return new ArrayList<>();
        }
        synchronized (LOCK) {
            try {
                return new ArrayList<>(needsAppFilesLocked(
                        directory(context)));
            } catch (RuntimeException ignored) {
                return new ArrayList<>();
            }
        }
    }

    /** İlk güvenlik-yönlendirmeli zarfı yalnız istenen görüşme için açar. */
    static Record firstNeedsApp(
            Context context, int conversationId) {
        if (context == null || conversationId < 0) {
            return null;
        }
        for (File file : needsAppFiles(context)) {
            try {
                Record record = read(file);
                if (conversationId == 0
                        || record.conversationId == conversationId) {
                    return record;
                }
            } catch (Exception corrupt) {
                // Kimliği doğrulanamayan ciphertext kullanıcı metnine
                // dönüştürülemez; güvenli kapalı davran ve yalnız onu sil.
                delete(file);
            }
        }
        return null;
    }

    /** Süreç/cihaz yeniden açılışında yalnız nötr uygulamaya-dön eylemini kurar. */
    static void repostNeedsAppNotifications(Context context) {
        if (context == null) {
            return;
        }
        Context app = context.getApplicationContext();
        for (File file : needsAppFiles(app)) {
            try {
                Record record = read(file);
                ChatNotificationController.showNeedsApp(
                        app, record.conversationId, record.requestId);
            } catch (Exception corrupt) {
                delete(file);
            }
        }
    }

    /**
     * Bir güvenlik 409'unu otomatik teslim kuyruğundan çıkarıp ayrı şifreli
     * uygulama-onayı durumuna geçirir. Hedef fsync olmadan kaynak silinmez;
     * süreç iki adım arasında ölürse sonraki deneme idempotent biçimde
     * hedefi doğrular ve kaynak kopyayı temizler.
     */
    static boolean moveToNeedsApp(Record record) {
        if (record == null || record.file == null) {
            return false;
        }
        synchronized (LOCK) {
            try {
                File source = record.file;
                if (!source.isFile()
                        || !source.getName().matches(
                        "[0-9a-f]{64}\\.reply")) {
                    return source.getName().matches(
                            "[0-9a-f]{64}\\.needs_app");
                }
                String digest = source.getName().substring(
                        0, source.getName().length() - SUFFIX.length());
                File target = new File(source.getParentFile(),
                        digest + NEEDS_APP_SUFFIX);
                if (target.isFile()) {
                    Record existing = read(target);
                    if (!record.requestId.equals(existing.requestId)) {
                        return false;
                    }
                    return delete(source);
                }

                byte[] encrypted;
                try (FileInputStream input =
                             new AtomicFile(source).openRead()) {
                    if (input.getChannel().size() <= 0
                            || input.getChannel().size()
                            > MAX_ENVELOPE_BYTES) {
                        return false;
                    }
                    encrypted = readBounded(input, MAX_ENVELOPE_BYTES);
                }
                try {
                    AtomicFile atomic = new AtomicFile(target);
                    FileOutputStream output = null;
                    try {
                        output = atomic.startWrite();
                        output.write(encrypted);
                        output.getFD().sync();
                        atomic.finishWrite(output);
                        output = null;
                    } catch (Exception failure) {
                        if (output != null) {
                            atomic.failWrite(output);
                        }
                        throw failure;
                    }
                    Record moved = read(target);
                    if (!record.requestId.equals(moved.requestId)) {
                        delete(target);
                        return false;
                    }
                } finally {
                    Arrays.fill(encrypted, (byte) 0);
                }
                return delete(source);
            } catch (Exception ignored) {
                return false;
            }
        }
    }

    /** Yalnız kullanıcıya gösterilen aynı needs_app request kaydını tüketir. */
    static boolean consumeNeedsApp(Record expected) {
        if (expected == null || expected.file == null
                || !expected.file.getName().matches(
                "[0-9a-f]{64}\\.needs_app")) {
            return false;
        }
        synchronized (LOCK) {
            try {
                Record current = read(expected.file);
                if (!expected.requestId.equals(current.requestId)
                        || expected.conversationId
                        != current.conversationId) {
                    return false;
                }
                return delete(expected.file);
            } catch (Exception ignored) {
                return false;
            }
        }
    }

    static Record read(File file) throws Exception {
        if (file == null || !file.isFile()
                || !file.getName().matches(
                "[0-9a-f]{64}\\.(?:reply|needs_app)")) {
            throw new IllegalArgumentException("geçersiz outbox dosyası");
        }
        synchronized (LOCK) {
            String filename = file.getName();
            String digest = filename.substring(0, 64);
            AtomicFile atomic = new AtomicFile(file);
            byte[] encoded;
            try (FileInputStream input = atomic.openRead()) {
                if (input.getChannel().size() <= 0
                        || input.getChannel().size() > MAX_ENVELOPE_BYTES) {
                    throw new IllegalArgumentException(
                            "geçersiz outbox boyutu");
                }
                encoded = readBounded(input, MAX_ENVELOPE_BYTES);
            }
            byte[] iv = null;
            byte[] ciphertext = null;
            byte[] plaintext = null;
            try (DataInputStream input = new DataInputStream(
                    new ByteArrayInputStream(encoded))) {
                if (input.readInt() != MAGIC || input.readUnsignedByte() != SCHEMA) {
                    throw new IllegalArgumentException(
                            "geçersiz outbox şeması");
                }
                int ivLength = input.readUnsignedByte();
                int cipherLength = input.readInt();
                if (ivLength != IV_BYTES || cipherLength < 16
                        || cipherLength > MAX_ENVELOPE_BYTES
                        || 10L + ivLength + cipherLength != encoded.length) {
                    throw new IllegalArgumentException(
                            "geçersiz outbox zarfı");
                }
                iv = new byte[ivLength];
                ciphertext = new byte[cipherLength];
                input.readFully(iv);
                input.readFully(ciphertext);
                Cipher cipher = Cipher.getInstance(TRANSFORMATION);
                cipher.init(Cipher.DECRYPT_MODE, secretKey(),
                        new GCMParameterSpec(TAG_BITS, iv));
                cipher.updateAAD(aad(digest));
                plaintext = cipher.doFinal(ciphertext);
                JSONObject envelope = new JSONObject(new String(
                        plaintext, StandardCharsets.UTF_8));
                Record record = Record.from(file, envelope);
                if (!digest(record.requestId).equals(digest)) {
                    throw new IllegalArgumentException(
                            "outbox kimliği eşleşmiyor");
                }
                return record;
            } finally {
                Arrays.fill(encoded, (byte) 0);
                if (iv != null) {
                    Arrays.fill(iv, (byte) 0);
                }
                if (ciphertext != null) {
                    Arrays.fill(ciphertext, (byte) 0);
                }
                if (plaintext != null) {
                    Arrays.fill(plaintext, (byte) 0);
                }
            }
        }
    }

    static boolean delete(File file) {
        if (file == null) {
            return true;
        }
        synchronized (LOCK) {
            AtomicFile atomic = new AtomicFile(file);
            atomic.delete();
            return !file.exists()
                    && !new File(file.getPath() + ".new").exists()
                    && !new File(file.getPath() + ".bak").exists();
        }
    }

    private static SecretKey secretKey() throws Exception {
        KeyStore store = KeyStore.getInstance(KEYSTORE);
        store.load(null);
        if (store.containsAlias(KEY_ALIAS)) {
            java.security.Key key = store.getKey(KEY_ALIAS, null);
            if (key instanceof SecretKey) {
                return (SecretKey) key;
            }
            throw new IllegalStateException("outbox anahtarı geçersiz");
        }
        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
        generator.init(new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT
                        | KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(
                        KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .setUserAuthenticationRequired(false)
                .build());
        return generator.generateKey();
    }

    private static File directory(Context context) {
        return new File(context.getApplicationContext().getNoBackupFilesDir(),
                DIRECTORY);
    }

    private static List<File> pendingFilesLocked(File directory) {
        recoverAtomicTempsLocked(directory);
        File[] files = directory.listFiles((parent, name) ->
                name != null && name.matches("[0-9a-f]{64}\\.reply"));
        List<File> pending = new ArrayList<>();
        if (files != null) {
            pending.addAll(Arrays.asList(files));
            pending.sort(Comparator.comparing(File::getName));
        }
        return pending;
    }

    private static List<File> needsAppFilesLocked(File directory) {
        recoverAtomicTempsLocked(directory);
        File[] files = directory.listFiles((parent, name) ->
                name != null
                        && name.matches(
                        "[0-9a-f]{64}\\.needs_app"));
        List<File> needsApp = new ArrayList<>();
        if (files != null) {
            needsApp.addAll(Arrays.asList(files));
            needsApp.sort(Comparator.comparing(File::getName));
        }
        return needsApp;
    }

    private static List<File> allFilesLocked(File directory) {
        List<File> files = pendingFilesLocked(directory);
        files.addAll(needsAppFilesLocked(directory));
        return files;
    }

    /** AtomicFile'ın güç/süreç kesintisinde bıraktığı şifreli yan dosyalar. */
    private static void recoverAtomicTempsLocked(File directory) {
        if (directory == null || !directory.isDirectory()) {
            return;
        }
        File[] files = directory.listFiles((parent, name) -> name != null
                && (name.matches("[0-9a-f]{64}\\.reply\\.new")
                || name.matches("[0-9a-f]{64}\\.reply\\.bak")
                || name.matches(
                "[0-9a-f]{64}\\.needs_app\\.new")
                || name.matches(
                "[0-9a-f]{64}\\.needs_app\\.bak")));
        if (files == null) {
            return;
        }
        Arrays.sort(files, Comparator.comparing(File::getName));
        for (File sidecar : files) {
            String path = sidecar.getPath();
            String suffix = path.endsWith(".new") ? ".new" : ".bak";
            File base = new File(path.substring(
                    0, path.length() - suffix.length()));
            if (base.isFile()) {
                sidecar.delete();
            } else {
                // İçerik yalnız ciphertext'tir. Eksikse GCM doğrulaması
                // drain sırasında başarısız olur ve fail-closed temizlenir.
                sidecar.renameTo(base);
            }
        }
    }

    private static byte[] readBounded(
            FileInputStream input, int maximum) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int total = 0;
        int count;
        while ((count = input.read(buffer)) != -1) {
            total += count;
            if (total > maximum) {
                throw new IllegalArgumentException("outbox kaydı çok büyük");
            }
            output.write(buffer, 0, count);
        }
        Arrays.fill(buffer, (byte) 0);
        return output.toByteArray();
    }

    private static byte[] aad(String digest) {
        return ("divan-notification-reply|" + SCHEMA + "|" + digest)
                .getBytes(StandardCharsets.UTF_8);
    }

    private static String digest(String value) throws Exception {
        byte[] bytes = MessageDigest.getInstance("SHA-256").digest(
                value.getBytes(StandardCharsets.UTF_8));
        StringBuilder encoded = new StringBuilder(64);
        for (byte item : bytes) {
            encoded.append(String.format("%02x", item & 0xff));
        }
        Arrays.fill(bytes, (byte) 0);
        return encoded.toString();
    }

    private static void validate(
            int conversationId, String message, String requestId,
            String sourceId, long replyTo, String sourceNotificationTag,
            int sourceNotificationId) {
        if (conversationId <= 0 || replyTo <= 0L
                || sourceNotificationId <= 0 || message == null
                || message.trim().isEmpty() || message.length() > 50_000
                || requestId == null
                || !requestId.matches(
                        "[A-Za-z0-9][A-Za-z0-9._:\\-]{11,127}")
                || sourceId == null
                || !sourceId.matches(
                        "[A-Za-z0-9][A-Za-z0-9._:\\-]{0,159}")
                || sourceNotificationTag != null
                && !sourceNotificationTag.isEmpty()
                && !sourceNotificationTag.equals(
                        ChatNotificationController.safeNotificationTag(
                                sourceNotificationTag))) {
            throw new IllegalArgumentException("geçersiz outbox kaydı");
        }
    }

    static final class Record {
        final File file;
        final int conversationId;
        final String message;
        final String requestId;
        final String sourceId;
        final long replyTo;
        final String sourceNotificationTag;
        final int sourceNotificationId;

        private Record(
                File file, int conversationId, String message,
                String requestId, String sourceId, long replyTo,
                String sourceNotificationTag,
                int sourceNotificationId) {
            this.file = file;
            this.conversationId = conversationId;
            this.message = message;
            this.requestId = requestId;
            this.sourceId = sourceId;
            this.replyTo = replyTo;
            this.sourceNotificationTag = sourceNotificationTag;
            this.sourceNotificationId = sourceNotificationId;
        }

        static Record from(File file, JSONObject envelope) {
            if (envelope.optInt("schema", 0) != SCHEMA) {
                throw new IllegalArgumentException("geçersiz outbox şeması");
            }
            int conversationId = envelope.optInt("conversation_id", 0);
            String message = envelope.optString("message", "");
            String requestId = envelope.optString("request_id", "");
            String sourceId = envelope.optString("source_id", "");
            long replyTo = envelope.optLong("reply_to", 0L);
            String sourceNotificationTag = envelope.optString(
                    "source_notification_tag", "");
            int sourceNotificationId = envelope.optInt(
                    "source_notification_id", 0);
            validate(conversationId, message, requestId, sourceId, replyTo,
                    sourceNotificationTag, sourceNotificationId);
            return new Record(file, conversationId, message, requestId,
                    sourceId, replyTo, sourceNotificationTag,
                    sourceNotificationId);
        }
    }
}
