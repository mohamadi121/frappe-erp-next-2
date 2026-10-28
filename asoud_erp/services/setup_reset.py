"""Fail-closed reset of owned setup data, never a database/ledger wipe."""
import hashlib
import json

import frappe
from frappe.utils import cint, get_datetime, now_datetime
from frappe.utils.password import check_password

from asoud_erp.services import account_state, security_audit
from asoud_erp.services.system_admin import is_system_admin

CONFIG = 'asoud_allow_setup_reset'
LIMIT = 2000
BUSY_KEY = 'asoud_setup_reset_busy'
RECEIPT_TTL = 86400
COMPANY_DATA = ('ASOUD Office Role Assignment', 'ASOUD Personnel Record',
    'ASOUD Organization Chart', 'ASOUD Document Template', 'ASOUD Party Profile',
    'ASOUD Company Setup', 'Employee', 'Department', 'ASOUD Form', 'ASOUD Workflow Definition')
NATIVE_COMPANY_DATA = ('Account', 'Cost Center', 'Warehouse', 'Sales Taxes and Charges Template',
    'Purchase Taxes and Charges Template', 'Item Tax Template')
PRESERVED = ['شناسهٔ حساب مدیر، نام کاربری، رمز و دسترسی مدیر سیستم',
    'نقش‌ها و تنظیمات ضروری سیستمی و سوابق امنیتی', 'اطلاعات دفاتر خارج از محدودهٔ تأییدشده']


def access(require_enabled=True):
    if not is_system_admin():
        frappe.throw('بازنشانی فقط پس از ورود مدیر سیستم مجاز است.', frappe.PermissionError)
    if require_enabled and not cint(frappe.conf.get(CONFIG)):
        frappe.throw('بازنشانی موقت روی این سرور فعال نشده است؛ مدیر سرور باید آن را صریحاً فعال کند.')
    return frappe.session.user


def rows(doctype, filters, order_by='name asc'):
    if not frappe.db.exists('DocType', doctype):
        return []
    result = frappe.get_all(doctype, filters=filters, fields=['name', 'modified'],
        order_by=order_by, limit_page_length=LIMIT + 1)
    if len(result) > LIMIT:
        frappe.throw('حجم اطلاعات برای بازنشانی موقت بیش از حد مجاز است؛ پاک‌سازی باید روی سرور بررسی شود.')
    return [dict(row) for row in result]


