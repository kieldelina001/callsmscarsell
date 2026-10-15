"""Philippine mobile number cleaning.

Accepted inputs (spaces, dashes, brackets are ignored):
    09171234567, 9171234567, 639171234567, +639171234567, 00639171234567
Everything is stored as +639XXXXXXXXX (E.164). Numbers are ALWAYS handled
as text so leading zeros are never lost.
"""
import re

# Matches things like 9.17E+09 - Excel's "scientific notation" damage.
SCI_RE = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")


def _result(ok=False, e164="", local="", issue="", note=""):
    return {"ok": ok, "e164": e164, "local": local, "issue": issue, "note": note}


def number_to_text(value):
    """Show the original cell value as text (no '.0', no 1e+10)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def normalize_ph_mobile(value):
    """Return dict: ok, e164 (+639...), local (09...), issue, note."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return _result(issue="blank number")

    if isinstance(value, bool):
        return _result(issue="not a phone number")

    if isinstance(value, float) and (value != value or not value.is_integer()):
        return _result(issue="number has decimals - not a valid phone number")

    s = number_to_text(value).replace("\u00a0", " ").strip()

    if SCI_RE.match(s):
        return _result(issue="scientific notation (digits were lost by Excel). "
                             "Format the column as Text and re-type the numbers")

    if re.fullmatch(r"\d+\.0+", s):           # "9171234567.0"
        s = s.split(".")[0]

    s = re.sub(r"[\s\-().]", "", s)
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("00"):
        s = s[2:]

    if not s.isdigit():
        return _result(issue="contains letters or symbols")

    note = ""
    if re.fullmatch(r"639\d{9}", s):
        national = s[2:]
    elif re.fullmatch(r"09\d{9}", s):
        national = s[1:]
    elif re.fullmatch(r"9\d{9}", s):
        national = s
        note = "leading 0 was missing (Excel often removes it) - assumed 0" + s
    else:
        return _result(issue="not a valid PH mobile number "
                             "(expected 09XXXXXXXXX or +639XXXXXXXXX)")

    return _result(True, "+63" + national, "0" + national, "", note)
