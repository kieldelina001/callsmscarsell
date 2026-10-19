# Car Promo Caller (full build, not yet tested on the phone)

## Files
```
main.py                     All screens (Kivy)
buildozer.spec              APK settings (pinned versions, permissions, Java folder)
java_src/org/sideline/carpromo/
    CallMonitor.java        Watches LOCAL call state (idle / off-hook)
    SmsResultReceiver.java  Collects "sent" and delivery-report results per SMS
app/
    phone_utils.py          PH number cleaning (+639XXXXXXXXX), text-safe
    importer.py             Column A (name) / Column B (number) from .xlsx/.csv
    database.py             SQLite: contacts, consent, opt-outs, campaigns, logs
    templates_engine.py     {name} {vehicle} {promo}, mandatory STOP line
    consent.py              Opt-out handling, STOP-reply scan
    campaign.py             Campaign runner: pause/resume/stop, limits, duplicate protection
    android_bridge.py       The only file that talks to Android (SIMs, calls, SMS, call log)
    bridge_dry.py           Dry-run bridge: nothing is called or sent
    exporter.py             CSV export of results and logs
tests/                      28 automatic tests (run on a PC)
```

## Tests (PC)
    pip install openpyxl
    python -m unittest discover -s tests -v

## Build
Push to GitHub; the Actions workflow builds the APK (see build.yml).

## Using it on the Huawei Y7a
1. Install, open, allow every permission it asks for.
2. Home > Import contacts. Then "Contacts, consent and opt-outs" > record consent.
3. Message template > Save.  SIM cards > Detect, choose call SIM and SMS SIM, Save.
4. New campaign: leave **DRY RUN ticked** first. Review > START. Nothing is called or sent.
5. Then a LIVE test: untick DRY RUN, Test mode ON, group size 2-3 of your own consenting numbers.
6. Report back what the Reports screen shows (answered? SIM used? sent? delivered?).

## Huawei EMUI tips
- Settings > Battery > App launch > Car Promo Caller > Manage manually: allow auto-launch,
  secondary launch and run in background.
- Keep the app open and the screen on during a campaign (the app asks Android to keep it awake).
- EMUI may show a prompt when an app sends SMS; allow it. Android also limits apps to
  roughly 30 SMS per 30 minutes, which is why the default limit is 20 per hour.
- Huawei Y7a has no Google services; nothing here needs them.

## Known limits (honest list)
- Remote ringing cannot be detected on Android 10. "Answered" is confirmed from the call log.
- Mapping a SIM to a calling account may fail on this phone; the app then refuses and says so.
- Delivery reports depend on the carrier. "Sent" is never shown as "delivered".
- Everything touching Android is untested until you run it.
