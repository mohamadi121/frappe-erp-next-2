"""Office-specific optional input checks; mirrors Flutter OfficeInputValidation."""
import re
from urllib.parse import urlsplit

from asoud_erp.services.party_validation import is_valid_iranian_national_code


def digits(value):
    return str(value or "").strip().translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def identity(value, legal=False):
    code = digits(value)
    if not code:
        return ""
    if not re.fullmatch(r"[0-9]{11}" if legal else r"[0-9]{10}", code):
        raise ValueError("شناسه ملی باید دقیقاً ۱۱ رقم باشد." if legal else "کد ملی باید دقیقاً ۱۰ رقم باشد.")
    if not legal:
        if not is_valid_iranian_national_code(code):
            raise ValueError("کد ملی معتبر نیست.")
    else:
        offset = int(code[9]) + 2
        weights = (29, 27, 23, 19, 17)
        remainder = sum((int(code[i]) + offset) * weights[i % 5] for i in range(10)) % 11
        if len(set(code)) == 1 or int(code[3:9]) == 0 or int(code[10]) != (0 if remainder == 10 else remainder):
            raise ValueError("شناسه ملی حقوقی معتبر نیست.")
    return code


def mobile(value):
    text = digits(value)
    if text and not re.fullmatch(r"09[0-9]{9}", text):
        raise ValueError("شماره موبایل باید ۱۱ رقم باشد و با ۰۹ شروع شود.")
    return text


def postal_code(value):
    text = digits(value)
    if text and not re.fullmatch(r"[0-9]{10}", text):
        raise ValueError("کد پستی باید ۱۰ رقم باشد.")
    return text


def website(value):
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text if "://" in text else "https://" + text
    try:
        uri = urlsplit(normalized)
        labels = (uri.hostname or "").split(".")
        if (re.search(r"\s", text) or uri.scheme not in ("http", "https")
                or uri.username is not None or uri.password is not None or len(labels) < 2
                or any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                       for label in labels)
                or (uri.port is not None and not 1 <= uri.port <= 65535)):
            raise ValueError
    except ValueError:
        raise ValueError("نشانی وب معتبر نیست.") from None
    return normalized
