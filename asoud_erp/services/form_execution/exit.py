"""Settlement drafts for an approved exit request: Exit Interview, Full and Final Statement, relieving date."""

from datetime import date

KIND = 'exit'
LABEL = 'تسویه حساب و خروج'
PARAMETERS = {
    'last_working_day': {'label': 'آخرین روز کاری', 'types': ['Date'], 'required': True},
    'reason': {'label': 'علت خروج', 'types': ['Select', 'Text', 'LongText'], 'required': False},
    'notes': {'label': 'توضیحات', 'types': ['Text', 'LongText'], 'required': False},
}
SAVEPOINT = 'exit_settlement'
NATIVE_ERROR = 'ثبت تسویه حساب انجام نشد؛ تاریخ پایان همکاری و اطلاعات پرونده کارمند را بررسی کنید.'
DUPLICATE_ERROR = 'برای این کارمند یک تسویه حساب باز یا ثبت‌شده وجود دارد؛ ابتدا آن را رد یا ابطال کنید.'
OPEN_STATUSES_EXCLUDED = ('Rejected', 'Cancelled')


def _text(value, message):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value.strip()


def _optional_text(value, message):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    return _text(value, message)


def _day(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError('آخرین روز کاری معتبر نیست.') from None


def check(params: dict) -> dict:
    """Validated parameters; the reason is checked but never copied to a native field."""
    if not isinstance(params, dict):
        raise ValueError('اطلاعات تسویه حساب معتبر نیست.')
    return {'last_working_day': _day(params.get('last_working_day')),
            'reason': _optional_text(params.get('reason'), 'علت خروج باید متن باشد.'),
            'notes': _optional_text(params.get('notes'), 'توضیحات تسویه حساب باید متن باشد.')}


def build(params: dict, ctx: dict) -> dict:
    if not isinstance(ctx, dict):
        raise ValueError('اطلاعات تسویه حساب معتبر نیست.')
    values = check(params)
    company = _text(ctx.get('company'), 'شرکت درخواست مشخص نشده است.')
    employee = _text(ctx.get('employee'), 'پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    today = ctx.get('today')
    statement = {'doctype': 'Full and Final Statement', 'docstatus': 0, 'company': company,
                 'employee': employee, 'relieving_date': values['last_working_day'],
                 'transaction_date': _day(today) if today else date.today().isoformat()}
    return {'doctype': 'Exit Interview', 'docstatus': 0, 'company': company, 'employee': employee,
            'status': 'Pending', 'employee_update': {'relieving_date': values['last_working_day']},
            'statement': statement, 'notes': values['notes']}


def _open_requests(employee: str, exclude_request: str | None):
    """Names of other live requests of this employee whose form executes as ``exit``.

    Rows are read with ``for update`` so a concurrent submit waits and then sees the other one.
    """
    import json

    import frappe

    rows = frappe.db.sql(
        """select r.name, v.name as revision, v.schema_json
           from `tabASOUD Workflow Request` r
           join `tabASOUD Form Entry` e on e.reference_doctype = 'ASOUD Workflow Request'
                and e.reference_name = r.name
           join `tabASOUD Form Revision` v on v.name = e.revision
           where r.requester_employee = %s and r.status not in %s and r.name != %s
           for update""", (employee, OPEN_STATUSES_EXCLUDED, exclude_request or ''), as_dict=True)
    return [row.name for row in rows
            if (json.loads(row.schema_json or '{}').get('execution') or {}).get('kind') == KIND]


def assert_no_open_settlement(employee: str, exclude_request: str | None = None) -> None:
    import frappe

    # Serialise concurrent settlements of one employee until the surrounding transaction ends.
    frappe.db.sql('select name from `tabEmployee` where name = %s for update', (employee,))
    if _open_requests(employee, exclude_request) or frappe.db.sql(
            'select name from `tabFull and Final Statement` where employee = %s and docstatus != 2 '
            'for update', (employee,)):
        raise ValueError(DUPLICATE_ERROR)


def validate_submit(params: dict, ctx: dict) -> None:
    """Registry hook: runs when the request is submitted, before it is stored."""
    check(params)
    employee = ctx.get('employee')
    if not employee:
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    assert_no_open_settlement(employee)


def apply(request, params: dict):
    import frappe

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    filters = {'user_id': request.owner, 'company': request.company, 'status': 'Active'}
    if request.get('requester_employee'):
        filters['name'] = request.requester_employee
    employee = frappe.db.get_value('Employee', filters, 'name')
    payload = build(params, {'company': request.company, 'employee': employee,
                             'today': frappe.utils.nowdate()})
    update, statement, notes = payload.pop('employee_update'), payload.pop('statement'), payload.pop('notes')
    assert_no_open_settlement(employee, request.get('name'))
    frappe.db.savepoint(SAVEPOINT)
    try:
        with as_administrator():
            person = frappe.get_doc('Employee', employee)
            person.relieving_date = update['relieving_date']
            person.save(ignore_permissions=True)
            interview = frappe.get_doc(payload).insert(ignore_permissions=True)
            if notes:
                from html import escape

                interview.add_comment('Comment', escape(notes))
            frappe.get_doc(statement).insert(ignore_permissions=True)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception as error:
        frappe.db.rollback(save_point=SAVEPOINT)
        frappe.clear_messages()
        if isinstance(error, (frappe.ValidationError, frappe.DoesNotExistError)):
            raise ValueError(NATIVE_ERROR) from None
        raise
    return NativeResult(status='Created', doctype='Exit Interview', name=interview.name)
