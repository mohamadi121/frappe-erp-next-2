"""Pure rules for identity data and passwords (no site needed).

One place for the mobile / national-id / email / password policy so the first-run
admin form, Settings > Account > Security, account recovery and HR onboarding agree.
"""

import re

from asoud_erp.services.digits import to_ascii_digits
from asoud_erp.services.party_validation import is_valid_iranian_national_code

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_MOBILE = re.compile(r"^(?:\+98|0098|98|0)?(9\d{9})$")


def normalize_mobile(value) -> str | None:
    """``09xxxxxxxxx`` from any accepted Iranian spelling (Persian digits, +98, spaces); None if empty.

    Raises ``ValueError`` with a Persian message when the value is not a mobile number.
    """
    text = to_ascii_digits(str(value or "")).strip()
    text = re.sub(r"[\s\-()]", "", text)
    if not text:
        return None
    match = _MOBILE.match(text)
    if not match:
        raise ValueError("شماره موبایل معتبر نیست؛ مثال: ۰۹۱۲۳۴۵۶۷۸۹")
    return "0" + match.group(1)


def normalize_national_id(value) -> str | None:
    text = re.sub(r"[\s\-]", "", to_ascii_digits(str(value or "")).strip())
    if not text:
        return None
    if not re.fullmatch(r"\d{10}", text) or not is_valid_iranian_national_code(text):
        raise ValueError("کد ملی معتبر نیست؛ کد ملی ۱۰ رقمی با رقم کنترل صحیح وارد کنید.")
    return text


def normalize_email(value) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if len(text) > 140 or not _EMAIL.match(text):
        raise ValueError("قالب ایمیل معتبر نیست.")
    return text


def clean_name(value, label: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        raise ValueError(f"{label} الزامی است.")
    if len(text) > 60 or re.search(r"[<>{}\[\]\\/@#$%^*=+|~`0-9۰-۹٠-٩]", text):
        raise ValueError(f"{label} معتبر نیست.")
    return text


def password_errors(new, repeat=None, *, current=None, identifiers=()) -> list[str]:
    """Persian reasons the new password is refused; empty list means acceptable."""
    errors: list[str] = []
    new = new if isinstance(new, str) else ""
    if repeat is not None and new != repeat:
        errors.append("رمز جدید و تکرار آن یکسان نیستند.")
    if len(new) < MIN_PASSWORD_LENGTH:
        errors.append(f"رمز عبور باید دست‌کم {MIN_PASSWORD_LENGTH} نویسه باشد.")
    if len(new) > MAX_PASSWORD_LENGTH:
        errors.append(f"رمز عبور حداکثر {MAX_PASSWORD_LENGTH} نویسه می‌تواند باشد.")
    if current is not None and new == current:
        errors.append("رمز جدید نباید با رمز فعلی یکسان باشد.")
    if new and len(set(new)) < 4:
        errors.append("رمز عبور بیش از حد ساده است.")
    lowered = new.lower()
    for ident in identifiers:
        part = str(ident or "").split("@")[0].lower()
        if len(part) >= 4 and part in lowered:
            errors.append("رمز عبور نباید شامل نام کاربری یا ایمیل باشد.")
            break
    return errors


def rate_limit_state(timestamps, now: float, window: float, limit: int) -> tuple[bool, int]:
    """(blocked, retry_after_seconds) for failures at ``timestamps`` inside a sliding window."""
    recent = sorted(t for t in timestamps if now - t < window)
    if len(recent) < limit:
        return False, 0
    oldest_relevant = recent[-limit]
    return True, max(1, int(oldest_relevant + window - now) + 1)
