"""Car Promo Caller - full app UI (Kivy).

STATUS: the screens and android_bridge.py have NOT been run on a real phone yet.
Everything else (database, templates, consent, campaign engine, export) is
covered by automatic tests that run on a PC.
"""
import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.utils import platform

from app import consent as consent_mod
from app import exporter
from app.bridge_dry import DryRunBridge
from app.campaign import (DEFAULT_SETTINGS, POLICIES, CampaignRunner, create_campaign,
                          plan_campaign, policy_uses_call, policy_uses_sms)
from app.database import Database
from app.importer import HEADER_AUTO, HEADER_NO, HEADER_YES, build_preview, read_raw_rows
from app.templates_engine import DEFAULT_TEMPLATE, SAMPLE, render, sms_info, find_unknown

IS_ANDROID = platform == "android"
HEADER_CHOICES = {
    "Auto-detect header": HEADER_AUTO,
    "Row 1 IS a header": HEADER_YES,
    "Row 1 is NOT a header (it is a contact)": HEADER_NO,
}
STATUS_CHOICES = {"All": None, "Valid": "valid", "Invalid": "invalid", "Duplicate": "duplicate"}
POLICY_LABELS = {v: k for k, v in POLICIES.items()}

KV = """
<Btn@Button>:
    size_hint_y: None
    height: dp(46)

<FLabel@Label>:
    size_hint_y: None
    height: dp(40)
    text_size: self.width, self.height
    halign: 'left'
    valign: 'middle'

<FInput@TextInput>:
    multiline: False
    size_hint_y: None
    height: dp(40)

<ScrollText@ScrollView>:
    text: ''
    Label:
        text: root.text
        size_hint_y: None
        height: self.texture_size[1]
        text_size: self.width, None
        halign: 'left'
        valign: 'top'

ScreenManager:
    HomeScreen:
    ImportScreen:
    ContactsScreen:
    ConsentScreen:
    TemplateScreen:
    SimScreen:
    SetupScreen:
    DashboardScreen:
    ReportsScreen:
    AboutScreen:

<HomeScreen>:
    name: 'home'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        Label:
            text: 'Car Promo Caller'
            font_size: '24sp'
            size_hint_y: None
            height: dp(44)
        Label:
            text: root.stats_text
            halign: 'center'
            valign: 'middle'
            text_size: self.size
        Btn:
            text: '1. Import contacts (.xlsx / .csv)'
            on_release: app.root.current = 'import'
        Btn:
            text: '2. Contacts, consent and opt-outs'
            on_release: app.root.current = 'consent'
        Btn:
            text: '3. Message template'
            on_release: app.root.current = 'template'
        Btn:
            text: '4. SIM cards and permissions'
            on_release: app.root.current = 'sim'
        Btn:
            text: '5. New campaign'
            on_release: app.root.current = 'setup'
        Btn:
            text: '6. Campaign dashboard'
            on_release: app.root.current = 'dashboard'
        Btn:
            text: '7. Reports and export'
            on_release: app.root.current = 'reports'
        Btn:
            text: 'View all contacts'
            on_release: app.root.current = 'contacts'
        Btn:
            text: 'Privacy, limits and how it works'
            on_release: app.root.current = 'about'

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
        ScrollText:
            size_hint_y: 0.5
            text: root.message

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
        Btn:
            text: 'Search / Refresh'
            on_release: root.refresh()
        ScrollText:
            text: root.listing
        Btn:
            text: 'Back'
            on_release: app.root.current = 'home'

<ConsentScreen>:
    name: 'consent'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        Label:
            text: 'Consent and opt-outs'
            size_hint_y: None
            height: dp(30)
        Btn:
            text: 'I HAVE permission: mark ALL valid contacts as consent GRANTED'
            on_release: root.ask_grant_all()
        Btn:
            text: 'Revoke consent for everyone'
            on_release: root.ask_revoke_all()
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            TextInput:
                id: number
                hint_text: 'Mobile number, e.g. 09171234567'
                multiline: False
            Button:
                text: 'Opt out'
                size_hint_x: 0.3
                on_release: root.add_optout()
        Btn:
            text: 'Scan SMS inbox for STOP replies'
            on_release: root.scan_inbox()
        ScrollText:
            text: root.info
        Btn:
            text: 'Back'
            on_release: app.root.current = 'home'

<TemplateScreen>:
    name: 'template'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        FLabel:
            text: 'Message template. Use {name} {vehicle} {promo}'
        TextInput:
            id: tpl
            multiline: True
            size_hint_y: 0.35
        FInput:
            id: vehicle
            hint_text: 'Vehicle text for {vehicle}, e.g. Toyota Vios'
        FInput:
            id: promo
            hint_text: 'Promo text for {promo}, e.g. low down payment'
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(6)
            Button:
                text: 'Preview'
                on_release: root.preview()
            Button:
                text: 'Save'
                on_release: root.save()
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
        ScrollText:
            size_hint_y: 0.4
            text: root.preview_text

<SimScreen>:
    name: 'sim'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        Btn:
            text: 'Allow permissions (calls, SMS, SIM info, call log)'
            on_release: root.ask_permissions()
        Btn:
            text: 'Detect SIM cards / check readiness'
            on_release: root.detect()
        FLabel:
            text: 'SIM for outgoing CALLS'
        Spinner:
            id: call_spin
            text: 'System default'
            size_hint_y: None
            height: dp(44)
        FLabel:
            text: 'SIM for SMS'
        Spinner:
            id: sms_spin
            text: 'System default'
            size_hint_y: None
            height: dp(44)
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(6)
            Button:
                text: 'Save SIM choices'
                on_release: root.save()
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
        ScrollText:
            text: root.info

<SetupScreen>:
    name: 'setup'
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            GridLayout:
                cols: 2
                size_hint_y: None
                height: self.minimum_height
                padding: dp(8)
                spacing: dp(6)
                FLabel:
                    text: 'Campaign name'
                FInput:
                    id: c_name
                FLabel:
                    text: 'What to do'
                Spinner:
                    id: policy
                    size_hint_y: None
                    height: dp(64)
                FLabel:
                    text: 'Call SIM'
                Spinner:
                    id: call_spin
                    size_hint_y: None
                    height: dp(44)
                FLabel:
                    text: 'SMS SIM'
                Spinner:
                    id: sms_spin
                    size_hint_y: None
                    height: dp(44)
                FLabel:
                    text: 'Call length (seconds)'
                FInput:
                    id: call_seconds
                    input_filter: 'int'
                FLabel:
                    text: 'Pause between contacts (s)'
                FInput:
                    id: delay
                    input_filter: 'int'
                FLabel:
                    text: 'Max contacts per run'
                FInput:
                    id: max_contacts
                    input_filter: 'int'
                FLabel:
                    text: 'Max SMS per hour'
                FInput:
                    id: max_sms
                    input_filter: 'int'
                FLabel:
                    text: 'Test mode (small group)'
                CheckBox:
                    id: test_chk
                    size_hint_y: None
                    height: dp(40)
                FLabel:
                    text: 'Test group size'
                FInput:
                    id: test_count
                    input_filter: 'int'
                FLabel:
                    text: 'DRY RUN (nothing is called or sent)'
                CheckBox:
                    id: dry_chk
                    size_hint_y: None
                    height: dp(40)
        BoxLayout:
            size_hint_y: None
            height: dp(50)
            padding: dp(6)
            spacing: dp(6)
            Button:
                text: 'Review and confirm'
                on_release: root.review()
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'

<DashboardScreen>:
    name: 'dashboard'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        Label:
            text: root.title_text
            size_hint_y: None
            height: dp(34)
            font_size: '16sp'
        Label:
            text: root.current_text
            size_hint_y: None
            height: dp(40)
            text_size: self.width, None
        ProgressBar:
            max: 100
            value: root.progress
            size_hint_y: None
            height: dp(16)
        ScrollText:
            text: root.stats_text
        BoxLayout:
            size_hint_y: None
            height: dp(50)
            spacing: dp(4)
            Button:
                text: 'Start'
                on_release: root.do_start()
            Button:
                text: 'Pause'
                on_release: root.do_pause()
            Button:
                text: 'Resume'
                on_release: root.do_resume()
            Button:
                text: 'Stop'
                on_release: root.do_stop()
        Btn:
            text: 'Back'
            on_release: app.root.current = 'home'

<ReportsScreen>:
    name: 'reports'
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
                hint_text: 'Search name / number / outcome'
                multiline: False
                on_text_validate: root.refresh()
            Spinner:
                id: view
                text: 'Results'
                values: ['Results', 'Event log']
                size_hint_x: 0.35
                on_text: root.refresh()
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(6)
            Button:
                text: 'Refresh'
                on_release: root.refresh()
            Button:
                text: 'Export CSV'
                on_release: root.export()
            Button:
                text: 'Back'
                on_release: app.root.current = 'home'
        ScrollText:
            text: root.listing

<AboutScreen>:
    name: 'about'
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        ScrollText:
            text: root.ABOUT
        Btn:
            text: 'Back'
            on_release: app.root.current = 'home'
"""


