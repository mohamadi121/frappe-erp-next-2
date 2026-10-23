"""Submit an HRMS Attendance Request (On Duty); conflicts with holidays, leave or attendance go to HR."""

from datetime import date, timedelta

KIND = 'mission'
LABEL = 'درخواست مأموریت'
PARAMETERS = {
    'from_date': {'label': 'تاریخ شروع', 'types': ['Date'], 'required': True},
    'to_date': {'label': 'تاریخ پایان', 'types': ['Date'], 'required': True},
    'half_day': {'label': 'نیم‌روز', 'types': ['Boolean', 'Checkbox'], 'required': False},
    'half_day_date': {'label': 'تاریخ نیم‌روز', 'types': ['Date'], 'required': False},
    'shift': {'label': 'شیفت مرتبط', 'types': ['Link'], 'required': False},
    'destination': {'label': 'مقصد مأموریت', 'types': ['Text'], 'required': True},
    'purpose': {'label': 'هدف مأموریت', 'types': ['Text', 'LongText'], 'required': True},
    'notes': {'label': 'توضیحات تکمیلی', 'types': ['Text', 'LongText'], 'required': False},
}
SAVEPOINT = 'mission_execution'
REASON = 'On Duty'
SHIFT_NOT_ALLOWED = 'شیفت انتخاب‌شده برای این پرسنل در بازه مأموریت مجاز نیست.'
INCOMPLETE = 'ثبت حضور مأموریت کامل نشد؛ بازه و شیفت را بررسی کنید.'
NATIVE_ERROR = 'ثبت مأموریت انجام نشد؛ بازه، شیفت و حضور ثبت‌شده را بررسی کنید.'


def build(params: dict, ctx: dict) -> dict:
    """The draft Attendance Request; ``reason`` and ``include_holidays`` are fixed here."""
    from . import period

    if not isinstance(params, dict):
        raise ValueError('اطلاعات درخواست مأموریت معتبر نیست.')
    company, employee = period.context(ctx)
    destination = period.clean_text(params.get('destination'), 'مقصد و هدف مأموریت را وارد کنید.', 250,
                                    required=True, too_long='مقصد مأموریت حداکثر ۲۵۰ نویسه است.')
    purpose = period.clean_text(params.get('purpose'), 'مقصد و هدف مأموریت را وارد کنید.', required=True,
                                too_long='هدف مأموریت حداکثر ۲۰۰۰ نویسه است.')
    notes = period.clean_text(params.get('notes'), 'توضیحات مأموریت باید متن باشد.',
                              too_long='توضیحات مأموریت حداکثر ۲۰۰۰ نویسه است.')
    start, end, half, half_date = period.date_range(params, 'مأموریت')
    shift = params.get('shift')
    if shift is not None and not isinstance(shift, str):
        raise ValueError('شیفت انتخاب‌شده معتبر نیست.')
    lines = [f'مقصد: {destination}', f'هدف: {purpose}'] + ([f'توضیحات: {notes}'] if notes else [])
    return {
        'doctype': 'Attendance Request', 'employee': employee, 'company': company, 'from_date': start,
        'to_date': end, 'half_day': half, 'half_day_date': half_date, 'reason': REASON,
        'include_holidays': 0, 'shift': (shift or '').strip() or None, 'explanation': '\n'.join(lines),
        'docstatus': 0,
    }


def conflict_days(start: str, end: str, holidays, attendance, leaves) -> list[str]:
    """Days of the range that a holiday, an Attendance or a leave already occupies (sorted ISO)."""
    taken = set(holidays) | set(attendance) | set(leaves)
    day, last, found = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= last:
        if day.isoformat() in taken:
            found.append(day.isoformat())
        day += timedelta(days=1)
    return found


def review_reason(days: list[str]) -> str:
    from asoud_erp.services.record_labels import jalali_date

    shown = '، '.join(jalali_date(value) for value in days[:10]) + (' و …' if len(days) > 10 else '')
    return ('نیاز به اقدام HR؛ بازه مأموریت با تعطیلی، مرخصی یا حضور ثبت‌شده تعارض دارد '
            f'({shown}).')


def _spread(rows, start: str, end: str) -> set[str]:
    """Every ISO day of the range covered by ``(from_date, to_date)`` rows."""
    low, high, found = date.fromisoformat(start), date.fromisoformat(end), set()
    for first, last in rows:
        day, stop = max(low, first), min(high, last)
        while day <= stop:
            found.add(day.isoformat())
            day += timedelta(days=1)
    return found


def _allowed_shifts(employee: str, start: str, end: str) -> set[str]:
    import frappe

    assignments = frappe.get_all('Shift Assignment', filters={
        'employee': employee, 'docstatus': 1, 'status': 'Active', 'start_date': ['<=', start]},
        or_filters=[['end_date', '>=', end], ['end_date', 'is', 'not set']],
        pluck='shift_type', limit_page_length=0)
    default = frappe.db.get_value('Employee', employee, 'default_shift')
    return set(assignments) | ({default} if default else set())


def apply(request, params: dict):
    import frappe
    from frappe.utils import nowdate

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    from . import period

    filters = {'user_id': request.owner, 'company': request.company}
    if request.get('requester_employee'):
        filters['name'] = request.requester_employee
    employee = period.lock_employee(filters)
    payload = build(params, {'company': request.company, 'employee': employee, 'today': nowdate()})
    start, end = payload['from_date'], payload['to_date']
    if payload['shift'] and payload['shift'] not in _allowed_shifts(employee, start, end):
        raise ValueError(SHIFT_NOT_ALLOWED)
    from hrms.hr.utils import get_holiday_dates_for_employee

    holidays = {str(value) for value in get_holiday_dates_for_employee(employee, start, end)}
    attendance = {str(value) for value in frappe.get_all('Attendance', filters={
        'employee': employee, 'docstatus': ['!=', 2], 'attendance_date': ['between', [start, end]]},
        pluck='attendance_date', limit_page_length=0)}
    leaves = _spread(((row.from_date, row.to_date) for row in frappe.get_all('Leave Application', filters={
        'employee': employee, 'docstatus': ['<', 2], 'status': ['in', ['Open', 'Approved']],
        'from_date': ['<=', end], 'to_date': ['>=', start]}, fields=['from_date', 'to_date'],
        limit_page_length=0)), start, end)
    requests = _spread(((row.from_date, row.to_date) for row in frappe.get_all('Attendance Request', filters={
        'employee': employee, 'docstatus': ['<', 2], 'from_date': ['<=', end], 'to_date': ['>=', start]},
        fields=['from_date', 'to_date'], limit_page_length=0)), start, end)
    days = conflict_days(start, end, holidays, attendance | requests, leaves)
    if days:
        return NativeResult(status='needs_review', reason=review_reason(days))
    frappe.db.savepoint(SAVEPOINT)
    try:
        with as_administrator():
            doc = frappe.get_doc(payload).insert(ignore_permissions=True)
            doc.submit()
            created = frappe.db.count('Attendance', {'employee': employee, 'attendance_request': doc.name,
                                                     'docstatus': 1})
            if created != (date.fromisoformat(end) - date.fromisoformat(start)).days + 1:
                raise ValueError(INCOMPLETE)
            doc.add_comment('Comment', f'ایجاد‌شده از درخواست {request.name}')
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except (frappe.ValidationError, ValueError) as error:
        frappe.db.rollback(save_point=SAVEPOINT)
        frappe.clear_messages()
        if isinstance(error, ValueError):
            raise
        raise ValueError(NATIVE_ERROR) from None
    return NativeResult(status='Created', doctype=doc.doctype, name=doc.name)
