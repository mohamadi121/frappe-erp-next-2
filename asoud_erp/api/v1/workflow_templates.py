"""Company-scoped catalog and independent draft copies of system workflows."""
import json

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import workflow_templates as service


@frappe.whitelist()
def catalog(company, search="", module_key="", start=0, page_length=20, include_user=0):
    return success(service.catalog(company, search, module_key, start, page_length, include_user=include_user))


@frappe.whitelist(methods=["POST"])
def create_from_template(company, source, source_modified, workflow_title,
                         process_description="", icon_key="hub", color_hex="#315CF5", start_settings=None):
    from asoud_erp.services.erp_documents import require_roles
    from asoud_erp.services.workflow_start_settings import save, validate_selection

    require_roles(('System Manager', 'Accounts Manager'))
    if start_settings is not None:
        validate_selection(company, start_settings)
    frappe.db.savepoint('workflow_template_with_start')
    try:
        result = service.create_from_template(company, source, source_modified, workflow_title,
            process_description, icon_key, color_hex)
        if start_settings is not None:
            start = save(result['name'], start_settings)
            result['start_settings'] = json.loads(start.config_json)
        return success(result)
    except Exception:
        frappe.db.rollback(save_point='workflow_template_with_start')
        raise
