"""Campaign creation and the background runner (call -> optional SMS).

Safety rules built in:
  * Only contacts with consent 'granted' and NOT in the opt-out list.
    Eligibility is checked again right before every call and every SMS.
  * The SMS attempt row is written BEFORE sending. After a crash/restart a
    contact caught mid-way is marked 'interrupted' and is never auto-retried.
  * One SMS per phone per campaign, plus a no-repeat window across campaigns.
  * If the chosen SIM is unusable the campaign PAUSES. It never switches SIM.
"""
import json
import threading
import time

from .database import now_text
from .templates_engine import find_unknown, render

POLICIES = {
    "answered_only": "Call, then SMS only if the call was ANSWERED (checked in call log)",
    "sms_only": "SMS only (no calls)",
    "call_only": "Call only (no SMS)",
    "unverified_call_then_sms": "Call, then SMS even if answer/ringing is NOT confirmed (UNVERIFIED)",
}

DEFAULT_SETTINGS = {
    "policy": "answered_only",
    "call_seconds": 15,
    "delay_seconds": 60,
    "max_contacts": 20,          # per run; pauses when reached
    "max_sms_per_hour": 20,
    "no_repeat_hours": 24,
    "test_mode": True,
    "test_count": 5,
    "dry_run": True,
    "delivery_wait_seconds": 20,   # how long to wait at the end for delivery reports
}


def policy_uses_call(policy):
    return policy != "sms_only"


def policy_uses_sms(policy):
    return policy != "call_only"


def plan_campaign(db, template, vehicle, promo, settings):
    """Pick recipients and render their messages (used for preview AND creation).
    Returns (recipients, problems). recipients = [(contact_id, name, phone, message)]"""
    problems = []
    unknown = find_unknown(template)
    if unknown:
        problems.append("Unknown placeholder(s) in template: " + ", ".join("{%s}" % u for u in unknown))
    if not template.strip():
        problems.append("The message template is empty.")
    people = db.eligible_contacts()
    if not people:
        problems.append("No eligible contacts. A contact needs consent = granted and must not be opted out.")
    if settings.get("test_mode"):
        people = people[: max(1, int(settings.get("test_count", 5)))]
    recipients = [(p["id"], p["name"], p["phone_e164"],
                   render(template, p["name"], p["vehicle_interest"] or vehicle,
                          p["promotion"] or promo)) for p in people]
    return recipients, problems


def create_campaign(db, name, template, vehicle, promo, call_sim, sms_sim, settings):
    recipients, problems = plan_campaign(db, template, vehicle, promo, settings)
    if problems:
        raise ValueError("; ".join(problems))
    cid = db.create_campaign(name, template, vehicle, promo, call_sim, sms_sim, settings, recipients)
    db.log(cid, "", "campaign_created",
           "%d recipients, policy=%s, dry_run=%s" % (len(recipients), settings["policy"], settings["dry_run"]))
    return cid


