"""Configure the existing Start node and reuse native form binding/permissions."""
import json

import frappe

from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_start_policy import normalize_settings


def save(definition, settings):
    try:
        values = normalize_settings(frappe.parse_json(settings) if isinstance(settings, str) else settings)
    except (ValueError, TypeError):
        frappe.throw('تنظیمات شروع معتبر نیست؛ نحوهٔ شروع، نقش‌ها و انتخاب فرم را بررسی کنید.')
    workflow = frappe.get_doc('ASOUD Workflow Definition', definition)
    require_company(workflow.company)
    workflow.check_permission('write')
    from asoud_erp.api.v1 import forms

    old_source = workflow.get('source_form')
    for name in sorted({name for name in (old_source, (values['submission_source'] or {}).get('form')) if name}):
        forms.load(name, edit=True, lock=True)
    workflow = frappe.get_doc('ASOUD Workflow Definition', definition, for_update=True)
    if workflow.get('source_form') != old_source:
        frappe.throw('تنظیمات شروع تغییر کرده است؛ صفحه را دوباره دریافت کنید.')
    active = set(frappe.get_all('Role', filters={'name': ['in', values['initiator_roles'] or ['']], 'disabled': 0}, pluck='name'))
    if set(values['initiator_roles']) - active:
        frappe.throw('یکی از نقش‌های شروع غیرفعال است یا وجود ندارد.')
    names = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition, 'stage_type': 'Start'},
        pluck='name', limit_page_length=2)
    if len(names) != 1:
        frappe.throw('گردش‌کار باید دقیقاً یک مرحلهٔ شروع داشته باشد.')
    start = frappe.get_doc('ASOUD Workflow Stage', names[0])
    start.check_permission('write')
    old_config = json.loads(start.config_json or '{}')
    if old_config.get('start_settings_version') == 1:
        previous = normalize_settings({key: old_config[key] for key in ('trigger_type', 'initiator_roles',
            'submission_source', 'allow_manager_restart', 'require_manual_reason') if key in old_config})
        if previous == values:
            return start  # A metadata-only save must not rewrite a live Start.
    if frappe.db.exists('ASOUD Workflow Instance', {'workflow_definition': definition, 'status': 'Running'}):
        frappe.throw('تا پایان اجراهای در حال انجام، تغییر تنظیمات شروع مجاز نیست.')
    frappe.db.savepoint('workflow_start_settings')
    try:
        # Explicitly move only routing metadata, never the old task's form/content.
        stages = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition, 'stage_type': 'User Task'},
            fields=['*'], limit_page_length=201)
        if len(stages) > 200:
            frappe.throw('تعداد مراحل بیش از حد مجاز است.')
        for row in stages:
            config = json.loads(row.config_json or '{}')
            if config.pop('submission_source', None):
                # Batch-read the stage rows; native save retains permission,
                # timestamp and Version checks for each actual changed document.
                doc = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', **dict(row)})
                doc.config_json = json.dumps(config, ensure_ascii=False)
                doc.save()
        config = {**json.loads(start.config_json or '{}'), **values}
        from asoud_erp.services.workflow_submission_source import bind

        bind(definition, start.name, config)
        start.config_json = json.dumps(config, ensure_ascii=False)
        start.configuration_status = 'Complete'
        start.save()
    except Exception:
        frappe.db.rollback(save_point='workflow_start_settings')
        raise
    return start
