"""Issue the employment certificate (T3) as a numbered PDF with letterhead after final approval.

Content comes from the Employee, the Company and, only when the form asked for it, the latest
submitted Salary Structure Assignment. Anything missing ends as ``needs_review`` with a Persian
reason: no number is taken and nothing is guessed. The text is rendered with the document-template
placeholder renderer; the PDF is made by Frappe's own WeasyPrint integration.
"""

from datetime import date, datetime
from html import escape

from asoud_erp.services.certificate_access import FIELD
from asoud_erp.services.digits import to_persian_digits
from asoud_erp.services.document_templates import render_placeholders
from asoud_erp.services.jalali import gregorian_to_jalali

KIND = 'certificate_issue'
LABEL = 'صدور گواهی اشتغال به کار'
ALLOW_INACTIVE = True  # a relieved requester must reach HR as needs_review, not fail
SERIES = 'CERT-.YYYY.-.#####'
PARAMETERS = {
    'recipient': {'label': 'مرجع دریافت‌کننده گواهی', 'types': ['Text', 'LongText'], 'required': True},
    'purpose': {'label': 'هدف از دریافت گواهی', 'types': ['Select', 'Text'], 'required': True},
    'purpose_details': {'label': 'شرح هدف', 'types': ['Text', 'LongText'], 'required': False},
    'language': {'label': 'زبان گواهی', 'types': ['Select', 'Text'], 'required': False},
    'include_compensation': {'label': 'درج حقوق و مزایا', 'types': ['Select', 'Boolean', 'Checkbox'], 'required': False},
}
PURPOSES = {'bank': 'ارائه به بانک', 'embassy': 'ارائه به سفارت', 'organization': 'ارائه به سازمان یا شرکت',
            'other': 'سایر موارد'}
REVIEW_NOT_EMPLOYED = 'نیاز به اقدام HR؛ کارمند در حال حاضر شاغل نیست و گواهی اشتغال خودکار صادر نمی‌شود.'
REVIEW_SALARY = ('نیاز به اقدام HR؛ برای درج حقوق، تخصیص ساختار حقوق ثبت‌شده و معتبر برای کارمند وجود ندارد.')
REVIEW_ENGLISH = 'نیاز به اقدام HR؛ قالب انگلیسی تأییدشده برای گواهی اشتغال تعریف نشده است.'
REVIEW_LETTERHEAD = 'نیاز به اقدام HR؛ سربرگ شرکت برای صدور گواهی تعریف نشده است.'
PDF_ERROR = 'ساخت فایل PDF گواهی انجام نشد؛ تنظیمات چاپ سرور را بررسی کنید.'
_YES = {'yes', 'true', '1', 1, True}
_NO = {'no', 'false', '0', 0, False, None, ''}

BODY = ('بدین‌وسیله گواهی می‌شود {{employee_name}} از تاریخ {{joined}} در شرکت {{company_name}}'
        '{{position}} مشغول به کار است. این گواهی بنا به درخواست ایشان {{purpose}} صادر می‌شود.')
SALARY_LINE = 'حقوق پایه ماهانه ثبت‌شده: {{amount}} {{currency}}.'
PAGE = ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>'
        '@page{size:A4;margin:18mm 16mm}body{font-family:Vazirmatn,"Noto Naskh Arabic","DejaVu Sans",sans-serif;'
        'font-size:13pt;line-height:2;direction:rtl;text-align:right}.meta{display:flex;justify-content:'
        'space-between;margin:12px 0}h1{text-align:center;font-size:18pt}.foot{margin-top:40px;font-size:10pt;'
        'color:#555}</style></head><body>{letterhead}<h1>گواهی اشتغال به کار</h1>'
        '<div class="meta"><span>شماره: <bdi>{number}</bdi></span><span>تاریخ صدور: {issued}</span></div>'
        '<p>به: {recipient}</p><p>{body}</p>{details}{salary}'
        '<p class="foot">این گواهی به‌صورت خودکار از سامانه صادر شده و فاقد امضا و مهر دستی است.</p>'
        '</body></html>')


