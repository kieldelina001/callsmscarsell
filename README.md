# Car Promo Caller — Stage 1

## Folder structure
```
car_promo_caller/
├── main.py              Kivy screens (Home, Import, Contacts)
├── buildozer.spec       APK build settings
├── requirements.txt     PC-side libraries for testing
├── CONTINUATION_PROMPT.md
├── app/
│   ├── phone_utils.py   Cleans Philippine numbers -> +639XXXXXXXXX
│   ├── importer.py      Reads Column A/B from .xlsx/.csv, header handling, preview
│   └── database.py      SQLite: contacts, consent, suppression, eligible view
└── tests/test_import.py 8 automatic tests
```
(Later stages add: templates.py, sim.py, campaign.py, and a Java/Kotlin bridge.)

## Run the tests (any PC with Python 3.9+)
    pip install openpyxl
    python -m unittest tests.test_import -v

## Try the UI on a PC (optional)
    pip install kivy openpyxl
    python main.py

## Build the APK (Linux or Windows WSL2 Ubuntu)
    sudo apt install -y python3-pip git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev libffi-dev libssl-dev
    pip install --user buildozer cython
    cd car_promo_caller
    buildozer android debug
The APK appears in `bin/`. Copy it to the phone and tap it (allow "install unknown apps").
The first build downloads a lot and can take 20-60 minutes.

## Why android.api = 28?
Android 10 with a newer target blocks direct file-path access to Downloads
("scoped storage"). Targeting 28 lets the simple file browser work. This is fine for
installing the APK yourself, but Google Play would not accept it.

## Troubleshooting
- Build fails on `sqlite3`/`openpyxl`: send me the last 40 lines of the log.
- File list is empty on the phone: Settings > Apps > Car Promo Caller > Permissions > Storage.
- Numbers lose the leading 0 in Excel: format Column B as Text before typing numbers.
