"""Route a submitted form entry, not another editable task form."""
import copy
import json

import frappe

from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_submission_policy import normalize

DEFINITION = 'ASOUD Workflow Definition'
ENTRY = 'ASOUD Form Entry'


def bind(definition, stage, config):
    from asoud_erp.api.v1 import forms

    source = config.get('submission_source')
    if not frappe.get_meta(DEFINITION).has_field('source_form'):
        if source:
            frappe.throw('ابتدا به‌روزرسانی پایگاه دادهٔ سرور را اجرا کنید.')
        return
    definition_doc = frappe.get_doc(DEFINITION, definition)
    require_company(definition_doc.company)
    definition_doc.check_permission('write')
    old_source = definition_doc.get('source_form')
    # Lock old and proposed forms in a deterministic order before the definition.
    # Form submission takes the same form lock, so source changes cannot race it.
    form_names = sorted({name for name in (old_source, (source or {}).get('form')) if name})
    for name in form_names:
        forms.load(name, edit=True, lock=True)
    definition_doc = frappe.get_doc(DEFINITION, definition, for_update=True)
    if definition_doc.get('source_form') != old_source:
        frappe.throw('اتصال گردش‌کار تغییر کرده است؛ تنظیمات را دوباره دریافت کنید.')
    require_company(definition_doc.company)
    if definition_doc.is_system_template and source:
        frappe.throw('ابتدا یک کپی مستقل از الگوی سیستمی بسازید.')
    rows = frappe.db.sql('select config_json from `tabASOUD Workflow Stage` '
        'where workflow_definition=%s and name!=%s limit 201 for update', (definition, stage), as_dict=True)
    if len(rows) > 200:
        frappe.throw('تعداد مراحل برای اتصال فرم بیش از حد مجاز است.')
    others = [row.config_json for row in rows]
    selected = [json.loads(raw or '{}').get('submission_source') for raw in others]
    selected = [s for s in selected if s]
    if source:
        selected.append(source)
    if any(normalize(item) != normalize(selected[0]) for item in selected):
        frappe.throw('تمام مراحل این گردش‌کار باید به یک نوع درخواست یا سند و نسخهٔ یکسان متصل باشند.')
    chosen = normalize(selected[0]) if selected else None
    if chosen:
        form = forms.load(chosen['form'], edit=True, lock=True)
        if form.company != definition_doc.company or form.disabled or form.active_revision != chosen['revision']:
            frappe.throw('فرم باید منتشرشده، فعال و متعلق به همین دفتر باشد؛ انتخاب را تازه کنید.')
        revision = forms.revision(form, chosen['revision'])
        schema = json.loads(revision.schema_json)
        if schema.get('kind') not in {'Request', 'Document'}:
            frappe.throw('این الگو فرم قابل ارسال نیست؛ یک درخواست یا سند قابل تکمیل را انتخاب کنید.')
        if schema['kind'] == 'Document':
            forms.native_mapping(schema)
        if schema.get('workflow'):
            frappe.throw('این فرم قبلاً مسیر گردش‌کار دارد؛ ابتدا اتصال قبلی آن را از مدیریت فرم اصلاح کنید.')
        if frappe.db.exists(DEFINITION, {'source_form': form.name,
                'name': ['!=', definition], 'status': ['!=', 'Archived']}):
            frappe.throw('این درخواست یا سند قبلاً به گردش‌کار دیگری متصل شده است.')
        if source:
            config['submission_source'] = {**chosen, 'title': schema['title'], 'kind': schema['kind']}
        definition_doc.source_form, definition_doc.source_revision = form.name, revision.name
    else:
        definition_doc.source_form = definition_doc.source_revision = None
    definition_doc.flags.submission_source_service = True
    definition_doc.save()


