"""Enrol the requester in a Training Event that is still a draft; submitted events go to HR."""

KIND = 'training_enrollment'
LABEL = 'ثبت‌نام در دوره آموزشی'
PARAMETERS = {
    'training_event': {'label': 'دوره آموزشی', 'types': ['Link'], 'required': True},
    'notes': {'label': 'توضیحات', 'types': ['Text', 'LongText'], 'required': False},
}
SUBMITTED_REVIEW = 'نیاز به اقدام HR؛ دوره آموزشی نهایی شده است و افزودن شرکت‌کننده باید توسط منابع انسانی انجام شود.'
NATIVE_ERROR = 'ثبت‌نام در دوره آموزشی انجام نشد؛ اطلاعات دوره را بررسی کنید.'
DUPLICATE_ERROR = 'درخواست‌دهنده قبلاً در فهرست شرکت‌کنندگان این دوره ثبت شده است.'


def _event_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('دوره آموزشی را انتخاب کنید.')
    return value.strip()


def _notes(value):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        raise ValueError('توضیحات ثبت‌نام باید متن باشد.')
    return value.strip()


def build(params: dict, ctx: dict) -> dict:
    """The participant to add; the Training Event itself is only read in ``apply``."""
    if not isinstance(params, dict) or not isinstance(ctx, dict):
        raise ValueError('اطلاعات ثبت‌نام آموزشی معتبر نیست.')
    if not isinstance(ctx.get('company'), str) or not ctx['company'].strip():
        raise ValueError('شرکت درخواست مشخص نشده است.')
    if not isinstance(ctx.get('employee'), str) or not ctx['employee'].strip():
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    return {'training_event': _event_name(params.get('training_event')),
            'employee': ctx['employee'], 'notes': _notes(params.get('notes'))}


def plan(event: dict | None, participants: list[str], employee: str, company: str) -> tuple[str, str | None]:
    """``('add', None)`` for a draft event, ``('review', reason)`` for a submitted one.

    An event without a company is accepted: HRMS does not require the field.
    """
    if not event:
        raise ValueError('دوره آموزشی انتخاب‌شده وجود ندارد.')
    if event.get('company') and event['company'] != company:
        raise ValueError('دوره آموزشی انتخاب‌شده متعلق به شرکت درخواست نیست.')
    if event.get('docstatus') == 2 or event.get('event_status') == 'Cancelled':
        raise ValueError('دوره آموزشی لغو شده است و ثبت‌نام در آن ممکن نیست.')
    if event.get('event_status') == 'Completed':
        raise ValueError('دوره آموزشی برگزار شده است و ثبت‌نام در آن ممکن نیست.')
    if employee in participants:
        raise ValueError(DUPLICATE_ERROR)
    if event.get('docstatus') == 1:
        return 'review', SUBMITTED_REVIEW
    return 'add', None


def _participants(event_name: str) -> list[str]:
    import frappe

    return [row.employee for row in frappe.get_all(
        'Training Event Employee', filters={'parent': event_name, 'parenttype': 'Training Event'},
        fields=['employee'], limit_page_length=0)]


def validate_submit(params: dict, ctx: dict) -> None:
    """Registry hook: refuses an enrolment that is already recorded; the event is re-read on approval."""
    import frappe

    values = build(params, {**ctx, 'company': ctx.get('company') or '-'})
    if frappe.db.exists('Training Event', values['training_event']) and values['employee'] in _participants(
            values['training_event']):
        raise ValueError(DUPLICATE_ERROR)


def apply(request, params: dict):
    import frappe

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    filters = {'user_id': request.owner, 'company': request.company, 'status': 'Active'}
    if request.get('requester_employee'):
        filters['name'] = request.requester_employee
    employee = frappe.db.get_value('Employee', filters, ['name', 'employee_name', 'department'], as_dict=True)
    if not employee:
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    values = build(params, {'company': request.company, 'employee': employee.name})
    # Row lock: a second approval for the same event waits here, then sees the first participant.
    rows = frappe.db.sql(
        'select name, docstatus, company, event_status from `tabTraining Event` where name = %s for update',
        (values['training_event'],), as_dict=True)
    action, reason = plan(rows[0] if rows else None, _participants(values['training_event']) if rows else [],
                          employee.name, request.company)
    if action == 'review':
        return NativeResult(status='needs_review', reason=reason)
    try:
        with as_administrator():
            event = frappe.get_doc('Training Event', values['training_event'])
            event.append('employees', {'employee': employee.name, 'employee_name': employee.employee_name,
                                       'department': employee.department, 'status': 'Open',
                                       'is_mandatory': 0})
            event.save(ignore_permissions=True)
            if values['notes']:
                from html import escape

                event.add_comment('Comment', escape(values['notes']))
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except frappe.ValidationError:
        frappe.clear_messages()
        raise ValueError(NATIVE_ERROR) from None
    return NativeResult(status='Created', doctype='Training Event', name=event.name)
