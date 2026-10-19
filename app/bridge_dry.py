"""Dry-run bridge: NOTHING is called and NOTHING is sent.

Used for the "Dry run" switch (safe rehearsal on the phone) and for PC tests.
If a real bridge is given as sim_source, real SIM info is shown so you can
check your SIM selection without spending credit.
"""
import time


class DryRunBridge:
    is_dry_run = True

    def __init__(self, sim_source=None, call_result="answered", call_log_found=True):
        self.sim_source = sim_source
        self.call_result = call_result      # answered | unanswered | not_connected | failed
        self.call_log_found = call_log_found
        self.sent = []                      # what WOULD have been sent
        self.calls = []                     # who WOULD have been called
        self.sims_ready = True
        self.fail_sms_numbers = set()

    # ---- SIMs ----
    def list_sims(self):
        if self.sim_source:
            return self.sim_source.list_sims()
        return [{"slot": 0, "sub_id": 1, "carrier": "TestNet A", "number": "", "iccid": "",
                 "state": 5, "state_text": "ready", "ready": True},
                {"slot": 1, "sub_id": 2, "carrier": "TestNet B", "number": "", "iccid": "",
                 "state": 5, "state_text": "ready", "ready": True}]

    def resolve_sim(self, pref):
        if self.sim_source:
            return self.sim_source.resolve_sim(pref)
        if not pref or pref.get("mode") != "slot":
            return None, "system default"
        for s in self.list_sims():
            if s["slot"] == pref["slot"]:
                return s, "ok"
        return None, "SIM in slot %d not found" % (pref["slot"] + 1)

    def sim_ready(self, pref):
        if self.sim_source:
            return self.sim_source.sim_ready(pref)
        if not self.sims_ready:
            return False, "SIM not ready (simulated)"
        sim, msg = self.resolve_sim(pref)
        if pref and pref.get("mode") == "slot" and sim is None:
            return False, msg
        return True, "ready"

    def permissions_missing(self, need_call, need_sms):
        return []

    # ---- calls ----
    def place_call(self, number, pref):
        self.calls.append(number)
        if self.call_result == "failed":
            return {"ok": False, "error": "simulated call failure", "start_ms": 0, "account_id": ""}
        return {"ok": True, "error": "", "start_ms": int(time.time() * 1000), "account_id": ""}

    def monitor_call(self, max_seconds, stop_event):
        if stop_event.is_set():
            return {"started": True, "ended_by": "stopped", "end_ok": True, "history": "dry-run"}
        started = self.call_result != "failed"
        ended_by = "remote_or_network" if self.call_result in ("answered", "not_connected") else "app_limit"
        return {"started": started, "ended_by": ended_by, "end_ok": True, "history": "dry-run"}

    def lookup_call_outcome(self, number, since_ms, wait_s=12):
        if not self.call_log_found:
            return {"found": False, "duration": 0, "account_id": ""}
        dur = 9 if self.call_result == "answered" else 0
        return {"found": True, "duration": dur, "account_id": ""}

    # ---- SMS ----
    def send_sms(self, number, message, pref, tag):
        if number in self.fail_sms_numbers:
            return {"ok": False, "parts": 1, "error": "simulated failure"}
        self.sent.append((number, message, tag))
        return {"ok": True, "parts": 1, "error": ""}

    def sms_status(self, kind, tag):
        return "sent" if kind == "sent" else "pending"

    # ---- misc ----
    def read_inbox(self, since_ms=0):
        return []

    def keep_screen_on(self):
        pass

    def storage_dir(self):
        import os
        d = os.path.join(os.getcwd(), "exports")
        os.makedirs(d, exist_ok=True)
        return d
