"""Metadata/value adapter for the existing condition stage, not a new engine."""
import json

import frappe

from asoud_erp.services.workflow_condition import guaranteed_predecessors

TYPE_MAP = {
    'Data': 'Text', 'Small Text': 'Text', 'Text': 'Text', 'LongText': 'Text', 'Long Text': 'Text',
    'Short Text': 'Text', 'Link': 'Text', 'User': 'Text', 'Department': 'Text',
    'Int': 'Number', 'Integer': 'Number', 'Number': 'Number', 'Float': 'Number',
    'Decimal': 'Number', 'Currency': 'Number', 'Money': 'Number', 'Formula': 'Number',
    'Date': 'Date', 'Select': 'Select', 'Choice': 'Select',
    'Datetime': 'DateTime', 'DateTime': 'DateTime', 'Time': 'Time',
    'Boolean': 'Boolean', 'Checkbox': 'Boolean', 'Check': 'Boolean',
    'MultiSelect': 'MultiSelect', 'Rating': 'Number', 'Barcode': 'Text', 'System Select': 'Text',
}
# Reference fields the app can render as a picker that stores the stable id.
_VALUE_SOURCE = {'User': 'user', 'Employee': 'employee', 'Department': 'department'}


def _link_doctype(field):
    """The linked DocType of a reference field, or None for non-Link fields."""
    if field.get('fieldtype') == 'Link':
        return field.get('options')
    if field.get('type') == 'Link':
        return field.get('source')
    if field.get('type') in {'User', 'Department', 'Employee'}:
        return field['type']
    if field.get('type') == 'System Select':
        from asoud_erp.services.request_lookup import SOURCE_FIELD_TYPES

        return SOURCE_FIELD_TYPES.get(field.get('source'))
    return None


def assert_editable(definition):
    from asoud_erp.services.request_access import require_company

    workflow = frappe.get_doc('ASOUD Workflow Definition', definition)
    require_company(workflow.company)
    workflow.check_permission('write')
    if workflow.status == 'Active' or frappe.db.exists('ASOUD Workflow Instance',
            {'workflow_definition': definition, 'status': 'Running'}):
        frappe.throw('برای حفظ اجراها، گردش کار را غیرفعال کنید و تا پایان اجراهای جاری منتظر بمانید؛ یا یک کپی مستقل برای طراحی بسازید.')


def _is_money(field):
    # Only a form-builder Money field has a known currency (the company default);
    # a native Currency field's currency is per document (its options name a field).
    return field.get('type') == 'Money'


def original_request_fields(definition):
    from asoud_erp.api.v1.workflow_request import _fields_by_name

    return _fields_by_name(definition)


def _fields(fields, source, stage='', stage_title='', currency=None):
    result = []
    for field in fields:
        kind = TYPE_MAP.get(field.get('type') or field.get('fieldtype'))
        if not kind or field.get('hidden') or field.get('sensitive') or field.get('permlevel', 0):
            continue
        options = field.get('options') or []
        if isinstance(options, str):
            options = [value for value in options.splitlines() if value]
        if kind in {'Select', 'MultiSelect'} and (not isinstance(options, list) or not options):
            continue
        labels = {**(field.get('option_labels') or {}), **{
            str(value.get('value', value.get('id', ''))): str(value.get('label', ''))
            for value in options if isinstance(value, dict)}}
        options = [str(value.get('value', value.get('id', ''))) if isinstance(value, dict) else str(value) for value in options]
        key = field.get('key') or field.get('fieldname')
        if not key:
            continue
        link = _link_doctype(field)
        if field.get('type') == 'System Select' and link and not frappe.db.exists('DocType', link):
            # Composite/virtual lookups are not native scalar references. Do not
            # invent a DocType or offer a picker that cannot validate its ids.
            continue
        result.append(dict(source_kind=source, source_stage=stage, stage_title=stage_title,
            source_field=key, label=field.get('label') or key, field_type=kind,
            options=options if kind in {'Select', 'MultiSelect'} else [], option_labels=labels,
            data_type=field.get('type') or field.get('fieldtype'),
            required=bool(field.get('required') or field.get('reqd')),
            value_source=_VALUE_SOURCE.get(link), link_doctype=link,
            currency=currency if _is_money(field) else None))
    return result


