package com.furkancanyilmaz.divan;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.Person;
import androidx.core.content.LocusIdCompat;
import androidx.core.content.pm.ShortcutInfoCompat;
import androidx.core.content.pm.ShortcutManagerCompat;
import androidx.core.graphics.drawable.IconCompat;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Android'in konuşma bildirimi sözleşmesini tek yerde kurar.
 *
 * <p>Bu sınıf yalnız kullanıcı içerik önizlemesine açıkça izin verdiğinde
 * çağrılır. MessagingStyle'ın kullanıcı kişisi gerçek kullanıcıyı, mesajın
 * gönderen kişisi ise AI tarafından canlandırılan ustayı temsil eder. Sohbet
 * geçmişi ve kullanıcı mesajı hiçbir zaman stile eklenmez.</p>
 */
final class ConversationNotificationSupport {

    static final String GROUP_KEY =
            "com.furkancanyilmaz.divan.AI_CONVERSATIONS";
    static final String SHORTCUT_PREFIX = "divan-conversation-";
    static final String LOCUS_PREFIX = "divan-conversation-locus-";
    static final String CONVERSATION_TAG_PREFIX =
            "divan.completion.conversation.";
    static final String AI_DISCLOSURE = "AI canlandırması";

    private ConversationNotificationSupport() {
    }

