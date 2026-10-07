"""Metadata and atomic stage+route save for automatic action schema 2."""

import json

import frappe
from frappe.model.workflow import get_workflow, get_workflow_name

from asoud_erp.api.v1.responses import success
from asoud_erp.services.automatic_action_metadata import (
    DOCUMENTS,
    RECORDS,
    record_fields,
    request_fields,
    schemas,
    service_user,
    validate_config,
    validate_permissions,
)
from asoud_erp.services.automatic_action_policy import ACTIONS
from asoud_erp.services.document_templates import TARGET_FIELDS
from asoud_erp.services.request_access import require_company


def _access(definition, stage):
    frappe.only_for(("System Manager", "Accounts Manager"))
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    require_company(workflow.company)
    doc = frappe.get_doc("ASOUD Workflow Stage", stage)
    if doc.workflow_definition != definition or doc.stage_type != "System Action":
        frappe.throw("The selected stage is not an automatic action of this workflow")
    return workflow, doc


@frappe.whitelist()
def options(definition: str, stage: str):
    workflow, _ = _access(definition, stage)
    sources = schemas(definition, stage)
    blocked = None
    try:
        user = service_user(workflow.company)
    except frappe.PermissionError as error:
        user, blocked = None, str(error)
    requests = []
    for row in frappe.get_all(
        "ASOUD Workflow Definition",
        filters={
            "company": workflow.company,
            "target_doctype": "ASOUD Workflow Request",
            "status": "Active",
            "readiness_status": "Ready",
            "allow_user_submission": 1,
        },
        fields=["name", "workflow_title"],
    ):
        if row.name == definition:
            continue
        try:
            fields = request_fields(row.name, workflow.company)
        except (ValueError, frappe.ValidationError):
            continue
        requests.append({"id": row.name, "label": row.workflow_title, "fields": fields})
    transitions = {}
    for doctype in RECORDS:
        if not get_workflow_name(doctype):
            transitions[doctype] = []
            continue
        native = get_workflow(doctype)
        roles = set(frappe.get_roles(user)) if user else set()
        transitions[doctype] = list(dict.fromkeys(t.action for t in native.transitions if t.allowed in roles))
    employees = frappe.get_all(
        "Employee",
        filters={"company": workflow.company, "status": "Active", "user_id": ["is", "set"]},
        fields=["user_id", "employee_name"],
        limit_page_length=200,
    )
    users = [
        {"id": row.user_id, "label": row.employee_name}
        for row in employees
        if row.user_id not in {"Guest", "Administrator"}
        and frappe.db.get_value("User", row.user_id, "enabled")
    ]
    return success(
        {
            "schema_version": 2,
            "actions": list(ACTIONS),
            "sources": sources,
            "documents": [{"id": dt, "label": dt, "fields": TARGET_FIELDS[dt]} for dt in DOCUMENTS],
            "records": [{"id": dt, "label": dt, "fields": record_fields(dt)} for dt in RECORDS],
            "requests": requests,
            "users": users,
            "transitions": transitions,
            "channels": ["in_app", "email"],
            "execution_ready": user is not None,
            "blocked_reason": blocked,
        }
    )


@frappe.whitelist(methods=["POST"])
def save(definition: str, stage: str, config: str | dict, routes: str | dict):
    from asoud_erp.api.v1.workflow import _design_payload, save_stage_routes, save_stage_settings

    _access(definition, stage)
    raw = json.loads(config) if isinstance(config, str) else config
    exits = json.loads(routes) if isinstance(routes, str) else routes
    if not isinstance(raw, dict) or not isinstance(exits, dict) or set(exits) != {"Success", "Error"}:
        frappe.throw("Configuration and both routes are required")
    if not exits["Success"]:
        frappe.throw("Choose an existing success stage")
    for outcome, destination in exits.items():
        if not destination:
            continue
        target = frappe.get_doc("ASOUD Workflow Stage", destination)
        if (
            target.workflow_definition != definition
            or target.name == stage
            or target.stage_type == "Start"
            or (outcome == "Error" and target.stage_type != "User Task")
        ):
            frappe.throw("Invalid route: errors may only route to a human task")
    try:
        validate_config(definition, stage, raw)
    except ValueError as error:
        frappe.throw(str(error))
    # Both changes share one POST transaction. A route failure rolls back settings.
    save_stage_settings(definition, stage, raw)
    save_stage_routes(definition, stage, exits)
    return success(_design_payload(definition))


def require_execution_ready(definition):
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    require_company(workflow.company)
    for stage in frappe.get_all(
        "ASOUD Workflow Stage",
        filters={"workflow_definition": definition, "stage_type": "System Action"},
        fields=["name", "config_json"],
    ):
        service_user(workflow.company)
        config = json.loads(stage.config_json or "{}")
        if config.get("schema_version") == 2:
            validate_config(definition, stage.name, config)
            validate_permissions(definition, stage.name, config)
