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
        # Current reads after the shared Form lock: repeatable-read snapshots must
        # not let two concurrently-created definitions both become the default.
        others = [row.name for row in frappe.db.sql('select name from `tabASOUD Workflow Definition` '
            'where source_form=%s and name!=%s and status!=%s limit 201 for update',
            (form.name, definition, 'Archived'), as_dict=True)]
        if len(others) > 200:
            frappe.throw('تعداد گردش‌کارهای مرتبط بیش از حد مجاز است.')
        previous = json.loads(frappe.db.get_value('ASOUD Workflow Stage', stage, 'config_json') or '{}')
        mode = config.get('source_route', previous.get('source_route', 'Default' if old_source == form.name else 'Available'))
        if not others and not schema.get('workflow') and mode == 'Available' and old_source != form.name:
            mode = 'Default'
        if mode == 'Default' and (schema.get('workflow') or any(
                value['mode'] == 'Default' for value in routing_configs(others, current=True).values())):
            frappe.throw('این فرم گردش‌کار پیش‌فرض دیگری دارد؛ اتصال مجاز است، اما فقط یک مسیر می‌تواند پیش‌فرض باشد.')
        config['source_route'] = mode
        if source:
            config['submission_source'] = {**chosen, 'title': schema['title'], 'kind': schema['kind']}
        definition_doc.source_form, definition_doc.source_revision = form.name, revision.name
    else:
        definition_doc.source_form = definition_doc.source_revision = None
    definition_doc.flags.submission_source_service = True
    definition_doc.save()


def routing_configs(names, *, current=False):
    if not names:
        return {}
    if current:
        rows = frappe.db.sql('select name, workflow_definition, stage_type, config_json from `tabASOUD Workflow Stage` '
            'where workflow_definition in %s limit 40201 for update', (tuple(names),), as_dict=True)
    else:
        rows = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': ['in', names]},
            fields=['name', 'workflow_definition', 'stage_type', 'config_json'], limit_page_length=40201)
    if len(rows) > 40200:
        frappe.throw('اندازهٔ مسیرهای فرم بیش از حد مجاز است.')
    result = {name: {'mode': 'Default', 'stages': []} for name in names}  # Explicit legacy compatibility.
    for row in sorted(rows, key=lambda value: value.stage_type == 'Start'):
        result[row.workflow_definition]['stages'].append(row)
        config = json.loads(row.config_json or '{}')
        if config.get('submission_source'):
            result[row.workflow_definition]['mode'] = config.get('source_route', 'Default')
    return result


def entry_condition(definition, *, stages=None, edges=None, available=None):
    from asoud_erp.services.workflow_condition import normalize_group

    if stages is None:
        stages = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition},
            fields=['name', 'stage_type', 'config_json'], limit_page_length=201)
    starts = [row for row in stages if row.stage_type == 'Start']
    if edges is None:
        edges = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition,
            'from_stage': starts[0].name if len(starts) == 1 else ''}, fields=['to_stage'], limit_page_length=2)
    gate = next((row for row in stages if len(edges) == 1 and row.name == edges[0].to_stage and row.stage_type == 'Condition'), None)
    if not gate:
        raise ValueError('برای انتخاب مشروط، یک ایستگاه «شرط و مسیر» مستقیماً بعد از شروع قرار دهید.')
    config = normalize_group(json.loads(gate.config_json or '{}'))
    if any(row['source_kind'] != 'Original' for row in config['conditions']):
        raise ValueError('شرط انتخاب گردش‌کار فقط می‌تواند از اطلاعات فرم اصلی استفاده کند.')
    from asoud_erp.services.workflow_condition_binding import catalog, validate_bindings

    validate_bindings(config, catalog(definition, gate.name) if available is None else available)
    return config


