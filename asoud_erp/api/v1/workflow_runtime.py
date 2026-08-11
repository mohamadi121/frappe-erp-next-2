import base64
import binascii
import json
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.workflow_assignment import assignment_values
from asoud_erp.services.workflow_condition import evaluate_condition, select_boolean_transition
from asoud_erp.services.workflow_history import merge_completed_responses, select_return_stage
from asoud_erp.services.workflow_response import normalize_form_response

ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".docx"}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _assert_task_owner(doc) -> None:
    if doc.assigned_to != frappe.session.user:
        frappe.throw(_("This task is assigned to another user"), frappe.PermissionError)


def _assert_instance_access(instance) -> None:
    if instance.started_by == frappe.session.user:
        return
    if frappe.db.exists(
        "ASOUD Workflow Task",
        {"workflow_instance": instance.name, "assigned_to": frappe.session.user},
    ):
        return
    if {"System Manager", "Accounts Manager"}.intersection(frappe.get_roles()):
        return
    frappe.throw(_("Not permitted to view this workflow instance"), frappe.PermissionError)


def _instance_summary(instance) -> dict:
    stage_title = ""
    if instance.current_stage:
        stage_title = frappe.db.get_value(
            "ASOUD Workflow Stage", instance.current_stage, "stage_title"
        ) or ""
    assignees = frappe.get_all(
        "ASOUD Workflow Task",
        filters={"workflow_instance": instance.name, "status": "Open"},
        pluck="assigned_to",
        order_by="assigned_on asc",
        limit_page_length=0,
    )
    return {
        "name": instance.name,
        "subject": instance.subject,
        "status": instance.status,
        "workflow_definition": instance.workflow_definition,
        "current_stage": instance.current_stage or "",
        "current_stage_title": stage_title,
        "current_assignees": list(dict.fromkeys(assignees)),
        "reference_doctype": instance.reference_doctype or "",
        "reference_name": instance.reference_name or "",
        "started_by": instance.started_by,
        "started_on": instance.started_on,
        "completed_on": instance.completed_on,
    }


def _record_activity(doc, action: str, comment: str = "") -> None:
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Activity",
            "workflow_instance": doc.workflow_instance,
            "workflow_task": doc.name,
            "workflow_stage": doc.workflow_stage,
            "actor": frappe.session.user,
            "action": action,
            "comment": comment,
            "created_on": now_datetime(),
        }
    ).insert(ignore_permissions=True)


def _users_for_stage(stage, instance) -> list[str]:
    config = json.loads(stage.config_json or "{}")
    assignment_type, values = assignment_values(config, stage.stage_type)
    if assignment_type == "Initiator":
        users = [instance.started_by]
    elif assignment_type == "Employee":
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


def _next_stage(instance, current_stage: str, action: str | None = None):
    transitions = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={
            "workflow_definition": instance.workflow_definition,
            "from_stage": current_stage,
        },
        fields=["to_stage", "transition_label", "condition_json", "sequence_no"],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    if not transitions:
        return None
    selected = None
    if action:
        for transition in transitions:
            condition = json.loads(transition.condition_json or "{}")
            route_action = str(condition.get("action") or transition.transition_label or "")
            if route_action.casefold() == action.casefold():
                selected = transition
                break
    selected = selected or (transitions[0] if len(transitions) == 1 else None)
    return frappe.get_doc("ASOUD Workflow Stage", selected.to_stage) if selected else None


def _latest_form_value(instance, fieldname: str, source_task=None):
    """Return the newest submitted form value available in this instance."""
    if source_task:
        response = json.loads(source_task.response_json or "{}")
        if fieldname in response:
            return response[fieldname]
    rows = frappe.get_all(
        "ASOUD Workflow Task",
        filters={"workflow_instance": instance.name, "status": "Completed"},
        fields=["response_json"],
        order_by="completed_on desc",
        limit_page_length=0,
    )
    for row in rows:
        response = json.loads(row.response_json or "{}")
        if fieldname in response:
            return response[fieldname]
    return None


def _completed_task_rows(instance, exclude_task: str | None = None) -> list[dict]:
    filters = {"workflow_instance": instance.name, "status": "Completed"}
    if exclude_task:
        filters["name"] = ["!=", exclude_task]
    rows = frappe.get_all(
        "ASOUD Workflow Task",
        filters=filters,
        fields=["name", "workflow_stage", "task_title", "response_json", "completed_on"],
        order_by="completed_on desc",
        limit_page_length=0,
    )
    result = []
    for row in rows:
        stage = frappe.get_doc("ASOUD Workflow Stage", row.workflow_stage)
        config = json.loads(stage.config_json or "{}")
        result.append(
            {
                **row,
                "stage_type": stage.stage_type,
                "has_form_fields": bool(config.get("form_fields")),
                "form_fields": config.get("form_fields", []),
            }
        )
    return result


