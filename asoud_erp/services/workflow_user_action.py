"""Use existing native task rows, form validation and workflow activities."""
import json

import frappe

from asoud_erp.services.workflow_user_action_policy import normalize_action, simple_schema

_PRESENTATION = object()


def company_for(definition):
    from asoud_erp.services.request_access import require_company

    company = frappe.db.get_value('ASOUD Workflow Definition', definition, 'company')
    require_company(company)
    return company


def form_schema(definition, config, *, designing=False, history=False):
    from asoud_erp.api.v1 import forms

    company = company_for(definition)
    if history and isinstance(config.get('result_schema'), dict):
        schema = config['result_schema']
        if not forms.allowed(schema, company):
            frappe.throw('دسترسی به اطلاعات فرم این اقدام مجاز نیست.', frappe.PermissionError)
        return schema, (config.get('result_form') or {}).get('form'), company
    if config['result_mode'] == 'Simple':
        return simple_schema(config['allow_add_attachments'], config.get('simple_result_style', 'Outcomes')), None, company
    source = config['result_form']
    if not frappe.db.exists('ASOUD Form', source['form']) or not frappe.db.exists('ASOUD Form Revision',
            {'name': source['revision'], 'form': source['form']}):
        frappe.throw('فرم ثبت نتیجه یا نسخهٔ انتخاب‌شده دیگر در دسترس نیست؛ تنظیمات را بازبینی کنید.')
    form = forms.load(source['form'], edit=designing)
    if form.kind == 'Stage':
        # A Stage form is the supplementary-stage concept (bound via `supplementary_form`);
        # it must not be reused as a task result form.
        frappe.throw('فرم ثبت نتیجه نمی‌تواند فرم تکمیلی مرحله باشد؛ فرم دیگری انتخاب کنید.')
    if form.company != company or form.disabled or not form.active_revision or (designing and form.active_revision != source['revision']):
        frappe.throw('فرم ثبت نتیجه باید فعال و نسخهٔ منتشرشدهٔ همین دفتر باشد؛ انتخاب را تازه کنید.')
    schema = forms.migrate_schema(json.loads(forms.revision(form, source['revision']).schema_json))
    if not designing and not forms.allowed(schema, company):
        frappe.throw('اجازهٔ استفاده از فرم ثبت نتیجه را ندارید.', frappe.PermissionError)
    return schema, form.name, company


def employee_fields(definition):
    from asoud_erp.api.v1 import forms

    source = frappe.db.get_value('ASOUD Workflow Definition', definition, 'source_revision')
    if not source:
        return set()
    schema = json.loads(frappe.db.get_value('ASOUD Form Revision', source, 'schema_json') or '{}')
    return {field['key'] for field in forms.fields(schema) if field['type'] == 'Link' and field.get('source') == 'Employee' and not field.get('sensitive')}


def validate_design(definition, config):
    try:
        normalized = normalize_action(config)
    except ValueError as error:
        frappe.throw(str(error))
    if not normalized:
        return
    schema, _, company = form_schema(definition, normalized, designing=True)
    if not normalized['allow_add_attachments']:
        from asoud_erp.api.v1.forms import fields

        if any(item.get('required') and item.get('type') in ('File', 'Image', 'Signature')
                for field in fields(schema) for item in [field, *field.get('columns', [])]):
            frappe.throw('فرم ثبت نتیجه پیوست الزامی دارد؛ امکان افزودن پیوست را روشن کنید یا فرم دیگری انتخاب کنید.')
    config['result_schema'] = schema
    config.update(normalized)
    rule = config['assignment_rule']
    if rule.get('department') and not frappe.db.exists('Department', {'name': rule['department'], 'company': company, 'disabled': 0}):
        frappe.throw('واحد سازمانی فعالِ همین دفتر را انتخاب کنید.')
    if rule.get('role') and not frappe.db.exists('Role', {'name': rule['role'], 'disabled': 0}):
        frappe.throw('نقش انتخاب‌شده وجود ندارد یا غیرفعال است.')
    if rule.get('person') and not frappe.db.exists('Employee', {'name': rule['person'], 'company': company,
            'department': rule['department'], 'status': 'Active', 'user_id': ['is', 'set']}):
        frappe.throw('فرد انتخاب‌شده باید پرسنل فعال و دارای حساب در همان واحد باشد.')
    if rule.get('subject') == 'Form Employee' and rule.get('employee_field') not in employee_fields(definition):
        frappe.throw('فیلد پرسنلی را از فرم اصلیِ متصل به شروع انتخاب کنید.')


