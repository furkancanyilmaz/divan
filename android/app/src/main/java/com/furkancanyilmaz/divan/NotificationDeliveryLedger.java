package com.furkancanyilmaz.divan;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** Kalıcı, kapsamlı ve sınırlı bildirim teslim defteri. */
final class NotificationDeliveryLedger {

    private static final String PREFERENCES =
            "divan_response_notifications_v2";
    private static final String DELIVERED_KEY = "delivered_request_ids";
    private static final String MAIN_CURSOR_KEY = "main_cursor";
    private static final String GUEST_CURSOR_KEY = "guest_cursor";
    private static final int MAX_DELIVERED_IDS = 96;

    private NotificationDeliveryLedger() {
    }

    private static SharedPreferences preferences(Context context) {
        return context.getApplicationContext().getSharedPreferences(
                PREFERENCES, Context.MODE_PRIVATE);
    }

    static synchronized long cursor(Context context, String scope) {
        return preferences(context).getLong(cursorKey(scope), 0L);
    }

    static synchronized boolean wasDelivered(
            Context context, String requestId) {
        return requestId != null && !requestId.isEmpty()
                && deliveredIds(context).contains(requestId);
    }

    static synchronized void mark(
            Context context, String scope, long cursor,
            List<String> requestIds) {
        Set<String> ids = deliveredIds(context);
        if (requestIds != null) {
            for (String requestId : requestIds) {
                if (requestId != null && !requestId.isEmpty()) {
                    ids.remove(requestId);
                    ids.add(requestId);
                }
            }
        }
        while (ids.size() > MAX_DELIVERED_IDS) {
            String oldest = ids.iterator().next();
            ids.remove(oldest);
        }
        JSONArray encoded = new JSONArray();
        for (String id : ids) {
            encoded.put(id);
        }
        SharedPreferences.Editor editor = preferences(context).edit()
                .putString(DELIVERED_KEY, encoded.toString());
        long previous = cursor(context, scope);
        if (cursor > previous) {
            editor.putLong(cursorKey(scope), cursor);
        }
        editor.commit();
    }

    static synchronized void markRequest(
            Context context, String requestId) {
        List<String> one = new ArrayList<>();
        one.add(requestId);
        mark(context, "main", cursor(context, "main"), one);
    }

    static synchronized String latestDelivered(Context context) {
        String latest = "";
        for (String id : deliveredIds(context)) {
            latest = id;
        }
        return latest;
    }

    private static String cursorKey(String scope) {
        return "guest".equals(scope) ? GUEST_CURSOR_KEY : MAIN_CURSOR_KEY;
    }

    private static LinkedHashSet<String> deliveredIds(Context context) {
        String raw = preferences(context).getString(DELIVERED_KEY, "[]");
        LinkedHashSet<String> result = new LinkedHashSet<>();
        try {
            JSONArray values = new JSONArray(raw);
            for (int index = 0; index < values.length(); index++) {
                String value = values.optString(index, "");
                if (!value.isEmpty()) {
                    result.add(value);
                }
            }
        } catch (JSONException ignored) {
            // Bozuk teslim defteri yalnızca yeniden kurulur; bildirim
            // içeriği veya kullanıcı verisi burada saklanmaz.
        }
        return result;
    }
}