def show_popup(title, text, buttons=None, size=(0.92, 0.7)):
    box = BoxLayout(orientation="vertical", spacing=8, padding=8)
    lab = Label(text=text, halign="left", valign="top")
    lab.bind(size=lambda w, s: setattr(w, "text_size", (w.width, None)))
    from kivy.uix.scrollview import ScrollView
    sv = ScrollView()
    lab.size_hint_y = None
    lab.bind(texture_size=lambda w, s: setattr(w, "height", s[1]))
    sv.add_widget(lab)
    box.add_widget(sv)
    row = BoxLayout(size_hint_y=None, height=48, spacing=8)
    pop = Popup(title=title, content=box, size_hint=size)
    for label, cb in (buttons or [("OK", None)]):
        b = Button(text=label)
        b.bind(on_release=lambda _w, cb=cb: (pop.dismiss(), cb() if cb else None))
        row.add_widget(b)
    box.add_widget(row)
    pop.open()


def to_int(text, default):
    try:
        return int(str(text).strip())
    except ValueError:
        return default


class HomeScreen(Screen):
    stats_text = StringProperty("")

    def on_pre_enter(self, *args):
        c = App.get_running_app().db.counts()
        self.stats_text = (
            "Contacts: %(total)d  (valid %(valid)d, invalid %(invalid)d, duplicate %(duplicate)d)\n"
            "Consent granted: %(granted)d   Opted out: %(optouts)d\n"
            "ELIGIBLE to contact: %(eligible)d" % c)


