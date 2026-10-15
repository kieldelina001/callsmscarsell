"""Car Promo Caller - Stage 1: skeleton, local database, contact import.

NOTE: This UI file has NOT been run on a real phone yet.
"""
import os

from kivy.app import App
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.screenmanager import Screen
from kivy.utils import platform

from app.database import Database
from app.importer import (HEADER_AUTO, HEADER_NO, HEADER_YES,
                          build_preview, read_raw_rows)

HEADER_CHOICES = {
    "Auto-detect header": HEADER_AUTO,
    "Row 1 IS a header": HEADER_YES,
    "Row 1 is NOT a header (it is a contact)": HEADER_NO,
}
STATUS_CHOICES = {"All": None, "Valid": "valid", "Invalid": "invalid", "Duplicate": "duplicate"}

KV = """
ScreenManager:
    HomeScreen:
    ImportScreen:
    ContactsScreen:

<HomeScreen>:
    name: 'home'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(12)
        Label:
            text: 'Car Promo Caller'
            font_size: '26sp'
            size_hint_y: None
            height: dp(60)
        Label:
            text: root.stats_text
            halign: 'center'
            valign: 'middle'
            text_size: self.size
        Button:
            text: 'Import contacts (.xlsx / .csv)'
            size_hint_y: None
            height: dp(56)
            on_release: app.root.current = 'import'
        Button:
            text: 'View contacts'
            size_hint_y: None
            height: dp(56)
            on_release: app.root.current = 'contacts'
        Label:
            text: 'Stage 1 build: calling and SMS are not added yet.'
            font_size: '13sp'
            size_hint_y: None
            height: dp(40)

<ImportScreen>:
    name: 'import'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        Label:
            text: '1) Pick a file   2) Preview   3) Confirm'
            size_hint_y: None
            height: dp(28)
        FileChooserListView:
            id: chooser
            filters: ['*.csv', '*.xlsx']
            size_hint_y: 0.35
        Spinner:
            id: header_spinner
            text: 'Auto-detect header'
            values: ['Auto-detect header', 'Row 1 IS a header', 'Row 1 is NOT a header (it is a contact)']
            size_hint_y: None
            height: dp(44)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(6)
            Button:
                text: 'Preview'
                on_release: root.do_preview()
            Button:
                id: confirm_btn
                text: 'Confirm import'
                disabled: True
                on_release: root.do_confirm()
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
        ScrollView:
            size_hint_y: 0.5
            Label:
                id: preview_label
                text: root.message
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'

<ContactsScreen>:
    name: 'contacts'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            TextInput:
                id: search
                hint_text: 'Search name or number'
                multiline: False
                on_text_validate: root.refresh()
            Spinner:
                id: status_spinner
                text: 'All'
                values: ['All', 'Valid', 'Invalid', 'Duplicate']
                size_hint_x: 0.4
                on_text: root.refresh()
        Button:
            text: 'Search / Refresh'
            size_hint_y: None
            height: dp(44)
            on_release: root.refresh()
        ScrollView:
            Label:
                text: root.listing
                size_hint_y: None
                height: self.texture_size[1]
                text_size: self.width, None
                halign: 'left'
                valign: 'top'
        Button:
            text: 'Back'
            size_hint_y: None
            height: dp(48)
            on_release: app.root.current = 'home'
"""


class HomeScreen(Screen):
    stats_text = StringProperty("")

    def on_pre_enter(self, *args):
        c = App.get_running_app().db.counts()
        self.stats_text = (
            "Contacts stored: %(total)d\nValid: %(valid)d   Invalid: %(invalid)d   "
            "Duplicate: %(duplicate)d\nEligible for promo (consent granted, "
            "not opted out): %(eligible)d" % c)