def users_for(stage, instance):
    from asoud_erp.services.request_access import company_access
    from asoud_erp.services.workflow_step_validation import request_values_for_instance

    config = json.loads(stage.config_json or '{}')
    rule = config['assignment_rule']
    company = company_for(instance.workflow_definition)
    basis = rule['basis']
    department = rule.get('department')
    if department and not frappe.db.exists('Department', {'name': department, 'company': company, 'disabled': 0}):
        frappe.throw('واحد مسئول حذف یا غیرفعال شده است.')
    employee = None
    initiator_user = None
    if basis in ('Subject', 'Subject Unit', 'Manager'):
        if rule.get('subject') == 'Form Employee':
            if rule.get('employee_field') not in employee_fields(instance.workflow_definition):
                frappe.throw('فیلد شخص مبنا دیگر معتبر نیست.')
            employee_id = request_values_for_instance(frappe, instance).get(rule['employee_field'])
            employee = frappe.db.get_value('Employee', {'name': employee_id, 'company': company, 'status': 'Active'},
                ['name', 'user_id', 'department', 'reports_to'], as_dict=True) if isinstance(employee_id, str) else None
        else:
            initiator_user = instance.started_by
            employee = frappe.db.get_value('Employee', {'user_id': initiator_user, 'company': company, 'status': 'Active'},
                ['name', 'user_id', 'department', 'reports_to'], as_dict=True)
        if basis == 'Subject':
            candidates = [employee.user_id if employee else initiator_user]
        elif not employee:
            frappe.throw('برای شخص مبنا، پروندهٔ فعال پرسنلی در این دفتر پیدا نشد.')
        elif basis == 'Manager':
            candidates = [frappe.db.get_value('Employee', {'name': employee.reports_to, 'company': company,
                'status': 'Active'}, 'user_id')] if employee.reports_to else []
        else:
            department = employee.department
            if not department:
                frappe.throw('واحد سازمانی شخص مبنا مشخص نیست.')
            if not frappe.db.exists('Department', {'name': department, 'company': company, 'disabled': 0}):
                frappe.throw('واحد سازمانی شخص مبنا فعال یا متعلق به این دفتر نیست.')
            candidates = frappe.db.sql("""
                select distinct u.name
                from `tabUser` u
                join `tabEmployee` e on e.user_id = u.name and e.company = %s and e.department = %s and e.status = 'Active'
                where u.enabled = 1 and u.user_type = 'System User' and u.name not in ('Guest', 'Administrator')
            """, (company, department), pluck=True)
    elif basis == 'Unit':
        filters = {'company': company, 'department': department, 'status': 'Active', 'user_id': ['is', 'set']}
        if rule['delivery'] == 'Direct':
            filters['name'] = rule['person']
            emp_user = frappe.db.get_value('Employee', filters, 'user_id')
            candidates = [emp_user] if emp_user else []
        else:
            candidates = frappe.db.sql("""
                select distinct u.name
                from `tabUser` u
                join `tabEmployee` e on e.user_id = u.name and e.company = %s and e.department = %s and e.status = 'Active'
                where u.enabled = 1 and u.user_type = 'System User' and u.name not in ('Guest', 'Administrator')
            """, (company, department), pluck=True)
    else:
        if not frappe.db.exists('Role', {'name': rule['role'], 'disabled': 0}):
            frappe.throw('نقش مسئول حذف یا غیرفعال شده است.')
        if rule.get('scope') == 'Department':
            candidates = frappe.db.sql("""
                select distinct u.name
                from `tabUser` u
                join `tabHas Role` hr on hr.parent = u.name and hr.parenttype = 'User' and hr.role = %s
                join `tabEmployee` e on e.user_id = u.name and e.company = %s and e.department = %s and e.status = 'Active'
                where u.enabled = 1 and u.user_type = 'System User' and u.name not in ('Guest', 'Administrator')
            """, (rule['role'], company, department), pluck=True)
        else:
            # SQL prefilter narrows candidates; company_access remains the final authority.
            candidates = frappe.db.sql("""
                select distinct u.name
                from `tabUser` u
                join `tabHas Role` hr on hr.parent = u.name and hr.parenttype = 'User' and hr.role = %s
                where u.enabled = 1 and u.user_type = 'System User' and u.name not in ('Guest', 'Administrator')
                and (
                    u.name in (select user_id from `tabEmployee` where company = %s and status = 'Active' and user_id is not null)
                    or u.name in (select user from `tabASOUD Office Role Assignment` where company = %s)
                    or u.name in (select user from `tabUser Permission` where allow = 'Company' and for_value = %s and apply_to_all_doctypes = 1)
                    or exists (select 1 from `tabHas Role` r where r.parent = u.name and r.parenttype = 'User' and r.role in ('System Manager', 'HR Manager', 'Accounts Manager', 'Accounts User'))
                )
            """, (rule['role'], company, company, company), pluck=True)
    if len(candidates) > 200:
        frappe.throw('تعداد نامزدهای ارجاع بیش از حد مجاز است؛ محدوده را کوچک‌تر کنید.')
    active = candidates
    # Native company authorization is checked per principal; master reads above are batched.
    result = [user for user in dict.fromkeys(active) if user not in ('Guest', 'Administrator') and company_access(company, user)]
    result = filter_form_users(config, company, result)
    result = filter_reference_users(instance, config, result)
    if not result:
        frappe.throw('مسئول فعال و دارای دسترسی به اطلاعات این اقدام پیدا نشد؛ تنظیمات ارجاع و فرم را اصلاح کنید.')
    return result


