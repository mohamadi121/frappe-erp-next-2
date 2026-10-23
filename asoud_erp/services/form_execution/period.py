"""Pure validators shared by the leave, mission and overtime executors (no Frappe import)."""

import re
from datetime import date

NO_EMPLOYEE = 'پرونده پرسنلی درخواست‌دهنده ثبت نشده است.'
NO_COMPANY = 'شرکت درخواست مشخص نشده است.'
TEXT_LIMIT = 2000


def context(ctx) -> tuple[str, str]:
    """Company and employee of the request, or a Persian ``ValueError``."""
    if not isinstance(ctx, dict):
        raise ValueError(NO_COMPANY)
    if not isinstance(ctx.get('company'), str) or not ctx['company'].strip():
        raise ValueError(NO_COMPANY)
    if not isinstance(ctx.get('employee'), str) or not ctx['employee'].strip():
        raise ValueError(NO_EMPLOYEE)
    return ctx['company'], ctx['employee']


def day(value, message: str) -> str:
    """ISO ``YYYY-MM-DD`` back unchanged, otherwise ``ValueError(message)``."""
    try:
        if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(message) from None
    return value


def flag(value, message: str) -> int:
    """0/1 from a bool, 0/1 or an empty value; anything else is an error."""
    if value is None or value == '':
        return 0
    if isinstance(value, bool) or (isinstance(value, int) and value in (0, 1)):
        return int(value)
    raise ValueError(message)


def clean_text(value, message: str, limit: int = TEXT_LIMIT, *, required: bool = False,
               too_long: str | None = None) -> str | None:
    """Trimmed text or ``None``; a non-string is rejected with ``message``."""
    if value is None or isinstance(value, str) and not value.strip():
        if required:
            raise ValueError(message)
        return None
    if not isinstance(value, str):
        raise ValueError(message)
    value = value.strip()
    if len(value) > limit:
        raise ValueError(too_long or message)
    return value


def date_range(params: dict, label: str) -> tuple[str, str, int, str | None]:
    """``(from, to, half_day, half_day_date)`` with the half day inside the range."""
    start = day(params.get('from_date'), f'تاریخ شروع {label} معتبر نیست.')
    end = day(params.get('to_date'), f'تاریخ پایان {label} معتبر نیست.')
    if end < start:
        raise ValueError('تاریخ پایان نباید پیش از تاریخ شروع باشد.')
    half = flag(params.get('half_day'), 'گزینه نیم‌روز باید بله یا خیر باشد.')
    if not half:
        return start, end, 0, None
    if start == end:
        return start, end, 1, start
    raw = params.get('half_day_date')
    if raw is None or isinstance(raw, str) and not raw.strip():
        raise ValueError('تاریخ نیم‌روز را مشخص کنید.')
    half_day = day(raw, 'تاریخ نیم‌روز باید در بازه درخواست باشد.')
    if not start <= half_day <= end:
        raise ValueError('تاریخ نیم‌روز باید در بازه درخواست باشد.')
    return start, end, 1, half_day


CLOCK = re.compile(r'[0-9]{2}:[0-9]{2}(:[0-9]{2})?')


def clock_minutes(value, message: str) -> int:
    """Minutes after midnight of ``HH:MM[:SS]``."""
    if not isinstance(value, str) or not CLOCK.fullmatch(value):
        raise ValueError(message)
    hours, minutes = int(value[:2]), int(value[3:5])
    seconds = int(value[6:8]) if len(value) == 8 else 0
    if hours > 23 or minutes > 59 or seconds > 59:
        raise ValueError(message)
    return hours * 60 + minutes


def lock_employee(filters: dict) -> str:
    """Name of the requester's active Employee, row-locked so two approvals of one person serialise."""
    import frappe

    row = frappe.db.get_value('Employee', {**filters, 'status': 'Active'}, ['name'], as_dict=True, for_update=True)
    if row:
        return row.name
    if frappe.db.exists('Employee', {**filters, 'status': ['!=', 'Active']}):
        raise ValueError('پرونده پرسنلی درخواست‌دهنده فعال نیست.')
    raise ValueError(NO_EMPLOYEE)
