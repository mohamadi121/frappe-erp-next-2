"""Shared form API. Published schemas are immutable; document posting stays native."""
import base64
import hashlib
import json
from datetime import date

import frappe
from frappe.utils import now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.form_schema import (
    FETCH_ATTRIBUTES,
    LINK_FILTERS,
    SCOPED_SOURCES,
    SOURCES,
    current_employee,
    default_value,
    fail,
    fetch_value,
    fields,
    migrate_schema,
    parse,
    scope_filters,
    validate_schema,
    validate_values,
)
from asoud_erp.services.record_labels import LABELS
from asoud_erp.services.request_access import require_company

DESIGNERS = ('System Manager', 'HR Manager', 'Accounts Manager', 'Purchase Manager')
NATIVE = {'Journal Entry': {'voucher_type', 'posting_date', 'user_remark', 'accounts'},
          'Material Request': {'material_request_type', 'schedule_date', 'items'}}
CHILDREN = {'accounts': {'account', 'party_type', 'party', 'cost_center', 'project', 'debit_in_account_currency', 'credit_in_account_currency'},
            'items': {'item_code', 'qty', 'uom', 'warehouse', 'schedule_date', 'description'}}


def designer():
    return frappe.session.user == 'Administrator' or bool(set(frappe.get_roles()) & set(DESIGNERS))


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
    from asoud_erp.services.hr_form_catalog import builtin_key
    active = revision(doc) if doc.active_revision else None
    result = {key: doc.get(key) for key in ('name', 'title', 'company', 'kind', 'module_key', 'draft_version', 'active_revision', 'disabled', 'pending_review')}
    result['status'] = 'Inactive' if doc.disabled else 'Pending' if doc.pending_review else 'Published' if active else 'Draft'
    result['version'] = active.version if active else 0
    result['has_changes'] = bool(active and doc.draft_json != active.schema_json)
    key = builtin_key(doc.company, doc.name)
    if key:
        result['builtin_key'] = key
    if schema:
        result['schema'] = migrate_schema(json.loads(doc.draft_json)) if doc.draft_json else {}
    return result


@frappe.whitelist()
def list_forms(company, kind='Request', manage=0):
    from asoud_erp.services.hr_form_catalog import builtin_key, catalog_rows
    require_company(company)
    manage = bool(int(manage))
    if manage:
        require_roles(DESIGNERS)
    result = []
    defaults = []
    names = frappe.get_all('ASOUD Form', filters={'company': company, 'kind': kind}, pluck='name', order_by='modified desc', limit_page_length=500)
    if kind == 'Request':
        # Include all catalog identities even if outside the ordinary list limit:
        # disabled tombstones must not reappear as virtual defaults.
        from asoud_erp.services.hr_form_catalog import catalog, form_name
        identities = [form_name(company, key) for key in catalog()]
        existing = frappe.get_all('ASOUD Form', filters={'company': company, 'name': ['in', identities]}, pluck='name')
        defaults = catalog_rows(company, existing)
        names = list(dict.fromkeys([*names, *existing]))
    for name in names:
        doc = load(name)
        key = builtin_key(company, name)
        if key and doc.disabled:
            continue
        if manage:
            result.append(row(doc, schema=True))
        elif not doc.disabled and doc.active_revision:
            rev = revision(doc)
            schema = migrate_schema(json.loads(rev.schema_json))
            if allowed(schema, company):
                result.append({'name': doc.name, 'title': schema['title'], 'company': company, 'kind': schema['kind'], 'module_key': schema.get('module'), 'category': schema.get('category', ''), 'status': 'Published', 'version': rev.version, **({'builtin_key': key} if key else {})})
    return success([*result, *defaults])


