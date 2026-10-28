"""Independent native workflow designs, scoped to an accessible company."""
import json

import frappe
from frappe.model.naming import make_autoname
from frappe.utils import cint

from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.jalali import current_jalali_year
from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_contract import serialize_workflow
from asoud_erp.services.workflow_template_copy import appearance, graph_plan

DEFINITION = "ASOUD Workflow Definition"
STAGE = "ASOUD Workflow Stage"
TRANSITION = "ASOUD Workflow Transition"


def access(company):
    require_roles(("System Manager", "Accounts Manager"))
    if not isinstance(company, str) or not company.strip():
        frappe.throw("دفتر کار را انتخاب کنید.")
    require_company(company)


def catalog(company, search="", module_key="", start=0, page_length=20):
    access(company)
    start, page_length = max(0, cint(start)), min(50, max(1, cint(page_length)))
    filters = {"company": company, "is_system_template": 1, "status": ["!=", "Archived"]}
    if module_key:
        filters["module_key"] = module_key
    if search:
        filters["workflow_title"] = ["like", f"%{str(search).strip()[:100]}%"]
    rows = frappe.get_list(DEFINITION, filters=filters,
        fields=["name", "workflow_title", "process_description", "module_key", "target_doctype",
                "icon_key", "color_hex", "steps_count", "modified"],
        order_by="workflow_title asc, name asc", limit_start=start, limit_page_length=page_length + 1)
    return {"items": rows[:page_length], "next_start": start + page_length if len(rows) > page_length else None}


def create_from_template(company, source, source_modified, workflow_title,
                         process_description="", icon_key="hub", color_hex="#315CF5"):
    access(company)
    if not isinstance(source, str) or not source or not isinstance(source_modified, str):
        frappe.throw("الگوی انتخاب‌شده یا نسخهٔ آن معتبر نیست.")
    if not frappe.db.exists(DEFINITION, source):
        frappe.throw("الگوی انتخاب‌شده دیگر در دسترس نیست.")
    original = frappe.get_doc(DEFINITION, source, for_update=True)
    original.check_permission("read")
    if original.company != company or not original.is_system_template or original.status == "Archived":
        frappe.throw("استفاده از این الگو در دفتر انتخاب‌شده مجاز نیست.", frappe.PermissionError)
    if str(original.modified) != str(source_modified):
        frappe.throw("الگو تغییر کرده است؛ آن را دوباره انتخاب کنید.", frappe.TimestampMismatchError)
    for doctype in (STAGE, TRANSITION):
        if not frappe.has_permission(doctype, "read") or not frappe.has_permission(doctype, "create"):
            frappe.throw("اجازهٔ کپی مراحل گردش کار را ندارید.", frappe.PermissionError)
    stages = frappe.get_all(STAGE, filters={"workflow_definition": source},
        fields=["name", "stage_type", "stage_subtype", "stage_title", "sequence_no", "config_json",
                "position_x", "position_y"], order_by="sequence_no asc", limit_page_length=201)
    transitions = frappe.get_all(TRANSITION, filters={"workflow_definition": source},
        fields=["from_stage", "to_stage", "transition_label", "condition_json", "sequence_no"],
        order_by="sequence_no asc", limit_page_length=1001)
    identities = {row.name: frappe.generate_hash(length=20) for row in stages}
    try:
        title, description = appearance(workflow_title, process_description, icon_key, color_hex)
        copied_stages, copied_edges = graph_plan(stages, transitions, identities)
    except ValueError as error:
        frappe.throw(str(error))
    # No original template identity, Frappe Workflow, history or execution state is inherited.
    doc = frappe.get_doc({"doctype": DEFINITION,
        "workflow_code": make_autoname(f"WF-{current_jalali_year()}-.###"),
        "workflow_title": title, "process_description": description, "company": company,
        "module_key": original.module_key, "target_doctype": original.target_doctype,
        "creation_mode": "Template", "status": "Inactive", "readiness_status": "Pending",
        "pending_reason": "مراحل و دسترسی‌های الگوی کپی‌شده را بررسی و تکمیل کنید.",
        "missing_requirements_json": json.dumps(["بررسی مراحل", "اتصال گردش کار"], ensure_ascii=False),
        "version_no": 1, "steps_count": max(0, len(stages) - 1), "icon_key": icon_key,
        "color_hex": color_hex, "request_category": original.request_category,
        "is_system_template": 0, "show_in_request_list": 0, "allow_user_submission": 0,
    }).insert()
    for row in copied_stages:
        name = row.pop("name")
        frappe.get_doc({"doctype": STAGE, **row, "workflow_definition": doc.name,
            "stage_key": f"copy-{frappe.generate_hash(length=24)}"}).insert(set_name=name)
    for row in copied_edges:
        frappe.get_doc({"doctype": TRANSITION, **row, "workflow_definition": doc.name}).insert()
    return serialize_workflow(doc.as_dict())
