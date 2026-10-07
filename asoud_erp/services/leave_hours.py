"""Pure hour/day maths of the leave request template (CONTRACT 3.6, 4.11, 4.12).

No ``frappe`` import: everything here is unit-tested with plain pytest. The leave
balance is money-like, so all arithmetic is exact (``Decimal`` / ``Fraction``) and
rounded half-up, never with binary floats or banker's rounding.

Rounding rules (CONTRACT 3.6 and 4.12)::

    hours          = round_half_up(minutes / 60, 2)
    day_equivalent = round_half_up(hours / daily_working_hours, 4)
    ledger leaves  = -round_half_up(hours / daily_working_hours, 6)

``hours`` is the stored two-decimal figure of ``values["duration"]``; the day
equivalent and the ledger deduction are derived from that stored figure, so a
client or auditor can reproduce both from the request alone. For quarter-hour
times (the 15-minute minimum is the natural step) the figure is exact.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

MIN_MINUTES = 15
DEFAULT_DAILY_HOURS = 8
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

CATEGORY_LABELS = {"annual": "سالانه", "sick": "استعلاجی", "unpaid": "بدون حقوق", "other": "سایر"}
#: Categories shown in the form's balance panel, in order (the mockup has no unpaid row).
PANEL_CATEGORIES = ("annual", "sick", "other")
KIND_LABELS = {"Daily": "روزانه", "Hourly": "ساعتی"}

MESSAGES = {
    "INVALID_DATE_RANGE": "تاریخ پایان نباید قبل از تاریخ شروع باشد.",
    "INVALID_TIME_RANGE": "ساعت پایان باید بعد از ساعت شروع باشد.",
    "MIN_DURATION": "حداقل مدت مرخصی ساعتی ۱۵ دقیقه است.",
    "INVALID_TIME": "ساعت باید با قالب HH:MM و به وقت ۲۴ ساعته وارد شود.",
    "LEAVE_ALL_HOLIDAYS": "روزهای انتخاب‌شده همگی تعطیل هستند و نیازی به مرخصی نیست.",
    "HOURLY_EXCEEDS_DAY": "مدت مرخصی ساعتی نمی‌تواند از ساعت کاری روزانه بیشتر باشد.",
    "HOURLY_ON_HOLIDAY": "تاریخ انتخاب‌شده برای شما تعطیل است.",
    "LEAVE_OVERLAP": "در این بازه قبلاً مرخصی ثبت یا درخواست شده است.",
    "INSUFFICIENT_LEAVE_BALANCE": "مانده مرخصی کافی نیست.",
    "DATE_IN_PAST": "ثبت مرخصی برای تاریخ گذشته مجاز نیست.",
}


class LeaveRuleError(ValueError):
    """A leave business rule failed. ``code`` is one of CONTRACT 4.15, ``field`` the form key."""

    def __init__(self, code: str, message: str | None = None, field: str | None = None):
        super().__init__(message or MESSAGES.get(code, code))
        self.code = code
        self.field = field

    @property
    def message(self) -> str:
        return str(self)


def to_decimal(value: Any) -> Decimal:
    """Exact Decimal of a number; floats go through ``str`` so 7.5 stays 7.5."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value: Any, places: int) -> float:
    """Round half away from zero at ``places`` decimals and return a float for JSON."""
    quantum = Decimal(1).scaleb(-places)
    # "+ 0.0" turns a negative zero (-0.0004 rounds to -0.000) into 0.0 so JSON never shows "-0.0".
    return float(to_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)) + 0.0


def daily_hours_value(value: Any) -> Decimal:
    """Company working hours per day; empty or non-positive falls back to the default 8."""
    try:
        hours = to_decimal(value) if value not in (None, "") else Decimal(0)
    except Exception:  # noqa: BLE001 - any junk in a custom field means "use the default"
        hours = Decimal(0)
    return hours if hours > 0 else Decimal(DEFAULT_DAILY_HOURS)


