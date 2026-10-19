package org.sideline.carpromo;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.telephony.PhoneStateListener;
import android.telephony.TelephonyManager;

/**
 * Watches the phone's LOCAL call state: 0 = idle, 1 = ringing (an INCOMING call),
 * 2 = off-hook (a call is dialing or connected).
 * Android does NOT tell apps whether the other person's phone is ringing.
 */
public class CallMonitor {
    private static volatile int state = 0;
    private static final StringBuilder HISTORY = new StringBuilder();
    private static PhoneStateListener listener;
    private static boolean started = false;

    public static synchronized void start(final Context ctx) {
        if (started) return;
        final Context app = ctx.getApplicationContext();
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            @Override
            public void run() {
                try {
                    TelephonyManager tm =
                        (TelephonyManager) app.getSystemService(Context.TELEPHONY_SERVICE);
                    listener = new PhoneStateListener() {
                        @Override
                        public void onCallStateChanged(int s, String number) {
                            record(s);
                        }
                    };
                    tm.listen(listener, PhoneStateListener.LISTEN_CALL_STATE);
                    markStarted();
                } catch (Throwable t) {
                    // permission not granted yet - Python calls start() again later
                }
            }
        });
    }

    private static synchronized void markStarted() { started = true; }

    private static synchronized void record(int s) {
        state = s;
        HISTORY.append(System.currentTimeMillis()).append(':').append(s).append(';');
        if (HISTORY.length() > 4000) HISTORY.delete(0, 2000);
    }

    public static int getState() { return state; }

    public static synchronized String history() { return HISTORY.toString(); }

    public static synchronized void clearHistory() { HISTORY.setLength(0); }
}
