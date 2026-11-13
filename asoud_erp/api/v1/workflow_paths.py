"""Preview and confirm removal of native draft-only workflow paths."""
import json

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_paths import references_any, removal_plan


def editable(definition, *, lock=False):
    require_roles(('System Manager', 'Accounts Manager'))
    doc = frappe.get_doc('ASOUD Workflow Definition', definition)
    require_company(doc.company)
    doc.check_permission('write')
    if lock:
        doc = frappe.get_doc(doc.doctype, doc.name, for_update=True)
    if doc.status == 'Active' or frappe.db.exists('ASOUD Workflow Instance', {'workflow_definition': definition}):
        frappe.throw('این گردش‌کار فعال است یا سابقهٔ اجرا دارد؛ برای تغییر مسیرها یک کپی مستقل بسازید.')
    return doc


def plan(definition, transition):
    stages = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition},
        fields=['name', 'stage_title', 'stage_type', 'config_json'], limit_page_length=1001)
    edges = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition},
        fields=['name', 'from_stage', 'to_stage'], limit_page_length=4001)
    if len(stages) > 1000 or len(edges) > 4000:
        frappe.throw('اندازهٔ نمودار بیش از محدودهٔ ویرایش ایمن است.')
    try:
        result = removal_plan(stages, edges, transition)
    except ValueError as error:
        frappe.throw(str(error))
    # A remaining action/condition may refer to a removed stage outside its edges.
    for stage in stages:
        if stage.name not in result['stages'] and references_any(json.loads(stage.config_json or '{}'), result['stages']):
            frappe.throw('تنظیمات یک مرحلهٔ باقی‌مانده به این شاخه وابسته است؛ ابتدا وابستگی را اصلاح کنید.')
    result['stage_labels'] = [row.stage_title for row in stages if row.name in result['stages']]
    return result


@frappe.whitelist()
def preview_path_removal(definition: str, transition: str):
    doc = editable(definition)
    return success({**plan(definition, transition), 'version': doc.version_no})


@frappe.whitelist(methods=['POST'])
def remove_path(definition: str, transition: str, version: int):
    from asoud_erp.api.v1.workflow import _design_payload, _touch_workflow

    doc = editable(definition, lock=True)
    if str(doc.version_no) != str(version):
        frappe.throw('نمودار تغییر کرده است؛ خلاصهٔ حذف را دوباره دریافت کنید.')
    result = plan(definition, transition)
    frappe.db.savepoint('remove_draft_workflow_path')
    try:
        for name in result['transitions']:
            frappe.delete_doc('ASOUD Workflow Transition', name)
        for name in result['stages']:
            frappe.delete_doc('ASOUD Workflow Stage', name)
        _touch_workflow(definition)
    except Exception:
        frappe.db.rollback(save_point='remove_draft_workflow_path')
        raise
    return success(_design_payload(definition))


@frappe.whitelist(methods=['POST'])
def discard_inserted_stage(definition: str, stage: str, original: str | dict):
    """Cancel a just-inserted editor, restoring only its original split edge."""
    from asoud_erp.api.v1.workflow import _design_payload, _touch_workflow

    editable(definition, lock=True)
    from time import time

    from frappe.utils.password import decrypt

    try:
        if not isinstance(original, str) or len(original) > 16000:
            raise ValueError
        ticket = json.loads(decrypt(original))
        if (ticket['definition'] != definition or ticket['stage'] != stage or ticket['actor'] != frappe.session.user
                or not 0 <= time() - ticket['issued'] < 86400):
            raise ValueError
        raw = ticket['original']
    except Exception:
        frappe.throw('مجوز بازگردانی این ویرایش معتبر نیست؛ نمودار را تازه کنید.')
    if not isinstance(raw, dict) or not raw.get('from_stage') or not raw.get('to_stage'):
        frappe.throw('اطلاعات مسیر اولیه معتبر نیست.')
    nodes = {row.name for row in frappe.get_all('ASOUD Workflow Stage',
        filters={'workflow_definition': definition}, fields=['name'], limit_page_length=1001)}
    if not {stage, raw['from_stage'], raw['to_stage']} <= nodes or stage in {raw['from_stage'], raw['to_stage']}:
        frappe.throw('مسیر تغییر کرده است؛ بازگردانی خودکار مجاز نیست.')
    links = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition},
        fields=['name', 'from_stage', 'to_stage', 'transition_label', 'condition_json', 'sequence_no'], limit_page_length=4001)
    affected = [row for row in links if stage in (row.from_stage, row.to_stage)]
    if len(affected) != 2 or not any(row.from_stage == raw['from_stage'] and row.to_stage == stage for row in affected):
        frappe.throw('مرحله با مسیر دیگری مشترک شده است؛ برای حفظ تغییرات، بازگردانی خودکار انجام نشد.')
    if not any(row.from_stage == stage and row.to_stage == raw['to_stage'] for row in affected):
        frappe.throw('مسیر مرحله تغییر کرده است؛ بازگردانی خودکار انجام نشد.')
    incoming = next(row for row in affected if row.to_stage == stage)
    outgoing = next(row for row in affected if row.from_stage == stage)
    if (incoming.transition_label != raw.get('transition_label')
            or json.loads(incoming.condition_json or '{}') != (raw.get('condition') or {})
            or incoming.sequence_no != raw.get('sequence_no')
            or json.loads(outgoing.condition_json or '{}')):
        frappe.throw('تنظیمات مسیر در حین ویرایش تغییر کرده است؛ برای حفظ تغییرات، بازگردانی خودکار انجام نشد.')
    for row in frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition},
            fields=['name', 'config_json'], limit_page_length=1001):
        if row.name != stage and references_any(json.loads(row.config_json or '{}'), {stage}):
            frappe.throw('مرحلهٔ دیگری به این ویرایش وابسته شده است؛ بازگردانی خودکار انجام نشد.')
    frappe.db.savepoint('discard_inserted_stage')
    try:
        for row in affected:
            frappe.delete_doc('ASOUD Workflow Transition', row.name)
        frappe.delete_doc('ASOUD Workflow Stage', stage)
        frappe.get_doc({'doctype': 'ASOUD Workflow Transition', 'workflow_definition': definition,
            'from_stage': raw['from_stage'], 'to_stage': raw['to_stage'],
            'transition_label': raw.get('transition_label') or '',
            'condition_json': json.dumps(raw.get('condition') or {}), 'sequence_no': raw.get('sequence_no', 1)}).insert()
        _touch_workflow(definition)
    except Exception:
        frappe.db.rollback(save_point='discard_inserted_stage')
        raise
    return success(_design_payload(definition))