    static void applySingleAssistantMessage(
            Context context, NotificationCompat.Builder builder,
            int conversationId, String masterName, String assistantText,
            long messageTime) {
        String master = safeMasterName(masterName);
        String senderLabel = master + " · " + AI_DISCLOSURE;
        IconCompat avatar = avatarIcon(master);
        Person self = new Person.Builder()
                .setName("Siz")
                .setKey("divan-self")
                .setBot(false)
                .setImportant(false)
                .build();
        Person assistant = new Person.Builder()
                .setName(senderLabel)
                .setKey("divan-ai-" + conversationId)
                .setIcon(avatar)
                .setBot(true)
                .setImportant(false)
                .build();
        NotificationCompat.MessagingStyle style =
                new NotificationCompat.MessagingStyle(self)
                        .setGroupConversation(false)
                        .addMessage(new NotificationCompat.MessagingStyle
                                .Message(assistantText, messageTime,
                                assistant));
        builder.setContentTitle(master)
                .setContentText(assistantText)
                .setSubText(AI_DISCLOSURE)
                .setStyle(style)
                .addPerson(assistant)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .setGroup(GROUP_KEY)
                .setGroupAlertBehavior(
                        NotificationCompat.GROUP_ALERT_CHILDREN)
                .setNumber(1)
                .setWhen(messageTime)
                .setShowWhen(true)
                // Sistem, özel konuşma metninden otomatik eylem türetmesin.
                .setAllowSystemGeneratedContextualActions(false);

        // Android 7.1 (API 25) ile dinamik kısayol desteği başlar. API 24'te
        // MessagingStyle ve notification grouping çalışır; kısayol/locus
        // eklenmeden aynı güvenli görünüm korunur.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N_MR1) {
            ShortcutInfoCompat shortcut = conversationShortcut(
                    context, conversationId, master, assistant, avatar);
            // Burada yalnız bildirimin shortcut/locus bağını kurarız. Sistem
            // shortcut'ı, privacy-generation denetimiyle aynı kilit içindeki
            // postConversationIfPrivacyStateCurrent yayımlar.
            builder.setShortcutInfo(shortcut);
        }
    }

    static void publishConversationShortcut(
            Context context, int conversationId, String masterName) {
        if (context == null || conversationId <= 0
                || Build.VERSION.SDK_INT < Build.VERSION_CODES.N_MR1) {
            return;
        }
        String master = safeMasterName(masterName);
        IconCompat avatar = avatarIcon(master);
        Person assistant = new Person.Builder()
                .setName(master + " · " + AI_DISCLOSURE)
                .setKey("divan-ai-" + conversationId)
                .setIcon(avatar)
                .setBot(true)
                .setImportant(false)
                .build();
        try {
            // push, sistem limitinde en az alakalı Divan kısayolunu atomik
            // biçimde düşürür; sabit hash slotu çakışması yaratmaz.
            ShortcutManagerCompat.pushDynamicShortcut(
                    context,
                    conversationShortcut(
                            context, conversationId, master, assistant,
                            avatar));
        } catch (RuntimeException ignored) {
            // Launcher kısayolu reddetse bile mesaj bildirimi kaybolmaz.
        }
    }

    static String conversationTag(int conversationId) {
        // NotificationManager kimliği (tag,id) çiftidir. Tam konuşma kimliği
        // tag'de kaldığı için modulo/hash çakışması başka sohbeti ezemez.
        return CONVERSATION_TAG_PREFIX + conversationId;
    }

    static String reminderTag(String reminderId) {
        return "divan.reminder." + String.valueOf(reminderId);
    }

    static String shortcutId(int conversationId) {
        return SHORTCUT_PREFIX + conversationId;
    }

    static String locusId(int conversationId) {
        return LOCUS_PREFIX + conversationId;
    }

    /** Kilit/PIN/guest/safety geçişinde sistemdeki kişi adlarını da siler. */
    static void purgeConversationShortcuts(Context context) {
        if (context == null
                || Build.VERSION.SDK_INT < Build.VERSION_CODES.N_MR1) {
            return;
        }
        try {
            List<String> ids = new ArrayList<>();
            for (ShortcutInfoCompat shortcut
                    : ShortcutManagerCompat.getDynamicShortcuts(context)) {
                if (shortcut.getId() != null
                        && shortcut.getId().startsWith(SHORTCUT_PREFIX)) {
                    ids.add(shortcut.getId());
                }
            }
            if (!ids.isEmpty()) {
                removeShortcutIds(context, ids);
            }
        } catch (RuntimeException ignored) {
            // Bazı OEM launcher'ları sorgu sırasında hata verebilir. Tepsi
            // temizliği bundan bağımsız olarak NotificationManager'da sürer.
        }
    }

    static void removeConversationShortcut(
            Context context, int conversationId) {
        if (context == null || conversationId <= 0
                || Build.VERSION.SDK_INT < Build.VERSION_CODES.N_MR1) {
            return;
        }
        List<String> ids = new ArrayList<>();
        ids.add(shortcutId(conversationId));
        try {
            removeShortcutIds(context, ids);
        } catch (RuntimeException ignored) {
            // OEM shortcut servisi bildirimin nötrleştirilmesini engellemez.
        }
    }

    private static void removeShortcutIds(
            Context context, List<String> ids) {
        ShortcutManagerCompat.removeDynamicShortcuts(context, ids);
        // API 30+ cached conversation surfaces are also cleared; compat eski
        // sürümlerde güvenli bir no-op/fallback uygular.
        ShortcutManagerCompat.removeLongLivedShortcuts(context, ids);
    }

    private static ShortcutInfoCompat conversationShortcut(
            Context context, int conversationId, String master,
            Person assistant, IconCompat avatar) {
        Intent open = new Intent(context, MainActivity.class)
                .setAction(Intent.ACTION_VIEW)
                .setData(Uri.parse(
                        "divan://notification/conversation/"
                                + conversationId))
                .setPackage(context.getPackageName())
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(
                        ChatNotificationController.EXTRA_CONVERSATION_ID,
                        conversationId);
        return new ShortcutInfoCompat.Builder(
                context, shortcutId(conversationId))
                .setShortLabel(shortcutLabel(master))
                .setLongLabel(master + " · " + AI_DISCLOSURE)
                .setIcon(avatar)
                .setIntent(open)
                .setActivity(new ComponentName(context, MainActivity.class))
                .setPerson(assistant)
                .setLocusId(new LocusIdCompat(locusId(conversationId)))
                .setLongLived(true)
                .setIsConversation()
                .build();
    }

    /** Katalog kişisini dosya/ağ erişimi olmadan sade bir baş harfle gösterir. */
    private static IconCompat avatarIcon(String master) {
        final int size = 128;
        Bitmap bitmap = Bitmap.createBitmap(
                size, size, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(Color.rgb(109, 37, 53));
        canvas.drawCircle(size / 2f, size / 2f, size / 2f, paint);
        paint.setColor(Color.WHITE);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        paint.setTextSize(60f);
        int firstEnd = Character.charCount(master.codePointAt(0));
        String initial = master.substring(0, firstEnd)
                .toUpperCase(new Locale("tr", "TR"));
        float baseline = size / 2f
                - (paint.ascent() + paint.descent()) / 2f;
        canvas.drawText(initial, size / 2f, baseline, paint);
        return IconCompat.createWithBitmap(bitmap);
    }

    private static String safeMasterName(String raw) {
        String name = NotificationTextSanitizer.plainAssistantText(raw)
                .replace('\n', ' ')
                .trim();
        if (name.isEmpty()) {
            return "Divan";
        }
        return safePrefix(name, 64);
    }

    private static String shortcutLabel(String master) {
        return safePrefix(master + " · AI", 40);
    }

    private static String safePrefix(String value, int limit) {
        int end = Math.min(value.length(), Math.max(1, limit));
        if (end < value.length()
                && Character.isHighSurrogate(value.charAt(end - 1))) {
            end--;
        }
        return value.substring(0, end);
    }
}