class ImportScreen(Screen):
    message = StringProperty("Choose a .xlsx or .csv file. Column A = Name, "
                             "Column B = Mobile Number.")
    preview = None
    path = None
    mode = HEADER_AUTO

    def on_pre_enter(self, *args):
        start = "/storage/emulated/0" if IS_ANDROID else os.path.expanduser("~")
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
        self.message = ("Imported.\nValid: %(valid)d   Invalid: %(invalid)d   Duplicate: %(duplicate)d"
                        "\n\nConsent for every new contact starts as UNKNOWN, so none are eligible "
                        "yet. Go to 'Contacts, consent and opt-outs' to record consent." % stored)


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
            line = "#%d (row %d) %s  ->  %s  [%s | consent: %s%s]" % (
                r["id"], r["source_row"], r["name"] or "(no name)",
                r["phone_e164"] or r["raw_number"], r["status"], r["consent"],
                " | OPTED OUT" if r["optout"] else "")
            if r["issue"]:
                line += "\n      problem: " + r["issue"]
            lines.append(line)
        if len(rows) >= 300:
            lines.append("\n(showing first 300 - use Search to narrow down)")
        self.listing = "\n".join(lines)


class ConsentScreen(Screen):
    info = StringProperty("")

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        db = App.get_running_app().db
        c = db.counts()
        sup = db.list_suppression()
        lines = ["Valid contacts: %(valid)d\nConsent granted: %(granted)d\nOpted out: %(optouts)d\n"
                 "ELIGIBLE (granted and not opted out): %(eligible)d\n" % c,
                 "Opt-out list (never contacted again):"]
        lines += ["  %s  (%s, %s)" % (s["phone_e164"], s["reason"], s["added_at"]) for s in sup[:100]] or ["  (empty)"]
        self.info = "\n".join(lines)

    def ask_grant_all(self):
        show_popup("Confirm consent",
                   "Only continue if EVERY valid contact in your list has given you permission "
                   "to receive promotional calls/SMS (Philippine Data Privacy Act / direct-marketing "
                   "rules). Your confirmation is saved with a timestamp.\n\n"
                   "Contacts already opted out stay blocked.",
                   [("Cancel", None), ("I confirm", self._grant_all)])

    def _grant_all(self):
        App.get_running_app().db.set_consent_all_valid(
            "owner confirmed permission on " + time.strftime("%Y-%m-%d %H:%M"))
        self.refresh()

    def ask_revoke_all(self):
        show_popup("Revoke consent", "Set consent back to 'unknown' for every contact?",
                   [("Cancel", None), ("Revoke", lambda: (App.get_running_app().db.revoke_all_consent(),
                                                           self.refresh()))])

    def add_optout(self):
        ok, msg = consent_mod.opt_out_number(App.get_running_app().db, self.ids.number.text,
                                             "added manually")
        if ok:
            self.ids.number.text = ""
        show_popup("Opt-out", msg)
        self.refresh()

    def scan_inbox(self):
        app = App.get_running_app()
        bridge = app.real_bridge()
        if bridge is None:
            show_popup("Inbox scan", "Reading the SMS inbox only works on the phone.")
            return
        try:
            added = consent_mod.process_inbox(app.db, bridge.read_inbox(0))
        except Exception as exc:
            show_popup("Inbox scan", "Could not read the inbox:\n%s\n\nAllow permissions first." % exc)
            return
        show_popup("Inbox scan", "%d new opt-out(s) added from STOP replies." % len(added)
                   + ("\n" + "\n".join(added) if added else ""))
        self.refresh()


