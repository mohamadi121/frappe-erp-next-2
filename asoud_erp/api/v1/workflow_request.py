import base64
import binascii
import hashlib
import json
from pathlib import PurePosixPath as Path

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.api.v1.workflow_runtime import start_workflow_instance
from asoud_erp.services.request_access import request_permission, require_company
from asoud_erp.services.request_link_values import item_uoms, validate_link_values
from asoud_erp.services.workflow_response import normalize_form_response

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".docx"}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _definition(name):
    definition = frappe.get_doc("ASOUD Workflow Definition", name)
    if (definition.status != "Active" or definition.readiness_status != "Ready"
            or definition.target_doctype != "ASOUD Workflow Request"):
        frappe.throw(_("The selected workflow is not ready"))
    if not definition.allow_user_submission:
        frappe.throw(_("Users cannot submit this request type"), frappe.PermissionError)
    return definition


def _may_submit(definition_name, user_roles):
    """The Start stage's initiator roles limit who may submit; none means everyone."""
    config = frappe.db.get_value("ASOUD Workflow Stage",
        {"workflow_definition": definition_name, "stage_type": "Start"}, "config_json")
    roles = json.loads(config or "{}").get("initiator_roles") or []
    return not roles or "System Manager" in user_roles or bool(set(roles) & set(user_roles))


def _fields(definition):
    from asoud_erp.api.v1.workflow_runtime import _next_stage

    start = frappe.db.get_value("ASOUD Workflow Stage",
        {"workflow_definition": definition.name, "stage_type": "Start"}, "name")
    stage = _next_stage(frappe._dict(workflow_definition=definition.name), start) if start else None
    if not stage or stage.stage_type != "User Task":
        frappe.throw("Generic requests require a user-task form immediately after Start")
    return json.loads(stage.config_json or "{}").get("form_fields", [])


def _serialize(doc):
    return {
        "name": doc.name, "company": doc.company,
        "workflow_definition": doc.workflow_definition,
        "request_type": doc.request_type, "subject": doc.subject,
        "priority": doc.priority, "required_by": str(doc.required_by or ""),
        "project": doc.project or "", "department": doc.department or "",
        "values": json.loads(doc.values_json or "{}"),
        "attachments": json.loads(doc.attachments_json or "[]"),
        "workflow_instance": doc.workflow_instance or "", "status": (frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "status") if doc.workflow_instance else doc.status),
        "request_id": doc.request_id,
        "display_status": doc.display_status or "",
        "owner": doc.owner,
    }


@frappe.whitelist()
def request_options(company: str | None = None):
    require_company(company)
    filters = {"status": "Active", "readiness_status": "Ready", "target_doctype": "ASOUD Workflow Request",
               "allow_user_submission": 1}
    if company:
        filters["company"] = ["in", [company, ""]]
    rows = frappe.get_all("ASOUD Workflow Definition", filters=filters,
                          fields=["name", "workflow_code", "workflow_title", "company", "module_key", "target_doctype",
                                  "short_title", "request_category", "process_description", "icon_key",
                                  "color_hex", "show_in_request_list"],
                          order_by="workflow_title asc", limit_page_length=200)
    result = []
    user_roles = frappe.get_roles()
    for row in rows:
        if not _may_submit(row["name"], user_roles):
            continue
        try:
            fields = _fields(frappe.get_doc("ASOUD Workflow Definition", row["name"]))
        except frappe.ValidationError:
            continue
        result.append({**row, "fields": fields})
    return success(result)