def parse_hhmm(value: Any, field: str | None = None) -> int:
    """Minutes since midnight of a 24-hour ``HH:MM`` string."""
    match = TIME_PATTERN.match(value) if isinstance(value, str) else None
    if not match:
        raise LeaveRuleError("INVALID_TIME_RANGE", MESSAGES["INVALID_TIME"], field)
    return int(match.group(1)) * 60 + int(match.group(2))


def hours_from_minutes(minutes: int) -> float:
    """Stored hours: minutes / 60 rounded to two decimals (15 min = 0.25, 20 min = 0.33)."""
    return round_half_up(Decimal(int(minutes)) / 60, 2)


def day_equivalent(hours: Any, daily_hours: Any) -> float:
    """Fraction of a working day, four decimals: 4 h at 8 h/day is 0.5, 1.5 h is 0.1875."""
    return round_half_up(to_decimal(hours) / daily_hours_value(daily_hours), 4)


def ledger_leaves(hours: Any, daily_hours: Any) -> float:
    """Negative Leave Ledger Entry amount of an hourly leave, six decimals (CONTRACT 4.12)."""
    return -round_half_up(to_decimal(hours) / daily_hours_value(daily_hours), 6)


def daily_duration(days: Any) -> dict:
    days = round_half_up(days, 1)
    return {"unit": "day", "days": days, "hours": None, "day_equivalent": days}


def hourly_duration(start_time: Any, end_time: Any, daily_hours: Any, other_minutes: int = 0) -> dict:
    """Validated hourly duration (CONTRACT 3.6).

    ``other_minutes`` is hourly leave already booked on the same date (in-flight or
    approved requests of the same employee); the total of the day must stay within
    the daily working hours. Raises ``LeaveRuleError`` with the contract code.
    """
    start = parse_hhmm(start_time, "start_time")
    end = parse_hhmm(end_time, "end_time")
    if end <= start:
        raise LeaveRuleError("INVALID_TIME_RANGE", field="end_time")
    minutes = end - start
    if minutes < MIN_MINUTES:
        raise LeaveRuleError("INVALID_TIME_RANGE", MESSAGES["MIN_DURATION"], "end_time")
    limit = daily_hours_value(daily_hours) * 60
    if Decimal(minutes) > limit:
        raise LeaveRuleError("HOURLY_EXCEEDS_DAY", field="end_time")
    if Decimal(minutes + max(int(other_minutes), 0)) > limit:
        raise LeaveRuleError(
            "HOURLY_EXCEEDS_DAY",
            "مجموع مرخصی ساعتی این روز از ساعت کاری روزانه بیشتر می‌شود.",
            "end_time",
        )
    hours = hours_from_minutes(minutes)
    return {"unit": "hour", "days": None, "hours": hours,
            "day_equivalent": day_equivalent(hours, daily_hours)}


def minutes_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    """Half-open ranges: 09:00-10:00 and 10:00-11:00 do not overlap."""
    return start_a < end_b and start_b < end_a


def duration_text(duration: dict) -> str:
    """Compact Latin-digit text used in the generated subject and notifications."""
    if duration.get("unit") == "hour":
        return f"{duration.get('hours'):g} ساعت"
    return f"{duration.get('days'):g} روز"


# ------------------------------------------------------------------ subject


def category_label(category: str | None) -> str:
    return CATEGORY_LABELS.get(category or "", CATEGORY_LABELS["other"])


def leave_subject(category: str | None, request_kind: str) -> str:
    """Server-generated subject (CONTRACT 3.6): «مرخصی سالانه (روزانه)»."""
    return f"مرخصی {category_label(category)} ({KIND_LABELS.get(request_kind, request_kind)})"


# ------------------------------------------------------------------ balance