def _previous_task_data(instance, exclude_task: str | None = None) -> list[dict]:
    sections = []
    for row in reversed(_completed_task_rows(instance, exclude_task)):
        response = json.loads(row.get("response_json") or "{}")
        if not response:
            continue
        labels = {
            field.get("key"): field.get("label") or field.get("key")
            for field in row.get("form_fields", [])
            if isinstance(field, dict)
        }
        sections.append(
            {
                "task": row.get("name"),
                "title": row.get("task_title"),
                "values": [
                    {"key": key, "label": labels.get(key, key), "value": value}
                    for key, value in response.items()
                ],
            }
        )
    return sections


def _activate_stage(instance, stage, source_task=None) -> None:
    instance.current_stage = stage.name
    config = json.loads(stage.config_json or "{}")
    if stage.stage_type == "End":
        instance.status = "Rejected" if config.get("outcome") == "Rejected" else "Completed"
        instance.completed_on = now_datetime()
        instance.save()
        return
    if stage.stage_type == "Condition":
        if config.get("source_kind") == "Form":
            actual = _latest_form_value(
                instance, config.get("source_field"), source_task=source_task
            )
        else:
            actual = None
            if instance.reference_doctype and instance.reference_name:
                actual = frappe.db.get_value(
                    instance.reference_doctype, instance.reference_name, config.get("source_field")
                )
        try:
            result = evaluate_condition(
                config.get("operator"), actual, config.get("compare_value")
            )
            rows = frappe.get_all(
                "ASOUD Workflow Transition",
                filters={
                    "workflow_definition": instance.workflow_definition,
                    "from_stage": stage.name,
                },
                fields=["to_stage", "condition_json"],
                limit_page_length=0,
            )
            destination = select_boolean_transition(
                [
                    {
                        "to_stage": row.to_stage,
                        "condition": json.loads(row.condition_json or "{}"),
                    }
                    for row in rows
                ],
                result,
            )
        except ValueError as error:
            frappe.throw(_(str(error)))
        instance.save(ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": "ASOUD Workflow Activity",
                "workflow_instance": instance.name,
                "workflow_task": source_task.name if source_task else None,
                "workflow_stage": stage.name,
                "actor": frappe.session.user,
                "action": "Condition True" if result else "Condition False",
                "comment": f"{config.get('source_field')} = {actual}",
                "created_on": now_datetime(),
            }
        ).insert(ignore_permissions=True)
        _activate_stage(
            instance,
            frappe.get_doc("ASOUD Workflow Stage", destination),
            source_task=source_task,
        )
        return
    if stage.stage_type not in {"User Task", "Approval"}:
        frappe.throw(_("Automatic execution of this workflow stage is not available yet"))
    instance.save()
    previous_rows = list(reversed(_completed_task_rows(instance)))
    previous_values = merge_completed_responses(previous_rows)
    form_keys = {
        field.get("key")
        for field in config.get("form_fields", [])
        if isinstance(field, dict)
    }
    draft_values = {key: value for key, value in previous_values.items() if key in form_keys}
    for user in _users_for_stage(stage, instance):
        frappe.get_doc(
            {
                "doctype": "ASOUD Workflow Task",
                "workflow_instance": instance.name,
                "workflow_stage": stage.name,
                "task_title": stage.stage_title,
                "assigned_to": user,
                "status": "Open",
                "assigned_on": now_datetime(),
                "draft_json": json.dumps(draft_values, ensure_ascii=False)
                if config.get("form_fields")
                else "{}",
            }
        ).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def start_workflow_instance(
    definition: str,
    subject: str,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
) -> dict:
    frappe.only_for(
        (
            "System Manager",
            "Accounts Manager",
            "Accounts User",
            "Purchase Manager",
            "Purchase User",
        )
    )
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


@frappe.whitelist()
def list_my_workflow_instances(status: str | None = None) -> dict:
    allowed = {"Running", "Completed", "Rejected", "Cancelled", "Failed"}
    if status and status not in allowed:
        frappe.throw(_("Invalid workflow instance status"))
    filters = {"started_by": frappe.session.user}
    if status:
        filters["status"] = status
    names = frappe.get_all(
        "ASOUD Workflow Instance",
        filters=filters,
        pluck="name",
        order_by="started_on desc",
        limit_page_length=200,
    )
    rows = [
        _instance_summary(frappe.get_doc("ASOUD Workflow Instance", name))
        for name in names
    ]
    return success(rows, meta={"total": len(rows)})