def route(form, revision):
    """Called under the native Form row lock, before any submit writes."""
    if not frappe.get_meta(DEFINITION).has_field('source_form'):
        return None
    rows = frappe.get_all(DEFINITION, filters={'source_form': form.name, 'status': ['!=', 'Archived']},
        fields=['name', 'company', 'status', 'readiness_status', 'source_revision'], limit_page_length=2)
    if not rows:
        if frappe.db.exists(DEFINITION, {'source_form': form.name, 'status': 'Archived'}):
            frappe.throw('گردش‌کار متصل بایگانی شده است؛ مدیر باید اتصال این فرم را اصلاح کند.')
        return None
    if len(rows) != 1:
        frappe.throw('بیش از یک گردش‌کار به این فرم متصل است؛ مدیر سیستم باید اتصال را اصلاح کند.')
    row = rows[0]
    if row.company != form.company or row.source_revision != revision.name:
        frappe.throw('نسخهٔ فرم تغییر کرده است؛ اتصال گردش‌کار باید توسط مدیر به‌روزرسانی شود.')
    if row.status != 'Active' or row.readiness_status != 'Ready':
        frappe.throw('گردش‌کار متصل هنوز فعال و آماده نیست؛ مدیر سیستم باید طراحی آن را تکمیل کند.')
    return row.name


def assert_reference(workflow, name):
    """Explicit owner/form/route authority, never arbitrary Form Entry access."""
    if not isinstance(name, str) or not frappe.db.exists(ENTRY, name):
        frappe.throw('ثبت اصلی فرم پیدا نشد.')
    entry = frappe.get_doc(ENTRY, name, for_update=True)
    require_company(entry.company)
    if entry.owner != frappe.session.user or entry.company != workflow.company or \
            not workflow.get('source_form') or workflow.source_form != entry.form or \
            workflow.source_revision != entry.revision:
        frappe.throw('شروع گردش‌کار فقط برای ثبت اصلی و متعلق به حساب شما مجاز است.', frappe.PermissionError)
    from asoud_erp.api.v1 import forms

    form = forms.load(entry.form, lock=True)
    rev = forms.revision(form, entry.revision)
    if form.disabled or form.active_revision != rev.name or not forms.allowed(json.loads(rev.schema_json), entry.company):
        frappe.throw('این فرم در دسترس حساب شما نیست.', frappe.PermissionError)
    if route(form, rev) != workflow.name:
        frappe.throw('مسیر ثبت فرم با گردش‌کار انتخاب‌شده سازگار نیست.')
    return entry


def start(entry, definition):
    from asoud_erp.api.v1.workflow_runtime import start_workflow_instance

    return start_workflow_instance(definition, entry.subject, ENTRY, entry.name)['data']['name']


def entry_for_instance(instance):
    if instance.reference_doctype != ENTRY or not instance.reference_name:
        return None
    return frappe.get_doc(ENTRY, instance.reference_name)


def values(entry):
    """Original saved request values; documents are always read from native fields."""
    from asoud_erp.services.form_schema import fields, migrate_schema

    rev = frappe.get_doc('ASOUD Form Revision', entry.revision)
    schema = migrate_schema(json.loads(rev.schema_json))
    result = json.loads(entry.values_json or '{}')
    if entry.reference_doctype and entry.reference_name and schema['kind'] == 'Document':
        native = frappe.get_doc(entry.reference_doctype, entry.reference_name)
        result = {}
        for field in fields(schema):
            key = field.get('native_key')
            if not key:
                continue
            value = native.get(key)
            if field['type'] == 'Table':
                value = [{c['key']: row.get(c['native_key']) for c in field['columns'] if c.get('native_key')}
                    for row in (value or [])]
            result[field['key']] = value
    return schema, result


