"""Route a submitted form entry, not another editable task form."""
import copy
import json

import frappe

from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_submission_policy import normalize, request_mode, require_record_only_policy

DEFINITION = 'ASOUD Workflow Definition'
ENTRY = 'ASOUD Form Entry'


def fixed_definition(schema, company):
    require_company(company)
    name = schema.get('workflow')
    row = frappe.db.get_value(DEFINITION, name, ['company', 'target_doctype'], as_dict=True) if isinstance(name, str) else None
    if not row:
        frappe.throw('گردش‌کار انتخاب‌شده وجود ندارد؛ مدیر باید اتصال فرم را اصلاح کند.')
    if row.company != company or row.target_doctype != 'ASOUD Workflow Request':
        frappe.throw('گردش‌کار انتخاب‌شده باید از نوع درخواست و متعلق به همین دفتر باشد.')
    # Authorize scope before locking; repeat under lock for concurrent changes.
    workflow = frappe.get_doc(DEFINITION, name, for_update=True)
    if workflow.company != company or workflow.target_doctype != 'ASOUD Workflow Request':
        frappe.throw('گردش‌کار انتخاب‌شده باید از نوع درخواست و متعلق به همین دفتر باشد.')
    if workflow.status != 'Active' or workflow.readiness_status != 'Ready':
        frappe.throw('گردش‌کار انتخاب‌شده فعال و آماده نیست؛ ارسال فرم انجام نشد.')
    return workflow


def fixed_start_error(workflow, form=None, *, start=False, legacy_form=False):
    """Design-time compatibility with the two existing runtime entry paths."""
    if workflow.get('source_form') and (not form or workflow.source_form != form.name):
        return 'این گردش‌کار فقط از فرم مبدأ خودش شروع می‌شود؛ گردش سازگار با این فرم را انتخاب کنید.'
    if workflow.get('source_form') and workflow.source_revision != form.active_revision:
        return 'نسخهٔ اتصال فرم مبدأ گردش‌کار معتبر نیست؛ ابتدا اتصال را اصلاح کنید.'
    if start is False:
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': workflow.name,
            'stage_type': 'Start'}, ['name', 'config_json'], as_dict=True)
    if not start:
        return 'گردش‌کار انتخاب‌شده مرحلهٔ شروع معتبر ندارد.'
    try:
        config = json.loads(start.config_json or '{}')
    except (ValueError, TypeError):
        return 'تنظیمات شروع گردش‌کار معتبر نیست؛ ابتدا آن را اصلاح کنید.'
    if not isinstance(config, dict):
        return 'تنظیمات شروع گردش‌کار معتبر نیست؛ ابتدا آن را اصلاح کنید.'
    if config.get('start_settings_version') == 1:
        if config.get('trigger_type') != 'Document Event' or not workflow.get('source_form'):
            return 'نحوهٔ شروع این گردش‌کار با ارسال از داخل فرم سازگار نیست؛ تنظیمات شروع را بررسی کنید.'
    if not workflow.get('source_form'):
        from asoud_erp.api.v1.workflow_request import _form_stage_or_none

        if legacy_form is False:
            legacy_form = _form_stage_or_none(workflow.name)
        if (not workflow.allow_user_submission or not legacy_form or
                legacy_form.workflow_definition != workflow.name):
            return 'این گردش‌کار ورودی معتبر برای ارسال درخواست از فرم ندارد.'
        try:
            values = json.loads(legacy_form.config_json or '{}')
        except (ValueError, TypeError):
            return 'تنظیمات ورودی گردش‌کار معتبر نیست؛ ابتدا آن را اصلاح کنید.'
        if not isinstance(values, dict) or not isinstance(values.get('form_fields', []), list):
            return 'تنظیمات ورودی گردش‌کار معتبر نیست؛ ابتدا آن را اصلاح کنید.'
    return ''


