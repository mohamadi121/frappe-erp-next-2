"""Void and reissue of the native document an approved request created (decision N6).

Pure rules first (no Frappe import), then the writes. Nothing is ever deleted: a submitted
document is cancelled with ERPNext/HRMS Cancel, a draft stays for HR (Frappe cannot cancel a
draft) and the request records the void.
"""

REASON_MAX = 500
VOIDED = "Voided"
# Doctypes whose submitted document is cancelled. Anything else that executors create is marked only.
CANCEL_DOCTYPES = frozenset({
    "Employee Advance", "Asset Movement", "Shift Request", "Exit Interview", "Leave Application",
    "Material Request"})
# Created by executors but never cancelled: not submittable, or shared with other people's data.
MARK_ONLY_DOCTYPES = frozenset({"Employee Checkin", "Training Event"})
ERRORS = {
    "reason": "دلیل ابطال سند را بنویسید.",
    "reason_long": "دلیل ابطال حداکثر ۵۰۰ نویسه است.",
    "not_voidable": "برای این درخواست سند اجراشده‌ای وجود ندارد که ابطال شود.",
    "doctype": "ابطال این نوع سند از این مسیر ممکن نیست.",
    "cancel_failed": "ابطال سند انجام نشد؛ اسناد وابسته به آن را بررسی کنید.",
    "not_reissuable": "صدور مجدد فقط پس از ابطال سند ممکن است.",
    "template": "صدور مجدد برای این نوع درخواست ممکن نیست.",
}


def clean_reason(reason) -> str:
    """The trimmed reason; raises ``ValueError`` with a Persian sentence."""
    text = reason.strip() if isinstance(reason, str) else ""
    if not text:
        raise ValueError(ERRORS["reason"])
    if len(text) > REASON_MAX:
        raise ValueError(ERRORS["reason_long"])
    return text


def void_plan(native_doctype: str, docstatus) -> str:
    """``cancel``, ``mark`` (record only) or ``already`` (document is cancelled / gone)."""
    if native_doctype not in CANCEL_DOCTYPES | MARK_ONLY_DOCTYPES:
        raise ValueError(ERRORS["doctype"])
    if docstatus is None or docstatus == 2:
        return "already"
    if native_doctype in CANCEL_DOCTYPES and docstatus == 1:
        return "cancel"
    return "mark"


def can_void(instance_status, native_status, native_name) -> bool:
    return instance_status == "Completed" and native_status == "Created" and bool(native_name)


def can_reissue(native_status, template_key) -> bool:
    return native_status == VOIDED and not template_key


def already_reissued(actions) -> bool:
    """``actions`` are the Voided/Reissued activity actions, oldest first."""
    return bool(actions) and actions[-1] == "Reissued"