def sanitized(schema, data):
    """Never return private attachments or declared sensitive values to assignees."""
    schema = copy.deepcopy(schema)
    visible = {}
    for section in schema.get('sections', []):
        safe = []
        for field in section.get('fields', []):
            if field.get('sensitive') or field['type'] in {'File', 'Image', 'Signature'}:
                continue
            item = copy.deepcopy(field)
            for key in ('default', 'default_source', 'fetch_from'):
                item.pop(key, None)
            value = data.get(item['key'])
            if item['type'] == 'Table':
                columns = [c for c in item.get('columns', []) if not c.get('sensitive') and
                    c['type'] not in {'File', 'Image', 'Signature'}]
                keys = {c['key'] for c in columns}
                item['columns'] = columns
                value = [{key: val for key, val in row.items() if key in keys}
                    for row in (value or []) if isinstance(row, dict)]
            safe.append(item)
            visible[item['key']] = value
        section['fields'] = safe
    return schema, visible


def task_snapshot(instance):
    entry = entry_for_instance(instance)
    if not entry:
        return None
    require_company(entry.company)
    schema, data = values(entry)
    # A task assignment alone cannot grant native document read access.
    if schema['kind'] == 'Document':
        frappe.get_doc(entry.reference_doctype, entry.reference_name).check_permission('read')
    schema, data = sanitized(schema, data)
    return {'company': entry.company, 'schema': schema, 'values': data, 'subject': entry.subject}


def instance_permission(instance, user=None, permission_type=None):
    from asoud_erp.services.request_access import company_access

    user = user or frappe.session.user
    if permission_type not in (None, 'read', 'select') or user == 'Guest':
        return False
    entry = entry_for_instance(instance)
    if not entry or not company_access(entry.company, user):
        return False
    if entry.reference_doctype and entry.reference_name and not frappe.has_permission(
            entry.reference_doctype, 'read', entry.reference_name, user=user):
        return False
    return bool(entry.owner == user or {'System Manager', 'HR Manager', 'Accounts Manager'} &
        set(frappe.get_roles(user)) or frappe.db.exists('ASOUD Workflow Task', {
            'workflow_instance': instance.name, 'assigned_to': user}))


def instance_clause(user=None):
    from asoud_erp.services.request_access import company_access

    user = user or frappe.session.user
    companies = [c for c in frappe.get_all('Company', pluck='name') if company_access(c, user)]
    if not companies:
        return "COALESCE(`tabASOUD Workflow Instance`.`reference_doctype`, '') != 'ASOUD Form Entry'"
    scope = ','.join(frappe.db.escape(c) for c in companies)
    actor = frappe.db.escape(user)
    manager = bool({'System Manager', 'HR Manager', 'Accounts Manager'} & set(frappe.get_roles(user)))
    people = '1=1' if manager else (f"e.owner={actor} OR EXISTS (SELECT name FROM `tabASOUD Workflow Task` t "
        f"WHERE t.workflow_instance=`tabASOUD Workflow Instance`.name AND t.assigned_to={actor})")
    return ("(COALESCE(`tabASOUD Workflow Instance`.`reference_doctype`, '') != 'ASOUD Form Entry' OR "
        "`tabASOUD Workflow Instance`.`reference_name` IN (SELECT e.name FROM `tabASOUD Form Entry` e "
        f"WHERE e.company IN ({scope}) AND ({people})))")


def condition_fields(definition):
    from asoud_erp.services.form_schema import fields

    doc = frappe.get_doc(DEFINITION, definition)
    if not doc.get('source_revision'):
        return []
    rev = frappe.get_doc('ASOUD Form Revision', doc.source_revision)
    types = {'Text': 'Data', 'Integer': 'Int', 'Decimal': 'Float', 'Money': 'Currency',
        'Formula': 'Float', 'Date': 'Date', 'DateTime': 'Datetime', 'Time': 'Data',
        'Select': 'Select', 'Boolean': 'Check', 'Checkbox': 'Check', 'Link': 'Link'}
    return [{'fieldname': f['key'], 'label': f.get('label') or f['key'],
        'fieldtype': types[f['type']], 'source': 'Form'}
        for f in fields(json.loads(rev.schema_json)) if f['type'] in types and not f.get('sensitive')]
