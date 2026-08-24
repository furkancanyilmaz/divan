package com.furkancanyilmaz.divan;

import android.text.Html;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Markdown/HTML model çıktısını yalnız düz bildirim metnine dönüştürür. */
final class NotificationTextSanitizer {

    /**
     * NotificationCompat/Android framework CharSequence sınırı 5.120 UTF-16
     * birimidir. Binder TransactionTooLargeException riskinden kaçınmak ve
     * sona açık bir uygulamaya-geçiş işareti sığdırmak için 5.000 kullanılır.
     * Bu ürün özeti değildir: platformun zorunlu güvenlik tavanıdır.
     */
    static final int ANDROID_TEXT_HARD_LIMIT = 5_000;
    private static final int SOURCE_HARD_LIMIT = 100_000;
    private static final String OPEN_FALLBACK =
            "\n\n[Tam metin için Divan'ı açın.]";
    private static final Pattern SCRIPT_STYLE = Pattern.compile(
            "(?is)<(script|style)\\b[^>]*>.*?</\\1\\s*>");
    private static final Pattern HTML_COMMENT = Pattern.compile(
            "(?s)<!--.*?-->");
    private static final Pattern MARKDOWN_IMAGE = Pattern.compile(
            "!\\[([^\\r\\n]{0,2048}?)\\]\\([^\\r\\n)]{0,8192}\\)");
    private static final Pattern MARKDOWN_LINK = Pattern.compile(
            "\\[([^\\r\\n]{0,2048}?)\\]\\([^\\r\\n)]{0,8192}\\)");
    private static final Pattern MARKDOWN_REFERENCE = Pattern.compile(
            "\\[([^\\r\\n]{0,2048}?)\\]\\[[^\\r\\n]{0,512}?\\]");
    private static final Pattern MARKDOWN_REFERENCE_DEFINITION =
            Pattern.compile(
                    "(?m)^\\s{0,3}\\[[^]\\r\\n]{1,512}\\]:\\s*\\S.*$");
    private static final Pattern MARKDOWN_TABLE_DIVIDER = Pattern.compile(
            "(?m)^\\s*\\|?(?:\\s*:?-{3,}:?\\s*\\|)+"
                    + "\\s*:?-{3,}:?\\s*\\|?\\s*$");
    private static final Pattern AUTOLINK = Pattern.compile(
            "<((?:(?:https?://)|(?:mailto:))[^>\\s]{1,8192})>",
            Pattern.CASE_INSENSITIVE);

    private NotificationTextSanitizer() {
    }

    static String plainAssistantText(String raw) {
        String source = String.valueOf(raw == null ? "" : raw);
        if (source.length() > SOURCE_HARD_LIMIT) {
            source = safePrefix(source, SOURCE_HARD_LIMIT);
        }
        source = source.replace("\r\n", "\n").replace('\r', '\n');
        source = SCRIPT_STYLE.matcher(source).replaceAll("");
        source = HTML_COMMENT.matcher(source).replaceAll("");
        source = AUTOLINK.matcher(source).replaceAll("$1");
        source = visibleMarkdownText(MARKDOWN_IMAGE, source);
        source = visibleMarkdownText(MARKDOWN_LINK, source);
        source = visibleMarkdownText(MARKDOWN_REFERENCE, source);
        source = MARKDOWN_REFERENCE_DEFINITION.matcher(source)
                .replaceAll("");
        source = MARKDOWN_TABLE_DIVIDER.matcher(source).replaceAll("");
        // Kod çitini kaldır, içindeki görünen metni koru.
        source = source.replaceAll(
                "(?m)^\\s*`{3,}(?:[A-Za-z0-9_+.#-]+)?\\s*$", "");

        // Html.fromHtml tag'leri yürütmez; String'e çevirme bütün span ve
        // tıklanabilir URL nesnelerini atar, entity'leri düz karaktere açar.
        String plain = Html.fromHtml(
                source, Html.FROM_HTML_MODE_LEGACY).toString();
        plain = plain.replace('\u00a0', ' ')
                .replace('\u2028', '\n')
                .replace('\u2029', '\n');

        // Satır-başı Markdown yapısını kaldır, görünen içeriği koru.
        plain = plain.replaceAll("(?m)^\\s{0,3}#{1,6}\\s+", "");
        plain = plain.replaceAll("(?m)^\\s{0,3}(?:>\\s*)+", "");
        plain = plain.replaceAll(
                "(?m)^\\s*(?:[-+*]|[0-9]{1,4}[.)]|[•◦▪])\\s+", "");
        plain = plain.replaceAll(
                "(?m)^\\s*(?:[-*_]\\s*){3,}$", "");
        plain = plain.replace("```", "").replace("`", "");
        plain = plain.replace("**", "").replace("__", "")
                .replace("~~", "");
        plain = plain.replace('|', ' ');
        // Kalan vurgu yıldızları markup'tır; alt çizgiyi kelime içindeyse
        // (dosya_adı gibi) koruruz.
        plain = plain.replace("*", "");
        plain = plain.replaceAll("(?<![\\p{L}\\p{N}])_(?=\\S)", "")
                .replaceAll("(?<=\\S)_(?![\\p{L}\\p{N}])", "");
        plain = plain.replaceAll(
                "\\\\([`*_{}\\[\\]()#+.!>~-])", "$1");
        plain = stripUnsafeControls(plain);
        plain = normalizePlainWhitespace(plain);
        if (plain.length() <= ANDROID_TEXT_HARD_LIMIT) {
            return plain;
        }
        int visibleLimit = ANDROID_TEXT_HARD_LIMIT
                - OPEN_FALLBACK.length();
        return safePrefix(plain, visibleLimit).trim() + OPEN_FALLBACK;
    }

    private static String visibleMarkdownText(
            Pattern pattern, String value) {
        String current = value;
        // İç içe olmayan standart Markdown linkleri için sınırlı tekrar.
        for (int pass = 0; pass < 4; pass++) {
            Matcher matcher = pattern.matcher(current);
            if (!matcher.find()) {
                break;
            }
            current = matcher.replaceAll("$1");
        }
        return current;
    }

    private static String stripUnsafeControls(String value) {
        StringBuilder clean = new StringBuilder(value.length());
        for (int offset = 0; offset < value.length();) {
            int codePoint = value.codePointAt(offset);
            offset += Character.charCount(codePoint);
            if (codePoint == '\n' || codePoint == '\t'
                    || !Character.isISOControl(codePoint)) {
                clean.appendCodePoint(codePoint);
            }
        }
        return clean.toString();
    }

    private static String normalizePlainWhitespace(String value) {
        String[] lines = value.split("\\n", -1);
        StringBuilder output = new StringBuilder(value.length());
        int blankLines = 0;
        for (String line : lines) {
            String compact = line.replaceAll("[\\t \\x0B\\f]+", " ")
                    .trim();
            if (compact.isEmpty()) {
                blankLines++;
                if (blankLines > 1 || output.length() == 0) {
                    continue;
                }
            } else {
                blankLines = 0;
            }
            if (output.length() > 0) {
                output.append('\n');
            }
            output.append(compact);
        }
        return output.toString().trim();
    }

    private static String safePrefix(String value, int limit) {
        int end = Math.max(0, Math.min(limit, value.length()));
        if (end > 0 && end < value.length()
                && Character.isHighSurrogate(value.charAt(end - 1))) {
            end--;
        }
        return value.substring(0, end);
    }
}
