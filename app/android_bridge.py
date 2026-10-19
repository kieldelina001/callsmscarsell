"""The ONLY file that talks to Android (via pyjnius).  NOT tested on a real phone yet.

What Android 10 lets an app do (and not do):
  * Remote ringing is NOT exposed. We only see the LOCAL state (idle / off-hook).
  * "Answered" is proven afterwards from the phone's call log (duration > 0).
  * Call SIM routing: we ask Android to use a specific phone account. If we cannot
    map your SIM to a phone account we REFUSE to call (we never switch SIMs silently).
  * SMS SIM routing uses SmsManager for a specific subscription (reliable).
  * "Sent" = handed to the network. "Delivered" only if the carrier returns a report.
"""
import re
import time

PERM_CALL = "android.permission.CALL_PHONE"
PERM_PHONE = "android.permission.READ_PHONE_STATE"
PERM_SMS = "android.permission.SEND_SMS"
PERM_READ_SMS = "android.permission.READ_SMS"
PERM_LOG = "android.permission.READ_CALL_LOG"
PERM_ANSWER = "android.permission.ANSWER_PHONE_CALLS"
PERM_READ_STORAGE = "android.permission.READ_EXTERNAL_STORAGE"
PERM_WRITE_STORAGE = "android.permission.WRITE_EXTERNAL_STORAGE"
ALL_PERMS = [PERM_CALL, PERM_PHONE, PERM_SMS, PERM_READ_SMS, PERM_LOG, PERM_ANSWER,
             PERM_READ_STORAGE, PERM_WRITE_STORAGE]

SIM_STATES = {0: "unknown", 1: "no SIM card", 2: "locked (PIN needed)", 3: "locked (PUK needed)",
              4: "network locked", 5: "ready", 6: "not ready", 7: "disabled",
              8: "card error", 9: "restricted"}


def request_all_permissions(callback=None):
    from android.permissions import request_permissions
    request_permissions(ALL_PERMS, callback)


def permission_status():
    from android.permissions import check_permission
    return {p.split(".")[-1]: bool(check_permission(p)) for p in ALL_PERMS}


