"""Office-bound reusable templates; effective grants remain native Custom DocPerm.

Templates are never attached as shared roles. Applying one is an explicit copy into
one account/office role. Legacy global assignments are reported, not guessed or migrated.
"""
import hashlib
import json

import frappe

from asoud_erp.services import security_audit
from asoud_erp.services.permission_catalog import MEDIUM_ACTIONS, catalog_rows, validate_grant


def gate(company):
    from asoud_erp.services.request_access import require_company

    if not isinstance(company, str) or not company or len(company) > 140 or not frappe.db.exists('Company', company):
        frappe.throw('دفتر معتبر را مشخص کنید.')
    require_company(company)
    if frappe.session.user != 'Administrator':
        from asoud_erp.services.office_access import office_roles

        held = set(frappe.get_roles()) | office_roles(frappe.session.user, company)
        if 'ASOUD Role Assigner' not in held:
            frappe.throw('مدیریت دسترسی این دفتر به شما واگذار نشده است.', frappe.PermissionError)


def catalog():
    rows = catalog_rows(lambda dt: frappe.db.exists('DocType', dt), lambda dt: frappe.get_meta(dt).is_submittable)
    result = []
    for row in rows:
        meta = frappe.get_meta(row['doctype'])
        # Shared native masters without an office owner cannot safely be made office-specific.
        if not meta.has_field('company'):
            continue
        supported = [a for a in MEDIUM_ACTIONS if any(p.get(a) for p in meta.permissions)]
        if not supported:
            continue
        group = financial_group(row['doctype'])
        row = {**row, 'module': 'مالی' if group else row['module'],
            'actions': supported, 'group': group, 'details': []}
        # Field-level readers currently combine roles site-wide. Do not advertise
        # office-specific field controls until every reader can enforce them.
        result.append(row)
    return result


def financial_group(doctype):
    if doctype in {'Journal Entry', 'Expense Claim'}:
        return 'ثبت حسابداری'
    if doctype in {'Payment Entry', 'Bank Account'}:
        return 'خزانه‌داری و بانک'
    if doctype in {'Account', 'Fiscal Year'}:
        return 'اطلاعات پایه و دوره مالی'
    if doctype.startswith(('Purchase', 'Sales')) or doctype == 'Quotation':
        return 'خرید و فروش'
    return ''


def normalize(grants):
    if not isinstance(grants, dict):
        frappe.throw('جدول مجوزها معتبر نیست.')
    allowed = {}
    for row in catalog():
        allowed[row['doctype']] = set(row['actions'])
        for detail in row['details']:
            allowed[f"{row['doctype']}::{detail['level']}"] = set(detail['actions'])
    if set(grants) - set(allowed):
        frappe.throw('یکی از اسناد یا جزئیات انتخاب‌شده مجوز قابل اعمال ندارد.')
    result = {}
    for key, actions in grants.items():
        error = validate_grant(actions, allowed[key])
        if error:
            frappe.throw(error)
        result[key] = sorted(set(actions))
    return result


def profile_row(doc):
    return {'name': doc.name, 'title': doc.title, 'description': doc.description or '',
            'company': doc.get('company'), 'modified': str(doc.modified),
            'readonly': not bool(doc.get('company')),
            'grants': json.loads(doc.get('template_permissions') or '{}')}


def list_profiles(company):
    gate(company)
    rows = frappe.get_all('ASOUD Role Definition', or_filters=[['company', '=', company],
        ['company', 'is', 'not set']], fields=['*'], order_by='title asc', limit_page_length=500)
    from asoud_erp.services.office_permission_templates import accountant_example

    available = catalog()
    example = accountant_example(available)
    return {'profiles': [profile_row(row) for row in rows], 'catalog': available,
        'examples': [example] if example['grants'] and not any(row.title == example['title'] for row in rows) else []}


