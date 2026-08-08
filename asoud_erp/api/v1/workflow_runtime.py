import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.workflow_assignment import assignment_values


def _users_for_stage(stage) -> list[str]:
    config = json.loads(stage.config_json or "{}")
    assignment_type, values = assignment_values(config, stage.stage_type)
    if assignment_type == "Employee":
        users = frappe.get_all(
            "Employee",
            filters={"name": ["in", values], "status": "Active", "user_id": ["is", "set"]},
            pluck="user_id",
            limit_page_length=0,
        )
    elif assignment_type == "Department":
        users = frappe.get_all(
            "Employee",
            filters={"department": ["in", values], "status": "Active", "user_id": ["is", "set"]},
            pluck="user_id",
            limit_page_length=0,
        )
    else:
        users = frappe.get_all(
            "Has Role",
            filters={"role": ["in", values], "parenttype": "User"},
            pluck="parent",
            limit_page_length=0,
        )
        disabled = set(
            frappe.get_all("User", filters={"name": ["in", users], "enabled": 0}, pluck="name")
        )
        users = [user for user in users if user not in disabled]
    result = list(dict.fromkeys(user for user in users if user not in {"Guest", "Administrator"}))
    if not result:
        frappe.throw(_("No active ERPNext user is available for the selected assignment target"))
    return result


def _next_stage(instance, current_stage: str):
    transition = frappe.db.get_value(
        "ASOUD Workflow Transition",
        {"workflow_definition": instance.workflow_definition, "from_stage": current_stage},
        "to_stage",
    )
    return frappe.get_doc("ASOUD Workflow Stage", transition) if transition else None


def _activate_stage(instance, stage) -> None:
    instance.current_stage = stage.name
    if stage.stage_type == "End":
        config = json.loads(stage.config_json or "{}")
        instance.status = "Rejected" if config.get("outcome") == "Rejected" else "Completed"
        instance.completed_on = now_datetime()
        instance.save()
        return
    if stage.stage_type not in {"User Task", "Approval"}:
        frappe.throw(_("Automatic execution of this workflow stage is not available yet"))
    instance.save()
    for user in _users_for_stage(stage):
        frappe.get_doc(
            {
                "doctype": "ASOUD Workflow Task",
                "workflow_instance": instance.name,
                "workflow_stage": stage.name,
                "task_title": stage.stage_title,
                "assigned_to": user,
                "status": "Open",
                "assigned_on": now_datetime(),
            }
        ).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def start_workflow_instance(
    definition: str,
    subject: str,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    if workflow.status != "Active":
        frappe.throw(_("Only an active workflow can be started"))
    if len((subject or "").strip()) < 3:
        frappe.throw(_("Workflow subject must contain at least 3 characters"))
    if reference_name:
        if reference_doctype != workflow.target_doctype:
            frappe.throw(_("Reference DocType does not match the workflow"))
        if not frappe.db.exists(reference_doctype, reference_name):
            frappe.throw(_("Referenced document does not exist"))
        if not frappe.has_permission(reference_doctype, "read", reference_name):
            frappe.throw(_("Not permitted to use the referenced document"), frappe.PermissionError)
    start = frappe.db.get_value(
        "ASOUD Workflow Stage",
        {"workflow_definition": definition, "stage_type": "Start"},
        "name",
    )
    if not start:
        frappe.throw(_("Workflow start stage does not exist"))
    instance = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Instance",
            "workflow_definition": definition,
            "subject": (subject or "").strip(),
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "status": "Running",
            "started_by": frappe.session.user,
            "started_on": now_datetime(),
        }
    ).insert()
    stage = _next_stage(instance, start)
    if not stage:
        frappe.throw(_("Workflow has no executable stage"))
    _activate_stage(instance, stage)
    return success({"name": instance.name, "status": instance.status})


@frappe.whitelist()
def list_my_workflow_tasks(status: str = "Open") -> dict:
    if status not in {"Open", "Completed", "Rejected", "Cancelled"}:
        frappe.throw(_("Invalid task status"))
    rows = frappe.get_all(
        "ASOUD Workflow Task",
        filters={"assigned_to": frappe.session.user, "status": status},
        fields=[
            "name", "workflow_instance", "workflow_stage", "task_title", "status",
            "assigned_on", "completed_on",
        ],
        order_by="assigned_on desc",
        limit_page_length=200,
    )
    return success(rows, meta={"total": len(rows)})


@frappe.whitelist(methods=["POST"])
def complete_workflow_task(task: str, action: str, comment: str | None = None) -> dict:
    if action not in {"Complete", "Approve", "Reject", "Return"}:
        frappe.throw(_("Invalid workflow task action"))
    frappe.db.sql("select name from `tabASOUD Workflow Task` where name = %s for update", task)
    doc = frappe.get_doc("ASOUD Workflow Task", task)
    if doc.assigned_to != frappe.session.user:
        frappe.throw(_("This task is assigned to another user"), frappe.PermissionError)
    if doc.status != "Open":
        frappe.throw(_("Workflow task has already been completed"))
    stage = frappe.get_doc("ASOUD Workflow Stage", doc.workflow_stage)
    config = json.loads(stage.config_json or "{}")
    if config.get("comment_required") and not (comment or "").strip():
        frappe.throw(_("A decision comment is required"))
    if action == "Reject" and not config.get("allow_reject", False):
        frappe.throw(_("Reject is not allowed for this stage"))
    doc.status = "Rejected" if action == "Reject" else "Completed"
    doc.action = action
    doc.comment = (comment or "").strip()
    doc.completed_on = now_datetime()
    doc.save(ignore_permissions=True)
    instance = frappe.get_doc("ASOUD Workflow Instance", doc.workflow_instance)
    if action == "Reject":
        instance.status = "Rejected"
        instance.completed_on = now_datetime()
        instance.save(ignore_permissions=True)
        return success({"task": doc.name, "instance_status": instance.status})
    open_count = frappe.db.count(
        "ASOUD Workflow Task",
        {"workflow_instance": instance.name, "workflow_stage": stage.name, "status": "Open"},
    )
    if open_count == 0 or config.get("approval_mode") == "Any":
        if config.get("approval_mode") == "Any":
            frappe.db.set_value(
                "ASOUD Workflow Task",
                {"workflow_instance": instance.name, "workflow_stage": stage.name, "status": "Open"},
                "status",
                "Cancelled",
                update_modified=False,
            )
        next_stage = _next_stage(instance, stage.name)
        if not next_stage:
            frappe.throw(_("Workflow has no next stage"))
        _activate_stage(instance, next_stage)
    return success({"task": doc.name, "instance_status": instance.status})
