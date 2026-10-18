"""Shared form API. Published schemas are immutable; document posting stays native."""
import base64
import hashlib
import json

import frappe
from frappe.utils import now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.form_schema import (
    LINK_FILTERS,
    SOURCES,
    default_value,
    fail,
    fields,
    migrate_schema,
    parse,
    validate_schema,
    validate_values,
)
from asoud_erp.services.request_access import require_company

DESIGNERS = ('System Manager', 'HR Manager', 'Accounts Manager', 'Purchase Manager')
FORM_USERS = DESIGNERS + ('Accounts User', 'HR User', 'Purchase User', 'Sales User', 'Stock User')
NATIVE = {'Journal Entry': {'voucher_type', 'posting_date', 'user_remark', 'accounts'},
          'Material Request': {'material_request_type', 'schedule_date', 'items'}}
CHILDREN = {'accounts': {'account', 'party_type', 'party', 'cost_center', 'project', 'debit_in_account_currency', 'credit_in_account_currency'},
            'items': {'item_code', 'qty', 'uom', 'warehouse', 'schedule_date', 'description'}}


def designer():
    return frappe.session.user == 'Administrator' or bool(set(frappe.get_roles()) & set(DESIGNERS))


def require_form_user():
    require_roles(FORM_USERS)


def store(doc):
    doc.flags.form_service = True
    is_new = doc.is_new() or not doc.name or not frappe.db.exists(doc.doctype, doc.name)
    return doc.insert(ignore_permissions=True, set_name=doc.name if doc.doctype == 'ASOUD Form' else None) if is_new else doc.save(ignore_permissions=True)


def load(name, edit=False, lock=False):
    doc = frappe.get_doc('ASOUD Form', name, for_update=lock)
    require_company(doc.company)
    if edit:
        require_roles(DESIGNERS)
    return doc


def revision(doc, name=None):
    name = name or doc.active_revision
    if not name:
        fail('فرم هنوز منتشر نشده است.')
    rev = frappe.get_doc('ASOUD Form Revision', name)
    if rev.form != doc.name:
        fail('نسخه متعلق به این فرم نیست.')
    return rev


def allowed(schema, company):
    require_company(company)
    access = schema.get('access', {})
    mode = access.get('mode', 'all')
    roles = bool(set(access.get('roles', [])) & set(frappe.get_roles()))
    department = frappe.db.get_value('Employee', {'user_id': frappe.session.user, 'company': company, 'status': 'Active'}, 'department')
    unit = bool(department and department in access.get('departments', []))
    return {'all': True, 'roles': roles, 'departments': unit, 'and': roles and unit, 'or': roles or unit}.get(mode, False)


def row(doc, schema=False):
    active = revision(doc) if doc.active_revision else None
    result = {key: doc.get(key) for key in ('name', 'title', 'company', 'kind', 'module_key', 'draft_version', 'active_revision', 'disabled', 'pending_review')}
    result['status'] = 'Inactive' if doc.disabled else 'Pending' if doc.pending_review else 'Published' if active else 'Draft'
    result['version'] = active.version if active else 0
    result['has_changes'] = bool(active and doc.draft_json != active.schema_json)
    if schema:
        result['schema'] = migrate_schema(json.loads(doc.draft_json)) if doc.draft_json else {}
    return result


@frappe.whitelist()
def list_forms(company, kind='Request', manage=0):
    require_form_user()
    require_company(company)
    manage = bool(int(manage))
    if manage:
        require_roles(DESIGNERS)
    result = []
    for name in frappe.get_all('ASOUD Form', filters={'company': company, 'kind': kind}, pluck='name', order_by='modified desc', limit_page_length=500):
        doc = load(name)
        if manage:
            result.append(row(doc, schema=True))
        elif not doc.disabled and doc.active_revision:
            rev = revision(doc)
            schema = migrate_schema(json.loads(rev.schema_json))
            if allowed(schema, company):
                result.append({'name': doc.name, 'title': schema['title'], 'company': company, 'kind': schema['kind'], 'module_key': schema.get('module'), 'category': schema.get('category', ''), 'status': 'Published', 'version': rev.version})
    return success(result)