def catalog(definition, stage, *, stage_types=('Condition',)):
    from asoud_erp.services.form_schema import fields

    workflow = frappe.get_doc('ASOUD Workflow Definition', definition)
    stages = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition},
        fields=['name', 'stage_type', 'stage_title', 'config_json'], limit_page_length=201)
    edges = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition},
        fields=['from_stage', 'to_stage'], limit_page_length=1001)
    if len(stages) > 200 or len(edges) > 1000:
        frappe.throw('اندازهٔ طراحی گردش کار بیش از حد مجاز است.')
    current = next((row for row in stages if row.name == stage and row.stage_type in stage_types), None)
    if not current:
        frappe.throw('ایستگاه شرط متعلق به این گردش کار نیست.')
    currency = frappe.get_cached_value('Company', workflow.company, 'default_currency') if workflow.company else None
    if workflow.get('source_revision'):
        revision = frappe.get_doc('ASOUD Form Revision', workflow.source_revision)
        result = _fields(fields(json.loads(revision.schema_json)), 'Original', currency=currency)
    else:
        result = _fields([field.as_dict() for field in frappe.get_meta(workflow.target_doctype).fields], 'Original',
            currency=currency)
        # Legacy request fields are owned by the existing first form task.
        # Keep its original field keys/options, rather than guessing from labels.
        if workflow.target_doctype == 'ASOUD Workflow Request':
            legacy = _fields(original_request_fields(definition), 'Original', currency=currency)
            result = list({row['source_field']: row for row in [*result, *legacy]}.values())
    prior = guaranteed_predecessors(stages, edges, stage)
    for row in stages:
        if row.name not in prior:
            continue
        config = json.loads(row.config_json or '{}')
        if config.get('action_contract_version') == 1:
            if config.get('result_mode') == 'Simple':
                from asoud_erp.services.workflow_user_action_policy import simple_schema

                schema = simple_schema(False, config.get('simple_result_style', 'Outcomes'))
            else:
                schema = config.get('result_schema') or {}
            saved_fields = fields(schema)
        else:
            saved_fields = config.get('form_fields') or []
        result.extend(_fields(saved_fields, 'Stage', row.name, row.stage_title, currency=currency))
    result.extend([
        dict(source_kind='System', source_stage='', source_field='started_by', label='ثبت‌کننده درخواست',
            field_type='Text', options=[], value_source='user', link_doctype='User', currency=None),
        dict(source_kind='System', source_stage='', source_field='started_on', label='تاریخ شروع فرایند',
            field_type='Date', options=[], value_source=None, link_doctype=None, currency=None),
        dict(source_kind='System', source_stage='', source_field='requester_unit', label='واحد سازمانی ثبت‌کننده',
            field_type='Text', options=[], value_source='department', link_doctype='Department', currency=None),
    ])
    for field in result:
        if field.get('link_doctype'):
            field['company'] = workflow.company
    _reference_labels(result, json.loads(current.config_json or '{}'))
    return result


def _reference_labels(available, config):
    """Batch display labels of already selected ids, without exposing other rows."""
    index = {(row['source_kind'], row['source_stage'], row['source_field']): row for row in available}
    groups = {}
    for rule in config.get('conditions', []):
        field = index.get((rule.get('source_kind'), rule.get('source_stage', ''), rule.get('source_field')))
        if field and field.get('link_doctype') and isinstance(rule.get('value'), str):
            groups.setdefault(field['link_doctype'], []).append((field, rule['value']))
    for doctype, selections in groups.items():
        if not frappe.has_permission(doctype, 'read'):
            continue
        meta = frappe.get_meta(doctype)
        title = meta.title_field or 'name'
        filters = {'name': ['in', sorted({value for _, value in selections})]}
        if meta.has_field('company'):
            filters['company'] = selections[0][0]['company']
        rows = frappe.get_list(doctype, filters=filters,
            fields=['name', title] if title != 'name' else ['name'], limit_page_length=len(selections))
        labels = {row.name: row.get(title) or row.name for row in rows}
        for field, value in selections:
            if value in labels:
                field.setdefault('option_labels', {})[value] = labels[value]


def validate_bindings(config, available, *, check_reference_permissions=False):
    index = {(row['source_kind'], row['source_stage'], row['source_field']): row for row in available}
    for number, rule in enumerate(config['conditions'], 1):
        field = index.get((rule['source_kind'], rule['source_stage'], rule['source_field']))
        if not field or field['field_type'] != rule['field_type']:
            raise ValueError(f'شرط {number}: منبع یا فیلد حذف شده یا در این مسیر معتبر نیست.')
        if rule['field_type'] in {'Select', 'MultiSelect'} and rule['operator'] not in {'Is Empty', 'Is Set'} and rule['value'] not in field['options']:
            raise ValueError(f'شرط {number}: مقدار انتخابی در گزینه‌های فیلد وجود ندارد.')
        for key in ('value', 'value_to'):
            if key in rule:
                validate_field_value(field, rule[key])
    # Batch each reference type; never load one native record per predicate.
    references = {}
    for rule in config['conditions']:
        field = index[(rule['source_kind'], rule['source_stage'], rule['source_field'])]
        if field.get('link_doctype') and field.get('company') and rule['operator'] in {'Equals', 'Not Equals'}:
            references.setdefault((field['link_doctype'], field['company']), set()).add(rule['value'])
    for (doctype, company), names in references.items():
        meta = frappe.get_meta(doctype)
        filters = {'name': ['in', sorted(names)]}
        if meta.has_field('company'):
            filters['company'] = company
        if meta.has_field('disabled'):
            filters['disabled'] = 0
        if doctype == 'User':
            filters['enabled'] = 1
        if doctype == 'Employee':
            filters['status'] = 'Active'
        # Saved rules may run for an ordinary requester. Checking an already
        # approved comparison id is not a grant to read that person's record.
        # Design/test callers must additionally have native read permission.
        getter = frappe.get_list if check_reference_permissions else frappe.get_all
        permitted = set(getter(doctype, filters=filters, pluck='name', limit_page_length=len(names)))
        if names - permitted:
            raise ValueError('مقدار مرجع انتخاب‌شده حذف، غیرفعال یا خارج از دسترسی این دفتر است؛ دوباره انتخاب کنید.')