def _text(value, label: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(label)
    return value.strip()


def normalize(params: dict) -> dict:
    """Validated form values: recipient, purpose, purpose_details, language, include_compensation."""
    if not isinstance(params, dict):
        raise ValueError('اطلاعات گواهی معتبر نیست.')
    purpose = params.get('purpose')
    if purpose not in PURPOSES:
        raise ValueError('هدف از دریافت گواهی معتبر نیست.')
    details = None
    if purpose == 'other':
        details = params.get('purpose_details')
        if not isinstance(details, str) or not details.strip():
            raise ValueError('شرح هدف برای گزینه سایر موارد الزامی است.')
        details = details.strip()[:1000]
    language = params.get('language') or 'persian'
    if language not in ('persian', 'english'):
        raise ValueError('زبان گواهی معتبر نیست.')
    raw = params.get('include_compensation')
    raw = raw.strip().lower() if isinstance(raw, str) else raw
    if raw not in _YES and raw not in _NO:
        raise ValueError('گزینه درج حقوق و مزایا معتبر نیست.')
    return {'recipient': _text(params.get('recipient'), 'مرجع دریافت‌کننده گواهی الزامی است.', limit=250),
            'purpose': purpose, 'purpose_details': details, 'language': language,
            'include_compensation': raw in _YES}


def _day(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def jalali(value) -> str:
    year, month, day = gregorian_to_jalali(_day(value))
    return to_persian_digits(f'{year:04d}/{month:02d}/{day:02d}')


def money(value) -> str:
    return to_persian_digits(f'{int(round(float(value))):,}').replace(',', '٬')


def review_reason(values: dict, facts: dict, today) -> str | None:
    relieved = _day(facts.get('relieving_date'))
    if facts.get('status') != 'Active' or (relieved and relieved <= _day(today)):
        return REVIEW_NOT_EMPLOYED
    if values['language'] == 'english':
        return REVIEW_ENGLISH
    if not facts.get('letterhead_html'):
        return REVIEW_LETTERHEAD
    if values['include_compensation']:
        salary = facts.get('salary') or {}
        if not salary.get('base') or float(salary['base']) <= 0:
            return REVIEW_SALARY
    return None


def build(params: dict, ctx: dict) -> dict:
    """``{'needs_review': reason}`` or ``{'html', 'number', 'filename'}``; pure."""
    if not isinstance(ctx, dict):
        raise ValueError('اطلاعات گواهی معتبر نیست.')
    if not isinstance(ctx.get('company'), str) or not ctx['company'].strip():
        raise ValueError('شرکت درخواست مشخص نشده است.')
    if not isinstance(ctx.get('employee'), str) or not ctx['employee'].strip():
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    values = normalize(params)
    facts = ctx.get('facts') or {}
    reason = review_reason(values, facts, ctx['today'])
    if reason:
        return {'needs_review': reason}
    number = ctx.get('number')
    if not isinstance(number, str) or not number:
        raise ValueError('شماره گواهی مشخص نشده است.')
    safe = {key: escape(str(value)) for key, value in {
        'employee_name': facts['employee_name'], 'company_name': facts['company_name'],
        'joined': jalali(facts['date_of_joining']), 'purpose': PURPOSES[values['purpose']]}.items()}
    safe['position'] = f' در سمت {escape(facts["designation"])}' if facts.get('designation') else ''
    salary = ''
    if values['include_compensation']:
        data = facts['salary']
        salary = '<p>' + render_placeholders(SALARY_LINE, {'request': {
            'amount': money(data['base']), 'currency': escape(str(data.get('currency') or ''))}}) + '</p>'
    details = f'<p>شرح: {escape(values["purpose_details"])}</p>' if values['purpose_details'] else ''
    html = (PAGE.replace('{number}', escape(number))
            .replace('{issued}', jalali(ctx['today'])).replace('{recipient}', escape(values['recipient']))
            .replace('{body}', render_placeholders(BODY, {'request': safe}))
            .replace('{details}', details).replace('{salary}', salary)
            .replace('{letterhead}', facts['letterhead_html']))
    return {'html': html, 'number': number, 'filename': f'{number}.pdf'}


# ------------------------------------------------------------------ native side


def _letterhead(company: str) -> str | None:
    import base64

    import frappe

    name = frappe.db.get_value('Company', company, 'default_letter_head')
    head = frappe.db.get_value('Letter Head', name, ['disabled', 'source', 'content', 'image'],
                               as_dict=True) if name else None
    if not head or head.disabled:
        return None
    if head.source == 'Image' and head.image:
        file_name = frappe.db.get_value('File', {'file_url': head.image}, 'name')
        if file_name:
            data = frappe.get_doc('File', file_name).get_content()
            data = data.encode() if isinstance(data, str) else data
            return '<img style="max-height:80px" src="data:image/png;base64,' + base64.b64encode(data).decode() + '">'
    # Frappe leaves the source on «Image» for a letter head that only has HTML content.
    return head.content or None


def _salary(employee: str, company: str, today) -> dict | None:
    import frappe

    rows = frappe.get_all('Salary Structure Assignment', filters={
        'employee': employee, 'company': company, 'docstatus': 1, 'from_date': ['<=', today]},
        fields=['base', 'currency'], order_by='from_date desc, creation desc', limit_page_length=1)
    return {'base': rows[0].base, 'currency': rows[0].currency} if rows else None


def _existing(request_name: str) -> str | None:
    import frappe

    return frappe.db.get_value('File', {
        'attached_to_doctype': 'ASOUD Workflow Request', 'attached_to_name': request_name,
        'attached_to_field': FIELD}, 'name')


def number_of(file_name: str) -> str:
    """The certificate number is the stem of the PDF file name (File has no description column)."""
    return file_name[:-4] if file_name.endswith('.pdf') else file_name


def render_pdf(html: str) -> bytes:
    from frappe.utils.weasyprint import import_weasyprint

    try:
        return import_weasyprint()[0](string=html).write_pdf()
    except Exception as error:  # noqa: BLE001 - WeasyPrint raises many types; the user gets one Persian sentence
        raise ValueError(PDF_ERROR) from error


def apply(request, params: dict):
    import frappe
    from frappe.model.naming import make_autoname
    from frappe.utils import nowdate

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    existing = _existing(request.name)
    if existing:
        return NativeResult(status='Created', doctype='File', name=existing)
    filters = {'user_id': request.owner, 'company': request.company}
    if request.get('requester_employee'):
        filters['name'] = request.requester_employee
    rows = frappe.get_all('Employee', filters=filters, fields=[
        'name', 'employee_name', 'designation', 'date_of_joining', 'status', 'relieving_date'],
        order_by='modified desc', limit_page_length=0)
    # An Active record wins over older ones; otherwise the latest decides (and ends as needs_review).
    employee = next((row for row in rows if row.status == 'Active'), rows[0] if rows else None)
    if not employee:
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    today = nowdate()
    values = normalize(params)
    facts = {'employee_name': employee.employee_name, 'designation': employee.designation,
             'date_of_joining': employee.date_of_joining, 'status': employee.status,
             'relieving_date': employee.relieving_date,
             'company_name': frappe.db.get_value('Company', request.company, 'company_name') or request.company,
             'letterhead_html': _letterhead(request.company),
             'salary': _salary(employee.name, request.company, today) if values['include_compensation'] else None}
    if not facts['date_of_joining']:
        raise ValueError('تاریخ شروع به کار کارمند ثبت نشده است.')
    ctx = {'company': request.company, 'employee': employee.name, 'user': request.owner,
           'request_name': request.name, 'today': today, 'facts': facts}
    reason = review_reason(values, facts, today)
    if reason:
        return NativeResult(status='needs_review', reason=reason)
    with as_administrator():
        number = make_autoname(SERIES)
        built = build(params, {**ctx, 'number': number})
        content = render_pdf(built['html'])
        file = frappe.get_doc({
            'doctype': 'File', 'file_name': built['filename'], 'content': content, 'is_private': 1,
            'attached_to_doctype': 'ASOUD Workflow Request', 'attached_to_name': request.name,
            'attached_to_field': FIELD}).insert(ignore_permissions=True)
    return NativeResult(status='Created', doctype='File', name=file.name)