def filter_reference_users(instance, config, users):
    """An assignment may not grant native document read permission."""
    # Native task-read hooks still require source-document permission even when
    # the designer hides its snapshot. Do not assign an unopenable task.
    if not instance.reference_name:
        return users
    doctype, name = instance.reference_doctype, instance.reference_name
    if doctype == 'ASOUD Form Entry':
        from asoud_erp.services.workflow_submission_source import entry_for_instance

        entry = entry_for_instance(instance)
        doctype, name = entry.reference_doctype, entry.reference_name
    # Request hooks explicitly authorize assignees, unlike native documents.
    if not doctype or not name or doctype == 'ASOUD Workflow Request':
        return users
    document = frappe.get_doc(doctype, name)
    return [user for user in users if frappe.has_permission(doctype, 'read', doc=document, user=user)]


def filter_form_users(config, company, users):
    from asoud_erp.api.v1 import forms

    if config['result_mode'] != 'Form' or not users:
        return users
    # The assignee's own form permissions still apply; no designer grant.
    source = config['result_form']
    if not frappe.db.exists('ASOUD Form', source['form']) or not frappe.db.exists('ASOUD Form Revision',
            {'name': source['revision'], 'form': source['form']}):
        frappe.throw('فرم ثبت نتیجه یا نسخهٔ انتخاب‌شده دیگر در دسترس نیست.')
    form = frappe.get_doc('ASOUD Form', source['form'])
    if form.company != company or form.disabled or not form.active_revision:
        frappe.throw('فرم ثبت نتیجه غیرفعال یا متعلق به دفتر دیگری است.')
    schema = forms.migrate_schema(json.loads(forms.revision(form, source['revision']).schema_json))
    departments = {row.user_id: row.department for row in frappe.get_all('Employee',
        filters={'company': company, 'status': 'Active', 'user_id': ['in', users]},
        fields=['user_id', 'department'], limit_page_length=201)}
    return [user for user in users if forms.matches_access(schema, frappe.get_roles(user), departments.get(user))]


