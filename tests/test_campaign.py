import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.database import Database
from app.importer import build_preview
from app.campaign import (CampaignRunner, DEFAULT_SETTINGS, create_campaign, plan_campaign)
from app.bridge_dry import DryRunBridge
from app.templates_engine import render, find_unknown, sms_info, DEFAULT_TEMPLATE
from app.consent import is_stop_message, process_inbox, opt_out_number

SIM0 = {"mode": "slot", "slot": 0, "label": "TestNet A"}


def make_db(rows=(("Juan Dela Cruz", "09171234567"), ("Maria Clara", "09181234567"),
                  ("Pedro Penduko", "09191234567"))):
    db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))
    raw = [(i, n, p) for i, (n, p) in enumerate(rows, start=1)]
    db.commit_import("x.csv", "no", build_preview(raw, "no"))
    db.set_consent_all_valid("test")
    return db


def settings(**kw):
    s = dict(DEFAULT_SETTINGS, delay_seconds=0, call_seconds=1, test_mode=False,
             dry_run=True, max_contacts=100, delivery_wait_seconds=0)
    s.update(kw)
    return s


def run(db, bridge, **kw):
    cid = create_campaign(db, "t", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings(**kw))
    r = CampaignRunner(db, bridge, cid)
    r.start(); r.thread.join(10)
    return cid, r


class TemplateTests(unittest.TestCase):
    def test_example_from_spec(self):
        t = "Hi {name}! We have exciting Toyota and BYD promotions available. Reply STOP to opt out."
        self.assertEqual(render(t, "Juan Dela Cruz"),
                         "Hi Juan Dela Cruz! We have exciting Toyota and BYD promotions available. Reply STOP to opt out.")

    def test_opt_out_added_once(self):
        self.assertTrue(render(DEFAULT_TEMPLATE, "Ana").endswith("Reply STOP to opt out."))
        self.assertEqual(render("Hi {name} reply STOP", "Ana").count("STOP"), 1)

    def test_unknown_and_empty(self):
        self.assertEqual(find_unknown("Hi {nmae} {name}"), ["nmae"])
        self.assertEqual(render("Hi {name} {vehicle} now", "Ana"), "Hi Ana now Reply STOP to opt out.")

    def test_parts(self):
        self.assertEqual(sms_info("a" * 161)[1], 2)


class ConsentTests(unittest.TestCase):
    def test_stop_detection_and_inbox(self):
        self.assertTrue(is_stop_message("STOP"))
        self.assertTrue(is_stop_message(" stop please"))
        self.assertFalse(is_stop_message("Please don't stop calling, interested!"))
        db = make_db()
        added = process_inbox(db, [("+639171234567", "STOP", 0), ("09181234567", "hello", 0)])
        self.assertEqual(added, ["+639171234567"])
        self.assertEqual(db.counts()["eligible"], 2)

    def test_manual_optout(self):
        db = make_db()
        self.assertTrue(opt_out_number(db, "0918 123 4567", "asked by phone")[0])
        self.assertFalse(db.is_eligible("+639181234567"))