@frappe.whitelist()
def get_form(name, manage=0, revision_name=None):
    require_form_user()
    doc = load(name, edit=bool(int(manage)))
    if int(manage) and not revision_name:
        return success(row(doc, schema=True))
    rev = revision(doc, revision_name)
    schema = migrate_schema(json.loads(rev.schema_json))
    if not int(manage) and (doc.disabled or rev.name != doc.active_revision or not allowed(schema, doc.company)):
        frappe.throw('این فرم در دسترس نیست.', frappe.PermissionError)
    for field in fields(schema):
        if field.get('default_source'):
            field['default'] = default_value(field, doc.company)
    return success({'name': doc.name, 'company': doc.company, 'schema': schema, 'revision': rev.name, 'version': rev.version})


@frappe.whitelist(methods=['POST'])
def save_form(company, schema, name=None, expected_version=0, client_id=None):
    require_roles(DESIGNERS)
    require_company(company)
    schema = validate_schema(schema)
    schema['schema_version'] = 2
    # Stable client ID makes retrying a timed-out create idempotent.
    if not name:
        if not client_id or not 8 <= len(client_id) <= 100:
            fail('شناسه ذخیره معتبر نیست.')
        name = hashlib.sha256(f'{company}:{frappe.session.user}:{client_id}'.encode()).hexdigest()[:32]
    frappe.get_doc('User', frappe.session.user, for_update=True)
    encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    if frappe.db.exists('ASOUD Form', name):
        doc = load(name, edit=True, lock=True)
        if doc.company != company:
            fail('دفتر فرم قابل تغییر نیست.')
        if doc.draft_json == encoded:
            return success(row(doc, True))
        if int(expected_version) != doc.draft_version:
            fail('فرم توسط فرد دیگری تغییر کرده است؛ نسخه جدید را دریافت کنید.')
        if doc.active_revision:
            previous = json.loads(revision(doc).schema_json)
            if previous['kind'] != schema['kind']:
                fail('نوع فرم منتشرشده قابل تغییر نیست؛ فرم مشابه جدید بسازید.')
            def types(items, prefix=''):
                result = {}
                for field in items:
                    path = prefix + field['key']
                    result[path] = field['type']
                    result.update(types(field.get('columns', []), path + '.'))
                return result
            old_types = types(fields(previous))
            if any(key in old_types and old_types[key] != kind for key, kind in types(fields(schema)).items()):
                fail('برای تغییر نوع فیلد منتشرشده، فیلد جدید با شناسه جدید ایجاد کنید.')
        doc.draft_version += 1
    else:
        doc = frappe.get_doc({'doctype': 'ASOUD Form', 'name': name, 'company': company, 'draft_version': 1})
        doc.flags.name_set = True
    doc.update({'title': schema['title'], 'kind': schema['kind'], 'module_key': schema.get('module', 'General'), 'draft_json': encoded, 'pending_review': 0})
    store(doc)
    return success(row(doc, True))


def native_mapping(schema):
    target = schema.get('target')
    if target not in NATIVE:
        fail('نوع سند پشتیبانی نمی‌شود.')
    meta = frappe.get_meta(target)
    used = set()
    for field in fields(schema):
        key = field.get('native_key')
        if not key:
            continue
        if key not in NATIVE[target] or key in used:
            fail('نگاشت فیلد سند تکراری یا غیرمجاز است.')
        used.add(key)
        df = meta.get_field(key)
        if not df or df.read_only:
            fail('فیلد سیستمی قابل تغییر نیست.')
        if df.fieldtype == 'Link' and (field['type'] != 'Link' or field.get('source') != df.options):
            fail('نگاشت اطلاعات سیستم با منبع فیلد سند سازگار نیست.')
        if field['type'] == 'Table':
            if df.fieldtype != 'Table':
                fail('نگاشت جدول معتبر نیست.')
            child_used = set()
            for col in field['columns']:
                child = col.get('native_key')
                if not child:
                    continue
                if child not in CHILDREN.get(key, set()) or child in child_used:
                    fail('نگاشت ستون سند معتبر نیست.')
                child_df = frappe.get_meta(df.options).get_field(child)
                if not child_df or child_df.read_only:
                    fail('ستون سیستمی قابل تغییر نیست.')
                if child_df.fieldtype == 'Link' and (col['type'] != 'Link' or col.get('source') != child_df.options):
                    fail('منبع ستون با اطلاعات سند سازگار نیست.')
                child_used.add(child)
        elif df.fieldtype == 'Table':
            fail('فیلد مقصد به جدول نیاز دارد.')
    required = {'accounts', 'posting_date'} if target == 'Journal Entry' else {'items', 'material_request_type'}
    if not required.issubset(used):
        fail('نگاشت فیلدهای اصلی سند کامل نیست.')