def file_names(schema, values):
    from asoud_erp.services.form_schema import fields

    result = set()
    for field in fields(schema):
        value = values.get(field['key'])
        if field['type'] == 'Table' and isinstance(value, list):
            nested = {'sections': [{'fields': field.get('columns', [])}]}
            for row in value:
                if isinstance(row, dict):
                    result.update(file_names(nested, row))
        elif field['type'] in ('File', 'Image', 'Signature'):
            result.update(item for item in (value if isinstance(value, list) else [value]) if isinstance(item, str) and item)
    return result


def prepare(task, config, *, draft=False, values=_PRESENTATION):
    from asoud_erp.api.v1 import forms

    instance = frappe.get_doc('ASOUD Workflow Instance', task.workflow_instance)
    schema, name, company = form_schema(instance.workflow_definition, config, history=task.status != 'Open')
    if values is _PRESENTATION:
        current = json.loads(task.draft_json or '{}') if task.status == 'Open' else json.loads(task.response_json or '{}')
        return {'action_schema': schema, 'action_form': name or task.name, 'action_company': company,
            'action_contract_version': 1, 'requires_claim': task.status == 'Open' and task.action == 'Awaiting Claim',
            'allow_draft': config.get('allow_draft', True), 'allow_add_attachments': config['allow_add_attachments'],
            'allow_reassign': config.get('allow_reassign', False),
            'allow_original_access': config.get('allow_original_access', True),
            'action_values': current}
    raw = forms.parse(values)
    if not isinstance(raw, dict):
        frappe.throw('اطلاعات اقدام معتبر نیست.')
    names = file_names(schema, raw)
    previous = file_names(schema, json.loads(task.draft_json or '{}')) | file_names(schema, json.loads(task.response_json or '{}'))
    if not config['allow_add_attachments'] and names - previous:
        frappe.throw('افزودن پیوست جدید برای این اقدام مجاز نیست.')
    known = {field['key'] for field in forms.fields(schema)}
    known.update(f"{field['key']}__next_day" for field in forms.fields(schema) if field.get('next_day_allowed'))
    if set(raw) - known:
        frappe.throw('اطلاعات اقدام شامل فیلد ناشناخته است.')
    if draft:
        for file in names:
            if not frappe.has_permission('File', 'read', file):
                frappe.throw('دسترسی به یکی از پیوست‌ها مجاز نیست.', frappe.PermissionError)
        return raw
    trusted = set(frappe.get_all('File', filters={'name': ['in', list(previous) or ['']],
        'attached_to_doctype': 'ASOUD Workflow Task', 'attached_to_name': task.name}, pluck='name', limit_page_length=31))
    checked = forms.validate_values(schema, raw, company, _file_budget={'bytes': 0, 'names': set(), 'trusted_names': trusted})
    for file in frappe.get_all('File', filters={'name': ['in', list(names) or ['']]},
            fields=['name', 'owner', 'attached_to_doctype', 'attached_to_name'], limit_page_length=31):
        if file.owner == frappe.session.user and not file.attached_to_doctype and not file.attached_to_name:
            frappe.db.set_value('File', file.name, {'attached_to_doctype': 'ASOUD Workflow Task', 'attached_to_name': task.name})
    return checked


