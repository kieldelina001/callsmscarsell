"""Local SQLite storage. Everything stays on the phone.

Design rule: the imported spreadsheet data (contacts) is kept SEPARATE from
consent (table consent) and opt-outs (table suppression).
"""
import sqlite3
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
"""


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def commit_import(self, filename, header_mode, preview):
        """Save a previewed import. Returns dict of counts actually stored."""
        s = preview["summary"]
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO import_batches(filename, imported_at, header_mode, "
            "header_skipped, total_rows) VALUES (?,?,?,?,?)",
            (filename, _now(), header_mode, int(s["header_skipped"]), s["data_rows"]))
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
            if status == "valid":   # consent starts as 'unknown' = NOT eligible
                cur.execute("INSERT OR IGNORE INTO consent(phone_e164, updated_at) "
                            "VALUES (?,?)", (r["phone"], _now()))
        self.conn.commit()
        return stored

    def counts(self):
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {
            "total": q("SELECT COUNT(*) FROM contacts"),
            "valid": q("SELECT COUNT(*) FROM contacts WHERE status='valid'"),
            "invalid": q("SELECT COUNT(*) FROM contacts WHERE status='invalid'"),
            "duplicate": q("SELECT COUNT(*) FROM contacts WHERE status='duplicate'"),
            "eligible": q("SELECT COUNT(*) FROM v_eligible_contacts"),
        }

    def list_contacts(self, status=None, search="", limit=300):
        sql, args = "SELECT * FROM contacts WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if search:
            sql += " AND (name LIKE ? OR raw_number LIKE ? OR phone_e164 LIKE ?)"
            args += ["%" + search + "%"] * 3
        sql += " ORDER BY id LIMIT ?"      # stable order = import order
        args.append(limit)
        return self.conn.execute(sql, args).fetchall()