def get_profile(company, name):
    gate(company)
    if not isinstance(name, str) or not name or not frappe.db.exists('ASOUD Role Definition', name):
        frappe.throw('پروفایل انتخاب‌شده یافت نشد.')
    doc = frappe.get_doc('ASOUD Role Definition', name)
    if doc.get('company') and doc.company != company:
        frappe.throw('این پروفایل متعلق به دفتر دیگری است.', frappe.PermissionError)
    return profile_row(doc)


def save_profile(company, title, description='', grants=None, name=None, modified=None):
    gate(company)
    title, description = str(title or '').strip(), str(description or '').strip()
    if not title or len(title) > 140 or len(description) > 2000:
        frappe.throw('نام پروفایل الزامی است؛ طول نام یا توضیحات معتبر نیست.')
    wanted = normalize(grants)
    key = hashlib.sha256(json.dumps([company, title.casefold()]).encode()).hexdigest()
    frappe.db.sql('select name from tabCompany where name=%s for update', (company,))
    duplicate = frappe.db.get_value('ASOUD Role Definition', {'template_key': key}, 'name')
    if duplicate and duplicate != name:
        frappe.throw('پروفایلی با این نام در همین دفتر وجود دارد.')
    if name:
        get_profile(company, name)
        doc = frappe.get_doc('ASOUD Role Definition', name, for_update=True)
        if not doc.get('company'):
            frappe.throw('دفتر این پروفایل قدیمی هنوز تأیید نشده است؛ فقط قابل مشاهده است.')
        if str(doc.modified) != modified:
            frappe.throw('پروفایل تغییر کرده است؛ دوباره بارگذاری کنید.', frappe.TimestampMismatchError)
    else:
        code = 'AP_' + frappe.generate_hash(length=25).upper()
        if not frappe.db.exists('ASOUD Role Category', 'ACCESS_PROFILES'):
            frappe.get_doc({'doctype': 'ASOUD Role Category', 'category_code': 'ACCESS_PROFILES',
                'title': 'پروفایل‌های دسترسی', 'style': 'system'}).insert(ignore_permissions=True)
        native = frappe.get_doc({'doctype': 'Role Profile', 'role_profile': 'ASOUD:' + code})
        native.insert(ignore_permissions=True)
        doc = frappe.get_doc({'doctype': 'ASOUD Role Definition', 'role_code': code,
            'role_profile': native.name, 'category': 'ACCESS_PROFILES', 'enabled': 1, 'scope': 'office'})
    doc.update({'company': company, 'title': title, 'description': description,
        'template_permissions': json.dumps(wanted), 'template_key': key})
    previous = frappe.flags.get('asoud_office_template_write')
    frappe.flags.asoud_office_template_write = doc.role_code
    try:
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.asoud_office_template_write = previous
    security_audit.record('access.profile_save', company=company,
        target_type=doc.doctype, target=doc.name)
    return profile_row(doc)


def person(company, employee):
    gate(company)
    if not isinstance(employee, str) or not employee or not frappe.db.exists('Employee', employee):
        frappe.throw('پرونده پرسنلی انتخاب‌شده یافت نشد.')
    doc = frappe.get_doc('Employee', employee)
    if doc.company != company or doc.status != 'Active':
        frappe.throw('پرسنل فعالِ همان دفتر را انتخاب کنید.', frappe.PermissionError)
    return doc


def account_role(user, company):
    return 'ASOUD-OFFICE-' + hashlib.sha256(json.dumps([user, company]).encode()).hexdigest()[:32]


def assignment(company, employee):
    doc = person(company, employee)
    row = frappe.db.get_value('ASOUD Access Assignment', {'company': company, 'employee': employee},
        ['name', 'user', 'native_role', 'managed_role', 'modified'], as_dict=True)
    if not row or doc.user_id != row.user:
        frappe.throw('این پرونده هنوز حساب دفترمحور معتبر ندارد؛ اتصال حساب را بررسی کنید.')
    return doc, row


