"""Forgot-password and invitation activation: real, expiring, attempt-limited one-time codes.

The code is e-mailed to the account's address (requires an outgoing Email Account;
``recovery_available`` tells the app whether the «فراموشی رمز» link may be shown). The request
endpoint answers identically whether or not the account exists, so it cannot be used to
enumerate accounts.
"""

import time

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from asoud_erp.services import password_service, security_audit, token_codes
from asoud_erp.services.credential_policy import rate_limit_state

TTL_MINUTES = {"password_reset": 30, "activation": 72 * 60}
REQUEST_WINDOW = 60 * 60
REQUEST_LIMIT = 5
GENERIC_INVALID = "کد نامعتبر یا منقضی شده است؛ در صورت نیاز کد جدید درخواست کنید."


def recovery_available() -> bool:
    return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1}))


def find_user(identifier) -> str | None:
    """Account by user id / email (case-insensitive) or mobile; disabled and non-system users are skipped."""
    from asoud_erp.services.credential_policy import normalize_mobile

    text = str(identifier or "").strip()
    if not text or len(text) > 140:
        return None
    candidates = [text, text.lower()]
    names = frappe.get_all("User", filters={"name": ["in", candidates]}, pluck="name", limit_page_length=1)
    if not names:
        names = frappe.get_all("User", filters={"email": ["in", candidates]}, pluck="name", limit_page_length=1)
    if not names:
        try:
            mobile = normalize_mobile(text)
        except ValueError:
            mobile = None
        if mobile:
            names = frappe.get_all("User", filters={"mobile_no": mobile}, pluck="name", limit_page_length=1)
    if not names:
        return None
    row = frappe.db.get_value("User", names[0], ["enabled", "user_type"], as_dict=True)
    if not row or not row.enabled or row.user_type != "System User" or names[0] in {"Administrator", "Guest"}:
        return None
    return names[0]


def _throttle(key: str) -> bool:
    """True when this requester has exhausted the hourly budget."""
    now = time.time()
    stamps = [t for t in (frappe.cache.get_value(key) or []) if now - t < REQUEST_WINDOW]
    blocked, _ = rate_limit_state(stamps, now, REQUEST_WINDOW, REQUEST_LIMIT)
    if not blocked:
        stamps.append(now)
        frappe.cache.set_value(key, stamps, expires_in_sec=REQUEST_WINDOW)
    return blocked


def issue(user: str, purpose: str) -> str:
    """Create a fresh code, voiding earlier unused codes of the same purpose."""
    for name in frappe.get_all("ASOUD Account Token", filters={"user": user, "purpose": purpose,
                                                               "consumed_on": ["is", "not set"]}, pluck="name"):
        frappe.db.set_value("ASOUD Account Token", name, "consumed_on", now_datetime())
    code, salt = token_codes.new_code(), token_codes.new_salt()
    frappe.get_doc({
        "doctype": "ASOUD Account Token", "user": user, "purpose": purpose, "salt": salt,
        "token_hash": token_codes.hash_code(code, salt),
        "expires_on": add_to_date(now_datetime(), minutes=TTL_MINUTES[purpose]),
        "requested_from": str(getattr(frappe.local, "request_ip", "") or "")[:140],
    }).insert(ignore_permissions=True)
    return code


def consume(user: str, purpose: str, code: str) -> None:
    """Verify and burn the newest code; every failure is the same Persian message."""
    rows = frappe.get_all("ASOUD Account Token", filters={"user": user, "purpose": purpose},
                          fields=["name"], order_by="creation desc", limit_page_length=1)
    if not rows:
        frappe.throw(GENERIC_INVALID, frappe.ValidationError)
    token = frappe.get_doc("ASOUD Account Token", rows[0].name, for_update=True)
    expired = get_datetime(token.expires_on) < now_datetime()
    if not token_codes.usable(consumed=token.consumed_on, expired=expired, attempts=token.attempts or 0):
        frappe.throw(GENERIC_INVALID, frappe.ValidationError)
    if not token_codes.matches(code, token.salt, token.token_hash):
        token.attempts = (token.attempts or 0) + 1
        token.save(ignore_permissions=True)
        security_audit.record(f"auth.{purpose}", result="failure", actor=user, target_type="User",
                              target=user, details={"reason": "wrong_code"}, commit=True)
        frappe.throw(GENERIC_INVALID, frappe.ValidationError)
    token.consumed_on = now_datetime()
    token.save(ignore_permissions=True)


def request_reset(identifier) -> dict:
    """Always the same answer. Sends the code only for a real, enabled account with an e-mail address."""
    ip = str(getattr(frappe.local, "request_ip", "") or "")
    answer = {"requested": True, "expires_in_minutes": TTL_MINUTES["password_reset"]}
    if _throttle(f"asoud_recovery_ip:{ip}") or _throttle(f"asoud_recovery_id:{str(identifier or '').lower()[:140]}"):
        security_audit.record("auth.password_reset_request", result="denied", actor=str(identifier or "")[:140],
                              details={"reason": "rate_limited"}, commit=True)
        return answer
    if not recovery_available():
        security_audit.record("auth.password_reset_request", result="failure", actor=str(identifier or "")[:140],
                              details={"reason": "no_outgoing_email_account"}, commit=True)
        return answer
    user = find_user(identifier)
    email = frappe.db.get_value("User", user, "email") if user else None
    from asoud_erp.services.first_office_setup import internal_email

    if not user or not email or internal_email(email):
        security_audit.record("auth.password_reset_request", result="failure",
                              actor=str(identifier or "")[:140], details={"reason": "unknown_or_unreachable"},
                              commit=True)
        return answer
    code = issue(user, "password_reset")
    frappe.sendmail(
        recipients=[email], subject="بازیابی رمز عبور آسود",
        message=(f"<p>کد بازیابی رمز عبور شما: <b dir='ltr'>{code}</b></p>"
                 f"<p>این کد تا {TTL_MINUTES['password_reset']} دقیقه معتبر و یک‌بارمصرف است. "
                 "اگر شما درخواست نداده‌اید، این پیام را نادیده بگیرید.</p>"),
        now=True)
    security_audit.record("auth.password_reset_request", actor=user, target_type="User", target=user,
                          commit=True)
    return answer


def confirm(identifier, code, new, repeat, purpose="password_reset") -> dict:
    """Set a new password with a valid one-time code; ends every session of the account."""
    if _throttle(f"asoud_recovery_confirm:{str(identifier or '').lower()[:140]}"):
        frappe.throw("تعداد تلاش‌ها زیاد است؛ بعداً دوباره تلاش کنید.", frappe.ValidationError)
    user = find_user(identifier)
    if not user:
        frappe.throw(GENERIC_INVALID, frappe.ValidationError)
    email = frappe.db.get_value("User", user, "email")
    password_service.validate_policy(new, repeat, user=user, email=email)
    consume(user, purpose, code)
    password_service.set_new_password(user, new, keep_current_session=False)
    security_audit.record(f"auth.{purpose}_complete", actor=user, target_type="User", target=user)
    return {"changed": True, "login_required": True}
