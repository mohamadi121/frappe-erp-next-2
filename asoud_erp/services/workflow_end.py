"""Terminal transition adapter for the existing single-current-stage runtime."""
import json

import frappe
from frappe.utils import now_datetime


def finish(instance, stage, *, previous_stage, source_task=None):
    """Caller already authorized the decision/route; serialize on its instance."""
    locked = frappe.get_doc('ASOUD Workflow Instance', instance.name, for_update=True)
    if locked.status != 'Running':
        instance.reload()
        return  # Retrying a committed end cannot overwrite it or repeat hooks.
    if stage.stage_type != 'End' or stage.workflow_definition != locked.workflow_definition:
        frappe.throw('مرحلهٔ پایان متعلق به این گردش کار نیست.')
    if not frappe.db.exists('ASOUD Workflow Transition', {'workflow_definition': locked.workflow_definition,
            'from_stage': previous_stage, 'to_stage': stage.name}):
        frappe.throw('مسیر ورودی معتبر برای پایان عملیات پیدا نشد.')
    if frappe.db.exists('ASOUD Workflow Transition', {'workflow_definition': locked.workflow_definition,
            'from_stage': stage.name}):
        frappe.throw('مرحلهٔ پایان نمی‌تواند مسیر خروجی داشته باشد.')
    from asoud_erp.services.workflow_stage_policy import normalize_stage_config

    try:
        raw = json.loads(stage.config_json or '{}')
        config = normalize_stage_config('End', {'title': stage.stage_title, 'outcome': 'Completed', **raw})
    except json.JSONDecodeError:
        frappe.throw('قالب تنظیمات مرحلهٔ پایان معتبر نیست؛ مدیر گردش کار باید آن را بررسی کند.')
    except (ValueError, TypeError) as error:
        frappe.throw(str(error) if isinstance(error, ValueError) else 'تنظیمات پایان معتبر نیست.')
    outcome = config['outcome']
    # Preserve the existing Reject execution override, not a shared End rewrite.
    if (source_task and source_task.action == 'Reject' and previous_stage == source_task.workflow_stage
            and source_task.workflow_instance == locked.name and source_task.status == 'Rejected'
            and frappe.db.get_value('ASOUD Workflow Stage', previous_stage, 'stage_type') == 'Approval'):
        outcome = 'Rejected'
    ended = now_datetime()
    cancelled = frappe.db.count('ASOUD Workflow Task', {'workflow_instance': locked.name, 'status': 'Open'})
    if cancelled:
        frappe.db.set_value('ASOUD Workflow Task', {'workflow_instance': locked.name, 'status': 'Open'},
            {'status': 'Cancelled', 'completed_on': ended}, update_modified=False)
    locked.status = {'Completed': 'Completed', 'Rejected': 'Rejected',
        'Cancelled': 'Cancelled', 'Stopped': 'Failed'}[outcome]
    locked.current_stage, locked.completed_on = stage.name, ended
    labels = {'outcome': 'نتیجه نهایی', 'result_label': 'پیام نتیجه', 'stage_title': 'عنوان مرحله'}
    outcomes = {'Completed': 'تکمیل موفق', 'Rejected': 'رد نهایی', 'Cancelled': 'لغو فرایند',
        'Stopped': 'توقف فرایند (بدون موفقیت)'}
    context = {'outcome': outcome, 'result_label': config['result_label'], 'ended_on': str(ended),
        'stage_title': stage.stage_title, 'from_stage': previous_stage, 'end_stage': stage.name,
        'definition_version': frappe.db.get_value('ASOUD Workflow Definition', locked.workflow_definition, 'version_no'),
        'decision_task': source_task.name if source_task else None,
        'decision': source_task.action if source_task else None,
        'decision_reason': source_task.comment if source_task else None, 'cancelled_tasks': cancelled}
    after = {'outcome': outcomes[outcome], 'result_label': config['result_label'], 'stage_title': stage.stage_title}
    # Keep technical context out of before/after: those are rendered to end users.
    frappe.get_doc({'doctype': 'ASOUD Workflow Activity', 'workflow_instance': locked.name,
        'workflow_stage': stage.name, 'workflow_task': source_task.name if source_task else None,
        'actor': frappe.session.user, 'action': 'پایان عملیات', 'created_on': ended,
        'comment': config['result_label'] or outcomes[outcome],
        'change_json': json.dumps({'before': {}, 'after': after, 'labels': labels, 'end_context': context},
            ensure_ascii=False, default=str)}).insert(ignore_permissions=True)
    locked.save(ignore_permissions=True)  # Existing module lifecycle mappings only.
    instance.reload()
