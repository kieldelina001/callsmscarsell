package org.sideline.carpromo;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.telephony.SmsMessage;

import java.util.HashMap;
import java.util.Map;

/**
 * Collects "sent" and "delivery report" results for each SMS (identified by a tag).
 * "sent" = the phone handed the message to the network.
 * "delivered" is reported ONLY if the carrier sends a delivery report back.
 */
public class SmsResultReceiver extends BroadcastReceiver {
    public static final String ACTION_SENT = "org.sideline.carpromo.SMS_SENT";
    public static final String ACTION_DELIVERED = "org.sideline.carpromo.SMS_DELIVERED";

    // each array: {expectedParts, okCount, failCount, code}
    private static final Map<String, int[]> SENT = new HashMap<String, int[]>();
    private static final Map<String, int[]> DELIV = new HashMap<String, int[]>();

    @Override
    public void onReceive(Context context, Intent intent) {
        String tag = intent.getStringExtra("tag");
        if (tag == null) return;
        int parts = intent.getIntExtra("parts", 1);
        String action = intent.getAction();

        if (ACTION_SENT.equals(action)) {
            int code = getResultCode();
            synchronized (SENT) {
                int[] a = SENT.get(tag);
                if (a == null) { a = new int[]{parts, 0, 0, 0}; SENT.put(tag, a); }
                if (code == Activity.RESULT_OK) a[1]++; else { a[2]++; a[3] = code; }
            }
        } else if (ACTION_DELIVERED.equals(action)) {
            boolean good = true;
            boolean parsed = false;
            int status = 0;
            try {
                byte[] pdu = intent.getByteArrayExtra("pdu");
                String fmt = intent.getStringExtra("format");
                if (pdu != null) {
                    SmsMessage m = (fmt == null) ? SmsMessage.createFromPdu(pdu)
                                                 : SmsMessage.createFromPdu(pdu, fmt);
                    if (m != null) { status = m.getStatus(); good = status < 0x20; parsed = true; }
                }
            } catch (Throwable t) { /* leave as "report received" */ }
            synchronized (DELIV) {
                int[] a = DELIV.get(tag);
                if (a == null) { a = new int[]{parts, 0, 0, 0}; DELIV.put(tag, a); }
                if (good) a[1]++; else { a[2]++; a[3] = status; }
                if (!parsed) a[3] = -1;
            }
        }
    }

    /** kind = "sent" or "delivery". Returns pending | sent | delivered | report_received | failed:CODE */
    public static String status(String kind, String tag) {
        boolean sent = "sent".equals(kind);
        Map<String, int[]> m = sent ? SENT : DELIV;
        synchronized (m) {
            int[] a = m.get(tag);
            if (a == null) return "pending";
            if (a[2] > 0) return "failed:" + a[3];
            if (a[1] >= a[0]) {
                if (sent) return "sent";
                return a[3] == -1 ? "report_received" : "delivered";
            }
            return "pending";
        }
    }
}
