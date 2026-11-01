"""Guards for existing definition operations; no alternative workflow engine."""
import json

import frappe

from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_contract import activation_requirements, is_system_workflow

DEFINITION = 'ASOUD Workflow Definition'


def require_activation_ready(doc):
    stages = frappe.db.sql('select name, stage_type, stage_title, configuration_status, config_json '
        'from `tabASOUD Workflow Stage` where workflow_definition=%s limit 201 for update',
        (doc.name,), as_dict=True)
    edges = frappe.db.sql('select from_stage, to_stage, transition_label, condition_json '
        'from `tabASOUD Workflow Transition` where workflow_definition=%s limit 1001 for update',
        (doc.name,), as_dict=True)
    if len(stages) > 200 or len(edges) > 1000:
        frappe.throw('اندازهٔ طراحی گردش‌کار بیش از حد مجاز است.')
    errors = activation_requirements(stages, edges)
    if errors:
        frappe.throw('فعال‌سازی ممکن نیست: ' + ' '.join(errors))
    from asoud_erp.api.v1.automatic_actions import require_execution_ready
    from asoud_erp.services.workflow_user_action import validate_design
    for stage in stages:
        if stage.stage_type == 'User Task':
            validate_design(doc.name, json.loads(stage.config_json or '{}'))

    require_execution_ready(doc.name)


def delete_definition(doc):
    require_roles(('System Manager', 'Accounts Manager'))
    require_company(doc.company)
    doc.check_permission('delete')
    # Serializes deletion against runtime starts and status changes.
    locked = frappe.get_doc(DEFINITION, doc.name, for_update=True)
    from asoud_erp.services.setup_reset import allows_workflow_cleanup

    resetting = allows_workflow_cleanup(locked)
    if is_system_workflow(locked) and not resetting:
        frappe.throw('گردش‌کار پیش‌فرض سیستمی قابل حذف نیست.')
    for doctype in ('ASOUD Workflow Instance', 'ASOUD Workflow Request'):
        if frappe.db.sql(f'select name from `tab{doctype}` where workflow_definition=%s limit 1 for update',
                (doc.name,)):
            frappe.throw('این گردش‌کار دارای درخواست یا سابقهٔ اجرا است؛ حذف آن مجاز نیست. می‌توانید آن را غیرفعال کنید.')
    if not resetting and frappe.db.exists('Version', {'ref_doctype': DEFINITION, 'docname': doc.name}):
        frappe.throw('این گردش‌کار دارای نسخه‌های تاریخی است و برای حفظ سوابق قابل حذف نیست.')
    if frappe.db.sql('select name from `tabASOUD Form Revision` where '
            "JSON_UNQUOTE(JSON_EXTRACT(IF(JSON_VALID(schema_json),schema_json,'{}'), %s))=%s limit 1",
            ('$.workflow', doc.name)):
        frappe.throw('یک نسخهٔ فرم به این گردش‌کار وابسته است؛ حذف مجاز نیست.')
    if frappe.db.sql('select name from `tabASOUD Form` where '
            "JSON_UNQUOTE(JSON_EXTRACT(IF(JSON_VALID(draft_json),draft_json,'{}'), %s))=%s limit 1",
            ('$.workflow', doc.name)):
        frappe.throw('پیش‌نویس یک فرم به این گردش‌کار وابسته است؛ حذف مجاز نیست.')
    if doc.get('source_form'):
        frappe.throw('این گردش‌کار به یک فرم متصل است؛ ابتدا اتصال آن را از تنظیمات مرحله حذف کنید.')
    if frappe.db.sql('select name from `tabASOUD Workflow Stage` where '
            "JSON_UNQUOTE(JSON_EXTRACT(IF(JSON_VALID(config_json),config_json,'{}'), %s))=%s limit 1",
            ('$.request_definition', doc.name)):
        frappe.throw('مرحله‌ای از گردش‌کار دیگر به این گردش‌کار وابسته است؛ حذف مجاز نیست.')
    from frappe.model.delete_doc import check_if_doc_is_dynamically_linked, check_if_doc_is_linked

    owned = {doctype: set(frappe.get_all(doctype, filters={'workflow_definition': doc.name},
        pluck='name', limit_page_length=0))
        for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage')}
    for doctype, names in owned.items():
        if not resetting and names and frappe.db.exists('Version', {'ref_doctype': doctype, 'docname': ['in', list(names)]}):
            frappe.throw('مراحل این گردش‌کار دارای نسخه‌های تاریخی هستند؛ حذف مجاز نیست.')
    frappe.db.savepoint('workflow_card_delete')
    try:
        # These are definition-owned technical records, not execution/history.
        # Native link checking remains enabled, including links to individual stages.
        for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'):
            for name in owned[doctype]:
                frappe.delete_doc(doctype, name, ignore_permissions=True)
        # Run native checks here as well, while the rollback savepoint still
        # covers the graph cleanup. The framework checks again after on_trash.
        check_if_doc_is_linked(doc)
        check_if_doc_is_dynamically_linked(doc)
    except frappe.LinkExistsError:
        frappe.db.rollback(save_point='workflow_card_delete')
        frappe.clear_messages()
        frappe.throw('این گردش‌کار یا مراحل آن وابستگی دارد؛ برای حفظ اطلاعات، حذف انجام نشد.')
    except Exception:
        frappe.db.rollback(save_point='workflow_card_delete')
        raise
