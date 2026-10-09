"""Request status model: one stored `status_key` mirrored from the workflow instance.

Pure functions only. `compute_status_key` maps the instance state to the key; the
lifecycle hook stores it, the list filters on it and the clients render the label.
"""

from __future__ import annotations

STATUS_LABELS = {
    "submitted": "ارسال شده",
    "in_review": "در حال بررسی",
    "returned": "برگشت برای اصلاح",
    "failed": "نیازمند بررسی",
    "approved": "تأیید شده",
    "rejected": "رد شده",
    "cancelled": "لغو شده",
    "draft": "پیش‌نویس",
}
# Tab of the request list; `cancelled` and `draft` appear only under "all".
STATUS_GROUPS = {
    "submitted": "pending",
    "in_review": "pending",
    "returned": "pending",
    "failed": "pending",
    "approved": "approved",
    "rejected": "rejected",
    "cancelled": "",
    "draft": "",
}
GROUP_NAMES = ("pending", "approved", "rejected")
PRIORITY_LABELS = {"Low": "کم", "Normal": "عادی", "High": "مهم", "Urgent": "فوری"}

_INSTANCE_STATUS_KEYS = {
    "Failed": "failed",
    "Completed": "approved",
    "Rejected": "rejected",
    "Cancelled": "cancelled",
}
_REQUEST_STATUS_KEYS = {
    "Draft": "draft",
    "Completed": "approved",
    "Rejected": "rejected",
    "Cancelled": "cancelled",
}


def compute_status_key(
    instance_status: str | None,
    request_status: str | None = None,
    *,
    at_form_stage: bool = False,
    form_submitted: bool = False,
    non_form_acted: bool = False,
) -> str:
    """The status key of a request.

    `instance_status` is the workflow instance status (None without an instance, then
    the legacy request `status` decides). For a running instance: `returned` when it is
    back at the form stage after the form was submitted, `in_review` once a non-form
    task was completed or rejected, otherwise `submitted`.
    """
    if not instance_status:
        return _REQUEST_STATUS_KEYS.get(request_status or "", "submitted")
    if instance_status in _INSTANCE_STATUS_KEYS:
        return _INSTANCE_STATUS_KEYS[instance_status]
    if at_form_stage and form_submitted:
        return "returned"
    return "in_review" if non_form_acted else "submitted"


def status_group(status_key: str | None) -> str:
    """The list tab of a status key (empty when it only appears under "all")."""
    return STATUS_GROUPS.get(status_key or "", "")


def group_keys(group: str | None) -> list[str]:
    """The status keys behind a tab; empty for "all" and unknown groups."""
    return [key for key, value in STATUS_GROUPS.items() if group in GROUP_NAMES and value == group]


def status_label(status_key: str | None, display_status: str | None = None,
                 instance_status: str | None = None) -> str:
    """The label shown to users; a running instance may carry a custom display status."""
    custom = (display_status or "").strip()
    if custom and instance_status == "Running":
        return custom
    return STATUS_LABELS.get(status_key or "", STATUS_LABELS["submitted"])


def priority_label(priority: str | None) -> str:
    return PRIORITY_LABELS.get(priority or "", priority or "")


def tab_counts(by_status_key: dict[str, int]) -> dict[str, int]:
    """`meta.counts` of the list from per-status-key row counts."""
    counts = {"all": sum(by_status_key.values()), **{name: 0 for name in GROUP_NAMES}}
    for key, number in by_status_key.items():
        group = status_group(key)
        if group:
            counts[group] += number
    return counts
