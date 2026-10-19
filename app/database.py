"""Local SQLite storage. Everything stays on the phone.

Design rules:
  * contacts      = the imported spreadsheet data (never edited afterwards)
  * consent       = consent status, stored SEPARATELY
  * suppression   = opt-out list; anything in here is never contacted again
  * campaign_contacts keeps a frozen copy of (name, phone, message) so a
    name can never drift away from its number.
"""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_batches(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT, imported_at TEXT, header_mode TEXT,
    header_skipped INTEGER, total_rows INTEGER);

CREATE TABLE IF NOT EXISTS contacts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    source_row INTEGER NOT NULL,
    name TEXT NOT NULL,
    raw_number TEXT NOT NULL,
    phone_e164 TEXT,
    status TEXT NOT NULL CHECK(status IN ('valid','invalid','duplicate')),
    issue TEXT, note TEXT,
    vehicle_interest TEXT DEFAULT '', promotion TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS consent(
    phone_e164 TEXT PRIMARY KEY,
    consent_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK(consent_status IN ('unknown','granted','denied')),
    consent_note TEXT DEFAULT '', updated_at TEXT);

CREATE TABLE IF NOT EXISTS suppression(
    phone_e164 TEXT PRIMARY KEY, reason TEXT, added_at TEXT);

CREATE VIEW IF NOT EXISTS v_eligible_contacts AS
SELECT c.* FROM contacts c
JOIN consent k ON k.phone_e164 = c.phone_e164
WHERE c.status = 'valid' AND k.consent_status = 'granted'
  AND c.phone_e164 NOT IN (SELECT phone_e164 FROM suppression);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS campaigns(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, created_at TEXT, started_at TEXT, finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    pause_reason TEXT DEFAULT '',
    template TEXT, vehicle TEXT, promo TEXT,
    call_sim TEXT, sms_sim TEXT, settings TEXT);

CREATE TABLE IF NOT EXISTS campaign_contacts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    contact_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    message TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    call_outcome TEXT DEFAULT '',
    sms_state TEXT DEFAULT 'none',
    note TEXT DEFAULT '',
    updated_at TEXT,
    UNIQUE(campaign_id, contact_id));

CREATE TABLE IF NOT EXISTS call_attempts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cc_id INTEGER, campaign_id INTEGER, phone TEXT,
    started_at TEXT, ended_at TEXT, outcome TEXT,
    duration_s INTEGER, sim TEXT, account_id TEXT, detail TEXT);

CREATE TABLE IF NOT EXISTS sms_attempts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cc_id INTEGER, campaign_id INTEGER, phone TEXT, message TEXT, sim TEXT,
    created_at TEXT, created_ts INTEGER,
    sent_state TEXT, delivery_state TEXT DEFAULT 'none', error TEXT DEFAULT '',
    parts INTEGER DEFAULT 1, tag TEXT UNIQUE);