@frappe.whitelist(methods=['POST'])
def open_builtin(company, key, manage=0):
    require_company(company)
    if int(manage):
        require_roles(DESIGNERS)
    from asoud_erp.services.hr_form_catalog import ensure_builtin
    doc = ensure_builtin(company, key)
    if doc.disabled:
        frappe.throw('این قالب از فهرست شرکت حذف شده است.', frappe.PermissionError)
    return get_form(doc.name, manage=manage)


@frappe.whitelist(methods=['POST'])
def remove_builtin(company, key):
    require_roles(('System Manager',))
    require_company(company)
    from asoud_erp.services.hr_form_catalog import ensure_builtin
    doc = ensure_builtin(company, key)
    if not doc.disabled:
        doc.disabled = 1
        doc.draft_version += 1
        store(doc)
        doc.add_comment('Info', 'حذف قالب پیش‌فرض از فهرست شرکت؛ سوابق حفظ شدند.')
    return success({'name': doc.name, 'removed': True})


@frappe.whitelist()
def get_form(name, manage=0, revision_name=None):
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
    schema = parse(schema)
    schema_version = schema.get('schema_version', 1)
    # Existing v1 designs used choice labels in their payload.  Upgrade only v1
    # before validating so v2 still requires its stable client-side identifiers.
    if schema_version is None or (schema_version == 1 and not isinstance(schema_version, bool)):
        schema = migrate_schema(schema)
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
    if schema.get('execution'):
        from asoud_erp.services.form_execution.schema import validate_parameter_fields

        for stage in frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': workflow.name},
                                    fields=['config_json'], limit_page_length=0):
            try:
                validate_parameter_fields(json.loads(stage.config_json or '{}').get('form_fields', []),
                                          schema['execution']['kind'])
            except ValueError as error:
                fail(str(error))
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
def get_link_options(company, source, query='', form=None, filter_field=None, filter_value=None, exclude_self=0):
    require_company(company)
    if source not in SOURCES:
        fail('منبع اطلاعات مجاز نیست.')
    if not designer():
        doc = load(form)
        schema = json.loads(revision(doc).schema_json)
        sources = {f.get('source') for f in fields(schema)} | {c.get('source') for f in fields(schema) for c in f.get('columns', [])}
        if doc.company != company or doc.disabled or not allowed(schema, company) or source not in sources:
            frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
        if int(exclude_self) and not any(
                f.get('source') == 'Employee' and f.get('exclude_self') is True
                for item in fields(schema) for f in [item, *item.get('columns', [])]):
            fail('این فیلد حذف خود را پشتیبانی نمی‌کند.')
    meta = frappe.get_meta(source)
    employee = current_employee(company)
    scoped = source in SCOPED_SOURCES
    if scoped:
        if source in {'Attendance', 'Asset'} and not employee:
            return success([], {'reason': 'no_employee'})
        filters = scope_filters(source, company, employee)
    else:
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
    if source == 'Employee' and int(exclude_self) and employee:
        filters['name'] = ['!=', employee]
    title = meta.title_field or 'name'
    attributes = list(FETCH_ATTRIBUTES.get(source, ()))
    database_attributes = [key for key in attributes if key != 'employee_count']
    query = query[:100]
    getter = frappe.get_all if scoped else frappe.get_list
    rows = getter(source, filters=filters, or_filters={title: ['like', f'%{query}%'], 'name': ['like', f'%{query}%']},
                  fields=['name', f'{title} as label', *database_attributes], limit_page_length=30)
    if not attributes:
        return success(rows)
    employee_counts = {}
    if source == 'Training Event' and rows:
        counts = frappe.get_all(
            'Training Event Employee', filters={'parent': ['in', [row['name'] for row in rows]],
                                                'parenttype': 'Training Event'},
            fields=['parent', 'count(name) as count'], group_by='parent')
        employee_counts = {row.parent: row.count for row in counts}
    for row in rows:
        extra = {key: fetch_value(row.pop(key, None)) for key in database_attributes}
        if source == 'Training Event' and 'employee_count' in attributes:
            extra['employee_count'] = employee_counts.get(row['name'], 0)
        row['label'] = LABELS[source](row | extra) if source in LABELS else row['label']
        row['extra'] = extra
    return success(rows)