def workflow_mapping(schema, company):
    if not schema.get('workflow'):
        return
    from asoud_erp.api.v1.workflow_request import _fields
    workflow = frappe.get_doc('ASOUD Workflow Definition', schema['workflow'])
    if workflow.company != company or workflow.target_doctype != 'ASOUD Workflow Request' or workflow.status != 'Active' or workflow.readiness_status != 'Ready':
        fail('گردش‌کار درخواست باید فعال، آماده و متعلق به همین دفتر باشد.')
    targets = {f['key']: f for f in _fields(workflow)}
    used = set()
    for field in fields(schema):
        key = field.get('workflow_key')
        if not key:
            continue
        if key not in targets or key in used:
            fail('نگاشت فیلد درخواست نامعتبر یا تکراری است.')
        if field['type'] in {'File', 'Image', 'Signature'} or any(c['type'] in {'File', 'Image', 'Signature'} for c in field.get('columns', [])):
            fail('نگاشت پیوست به گردش‌کار فعلاً از مسیر استاندارد درخواست انجام می‌شود.')
        used.add(key)
        if field['type'] == 'Table':
            columns = {c['key'] for c in targets[key].get('columns', [])}
            if any(c.get('workflow_key') not in columns for c in field.get('columns', [])):
                fail('ستون‌های جدول به ستون‌های گردش‌کار نگاشت نشده‌اند.')
    required = {key for key, f in targets.items() if f.get('required') and not f.get('default_value') and not f.get('default_source') and f.get('type') != 'Auto'}
    if not required.issubset(used):
        fail('نگاشت فیلدهای الزامی گردش‌کار کامل نیست.')


@frappe.whitelist(methods=['POST'])
def transition(name, action, expected_version, note=''):
    doc = load(name, edit=True, lock=True)
    if int(expected_version) != doc.draft_version:
        fail('نسخه فرم تغییر کرده است؛ دوباره دریافت کنید.')
    if action == 'review':
        validate_schema(doc.draft_json)
        doc.pending_review = 1
    elif action == 'publish':
        require_roles(('System Manager',))
        schema = validate_schema(doc.draft_json)
        for department in schema.get('access', {}).get('departments', []):
            if frappe.db.get_value('Department', department, 'company') != doc.company:
                fail('واحد سازمانی متعلق به دفتر فرم نیست.')
        if schema['kind'] == 'Document':
            native_mapping(schema)
        if schema['kind'] == 'Request':
            workflow_mapping(schema, doc.company)
        if doc.active_revision and revision(doc).schema_json == doc.draft_json:
            doc.disabled = 0
            doc.pending_review = 0
        else:
            version = int(frappe.db.count('ASOUD Form Revision', {'form': doc.name})) + 1
            rev = store(frappe.get_doc({'doctype': 'ASOUD Form Revision', 'form': doc.name, 'version': version,
                'schema_json': doc.draft_json, 'published_by': frappe.session.user, 'published_on': now_datetime(), 'change_note': note[:500]}))
            doc.active_revision = rev.name
            doc.disabled = 0
            doc.pending_review = 0
    elif action in {'disable', 'enable'}:
        require_roles(('System Manager',))
        if not doc.active_revision:
            fail('فرم هنوز منتشر نشده است.')
        doc.disabled = int(action == 'disable')
    else:
        fail('عملیات معتبر نیست.')
    doc.draft_version += 1
    store(doc)
    doc.add_comment('Info', f'{action}: {note[:500]}')
    return success(row(doc, True))


@frappe.whitelist()
def get_history(name):
    load(name, edit=True)
    return success(frappe.get_all('ASOUD Form Revision', filters={'form': name}, fields=['name', 'version', 'published_by', 'published_on', 'change_note'], order_by='version desc', limit_page_length=200))


@frappe.whitelist()
def get_validation(company, schema, values=None):
    require_company(company)
    require_roles(DESIGNERS)
    normalized = validate_schema(schema)
    if normalized['kind'] == 'Document':
        native_mapping(normalized)
    if normalized['kind'] == 'Request':
        workflow_mapping(normalized, company)
    result = {'valid': True}
    if values is not None:
        result['values'] = validate_values(normalized, values, company)
    return success(result)


