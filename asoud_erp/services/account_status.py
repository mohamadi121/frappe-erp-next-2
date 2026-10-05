"""Pure rules for the account operations of a personnel file (فعال/غیرفعال، دعوت، سوابق ورود).

Nothing here talks to the database: the API layer reads the native Frappe
records (``User``, ``User Permission``, ``Activity Log``, ``Sessions``) and passes
their raw values in.  The shapes here are the ones the Flutter ⋮ menu consumes.
"""

import ast
from collections.abc import Iterable

HISTORY_DEFAULT_LIMIT = 20
HISTORY_MAX_LIMIT = 50

# «ارسال مجدد دعوت» is only for an account that was created but never used.
RESEND_BLOCKED_MESSAGE = (
    "ارسال مجدد دعوت برای این حساب ممکن نیست؛ کاربر قبلاً وارد سامانه شده است. "
    "برای حساب فعال، از «بازنشانی رمز عبور» در تنظیمات کاربر استفاده کنید."
)


def can_resend_invitation(user: str | None, has_logged_in: bool) -> bool:
    """Only an existing account with no recorded login may be invited again."""
    return bool(user) and not bool(has_logged_in)


def resend_blocked_message(has_logged_in: bool) -> str:
    """The Persian refusal for «ارسال مجدد دعوت»; empty when the resend is allowed."""
    return RESEND_BLOCKED_MESSAGE if has_logged_in else ""


def allowed_modules(installed: Iterable[str] | None, blocked: Iterable[str] | None) -> list[str]:
    """Installed app modules minus the ones Frappe blocks for this user."""
    hidden = {str(module).strip() for module in blocked or () if module}
    return sorted({str(module).strip() for module in installed or () if module} - hidden)


def account_status(
    user: str | None,
    *,
    enabled: int | bool | None,
    last_login,
    last_ip,
    roles: Iterable[str] | None,
    modules: Iterable[str] | None,
    data_scope: Iterable[dict] | None,
) -> dict:
    """The ⋮ menu payload for one personnel profile's login account."""
    user = str(user or "")
    has_logged_in = bool(last_login)
    return {
        "user": user,
        "enabled": int(bool(enabled)),
        "has_logged_in": has_logged_in,
        "last_login": str(last_login or ""),
        "last_ip": str(last_ip or ""),
        "can_resend_invitation": can_resend_invitation(user, has_logged_in),
        "roles": list(roles or []),
        "modules": list(modules or []),
        "data_scope": list(data_scope or []),
    }


def _session_data(raw) -> dict:
    """The inner session dict of a ``tabSessions.sessiondata`` blob.

    Frappe stores it as a Python repr and reads it back with ``safe_eval``; only
    the device and the session IP are of interest here, so it is parsed with
    ``ast.literal_eval`` which never executes anything.
    """
    if not raw or not isinstance(raw, str):
        return {}
    try:
        parsed = ast.literal_eval(raw)
    except (MemoryError, SyntaxError, TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    inner = parsed.get("data")
    return inner if isinstance(inner, dict) else {}


def login_events(rows: Iterable[dict] | None) -> list[dict]:
    """Native ``Activity Log`` Login/Logout rows, most recent first."""
    events = [
        {
            "datetime": str(row.get("creation") or ""),
            "operation": str(row.get("operation") or ""),
            "status": str(row.get("status") or ""),
            "ip": str(row.get("ip_address") or ""),
        }
        for row in rows or []
    ]
    return sorted(events, key=lambda event: event["datetime"], reverse=True)


def session_rows(rows: Iterable[dict] | None) -> list[dict]:
    """Native ``tabSessions`` rows without the ``sid``, the cookie or the csrf token."""
    sessions = []
    for row in rows or []:
        data = _session_data(row.get("sessiondata"))
        sessions.append({
            "device": str(data.get("device") or data.get("user_agent") or ""),
            "ip": str(data.get("session_ip") or row.get("ipaddress") or ""),
            "last_active": str(row.get("lastupdate") or ""),
            "status": str(row.get("status") or ""),
        })
    return sessions


def login_history(last_login, last_ip, events, sessions) -> dict:
    """«مشاهده سوابق ورود»: last login plus the recent events and active sessions."""
    return {
        "last_login": str(last_login or ""),
        "last_ip": str(last_ip or ""),
        "events": login_events(events),
        "sessions": session_rows(sessions),
    }


def history_limit(value, default: int = HISTORY_DEFAULT_LIMIT, maximum: int = HISTORY_MAX_LIMIT) -> int:
    """The client's requested page size, clamped to a sane range."""
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, maximum))