def _may_read_schedule(company, form, field):
    """Colleague schedules: HR/System managers, or a form the caller fills with an exclude_self Employee link."""
    if frappe.session.user == 'Administrator' or {'System Manager', 'HR Manager'} & set(frappe.get_roles()):
        return True
    if not form:
        return False
    doc = load(form)
    if doc.company != company or doc.disabled or not doc.active_revision:
        return False
    schema = json.loads(revision(doc).schema_json)
    if not allowed(schema, company):
        return False
    return any(
        item.get('source') == 'Employee' and item.get('exclude_self') is True and (not field or item.get('key') == field)
        for top in fields(schema) for item in [top, *top.get('columns', [])] if item.get('type') == 'Link')


@frappe.whitelist()
def employee_schedule(company, from_date, to_date, employee=None, form=None, field=None):
    """Effective HRMS schedule for the caller, an in-scope colleague or any employee for HR managers."""
    from asoud_erp.services.employee_schedule import MAX_DAYS, build_schedule, parse_range

    require_company(company)
    own_employee = current_employee(company)
    target = employee or own_employee
    if not target:
        fail('پرونده پرسنلی شما ثبت نشده است.')
    if target != own_employee and not _may_read_schedule(company, form, field):
        frappe.throw('دسترسی به برنامه شیفت این همکار مجاز نیست.', frappe.PermissionError)
    employee_doc = frappe.db.get_value('Employee', target, ['company', 'status', 'default_shift', 'holiday_list'],
                                       as_dict=True)
    if not employee_doc or employee_doc.company != company or employee_doc.status != 'Active':
        fail('پرسنل انتخاب‌شده در این دفتر فعال نیست.')
    try:
        start, end, days = parse_range(from_date, to_date)
    except ValueError as error:
        fail(str(error))
    rows = frappe.get_all(
        'Shift Assignment',
        filters={'employee': target, 'docstatus': 1, 'status': 'Active', 'start_date': ['<=', end]},
        or_filters=[['end_date', '>=', start], ['end_date', 'is', 'not set']],
        fields=['name', 'shift_type', 'start_date', 'end_date'],
        order_by='start_date asc, creation asc',
        limit_page_length=200,
    )
    shift_names = {row.shift_type for row in rows if row.shift_type}
    if employee_doc.default_shift:
        shift_names.add(employee_doc.default_shift)
    shift_rows = frappe.get_all('Shift Type', filters={'name': ['in', list(shift_names)]},
                                fields=['name', 'start_time', 'end_time'], limit_page_length=200) if shift_names else []
    shifts = {row.name: {'start_time': fetch_value(row.start_time), 'end_time': fetch_value(row.end_time)}
              for row in shift_rows}
    holiday_list = employee_doc.holiday_list or frappe.db.get_value('Company', company, 'default_holiday_list')
    holiday_rows = frappe.get_all('Holiday', filters={'parent': holiday_list, 'holiday_date': ['between', [start, end]]},
                                  pluck='holiday_date', limit_page_length=MAX_DAYS) if holiday_list else []
    assignments = [{'shift_type': row.shift_type, 'start_date': row.start_date, 'end_date': row.end_date}
                   for row in rows]
    data = build_schedule(start, end, assignments, employee_doc.default_shift, set(holiday_rows), shifts)
    return success(data, {'from_date': start.isoformat(), 'to_date': end.isoformat(), 'days': days, 'max_days': MAX_DAYS})