class TemplateScreen(Screen):
    preview_text = StringProperty("")

    def on_pre_enter(self, *args):
        db = App.get_running_app().db
        self.ids.tpl.text = db.get_setting("template", DEFAULT_TEMPLATE)
        self.ids.vehicle.text = db.get_setting("vehicle", "")
        self.ids.promo.text = db.get_setting("promo", "")

    def preview(self):
        t = self.ids.tpl.text
        unknown = find_unknown(t)
        text = render(t, SAMPLE["name"], self.ids.vehicle.text or SAMPLE["vehicle"],
                      self.ids.promo.text or SAMPLE["promo"])
        n, parts, enc = sms_info(text)
        warn = ("\n\nUNKNOWN placeholder(s): " + ", ".join("{%s}" % u for u in unknown)) if unknown else ""
        self.preview_text = ("Preview for 'Juan Dela Cruz':\n\n%s\n\n%d characters, %d SMS part(s), %s.\n"
                             "'Reply STOP to opt out.' is added automatically if your text has no STOP wording.%s"
                             % (text, n, parts, enc, warn))

    def save(self):
        db = App.get_running_app().db
        db.set_setting("template", self.ids.tpl.text)
        db.set_setting("vehicle", self.ids.vehicle.text)
        db.set_setting("promo", self.ids.promo.text)
        self.preview()
        self.preview_text += "\n\nSaved."