CREATE TABLE IF NOT EXISTS logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, campaign_id INTEGER, phone TEXT, event TEXT, detail TEXT);
"""


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---- tiny helpers (thread-safe) ----
    def run(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def rows(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    # ---- settings ----
    def get_setting(self, key, default=None):
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    def set_setting(self, key, value):
        self.run("INSERT INTO settings(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_json(self, key, default=None):
        raw = self.get_setting(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def set_json(self, key, obj):
        self.set_setting(key, json.dumps(obj))

    # ---- import (Stage 1) ----
    def commit_import(self, filename, header_mode, preview):
        s = preview["summary"]
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO import_batches(filename, imported_at, header_mode, "
                "header_skipped, total_rows) VALUES (?,?,?,?,?)",
                (filename, now_text(), header_mode, int(s["header_skipped"]), s["data_rows"]))
            batch_id = cur.lastrowid
            stored = {"valid": 0, "invalid": 0, "duplicate": 0}
            for r in preview["records"]:
                status, issue = r["status"], r["issue"]
                if status == "valid":
                    hit = cur.execute(
                        "SELECT id FROM contacts WHERE phone_e164=? AND status='valid'",
                        (r["phone"],)).fetchone()
                    if hit:
                        status, issue = "duplicate", "already in your contact list"
                cur.execute(
                    "INSERT INTO contacts(batch_id, source_row, name, raw_number, "
                    "phone_e164, status, issue, note) VALUES (?,?,?,?,?,?,?,?)",
                    (batch_id, r["source_row"], r["name"], r["raw_number"],
                     r["phone"] or None, status, issue, r["note"]))
                stored[status] += 1
                if status == "valid":   # consent starts 'unknown' = NOT eligible
                    cur.execute("INSERT OR IGNORE INTO consent(phone_e164, updated_at) "
                                "VALUES (?,?)", (r["phone"], now_text()))
            self.conn.commit()
        return stored

    def counts(self):
        q = lambda sql: self.one(sql)[0]
        return {
            "total": q("SELECT COUNT(*) FROM contacts"),
            "valid": q("SELECT COUNT(*) FROM contacts WHERE status='valid'"),
            "invalid": q("SELECT COUNT(*) FROM contacts WHERE status='invalid'"),
            "duplicate": q("SELECT COUNT(*) FROM contacts WHERE status='duplicate'"),
            "eligible": q("SELECT COUNT(*) FROM v_eligible_contacts"),
            "granted": q("SELECT COUNT(*) FROM consent WHERE consent_status='granted'"),
            "optouts": q("SELECT COUNT(*) FROM suppression"),
        }

    def list_contacts(self, status=None, search="", limit=300):
        sql, args = ("SELECT c.*, COALESCE(k.consent_status,'-') AS consent, "
                     "CASE WHEN s.phone_e164 IS NULL THEN 0 ELSE 1 END AS optout "
                     "FROM contacts c LEFT JOIN consent k ON k.phone_e164=c.phone_e164 "
                     "LEFT JOIN suppression s ON s.phone_e164=c.phone_e164 WHERE 1=1"), []
        if status:
            sql += " AND c.status=?"
            args.append(status)
        if search:
            sql += " AND (c.name LIKE ? OR c.raw_number LIKE ? OR c.phone_e164 LIKE ?)"
            args += ["%" + search + "%"] * 3
        sql += " ORDER BY c.id LIMIT ?"      # stable order = import order
        args.append(limit)
        return self.rows(sql, args)

    # ---- consent / opt-out ----
    def set_consent_all_valid(self, note):
        self.run("UPDATE consent SET consent_status='granted', consent_note=?, updated_at=? "
                 "WHERE phone_e164 IN (SELECT phone_e164 FROM contacts WHERE status='valid')",
                 (note, now_text()))

    def revoke_all_consent(self):
        self.run("UPDATE consent SET consent_status='unknown', consent_note='revoked', updated_at=?",
                 (now_text(),))

    def set_consent_for(self, phone, status, note=""):
        self.run("INSERT INTO consent(phone_e164, consent_status, consent_note, updated_at) "
                 "VALUES(?,?,?,?) ON CONFLICT(phone_e164) DO UPDATE SET "
                 "consent_status=excluded.consent_status, consent_note=excluded.consent_note, "
                 "updated_at=excluded.updated_at", (phone, status, note, now_text()))

    def add_suppression(self, phone, reason):
        self.run("INSERT OR IGNORE INTO suppression(phone_e164, reason, added_at) VALUES(?,?,?)",
                 (phone, reason, now_text()))
        self.set_consent_for(phone, "denied", "opted out: " + reason)

    def list_suppression(self):
        return self.rows("SELECT * FROM suppression ORDER BY added_at DESC")

    def is_eligible(self, phone):
        r = self.one(
            "SELECT 1 FROM consent k WHERE k.phone_e164=? AND k.consent_status='granted' "
            "AND k.phone_e164 NOT IN (SELECT phone_e164 FROM suppression) "
            "AND EXISTS (SELECT 1 FROM contacts c WHERE c.phone_e164=? AND c.status='valid')",
            (phone, phone))
        return r is not None

    def eligible_contacts(self):
        return self.rows("SELECT * FROM v_eligible_contacts ORDER BY id")

    def match_contacts_by_last10(self, last10_digits):
        return self.rows("SELECT DISTINCT phone_e164 FROM contacts WHERE status='valid' "
                         "AND phone_e164 LIKE ?", ("%" + last10_digits,))

    # ---- campaigns ----
    def create_campaign(self, name, template, vehicle, promo, call_sim, sms_sim,
                        settings, recipients):
        """recipients = list of (contact_id, name, phone, message) in order."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO campaigns(name, created_at, status, template, vehicle, promo, "
                "call_sim, sms_sim, settings) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, now_text(), "ready", template, vehicle, promo,
                 json.dumps(call_sim), json.dumps(sms_sim), json.dumps(settings)))
            cid = cur.lastrowid
            for pos, (contact_id, nm, phone, msg) in enumerate(recipients, start=1):
                cur.execute(
                    "INSERT INTO campaign_contacts(campaign_id, contact_id, position, name, "
                    "phone_e164, message, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (cid, contact_id, pos, nm, phone, msg, now_text()))
            self.conn.commit()
        return cid

    def get_campaign(self, cid):
        return self.one("SELECT * FROM campaigns WHERE id=?", (cid,))

    def latest_open_campaign(self):
        return self.one("SELECT * FROM campaigns WHERE status IN ('ready','running','paused') "
                        "ORDER BY id DESC LIMIT 1")

    def set_campaign(self, cid, **fields):
        cols = ", ".join(k + "=?" for k in fields)
        self.run("UPDATE campaigns SET " + cols + " WHERE id=?", list(fields.values()) + [cid])

    def next_pending(self, cid):
        return self.one("SELECT * FROM campaign_contacts WHERE campaign_id=? AND state='pending' "
                        "ORDER BY position LIMIT 1", (cid,))

    def set_cc(self, rid, **fields):
        fields["updated_at"] = now_text()
        cols = ", ".join(k + "=?" for k in fields)
        self.run("UPDATE campaign_contacts SET " + cols + " WHERE id=?",
                 list(fields.values()) + [rid])

    def campaign_stats(self, cid):
        q = lambda sql, *a: self.one(sql, a)[0]
        return {
            "total": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=?", cid),
            "pending": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND state='pending'", cid),
            "done": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND state='done'", cid),
            "skipped": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND state='skipped'", cid),
            "interrupted": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND state='interrupted'", cid),
            "answered": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND call_outcome='answered'", cid),
            "call_failed": q("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND call_outcome='call_failed'", cid),
            "sms_sent": q("SELECT COUNT(*) FROM sms_attempts WHERE campaign_id=? AND sent_state='sent'", cid),
            "sms_failed": q("SELECT COUNT(*) FROM sms_attempts WHERE campaign_id=? AND sent_state LIKE 'failed%'", cid),
            "sms_unknown": q("SELECT COUNT(*) FROM sms_attempts WHERE campaign_id=? AND sent_state IN ('unknown','sending')", cid),
            "sms_delivered": q("SELECT COUNT(*) FROM sms_attempts WHERE campaign_id=? AND delivery_state='delivered'", cid),
        }

    def recover_after_restart(self):
        """Anything caught mid-action when the app closed is NEVER retried
        automatically (that could double-send); it is flagged for review."""
        with self.lock:
            self.conn.execute("UPDATE campaign_contacts SET state='interrupted', "
                              "note='app closed during this contact - review before retrying' "
                              "WHERE state IN ('calling','sms_sending')")
            self.conn.execute("UPDATE sms_attempts SET sent_state='unknown' WHERE sent_state='sending'")
            self.conn.execute("UPDATE campaigns SET status='paused', "
                              "pause_reason='App was closed - press Resume to continue' "
                              "WHERE status='running'")
            self.conn.commit()

    # ---- attempts / logs ----
    def log(self, campaign_id, phone, event, detail=""):
        self.run("INSERT INTO logs(ts, campaign_id, phone, event, detail) VALUES (?,?,?,?,?)",
                 (now_text(), campaign_id, phone, event, detail))

    def add_call_attempt(self, cc_id, campaign_id, phone, started_at, ended_at, outcome,
                         duration_s, sim, account_id, detail):
        self.run("INSERT INTO call_attempts(cc_id, campaign_id, phone, started_at, ended_at, "
                 "outcome, duration_s, sim, account_id, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (cc_id, campaign_id, phone, started_at, ended_at, outcome, duration_s,
                  sim, account_id, detail))

    def new_sms_attempt(self, cc_id, campaign_id, phone, message, sim):
        """Written BEFORE sending, so a crash can never lead to a second send."""
        ts = int(time.time())
        tag = "c%d-r%d-%d" % (campaign_id, cc_id, ts)
        self.run("INSERT INTO sms_attempts(cc_id, campaign_id, phone, message, sim, created_at, "
                 "created_ts, sent_state, tag) VALUES (?,?,?,?,?,?,?,?,?)",
                 (cc_id, campaign_id, phone, message, sim, now_text(), ts, "sending", tag))
        return tag

    def update_sms(self, tag, **fields):
        cols = ", ".join(k + "=?" for k in fields)
        self.run("UPDATE sms_attempts SET " + cols + " WHERE tag=?", list(fields.values()) + [tag])

    def sms_attempted_in_campaign(self, campaign_id, phone):
        return self.one("SELECT 1 FROM sms_attempts WHERE campaign_id=? AND phone=?",
                        (campaign_id, phone)) is not None

    def sms_recent_to(self, phone, hours):
        cutoff = int(time.time() - hours * 3600)
        return self.one("SELECT 1 FROM sms_attempts WHERE phone=? AND created_ts>=? "
                        "AND sent_state NOT LIKE 'failed%'", (phone, cutoff)) is not None

    def sms_count_since(self, seconds):
        cutoff = int(time.time() - seconds)
        return self.one("SELECT COUNT(*) FROM sms_attempts WHERE created_ts>=?", (cutoff,))[0]

    def open_delivery_attempts(self, campaign_id=None):
        sql = ("SELECT * FROM sms_attempts WHERE sent_state='sent' "
               "AND delivery_state IN ('none','pending')")
        args = []
        if campaign_id:
            sql += " AND campaign_id=?"
            args.append(campaign_id)
        return self.rows(sql, args)