def bind(definition, stage, config, *, revision_configs=None):
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
    rows = frappe.db.sql('select name, config_json from `tabASOUD Workflow Stage` '
        'where workflow_definition=%s and name!=%s limit 201 for update', (definition, stage), as_dict=True)
    if len(rows) > 200:
        frappe.throw('تعداد مراحل برای اتصال فرم بیش از حد مجاز است.')
    # Only the atomic form publication service supplies this batch. The normal
    # designer API still validates the persisted configurations without overrides.
    others = [json.dumps(revision_configs[row.name]) if revision_configs and row.name in revision_configs
        else row.config_json for row in rows]
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
        legacy_default = bool(schema.get('workflow')) and request_mode(schema) is None
        if not others and not legacy_default and mode == 'Available' and old_source != form.name:
            mode = 'Default'
        if mode == 'Default' and (legacy_default or any(
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


def publish_revision(form, revision, previous_revision):
    """Rebind existing routing metadata, under the caller's publication savepoint.

    The form row is locked. The candidate active revision is transaction-local;
    another submission can only see the complete commit or the previous version.
    """
    schema = json.loads(revision.schema_json)
    mode = request_mode(schema)
    if mode not in {'Fixed', 'Conditional'}:
        return
    if mode == 'Fixed':
        chosen = fixed_definition(schema, form.company)
        if not chosen.get('source_form'):
            return
        definitions = [chosen.name]
    else:
        records = frappe.db.sql('select name, company, source_form, source_revision, status, readiness_status '
            'from `tabASOUD Workflow Definition` '
            'where source_form=%s and status!=%s order by name limit 201 for update',
            (form.name, 'Archived'), as_dict=True)
        metadata = {row.name: row for row in records}
        definitions = list(metadata)
        if len(definitions) > 200:
            frappe.throw('تعداد گردش‌کارهای مرتبط بیش از حد مجاز است.')
        configs = routing_configs(definitions, current=True)
        selected = []
        defaults = 0
        for name in definitions:
            doc = metadata[name]
            route_mode = configs[name]['mode']
            if route_mode not in {'Default', 'Conditional', 'Available'}:
                frappe.throw('روش انتخاب گردش‌کار مرتبط معتبر نیست؛ نسخهٔ عملیاتی فرم حفظ شد.')
            if route_mode == 'Default':
                defaults += 1
                if doc.status != 'Active' or doc.readiness_status != 'Ready':
                    frappe.throw('گردش‌کار پیش‌فرض فعال و آماده نیست؛ نسخهٔ عملیاتی فرم حفظ شد.')
            if route_mode == 'Default' or (route_mode == 'Conditional' and
                    doc.status == 'Active' and doc.readiness_status == 'Ready'):
                selected.append(name)
        if defaults > 1:
            frappe.throw('بیش از یک گردش‌کار پیش‌فرض وجود دارد؛ نسخهٔ عملیاتی فرم حفظ شد.')
        if not selected:
            frappe.throw('هیچ مسیر معتبر و آماده‌ای برای انتشار فرم مشروط وجود ندارد؛ نسخهٔ عملیاتی حفظ شد.')
        definitions = selected
    configs = routing_configs(definitions, current=True)
    if mode == 'Fixed':
        metadata = {chosen.name: chosen}
    for name in definitions:
        doc = metadata[name]
        if doc.company != form.company or doc.source_form != form.name or doc.source_revision != previous_revision:
            frappe.throw('اتصال نسخهٔ قبلی گردش‌کار سازگار نیست؛ نسخهٔ عملیاتی فرم حفظ شد.')
        if frappe.db.exists('ASOUD Workflow Instance', {'workflow_definition': name, 'status': 'Running'}):
            frappe.throw('تا پایان گردش‌های در حال اجرا، انتشار نسخهٔ متصل جدید مجاز نیست.')
        rows = configs[name]['stages']
        if len(rows) > 200:
            frappe.throw('تعداد مراحل بیش از حد مجاز است.')
        updates = {}
        for row in rows:
            config = json.loads(row.config_json or '{}')
            source = config.get('submission_source')
            if source:
                if source.get('form') != form.name or source.get('revision') != previous_revision:
                    frappe.throw('اتصال مراحل به نسخهٔ قبلی یکسان نیست؛ نسخهٔ عملیاتی فرم حفظ شد.')
                config['submission_source'] = {**source, 'revision': revision.name}
                updates[row.name] = config
        if not updates:
            frappe.throw('تنظیمات اتصال گردش‌کار به نسخهٔ فرم کامل نیست؛ نسخهٔ عملیاتی حفظ شد.')
        stage = next(iter(updates))
        # Existing bind retains permission, company, system-template and running
        # instance guards. Stage.save retains native history/editability guards.
        bind(name, stage, updates[stage], revision_configs=updates)
        for stage, config in updates.items():
            target = frappe.get_doc('ASOUD Workflow Stage', stage)
            target.check_permission('write')
            target.config_json = json.dumps(config, ensure_ascii=False)
            # The existing controller explicitly permits guarded internal writes
            # with ignore_permissions. Scope, write permission and absence of
            # Running instances were checked above; only server-owned binding
            # metadata changes here, never stage design/routes or user payload.
            # All other native validators (including historical task protection)
            # still execute. Raw/Desk design writes retain the Active guard.
            target.save(ignore_permissions=True)
        from asoud_erp.services.workflow_lifecycle import require_activation_ready

        updated = frappe.get_doc(DEFINITION, name)
        error = fixed_start_error(updated, form)
        if error:
            frappe.throw(error)
        require_activation_ready(updated)


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


def conditional_gate(definition):
    """True when a Condition stage sits immediately after the single Start.

    Read-only structural check (no locks, no binding validation) used to refuse
    saving a Conditional start route on a live workflow that has no gate yet.
    """
    stages = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition},
        fields=['name', 'stage_type'], limit_page_length=201)
    starts = [row for row in stages if row.stage_type == 'Start']
    if len(starts) != 1:
        return False
    edges = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition,
        'from_stage': starts[0].name}, fields=['to_stage'], limit_page_length=2)
    if len(edges) != 1:
        return False
    return any(row.name == edges[0].to_stage and row.stage_type == 'Condition' for row in stages)


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
    schema = json.loads(revision.schema_json)
    selection_mode = request_mode(schema)
    try:
        require_record_only_policy(selection_mode)
    except ValueError as error:
        frappe.throw(str(error))
    if selection_mode == 'RecordOnly':
        return None  # Only reachable once an authoritative exemption is supported.
    if selection_mode == 'Fixed':
        workflow = fixed_definition(schema, form.company)
        if workflow.get('source_form'):
            if workflow.source_form != form.name or workflow.source_revision != revision.name:
                frappe.throw('اتصال گردش‌کار انتخاب‌شده به فرم یا نسخهٔ جاری سازگار نیست؛ مدیر باید آن را اصلاح کند.')
            return workflow.name
        # Reuse the existing request/mapping path, without evaluating another rule.
        return None
    if not frappe.get_meta(DEFINITION).has_field('source_form'):
        if selection_mode == 'Conditional':
            frappe.throw('انتخاب مشروط در این نسخهٔ سرور در دسترس نیست.')
        return None
    # Read without FOR UPDATE: route() is a read-only routing decision.
    # Design changes are serialized by bind(); instance creation by start_workflow_instance.
    rows = frappe.db.sql('select name, company, status, readiness_status, source_revision '
        'from `tabASOUD Workflow Definition` where source_form=%s and status!=%s '
        'order by name limit 201', (form.name, 'Archived'), as_dict=True)
    if not rows:
        if frappe.db.exists(DEFINITION, {'source_form': form.name, 'status': 'Archived'}):
            frappe.throw('گردش‌کار متصل بایگانی شده است؛ مدیر باید اتصال این فرم را اصلاح کند.')
        if selection_mode == 'Conditional':
            frappe.throw('هیچ گردش‌کار معتبری برای انتخاب مشروط این فرم تنظیم نشده است.')
        return None
    if len(rows) > 200 or any(row.company != form.company for row in rows):
        frappe.throw('تنظیمات مسیرهای این فرم معتبر نیست؛ مدیر باید آن‌ها را بررسی کند.')
    from asoud_erp.services.workflow_condition import evaluate_group
    from asoud_erp.services.workflow_submission_policy import choose_route

    # Plain read: no FOR UPDATE on stage rows during a submission.
    configs = routing_configs([row.name for row in rows], current=False)
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
        selected = choose_route(candidates, legacy_default=bool(schema.get('workflow')) and selection_mode != 'Conditional')
        if selection_mode == 'Conditional' and not selected:
            raise ValueError('هیچ مسیر معتبر و آماده‌ای برای ارسال فرم مشروط انتخاب نشد.')
        return selected
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
    saved_schema = json.loads(rev.schema_json)
    if saved_schema.get('kind') == 'Request' and saved_schema.get('workflow_mode') == 'RecordOnly':
        frappe.throw('این ثبت درخواست صریحاً «فقط ثبت فرم» است؛ شروع گردش‌کار از روی آن مجاز نیست.')
    if form.disabled or form.active_revision != rev.name or not forms.allowed(saved_schema, entry.company):
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