@frappe.whitelist(methods=["POST"])
def create_request(company: str, workflow_definition: str, subject: str, request_id: str,
                   values: str | dict = "{}", priority: str = "Normal",
                   required_by: str | None = None, project: str = "",
                   department: str = "", attachments: str | list = "[]"):
    require_company(company)
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")
    raw_values = json.loads(values) if isinstance(values, str) else values
    raw_attachments = json.loads(attachments) if isinstance(attachments, str) else attachments
    fingerprint = hashlib.sha256(json.dumps(dict(company=company, workflow=workflow_definition,
        subject=subject, values=raw_values, attachments=raw_attachments, priority=priority,
        required_by=required_by, project=project, department=department), sort_keys=True).encode()).hexdigest()
    frappe.get_doc("User", frappe.session.user, for_update=True)
    existing = frappe.db.get_value("ASOUD Workflow Request", {"request_id": request_id},
        ["name", "owner", "request_fingerprint"], as_dict=True, for_update=True)
    if existing:
        if existing.owner != frappe.session.user or existing.request_fingerprint != fingerprint:
            frappe.throw("Request ID conflict")
        return get_request(existing.name)
    definition = _definition(workflow_definition)
    if not _may_submit(definition.name, frappe.get_roles()):
        frappe.throw(_("You are not allowed to submit this request type"), frappe.PermissionError)
    if definition.company and definition.company != company:
        frappe.throw(_("Workflow company does not match request company"))
    if priority not in {"Low", "Normal", "High", "Urgent"}:
        frappe.throw(_("Invalid request priority"))
    if required_by and getdate(required_by) < getdate(nowdate()):
        frappe.throw(_("Required-by date cannot be in the past"))
    raw_values = json.loads(values) if isinstance(values, str) else values
    if not isinstance(raw_values, dict):
        frappe.throw("Invalid request values")
    fields = _fields(definition)
    attachment_keys = {f["key"] for f in fields if f.get("type") == "Attachment"}
    normalized = normalize_form_response(fields, {
        key: "/private/files/pending" if key in attachment_keys and value else value
        for key, value in raw_values.items()})
    validate_link_values(fields, normalized, company)
    for doctype, value in (("Project", project), ("Department", department)):
        if value and (not frappe.has_permission(doctype, "read", value)
                      or frappe.db.get_value(doctype, value, "company") != company):
            frappe.throw("Invalid or inaccessible request context", frappe.PermissionError)
    raw_attachments = json.loads(attachments) if isinstance(attachments, str) else attachments
    if not isinstance(raw_attachments, list) or len(raw_attachments) > 10:
        frappe.throw(_("At most 10 attachments are allowed"))
    doc = frappe.get_doc({
        "doctype": "ASOUD Workflow Request", "company": company,
        "workflow_definition": definition.name, "request_type": definition.workflow_title,
        "subject": subject.strip(), "priority": priority, "required_by": required_by,
        "project": project.strip(), "department": department.strip(),
        "values_json": json.dumps(normalized, ensure_ascii=False),
        "attachments_json": "[]",
        "status": "Submitted", "owner": frappe.session.user,
        "request_id": request_id, "request_fingerprint": fingerprint,
    })
    if not 3 <= len(doc.subject) <= 140:
        frappe.throw(_("Request subject must contain at least 3 characters"))
    doc.insert(ignore_permissions=True)
    stored_attachments = []
    urls = {}
    total_size = 0
    for item in raw_attachments:
        if not isinstance(item, dict):
            frappe.throw(_("Invalid request attachment"))
        filename = Path(str(item.get("filename") or "").replace(chr(92), "/")).name
        if not isinstance(item.get("content_base64"), str) or len(item["content_base64"]) > 14 * 1024 * 1024:
            frappe.throw("Attachment exceeds size limit")
        if "attachment:" + filename in urls:
            frappe.throw("Attachment names must be unique")
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            frappe.throw(_("Unsupported request attachment type"))
        try:
            content = base64.b64decode(item.get("content_base64") or "", validate=True)
        except (ValueError, binascii.Error):
            frappe.throw(_("Invalid request attachment data"))
        total_size += len(content)
        if not content or len(content) > MAX_ATTACHMENT_BYTES or total_size > 25 * 1024 * 1024:
            frappe.throw(_("Request attachment must be between 1 byte and 10 MB"))
        file_doc = frappe.get_doc({
            "doctype": "File", "file_name": filename, "content": content,
            "attached_to_doctype": "ASOUD Workflow Request",
            "attached_to_name": doc.name, "is_private": 1,
        }).insert(ignore_permissions=True)
        urls["attachment:" + filename] = file_doc.file_url
        stored_attachments.append({"name": file_doc.name, "filename": filename, "file_url": file_doc.file_url})
    for key in attachment_keys:
        value = raw_values.get(key)
        if value and value not in urls:
            frappe.throw("Attachment field must reference an uploaded file")
        normalized[key] = urls.get(value) if value else None
    doc.values_json = json.dumps(normalized, ensure_ascii=False)
    doc.attachments_json = json.dumps(stored_attachments, ensure_ascii=False)
    doc.save(ignore_permissions=True)
    result = start_workflow_instance(definition=definition.name, subject=doc.subject,
                                     reference_doctype=doc.doctype, reference_name=doc.name)
    instance = result.get("data", {}).get("name", "")
    doc.workflow_instance = instance
    doc.save(ignore_permissions=True)
    return success(_serialize(doc))


