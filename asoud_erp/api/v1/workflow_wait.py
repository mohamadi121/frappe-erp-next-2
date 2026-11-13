"""Company-scoped Wait editor using the existing stage settings API."""
import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import workflow_wait as waits
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import require_company


def access(definition, stage):
    require_roles(('System Manager', 'Accounts Manager'))
    company = frappe.db.get_value('ASOUD Workflow Definition', definition, 'company')
    if not company:
        frappe.throw('گردش‌کار موردنظر پیدا نشد.')
    require_company(company)
    doc = frappe.get_doc('ASOUD Workflow Definition', definition)
    doc.check_permission('write')
    if not frappe.db.exists('ASOUD Workflow Stage', {'name': stage, 'workflow_definition': definition, 'stage_type': 'Wait'}):
        frappe.throw('مرحلهٔ انتظار متعلق به این گردش‌کار نیست.')
    return doc


@frappe.whitelist()
def get_wait_options(definition: str, stage: str):
    access(definition, stage)
    try:
        tz, source = waits.office_zone(definition)
        available = waits.fields(definition, stage)
    except ValueError as error:
        frappe.throw(str(error))
    output, label = True, ''
    try:
        label = waits.destination(definition, stage).stage_title
    except ValueError:
        output = False
    blocked = waits.blocked_message()
    return success({'wait_version': 1, 'fields': available,
        'time_zone': tz, 'zone_source': source, 'output_valid': output, 'output_label': label,
        'execution_ready': blocked is None, 'blocked_message': blocked})


@frappe.whitelist(methods=['POST'])
def save_wait_settings(definition: str, stage: str, config: str | dict):
    import json

    from asoud_erp.api.v1.workflow import save_stage_settings
    from asoud_erp.services.workflow_condition_binding import assert_editable

    access(definition, stage)
    frappe.get_doc('ASOUD Workflow Definition', definition, for_update=True)
    assert_editable(definition)
    try:
        raw = json.loads(config) if isinstance(config, str) else config
        from asoud_erp.services.workflow_wait_policy import normalize

        checked = normalize(raw)
    except json.JSONDecodeError:
        frappe.throw('قالب تنظیمات انتظار معتبر نیست؛ اطلاعات را دوباره ارسال کنید.')
    except (ValueError, TypeError) as error:
        frappe.throw(str(error) if isinstance(error, ValueError) else 'تنظیمات انتظار معتبر نیست.')
    return save_stage_settings(definition, stage, checked)
