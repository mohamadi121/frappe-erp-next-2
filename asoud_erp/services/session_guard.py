"""Server-side enforcement of «تغییر اجباری رمز موقت».

A signed-in account flagged ``must_change_password`` (temporary password issued by an
administrator or HR) may call only the endpoints needed to change the password and to
sign out. Every other API call is refused by the server, not merely hidden by the app.
"""

import frappe

ALLOWED_METHODS = frozenset({
    "asoud_erp.api.v1.session.login_state",
    "asoud_erp.api.v1.session.logout",
    "asoud_erp.api.v1.account_security.change_password",
    "login",
    "logout",
    "frappe.auth.get_logged_user",
    "frappe.ping",
    "ping",
})
MESSAGE = "رمز عبور موقت شما باید ابتدا تغییر کند؛ پیش از ادامه رمز جدید تعیین کنید."


def method_of(path: str) -> str | None:
    marker = "/api/method/"
    if marker not in (path or ""):
        return None
    return path.split(marker, 1)[1].strip("/").split("?", 1)[0]


def blocked(path: str, must_change: bool) -> bool:
    method = method_of(path)
    return bool(must_change and method is not None and method not in ALLOWED_METHODS)


def enforce_password_change() -> None:
    request = getattr(frappe.local, "request", None)
    user = getattr(getattr(frappe.local, "session", None), "user", None)
    if not request or not user or user in {"Guest", "Administrator"}:
        return
    if method_of(request.path) is None:
        return
    try:
        from asoud_erp.services import account_state

        must_change = account_state.must_change_password(user)
    except Exception:
        # Before the first migrate the state table does not exist; never lock the site out.
        return
    if blocked(request.path, must_change):
        frappe.throw(MESSAGE, frappe.PermissionError)


def on_login(login_manager=None) -> None:
    """An expired temporary password must not open a session."""
    user = getattr(login_manager, "user", None)
    if not user or user in {"Guest", "Administrator"}:
        return
    try:
        from asoud_erp.services import account_state

        expired = account_state.temp_password_expired(user)
    except Exception:
        return
    if expired:
        from asoud_erp.services import security_audit

        security_audit.record("auth.login", result="denied", actor=user,
                              details={"reason": "temporary_password_expired"}, commit=True)
        frappe.throw("رمز موقت منقضی شده است؛ از مسئول منابع انسانی یا مدیر سیستم رمز جدید بخواهید.",
                     frappe.AuthenticationError)