class CampaignTests(unittest.TestCase):
    def test_no_consent_no_campaign(self):
        db = make_db(); db.revoke_all_consent()
        _, problems = plan_campaign(db, DEFAULT_TEMPLATE, "", "", settings())
        self.assertTrue(problems)

    def test_answered_only(self):
        db = make_db(); b = DryRunBridge(call_result="answered")
        cid, _ = run(db, b)
        st = db.campaign_stats(cid)
        self.assertEqual((st["done"], st["sms_sent"], st["answered"]), (3, 3, 3))
        self.assertEqual(len(b.sent), 3)
        self.assertEqual(b.sent[0][1].split("!")[0], "Hi Juan Dela Cruz")   # name/number pairing
        self.assertEqual(b.sent[0][0], "+639171234567")

    def test_unanswered_skips_sms(self):
        db = make_db(); b = DryRunBridge(call_result="unanswered")
        cid, _ = run(db, b)
        st = db.campaign_stats(cid)
        self.assertEqual((st["sms_sent"], len(b.sent)), (0, 0))
        self.assertEqual(db.one("SELECT call_outcome FROM campaign_contacts").
                         __getitem__(0), "unanswered_ringing_unconfirmed")

    def test_failed_and_unknown_skip_under_answered_only(self):
        for res, found in (("failed", True), ("answered", False)):
            db = make_db(); b = DryRunBridge(call_result=res, call_log_found=found)
            run(db, b); self.assertEqual(len(b.sent), 0)

    def test_unverified_policy_sends_when_unconfirmed(self):
        db = make_db(); b = DryRunBridge(call_result="unanswered")
        run(db, b, policy="unverified_call_then_sms"); self.assertEqual(len(b.sent), 3)
        db = make_db(); b = DryRunBridge(call_result="failed")
        run(db, b, policy="unverified_call_then_sms"); self.assertEqual(len(b.sent), 0)

    def test_sms_only_and_call_only(self):
        db = make_db(); b = DryRunBridge()
        run(db, b, policy="sms_only"); self.assertEqual((len(b.sent), len(b.calls)), (3, 0))
        db = make_db(); b = DryRunBridge()
        run(db, b, policy="call_only"); self.assertEqual((len(b.sent), len(b.calls)), (0, 3))

    def test_optout_after_creation_is_respected(self):
        db = make_db(); b = DryRunBridge()
        cid = create_campaign(db, "t", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings())
        db.add_suppression("+639181234567", "replied STOP")
        r = CampaignRunner(db, b, cid); r.start(); r.thread.join(10)
        self.assertNotIn("+639181234567", [x[0] for x in b.sent])
        self.assertNotIn("+639181234567", b.calls)

    def test_no_duplicate_sms_on_resume_or_rerun(self):
        db = make_db(); b = DryRunBridge()
        cid, r = run(db, b)
        self.assertEqual(len(b.sent), 3)
        r2 = CampaignRunner(db, b, cid); r2.start(); r2.thread.join(5)   # finished: nothing more
        self.assertEqual(len(b.sent), 3)
        # second campaign within 24h must not re-message the same people
        cid2 = create_campaign(db, "t2", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings())
        r3 = CampaignRunner(db, b, cid2); r3.start(); r3.thread.join(10)
        self.assertEqual(len(b.sent), 3)

    def test_crash_mid_sms_is_never_retried(self):
        db = make_db(); b = DryRunBridge()
        cid = create_campaign(db, "t", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings(policy="sms_only"))
        row = db.next_pending(cid)
        db.new_sms_attempt(row["id"], cid, row["phone_e164"], row["message"], "{}")  # 'sending'
        db.set_cc(row["id"], state="sms_sending")
        db.recover_after_restart()      # simulates app restart
        r = CampaignRunner(db, b, cid); r.start(); r.thread.join(10)
        self.assertNotIn(row["phone_e164"], [x[0] for x in b.sent])
        self.assertEqual(db.one("SELECT state FROM campaign_contacts WHERE id=?", (row["id"],))[0], "interrupted")

    def test_sim_not_ready_pauses_never_switches(self):
        db = make_db(); b = DryRunBridge(); b.sims_ready = False
        cid = create_campaign(db, "t", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings())
        r = CampaignRunner(db, b, cid); r.start()
        import time; time.sleep(1.0)
        c = db.get_campaign(cid)
        self.assertEqual(c["status"], "paused"); self.assertIn("SIM", c["pause_reason"])
        self.assertEqual((len(b.calls), len(b.sent)), (0, 0))
        b.sims_ready = True; r.resume(); r.thread.join(10)
        self.assertEqual(len(b.sent), 3)

    def test_run_limit_pauses_then_resumes(self):
        db = make_db(); b = DryRunBridge()
        cid = create_campaign(db, "t", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings(max_contacts=2))
        r = CampaignRunner(db, b, cid); r.start()
        import time; time.sleep(1.0)
        self.assertEqual(db.get_campaign(cid)["status"], "paused"); self.assertEqual(len(b.sent), 2)
        r.resume(); r.thread.join(10); self.assertEqual(len(b.sent), 3)

    def test_test_mode_limits_group(self):
        db = make_db(); b = DryRunBridge()
        run(db, b, test_mode=True, test_count=2); self.assertEqual(len(b.sent), 2)

    def test_hourly_limit(self):
        db = make_db(); b = DryRunBridge()
        cid = create_campaign(db, "t", DEFAULT_TEMPLATE, "", "", SIM0, SIM0, settings(max_sms_per_hour=1))
        r = CampaignRunner(db, b, cid); r.start()
        import time; time.sleep(1.0)
        self.assertEqual(len(b.sent), 1); self.assertEqual(db.get_campaign(cid)["status"], "paused")
        r.stop(); r.thread.join(5)

    def test_export_keeps_pairs(self):
        from app.exporter import export_results
        import csv
        db = make_db(); b = DryRunBridge(); cid, _ = run(db, b)
        p = export_results(db, tempfile.mkdtemp(), cid)
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        self.assertEqual([r["name"] for r in rows], ["Juan Dela Cruz", "Maria Clara", "Pedro Penduko"])
        self.assertEqual(rows[0]["phone_e164"].lstrip("'"), "+639171234567")


if __name__ == "__main__":
    unittest.main()
