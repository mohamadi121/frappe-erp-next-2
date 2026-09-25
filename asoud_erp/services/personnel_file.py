"""Pure rules of the personnel file (no Frappe imports): validity, tenure, states."""

from datetime import date

EXPIRY_WARNING_DAYS = 30

PROMOTION_FIELDS = {"designation": "Designation", "department": "Department", "branch": "Branch"}

HISTORY_TITLES = {
    "joining": "استخدام",
    "internal": "سابقه سازمانی",
    "promotion": "ارتقا یا تغییر سمت",
    "transfer": "انتقال",
    "contract": "قرارداد",
    "salary": "تعیین حقوق",
    "relieving": "پایان همکاری",
}


def as_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def document_status(expiry, today: date) -> str:
    """``no_expiry``, ``expired``, ``expiring`` (within 30 days) or ``valid``."""
    end = as_date(expiry)
    if end is None:
        return "no_expiry"
    if end < today:
        return "expired"
    if (end - today).days <= EXPIRY_WARNING_DAYS:
        return "expiring"
    return "valid"


def service_length(joining, today: date, until=None) -> dict | None:
    """Whole years and months of service up to ``until`` (relieving) or today."""
    start = as_date(joining)
    if start is None:
        return None
    end = min(as_date(until) or today, today)
    if end < start:
        return {"years": 0, "months": 0, "days": 0}
    months = (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)
    return {"years": months // 12, "months": months % 12, "days": (end - start).days}


def contract_state(start, end, docstatus: int, is_signed: bool, today: date) -> str:
    """``draft``, ``cancelled``, ``unsigned``, ``upcoming``, ``active`` or ``expired``."""
    if docstatus == 2:
        return "cancelled"
    if docstatus == 0:
        return "draft"
    if not is_signed:
        return "unsigned"
    begin, finish = as_date(start), as_date(end)
    if begin and begin > today:
        return "upcoming"
    if finish and finish < today:
        return "expired"
    return "active"


def days_remaining(end, today: date) -> int | None:
    finish = as_date(end)
    return None if finish is None else (finish - today).days


def sort_history(events: list[dict]) -> list[dict]:
    """Newest first; undated events last."""
    return sorted(events, key=lambda row: (row.get("date") or "", row.get("order", 0)), reverse=True)


def promotion_rows(employee_values: dict, changes: dict) -> list[dict]:
    """Employee Property History rows for the fields that actually change."""
    unknown = set(changes) - set(PROMOTION_FIELDS)
    if unknown:
        raise ValueError("Only designation, department and branch can be changed by a promotion")
    rows = []
    for field, label in PROMOTION_FIELDS.items():
        new = str(changes.get(field) or "").strip()
        current = str(employee_values.get(field) or "")
        if new and new != current:
            rows.append({"property": label, "fieldname": field, "current": current, "new": new})
    if not rows:
        raise ValueError("The promotion does not change anything")
    return rows