def assert_writable(task, config):
    if task.assigned_to != frappe.session.user:
        frappe.throw('این اقدام به کاربر دیگری واگذار شده است.', frappe.PermissionError)
    if task.status != 'Open':
        frappe.throw('این اقدام دیگر باز نیست.')
    if task.action == 'Awaiting Claim':
        frappe.throw('ابتدا اقدام را از صف دریافت کنید.')
    instance = frappe.get_doc('ASOUD Workflow Instance', task.workflow_instance)
    stage = frappe.get_doc('ASOUD Workflow Stage', task.workflow_stage)
    escalated = bool(task.escalated_on and config.get('reassign_on_overdue') and
        frappe.db.exists('ASOUD Workflow Activity', {'workflow_task': task.name, 'action': 'Escalated'}) and
        frappe.session.user in filter_reference_users(instance, config,
            escalation_users(config, company_for(instance.workflow_definition))))
    delegated = bool(config.get('allow_reassign') and frappe.db.exists('ASOUD Workflow Activity', {
        'workflow_task': task.name, 'action': 'Reassigned', 'reference_doctype': 'User',
        'reference_name': frappe.session.user}) and frappe.session.user in delegation_users(stage, instance))
    if instance.status != 'Running' or instance.current_stage != stage.name or (not escalated and not delegated and frappe.session.user not in users_for(stage, instance)):
        frappe.throw('این اقدام یا دسترسی مسئول آن تغییر کرده است؛ صفحه را دوباره دریافت کنید.', frappe.PermissionError)


def escalation_users(config, company):
    from asoud_erp.api.v1.workflow_runtime import _users_for_roles
    from asoud_erp.services.request_access import company_access

    roles = frappe.get_all('Role', filters={'name': ['in', config.get('escalation_roles') or ['']], 'disabled': 0},
        pluck='name', limit_page_length=201)
    candidates = _users_for_roles(roles)
    active = frappe.get_all('User', filters={'name': ['in', candidates or ['']],
        'enabled': 1, 'user_type': 'System User'}, pluck='name', limit_page_length=201)
    return filter_form_users(config, company,
        [user for user in active if user not in ('Guest', 'Administrator') and company_access(company, user)])


def escalate(task_name, current):
    """Reuse native overdue reassignment without duplicating a shared obligation."""
    from asoud_erp.api.v1.workflow_runtime import _notify_user, _record_activity

    original = frappe.get_doc('ASOUD Workflow Task', task_name)
    instance = frappe.get_doc('ASOUD Workflow Instance', original.workflow_instance, for_update=True)
    task = frappe.get_doc('ASOUD Workflow Task', task_name, for_update=True)
    if task.status != 'Open' or task.escalated_on or instance.status != 'Running' or instance.current_stage != task.workflow_stage:
        return
    config = json.loads(frappe.db.get_value('ASOUD Workflow Stage', task.workflow_stage, 'config_json') or '{}')
    company = frappe.db.get_value('ASOUD Workflow Definition', instance.workflow_definition, 'company')
    esc_users = escalation_users(config, company)
    notified = set()
    for user in esc_users:
        if user and user not in notified and user not in ('Guest', 'Administrator'):
            notified.add(user)
            _notify_user(user, 'اقدام نیازمند ارجاع است', instance, message=f"{task.task_title}: {task.assigned_to}")
    candidates = sorted(filter_reference_users(instance, config, esc_users))
    if config.get('reassign_on_overdue') and candidates:
        previous = task.assigned_to
        if task.action == 'Awaiting Claim':
            peers = frappe.db.sql('select name from `tabASOUD Workflow Task` where workflow_instance=%s '
                'and workflow_stage=%s and status=%s and action=%s for update',
                (instance.name, task.workflow_stage, 'Open', 'Awaiting Claim'), as_dict=True)
            others = [row.name for row in peers if row.name != task.name]
            if others:
                frappe.db.set_value('ASOUD Workflow Task', {'name': ['in', others]},
                    {'status': 'Cancelled', 'action': 'Claimed Elsewhere'})
            task.action = 'Claimed'
        task.assigned_to = candidates[0]
        previous_name = frappe.db.get_value('User', previous, 'full_name') or 'مسئول قبلی'
        _record_activity(task, 'Escalated', f'ارجاع مجدد پس از پایان مهلت؛ مسئول قبلی: {previous_name}',
            reference_doctype='User', reference_name=task.assigned_to)
    elif config.get('reassign_on_overdue'):
        _record_activity(task, 'Note', 'مسئول مجاز برای ارجاع مجدد پیدا نشد؛ مسئول فعلی حفظ شد.')
    task.escalated_on = current
    task.save(ignore_permissions=True)
    _notify_user(task.assigned_to, 'مهلت انجام اقدام پایان یافته است.', instance, message=task.task_title)