class ImportScreen(Screen):
    message = StringProperty("Choose a .xlsx or .csv file. Column A = Name, "
                             "Column B = Mobile Number.")
    preview = None
    path = None
    mode = HEADER_AUTO

    def on_pre_enter(self, *args):
        start = "/storage/emulated/0" if platform == "android" else os.path.expanduser("~")
        if os.path.isdir(start):
            self.ids.chooser.path = start

    def do_preview(self):
        self.preview = None
        self.ids.confirm_btn.disabled = True
        sel = self.ids.chooser.selection
        if not sel:
            self.message = "Please tap a .csv or .xlsx file in the list first."
            return
        self.path = sel[0]
        self.mode = HEADER_CHOICES[self.ids.header_spinner.text]
        try:
            self.preview = build_preview(read_raw_rows(self.path), self.mode)
        except Exception as exc:
            self.message = "Could not read that file:\n%s" % exc
            return
        self.message = format_preview(self.preview, os.path.basename(self.path))
        self.ids.confirm_btn.disabled = self.preview["summary"]["valid"] == 0

    def do_confirm(self):
        if not self.preview:
            return
        stored = App.get_running_app().db.commit_import(
            os.path.basename(self.path), self.mode, self.preview)
        self.ids.confirm_btn.disabled = True
        self.preview = None
        self.message = ("Imported.\nValid: %(valid)d   Invalid: %(invalid)d   "
                        "Duplicate: %(duplicate)d\n\nConsent for every new contact "
                        "starts as UNKNOWN, so none are eligible for messaging yet."
                        % stored)


class ContactsScreen(Screen):
    listing = StringProperty("")

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        status = STATUS_CHOICES[self.ids.status_spinner.text]
        rows = App.get_running_app().db.list_contacts(status, self.ids.search.text.strip())
        if not rows:
            self.listing = "No contacts to show."
            return
        lines = []
        for r in rows:
            line = "#%d (row %d) %s  ->  %s  [%s]" % (
                r["id"], r["source_row"], r["name"] or "(no name)",
                r["phone_e164"] or r["raw_number"], r["status"])
            if r["issue"]:
                line += "\n      problem: " + r["issue"]
            lines.append(line)
        if len(rows) >= 300:
            lines.append("\n(showing first 300 - use Search to narrow down)")
        self.listing = "\n".join(lines)


def format_preview(pv, filename):
    s, recs = pv["summary"], pv["records"]
    out = ["File: %s" % filename]
    if s["header_skipped"]:
        out.append("Header row detected and skipped: Name='%s', Number='%s'" % s["header_row"])
    else:
        out.append("No header row - the first row is treated as a contact.")
    out.append("Rows read: %d   Valid: %d   Invalid: %d   Duplicate: %d   Empty rows ignored: %d"
               % (s["data_rows"], s["valid"], s["invalid"], s["duplicate"], s["empty_rows_skipped"]))
    out.append("\nPREVIEW (Column A = Name  ->  Column B = Mobile Number):")
    for r in [x for x in recs if x["status"] == "valid"][:15]:
        extra = "   (note: %s)" % r["note"] if r["note"] else ""
        out.append("row %d: %s  ->  %s%s" % (r["source_row"], r["name"], r["phone"], extra))
    bad = [x for x in recs if x["status"] != "valid"]
    if bad:
        out.append("\nROWS TO REVIEW (these will NOT be messaged):")
        for r in bad[:40]:
            out.append("row %d: '%s' / '%s' -> %s" % (
                r["source_row"], r["name"], r["raw_number"], r["issue"]))
        if len(bad) > 40:
            out.append("...and %d more" % (len(bad) - 40))
    return "\n".join(out)


class CarPromoApp(App):
    def build(self):
        self.title = "Car Promo Caller"
        self.db = Database(os.path.join(self.user_data_dir, "carpromo.db"))
        return Builder.load_string(KV)

    def on_start(self):
        if platform == "android":
            try:
                from android.permissions import Permission, request_permissions
                request_permissions([Permission.READ_EXTERNAL_STORAGE])
            except Exception as exc:
                print("Permission request failed:", exc)


if __name__ == "__main__":
    CarPromoApp().run()