def _collect(actor):
    offices = frappe.get_all('ASOUD Company Setup', pluck='company', limit_page_length=LIMIT + 1)
    if len(offices) > LIMIT:
        frappe.throw('تعداد دفاتر برای بازنشانی موقت بیش از حد مجاز است.')
    companies = rows('Company', {'name': ['in', offices or ['']], 'owner': actor}, 'lft desc')
    names = [row['name'] for row in companies]
    groups = {'Company': companies}
    blockers = []
    scope = {'company': ['in', names or ['']]}
    for doctype in (*COMPANY_DATA, *NATIVE_COMPANY_DATA):
        order = 'lft desc' if doctype == 'Department' else 'name asc'
        groups[doctype] = rows(doctype, scope, order)
    personal = rows('ASOUD Party Profile', {'user': actor})
    if any(frappe.db.get_value('ASOUD Party Profile', r['name'], 'company') not in [None, '', *names] for r in personal):
        blockers.append('مشخصات مدیر به دفتر دیگری متصل است؛ حذف خودکار متوقف شد.')
    groups['ASOUD Party Profile'] = list({r['name']: r for r in [*groups['ASOUD Party Profile'], *personal]}.values())
    fiscal_names = frappe.get_all('Fiscal Year Company', filters={'company': ['in', names or ['']]}, pluck='parent')
    groups['Fiscal Year'] = rows('Fiscal Year', {'name': ['in', fiscal_names or ['']]})
    for row in groups['Fiscal Year']:
        linked = set(frappe.get_all('Fiscal Year Company', filters={'parent': row['name']}, pluck='company'))
        if not linked - set(names) and frappe.db.get_value('Fiscal Year', row['name'], 'owner') != actor:
            blockers.append('سال مالی دفتر متعلق به حساب دیگری است؛ پاک‌سازی خودکار آن مجاز نیست.')
    # Internal graphs and immutable revisions are technical children, not business submissions.
    for parent, children, field in (
        ('ASOUD Workflow Definition', ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'), 'workflow_definition'),
        ('ASOUD Form', ('ASOUD Form Revision',), 'form'),
    ):
        for child in children:
            groups[child] = rows(child, {field: ['in', [r['name'] for r in groups[parent]] or ['']]})
    employee_names = [r['name'] for r in groups['Employee']]
    users = set(frappe.get_all('Employee', filters={'name': ['in', employee_names or ['']]}, pluck='user_id'))
    users.update(frappe.get_all('ASOUD Company Setup', filters=scope, pluck='first_hr_user'))
    users.discard(None)
    users -= {actor, 'Administrator', 'Guest', ''}
    owned_users = frappe.get_all('User', filters={'name': ['in', sorted(users) or ['']], 'owner': actor}, pluck='name')
    protected = set(frappe.get_all('Has Role', filters={'parent': ['in', owned_users or ['']],
        'parenttype': 'User', 'role': 'System Manager'}, pluck='parent'))
    if protected:
        blockers.append('یکی از حساب‌های وابسته مدیر سیستم است؛ حذف خودکار آن مجاز نیست.')
    owned_users = sorted(set(owned_users) - protected)
    groups['User'] = rows('User', {'name': ['in', owned_users or ['']]})
    for doctype in ('ASOUD Account State', 'ASOUD Account Token'):
        subjects = [actor, *owned_users] if doctype == 'ASOUD Account Token' else owned_users
        groups[doctype] = rows(doctype, {'user': ['in', subjects or ['']]})
    roles = rows('ASOUD Role Definition', {'owner': actor, 'is_system': 0})
    groups['ASOUD Role Definition'] = roles
    codes = [r['name'] for r in roles]
    role_rows = frappe.get_all('ASOUD Role Definition', filters={'name': ['in', codes or ['']]},
        fields=['name', 'role_profile', 'parent_role'], limit_page_length=LIMIT)
    profiles = [r.role_profile for r in role_rows if r.role_profile]
    if frappe.db.exists('User', {'role_profile_name': ['in', profiles or ['']], 'name': ['not in', [actor, *owned_users]]}):
        blockers.append('نقش اختصاصی شما به حسابی خارج از محدوده متصل است؛ ابتدا وابستگی را بررسی کنید.')
    groups['Role Profile'] = rows('Role Profile', {'name': ['in', profiles or ['']]})
    groups['ASOUD Access Assignment'] = rows('ASOUD Access Assignment', {'managed_role': ['in', codes or ['']]})
    from asoud_erp.api.v1.user_access import _native
    adapter_roles = {_native(code) for code in codes}
    for assignment in frappe.get_all('ASOUD Access Assignment',
            filters={'managed_role': ['in', codes or ['']]}, fields=['managed_role', 'user', 'native_role']):
        expected = {_native(assignment.managed_role), _native(assignment.managed_role, assignment.user or '')}
        if assignment.native_role not in expected:
            blockers.append('یک مجوز اختصاصی با نقش سیستمی سازگار نیست؛ حذف خودکار متوقف شد.')
        else:
            adapter_roles.add(assignment.native_role)
    groups['Role'] = rows('Role', {'name': ['in', sorted(adapter_roles) or ['']]})
    groups['Custom DocPerm'] = rows('Custom DocPerm', {'role': ['in', sorted(adapter_roles) or ['']]})
    if frappe.db.exists('Has Role', {'role': ['in', sorted(adapter_roles) or ['']],
            'parenttype': 'User', 'parent': ['not in', [actor, *owned_users]]}):
        blockers.append('مجوز اختصاصی نقش به کاربر خارج از محدوده متصل است؛ حذف خودکار مجاز نیست.')
    if any(frappe.db.get_value('ASOUD Access Assignment', row['name'], 'user') not in [actor, *owned_users]
           for row in groups['ASOUD Access Assignment']):
        blockers.append('نقش اختصاصی به حساب دیگری دسترسی داده است؛ حذف این دسترسی بدون بررسی مجاز نیست.')
    groups['User Permission'] = rows('User Permission', {'allow': 'Company', 'for_value': ['in', names or ['']]})
    # Do not erase operational records: a real linked record blocks the whole reset.
    allowed = set(COMPANY_DATA) | set(NATIVE_COMPANY_DATA) | {'Company'}
    links = frappe.get_all('DocField', filters={'fieldtype': 'Link', 'options': 'Company'}, fields=['parent', 'fieldname'])
    links += frappe.get_all('Custom Field', filters={'fieldtype': 'Link', 'options': 'Company'}, fields=['dt as parent', 'fieldname'])
    seen = set()
    for link in links:
        if link.parent in allowed or link.parent in seen:
            continue
        meta = frappe.get_meta(link.parent)
        if meta.istable or meta.issingle or meta.is_virtual:
            continue
        if frappe.db.exists(link.parent, {link.fieldname: ['in', names or ['']]}):
            blockers.append(f'اطلاعات عملیاتی یا وابستگی پشتیبانی‌نشده وجود دارد: {frappe._(link.parent)}')
            seen.add(link.parent)
    # Native HR dependencies without a direct company link must not be orphaned.
    for link in frappe.get_all('DocField', filters={'fieldtype': 'Link', 'options': 'Employee'}, fields=['parent', 'fieldname']):
        if link.parent in allowed or link.parent in seen:
            continue
        meta = frappe.get_meta(link.parent)
        if not meta.istable and not meta.issingle and not meta.is_virtual and frappe.db.exists(
                link.parent, {link.fieldname: ['in', employee_names or ['']]}):
            blockers.append(f'پرسنل دارای سوابق وابسته است: {frappe._(link.parent)}')
            seen.add(link.parent)
    # Delete tree children first; never clear an outside employee/role parent link.
    for doctype, parent_field in (('Employee', 'reports_to'), ('ASOUD Role Definition', 'parent_role')):
        indexed = {r['name']: r for r in groups[doctype]}
        parents = {r.name: r.get(parent_field) for r in frappe.get_all(doctype,
            filters={'name': ['in', list(indexed) or ['']]}, fields=['name', parent_field], limit_page_length=LIMIT)}
        ordered = []
        while parents:
            leaves = [name for name in parents if name not in set(parents.values())]
            if not leaves:
                blockers.append('رابطهٔ دوری در اطلاعات وجود دارد؛ بازنشانی خودکار ممکن نیست.')
                break
            for name in leaves:
                ordered.append(indexed[name])
                parents.pop(name)
        if not parents:
            groups[doctype] = ordered
    # Account identity/profile token participates in the stale-preview check.
    profile = frappe.db.get_value('User', actor, 'modified')
    state_token = frappe.db.get_value('ASOUD Account State', actor, 'modified')
    digest = hashlib.sha256(json.dumps([actor, groups, str(profile), str(state_token)], sort_keys=True, default=str).encode()).hexdigest()
    return groups, list(dict.fromkeys(blockers)), digest


def preview():
    actor = access()
    job = frappe.cache.get_value(f'asoud_setup_reset_latest:{actor}')
    if job:
        receipt = _receipt(job)
        if not receipt or receipt.get('state') in {'queued', 'running'}:
            return {'job': job}
    groups, blockers, digest = _collect(actor)
    token = frappe.generate_hash(length=40)
    frappe.cache.set_value(f'asoud_setup_reset:{token}', {'actor': actor, 'digest': digest}, expires_in_sec=300)
    return {'token': token, 'companies': [r['name'] for r in groups['Company']],
        'counts': {key: len(value) for key, value in groups.items() if value},
        'blockers': blockers, 'preserved': PRESERVED}


def _execute(actor, expected_digest):
    access()
    frappe.db.sql('select name from tabRole where name=%s for update', ('System Manager',))
    groups, blockers, digest = _collect(actor)
    if blockers or expected_digest != digest:
        frappe.throw('اطلاعات یا وابستگی‌ها تغییر کرده‌اند؛ پیش‌نمایش تازه را بررسی کنید.')
    frappe.db.savepoint('asoud_setup_reset')
    try:
        settings = frappe.get_single('ASOUD Settings')
        companies = [r['name'] for r in groups['Company']]
        if settings.first_office_company in companies:
            for field in ('first_office_company', 'first_office_created_by', 'first_office_created_on'):
                settings.set(field, None)
            settings.save(ignore_permissions=True)
        # Break the form/revision cycle through the existing storage boundary.
        from asoud_erp.api.v1.forms import store
        for row in groups['ASOUD Form']:
            doc = frappe.get_doc('ASOUD Form', row['name'])
            doc.active_revision = None
            store(doc)
        for row in groups['Fiscal Year']:
            year = frappe.get_doc('Fiscal Year', row['name'])
            remaining = [r for r in year.companies if r.company not in companies]
            if remaining:
                year.set('companies', remaining)
                year.save()
            else:
                if frappe.db.get_single_value('Global Defaults', 'current_fiscal_year') == year.name:
                    frappe.db.set_single_value('Global Defaults', 'current_fiscal_year', None)
                frappe.delete_doc('Fiscal Year', year.name, ignore_permissions=True)
        for row in groups['ASOUD Access Assignment']:
            frappe.delete_doc('ASOUD Access Assignment', row['name'], ignore_permissions=True)
        user = frappe.get_doc('User', actor)
        identity = (user.name, user.username, user.email)
        if user.role_profile_name in [r['name'] for r in groups['Role Profile']]:
            user.role_profile_name = None
        user.set('roles', [r for r in user.roles if r.role not in {item['name'] for item in groups['Role']}])
        user.first_name, user.last_name, user.mobile_no = 'مدیر سیستم', None, None
        for field in ('phone', 'birth_date', 'gender', 'bio', 'location', 'user_image'):
            user.set(field, None)
        user.save(ignore_permissions=True)  # Identity, username, native password hash and roles are not rewritten.
        if (user.name, user.username, user.email) != identity:
            frappe.throw('شناسهٔ ورود مدیر نباید هنگام بازنشانی تغییر کند؛ عملیات متوقف شد.')
        state = account_state.ensure(actor, lock=True)
        state.admin_profile_completed_on = None
        state.mobile_verified = state.email_verified = 0
        state.save(ignore_permissions=True)
        order = ('ASOUD Access Assignment', 'ASOUD Office Role Assignment', 'ASOUD Personnel Record',
            'ASOUD Organization Chart', 'ASOUD Workflow Transition', 'ASOUD Workflow Stage',
            'ASOUD Workflow Definition', 'ASOUD Form Revision', 'ASOUD Form', 'ASOUD Document Template',
            'ASOUD Party Profile', 'Employee', 'Department', 'ASOUD Company Setup', 'User Permission',
            'ASOUD Account Token', 'ASOUD Account State', 'User', 'ASOUD Role Definition',
            'Role Profile', 'Custom DocPerm', 'Role', 'Company')
        for doctype in order:
            for row in groups.get(doctype, []):
                if frappe.db.exists(doctype, row['name']):
                    # Explicit authenticated reset authority; business/link guards are never bypassed.
                    frappe.delete_doc(doctype, row['name'], ignore_permissions=True)
        security_audit.record('onboarding.reset', target_type='User', target=actor,
            details={'counts': {key: len(value) for key, value in groups.items()}, 'credentials_preserved': True})
        # A mandatory durable receipt shares the deletion transaction. Unlike
        # best-effort audit logging, failure here must roll the reset back.
        receipt = security_audit.build_row(actor=actor, action='onboarding.reset.completed',
            target_type='Setup Reset', target=frappe.flags.asoud_setup_reset_job,
            occurred_on=now_datetime(), details={'credentials_preserved': True})
        frappe.get_doc(receipt).insert(ignore_permissions=True)
    except Exception:
        frappe.db.rollback(save_point='asoud_setup_reset')
        frappe.clear_messages()
        frappe.throw('بازنشانی به دلیل وابستگی یا قاعدهٔ حذف متوقف شد؛ هیچ حذف جزئی تأیید نشد. مدیر سرور باید وابستگی را بررسی کند.')
    frappe.clear_cache(user=actor)
    return {'reset': True}


def _receipt(job):
    return frappe.cache.get_value(f'asoud_setup_reset_job:{job}')


def _save_receipt(job, actor, state, message='', digest=None):
    receipt = {'job': job, 'actor': actor, 'state': state, 'message': message,
        'issued_on': now_datetime().isoformat()}
    if digest:
        receipt['digest'] = digest
    frappe.cache.set_value(f'asoud_setup_reset_job:{job}', receipt, expires_in_sec=RECEIPT_TTL)


def _committed(job, actor):
    # Locking current read, not an old repeatable-read snapshot: a worker can
    # commit between polling the receipt and querying its native queue state.
    return bool(frappe.db.sql('select name from `tabASOUD Security Audit` where action=%s '
        'and actor=%s and target_type=%s and target=%s and result=%s limit 1 lock in share mode',
        ('onboarding.reset.completed', actor, 'Setup Reset', job, 'success')))


def status(job=None, preview_token=None):
    actor = access(require_enabled=False)
    if preview_token is not None:
        if not isinstance(preview_token, str) or len(preview_token) != 40:
            frappe.throw('شناسهٔ پیش‌نمایش برای پیگیری معتبر نیست.')
        authorization = frappe.cache.get_value(f'asoud_setup_reset_authorization:{preview_token}')
        if not authorization or authorization.get('actor') != actor:
            frappe.throw('عملیات پذیرفته‌شده‌ای برای این پیش‌نمایش پیدا نشد؛ موفقیتی تأیید نشده است.')
        job = authorization['job']
    if not isinstance(job, str) or not 20 <= len(job) <= 80:
        frappe.throw('شناسهٔ پیگیری بازنشانی معتبر نیست.')
    if _committed(job, actor):
        return {'job': job, 'state': 'completed', 'message': 'بازنشانی سرور ثبت شده است.'}
    receipt = _receipt(job)
    if not receipt or receipt.get('actor') != actor:
        frappe.throw('وضعیت این عملیات در دسترس نیست؛ هیچ موفقیتی تأیید نشده است. مدیر سرور باید بررسی کند.')
    if receipt.get('state') in {'queued', 'running'}:
        from frappe.utils.background_jobs import get_job_status

        queue_state = get_job_status(f'asoud-setup-reset-{job}')
        if queue_state in {'failed', 'stopped', 'canceled', 'finished'}:
            if _committed(job, actor):
                return {'job': job, 'state': 'completed', 'message': 'بازنشانی سرور ثبت شده است.'}
            _save_receipt(job, actor, 'failed', 'پردازش متوقف شد و رسید تکمیل وجود ندارد؛ پیش‌نمایش تازه و وضعیت سرور را بررسی کنید.')
            if frappe.cache.get_value(BUSY_KEY) == job:
                frappe.cache.delete_value(BUSY_KEY)
            receipt = _receipt(job)
        elif receipt['state'] == 'queued':
            receipt['message'] = 'در انتظار پردازش سرور؛ پردازشگر صف باید فعال باشد.'
    return {key: receipt.get(key) for key in ('job', 'state', 'message')}


def perform(token=None, password=None, confirmation=None, backup_confirmed=0):
    actor = access()
    if not isinstance(password, str) or not password or confirmation != 'شروع دوباره' or cint(backup_confirmed) != 1:
        frappe.throw('رمز حساب، تأیید نسخهٔ پشتیبان و عبارت «شروع دوباره» لازم است.')
    # Fresh verification is explicitly rate limited; secret is never queued.
    rate_key = f'asoud_setup_reset_password:{actor}'
    if cint(frappe.cache.get_value(rate_key)) >= 8:
        frappe.throw('تلاش‌های ناموفق زیاد است؛ ده دقیقه دیگر دوباره تلاش کنید.')
    try:
        check_password(actor, password)
    except frappe.AuthenticationError:
        frappe.cache.set_value(rate_key, cint(frappe.cache.get_value(rate_key)) + 1, expires_in_sec=600)
        raise
    frappe.cache.delete_value(rate_key)
    with frappe.cache.lock('asoud_setup_reset_authorize', timeout=30, blocking_timeout=3):
        previous = frappe.cache.get_value(f'asoud_setup_reset_latest:{actor}')
        if previous:
            receipt = _receipt(previous)
            if not receipt or receipt.get('state') in {'queued', 'running'}:
                return {'job': previous}
        if frappe.cache.get_value(BUSY_KEY):
            frappe.throw('بازنشانی دیگری روی سرور در حال اجراست؛ پس از پایان دوباره تلاش کنید.')
        if not isinstance(token, str) or len(token) != 40:
            frappe.throw('پیش‌نمایش بازنشانی معتبر نیست.')
        stored = frappe.cache.get_value(f'asoud_setup_reset:{token}')
        if not stored or stored.get('actor') != actor:
            frappe.throw('پیش‌نمایش بازنشانی منقضی شده است؛ دوباره دریافت کنید.')
        groups, blockers, digest = _collect(actor)
        if blockers or stored.get('digest') != digest:
            frappe.throw('اطلاعات تغییر کرده‌اند؛ پیش‌نمایش تازه را بررسی کنید.')
        job = frappe.generate_hash(length=40)
        _save_receipt(job, actor, 'queued', digest=digest)
        frappe.cache.set_value(f'asoud_setup_reset_authorization:{token}',
            {'actor': actor, 'job': job}, expires_in_sec=RECEIPT_TTL)
        frappe.cache.set_value(f'asoud_setup_reset_latest:{actor}', job, expires_in_sec=RECEIPT_TTL)
        frappe.cache.delete_value(f'asoud_setup_reset:{token}')
        try:
            frappe.enqueue('asoud_erp.services.setup_reset.run', job=job,
                job_id=f'asoud-setup-reset-{job}', queue='long', timeout=900)
        except Exception:
            _save_receipt(job, actor, 'failed', 'صف پردازش در دسترس نیست؛ هیچ بازنشانی اجرا نشد.')
            raise
    return {'job': job}


def run(job):
    """Trusted worker entry; not whitelisted and contains no password."""
    receipt = _receipt(job)
    if not receipt or receipt.get('state') != 'queued':
        return
    actor = receipt['actor']
    if (now_datetime() - get_datetime(receipt['issued_on'])).total_seconds() > 300:
        _save_receipt(job, actor, 'failed', 'تأیید بازنشانی پیش از شروع پردازش منقضی شد؛ دوباره پیش‌نمایش و تأیید کنید.')
        return
    previous_user = frappe.session.user
    committed = False
    try:
        with frappe.cache.lock('asoud_setup_reset_site', timeout=1200, blocking_timeout=3):
            frappe.set_user(actor)
            access()
            frappe.flags.asoud_setup_reset_worker = True
            frappe.flags.asoud_setup_reset_job = job
            frappe.cache.set_value(BUSY_KEY, job, expires_in_sec=1200)
            _save_receipt(job, actor, 'running')
            try:
                frappe.db.rollback()  # Fresh snapshot after the application write barrier.
                _execute(actor, receipt['digest'])
                frappe.db.commit()
                committed = True
                _save_receipt(job, actor, 'completed', 'بازنشانی ثبت شد؛ نام کاربری و رمز مدیر حفظ شدند.')
            except Exception:
                if not committed:
                    frappe.db.rollback()
                    frappe.clear_messages()
                    _save_receipt(job, actor, 'failed',
                        'بازنشانی متوقف و تغییرات این عملیات برگردانده شد؛ وابستگی‌ها و پیش‌نمایش را دوباره بررسی کنید.')
            finally:
                frappe.cache.delete_value(BUSY_KEY)
                frappe.flags.asoud_setup_reset_worker = False
    except Exception:
        if not committed:
            frappe.db.rollback()
            _save_receipt(job, actor, 'failed', 'شروع بازنشانی ممکن نشد؛ دسترسی مدیر، صف و قفل سرور را بررسی کنید.')
    finally:
        frappe.set_user(previous_user)


def guard_write(doc=None, method=None):
    if not cint(frappe.conf.get(CONFIG)):
        return
    # Also check at commit: a request validated before the worker's barrier must
    # not commit stale setup writes while deletion is running.
    frappe.db.before_commit.add(_guard_commit)
    _guard_commit()


def _guard_commit():
    if not getattr(frappe.flags, 'asoud_setup_reset_worker', False) and frappe.cache.get_value(BUSY_KEY):
        frappe.throw('بازنشانی راه‌اندازی در حال انجام است؛ ثبت اطلاعات موقتاً متوقف است.')


def guard_request():
    if not cint(frappe.conf.get(CONFIG)):
        return
    request = getattr(frappe.local, 'request', None)
    path = getattr(request, 'path', '')
    allowed = ('/api/method/asoud_erp.api.v1.setup_reset.status',
        # Authorization/enqueue only: deletion never runs in the HTTP request.
        '/api/method/asoud_erp.api.v1.setup_reset.perform',
        '/api/method/asoud_erp.api.v1.session.logout', '/api/method/logout')
    if path in allowed:
        return
    frappe.db.before_commit.add(_guard_commit)
    if frappe.cache.get_value(BUSY_KEY):
        frappe.throw('بازنشانی راه‌اندازی در حال انجام است؛ کمی بعد دوباره تلاش کنید.')


def guard_job(method=None, kwargs=None, transaction_type=None):
    if not cint(frappe.conf.get(CONFIG)) or method == 'asoud_erp.services.setup_reset.run':
        return
    frappe.db.before_commit.add(_guard_commit)
    _guard_commit()
