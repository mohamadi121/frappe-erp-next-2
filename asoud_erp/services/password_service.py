"""The ONE password-change service.

Used by the first-run flow (temporary password, admin profile) and by
Settings > Account > Security: both call ``change_password`` through
``api/v1/account_security.change_password``. Also used, minus the current-password check,
by account recovery and activation (``set_new_password``).

Storage: Frappe's native salted PBKDF2-SHA256 hash (``frappe.utils.password``). Argon2id would
mean replacing the framework's password context, which this extension app must not do.
"""

import frappe

from asoud_erp.services import account_state, security_audit
from asoud_erp.services.credential_policy import password_errors, rate_limit_state

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5


def _key(user: str) -> str:
    return f"asoud_pwchange_failures:{user}"


def _failures(user: str) -> list[float]:
    return list(frappe.cache.get_value(_key(user), expires=True) or [])


def _record_failure(user: str) -> None:
    import time

    now = time.time()
    recent = [t for t in _failures(user) if now - t < WINDOW_SECONDS] + [now]
    frappe.cache.set_value(_key(user), recent, expires_in_sec=WINDOW_SECONDS)


def _check_rate(user: str) -> None:
    import time

    blocked, retry = rate_limit_state(_failures(user), time.time(), WINDOW_SECONDS, MAX_FAILURES)
    if blocked:
        security_audit.record("auth.password_change", result="denied", actor=user,
                              target_type="User", target=user, details={"reason": "rate_limited"},
                              commit=True)
        frappe.throw(f"تعداد تلاش‌های ناموفق زیاد است؛ {max(1, retry // 60)} دقیقه دیگر دوباره تلاش کنید.",
                     frappe.ValidationError)


def _strength_error(new: str, user: str) -> str | None:
    """Frappe's zxcvbn score on top of our policy (score 0-1 is trivially guessable)."""
    try:
        from frappe.utils.password_strength import test_password_strength

        result = test_password_strength(new, [user])
        if (result.get("score") or 0) < 2:
            return "رمز عبور بسیار قابل حدس است؛ رمز طولانی‌تر و غیرتکراری انتخاب کنید."
    except Exception:
        return None
    return None


def validate_policy(new, repeat, *, current=None, user: str, email: str | None = None) -> None:
    errors = password_errors(new, repeat, current=current, identifiers=(user, email))
    if not errors:
        error = _strength_error(new, user)
        errors = [error] if error else []
    if errors:
        frappe.throw(errors[0], frappe.ValidationError)


def set_new_password(user: str, new: str, *, keep_current_session: bool) -> None:
    """Hash + store, flip the temp flag, invalidate every other session."""
    from frappe.sessions import clear_sessions
    from frappe.utils.password import update_password

    update_password(user, new)
    account_state.mark_password_changed(user)
    if keep_current_session and frappe.session.user == user:
        clear_sessions(user, keep_current=True, force=True)
    else:
        clear_sessions(user, keep_current=False, force=True)
    frappe.cache.delete_value(_key(user))


def change_password(current, new, repeat) -> dict:
    """Authenticated change. Raises Persian errors; never logs a password."""
    from frappe.utils.password import check_password

    user = frappe.session.user
    if user == "Guest":
        frappe.throw("ورود به حساب لازم است.", frappe.AuthenticationError)
    if not isinstance(current, str) or not current:
        frappe.throw("رمز عبور فعلی را وارد کنید.", frappe.ValidationError)
    _check_rate(user)
    try:
        check_password(user, current)
    except frappe.AuthenticationError:
        _record_failure(user)
        security_audit.record("auth.password_change", result="failure", target_type="User", target=user,
                              details={"reason": "wrong_current_password"}, commit=True)
        frappe.throw("رمز عبور فعلی درست نیست.", frappe.ValidationError)
    email = frappe.db.get_value("User", user, "email")
    validate_policy(new, repeat, current=current, user=user, email=email)
    set_new_password(user, new, keep_current_session=True)
    security_audit.record("auth.password_change", target_type="User", target=user)
    return {"changed": True, "must_change_password": False, "other_sessions_revoked": True,
            "reauthentication_required_for_saved_credentials": True}
