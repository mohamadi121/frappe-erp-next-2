"""Company-scoped catalog and independent draft copies of system workflows."""
import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import workflow_templates as service


@frappe.whitelist()
def catalog(company, search="", module_key="", start=0, page_length=20):
    return success(service.catalog(company, search, module_key, start, page_length))


@frappe.whitelist(methods=["POST"])
def create_from_template(company, source, source_modified, workflow_title,
                         process_description="", icon_key="hub", color_hex="#315CF5"):
    return success(service.create_from_template(company, source, source_modified, workflow_title,
        process_description, icon_key, color_hex))
