[app]
title = Car Promo Caller
package.name = carpromocaller
package.domain = org.sideline
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = tests,bin,.buildozer
version = 0.1.0

# sqlite3 is needed for the database; openpyxl + et_xmlfile read .xlsx files
requirements = python3,kivy==2.3.0,sqlite3,openpyxl,et_xmlfile,pyjnius,android

orientation = portrait
fullscreen = 0

# Stage 1 only needs file reading. Calling/SMS permissions come in Stage 3-5.
android.permissions = READ_EXTERNAL_STORAGE

# API 28 target keeps old-style file access working on Android 10 (see README).
android.api = 28
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
