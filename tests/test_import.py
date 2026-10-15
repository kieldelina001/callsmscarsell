import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.phone_utils import normalize_ph_mobile as n
from app.importer import read_raw_rows, build_preview
from app.database import Database


def make_xlsx(path, rows):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(list(r))
    wb.save(path)


class PhoneTests(unittest.TestCase):
    def test_formats(self):
        for v in ["09171234567", "+63 917 123 4567", "639171234567",
                  "0917-123-4567", "00639171234567", 639171234567]:
            self.assertEqual(n(v)["e164"], "+639171234567", v)

    def test_lost_zero_recovered_with_note(self):
        for v in [9171234567, 9171234567.0, "9171234567"]:
            r = n(v); self.assertTrue(r["ok"]); self.assertTrue(r["note"])

    def test_bad(self):
        for v in [None, "", "abc", "0917123", "9.17E+09", "02-8123-4567", 12.5]:
            self.assertFalse(n(v)["ok"], v)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_xlsx_with_header_and_text_numbers(self):
        p = os.path.join(self.d, "a.xlsx")
        make_xlsx(p, [("Name", "Mobile Number"), ("Juan Dela Cruz", "09171234567"),
                      ("Maria Clara", 9181234567), ("Juan Again", "+639171234567"),
                      ("", "09191234567"), ("Bad Num", "12345"), (None, None)])
        pv = build_preview(read_raw_rows(p), "auto")
        s = pv["summary"]
        self.assertTrue(s["header_skipped"])
        self.assertEqual((s["valid"], s["duplicate"], s["invalid"]), (2, 1, 2))
        self.assertEqual(pv["records"][0]["name"], "Juan Dela Cruz")
        self.assertEqual(pv["records"][0]["phone"], "+639171234567")
        self.assertEqual(pv["records"][0]["source_row"], 2)

    def test_no_header_first_contact_not_skipped(self):
        p = os.path.join(self.d, "b.xlsx")
        make_xlsx(p, [("Juan Dela Cruz", "09171234567"), ("Ana", "09181234567")])
        pv = build_preview(read_raw_rows(p), "auto")
        self.assertFalse(pv["summary"]["header_skipped"])
        self.assertEqual(pv["summary"]["valid"], 2)
        pv = build_preview(read_raw_rows(p), "no")
        self.assertEqual(pv["summary"]["valid"], 2)

    def test_forced_header_yes_and_no(self):
        p = os.path.join(self.d, "c.csv")
        open(p, "w").write("Name,Number\nJuan,09171234567\n")
        self.assertEqual(build_preview(read_raw_rows(p), "yes")["summary"]["valid"], 1)
        pv = build_preview(read_raw_rows(p), "no")
        self.assertEqual(pv["summary"]["invalid"], 1)  # header row shown for review

    def test_csv_keeps_leading_zero(self):
        p = os.path.join(self.d, "d.csv")
        open(p, "w", encoding="utf-8-sig").write("Juan Dela Cruz,09171234567\n")
        r = build_preview(read_raw_rows(p), "auto")["records"][0]
        self.assertEqual(r["raw_number"], "09171234567")
        self.assertEqual(r["local"], "09171234567")

    def test_database_separates_consent(self):
        p = os.path.join(self.d, "e.csv")
        open(p, "w").write("Juan Dela Cruz,09171234567\nAna,09181234567\n")
        db = Database(os.path.join(self.d, "t.db"))
        pv = build_preview(read_raw_rows(p), "auto")
        self.assertEqual(db.commit_import("e.csv", "auto", pv)["valid"], 2)
        c = db.counts()
        self.assertEqual((c["valid"], c["eligible"]), (2, 0))   # no consent yet
        # re-import same file -> duplicates, order preserved
        st = db.commit_import("e.csv", "auto", pv)
        self.assertEqual(st["duplicate"], 2)
        names = [r["name"] for r in db.list_contacts(status="valid")]
        self.assertEqual(names, ["Juan Dela Cruz", "Ana"])
        # consent + suppression
        db.conn.execute("UPDATE consent SET consent_status='granted'")
        self.assertEqual(db.counts()["eligible"], 2)
        db.conn.execute("INSERT INTO suppression VALUES('+639171234567','test','now')")
        self.assertEqual(db.counts()["eligible"], 1)


if __name__ == "__main__":
    unittest.main()
