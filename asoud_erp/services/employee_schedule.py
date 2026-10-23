"""Pure helpers for presenting an HRMS employee schedule."""
from datetime import date, timedelta

from asoud_erp.services.digits import to_persian_digits
from asoud_erp.services.jalali import gregorian_to_jalali

SOURCE_LABELS = {
    "assignment": "تخصیص شیفت",
    "default": "شیفت پیش‌فرض",
    "holiday": "تعطیل",
    "none": "بدون برنامه",
}
MAX_DAYS = 62


def parse_range(from_date, to_date):
    try:
        start = date.fromisoformat(str(from_date))
        end = date.fromisoformat(str(to_date))
    except (TypeError, ValueError):
        raise ValueError("بازه تاریخ معتبر نیست.") from None
    days = (end - start).days + 1
    if days < 1:
        raise ValueError("تاریخ پایان نباید قبل از تاریخ شروع باشد.")
    if days > MAX_DAYS:
        raise ValueError("بازه برنامه شیفت نمی‌تواند بیشتر از ۶۲ روز باشد.")
    return start, end, days


def date_label(value):
    year, month, day = gregorian_to_jalali(value)
    return to_persian_digits(f"{year:04d}/{month:02d}/{day:02d}")


def build_schedule(start, end, assignments, default_shift, holidays, shifts):
    """Return one effective row per day without database access."""
    result = []
    current = start
    while current <= end:
        covering = [row for row in assignments if row["start_date"] <= current <= row["end_date"]]
        assignment = covering[-1] if covering else None
        if assignment:
            shift_type, source = assignment["shift_type"], "assignment"
        elif default_shift:
            shift_type, source = default_shift, "default"
        elif current in holidays:
            shift_type, source = None, "holiday"
        else:
            shift_type, source = None, "none"
        times = shifts.get(shift_type, {}) if shift_type else {}
        result.append({
            "date": current.isoformat(),
            "date_label": date_label(current),
            "shift_type": shift_type,
            "start_time": times.get("start_time"),
            "end_time": times.get("end_time"),
            "source": source,
            "source_label": SOURCE_LABELS[source],
        })
        current += timedelta(days=1)
    return result