@frappe.whitelist()
def get_options(company):
    require_company(company)
    require_roles(DESIGNERS)
    from asoud_erp.api.v1.workflow_request import _fields
    workflows = []
    for name in frappe.get_all('ASOUD Workflow Definition', filters={'company': company, 'target_doctype': 'ASOUD Workflow Request', 'status': 'Active', 'readiness_status': 'Ready'}, pluck='name', limit_page_length=200):
        workflow = frappe.get_doc('ASOUD Workflow Definition', name)
        workflows.append({'name': name, 'title': workflow.workflow_title, 'fields': _fields(workflow)})
    return success({'roles': frappe.get_all('Role', filters={'disabled': 0}, pluck='name', limit_page_length=500), 'workflows': workflows,
        'departments': frappe.get_list('Department', filters={'company': company}, pluck='name', limit_page_length=500),
        'can_publish': 'System Manager' in frappe.get_roles() or frappe.session.user == 'Administrator',
        'targets': list(NATIVE), 'sources': sorted(SOURCES)})


@frappe.whitelist()
def get_link_options(company, source, query='', form=None, filter_field=None, filter_value=None):
    require_form_user()
    require_company(company)
    if source not in SOURCES:
        fail('منبع اطلاعات مجاز نیست.')
    if not designer():
        doc = load(form)
        schema = json.loads(revision(doc).schema_json)
        sources = {f.get('source') for f in fields(schema)} | {c.get('source') for f in fields(schema) for c in f.get('columns', [])}
        if doc.company != company or doc.disabled or not allowed(schema, company) or source not in sources:
            frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    meta = frappe.get_meta(source)
    filters = {'company': company} if meta.has_field('company') else {}
    if filter_field:
        if filter_field not in LINK_FILTERS.get(source, set()):
            fail('فیلتر منبع اطلاعات مجاز نیست.')
        if filter_value is None or filter_value == '':
            return success([])
        filters[filter_field] = filter_value
    if meta.has_field('disabled'):
        filters['disabled'] = 0
    if meta.has_field('is_group'):
        filters['is_group'] = 0
    title = meta.title_field or 'name'
    return success(frappe.get_list(source, filters=filters, or_filters={title: ['like', f'%{query[:100]}%'], 'name': ['like', f'%{query[:100]}%']}, fields=['name', f'{title} as label'], limit_page_length=30))