def get_account(company, employee):
    doc = person(company, employee)
    row = frappe.db.get_value('ASOUD Access Assignment', {'company': company, 'employee': employee},
        ['name', 'user', 'native_role', 'managed_role', 'modified'], as_dict=True)
    grants = {}
    if row:
        for p in frappe.get_all('Custom DocPerm', filters={'role': row.native_role},
                fields=['parent', 'permlevel', *MEDIUM_ACTIONS], limit_page_length=0):
            key = p.parent + (f'::{p.permlevel}' if p.permlevel else '')
            grants[key] = [a for a in MEDIUM_ACTIONS if p.get(a)]
    return {'employee': employee, 'title': doc.employee_name, 'designation': doc.designation or '',
        'company': company, 'user': doc.user_id or '', 'legacy': bool(doc.user_id and not row),
        'login': (doc.user_id or '').removesuffix('@users.asoud.invalid'),
        'profile': row.managed_role if row else None, 'token': str(row.modified) if row else None,
        'grants': grants, 'catalog': catalog()}


def save_account_access(company, employee, grants, token, profile=None):
    from frappe.permissions import add_permission, update_permission_property

    doc, row = assignment(company, employee)
    frappe.db.sql('select name from tabUser where name=%s for update', (row.user,))
    if str(frappe.db.get_value('ASOUD Access Assignment', row.name, 'modified')) != token:
        frappe.throw('دسترسی تغییر کرده است؛ دوباره بارگذاری کنید.', frappe.TimestampMismatchError)
    if profile:
        selected = get_profile(company, profile)
        if selected['readonly']:
            frappe.throw('پروفایل قدیمی بدون دفتر قابل اعمال نیست.')
    wanted = normalize(grants)
    if frappe.session.user != 'Administrator':
        # Delegates may copy only native rights that they hold in this office.
        from asoud_erp.services.office_permission_scope import has_grant

        for key, actions in wanted.items():
            dt, _, level = key.partition('::')
            if any(not has_grant(frappe.session.user, company, dt, a, int(level or 0)) for a in actions):
                frappe.throw('نمی‌توانید مجوزی فراتر از دسترسی خود در این دفتر بدهید.', frappe.PermissionError)
    allowed = {r['doctype']: r for r in catalog()}
    existing = frappe.get_all('Custom DocPerm', filters={'role': row.native_role},
        fields=['parent', 'permlevel'], limit_page_length=0)
    keys = set(wanted) | {p.parent + (f'::{p.permlevel}' if p.permlevel else '') for p in existing}
    for key in sorted(keys):
        dt, _, level = key.partition('::')
        if dt not in allowed:
            frappe.throw('مجوز ذخیره‌شده نیازمند بازبینی است؛ حذف خودکار انجام نشد.')
        level = int(level or 0)
        if not frappe.db.exists('Custom DocPerm', {'parent': dt, 'role': row.native_role, 'permlevel': level}):
            add_permission(dt, row.native_role, permlevel=level)
        for action in (*MEDIUM_ACTIONS, 'submit', 'cancel', 'amend', 'share', 'export', 'import', 'report'):
            update_permission_property(dt, row.native_role, level, action,
                int(action in wanted.get(key, [])), validate=False)
        frappe.clear_cache(doctype=dt)
    record = frappe.get_doc('ASOUD Access Assignment', row.name)
    record.managed_role = profile or None
    record.save(ignore_permissions=True)
    frappe.clear_cache(user=row.user)
    security_audit.record('access.account_save', company=company, target_type='User', target=row.user)
    return get_account(company, employee)


def list_accounts(company):
    gate(company)
    return frappe.get_all('Employee', filters={'company': company, 'status': 'Active'},
        fields=['name', 'employee_name', 'designation', 'user_id'], order_by='employee_name asc', limit_page_length=500)


