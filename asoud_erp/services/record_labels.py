"""Persian option labels for form record sources. Pure: no database access."""
from datetime import date, datetime, timedelta

from asoud_erp.services.digits import to_persian_digits
from asoud_erp.services.jalali import gregorian_to_jalali

SEPARATOR = " · "
ATTENDANCE_STATUS = {
    "Present": "حاضر", "Absent": "غایب", "On Leave": "مرخصی", "Half Day": "نیم‌روز", "Work From Home": "دورکاری",
}


def _parse(value):
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def jalali_date(value):
    """«۱۴۰۵/۰۷/۲۸» for a date, datetime or ISO string; '' when missing."""
    parsed = _parse(value)
    if parsed is None:
        return ""
    year, month, day = gregorian_to_jalali(parsed.date() if isinstance(parsed, datetime) else parsed)
    return to_persian_digits(f"{year:04d}/{month:02d}/{day:02d}")


def clock(value):
    """«۰۸:۰۱» from a datetime, timedelta, 'HH:MM:SS' or ISO datetime string; '' when missing."""
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        return to_persian_digits(f"{seconds // 3600 % 24:02d}:{seconds // 60 % 60:02d}")
    if isinstance(value, str) and value and "-" not in value:
        return to_persian_digits(value[:5])
    parsed = _parse(value)
    return to_persian_digits(parsed.strftime("%H:%M")) if isinstance(parsed, datetime) else ""


def attendance_label(row):
    parts = [jalali_date(row.get("attendance_date")), ATTENDANCE_STATUS.get(row.get("status"), row.get("status") or "")]
    if clock(row.get("in_time")):
        parts.append(f"ورود {clock(row['in_time'])}")
    if clock(row.get("out_time")):
        parts.append(f"خروج {clock(row['out_time'])}")
    return SEPARATOR.join(p for p in parts if p)


def shift_label(row):
    start, end = clock(row.get("start_time")), clock(row.get("end_time"))
    return SEPARATOR.join(p for p in (row["name"], f"{start} تا {end}" if start and end else "") if p)


def training_event_label(row):
    return SEPARATOR.join(p for p in (row.get("label") or row["name"], jalali_date(row.get("start_time"))) if p)


def asset_label(row):
    return f"{row.get('label') or row['name']} ({row['name']})"


LABELS = {"Attendance": attendance_label, "Shift Type": shift_label,
          "Training Event": training_event_label, "Asset": asset_label}