def _validate_shift_request(schema, values, company):
    """Recheck day-by-day shift proposals immediately before request creation."""
    from asoud_erp.services.employee_schedule import covers
    schedule_fields = [field for field in fields(schema) if field['type'] == 'Schedule']
    if not schedule_fields:
        return
    tables = []
    for field in fields(schema):
        if field['type'] != 'Table':
            continue
        date_column = next((column for column in field['columns'] if column['type'] == 'Date'), None)
        shift_column = next((column for column in field['columns']
                             if column['type'] == 'Link' and column.get('source') == 'Shift Type'), None)
        if date_column and shift_column:
            tables.append((field, date_column, shift_column))
    proposed = []
    for table, date_column, shift_column in tables:
        for row in values.get(table['key'], []):
            day_value, shift_value = row.get(date_column['key']), row.get(shift_column['key'])
            if day_value and shift_value:
                proposed.append((day_value, shift_value))
    if not proposed:
        return
    employee = current_employee(company)
    if not employee:
        fail('پرونده پرسنلی شما ثبت نشده است.')
    dates = [date.fromisoformat(value[0]) for value in proposed]
    rows = frappe.get_all(
        'Shift Assignment',
        filters={'employee': employee, 'docstatus': 1, 'status': 'Active', 'start_date': ['<=', max(dates)]},
        or_filters=[['end_date', '>=', min(dates)], ['end_date', 'is', 'not set']],
        fields=['shift_type', 'start_date', 'end_date'],
        limit_page_length=200,
    )
    default_shift = frappe.db.get_value('Employee', employee, 'default_shift')
    for day_text, requested_shift in proposed:
        day = date.fromisoformat(day_text)
        covering = [row for row in rows if covers(row, day)]
        if len(covering) > 1:
            fail('برای این روز بیش از یک تخصیص شیفت ثبت‌شده وجود دارد؛ ابتدا تداخل برنامه را برطرف کنید.')
        current = covering[0].shift_type if covering else default_shift
        if current and requested_shift == current:
            fail('شیفت پیشنهادی در این روز با شیفت فعلی یکسان است.')


@frappe.whitelist(methods=['POST'])
def upload_file(form, filename, content):
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


def _validate_execution_submit(schema, values, company):
    """Let the executor refuse a request before it is stored (optional validate_submit hook)."""
    from asoud_erp.services.form_execution import EXECUTORS
    from asoud_erp.services.form_execution.parameters import collect_parameters

    kind = (schema.get('execution') or {}).get('kind')
    hook = getattr(EXECUTORS.get(kind), 'validate_submit', None)
    if not hook:
        return
    params = collect_parameters(fields(schema), values, [])
    try:
        hook(params, {'company': company, 'employee': current_employee(company),
                      'user': frappe.session.user})
    except ValueError as error:
        fail(str(error))


@frappe.whitelist(methods=['POST'])
def submit_form(name, revision_name, subject, values, request_key):
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
    _validate_shift_request(schema, checked, doc.company)
    _validate_execution_submit(schema, checked, doc.company)
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
    if reference_type == 'ASOUD Workflow Request':
        from asoud_erp.api.v1.workflow_request import refresh_search_text

        refresh_search_text(reference_name)
    if reference_type == 'ASOUD Workflow Request' and schema.get('execution'):
        from asoud_erp.services.request_templates.lifecycle import dispatch_native_document

        dispatch_native_document(reference_name)
    return success({'name': entry.name, 'reference_name': reference_name, 'reference_doctype': reference_type})


@frappe.whitelist()
def list_my_entries(company):
    require_company(company)
    return success(frappe.get_all('ASOUD Form Entry', filters={'company': company, 'owner': frappe.session.user}, fields=['name', 'form', 'revision', 'subject', 'creation', 'reference_doctype', 'reference_name'], order_by='creation desc', limit_page_length=200))


@frappe.whitelist()
def get_entry(name):
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


@frappe.whitelist()
def execution_kinds():
    require_roles(DESIGNERS)
    from asoud_erp.services.form_execution import EXECUTORS

    return success([{'kind': kind, 'label': executor.LABEL, 'parameters': executor.PARAMETERS}
                    for kind, executor in sorted(EXECUTORS.items())])