def create_account(company, employee, contact, method='email', invite=False):
    from asoud_erp.services.credential_policy import normalize_email, normalize_mobile

    doc = person(company, employee)
    if doc.user_id:
        frappe.throw('این پرونده حساب دارد؛ از جزئیات حساب استفاده کنید.')
    try:
        if method == 'mobile':
            mobile = normalize_mobile(contact)
            if not mobile:
                raise ValueError('شماره موبایل الزامی است.')
            login = mobile + '@users.asoud.invalid'
        elif method == 'email':
            mobile = ''
            login = normalize_email(contact)
            if not login:
                raise ValueError('ایمیل ورود الزامی است.')
        else:
            raise ValueError('روش ورود معتبر نیست.')
    except ValueError as exc:
        frappe.throw(str(exc))
    if frappe.db.exists('User', login):
        frappe.throw('این شناسه حساب دارد؛ اتصال آن باید جداگانه توسط مدیر بررسی شود.')
    frappe.db.savepoint('office_account_create')
    try:
        # Native Employee linking never creates a new Employee or a personnel profile.
        frappe.db.sql('select name from tabEmployee where name=%s for update', (employee,))
        if frappe.db.get_value('Employee', employee, 'user_id'):
            frappe.throw('این پرونده هم‌زمان به حساب دیگری متصل شده است.')
        role = account_role(login, company)
        frappe.get_doc({'doctype': 'Role', 'role_name': role, 'desk_access': 1}).insert(ignore_permissions=True)
        user = frappe.get_doc({'doctype': 'User', 'email': login, 'first_name': doc.first_name,
            'last_name': doc.last_name, 'mobile_no': mobile or None, 'send_welcome_email': 0,
            'user_type': 'System User', 'roles': [{'role': 'Employee'}]})
        user.insert(ignore_permissions=True)
        doc.user_id = user.name
        # A global Employee/Department User Permission would also restrict a later
        # HR grant to self. Personal scope is enforced by native Employee policies
        # and the office boundary, not a permanent filter across every DocType.
        doc.create_user_permission = 0
        doc.save(ignore_permissions=True)
        from frappe.permissions import add_user_permission

        add_user_permission('Company', company, user.name, ignore_permissions=True)
        frappe.get_doc({'doctype': 'ASOUD Access Assignment', 'user': user.name,
            'company': company, 'employee': employee, 'native_role': role}).insert(ignore_permissions=True)
        user.reload()
        user.save(ignore_permissions=True)
        from asoud_erp.services import account_state

        state = account_state.ensure(user.name)
        state.activation_pending = 1
        state.save(ignore_permissions=True)
        result = get_account(company, employee)
        if invite:
            result['activation'] = invite_account(company, employee)
        security_audit.record('access.account_create', company=company, target_type='User', target=user.name)
        return result
    except Exception:
        frappe.db.rollback(save_point='office_account_create')
        raise


def invite_account(company, employee):
    from asoud_erp.services.hr_onboarding import _activate

    _, row = assignment(company, employee)
    if frappe.db.get_value('User', row.user, 'last_login'):
        frappe.throw('این حساب قبلاً وارد شده است؛ از مسیر بازیابی رمز استفاده کنید.')
    if row.user.endswith('@users.asoud.invalid'):
        # Existing one-time temporary-password delivery; never pretend SMS was sent.
        return _activate(row.user, '', 'temporary_password')
    return _activate(row.user, row.user, 'invite')


def legacy_report(company):
    gate(company)
    people = list_accounts(company)
    users = [row.user_id for row in people if row.user_id]
    return {'assignments': frappe.get_all('ASOUD Access Assignment',
        filters={'user': ['in', users or ['']], 'company': ['is', 'not set']},
        fields=['name', 'user', 'managed_role', 'native_role'], limit_page_length=500),
        'profiles': [row for row in list_profiles(company)['profiles'] if row['readonly']],
        'notice': 'دفتر مجوزهای سراسری قبلی مشخص نیست؛ هیچ انتقال یا حذفی انجام نشده است.'}
