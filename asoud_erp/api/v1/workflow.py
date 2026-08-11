import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.jalali import current_jalali_year
from asoud_erp.services.workflow_contract import (
    ALLOWED_WORKFLOW_STATUSES,
    serialize_workflow,
)
from asoud_erp.services.workflow_stage_policy import ROLE_BASED_TYPES, normalize_stage_config

ALLOWED_STATUSES = ALLOWED_WORKFLOW_STATUSES
MODULE_DOCTYPES = {
    "Purchase": ("Material Request", "Purchase Order"),
    "Accounting": ("Payment Request", "Expense Claim", "Journal Entry"),
    "Sales": ("Quotation", "Sales Order"),
    "Inventory": ("Stock Entry",),
    "Support": ("Issue",),
    "HR": ("Leave Application", "Job Applicant"),
}
STAGE_TITLES = {
    "User Task": "وظیفه کاربر",
    "Approval": "تأیید یا رد",
    "Condition": "شرط و مسیر",
    "System Action": "اقدام خودکار",
    "Wait": "انتظار و زمان‌بندی",
    "End": "پایان فرایند",
}


def _stage_dict(row: dict) -> dict:
    result = dict(row)
    result["config"] = json.loads(result.pop("config_json") or "{}")
    return result


def _transition_dict(row: dict) -> dict:
    result = dict(row)
    result["condition"] = json.loads(result.pop("condition_json") or "{}")
    return result


def _design_payload(definition: str) -> dict:
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    stages = frappe.get_all(
        "ASOUD Workflow Stage",
        filters={"workflow_definition": definition},
        fields=[
            "name", "stage_key", "stage_type", "stage_subtype", "stage_title",
            "sequence_no", "config_json", "configuration_status", "position_x", "position_y",
        ],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    transitions = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={"workflow_definition": definition},
        fields=["name", "from_stage", "to_stage", "transition_label", "condition_json", "sequence_no"],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    return {
        "workflow": serialize_workflow(workflow.as_dict()),
        "stages": [_stage_dict(row) for row in stages],
        "transitions": [_transition_dict(row) for row in transitions],
    }


@frappe.whitelist()
def list_workflows(
    search: str | None = None,
    status: str | None = None,
    company: str | None = None,
    order_by: str = "modified desc",
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if status and status not in ALLOWED_STATUSES:
        frappe.throw(_("Invalid workflow status"))
    allowed_order = {
        "modified desc": "modified desc",
        "modified asc": "modified asc",
        "title asc": "workflow_title asc",
        "code asc": "workflow_code asc",
    }
    filters: dict = {}
    if status:
        filters["status"] = status
    if company:
        filters["company"] = company
    or_filters = None
    if search:
        term = f"%{search.strip()}%"
        or_filters = {"workflow_title": ["like", term], "workflow_code": ["like", term]}
    rows = frappe.get_all(
        "ASOUD Workflow Definition",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "workflow_code", "workflow_title", "company", "target_doctype",
            "process_description", "module_key", "creation_mode",
            "frappe_workflow", "status", "readiness_status", "pending_reason",
            "missing_requirements_json", "version_no", "steps_count", "icon_key",
            "color_hex", "modified", "modified_by",
        ],
        order_by=allowed_order.get(order_by, "modified desc"),
        limit_page_length=200,
    )
    return success([serialize_workflow(row) for row in rows], meta={"total": len(rows)})


@frappe.whitelist()
def workflow_form_options() -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    modules = []
    for key, doctypes in MODULE_DOCTYPES.items():
        options = [
            {"name": doctype, "available": bool(frappe.db.exists("DocType", doctype))}
            for doctype in doctypes
        ]
        modules.append({"key": key, "doctypes": options})
    companies = frappe.get_all("Company", filters={"disabled": 0}, pluck="name", order_by="name asc")
    roles = frappe.get_all(
        "Role",
        filters={"disabled": 0, "name": ["not in", ["All", "Guest"]]},
        pluck="name",
        order_by="name asc",
    )
    departments = frappe.get_all(
        "Department",
        filters={"disabled": 0},
        fields=["name", "department_name", "company"],
        order_by="department_name asc",
        limit_page_length=0,
    )
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "department", "company", "user_id"],
        order_by="employee_name asc",
        limit_page_length=0,
    )
    return success({
        "modules": modules,
        "companies": companies,
        "roles": roles,
        "departments": departments,
        "employees": employees,
    })


