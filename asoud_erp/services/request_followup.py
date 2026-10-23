"""Follow-up tasks a native document leaves behind after a request is approved (N6).

Pure rules only (no Frappe import, so they are covered by plain pytest). The database work lives in
``request_followup_runtime``. Documented in ``docs/api/form-execution.md``.
"""

import json

CONFIRM_RECEIPT = "confirm_receipt"
KINDS = {CONFIRM_RECEIPT: {"doctype": "Asset Movement", "title": "تأیید دریافت تجهیز"}}
REASON_LIMIT = 500
MARKER = "followup"
ACTIVITY_TYPE = {CONFIRM_RECEIPT: "ConfirmReceipt"}
_CLOSED = {
    "Completed": "دریافت این تجهیز قبلاً تأیید شده است.",
    "Rejected": "عدم دریافت این تجهیز قبلاً ثبت شده است.",
    "Cancelled": "جابه‌جایی این تجهیز لغو شده است و دریافت آن قابل تأیید نیست.",
}


def followup_of(draft_json) -> dict | None:
    """The server-written marker of a task's ``draft_json``, or None for an ordinary task."""
    try:
        value = json.loads(draft_json) if isinstance(draft_json, str) and draft_json.strip() else None
    except ValueError:
        return None
    marker = value.get(MARKER) if isinstance(value, dict) else None
    if not isinstance(marker, dict) or marker.get("kind") not in KINDS:
        return None
    return marker


def normalize(raw, owner: str) -> dict:
    """Validates what an executor returned as ``followup`` and keeps only the stored keys."""
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        raise ValueError("نوع اقدام پس از اجرا معتبر نیست.")
    kind = raw["kind"]
    name = raw.get("name")
    if raw.get("doctype") != KINDS[kind]["doctype"] or not isinstance(name, str) or not name.strip():
        raise ValueError("سند اقدام پس از اجرا مشخص نیست.")
    if not owner or raw.get("assignee") != owner:
        raise ValueError("اقدام پس از اجرا باید برای درخواست‌دهنده ثبت شود.")
    subject = raw.get("subject")
    return {"kind": kind, "doctype": raw["doctype"], "name": name.strip(),
            "subject": subject.strip() if isinstance(subject, str) else ""}


def task_title(marker: dict) -> str:
    title = KINDS[marker["kind"]]["title"]
    subject = (marker.get("subject") or "").strip()
    return f"{title}: {subject}"[:140] if subject else title


def clean_reason(reason) -> str:
    text = reason.strip() if isinstance(reason, str) else ""
    if not text:
        raise ValueError("علت عدم دریافت را بنویسید.")
    if len(text) > REASON_LIMIT:
        raise ValueError("علت عدم دریافت نباید بیشتر از ۵۰۰ نویسه باشد.")
    return text


def closed_message(status: str) -> str | None:
    """The refusal for a task that is no longer open (None while it is open)."""
    return _CLOSED.get(status)
