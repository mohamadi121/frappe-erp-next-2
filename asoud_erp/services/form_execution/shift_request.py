"""Atomic draft shift requests using native HRMS validation."""

from datetime import date

KIND = 'shift_request'
LABEL = 'تغییر شیفت'
PARAMETERS = {
    'kind': {'label': 'نوع تغییر', 'types': ['Select'], 'required': True},
    'from_date': {'label': 'تاریخ شروع', 'types': ['Date'], 'required': True},
    'to_date': {'label': 'تاریخ پایان', 'types': ['Date'], 'required': False},
    'shift_type': {'label': 'شیفت پیشنهادی درخواست‌دهنده', 'types': ['Link'], 'required': True},
    'colleague': {'label': 'همکار', 'types': ['Link'], 'required': False},
    'colleague_shift_type': {'label': 'شیفت پیشنهادی همکار', 'types': ['Link'], 'required': False},
    'reason': {'label': 'دلیل تغییر', 'types': ['Text', 'LongText'], 'required': False},
}
NATIVE_ERROR = 'ثبت درخواست شیفت انجام نشد؛ هم‌پوشانی برنامه، شیفت پیش‌فرض و تأییدکننده را بررسی کنید.'


def _text(value, message):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value.strip()


def _day(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError('تاریخ تغییر شیفت معتبر نیست.') from None


def build(params: dict, ctx: dict) -> dict:
    if not isinstance(params, dict) or not isinstance(ctx, dict):
        raise ValueError('اطلاعات تغییر شیفت معتبر نیست.')
    company = _text(ctx.get('company'), 'شرکت درخواست مشخص نشده است.')
    employee = _text(ctx.get('employee'), 'پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    kind = params.get('kind')
    if kind not in ('self_change', 'swap_with_colleague'):
        raise ValueError('نوع تغییر شیفت معتبر نیست.')
    start = _day(params.get('from_date'))
    end = params.get('to_date')
    end = None if end is None or isinstance(end, str) and not end.strip() else _day(end)
    if end and end < start:
        raise ValueError('تاریخ پایان نمی‌تواند پیش از شروع باشد.')
    reason = params.get('reason')
    if reason is not None and not isinstance(reason, str):
        raise ValueError('دلیل تغییر شیفت باید متن باشد.')
    payload = {'doctype': 'Shift Request', 'company': company, 'employee': employee,
               'from_date': start, 'to_date': end, 'status': 'Draft', 'docstatus': 0,
               'shift_type': _text(params.get('shift_type'), 'شیفت پیشنهادی را انتخاب کنید.')}
    if kind == 'swap_with_colleague':
        colleague = _text(params.get('colleague'), 'همکار جایگزین را انتخاب کنید.')
        if colleague == employee:
            raise ValueError('همکار جایگزین باید با درخواست‌دهنده متفاوت باشد.')
        payload['additional_requests'] = [{**payload, 'employee': colleague,
            'shift_type': _text(params.get('colleague_shift_type'), 'شیفت پیشنهادی همکار را انتخاب کنید.')}]
    return payload


def apply(request, params: dict):
    import frappe

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    filters = {'user_id': request.owner, 'company': request.company, 'status': 'Active'}
    if request.get('requester_employee'):
        filters['name'] = request.requester_employee
    employee = frappe.db.get_value('Employee', filters, 'name')
    payload = build(params, {'company': request.company, 'employee': employee})
    payloads = [payload, *payload.pop('additional_requests', [])]
    names = sorted({row['employee'] for row in payloads})
    # Lock both people in stable order before checking native schedules.
    frappe.db.sql('select name from `tabEmployee` where name in %s order by name for update', (names,))
    people = {row.name: row for row in frappe.get_all('Employee', filters={'name': ['in', names]},
        fields=['name', 'company', 'status', 'department', 'shift_request_approver'], limit_page_length=0)}
    if any(name not in people or people[name].company != request.company or
           people[name].status != 'Active' for name in names):
        raise ValueError('همکار انتخاب‌شده باید فعال و متعلق به شرکت درخواست باشد.')
    shifts = {row.name for row in frappe.get_all('Shift Type',
        filters={'name': ['in', [row['shift_type'] for row in payloads]]},
        fields=['name'], limit_page_length=0)}
    if any(row['shift_type'] not in shifts for row in payloads):
        raise ValueError('شیفت انتخاب‌شده وجود ندارد.')
    departments = [row.department for row in people.values() if row.department]
    department_approvers = frappe.get_all('Department Approver', filters={
        'parent': ['in', departments], 'parenttype': 'Department',
        'parentfield': 'shift_request_approver'}, fields=['parent', 'approver'],
        order_by='idx asc', limit_page_length=0) if departments else []
    candidates = {name: [people[name].shift_request_approver] + [row.approver
        for row in department_approvers if row.parent == people[name].department] for name in names}
    enabled = set(frappe.get_all('User', filters={
        'name': ['in', [user for users in candidates.values() for user in users if user]],
        'enabled': 1}, pluck='name', limit_page_length=0))
    approvers = {name: next((user for user in candidates[name] if user in enabled), None)
                 for name in names}
    if any(not user for user in approvers.values()):
        raise ValueError('تأییدکننده فعال شیفت برای کارکنان تنظیم نشده است.')
    frappe.db.savepoint('shift_request_pair')
    try:
        with as_administrator():
            docs = []
            for row in payloads:
                row['approver'] = approvers[row['employee']]
                assignment = frappe.get_doc({'doctype': 'Shift Assignment', 'employee': row['employee'],
                    'company': row['company'], 'shift_type': row['shift_type'],
                    'start_date': row['from_date'], 'end_date': row['to_date'], 'status': 'Active'})
                assignment.validate_overlapping_shifts()
                docs.append(frappe.get_doc(row).insert(ignore_permissions=True))
            from html import escape

            reason = (params.get('reason') or '').strip()
            if reason:
                for doc in docs:
                    doc.add_comment('Comment', escape(reason))
            if len(docs) == 2:
                docs[0].add_comment('Comment', 'درخواست مرتبط همکار: ' + escape(docs[1].name))
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception as error:
        frappe.db.rollback(save_point='shift_request_pair')
        frappe.clear_messages()
        if isinstance(error, (frappe.ValidationError, frappe.DoesNotExistError)):
            raise ValueError(NATIVE_ERROR) from None
        raise
    return NativeResult(status='Created', doctype='Shift Request', name=docs[0].name)