class SimScreen(Screen):
    info = StringProperty("Tap 'Allow permissions', then 'Detect SIM cards'.")
    opts = None

    def on_pre_enter(self, *args):
        self.detect(quiet=True)

    def ask_permissions(self):
        if not IS_ANDROID:
            show_popup("Permissions", "Permissions are only needed on the phone.")
            return
        from app.android_bridge import request_all_permissions
        request_all_permissions(lambda perms, grants: Clock.schedule_once(
            lambda dt: self.detect(), 0.5))
        show_popup("Permissions",
                   "Android will now ask for: Phone (make calls, end calls, read SIM info and call "
                   "state), SMS (send, read replies to find STOP), Call log (to confirm a call was "
                   "answered) and Storage (import/export files).\n\nAllow all of them.")

    def detect(self, quiet=False):
        app = App.get_running_app()
        self.opts = app.sim_options()
        labels = [o[0] for o in self.opts]
        for sid, key in (("call_spin", "call_sim"), ("sms_spin", "sms_sim")):
            sp = self.ids[sid]
            sp.values = labels
            sp.text = app.label_for_pref(self.opts, app.db.get_json(key, {"mode": "default"}))
        lines = []
        if IS_ANDROID:
            from app.android_bridge import permission_status
            miss = [k for k, v in permission_status().items() if not v]
            lines.append("Missing permissions: " + (", ".join(miss) if miss else "none"))
        else:
            lines.append("(PC mode: showing fake test SIMs)")
        if app.sim_error:
            lines.append("SIM detection problem: " + app.sim_error)
        for label, pref in self.opts[1:]:
            lines.append(label)
        if len(self.opts) == 1 and not app.sim_error:
            lines.append("No active SIM card was reported by Android.")
        lines.append("\nNotes:\n- If only one SIM is active, only that SIM is offered.\n"
                     "- The phone number is shown only if the SIM/carrier provides it to apps.\n"
                     "- If Android cannot map a SIM to a calling account, the app REFUSES to call and "
                     "tells you. It never silently uses another SIM. Choose 'System default' then.\n"
                     "- Huawei EMUI may also show its own prompts or block background activity; "
                     "see the README.")
        self.info = "\n".join(lines)

    def save(self):
        app = App.get_running_app()
        for sid, key in (("call_spin", "call_sim"), ("sms_spin", "sms_sim")):
            pref = dict(self.opts)[self.ids[sid].text] if self.opts else {"mode": "default"}
            app.db.set_json(key, pref)
        show_popup("Saved", "SIM choices saved.\nCalls: %s\nSMS: %s" % (
            self.ids.call_spin.text, self.ids.sms_spin.text))