class CampaignRunner:
    def __init__(self, db, bridge, campaign_id):
        self.db, self.bridge, self.cid = db, bridge, campaign_id
        c = db.get_campaign(campaign_id)
        self.settings = dict(DEFAULT_SETTINGS, **json.loads(c["settings"] or "{}"))
        self.call_sim = json.loads(c["call_sim"] or "{}")
        self.sms_sim = json.loads(c["sms_sim"] or "{}")
        self.pause_ev, self.stop_ev = threading.Event(), threading.Event()
        self.thread = None
        self.reason = ""
        self.processed = 0
        self.current = "-"

    # ---- controls ----
    @property
    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.alive:
            return
        self.stop_ev.clear()
        self.pause_ev.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def pause(self, reason="Paused by you"):
        self.reason = reason
        self.pause_ev.set()

    def resume(self):
        self.db.recover_after_restart() if not self.alive else None
        self.pause_ev.clear()
        if not self.alive:
            self.start()
        else:
            self.db.set_campaign(self.cid, status="running", pause_reason="")

    def stop(self):
        self.stop_ev.set()
        self.pause_ev.clear()

    # ---- internals ----
    def _wait(self, seconds):
        end = time.time() + seconds
        while time.time() < end and not self.stop_ev.is_set() and not self.pause_ev.is_set():
            time.sleep(0.2)

    def _auto_pause(self, reason):
        self.db.log(self.cid, "", "auto_pause", reason)
        self.pause(reason)

    def _run(self):
        db, s = self.db, self.settings
        db.set_campaign(self.cid, status="running", pause_reason="")
        if not db.get_campaign(self.cid)["started_at"]:
            db.set_campaign(self.cid, started_at=now_text())
        self.bridge.keep_screen_on()
        while not self.stop_ev.is_set():
            if self.pause_ev.is_set():
                db.set_campaign(self.cid, status="paused", pause_reason=self.reason)
                while self.pause_ev.is_set() and not self.stop_ev.is_set():
                    time.sleep(0.25)
                if self.stop_ev.is_set():
                    break
                db.set_campaign(self.cid, status="running", pause_reason="")
                self.processed = 0
                continue
            row = db.next_pending(self.cid)
            if row is None:
                self._refresh_delivery(wait=True)
                db.set_campaign(self.cid, status="completed", finished_at=now_text())
                self.current = "Finished"
                return
            if self.processed >= int(s["max_contacts"]):
                self._auto_pause("Run limit of %s contacts reached. Press Resume for another batch."
                                 % s["max_contacts"])
                continue
            try:
                consumed = self._process(row)
            except Exception as exc:    # never let one contact kill the campaign silently
                db.set_cc(row["id"], state="interrupted", note="error: %s" % exc)
                db.log(self.cid, row["phone_e164"], "error", str(exc))
                self._auto_pause("Unexpected error: %s" % exc)
                consumed = False
            if consumed:
                self.processed += 1
                self._refresh_delivery()
                if db.next_pending(self.cid) is not None:
                    self._wait(float(s["delay_seconds"]))
        self._refresh_delivery()
        db.set_campaign(self.cid, status="stopped", finished_at=now_text())
        self.current = "Stopped"

    def _skip(self, row, reason):
        self.db.set_cc(row["id"], state="skipped", note=reason)
        self.db.log(self.cid, row["phone_e164"], "skipped", reason)
        return True

    def _process(self, row):
        db, s, b = self.db, self.settings, self.bridge
        rid, phone, name = row["id"], row["phone_e164"], row["name"]
        self.current = "%s  (%s)" % (name, phone)
        policy = s["policy"]

        if not db.is_eligible(phone):
            return self._skip(row, "not eligible now (no consent or opted out)")

        # ---- SIM readiness (never switch SIMs) ----
        if policy_uses_call(policy):
            ok, why = b.sim_ready(self.call_sim)
            if not ok:
                self._auto_pause("Call SIM problem: " + why)
                return False
        if policy_uses_sms(policy):
            ok, why = b.sim_ready(self.sms_sim)
            if not ok:
                self._auto_pause("SMS SIM problem: " + why)
                return False

        outcome = ""
        # ---- CALL ----
        if policy_uses_call(policy):
            db.set_cc(rid, state="calling")
            started_txt = now_text()
            res = b.place_call(phone, self.call_sim)
            db.log(self.cid, phone, "call_requested", res["error"] or "ok")
            if not res["ok"]:
                outcome = "call_failed"
                db.add_call_attempt(rid, self.cid, phone, started_txt, now_text(), outcome, 0,
                                    json.dumps(self.call_sim), "", res["error"])
            else:
                mon = b.monitor_call(int(s["call_seconds"]), self.stop_ev)
                if mon["ended_by"] == "stopped":
                    db.set_cc(rid, state="interrupted", note="stopped during call")
                    return True
                if not mon["end_ok"]:
                    db.set_cc(rid, state="interrupted", note="could not end the call automatically")
                    self._auto_pause("The app could not end the call. End it by hand, then press Resume.")
                    return True
                if not mon["started"]:
                    outcome, lk = "call_failed", {"found": False, "duration": 0, "account_id": ""}
                else:
                    lk = b.lookup_call_outcome(phone, res["start_ms"])
                    if lk["found"] and lk["duration"] > 0:
                        outcome = "answered"
                    elif lk["found"] and mon["ended_by"] == "app_limit":
                        outcome = "unanswered_ringing_unconfirmed"
                    elif lk["found"]:
                        outcome = "not_connected"
                    else:
                        outcome = "unknown"
                db.add_call_attempt(rid, self.cid, phone, started_txt, now_text(), outcome,
                                    int(lk["duration"]), json.dumps(self.call_sim),
                                    lk["account_id"], "ended_by=%s; states=%s" % (mon["ended_by"], mon["history"]))
                # SIM routing check: call log must report the account we asked for
                if res["account_id"] and lk["account_id"] and res["account_id"] != lk["account_id"]:
                    db.set_cc(rid, state="interrupted", call_outcome=outcome,
                              note="SIM ROUTING MISMATCH: call used another SIM")
                    db.log(self.cid, phone, "sim_mismatch", "asked %s, call log says %s"
                           % (res["account_id"], lk["account_id"]))
                    self._auto_pause("The call went out on a different SIM than selected. "
                                     "Campaign paused. Check the SIM settings.")
                    return True
            db.set_cc(rid, call_outcome=outcome)
            db.log(self.cid, phone, "call_outcome", outcome)

        # ---- SMS decision ----
        if policy == "sms_only":
            want = True
        elif policy == "call_only":
            db.set_cc(rid, state="done", sms_state="not_requested")
            return True
        elif policy == "answered_only":
            want = outcome == "answered"
        else:
            want = outcome in ("answered", "unanswered_ringing_unconfirmed", "unknown")
        if not want:
            db.set_cc(rid, state="done", sms_state="skipped",
                      note="SMS skipped: call outcome = %s" % outcome)
            return True

        # ---- SMS ----
        if not db.is_eligible(phone):
            return self._skip(row, "opted out before SMS")
        if db.sms_attempted_in_campaign(self.cid, phone):
            db.set_cc(rid, state="done", sms_state="skipped", note="duplicate protection: already attempted")
            return True
        if db.sms_recent_to(phone, float(s["no_repeat_hours"])):
            db.set_cc(rid, state="done", sms_state="skipped",
                      note="duplicate protection: messaged within %s h" % s["no_repeat_hours"])
            return True
        if db.sms_count_since(3600) >= int(s["max_sms_per_hour"]):
            self._auto_pause("Hourly SMS limit (%s) reached. Resume later." % s["max_sms_per_hour"])
            db.set_cc(rid, state="pending")
            return False
        if not row["message"].strip() or not phone:
            return self._skip(row, "empty message or number")

        tag = db.new_sms_attempt(rid, self.cid, phone, row["message"], json.dumps(self.sms_sim))
        db.set_cc(rid, state="sms_sending", sms_state="sending")
        res = b.send_sms(phone, row["message"], self.sms_sim, tag)
        db.log(self.cid, phone, "sms_requested", res["error"] or "ok")
        if not res["ok"]:
            db.update_sms(tag, sent_state="failed", error=res["error"])
            db.set_cc(rid, state="done", sms_state="failed", note=res["error"])
            return True
        db.update_sms(tag, parts=res["parts"])
        end, state = time.time() + 30, "pending"
        while time.time() < end and state == "pending" and not self.stop_ev.is_set():
            state = b.sms_status("sent", tag)
            if state == "pending":
                time.sleep(0.5)
        if state == "pending":
            state = "unknown"        # never retried automatically
        db.update_sms(tag, sent_state=state, delivery_state="pending" if state == "sent" else "none")
        db.set_cc(rid, state="done", sms_state=state)
        db.log(self.cid, phone, "sms_result", state)
        return True

    def _refresh_delivery(self, wait=False):
        """Pick up delivery reports (only exist if the carrier sends them)."""
        deadline = time.time() + (float(self.settings.get('delivery_wait_seconds', 20)) if wait else 0)
        while True:
            open_rows = self.db.open_delivery_attempts(self.cid)
            for r in open_rows:
                st = self.bridge.sms_status("delivery", r["tag"])
                if st != "pending":
                    self.db.update_sms(r["tag"], delivery_state=st)
            if not wait or time.time() >= deadline or not self.db.open_delivery_attempts(self.cid):
                break
            time.sleep(1)