def link_schema(task_name, form_name, company):
    from asoud_erp.api.v1.workflow_runtime import _assert_task_owner

    task = frappe.get_doc('ASOUD Workflow Task', task_name)
    _assert_task_owner(task)
    config = json.loads(frappe.db.get_value('ASOUD Workflow Stage', task.workflow_stage, 'config_json') or '{}')
    if config.get('action_contract_version') != 1 or (config.get('result_form') or {}).get('form') != form_name:
        frappe.throw('فرم انتخاب‌شده متعلق به این اقدام نیست.', frappe.PermissionError)
    assert_writable(task, config)
    instance = frappe.get_doc('ASOUD Workflow Instance', task.workflow_instance)
    schema, _, actual_company = form_schema(instance.workflow_definition, config)
    if actual_company != company:
        frappe.throw('فرم و اقدام متعلق به این دفتر نیستند.', frappe.PermissionError)
    return schema


def handle(task_name, action, response, comment, assignee=None):
    """Caller already checks task ownership; use instance-first locks for candidates."""
    from asoud_erp.api.v1.workflow_runtime import _record_activity

    original = frappe.get_doc('ASOUD Workflow Task', task_name)
    instance = frappe.get_doc('ASOUD Workflow Instance', original.workflow_instance, for_update=True)
    task = frappe.get_doc('ASOUD Workflow Task', task_name, for_update=True)
    if task.assigned_to != frappe.session.user:
        frappe.throw('این اقدام متعلق به حساب شما نیست.', frappe.PermissionError)
    stage = frappe.get_doc('ASOUD Workflow Stage', task.workflow_stage)
    config = json.loads(stage.config_json or '{}')
    if task.status != 'Open' or instance.status != 'Running' or instance.current_stage != stage.name:
        frappe.throw('این اقدام دیگر قابل انجام نیست؛ صفحه را تازه کنید.')
    if action == 'Claim':
        if task.action != 'Awaiting Claim' or frappe.session.user not in users_for(stage, instance):
            frappe.throw('دریافت این اقدام مجاز نیست.', frappe.PermissionError)
        # Check the pinned result form before cancelling any colleague's task.
        form_schema(instance.workflow_definition, config)
        peers = frappe.db.sql('select name from `tabASOUD Workflow Task` where workflow_instance=%s '
            'and workflow_stage=%s and status=%s and action=%s for update',
            (instance.name, stage.name, 'Open', 'Awaiting Claim'), as_dict=True)
        other = [row.name for row in peers if row.name != task.name]
        if other:
            frappe.db.set_value('ASOUD Workflow Task', {'name': ['in', other]}, {'status': 'Cancelled', 'action': 'Claimed Elsewhere'})
        task.action = 'Claimed'
        task.save(ignore_permissions=True)
        _record_activity(task, 'Claim', 'اقدام از صف مشترک دریافت شد.')
        return {'task': task.name, 'claimed': True, 'instance_status': instance.status}
    assert_writable(task, config)
    if action == 'Reassign':
        return reassign(task, stage, instance, config, assignee)
    if config['result_mode'] != 'Simple' or config.get('simple_result_style') == 'Report' or action not in ('Follow Up', 'Blocked'):
        frappe.throw('عملیات ثبت وضعیت اقدام معتبر نیست.')
    checked = prepare(task, config, values=response)
    expected = 'follow_up' if action == 'Follow Up' else 'blocked'
    if checked.get('action_result') != expected or not (checked.get('action_note') or '').strip():
        frappe.throw('نتیجهٔ اقدام و توضیح علت پیگیری یا مانع را وارد کنید.')
    task.action = action
    task.comment = checked['action_note'].strip()
    task.draft_json = task.response_json = json.dumps(checked, ensure_ascii=False)
    task.save(ignore_permissions=True)
    _record_activity(task, action, task.comment)
    return {'task': task.name, 'saved': True, 'instance_status': instance.status}


