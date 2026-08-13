from __future__ import annotations

REPORT_STATUSES = {"Draft", "Submitted", "Under Review", "Approved", "Returned", "Archived"}
COMMUNICATION_TYPES = {"Internal Letter", "Request", "Announcement", "Report", "Directive", "Suggestion"}
PRIORITIES = {"Low", "Medium", "High", "Urgent"}


def normalize_report_payload(payload: dict) -> dict:
    activities = []
    for raw in payload.get("activities") or []:
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        minutes = max(0, int(raw.get("duration_minutes") or 0))
        activities.append(
            {
                "title": title,
                "description": str(raw.get("description") or "").strip(),
                "duration_minutes": minutes,
                "progress": min(100, max(0, int(raw.get("progress") or 0))),
                "output": str(raw.get("output") or "").strip(),
                "blocker": str(raw.get("blocker") or "").strip(),
            }
        )
    if not activities:
        raise ValueError("At least one activity is required")
    return {**payload, "activities": activities}


def normalize_communication_payload(payload: dict) -> dict:
    subject = str(payload.get("subject") or "").strip()
    content = str(payload.get("content") or "").strip()
    recipients = sorted({str(value).strip() for value in payload.get("recipients") or [] if str(value).strip()})
    if not subject or not content or not recipients:
        raise ValueError("Subject, content and at least one recipient are required")
    kind = str(payload.get("communication_type") or "Internal Letter")
    priority = str(payload.get("priority") or "Medium")
    if kind not in COMMUNICATION_TYPES or priority not in PRIORITIES:
        raise ValueError("Communication type or priority is invalid")
    return {**payload, "subject": subject, "content": content, "recipients": recipients, "communication_type": kind, "priority": priority}

