"""Create a draft HRMS employee advance from approved form parameters."""

from datetime import date
from math import isfinite

KIND = 'employee_advance'
LABEL = 'مساعده کارکنان'
PARAMETERS = {
    'amount': {'label': 'مبلغ مساعده', 'types': ['Integer', 'Decimal', 'Money'], 'required': True},
    'purpose': {'label': 'شرح درخواست', 'types': ['Text', 'LongText'], 'required': True},
    'posting_date': {'label': 'تاریخ ثبت', 'types': ['Date'], 'required': False},
    'repay_from_salary': {'label': 'بازپرداخت از حقوق', 'types': ['Boolean', 'Checkbox'], 'required': False},
}


def _empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def build(params: dict, ctx: dict) -> dict:
    for key, message in (
        ('company', 'شرکت درخواست مشخص نشده است.'),
        ('employee', 'پرونده پرسنلی درخواست‌دهنده ثبت نشده است.'),
    ):
        if _empty(ctx.get(key)):
            raise ValueError(message)
    try:
        amount = float(params.get('amount'))
        if isinstance(params.get('amount'), bool) or not isfinite(amount) or amount <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError('مبلغ مساعده باید عددی مثبت و متناهی باشد.') from None
    purpose = params.get('purpose')
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError('شرح درخواست مساعده الزامی است.')
    posting_date = params.get('posting_date')
    if _empty(posting_date):
        posting_date = ctx.get('today')
    try:
        if not isinstance(posting_date, str) or len(posting_date) != 10:
            raise ValueError
        posting_date = date.fromisoformat(posting_date).isoformat()
    except (ValueError, TypeError):
        raise ValueError('تاریخ ثبت مساعده معتبر نیست.') from None
    repay = params.get('repay_from_salary')
    if _empty(repay):
        repay = 0
    if not isinstance(repay, (bool, int, str)) or repay not in (0, 1, '0', '1'):
        raise ValueError('گزینه بازپرداخت از حقوق باید بله یا خیر باشد.')
    return {
        'doctype': 'Employee Advance', 'docstatus': 0, 'company': ctx['company'],
        'employee': ctx['employee'], 'advance_amount': amount, 'purpose': purpose.strip(),
        'posting_date': posting_date, 'repay_unclaimed_amount_from_salary': int(repay),
        'exchange_rate': 1,
    }


def apply(request, params: dict):
    import frappe
    from frappe.utils import nowdate

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    company_name = request.get('company')
    if not company_name:
        raise ValueError('شرکت درخواست مشخص نشده است.')
    company = frappe.db.get_value('Company', company_name,
                                 ['default_currency', 'default_employee_advance_account'], as_dict=True)
    if not company:
        raise ValueError('شرکت درخواست یافت نشد.')
    filters = {'company': company_name, 'user_id': request.get('requester'), 'status': 'Active'}
    if not request.get('requester'):
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    if request.get('requester_employee'):
        filters['name'] = request.get('requester_employee')
    employee = frappe.db.get_value('Employee', filters, 'name')
    payload = build(params, dict(company=company_name, employee=employee,
                                user=request.get('requester'), request_name=request.get('name'), today=nowdate()))
    if not company.default_currency:
        raise ValueError('واحد پول شرکت مشخص نشده است.')
    account_name = company.default_employee_advance_account
    if not account_name:
        raise ValueError('حساب پیش‌فرض مساعده کارکنان در شرکت تنظیم نشده است.')
    account = frappe.db.get_value('Account', account_name,
                                 ['company', 'account_type', 'is_group', 'disabled'], as_dict=True)
    if (not account or account.company != company_name or account.account_type != 'Receivable'
            or account.is_group or account.disabled):
        raise ValueError('حساب مساعده کارکنان باید حساب دریافتنی فعال و غیرگروهی همین شرکت باشد.')
    payload.update(currency=company.default_currency, advance_account=account_name)
    with as_administrator():
        doc = frappe.get_doc(payload)
        doc.insert(ignore_permissions=True)
    return NativeResult(doctype=doc.doctype, name=doc.name, status='Created', reason='')