class SetupScreen(Screen):
    opts = None

    def on_pre_enter(self, *args):
        app, db = App.get_running_app(), App.get_running_app().db
        s = dict(DEFAULT_SETTINGS, **db.get_json("campaign_settings", {}))
        self.opts = app.sim_options()
        labels = [o[0] for o in self.opts]
        for sid, key in (("call_spin", "call_sim"), ("sms_spin", "sms_sim")):
            self.ids[sid].values = labels
            self.ids[sid].text = app.label_for_pref(self.opts, db.get_json(key, {"mode": "default"}))
        self.ids.policy.values = list(POLICIES.values())
        self.ids.policy.text = POLICIES[s["policy"]]
        self.ids.c_name.text = self.ids.c_name.text or time.strftime("Campaign %Y-%m-%d")
        self.ids.call_seconds.text = str(s["call_seconds"])
        self.ids.delay.text = str(s["delay_seconds"])
        self.ids.max_contacts.text = str(s["max_contacts"])
        self.ids.max_sms.text = str(s["max_sms_per_hour"])
        self.ids.test_chk.active = bool(s["test_mode"])
        self.ids.test_count.text = str(s["test_count"])
        self.ids.dry_chk.active = bool(s["dry_run"])

    def read_settings(self):
        d = DEFAULT_SETTINGS
        return {
            "policy": POLICY_LABELS[self.ids.policy.text],
            "call_seconds": max(5, to_int(self.ids.call_seconds.text, d["call_seconds"])),
            "delay_seconds": max(10, to_int(self.ids.delay.text, d["delay_seconds"])),
            "max_contacts": max(1, to_int(self.ids.max_contacts.text, d["max_contacts"])),
            "max_sms_per_hour": max(1, to_int(self.ids.max_sms.text, d["max_sms_per_hour"])),
            "no_repeat_hours": d["no_repeat_hours"],
            "test_mode": self.ids.test_chk.active,
            "test_count": max(1, to_int(self.ids.test_count.text, d["test_count"])),
            "dry_run": self.ids.dry_chk.active,
            "delivery_wait_seconds": d["delivery_wait_seconds"],
        }

    def review(self):
        app, db = App.get_running_app(), App.get_running_app().db
        s = self.read_settings()
        call_sim, sms_sim = dict(self.opts)[self.ids.call_spin.text], dict(self.opts)[self.ids.sms_spin.text]
        db.set_json("campaign_settings", s)
        db.set_json("call_sim", call_sim)
        db.set_json("sms_sim", sms_sim)
        template = db.get_setting("template", DEFAULT_TEMPLATE)
        vehicle, promo = db.get_setting("vehicle", ""), db.get_setting("promo", "")
        recipients, problems = plan_campaign(db, template, vehicle, promo, s)

        bridge = app.make_bridge(s["dry_run"])
        if bridge is None:
            problems.append("Real calls and SMS only work on the phone. Tick DRY RUN to rehearse on a PC.")
        else:
            miss = bridge.permissions_missing(policy_uses_call(s["policy"]), policy_uses_sms(s["policy"]))
            if miss and not s["dry_run"]:
                problems.append("Missing permissions: %s. Open 'SIM cards and permissions'." % ", ".join(miss))
            try:
                if policy_uses_call(s["policy"]):
                    ok, why = bridge.sim_ready(call_sim)
                    if not ok:
                        problems.append("Call SIM not usable: " + why)
                if policy_uses_sms(s["policy"]):
                    ok, why = bridge.sim_ready(sms_sim)
                    if not ok:
                        problems.append("SMS SIM not usable: " + why)
            except Exception as exc:
                problems.append("SIM check failed: %s" % exc)
        if problems:
            show_popup("Cannot start yet", "\n\n".join("- " + p for p in problems))
            return
        sample = "\n".join("%s -> %s\n   \"%s\"" % (r[1], r[2], r[3]) for r in recipients[:3])
        text = ("%s\n\nMODE: %s\nCall SIM: %s\nSMS SIM: %s\n\nRecipients: %d%s\nCall length: %ds, pause "
                "between contacts: %ds\nLimits: %d contacts per run, %d SMS per hour\n\n"
                "First messages:\n%s\n\n%s"
                % ("*** DRY RUN: nothing will be called or sent ***" if s["dry_run"] else
                   "*** LIVE: real calls and SMS will be made ***",
                   POLICIES[s["policy"]], self.ids.call_spin.text if policy_uses_call(s["policy"]) else "(not used)",
                   self.ids.sms_spin.text if policy_uses_sms(s["policy"]) else "(not used)",
                   len(recipients), " (test group)" if s["test_mode"] else "", s["call_seconds"],
                   s["delay_seconds"], s["max_contacts"], s["max_sms_per_hour"], sample,
                   "Only contacts with recorded consent who are not opted out are included. "
                   "SMS is skipped whenever the required call result is not confirmed."))

        def go():
            try:
                cid = create_campaign(db, self.ids.c_name.text.strip() or "Campaign", template,
                                      vehicle, promo, call_sim, sms_sim, s)
            except ValueError as exc:
                show_popup("Cannot start", str(exc))
                return
            app.attach_campaign(cid)
            app.runner.start()
            app.root.current = "dashboard"
        show_popup("Confirm campaign", text, [("Cancel", None), ("START", go)], size=(0.96, 0.9))