def validate_field_value(field, value):
    """Validate domain values without changing the existing comparison engine."""
    from asoud_erp.services.workflow_condition import condition_value

    if value is None or value == '' or value == []:
        return
    kind = field['field_type']
    if kind in {'Select', 'MultiSelect'}:
        choices = value if isinstance(value, list) else [value]
        if any(choice not in field['options'] for choice in choices):
            raise ValueError('مقدار انتخابی در گزینه‌های فیلد وجود ندارد.')
    if field.get('data_type') in {'Integer', 'Int'}:
        number = condition_value('Number', value)
        if number != number.to_integral_value():
            raise ValueError('مقدار باید عدد صحیح باشد.')


def reference_choices(field, query):
    """Permission-checked native choices for a server-owned field binding."""
    doctype = field['link_doctype']
    meta = frappe.get_meta(doctype)
    filters = {}
    if meta.has_field('company'):
        filters['company'] = field['company']
    if meta.has_field('disabled'):
        filters['disabled'] = 0
    if doctype == 'User':
        filters['enabled'] = 1
    if doctype == 'Employee':
        filters['status'] = 'Active'
    title = meta.title_field or 'name'
    term = f'%{(query or "")[:100]}%'
    rows = frappe.get_list(doctype, filters=filters,
        or_filters={'name': ['like', term], title: ['like', term]},
        fields=['name', title] if title != 'name' else ['name'],
        order_by='name asc', limit_page_length=30)
    return [{'value': row.name, 'label': row.get(title) or row.name} for row in rows]


def resolver(instance, config, available):
    from asoud_erp.services.workflow_step_validation import request_values_for_instance

    native = None
    original = request_values_for_instance(frappe, instance)
    if instance.reference_doctype != 'ASOUD Form Entry' and instance.reference_name:
        native = frappe.get_doc(instance.reference_doctype, instance.reference_name)
        native.check_permission('read')
    needed = tuple({row['source_stage'] for row in config['conditions'] if row['source_kind'] == 'Stage'})
    tasks = frappe.db.sql('''select workflow_stage, response_json from (
        select workflow_stage, response_json,
          ROW_NUMBER() OVER (PARTITION BY workflow_stage ORDER BY completed_on desc, name desc) as rn
        from `tabASOUD Workflow Task` where workflow_instance=%s and status='Completed'
          and workflow_stage in %s) latest where rn=1''', (instance.name, needed), as_dict=True) if needed else []
    stage_values = {}
    for task in tasks:
        stage_values.setdefault(task.workflow_stage, json.loads(task.response_json or '{}'))

    def resolve(rule):
        source, key = rule['source_kind'], rule['source_field']
        if source == 'System':
            if key == 'requester_unit':
                # The requester's unit is their Employee's department, the same rule the
                # notification context uses; a missing unit is an error, never a guess.
                metadata = next((field for field in available if field['source_kind'] == 'System'
                    and field['source_field'] == 'requester_unit'), {})
                if not metadata.get('company'):
                    raise ValueError('دفتر مربوط به واحد سازمانی ثبت‌کننده مشخص نیست.')
                employee = frappe.db.get_value('Employee', {'user_id': instance.started_by,
                    'company': metadata['company'], 'status': 'Active'},
                    'department', as_dict=True)
                if not employee or not employee.get('department'):
                    raise ValueError('واحد سازمانی ثبت‌کننده قابل تعیین نیست.')
                return employee.get('department')
            value = instance.get(key)
            if key == 'started_on' and value:
                from frappe.utils import get_datetime

                try:
                    return get_datetime(value).date()
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValueError('تاریخ شروع فرایند معتبر نیست.') from exc
            return value
        if source == 'Stage':
            values = stage_values.get(rule['source_stage'])
            if values is None:
                raise ValueError('خروجی اقدام قبلی در این اجرای فرایند تولید نشده است.')
        elif key in original:
            return original[key]
        elif native:
            if not native.meta.has_field(key):
                raise ValueError('فیلد سند اصلی دیگر وجود ندارد.')
            return native.get(key)
        else:
            values = original
        if key not in values:
            metadata = next((field for field in available if field['source_kind'] == source
                and field['source_stage'] == rule['source_stage'] and field['source_field'] == key), None)
            if metadata and not metadata.get('required') and (source == 'Stage' or instance.reference_name):
                return None
            raise ValueError('دادهٔ فیلد موردنیاز در این اجرا موجود نیست.')
        return values[key]
    return resolve
