"""Append-only security audit trail (ASOUD Security Audit).

Every row carries actor, action, time, source and result. Secrets never enter it:
``redact`` drops any key that looks like a password/token/secret and truncates values,
and callers pass identifiers, never credentials.
"""

import json
import re

SECRET_KEY = re.compile(r"pass(word|wd)?|pwd|token|secret|otp|code_hash|salt|authorization|api_key|sid|cookie|csrf",
                        re.IGNORECASE)
MAX_VALUE = 500
MAX_DEPTH = 4

RESULTS = ("success", "failure", "denied")


def redact(value, depth: int = 0):
    """A JSON-safe copy of ``value`` without secret-looking keys and with bounded size."""
    if depth > MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        return {str(k)[:80]: ("[حذف‌شده]" if SECRET_KEY.search(str(k)) else redact(v, depth + 1))
                for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set)):
        return [redact(v, depth + 1) for v in list(value)[:50]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "…"


def build_row(*, actor, action, result="success", source="", target_type="", target="", company="",
              details=None, occurred_on=None) -> dict:
    if result not in RESULTS:
        raise ValueError("invalid audit result")
    return {
        "doctype": "ASOUD Security Audit",
        "occurred_on": occurred_on,
        "actor": str(actor or "")[:140],
        "action": str(action)[:140],
        "result": result,
        "source": str(source or "")[:300],
        "target_type": str(target_type or "")[:140],
        "target": str(target or "")[:140],
        "company": str(company or "")[:140],
        "details": json.dumps(redact(details or {}), ensure_ascii=False),
    }


def request_source() -> str:
    """``ip | method`` of the current request, empty outside a request."""
    import frappe

    parts = []
    ip = getattr(frappe.local, "request_ip", None)
    if ip:
        parts.append(str(ip))
    form = getattr(frappe.local, "form_dict", None) or {}
    cmd = form.get("cmd") if hasattr(form, "get") else None
    if cmd:
        parts.append(str(cmd))
    return " | ".join(parts)


def record(action, *, result="success", actor=None, target_type="", target="", company="",
           details=None, source=None, commit=False) -> None:
    """Write one audit row. Never raises into the caller's business flow.

    ``commit=True`` is for failures/denials where the caller is about to raise (which
    rolls the transaction back); the row is kept.
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        row = build_row(
            actor=actor if actor is not None else frappe.session.user, action=action, result=result,
            source=source if source is not None else request_source(), target_type=target_type,
            target=target, company=company, details=details, occurred_on=now_datetime())
        frappe.get_doc(row).insert(ignore_permissions=True)
        if commit and not frappe.flags.in_test:
            # keeps the row when the caller is about to raise (which rolls the request back)
            frappe.db.commit()
    except Exception:
        frappe.log_error(title="ASOUD Security Audit write failed")