class DashboardScreen(Screen):
    title_text = StringProperty("No campaign yet")
    current_text = StringProperty("")
    stats_text = StringProperty("")
    progress = NumericProperty(0)
    _ev = None

    def on_enter(self, *args):
        app = App.get_running_app()
        if app.runner is None:
            c = app.db.latest_open_campaign()
            if c:
                app.attach_campaign(c["id"])
        self.refresh()
        self._ev = Clock.schedule_interval(lambda dt: self.refresh(), 1)

    def on_leave(self, *args):
        if self._ev:
            self._ev.cancel()

    def refresh(self):
        app = App.get_running_app()
        if app.campaign_id is None:
            return
        db, cid = app.db, app.campaign_id
        c, st = db.get_campaign(cid), db.campaign_stats(cid)
        self.title_text = "#%d %s  [%s]" % (cid, c["name"], c["status"].upper())
        self.current_text = ((app.runner.current if app.runner and app.runner.alive else "") or "")
        if c["pause_reason"]:
            self.current_text = "PAUSED: " + c["pause_reason"]
        finished = st["done"] + st["skipped"] + st["interrupted"]
        self.progress = 100.0 * finished / st["total"] if st["total"] else 0
        self.stats_text = (
            "Progress: %d of %d contacts handled\nRemaining eligible: %d\n\n"
            "Calls answered: %d\nCalls failed to start: %d\n\n"
            "SMS handed to network (sent): %d\nSMS failed: %d\nSMS result unknown (not retried): %d\n"
            "Delivery reports received: %d  (many carriers send none - 'sent' is NOT 'delivered')\n\n"
            "Skipped: %d   Needs review (interrupted): %d"
            % (finished, st["total"], st["pending"], st["answered"], st["call_failed"], st["sms_sent"],
               st["sms_failed"], st["sms_unknown"], st["sms_delivered"], st["skipped"], st["interrupted"]))

    def do_start(self):
        r = App.get_running_app().runner
        if r is None:
            show_popup("Start", "Create a campaign first (New campaign).")
        elif not r.alive:
            r.start()

    def do_pause(self):
        r = App.get_running_app().runner
        if r:
            r.pause()

    def do_resume(self):
        r = App.get_running_app().runner
        if r:
            r.resume()

    def do_stop(self):
        r = App.get_running_app().runner
        if r:
            show_popup("Stop campaign", "Stop this campaign for good?",
                       [("No", None), ("Stop", r.stop)])


class ReportsScreen(Screen):
    listing = StringProperty("")

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        db, q = App.get_running_app().db, self.ids.search.text.strip().lower()
        out = []
        if self.ids.view.text == "Event log":
            for r in db.rows("SELECT * FROM logs ORDER BY id DESC LIMIT 500"):
                line = "%s [c%s] %s %s: %s" % (r["ts"], r["campaign_id"], r["phone"] or "", r["event"], r["detail"])
                if not q or q in line.lower():
                    out.append(line)
        else:
            sql = ("SELECT cc.*, c.name AS cname, "
                   "(SELECT duration_s FROM call_attempts a WHERE a.cc_id=cc.id ORDER BY a.id DESC LIMIT 1) AS secs, "
                   "(SELECT delivery_state FROM sms_attempts s WHERE s.cc_id=cc.id ORDER BY s.id DESC LIMIT 1) AS deliv "
                   "FROM campaign_contacts cc JOIN campaigns c ON c.id=cc.campaign_id "
                   "ORDER BY cc.campaign_id DESC, cc.position LIMIT 800")
            for r in db.rows(sql):
                line = ("[c%d] %s -> %s | %s | call: %s%s | SMS: %s%s%s" % (
                    r["campaign_id"], r["name"], r["phone_e164"], r["state"], r["call_outcome"] or "-",
                    " (%ss)" % r["secs"] if r["secs"] else "", r["sms_state"],
                    " / delivery: %s" % r["deliv"] if r["deliv"] and r["deliv"] != "none" else "",
                    ("\n     " + r["note"]) if r["note"] else ""))
                if not q or q in line.lower():
                    out.append(line)
        self.listing = "\n".join(out) or "Nothing to show yet."

    def export(self):
        app = App.get_running_app()
        folder = (app.real_bridge() or DryRunBridge()).storage_dir()
        try:
            p1 = exporter.export_results(app.db, folder)
            p2 = exporter.export_logs(app.db, folder)
        except Exception as exc:
            show_popup("Export failed", str(exc))
            return
        show_popup("Exported", "Saved:\n%s\n%s" % (p1, p2))