def route(form, revision, submitted=None):
    """Called under the native Form row lock, before any submit writes."""
    if not frappe.get_meta(DEFINITION).has_field('source_form'):
        return None
    rows = frappe.db.sql('select name, company, status, readiness_status, source_revision '
        'from `tabASOUD Workflow Definition` where source_form=%s and status!=%s '
        'order by name limit 201 for update', (form.name, 'Archived'), as_dict=True)
    if not rows:
        if frappe.db.exists(DEFINITION, {'source_form': form.name, 'status': 'Archived'}):
            frappe.throw('گردش‌کار متصل بایگانی شده است؛ مدیر باید اتصال این فرم را اصلاح کند.')
        return None
    if len(rows) > 200 or any(row.company != form.company for row in rows):
        frappe.throw('تنظیمات مسیرهای این فرم معتبر نیست؛ مدیر باید آن‌ها را بررسی کند.')
    from asoud_erp.services.workflow_condition import evaluate_group
    from asoud_erp.services.workflow_submission_policy import choose_route

    configs = routing_configs([row.name for row in rows], current=True)
    starts = [stage.name for config in configs.values() for stage in config['stages'] if stage.stage_type == 'Start']
    outgoing = frappe.get_all('ASOUD Workflow Transition', filters={'from_stage': ['in', starts or ['']]},
        fields=['workflow_definition', 'to_stage'], limit_page_length=40201)
    if len(outgoing) > 40200:
        frappe.throw('اندازهٔ مسیرهای فرم بیش از حد مجاز است.')
    from asoud_erp.services.form_schema import fields
    from asoud_erp.services.workflow_condition_binding import _fields

    available = _fields(fields(json.loads(revision.schema_json)), 'Original')
    required = {field['source_field'] for field in available if field.get('required')}
    candidates = []
    try:
        for row in rows:
            mode = configs[row.name]['mode']
            if mode not in {'Available', 'Default', 'Conditional'}:
                raise ValueError('روش انتخاب یکی از گردش‌کارهای مرتبط معتبر نیست؛ مدیر باید تنظیمات شروع را بررسی کند.')
            candidate = {**dict(row), 'mode': mode, 'stale': row.source_revision != revision.name}
            if mode == 'Conditional' and row.status == 'Active' and row.readiness_status == 'Ready':
                if candidate['stale']:
                    raise ValueError('نسخهٔ فرم مسیر مشروط تغییر کرده است؛ اتصال آن را به‌روزرسانی کنید.')
                rules = entry_condition(row.name, stages=configs[row.name]['stages'],
                    edges=[edge for edge in outgoing if edge.workflow_definition == row.name], available=available)
                data = submitted or {}
                if any(rule['source_field'] in required and rule['source_field'] not in data for rule in rules['conditions']):
                    raise ValueError('اطلاعات لازم برای انتخاب مسیر در فرم ثبت نشده است.')
                # Metadata already validated; absent optional fields are genuinely empty.
                candidate['matched'] = evaluate_group(rules, lambda rule: data.get(rule['source_field']))
            candidates.append(candidate)
        return choose_route(candidates, legacy_default=bool(json.loads(revision.schema_json).get('workflow')))
    except ValueError as error:
        frappe.throw(str(error))


def assert_reference(workflow, name, *, lock=True, restarting=False):
    """Explicit owner/form/route authority, never arbitrary Form Entry access."""
    if not isinstance(name, str) or not frappe.db.exists(ENTRY, name):
        frappe.throw('ثبت اصلی فرم پیدا نشد.')
    entry = frappe.get_doc(ENTRY, name, for_update=lock)
    require_company(entry.company)
    roles = set(frappe.get_roles())
    manager_restart = bool(roles.intersection({'System Manager', 'Accounts Manager'}) and workflow.has_permission('write'))
    start_config = {}
    if restarting:
        start_row = frappe.db.get_value('ASOUD Workflow Stage',
            {'workflow_definition': workflow.name, 'stage_type': 'Start'}, ['config_json'], as_dict=True)
        start_config = json.loads(start_row.config_json or '{}') if start_row else {}
        if not manager_restart or not start_config.get('allow_manager_restart'):
            frappe.throw('شروع مجدد فقط توسط مدیر مجاز است.', frappe.PermissionError)
    else:
        if entry.owner != frappe.session.user:
            frappe.throw('شروع گردش‌کار فقط برای ثبت اصلی و متعلق به حساب شما مجاز است.', frappe.PermissionError)
    if entry.company != workflow.company or \
            not workflow.get('source_form') or workflow.source_form != entry.form or \
            workflow.source_revision != entry.revision:
        frappe.throw('شروع گردش‌کار فقط برای ثبت اصلی و متعلق به حساب شما مجاز است.', frappe.PermissionError)
    from asoud_erp.api.v1 import forms

    form = forms.load(entry.form, lock=lock)
    rev = forms.revision(form, entry.revision)
    if form.disabled or form.active_revision != rev.name or not forms.allowed(json.loads(rev.schema_json), entry.company):
        frappe.throw('این فرم در دسترس حساب شما نیست.', frappe.PermissionError)
    existing = frappe.db.get_value('ASOUD Workflow Instance', {'reference_doctype': ENTRY,
        'reference_name': entry.name}, 'workflow_definition', order_by='creation asc')
    if (existing or route(form, rev, values(entry)[1])) != workflow.name:
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
