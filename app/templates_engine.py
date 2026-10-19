"""Message templates: {name}, {vehicle}, {promo} + mandatory opt-out line."""
import re

PLACEHOLDERS = ("name", "vehicle", "promo")
OPT_OUT_LINE = "Reply STOP to opt out."
DEFAULT_TEMPLATE = ("Hi {name}! We have exciting Toyota and BYD promotions available. "
                    "Reply to inquire or request a quotation.")
SAMPLE = {"name": "Juan Dela Cruz", "vehicle": "Toyota Vios", "promo": "low down payment"}

_PAT = re.compile(r"\{(\w+)\}")
_GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
            "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà^{}\\[~]|€")


def find_unknown(template):
    """Placeholders that are not supported, e.g. {nmae}."""
    return sorted({m for m in _PAT.findall(template) if m not in PLACEHOLDERS})


def render(template, name, vehicle="", promo="", add_opt_out=True):
    values = {"name": (name or "").strip(), "vehicle": (vehicle or "").strip(),
              "promo": (promo or "").strip()}
    text = _PAT.sub(lambda m: values.get(m.group(1), m.group(0)), template)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if add_opt_out and not re.search(r"\bstop\b", text, re.I):
        text = text + " " + OPT_OUT_LINE
    return text


def sms_info(text):
    """(characters, number_of_sms_parts, encoding)"""
    gsm = all(ch in _GSM7 for ch in text)
    n = len(text)
    if gsm:
        parts = 1 if n <= 160 else -(-n // 153)
    else:
        parts = 1 if n <= 70 else -(-n // 67)
    return n, parts, "GSM-7" if gsm else "Unicode"