@frappe.whitelist(methods=["POST"])
def create_workflow_draft(
    workflow_title: str,
    module_key: str,
    target_doctype: str,
    company: str | None = None,
    process_description: str | None = None,
    creation_mode: str = "Custom",
    icon_key: str | None = None,
    color_hex: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    title = (workflow_title or "").strip()
    if len(title) < 3:
        frappe.throw(_("Workflow title must contain at least 3 characters"))
    if module_key not in MODULE_DOCTYPES:
        frappe.throw(_("Invalid workflow module"))
    if target_doctype not in MODULE_DOCTYPES[module_key]:
        frappe.throw(_("The selected DocType does not belong to this module"))
    if not frappe.db.exists("DocType", target_doctype):
        frappe.throw(_("The selected DocType is not installed"))
    if company and not frappe.db.exists("Company", company):
        frappe.throw(_("The selected company does not exist"))
    if creation_mode not in {"Custom", "Template"}:
        frappe.throw(_("Invalid workflow creation mode"))

    code = make_autoname(f"WF-{current_jalali_year()}-.###")
    doc = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Definition",
            "workflow_code": code,
            "workflow_title": title,
            "process_description": (process_description or "").strip(),
            "company": company,
            "module_key": module_key,
            "creation_mode": creation_mode,
            "target_doctype": target_doctype,
            "status": "Inactive",
            "readiness_status": "Pending",
            "pending_reason": _("Workflow stages and transitions are not complete"),
            "missing_requirements_json": '["Workflow stages", "Transitions", "Frappe Workflow"]',
            "icon_key": icon_key,
            "color_hex": color_hex,
        }
    )
    doc.insert()
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Stage",
            "workflow_definition": doc.name,
            "stage_key": f"start-{frappe.generate_hash(length=10)}",
            "stage_type": "Start",
            "stage_title": _("Start"),
            "sequence_no": 0,
            "configuration_status": "Pending",
            "config_json": json.dumps(
                {
                    "trigger_type": "Manual",
                    "initiator_roles": [],
                    "subject_source": "Referenced Document",
                    "pass_mode": "Direct",
                }
            ),
        }
    ).insert()
    return success(serialize_workflow(doc.as_dict()))


@frappe.whitelist()
def get_workflow_design(definition: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def save_start_settings(
    definition: str,
    trigger_type: str,
    initiator_roles: str | list[str],
    subject_source: str,
    pass_mode: str = "Direct",
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if trigger_type not in {"Manual", "Document Event", "System", "API"}:
        frappe.throw(_("Invalid start trigger"))
    if subject_source not in {"Referenced Document", "ASOUD Record", "General Subject"}:
        frappe.throw(_("Invalid workflow subject source"))
    if pass_mode not in {"Direct", "Conditional"}:
        frappe.throw(_("Invalid start pass mode"))
    values = json.loads(initiator_roles) if isinstance(initiator_roles, str) else initiator_roles
    roles = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    missing_roles = [role for role in roles if not frappe.db.exists("Role", role)]
    if missing_roles:
        frappe.throw(_("One or more initiator roles do not exist"))
    stage_name = frappe.db.get_value(
        "ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Start"}, "name"
    )
    if not stage_name:
        frappe.throw(_("Workflow start stage does not exist"))
    stage = frappe.get_doc("ASOUD Workflow Stage", stage_name)
    stage.config_json = json.dumps(
        {
            "trigger_type": trigger_type,
            "initiator_roles": roles,
            "subject_source": subject_source,
            "pass_mode": pass_mode,
        },
        ensure_ascii=False,
    )
    stage.configuration_status = "Complete" if roles or trigger_type != "Manual" else "Pending"
    stage.save()
    return success(_stage_dict(stage.as_dict()))


@frappe.whitelist(methods=["POST"])
def add_workflow_stage(definition: str, stage_type: str, after_stage: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if stage_type not in STAGE_TITLES:
        frappe.throw(_("Invalid workflow stage type"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    previous = frappe.get_doc("ASOUD Workflow Stage", after_stage)
    if previous.workflow_definition != definition:
        frappe.throw(_("The selected previous stage belongs to another workflow"))
    if previous.stage_type == "End":
        frappe.throw(_("A stage cannot be added after the end stage"))
    existing_next = frappe.db.exists("ASOUD Workflow Transition", {"from_stage": previous.name})
    if existing_next:
        frappe.throw(_("Linear designer already has a stage after the selected stage"))
    sequence = int(previous.sequence_no or 0) + 1
    stage = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Stage",
            "workflow_definition": definition,
            "stage_key": f"stage-{frappe.generate_hash(length=10)}",
            "stage_type": stage_type,
            "stage_title": STAGE_TITLES[stage_type],
            "sequence_no": sequence,
            "configuration_status": "Pending" if stage_type != "End" else "Complete",
            "config_json": "{}",
            "position_y": sequence * 180,
        }
    )
    stage.insert()
    transition = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": previous.name,
            "to_stage": stage.name,
            "sequence_no": sequence,
            "condition_json": "{}",
        }
    )
    transition.insert()
    definition_doc = frappe.get_doc("ASOUD Workflow Definition", definition)
    definition_doc.steps_count = frappe.db.count(
        "ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": ["!=", "Start"]}
    )
    definition_doc.version_no = int(definition_doc.version_no or 1) + 1
    definition_doc.save()
    return success(_design_payload(definition))