class AboutScreen(Screen):
    ABOUT = (
        "HOW IT WORKS\n"
        "- Contacts come from Column A (name) and Column B (mobile number) of your file.\n"
        "- Only contacts with recorded consent who have not opted out are ever contacted.\n"
        "- A 'Reply STOP to opt out.' line is always added to promotional SMS. STOP replies can be "
        "found by scanning your SMS inbox, and numbers can be added by hand. Opted-out numbers are "
        "never contacted again.\n\n"
        "WHAT ANDROID 10 CAN AND CANNOT DO\n"
        "- It does NOT tell apps whether the other phone is ringing. This app never claims that.\n"
        "- It CAN show, afterwards, whether an outgoing call connected (call log duration above 0). "
        "So the safe default is: call, then SMS only if the call was ANSWERED.\n"
        "- 'Sent' means the phone handed the SMS to the network. 'Delivered' appears only if the "
        "carrier returns a delivery report.\n"
        "- If the chosen SIM cannot be used or Android refuses to route a call to it, the campaign "
        "stops and tells you. It never switches SIM by itself.\n\n"
        "YOUR DATA\n"
        "- Everything is stored on this phone. Nothing is uploaded anywhere.\n"
        "- Philippine Data Privacy Act: keep proof of consent, honor opt-outs, and only message "
        "people who agreed to receive promotions.\n"
        "- This APK is for your own installation. Google Play restricts call-log and SMS permissions, "
        "so it would not be accepted there as-is.\n\n"
        "KEEP THE APP OPEN\n"
        "- Keep the app on screen and the phone awake during a campaign. If Android or EMUI closes "
        "the app, reopen it and press Resume; contacts caught mid-action are flagged for review, "
        "never re-sent."
    )


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
            out.append("row %d: '%s' / '%s' -> %s" % (r["source_row"], r["name"], r["raw_number"], r["issue"]))
        if len(bad) > 40:
            out.append("...and %d more" % (len(bad) - 40))
    return "\n".join(out)


class CarPromoApp(App):
    runner = None
    campaign_id = None
    sim_error = ""
    _real = None

    def build(self):
        self.title = "Car Promo Caller"
        self.db = Database(os.path.join(self.user_data_dir, "carpromo.db"))
        self.db.recover_after_restart()      # anything mid-action is flagged, never re-sent
        return Builder.load_string(KV)

    def on_start(self):
        if IS_ANDROID:
            try:
                from app.android_bridge import request_all_permissions
                request_all_permissions()
            except Exception as exc:
                print("Permission request failed:", exc)

    def on_pause(self):
        return True      # keep running if the user switches app

    # ---- bridges ----
    def real_bridge(self):
        if not IS_ANDROID:
            return None
        if self._real is None:
            from app.android_bridge import AndroidBridge
            self._real = AndroidBridge()
        return self._real

    def make_bridge(self, dry_run):
        real = None
        if IS_ANDROID:
            try:
                real = self.real_bridge()
            except Exception as exc:
                self.sim_error = str(exc)
        if dry_run:
            return DryRunBridge(sim_source=real)
        return real

    # ---- SIM spinner helpers ----
    def sim_options(self):
        opts = [("System default", {"mode": "default"})]
        self.sim_error = ""
        try:
            src = self.real_bridge() if IS_ANDROID else DryRunBridge()
            sims = src.list_sims() if src else []
        except Exception as exc:
            sims, self.sim_error = [], str(exc)
        for s in sims:
            label = "SIM %d - %s%s%s" % (s["slot"] + 1, s["carrier"] or "unknown carrier",
                                         " (%s)" % s["number"] if s["number"] else "",
                                         "" if s["ready"] else " [%s]" % s["state_text"])
            opts.append((label, {"mode": "slot", "slot": s["slot"], "label": s["carrier"]}))
        return opts

    @staticmethod
    def label_for_pref(opts, pref):
        for label, p in opts:
            if p.get("mode") == pref.get("mode") and p.get("slot") == pref.get("slot"):
                return label
        return opts[0][0]

    # ---- campaigns ----
    def attach_campaign(self, cid):
        import json
        c = self.db.get_campaign(cid)
        dry = bool(json.loads(c["settings"] or "{}").get("dry_run", True))
        bridge = self.make_bridge(dry)
        if bridge is None:
            return
        self.campaign_id = cid
        self.runner = CampaignRunner(self.db, bridge, cid)


if __name__ == "__main__":
    CarPromoApp().run()