@frappe.whitelist()
def get_workflow_instance(instance: str) -> dict:
    doc = frappe.get_doc("ASOUD Workflow Instance", instance)
    _assert_instance_access(doc)
    activities = frappe.get_all(
        "ASOUD Workflow Activity",
        filters={"workflow_instance": doc.name},
        fields=[
            "name",
            "workflow_task",
            "workflow_stage",
            "actor",
            "action",
            "comment",
            "created_on",
        ],
        order_by="created_on asc",
        limit_page_length=0,
    )
    for activity in activities:
        activity["stage_title"] = (
            frappe.db.get_value(
                "ASOUD Workflow Stage", activity.workflow_stage, "stage_title"
            )
            if activity.workflow_stage
            else ""
        ) or ""
    return success({**_instance_summary(doc), "activities": activities})


@frappe.whitelist()
def get_workflow_task(task: str) -> dict:
    doc = frappe.get_doc("ASOUD Workflow Task", task)
    _assert_task_owner(doc)
    stage = frappe.get_doc("ASOUD Workflow Stage", doc.workflow_stage)
    config = json.loads(stage.config_json or "{}")
    instance = frappe.get_doc("ASOUD Workflow Instance", doc.workflow_instance)
    history = frappe.get_all(
        "ASOUD Workflow Activity",
        filters={"workflow_instance": doc.workflow_instance},
        fields=["name", "workflow_task", "workflow_stage", "actor", "action", "comment", "created_on"],
        order_by="created_on asc",
        limit_page_length=0,
    )
    document_context = {}
    if instance.reference_doctype and instance.reference_name:
        if not frappe.has_permission(
            instance.reference_doctype,
            "read",
            doc=instance.reference_name,
            user=frappe.session.user,
        ):
            frappe.throw(
                _("You are not allowed to read the referenced document"),
                frappe.PermissionError,
            )
        reference = frappe.get_doc(instance.reference_doctype, instance.reference_name)
        meta = frappe.get_meta(instance.reference_doctype)
        visible_fields = [
            field
            for field in meta.fields
            if field.fieldname
            and not field.hidden
            and field.fieldtype
            not in {"Section Break", "Column Break", "Tab Break", "HTML", "Button"}
        ]
        document_context = {
            "doctype": instance.reference_doctype,
            "name": instance.reference_name,
            "values": [
                {
                    "key": field.fieldname,
                    "label": field.label or field.fieldname,
                    "value": reference.get(field.fieldname),
                    "read_only": bool(field.read_only),
                }
                for field in visible_fields
                if reference.get(field.fieldname) not in (None, "", [])
            ],
        }
    return success(
        {
            "name": doc.name,
            "workflow_instance": doc.workflow_instance,
            "workflow_stage": doc.workflow_stage,
            "task_title": doc.task_title,
            "status": doc.status,
            "stage_type": stage.stage_type,
            "config": config,
            "draft": json.loads(doc.draft_json or "{}"),
            "response": json.loads(doc.response_json or "{}"),
            "history": history,
            "previous_data": _previous_task_data(instance, exclude_task=doc.name),
            "document": document_context,
        }
    )


@frappe.whitelist(methods=["POST"])
def save_workflow_task_draft(task: str, response: str | dict) -> dict:
    doc = frappe.get_doc("ASOUD Workflow Task", task)
    _assert_task_owner(doc)
    if doc.status != "Open":
        frappe.throw(_("Only an open workflow task can be edited"))
    values = json.loads(response) if isinstance(response, str) else response
    if not isinstance(values, dict):
        frappe.throw(_("Workflow draft must be an object"))
    stage = frappe.get_doc("ASOUD Workflow Stage", doc.workflow_stage)
    fields = json.loads(stage.config_json or "{}").get("form_fields", [])
    allowed_keys = {field.get("key") for field in fields if isinstance(field, dict)}
    if set(values) - allowed_keys:
        frappe.throw(_("Workflow draft contains unknown fields"))
    doc.draft_json = json.dumps(values, ensure_ascii=False)
    doc.save(ignore_permissions=True)
    return success({"task": doc.name, "saved": True})