@frappe.whitelist()
def request_field_options(company: str, field_type: str, txt: str = "", item_code: str | None = None):
    """Choices for User, Department and Item Table fields, from the ERPNext masters."""
    require_company(company)
    term = f"%{(txt or '').strip()}%"
    if field_type == "User":
        rows = frappe.get_all("Employee",
            filters={"company": company, "status": "Active", "user_id": ["is", "set"]},
            or_filters={"employee_name": ["like", term], "user_id": ["like", term]},
            fields=["user_id as value", "employee_name as label", "department"],
            order_by="employee_name asc", limit_page_length=20)
    elif field_type == "Department":
        rows = frappe.get_all("Department",
            filters={"company": company, "disabled": 0, "department_name": ["like", term]},
            fields=["name as value", "department_name as label"],
            order_by="department_name asc", limit_page_length=20)
    elif field_type == "Item":
        rows = frappe.get_all("Item",
            filters={"disabled": 0, "has_variants": 0},
            or_filters={"item_code": ["like", term], "item_name": ["like", term]},
            fields=["name as value", "item_name as label", "stock_uom"],
            order_by="item_name asc", limit_page_length=20)
    elif field_type == "UOM":
        if not item_code or not frappe.db.exists("Item", item_code):
            frappe.throw(_("Select an item first"))
        rows = [{"value": row["uom"], "label": row["uom"], "conversion_factor": row["conversion_factor"]}
                for row in item_uoms(item_code)]
    else:
        frappe.throw(_("Unsupported field type"))
    return success(rows)


@frappe.whitelist()
def list_my_requests(company: str | None = None):
    require_company(company)
    filters = {"owner": frappe.session.user}
    if company:
        filters["company"] = company
    rows = frappe.get_all("ASOUD Workflow Request", filters=filters,
                          fields=["name"], order_by="creation desc", limit_page_length=200)
    return success([_serialize(frappe.get_doc("ASOUD Workflow Request", row.name)) for row in rows])


@frappe.whitelist()
def get_request(name: str):
    doc = frappe.get_doc("ASOUD Workflow Request", name)
    if not request_permission(doc):
        frappe.throw(_("Not permitted to view this request"), frappe.PermissionError)
    return success(_serialize(doc))


@frappe.whitelist()
def get_attachment(name):
    file = frappe.get_doc("File", name)
    if file.attached_to_doctype != "ASOUD Workflow Request" or not file.is_private:
        frappe.throw("Invalid request attachment", frappe.PermissionError)
    get_request(file.attached_to_name)
    if not str(file.file_url).startswith("/private/files/"):
        frappe.throw("Remote attachments are unsupported")
    content = file.get_content()
    if isinstance(content, str):
        content = content.encode()
    if len(content) > MAX_ATTACHMENT_BYTES:
        frappe.throw("File exceeds download limit")
    return success({"filename": file.file_name, "content_base64": base64.b64encode(content).decode()})
