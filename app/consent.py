"""Opt-out handling. Opted-out numbers go to the suppression list for good."""
import re

from .phone_utils import last10, normalize_ph_mobile

STOP_RE = re.compile(r"^\W*(stop|unsubscribe|opt[\s\-]*out|cancel|tigil|huwag na)\b", re.I)


def is_stop_message(body):
    return bool(body and STOP_RE.match(body.strip()))


def opt_out_number(db, raw_number, reason):
    """Add one number typed by the user. Returns (ok, message)."""
    n = normalize_ph_mobile(raw_number)
    if not n["ok"]:
        return False, "Not a valid PH mobile number: " + n["issue"]
    db.add_suppression(n["e164"], reason)
    return True, "%s added to the opt-out list." % n["e164"]


def process_inbox(db, messages):
    """messages = [(address, body, date_ms)] from the phone's SMS inbox.
    Any STOP-style reply from a number we have on file is suppressed."""
    added = []
    for address, body, _date in messages:
        if not is_stop_message(body):
            continue
        digits = last10(address)
        if len(digits) < 10:
            continue
        for row in db.match_contacts_by_last10(digits):
            if not any(s["phone_e164"] == row["phone_e164"] for s in db.list_suppression()):
                db.add_suppression(row["phone_e164"], "replied STOP by SMS")
                added.append(row["phone_e164"])
    return added
