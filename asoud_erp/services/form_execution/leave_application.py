"""Submit an HRMS Leave Application after the final approval (owner decision: automatic, all or nothing)."""

KIND = 'leave_application'
LABEL = 'درخواست مرخصی'
PARAMETERS = {
    'leave_type': {'label': 'نوع مرخصی', 'types': ['Link'], 'required': True},
    'from_date': {'label': 'تاریخ شروع', 'types': ['Date'], 'required': True},
    'to_date': {'label': 'تاریخ پایان', 'types': ['Date'], 'required': True},
    'half_day': {'label': 'نیم‌روز', 'types': ['Boolean', 'Checkbox'], 'required': False},
    'half_day_date': {'label': 'تاریخ نیم‌روز', 'types': ['Date'], 'required': False},
    'description': {'label': 'توضیح درخواست مرخصی', 'types': ['Text', 'LongText'], 'required': False},
}
SAVEPOINT = 'leave_application_execution'
INSUFFICIENT = 'مانده قابل مصرف برای این مرخصی کافی نیست.'
NO_ALLOCATION = 'برای این نوع مرخصی در تاریخ شروع تخصیص معتبر ثبت نشده است.'
ONLY_HOLIDAYS = 'روزهای درخواستی تعطیل است و نیازی به مرخصی نیست.'
OVERLAP = 'برای این بازه مرخصی هم‌پوشان ثبت شده است.'
NO_APPROVER = 'تأییدکننده مرخصی برای این پرسنل تنظیم نشده است.'
UNKNOWN_TYPE = 'نوع مرخصی انتخاب‌شده وجود ندارد.'
NATIVE_ERROR = 'ثبت مرخصی انجام نشد؛ حضور ثبت‌شده، روزهای مسدود و محدودیت‌های مرخصی را بررسی کنید.'


def build(params: dict, ctx: dict) -> dict:
    """The draft Leave Application; ``apply`` submits it. Pure: no Frappe import."""
    from . import period

    if not isinstance(params, dict):
        raise ValueError('اطلاعات درخواست مرخصی معتبر نیست.')
    company, employee = period.context(ctx)
    leave_type = params.get('leave_type')
    if not isinstance(leave_type, str) or not leave_type.strip():
        raise ValueError('نوع مرخصی را انتخاب کنید.')
    start, end, half, half_date = period.date_range(params, 'مرخصی')
    description = period.clean_text(params.get('description'), 'توضیح مرخصی باید متن باشد.',
                                    too_long='توضیح مرخصی حداکثر ۲۰۰۰ نویسه است.')
    return {
        'doctype': 'Leave Application', 'employee': employee, 'company': company,
        'leave_type': leave_type.strip(), 'from_date': start, 'to_date': end,
        'half_day': half, 'half_day_date': half_date, 'description': description,
        'posting_date': ctx.get('today'), 'leave_approver': ctx.get('leave_approver') or None,
        'status': 'Approved', 'docstatus': 0,
    }


def check_balance(details: dict, leave_type: str, days: float) -> None:
    """Compare the HRMS ``get_leave_details`` answer with the requested days (pure)."""
    allocation = (details.get('leave_allocation') or {}).get(leave_type)
    if allocation is None:
        raise ValueError(NO_ALLOCATION)
    remaining = allocation.get('remaining_leaves')
    if remaining is None or float(remaining) < float(days):
        raise ValueError(INSUFFICIENT)


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
    with as_administrator():
        from hrms.hr.doctype.leave_application import leave_application as hrms_leave

        approver = hrms_leave.get_leave_approver(employee)
        payload = build(params, {'company': request.company, 'employee': employee, 'today': nowdate(),
                                 'leave_approver': approver})
        leave_type = frappe.db.get_value('Leave Type', payload['leave_type'],
                                         ['is_lwp', 'allow_negative'], as_dict=True)
        if not leave_type:
            raise ValueError(UNKNOWN_TYPE)
        if not approver and frappe.db.get_single_value('HR Settings', 'leave_approver_mandatory_in_leave_application'):
            raise ValueError(NO_APPROVER)
        days = hrms_leave.get_number_of_leave_days(
            employee, payload['leave_type'], payload['from_date'], payload['to_date'],
            payload['half_day'], payload['half_day_date'])
        if days <= 0:
            raise ValueError(ONLY_HOLIDAYS)
        if not leave_type.is_lwp and not leave_type.allow_negative:
            check_balance(hrms_leave.get_leave_details(employee, payload['from_date']),
                          payload['leave_type'], days)
        frappe.db.savepoint(SAVEPOINT)
        try:
            doc = frappe.get_doc(payload).insert(ignore_permissions=True)
            doc.submit()
            doc.add_comment('Comment', f'ایجاد‌شده از درخواست {request.name}')
        except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
            raise
        except frappe.ValidationError as error:
            frappe.db.rollback(save_point=SAVEPOINT)
            frappe.clear_messages()
            raise ValueError(_native_message(error)) from None
    return NativeResult(status='Created', doctype=doc.doctype, name=doc.name)


def _native_message(error) -> str:
    from hrms.hr.doctype.leave_application import leave_application as hrms_leave

    if isinstance(error, hrms_leave.InsufficientLeaveBalanceError):
        return INSUFFICIENT
    if isinstance(error, hrms_leave.OverlapError):
        return OVERLAP
    return NATIVE_ERROR
