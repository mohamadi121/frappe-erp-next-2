"""Business output of a human task, under the completing user's permissions."""
import hashlib
import json

import frappe

from asoud_erp.services.request_access import require_company


def _no_cycle(definition, target):
    pending, seen = [target], set()
    while pending:
        name = pending.pop()
        if name == definition:
            frappe.throw("Request creation cannot form a recursive workflow cycle")
        if name in seen:
            continue
        seen.add(name)
        if len(seen) > 100:
            frappe.throw("Request dependency graph is too large")
        for raw in frappe.get_all("ASOUD Workflow Stage",
                filters={"workflow_definition": name}, pluck="config_json"):
            config = json.loads(raw or "{}")
            if config.get("task_purpose") == "Create Request":
                pending.append(config["request_definition"])
            if config.get("schema_version") == 2 and config.get("action_type") == "Create Request":
                pending.append(config["operation"]["request_type"])


def validate_target(definition, config):
    purpose = config.get("task_purpose", "Existing")
    company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
    require_company(company)
    if purpose == "Create Request":
        from asoud_erp.api.v1.workflow_request import _definition

        name = config.get("request_definition")
        _no_cycle(definition, name)
        target = _definition(name)
        if target.company and target.company != company:
            frappe.throw("Request type belongs to another company")
    elif purpose == "Create Document":
        template = frappe.get_doc("ASOUD Document Template", config.get("document_template"))
        template.check_permission("read")
        if template.company != company or template.status != "Active":
            frappe.throw("Select an active document template in the workflow company")
    return company


def create_output(task, instance, config, response):
    purpose = config.get("task_purpose", "Existing")
    if purpose == "Existing":
        return None
    company = validate_target(instance.workflow_definition, config)
    if purpose == "Create Request":
        from asoud_erp.api.v1.workflow_request import create_request
        from asoud_erp.services.automatic_action_runtime import _request_attachments

        if not frappe.has_permission("ASOUD Workflow Request", "create"):
            frappe.throw("No permission to create requests", frappe.PermissionError)
        values, attachments = _request_attachments(
            response, config["request_definition"], instance, task.name
        )
        result = create_request(
            company=company, workflow_definition=config["request_definition"],
            subject=instance.subject or task.task_title,
            request_id="task-" + hashlib.sha256(task.name.encode()).hexdigest(),
            values=values, attachments=attachments,
        )
        return {"doctype": "ASOUD Workflow Request", "name": result["data"]["name"]}
    if purpose == "Create Document":
        from asoud_erp.api.v1.document_templates import create_document
        from asoud_erp.api.v1.workflow_runtime import _action_context

        context = _action_context(instance)
        context["request"].update(response)
        document = create_document(config["document_template"], context, company,
            transfer_values=config.get("transfer_values", True),
            remark=config.get("document_remark", ""))
        return {"doctype": document.doctype, "name": document.name}
    frappe.throw("Unknown task purpose")