def delegation_users(stage, instance):
    """Use the existing recipient resolver; transfer never grants new rights."""
    import copy

    config = json.loads(stage.config_json or '{}')
    rule = config['assignment_rule']
    proxy = copy.copy(stage)
    expanded = copy.deepcopy(config)
    if rule['basis'] == 'Unit':
        expanded['assignment_rule'] = {'basis': 'Unit', 'department': rule['department'], 'delivery': 'Shared'}
    elif rule['basis'] in ('Subject', 'Manager'):
        original = users_for(stage, instance)
        company = company_for(instance.workflow_definition)
        departments = frappe.get_all('Employee', filters={'user_id': ['in', original],
            'company': company, 'status': 'Active'}, pluck='department', limit_page_length=2)
        if len(departments) == 1 and departments[0]:
            expanded['assignment_rule'] = {'basis': 'Unit', 'department': departments[0], 'delivery': 'Shared'}
    proxy.config_json = json.dumps(expanded)
    return users_for(proxy, instance)


def reassignment_candidates(task, config, query, start):
    assert_writable(task, config)
    if not config.get('allow_reassign'):
        frappe.throw('واگذاری مجدد برای این اقدام فعال نیست.', frappe.PermissionError)
    if not isinstance(query, str) or len(query) > 100:
        frappe.throw('عبارت جست‌وجوی مسئول معتبر نیست.')
    try:
        start = int(start)
    except (ValueError, TypeError):
        frappe.throw('شمارهٔ صفحه معتبر نیست.')
    if start < 0 or start > 200:
        frappe.throw('شمارهٔ صفحه معتبر نیست.')
    stage = frappe.get_doc('ASOUD Workflow Stage', task.workflow_stage)
    instance = frappe.get_doc('ASOUD Workflow Instance', task.workflow_instance)
    candidates = [user for user in delegation_users(stage, instance) if user != task.assigned_to]
    rows = frappe.get_all('User', filters={'name': ['in', candidates or ['']]},
        fields=['name', 'full_name'], order_by='full_name asc, name asc', limit_page_length=201)
    matches = [row for row in rows if query.casefold() in (row.full_name or '').casefold()]
    return {'reassignment_candidates': [{'user': row.name, 'label': row.full_name or 'کاربر مجاز'}
        for row in matches[start:start + 25]], 'has_more': len(matches) > start + 25}


def reassign(task, stage, instance, config, assignee):
    from asoud_erp.api.v1.workflow_runtime import _notify_user, _record_activity

    if not config.get('allow_reassign'):
        frappe.throw('واگذاری مجدد برای این اقدام فعال نیست.', frappe.PermissionError)
    if not isinstance(assignee, str) or assignee == task.assigned_to or assignee not in delegation_users(stage, instance):
        frappe.throw('کاربر انتخاب‌شده واجد شرایط این اقدام نیست.', frappe.PermissionError)
    previous = task.assigned_to
    previous_name = frappe.db.get_value('User', previous, 'full_name') or 'مسئول قبلی'
    next_name = frappe.db.get_value('User', assignee, 'full_name') or 'مسئول جدید'
    task.assigned_to = assignee
    task.save(ignore_permissions=True)
    _record_activity(task, 'Reassigned', f'واگذاری از {previous_name} به {next_name}',
        reference_doctype='User', reference_name=assignee)
    _notify_user(assignee, 'اقدام به شما واگذار شد.', instance, message=task.task_title)
    return {'task': task.name, 'reassigned': True, 'instance_status': instance.status}