def _assert_stage_in_definition(stage_name: str, definition: str):
    stage = frappe.get_doc("ASOUD Workflow Stage", stage_name)
    if stage.workflow_definition != definition:
        frappe.throw(_("Stage does not belong to the selected workflow"))
    return stage


def _touch_workflow(definition: str) -> None:
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    workflow.steps_count = frappe.db.count(
        "ASOUD Workflow Stage",
        {"workflow_definition": definition, "stage_type": ["!=", "Start"]},
    )
    workflow.version_no = int(workflow.version_no or 1) + 1
    workflow.save()


@frappe.whitelist(methods=["POST"])
def update_stage_positions(definition: str, positions: str | dict) -> dict:
    """Persist designer coordinates without changing workflow semantics."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    values = json.loads(positions) if isinstance(positions, str) else positions
    if not isinstance(values, dict) or len(values) > 250:
        frappe.throw(_("Invalid stage positions"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    for stage_name, point in values.items():
        if not isinstance(point, dict):
            frappe.throw(_("Invalid stage position"))
        stage = _assert_stage_in_definition(stage_name, definition)
        try:
            x = float(point.get("x", 0))
            y = float(point.get("y", 0))
        except (TypeError, ValueError):
            frappe.throw(_("Invalid stage position"))
        if not (-10000 <= x <= 10000 and -10000 <= y <= 10000):
            frappe.throw(_("Stage position is outside the allowed canvas"))
        stage.db_set({"position_x": x, "position_y": y}, update_modified=False)
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def connect_workflow_stages(
    definition: str,
    from_stage: str,
    to_stage: str,
    action: str,
    condition: str | dict | None = None,
) -> dict:
    """Create a named route; backward routes are deliberately supported."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    action = (action or "").strip()
    if not action or len(action) > 140 or from_stage == to_stage:
        frappe.throw(_("Invalid workflow transition"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    source = _assert_stage_in_definition(from_stage, definition)
    _assert_stage_in_definition(to_stage, definition)
    if source.stage_type == "End":
        frappe.throw(_("The end stage cannot have an outgoing route"))
    if frappe.db.exists(
        "ASOUD Workflow Transition",
        {
            "workflow_definition": definition,
            "from_stage": from_stage,
            "transition_label": action,
        },
    ):
        frappe.throw(_("This action already has a route from the selected stage"))
    raw_condition = json.loads(condition) if isinstance(condition, str) else (condition or {})
    if not isinstance(raw_condition, dict):
        frappe.throw(_("Transition condition must be an object"))
    canonical_actions = {
        "تأیید": "Approve",
        "رد": "Reject",
        "بازگشت برای اصلاح": "Return",
        "ارجاع": "Forward",
        "ادامه": "Complete",
    }
    raw_condition.setdefault("action", canonical_actions.get(action, action))
    sequence = frappe.db.count(
        "ASOUD Workflow Transition",
        {"workflow_definition": definition, "from_stage": from_stage},
    ) + 1
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "transition_label": action,
            "condition_json": json.dumps(raw_condition, ensure_ascii=False),
            "sequence_no": sequence,
        }
    ).insert()
    _touch_workflow(definition)
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def insert_workflow_stage(
    definition: str, transition: str, stage_type: str
) -> dict:
    """Split one existing route into source -> new stage -> old destination."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    if stage_type not in STAGE_TITLES:
        frappe.throw(_("Invalid workflow stage type"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    edge = frappe.get_doc("ASOUD Workflow Transition", transition)
    if edge.workflow_definition != definition:
        frappe.throw(_("Transition does not belong to the selected workflow"))
    source = _assert_stage_in_definition(edge.from_stage, definition)
    destination = _assert_stage_in_definition(edge.to_stage, definition)
    sequence = max(int(source.sequence_no or 0) + 1, 1)
    stage = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Stage",
            "workflow_definition": definition,
            "stage_key": f"stage-{frappe.generate_hash(length=10)}",
            "stage_type": stage_type,
            "stage_title": STAGE_TITLES[stage_type],
            "sequence_no": sequence,
            "configuration_status": "Complete" if stage_type == "End" else "Pending",
            "config_json": "{}",
            "position_x": (float(source.position_x or 0) + float(destination.position_x or 0)) / 2,
            "position_y": (float(source.position_y or 0) + float(destination.position_y or 0)) / 2,
        }
    ).insert()
    original = {
        "label": edge.transition_label,
        "condition": edge.condition_json or "{}",
        "sequence": edge.sequence_no,
    }
    edge.delete()
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": source.name,
            "to_stage": stage.name,
            "transition_label": original["label"],
            "condition_json": original["condition"],
            "sequence_no": original["sequence"],
        }
    ).insert()
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": stage.name,
            "to_stage": destination.name,
            "transition_label": _("Continue"),
            "condition_json": "{}",
            "sequence_no": 1,
        }
    ).insert()
    _touch_workflow(definition)
    return success(_design_payload(definition))


@frappe.whitelist()
def workflow_condition_fields(definition: str, stage: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    target_doctype = frappe.db.get_value("ASOUD Workflow Definition", definition, "target_doctype")
    if not target_doctype or not frappe.db.exists("DocType", target_doctype):
        frappe.throw(_("Workflow target DocType does not exist"))
    allowed_types = {"Data", "Select", "Link", "Int", "Float", "Currency", "Check", "Date", "Datetime"}
    fields = [
        {"fieldname": field.fieldname, "label": field.label or field.fieldname, "fieldtype": field.fieldtype, "source": "Document"}
        for field in frappe.get_meta(target_doctype).fields
        if field.fieldname and field.fieldtype in allowed_types and not field.hidden
    ]
    stage_filters = {"workflow_definition": definition, "stage_type": "User Task"}
    if stage:
        condition = frappe.get_doc("ASOUD Workflow Stage", stage)
        if condition.workflow_definition != definition or condition.stage_type != "Condition":
            frappe.throw(_("Selected stage is not a condition in this workflow"))
        stage_filters["sequence_no"] = ["<", condition.sequence_no]
    stage_rows = frappe.get_all(
        "ASOUD Workflow Stage",
        filters=stage_filters,
        fields=["config_json"],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    for row in stage_rows:
        for field in json.loads(row.config_json or "{}").get("form_fields", []):
            if field.get("type") in {"Short Text", "Long Text", "Number", "Currency", "Date", "Choice", "Checkbox"}:
                fields.append({
                    "fieldname": field.get("key"),
                    "label": field.get("label") or field.get("key"),
                    "fieldtype": field.get("type"),
                    "source": "Form",
                })
    fields = list({(item["source"], item["fieldname"]): item for item in fields}.values())
    return success({"doctype": target_doctype, "fields": fields})


@frappe.whitelist(methods=["POST"])
def add_condition_branch(
    definition: str,
    condition_stage: str,
    stage_type: str,
    result: int | bool | str,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if stage_type not in STAGE_TITLES:
        frappe.throw(_("Invalid workflow stage type"))
    truthy = result is True or str(result).lower() in {"1", "true"}
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    condition = frappe.get_doc("ASOUD Workflow Stage", condition_stage)
    if condition.workflow_definition != definition or condition.stage_type != "Condition":
        frappe.throw(_("Selected stage is not a condition in this workflow"))
    transitions = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={"workflow_definition": definition, "from_stage": condition.name},
        fields=["condition_json"],
        limit_page_length=0,
    )
    if any(json.loads(row.condition_json or "{}").get("result") is truthy for row in transitions):
        frappe.throw(_("This condition result already has a branch"))
    sequence = int(condition.sequence_no or 0) + 1
    stage = frappe.get_doc({
        "doctype": "ASOUD Workflow Stage",
        "workflow_definition": definition,
        "stage_key": f"stage-{frappe.generate_hash(length=10)}",
        "stage_type": stage_type,
        "stage_title": STAGE_TITLES[stage_type],
        "sequence_no": sequence,
        "configuration_status": "Pending" if stage_type != "End" else "Complete",
        "config_json": "{}",
        "position_x": 180 if truthy else -180,
        "position_y": sequence * 180,
    }).insert()
    frappe.get_doc({
        "doctype": "ASOUD Workflow Transition",
        "workflow_definition": definition,
        "from_stage": condition.name,
        "to_stage": stage.name,
        "transition_label": _("Yes") if truthy else _("No"),
        "condition_json": json.dumps({"result": truthy}),
        "sequence_no": 1 if truthy else 2,
    }).insert()
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    workflow.steps_count = frappe.db.count(
        "ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": ["!=", "Start"]}
    )
    workflow.version_no = int(workflow.version_no or 1) + 1
    workflow.save()
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def save_stage_settings(definition: str, stage: str, config: str | dict) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    doc = frappe.get_doc("ASOUD Workflow Stage", stage)
    if doc.workflow_definition != definition:
        frappe.throw(_("Stage does not belong to the selected workflow"))
    if doc.stage_type == "Start":
        frappe.throw(_("Use the start settings endpoint for the start stage"))
    raw = json.loads(config) if isinstance(config, str) else config
    if not isinstance(raw, dict):
        frappe.throw(_("Stage configuration must be an object"))
    try:
        normalized = normalize_stage_config(doc.stage_type, raw)
    except ValueError as error:
        frappe.throw(_(str(error)))

    role_field = ROLE_BASED_TYPES.get(doc.stage_type)
    roles = normalized.get(role_field, []) if role_field else normalized.get("target_roles", [])
    if roles and any(not frappe.db.exists("Role", role) for role in roles):
        frappe.throw(_("One or more selected roles do not exist"))
    if doc.stage_type in ROLE_BASED_TYPES:
        prefix = "assignee" if doc.stage_type == "User Task" else "approver"
        departments = normalized.get(f"{prefix}_departments", [])
        employees = normalized.get(f"{prefix}_employees", [])
        if departments and any(not frappe.db.exists("Department", value) for value in departments):
            frappe.throw(_("One or more selected departments do not exist"))
        if employees:
            active_employees = frappe.get_all(
                "Employee",
                filters={"name": ["in", employees], "status": "Active"},
                fields=["name", "user_id"],
            )
            if {row.name for row in active_employees} != set(employees):
                frappe.throw(_("One or more selected employees do not exist or are inactive"))
            if any(not row.user_id for row in active_employees):
                frappe.throw(_("Selected employees must have an ERPNext user account for inbox assignment"))
            company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
            if company and frappe.db.count(
                "Employee", {"name": ["in", employees], "company": ["!=", company]}
            ):
                frappe.throw(_("Selected employees must belong to the workflow company"))
    if doc.stage_type == "Condition":
        if normalized["source_kind"] == "Document":
            target_doctype = frappe.db.get_value("ASOUD Workflow Definition", definition, "target_doctype")
            meta = frappe.get_meta(target_doctype)
            field = meta.get_field(normalized["source_field"])
            allowed_types = {"Data", "Select", "Link", "Int", "Float", "Currency", "Check", "Date", "Datetime"}
            if not field or field.fieldtype not in allowed_types or field.hidden:
                frappe.throw(_("The selected condition field is not allowed"))
        else:
            configs = frappe.get_all(
                "ASOUD Workflow Stage",
                filters={
                    "workflow_definition": definition,
                    "stage_type": "User Task",
                    "sequence_no": ["<", doc.sequence_no],
                },
                pluck="config_json",
                limit_page_length=0,
            )
            form_keys = {
                field.get("key")
                for config in configs
                for field in json.loads(config or "{}").get("form_fields", [])
            }
            if normalized["source_field"] not in form_keys:
                frappe.throw(_("The selected form field does not exist in this workflow"))

    doc.stage_title = normalized.pop("title")
    doc.config_json = json.dumps(normalized, ensure_ascii=False)
    doc.configuration_status = "Complete"
    doc.save()
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    workflow.version_no = int(workflow.version_no or 1) + 1
    workflow.save()
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def set_workflow_status(name: str, status: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if status not in ALLOWED_STATUSES:
        frappe.throw(_("Invalid workflow status"))
    doc = frappe.get_doc("ASOUD Workflow Definition", name)
    if status == "Active" and doc.readiness_status != "Ready":
        frappe.throw(_("Complete the pending requirements before activation"))
    if status == "Active" and not doc.frappe_workflow:
        frappe.throw(_("Link a valid Frappe Workflow before activation"))
    doc.status = status
    doc.archived_on = now_datetime() if status == "Archived" else None
    doc.save()
    return success(serialize_workflow(doc.as_dict()))