class AndroidBridge:
    is_dry_run = False

    def __init__(self):
        from jnius import autoclass, cast
        self._auto, self._cast = autoclass, cast
        self.ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        self.CallMonitor = autoclass("org.sideline.carpromo.CallMonitor")
        self.SmsRx = autoclass("org.sideline.carpromo.SmsResultReceiver")
        self._req = 0
        self._register_receiver()
        self.CallMonitor.start(self.ctx)

    # ---------- helpers ----------
    def _has(self, perm):
        from android.permissions import check_permission
        return bool(check_permission(perm))

    @staticmethod
    def _s(x):
        if x is None:
            return ""
        return x if isinstance(x, str) else x.toString()

    def _register_receiver(self):
        IntentFilter = self._auto("android.content.IntentFilter")
        f = IntentFilter()
        f.addAction(self.SmsRx.ACTION_SENT)
        f.addAction(self.SmsRx.ACTION_DELIVERED)
        self._rx = self.SmsRx()
        self.ctx.registerReceiver(self._rx, f)

    def _tm(self):
        return self._cast("android.telephony.TelephonyManager", self.ctx.getSystemService("phone"))

    def permissions_missing(self, need_call, need_sms):
        need = [PERM_PHONE]
        if need_call:
            need += [PERM_CALL, PERM_ANSWER, PERM_LOG]
        if need_sms:
            need += [PERM_SMS]
        return [p.split(".")[-1] for p in need if not self._has(p)]

    # ---------- SIM detection ----------
    def list_sims(self):
        if not self._has(PERM_PHONE):
            raise RuntimeError("READ_PHONE_STATE permission is not granted")
        sm = self._cast("android.telephony.SubscriptionManager",
                        self.ctx.getSystemService("telephony_subscription_service"))
        lst = sm.getActiveSubscriptionInfoList()
        out = []
        if lst is None:
            return out
        tm = self._tm()
        for i in range(lst.size()):
            info = self._cast("android.telephony.SubscriptionInfo", lst.get(i))
            sub_id = info.getSubscriptionId()
            try:
                state = tm.createForSubscriptionId(sub_id).getSimState()
            except Exception:
                state = 0
            out.append({
                "slot": info.getSimSlotIndex(), "sub_id": sub_id,
                "carrier": self._s(info.getCarrierName()) or self._s(info.getDisplayName()),
                "number": self._s(info.getNumber()), "iccid": self._s(info.getIccId()),
                "state": state, "state_text": SIM_STATES.get(state, "unknown"),
                "ready": state == 5})
        out.sort(key=lambda s: s["slot"])
        return out

    def resolve_sim(self, pref):
        """-> (sim dict or None, message).  None + 'system default' means use the default."""
        if not pref or pref.get("mode") != "slot":
            return None, "system default"
        for s in self.list_sims():
            if s["slot"] == pref["slot"]:
                if pref.get("label") and s["carrier"] and pref["label"] != s["carrier"]:
                    return None, ("The SIM in slot %d is now '%s' but you selected '%s'. "
                                  "Re-select the SIM." % (pref["slot"] + 1, s["carrier"], pref["label"]))
                return s, "ok"
        return None, "No active SIM in slot %d. Re-select the SIM." % (pref["slot"] + 1)

    def sim_ready(self, pref):
        sim, msg = self.resolve_sim(pref)
        if pref and pref.get("mode") == "slot":
            if sim is None:
                return False, msg
            if not sim["ready"]:
                return False, "SIM %d (%s) is %s" % (sim["slot"] + 1, sim["carrier"], sim["state_text"])
        return True, "ready"

    # ---------- calls ----------
    def _find_handle(self, sim):
        telecom = self._cast("android.telecom.TelecomManager", self.ctx.getSystemService("telecom"))
        hs = telecom.getCallCapablePhoneAccounts()
        cands = []
        for i in range(hs.size()):
            h = self._cast("android.telecom.PhoneAccountHandle", hs.get(i))
            cands.append((h, h.getId() or ""))
        iccid, sid = sim.get("iccid", ""), str(sim["sub_id"])
        for h, hid in cands:                       # 1) exact id match
            if hid == sid or (iccid and hid and (iccid.startswith(hid) or hid.startswith(iccid))):
                return h
        hits = []                                  # 2) unique label match
        for h, hid in cands:
            acct = telecom.getPhoneAccount(h)
            label = self._s(acct.getLabel()).lower() if acct is not None else ""
            m = re.search(r"sim\s*(\d)", label)
            if (m and int(m.group(1)) == sim["slot"] + 1) or \
               (label and sim["carrier"] and label == sim["carrier"].lower()):
                hits.append(h)
        return hits[0] if len(hits) == 1 else None

    def place_call(self, number, pref):
        fail = lambda e: {"ok": False, "error": e, "start_ms": 0, "account_id": ""}
        if not self._has(PERM_CALL):
            return fail("CALL_PHONE permission not granted")
        try:
            self.CallMonitor.start(self.ctx)
            handle, account_id = None, ""
            sim, msg = self.resolve_sim(pref)
            if pref and pref.get("mode") == "slot":
                if sim is None:
                    return fail(msg)
                ok, why = self.sim_ready(pref)
                if not ok:
                    return fail(why)
                handle = self._find_handle(sim)
                if handle is None:
                    return fail("Android would not let this app map SIM %d to a calling account "
                                "on this phone. Choose 'System default' for calls." % (sim["slot"] + 1))
                account_id = handle.getId() or ""
            Uri = self._auto("android.net.Uri")
            Bundle = self._auto("android.os.Bundle")
            telecom = self._cast("android.telecom.TelecomManager", self.ctx.getSystemService("telecom"))
            extras = Bundle()
            if handle is not None:
                extras.putParcelable("android.telecom.extra.PHONE_ACCOUNT_HANDLE", handle)
            self.CallMonitor.clearHistory()
            start_ms = int(time.time() * 1000)
            telecom.placeCall(Uri.fromParts("tel", number, None), extras)
            return {"ok": True, "error": "", "start_ms": start_ms, "account_id": account_id}
        except Exception as exc:
            return fail("placeCall failed: %s" % exc)

    def end_call(self):
        try:
            telecom = self._cast("android.telecom.TelecomManager", self.ctx.getSystemService("telecom"))
            return bool(telecom.endCall())
        except Exception:
            return False

    def _wait_idle(self, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.CallMonitor.getState() == 0:
                return True
            time.sleep(0.25)
        return self.CallMonitor.getState() == 0

    def monitor_call(self, max_seconds, stop_event):
        """Watch the LOCAL call state. Ends the call at max_seconds."""
        t0 = time.time()
        while time.time() - t0 < 12 and self.CallMonitor.getState() != 2:
            time.sleep(0.25)
        if self.CallMonitor.getState() != 2:
            return {"started": False, "ended_by": "never_started", "end_ok": True,
                    "history": self.CallMonitor.history()}
        t_start, ended_by = time.time(), "app_limit"
        while True:
            if self.CallMonitor.getState() == 0:
                ended_by = "remote_or_network"
                break
            if stop_event.is_set():
                ended_by = "stopped"
                break
            if time.time() - t_start >= max_seconds:
                break
            time.sleep(0.25)
        end_ok = True
        if ended_by in ("app_limit", "stopped"):
            self.end_call()
            end_ok = self._wait_idle(10)
        return {"started": True, "ended_by": ended_by, "end_ok": end_ok,
                "history": self.CallMonitor.history()}

    def lookup_call_outcome(self, number, since_ms, wait_s=12):
        """Read the phone's call log: was there an outgoing call and did it connect?"""
        if not self._has(PERM_LOG):
            return {"found": False, "duration": 0, "account_id": ""}
        from .phone_utils import last10
        want = last10(number)
        CallsCls = self._auto("android.provider.CallLog$Calls")
        resolver = self.ctx.getContentResolver()
        t0 = time.time()
        while time.time() - t0 <= wait_s:
            cur = resolver.query(CallsCls.CONTENT_URI,
                                 ["number", "type", "date", "duration", "phone_account_id"],
                                 "date >= ?", [str(since_ms - 3000)], "date DESC")
            try:
                if cur is not None:
                    while cur.moveToNext():
                        if cur.getInt(1) == 2 and last10(cur.getString(0) or "") == want:
                            return {"found": True, "duration": cur.getLong(3),
                                    "account_id": cur.getString(4) or ""}
            finally:
                if cur is not None:
                    cur.close()
            time.sleep(2)
        return {"found": False, "duration": 0, "account_id": ""}

    # ---------- SMS ----------
    def _pi(self, action, tag, parts):
        Intent = self._auto("android.content.Intent")
        PendingIntent = self._auto("android.app.PendingIntent")
        it = Intent(action)
        it.setPackage(self.ctx.getPackageName())
        it.putExtra("tag", tag)
        it.putExtra("parts", parts)
        self._req += 1
        return PendingIntent.getBroadcast(self.ctx, self._req, it, PendingIntent.FLAG_UPDATE_CURRENT)

    def send_sms(self, number, message, pref, tag):
        if not self._has(PERM_SMS):
            return {"ok": False, "parts": 1, "error": "SEND_SMS permission not granted"}
        try:
            SmsManager = self._auto("android.telephony.SmsManager")
            sim, msg = self.resolve_sim(pref)
            if pref and pref.get("mode") == "slot":
                if sim is None:
                    return {"ok": False, "parts": 1, "error": msg}
                mgr = SmsManager.getSmsManagerForSubscriptionId(sim["sub_id"])
            else:
                mgr = SmsManager.getDefault()
            parts = mgr.divideMessage(message)
            n = parts.size()
            ArrayList = self._auto("java.util.ArrayList")
            sent_l, deliv_l = ArrayList(), ArrayList()
            for _ in range(n):
                sent_l.add(self._pi(self.SmsRx.ACTION_SENT, tag, n))
                deliv_l.add(self._pi(self.SmsRx.ACTION_DELIVERED, tag, n))
            mgr.sendMultipartTextMessage(number, None, parts, sent_l, deliv_l)
            return {"ok": True, "parts": n, "error": ""}
        except Exception as exc:
            return {"ok": False, "parts": 1, "error": "send failed: %s" % exc}

    def sms_status(self, kind, tag):
        return self.SmsRx.status(kind, tag)

    # ---------- misc ----------
    def read_inbox(self, since_ms=0):
        if not self._has(PERM_READ_SMS):
            raise RuntimeError("READ_SMS permission is not granted")
        Uri = self._auto("android.net.Uri")
        cur = self.ctx.getContentResolver().query(
            Uri.parse("content://sms/inbox"), ["address", "body", "date"],
            "date >= ?", [str(since_ms)], "date DESC")
        out = []
        try:
            while cur is not None and cur.moveToNext():
                out.append((cur.getString(0) or "", cur.getString(1) or "", cur.getLong(2)))
        finally:
            if cur is not None:
                cur.close()
        return out

    def keep_screen_on(self):
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _go():
            self.ctx.getWindow().addFlags(128)   # FLAG_KEEP_SCREEN_ON
        _go()

    def storage_dir(self):
        import os
        d = "/storage/emulated/0/Download/CarPromoCaller"
        os.makedirs(d, exist_ok=True)
        return d