@frappe.whitelist(methods=['POST'])
def upload_file(form, filename, content):
    require_form_user()
    from frappe.utils.file_manager import save_file
    doc = load(form)
    if doc.disabled or not allowed(json.loads(revision(doc).schema_json), doc.company):
        frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    if not isinstance(content, str) or not isinstance(filename, str) or len(content) > 14 * 1024 * 1024:
        fail('فایل بیش از حد بزرگ است یا معتبر نیست.')
    try:
        data = base64.b64decode(content, validate=True)
    except ValueError:
        fail('فایل معتبر نیست.')
    if len(data) > 10 * 1024 * 1024:
        fail('فایل بیش از حد بزرگ است.')
    suffix = filename.rsplit('.', 1)[-1].lower()
    if suffix not in {'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'csv', 'docx'}:
        fail('نوع فایل مجاز نیست.')
    filename = filename.replace('\\', '/').split('/')[-1]
    file = save_file(filename, data, None, None, is_private=1)
    return success({'name': file.name, 'label': file.file_name})


@frappe.whitelist(methods=['POST'])
def submit_form(name, revision_name, subject, values, request_key):
    require_form_user()
    doc = load(name, lock=True)
    if not 8 <= len(request_key) <= 100 or not 3 <= len(subject.strip()) <= 140:
        fail('عنوان یا شناسه ثبت معتبر نیست.')
    raw = parse(values)
    fingerprint = hashlib.sha256(json.dumps([name, revision_name, subject, raw], sort_keys=True).encode()).hexdigest()
    key = hashlib.sha256(f'{frappe.session.user}:{doc.company}:{request_key}'.encode()).hexdigest()
    existing = frappe.db.get_value('ASOUD Form Entry', {'request_key': key}, ['name', 'fingerprint', 'owner'], as_dict=True)
    if existing:
        if existing.owner != frappe.session.user or existing.fingerprint != fingerprint:
            fail('شناسه ثبت قبلاً با اطلاعات دیگری استفاده شده است.')
        return success({'name': existing.name})
    rev = revision(doc, revision_name)
    # Open, incomplete forms are never silently migrated to the new version.
    if doc.disabled or rev.name != doc.active_revision:
        fail('نسخه فرم تغییر کرده یا غیرفعال شده است؛ فرم جدید را دریافت کنید.')
    schema = migrate_schema(json.loads(rev.schema_json))
    if not allowed(schema, doc.company):
        frappe.throw('ثبت این فرم مجاز نیست.', frappe.PermissionError)
    checked = validate_values(schema, raw, doc.company)
    reference_type = reference_name = ''
    if schema['kind'] == 'Request' and schema.get('workflow'):
        from asoud_erp.api.v1.workflow_request import create_request
        workflow_mapping(schema, doc.company)
        payload = {}
        for field in fields(schema):
            target_key = field.get('workflow_key')
            if not target_key or field['key'] not in checked:
                continue
            value = checked[field['key']]
            if field['type'] in {'File', 'Image', 'Signature'}:
                fail('پیوست متصل به گردش‌کار باید از مسیر استاندارد پیوست درخواست ثبت شود؛ این نگاشت پشتیبانی نمی‌شود.')
            if field['type'] == 'Table':
                value = [{c['workflow_key']: row.get(c['key']) for c in field['columns'] if c.get('workflow_key')} for row in (value or [])]
            payload[target_key] = value
        result = create_request(company=doc.company, workflow_definition=schema['workflow'], subject=subject, values=payload, request_id=key)
        reference_type = 'ASOUD Workflow Request'
        reference_name = result['data']['name']
    if schema['kind'] == 'Document':
        native_mapping(schema)
        payload = {'doctype': schema['target'], 'company': doc.company}
        for field in fields(schema):
            key = field.get('native_key')
            if not key or field['key'] not in checked:
                continue
            value = checked[field['key']]
            if field['type'] == 'Table':
                value = [{c['native_key']: item.get(c['key']) for c in field['columns'] if c.get('native_key')} for item in (value or [])]
            payload[key] = value
        native = frappe.get_doc(payload).insert()  # Native permissions + controller. Never auto-submit.
        reference_type, reference_name = native.doctype, native.name
    entry = store(frappe.get_doc({'doctype': 'ASOUD Form Entry', 'form': doc.name, 'revision': rev.name, 'company': doc.company,
        'subject': subject.strip(), 'values_json': json.dumps(checked, ensure_ascii=False) if schema['kind'] == 'Request' else '{}',
        'reference_doctype': reference_type, 'reference_name': reference_name, 'request_key': key, 'fingerprint': fingerprint}))
    return success({'name': entry.name, 'reference_name': reference_name, 'reference_doctype': reference_type})


@frappe.whitelist()
def list_my_entries(company):
    require_form_user()
    require_company(company)
    return success(frappe.get_all('ASOUD Form Entry', filters={'company': company, 'owner': frappe.session.user}, fields=['name', 'form', 'revision', 'subject', 'creation', 'reference_doctype', 'reference_name'], order_by='creation desc', limit_page_length=200))


@frappe.whitelist()
def get_entry(name):
    require_form_user()
    entry = frappe.get_doc('ASOUD Form Entry', name)
    require_company(entry.company)
    if entry.owner != frappe.session.user and frappe.session.user != 'Administrator' and 'System Manager' not in frappe.get_roles():
        frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    rev = frappe.get_doc('ASOUD Form Revision', entry.revision)
    schema = json.loads(rev.schema_json)
    values = json.loads(entry.values_json or '{}')
    schema = migrate_schema(schema, values=values)
    result = {'name': entry.name, 'subject': entry.subject, 'schema': schema, 'values': values, 'version': rev.version}
    if entry.reference_name:
        native = frappe.get_doc(entry.reference_doctype, entry.reference_name)
        native.check_permission('read')
        result['reference_name'] = native.name
        if entry.reference_doctype in NATIVE:
            result['current_native_values'] = True
            native_values = {}
            for field in fields(result['schema']):
                target = field.get('native_key')
                if not target:
                    continue
                value = native.get(target)
                if field['type'] == 'Table':
                    value = [{c['key']: row.get(c['native_key']) for c in field['columns'] if c.get('native_key')} for row in (value or [])]
                native_values[field['key']] = value
            result['values'] = native_values
    return success(result)
