"""Execution lane of a request: what happened after the approval, kept apart from `status_key`.

Pure functions. The state is computed from the workflow instance status and the native
document result (`native_status`) that the request already stores; nothing is stored here.
An approval alone is never reported as done.
"""

from __future__ import annotations

import json

LABELS = {
    "not_applicable": "",
    "not_started": "تأیید شده، اجرا انجام نشده",
    "awaiting_approval": "اجرا پس از تأیید نهایی انجام می‌شود",
    "pending": "در انتظار اجرا",
    "succeeded": "اجرا انجام شد",
    "failed": "اجرا ناموفق بود؛ درخواست تأیید شده است",
    "needs_review": "نیازمند بررسی",
    "not_connected": "اجرای خودکار برای این نوع درخواست متصل نیست",
}
_NATIVE_STATES = {"Pending": "pending", "Created": "succeeded", "Failed": "failed", "Skipped": "not_connected"}
_CLOSED_WITHOUT_APPROVAL = ("Rejected", "Cancelled")


def _state(instance_status, native_status, has_execution) -> tuple[str, str]:
    """`(state, label_key)`; the label key differs from the state only before the approval."""
    if not instance_status or instance_status in _CLOSED_WITHOUT_APPROVAL:
        return "not_applicable", "not_applicable"
    if instance_status == "Failed":
        return "needs_review", "needs_review"
    if instance_status == "Completed" and native_status in _NATIVE_STATES:
        state = _NATIVE_STATES[native_status]
        return state, state
    if not has_execution:
        return "not_applicable", "not_applicable"
    if instance_status == "Completed":
        return "not_started", "not_started"
    return "not_started", "awaiting_approval"


def build_execution(instance_status, native_status, *, has_execution=False, error="", privileged=False,
                    reference="", executed_on="", executed_by_name="") -> dict:
    """The `execution` block of `get_request`.

    `error` is returned only to privileged users and only for a failed execution; the
    reference and the who/when only for a succeeded one.
    """
    state, label = _state(instance_status, native_status or "", has_execution)
    done = state == "succeeded"
    return {
        "state": state, "label": LABELS[label],
        "error": (error or "") if state == "failed" and privileged else "",
        "executed_on": str(executed_on or "") if done else "",
        "executed_by_name": (executed_by_name or "") if done else "",
        "reference": (reference or "") if done else "",
    }


def activity_change(raw) -> dict:
    """`{before, after, labels}` of an activity from its stored JSON; empty dicts when absent or broken.

    `labels` maps a changed key to its field label, so a client without the form can show it.
    """
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        value = {}
    value = value if isinstance(value, dict) else {}
    return {key: value[key] if isinstance(value.get(key), dict) else {} for key in ("before", "after", "labels")}