@frappe.whitelist(methods=["POST"])
def upload_workflow_attachment(task: str, filename: str, content_base64: str) -> dict:
    doc = frappe.get_doc("ASOUD Workflow Task", task)
    _assert_task_owner(doc)
    if doc.status != "Open":
        frappe.throw(_("Only an open workflow task can receive attachments"))
    safe_name = Path(filename or "").name
    if Path(safe_name).suffix.lower() not in ALLOWED_ATTACHMENT_EXTENSIONS:
        frappe.throw(_("Unsupported workflow attachment type"))
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        frappe.throw(_("Invalid attachment data"))
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        frappe.throw(_("Workflow attachment must be between 1 byte and 10 MB"))
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": safe_name,
            "content": content,
            "attached_to_doctype": "ASOUD Workflow Task",
            "attached_to_name": doc.name,
            "is_private": 1,
        }
    ).insert(ignore_permissions=True)
    return success({"file_url": file_doc.file_url, "file_name": file_doc.file_name})


@frappe.whitelist(methods=["POST"])
def complete_workflow_task(
    task: str,
    action: str,
    comment: str | None = None,
    response: str | dict | None = None,
) -> dict:
    if action not in {"Complete", "Approve", "Reject", "Return"}:
        frappe.throw(_("Invalid workflow task action"))
    frappe.db.sql("select name from `tabASOUD Workflow Task` where name = %s for update", task)
    doc = frappe.get_doc("ASOUD Workflow Task", task)
    _assert_task_owner(doc)
    if doc.status != "Open":
        frappe.throw(_("Workflow task has already been completed"))
    stage = frappe.get_doc("ASOUD Workflow Stage", doc.workflow_stage)
    config = json.loads(stage.config_json or "{}")
    allowed_actions = (
        {"Approve", "Reject", "Return"}
        if stage.stage_type == "Approval"
        else {"Complete", "Reject", "Return"}
    )
    if action not in allowed_actions:
        frappe.throw(_("Action is not valid for this workflow stage"))
    if config.get("comment_required") and not (comment or "").strip():
        frappe.throw(_("A decision comment is required"))
    if action == "Reject" and not config.get("allow_reject", False):
        frappe.throw(_("Reject is not allowed for this stage"))
    if action == "Return" and not config.get("allow_return", False):
        frappe.throw(_("Return is not allowed for this stage"))
    if action == "Return" and not (comment or "").strip():
        frappe.throw(_("A return reason is required"))
    normalized_response = {}
    if action in {"Complete", "Approve"}:
        raw_response = response if response is not None else json.loads(doc.draft_json or "{}")
        if isinstance(raw_response, str):
            raw_response = json.loads(raw_response)
        try:
            normalized_response = normalize_form_response(config.get("form_fields", []), raw_response)
        except ValueError as error:
            frappe.throw(_(str(error)))
    doc.status = "Rejected" if action == "Reject" else "Completed"
    doc.action = action
    doc.comment = (comment or "").strip()
    doc.response_json = json.dumps(normalized_response, ensure_ascii=False)
    doc.completed_on = now_datetime()
    doc.save(ignore_permissions=True)
    _record_activity(doc, action, doc.comment)
    instance = frappe.get_doc("ASOUD Workflow Instance", doc.workflow_instance)
    if action == "Reject":
        frappe.db.set_value(
            "ASOUD Workflow Task",
            {
                "workflow_instance": instance.name,
                "workflow_stage": stage.name,
                "status": "Open",
            },
            "status",
            "Cancelled",
            update_modified=False,
        )
        reject_target = _next_stage(instance, stage.name, action)
        if reject_target:
            _activate_stage(instance, reject_target, source_task=doc)
        else:
            instance.status = "Rejected"
            instance.completed_on = now_datetime()
            instance.save(ignore_permissions=True)
        return success({"task": doc.name, "instance_status": instance.status})
    if action == "Return":
        frappe.db.set_value(
            "ASOUD Workflow Task",
            {
                "workflow_instance": instance.name,
                "workflow_stage": stage.name,
                "status": "Open",
            },
            "status",
            "Cancelled",
            update_modified=False,
        )
        return_target = _next_stage(instance, stage.name, action)
        if return_target:
            _activate_stage(instance, return_target, source_task=doc)
        else:
            try:
                previous_stage = select_return_stage(
                    _completed_task_rows(instance, exclude_task=doc.name)
                )
            except ValueError as error:
                frappe.throw(_(str(error)))
            _activate_stage(instance, frappe.get_doc("ASOUD Workflow Stage", previous_stage))
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
        next_stage = _next_stage(instance, stage.name, action)
        if not next_stage:
            frappe.throw(_("Workflow has no next stage"))
        _activate_stage(instance, next_stage, source_task=doc)
    return success({"task": doc.name, "instance_status": instance.status})