def type_balance(*, native: dict | None, hourly_taken: Any, inflight: Any, is_lwp: bool) -> dict:
    """Balance numbers of one Leave Type (CONTRACT 4.11, all rounded to 3 decimals).

    ``native`` is HRMS ``get_leave_details(...)["leave_allocation"][leave_type]`` or
    ``None`` when the employee has no allocation::

        remaining = native.remaining_leaves - hourly_taken
        pending   = native.leaves_pending_approval + inflight
        available = remaining - pending

    ``remaining`` and ``available`` are ``None`` for leave-without-pay types.
    """
    has_allocation = bool(native)
    native = native or {}
    hourly = to_decimal(hourly_taken or 0)
    pending = to_decimal(native.get("leaves_pending_approval") or 0) + to_decimal(inflight or 0)
    remaining = to_decimal(native.get("remaining_leaves") or 0) - hourly
    result = {
        "has_allocation": has_allocation,
        "total_leaves": round_half_up(native.get("total_leaves") or 0, 3),
        "leaves_taken": round_half_up(native.get("leaves_taken") or 0, 3),
        "hourly_taken": round_half_up(hourly, 3),
        "leaves_pending": round_half_up(pending, 3),
        "remaining": round_half_up(remaining, 3),
        "available": round_half_up(remaining - pending, 3),
    }
    if is_lwp:
        result["remaining"] = None
        result["available"] = None
    return result


def category_rows(types: list[dict]) -> list[dict]:
    """Panel rows per category from ``leave_types`` rows (non-LWP types only, CONTRACT 4.11).

    ``unpaid`` is left out; annual, sick and other always appear (zeros when empty).
    """
    rows = []
    for category in PANEL_CATEGORIES:
        mine = [row for row in types if row.get("category") == category and not row.get("is_lwp")]
        remaining = sum((to_decimal(row.get("remaining") or 0) for row in mine), Decimal(0))
        available = sum((to_decimal(row.get("available") or 0) for row in mine), Decimal(0))
        pending = sum((to_decimal(row.get("leaves_pending") or 0) for row in mine), Decimal(0))
        rows.append({
            "category": category, "label": CATEGORY_LABELS[category],
            "remaining_days": round_half_up(remaining, 3),
            "available_days": round_half_up(available, 3),
            "pending_days": round_half_up(pending, 3),
        })
    return rows


def preview_balance(leave_type: str, balance: dict, requested_days: Any) -> dict:
    """The ``balance`` object of ``preview_leave_request`` (CONTRACT 4.11)."""
    requested = to_decimal(requested_days or 0)
    remaining, available = balance.get("remaining"), balance.get("available")
    return {
        "leave_type": leave_type,
        "remaining_before": remaining,
        "requested_days": round_half_up(requested, 4),
        "remaining_after": None if remaining is None else round_half_up(to_decimal(remaining) - requested, 3),
        "available_after": None if available is None else round_half_up(to_decimal(available) - requested, 3),
    }


def exceeds_available(day_eq: Any, balance: dict, *, is_lwp: bool, allow_negative: bool) -> bool:
    """True when the request needs more than ``available`` (INSUFFICIENT_LEAVE_BALANCE at create)."""
    if is_lwp or allow_negative:
        return False
    return to_decimal(day_eq) > to_decimal(balance.get("available") or 0)


def exceeds_remaining(day_eq: Any, balance: dict, *, is_lwp: bool, allow_negative: bool) -> bool:
    """Final-approval re-check: ``day_equivalent <= remaining`` without its own reservation."""
    if is_lwp or allow_negative:
        return False
    return to_decimal(day_eq) > to_decimal(balance.get("remaining") or 0)


def overlay_insufficient(consumption: Any, hourly_taken: Any, total_leave_days: Any) -> bool:
    """Leave Application validate overlay (CONTRACT 4.12).

    ``consumption`` is HRMS ``leave_balance_for_consumption``. Hourly leave is not
    visible to it, so a full-day application fails when
    ``consumption - hourly_taken < total_leave_days``.
    """
    remaining = to_decimal(consumption or 0) - to_decimal(hourly_taken or 0)
    return round_half_up(remaining, 3) < round_half_up(total_leave_days or 0, 3)
