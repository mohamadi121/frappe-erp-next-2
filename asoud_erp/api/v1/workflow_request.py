import base64
import hashlib
import json

import frappe
from frappe import _
from frappe.utils import get_fullname, getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.api.v1.workflow_runtime import _next_stage, start_workflow_instance
from asoud_erp.services import request_attachments as files
from asoud_erp.services import request_comments, request_lookup, request_serializer
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import request_permission, require_company
from asoud_erp.services.request_link_values import validate_link_values
from asoud_erp.services.request_status import (
    GROUP_NAMES,
    PRIORITY_LABELS,
    compute_status_key,
    group_keys,
    status_label,
    tab_counts,
)
from asoud_erp.services.request_status import (
    status_group as group_of_status,
)
from asoud_erp.services.request_templates import base as templates
from asoud_erp.services.workflow_history import merge_completed_responses
from asoud_erp.services.workflow_response import (
    attachment_references,
    map_attachment_values,
    normalize_form_response,
)

REQUEST_DOCTYPE = "ASOUD Workflow Request"
ALLOWED_EXTENSIONS = {"." + extension for extension in files.DEFAULT_EXTENSIONS}
MAX_ATTACHMENT_BYTES = files.MAX_FILE_BYTES
PENDING_PREFIX = "/private/files/pending/"
HEADER_PRIORITIES = {"Low", "Normal", "High", "Urgent"}
LIST_MAX_PAGE_LENGTH = 100
MANAGER_ROLES = {"System Manager", "HR Manager"}
# Required-by-setting name -> (Company custom field, error code).
SETTING_RULES = {"request_cost_center_required": ("asoud_request_cost_center_required", "COST_CENTER_REQUIRED")}
DEFAULT_DAILY_HOURS = 8.0


# ------------------------------------------------------------------ definition and form


def _definition(name):
    definition = frappe.get_doc("ASOUD Workflow Definition", name)
    if (definition.status != "Active" or definition.readiness_status != "Ready"
            or definition.target_doctype != REQUEST_DOCTYPE):
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


def _form_stage_or_none(definition_name):
    """The request form: the user task right after Start (None when the workflow has none)."""
    start = frappe.db.get_value("ASOUD Workflow Stage",
        {"workflow_definition": definition_name, "stage_type": "Start"}, "name")
    stage = _next_stage(frappe._dict(workflow_definition=definition_name), start) if start else None
    return stage if stage and stage.stage_type == "User Task" else None


def form_stage_name(definition_name):
    """Name of the form stage of a definition, or None."""
    stage = _form_stage_or_none(definition_name)
    return stage.name if stage else None


def _form_stage(definition):
    stage = _form_stage_or_none(definition.name)
    if not stage:
        frappe.throw("Generic requests require a user-task form immediately after Start")
    return stage


def _fields(definition):
    return json.loads(_form_stage(definition).config_json or "{}").get("form_fields", [])


def _fields_by_name(definition_name):
    """Form fields of a definition by name; empty when it has no request form."""
    stage = _form_stage_or_none(definition_name)
    return json.loads(stage.config_json or "{}").get("form_fields", []) if stage else []


def _spec_for(definition):
    """The TemplateSpec of a system template definition; None for custom request types."""
    if not definition.template_key:
        return None
    spec = templates.get(definition.template_key)
    if not spec:
        templates.throw_error("TEMPLATE_NOT_AVAILABLE")
    return spec


def company_settings(company):
    """Per-company request settings kept on Company (Desk-edited custom fields)."""
    meta = frappe.get_meta("Company")
    names = [field for field in ("asoud_request_cost_center_required", "asoud_daily_working_hours")
             if meta.has_field(field)]
    row = (frappe.db.get_value("Company", company, names, as_dict=True) if names else None) or {}
    return {"cost_center_required": bool(row.get("asoud_request_cost_center_required")),
            "daily_working_hours": float(row.get("asoud_daily_working_hours") or DEFAULT_DAILY_HOURS)}


def _employee_of(company, user):
    return frappe.db.get_value("Employee", {"user_id": user, "company": company, "status": "Active"},
                               ["name", "employee_name", "department", "branch"], as_dict=True)


def effective_values(name):
    """Request values: `values_json` overlaid with what the form task was completed with.

    After a Return the requester corrects the form through the cartable; that response is
    newer than `values_json`, which only the creation and `update_request` write.
    """
    row = frappe.db.get_value(REQUEST_DOCTYPE, name,
        ["values_json", "workflow_instance", "workflow_definition"], as_dict=True)
    if not row:
        return {}
    values = json.loads(row.values_json or "{}")
    stage = form_stage_name(row.workflow_definition) if row.workflow_instance else None
    if stage:
        tasks = frappe.get_all("ASOUD Workflow Task", filters={
            "workflow_instance": row.workflow_instance, "workflow_stage": stage, "status": "Completed"},
            fields=["response_json"], order_by="completed_on asc, creation asc", limit_page_length=0)
        values.update(merge_completed_responses(tasks))
    return values


def _submit_form_task(definition, instance: str, values: dict, request_name: str) -> None:
    """Submitting the request fills the form stage when that task is the requester's own."""
    from asoud_erp.api.v1.workflow_runtime import complete_workflow_task

    task = frappe.db.get_value("ASOUD Workflow Task", {
        "workflow_instance": instance, "status": "Open", "assigned_to": frappe.session.user,
        "workflow_stage": _form_stage(definition).name}, "name")
    if task:
        # The values were validated by create_request; do not run the template rules twice.
        frappe.flags.asoud_request_form_validated = request_name
        try:
            complete_workflow_task(task, "Complete", response=values)
        finally:
            frappe.flags.asoud_request_form_validated = None


# ------------------------------------------------------------------ engine rules


def _apply_locked_defaults(fields, raw: dict, user: str) -> dict:
    """The requester field is the session user; a different value is refused."""
    result = dict(raw)
    for field in fields:
        if field.get("default_source") == "session_user" and field.get("editable") is False:
            key = field["key"]
            if result.get(key) in (None, ""):
                result[key] = user
            elif result[key] != user:
                templates.throw_error("REQUESTER_MISMATCH")
    return result


def _engine_checks(fields, values: dict, company: str, previous: dict | None) -> None:
    """Rules every form field with these attributes gets, whatever the template does on top."""
    needed = [field for field in fields if field.get("required_by_setting") or field.get("min_date")]
    if not needed:
        return
    settings = company_settings(company)
    today = getdate(nowdate())
    for field in needed:
        value = values.get(field["key"])
        rule = SETTING_RULES.get(field.get("required_by_setting"))
        if rule and settings["cost_center_required"] and value in (None, "", []):
            templates.throw_error(rule[1])
        if field.get("min_date") == "today" and value and getdate(value) < today and (
                previous is None or previous.get(field["key"]) != value):
            templates.throw_error("DATE_IN_PAST")


def _normalize(fields, raw_values, mapper):
    try:
        return normalize_form_response(fields, map_attachment_values(fields, raw_values, mapper))
    except ValueError as error:
        frappe.throw(_(str(error)))


def _parse_json(value, message: str, code: str | None = None):
    """A JSON argument given as text or already parsed; malformed text is a validation error."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        if code:
            templates.throw_error(code)
        frappe.throw(_(message))


def _pending_url(key: str) -> str:
    return PENDING_PREFIX + key


def _search_text(name, subject, requester_name, department, project, values) -> str:
    department_name = (frappe.db.get_value("Department", department, "department_name")
                       if department else "") or department or ""
    return request_serializer.build_search_text(
        name, subject, requester_name, department_name, project or "", request_serializer.item_rows_of(values))


def _header(spec, values: dict, subject: str, priority, required_by, project, department) -> dict:
    """Priority, required-by date, project, department and subject of the request row.

    A system template derives them from the validated values; a client value that
    conflicts is ignored. Custom request types use what the client sent.
    """
    if not spec:
        return {"subject": subject.strip(), "priority": priority, "required_by": required_by,
                "project": (project or "").strip(), "department": (department or "").strip()}
    derived = spec.denormalize(values)
    built = spec.build_subject(values) if spec.subject_mode == "generated" and spec.build_subject else subject
    if not (built or "").strip():
        built = spec.short_title or spec.title
    return {"subject": (built or "").strip(), "priority": derived.get("priority") or "Normal",
            "required_by": derived.get("required_by") or None, "project": derived.get("project") or "",
            "department": derived.get("department") or ""}


def _check_subject(subject: str) -> None:
    if not 3 <= len(subject) <= 140:
        frappe.throw(_("Request subject must contain at least 3 characters"))


def _store_new_files(doc, uploads, existing_entries, removed_names):
    """Saves uploads and returns `(key -> file_url, new entries without scope)`.

    A file already attached to the request with the same name, size and content hash is
    reused, so replaying an update never duplicates it.
    """
    urls: dict[str, str] = {}
    entries: list[dict] = []
    existing = {}
    if existing_entries:
        hashes = dict(frappe.get_all("File", filters={"name": ["in", [e["name"] for e in existing_entries]]},
                                     fields=["name", "content_hash"], as_list=True))
        existing = {(e["filename"], int(e.get("size") or 0), hashes.get(e["name"])): e
                    for e in existing_entries if e["name"] not in removed_names}
    for upload in uploads:
        digest = hashlib.md5(upload.content, usedforsecurity=False).hexdigest()
        match = existing.get((upload.filename, len(upload.content), digest))
        if match:
            urls[upload.key] = match["file_url"]
            continue
        stored = files.store_uploads(doc.name, [upload])[0]
        urls[upload.key] = stored["file_url"]
        entries.append({"name": stored["name"], "filename": upload.filename, "file_url": stored["file_url"],
                        "size": stored["size"]})
    return urls, entries


def _entries_with_scopes(entries, fields, values) -> list[dict]:
    scopes = files.file_scopes(attachment_references(fields, values), {})
    return [files.entry(item["name"], item["filename"], item["file_url"], item.get("size") or 0,
                        scopes.get(item["file_url"], "general")) for item in entries]


# ------------------------------------------------------------------ status and detail


def _instance_row(instance_name):
    if not instance_name:
        return None
    return frappe.db.get_value("ASOUD Workflow Instance", instance_name,
                               ["name", "status", "current_stage", "started_by"], as_dict=True)


def _status_fields(doc, instance_status) -> dict:
    key = doc.status_key or compute_status_key(instance_status, doc.status)
    return {"status": instance_status or doc.status, "display_status": doc.display_status or "",
            "status_key": key, "status_label": status_label(key, doc.display_status, instance_status),
            "status_group": group_of_status(key)}


def _has_acted(instance_name, form_stage) -> bool:
    filters = {"workflow_instance": instance_name, "status": ["in", ["Completed", "Rejected"]]}
    if form_stage:
        filters["workflow_stage"] = ["!=", form_stage]
    return bool(frappe.db.exists("ASOUD Workflow Task", filters))


def _rejection_reason(instance_name) -> str:
    if not instance_name:
        return ""
    return frappe.db.get_value("ASOUD Workflow Task", {"workflow_instance": instance_name, "status": "Rejected"},
                               "comment", order_by="completed_on desc") or ""


def _requester_name(owner: str) -> str:
    return frappe.db.get_value("Employee", {"user_id": owner}, "employee_name") or get_fullname(owner)


def _detail(doc) -> dict:
    instance = _instance_row(doc.workflow_instance)
    instance_status = instance.status if instance else None
    fields = _fields_by_name(doc.workflow_definition)
    values = effective_values(doc.name)
    stored = json.loads(doc.attachments_json or "[]")
    missing = [item["name"] for item in stored if not item.get("size")]
    sizes = dict(frappe.get_all("File", filters={"name": ["in", missing]}, fields=["name", "file_size"],
                                as_list=True)) if missing else {}
    entries = _entries_with_scopes(
        [{**item, "size": item.get("size") or sizes.get(item["name"]) or 0} for item in stored], fields, values)
    by_url = {entry["file_url"]: entry for entry in entries}
    owner = doc.owner == frappe.session.user
    running = instance_status == "Running"
    form_stage = form_stage_name(doc.workflow_definition) if instance else None
    can_edit = owner and running and not _has_acted(instance.name, form_stage)
    privileged = bool(MANAGER_ROLES & set(frappe.get_roles()))
    return {
        "name": doc.name, "number": doc.name, "company": doc.company, "template_key": doc.template_key or "",
        "template_version": doc.template_version or 0, "workflow_definition": doc.workflow_definition,
        "request_type": doc.request_type, "subject": doc.subject, "priority": doc.priority,
        "required_by": str(doc.required_by or ""), "project": doc.project or "", "department": doc.department or "",
        "owner": doc.owner, "requester_name": _requester_name(doc.owner),
        "requester_employee": doc.requester_employee or "", "creation": str(doc.creation or ""),
        "workflow_instance": doc.workflow_instance or "", **_status_fields(doc, instance_status),
        "request_id": doc.request_id, "rejection_reason": _rejection_reason(doc.workflow_instance),
        "can_edit": bool(can_edit), "can_cancel": bool(owner and running),
        "item_count": request_serializer.item_count(values), "attachment_count": len(entries),
        "comment_count": request_comments.count_comments(doc.name),
        "values": request_serializer.with_attachment_refs(values, by_url),
        "attachments": entries, "fields": fields,
        "native": {"doctype": doc.native_doctype or "", "name": doc.native_name or "",
                   "status": doc.native_status or "", "error": (doc.native_error or "") if privileged else ""},
    }


def _readable_request(name):
    doc = frappe.get_doc(REQUEST_DOCTYPE, name)
    if not request_permission(doc):
        frappe.throw(_("Not permitted to view this request"), frappe.PermissionError)
    return doc


# ------------------------------------------------------------------ options


def _label(doctype, name, field):
    return (frappe.db.get_value(doctype, name, field) if name else "") or name or ""


def _builtin_default(source, company, user, employee):
    if source == "today":
        return nowdate(), None
    if source == "session_user":
        return user, (employee.employee_name if employee else get_fullname(user))
    if not employee:
        return None, None
    if source == "employee_department" and employee.department:
        return employee.department, _label("Department", employee.department, "department_name")
    if source == "employee_branch" and employee.branch:
        return employee.branch, employee.branch
    return None, None


def _resolve_form_fields(fields, company, user, employee, spec, settings):
    """Fields with default_source and required_by_setting replaced by concrete values."""
    spec_defaults = spec.resolve_defaults(company, user) if spec else {}
    resolved = []
    for field in fields:
        field = dict(field)
        source = field.pop("default_source", None)
        default = spec_defaults.get(field.get("key"))
        if default:
            value, label = default.get("value"), default.get("label")
        else:
            value, label = _builtin_default(source, company, user, employee) if source else (None, None)
        if value is not None:
            field["default_value"] = value
            if label is not None:
                field["default_label"] = label
        rule = SETTING_RULES.get(field.get("required_by_setting"))
        if rule:
            field["required"] = settings["cost_center_required"]
        resolved.append(field)
    return resolved


@frappe.whitelist()
def request_options(company: str | None = None):
    require_company(company)
    filters = {"status": "Active", "readiness_status": "Ready", "target_doctype": REQUEST_DOCTYPE,
               "allow_user_submission": 1}
    if company:
        filters["company"] = ["in", [company, ""]]
    rows = frappe.get_all("ASOUD Workflow Definition", filters=filters,
                          fields=["name", "workflow_code", "workflow_title", "company", "module_key", "target_doctype",
                                  "short_title", "request_category", "process_description", "icon_key",
                                  "color_hex", "show_in_request_list", "template_key", "template_version"],
                          order_by="is_system_template desc, workflow_title asc", limit_page_length=200)
    user, user_roles = frappe.session.user, frappe.get_roles()
    settings = company_settings(company)
    employee = _employee_of(company, user)
    result = []
    for row in rows:
        if not _may_submit(row["name"], user_roles):
            continue
        fields = _fields_by_name(row["name"])
        if not fields:
            continue
        spec = templates.get(row.template_key) if row.template_key else None
        if row.template_key and (not spec or not spec.available_for(company, user)):
            continue
        limits = (spec.attachments if spec else None) or {
            "max_files": files.MAX_FILES, "max_mb": 10, "extensions": list(files.DEFAULT_EXTENSIONS)}
        result.append({
            **row, "template_key": row.template_key or "", "template_version": row.template_version or 0,
            "subject_mode": spec.subject_mode if spec else "input", "subject_label": "عنوان درخواست",
            "number_prefix": spec.number_prefix if spec else "", "settings": settings, "attachments": limits,
            "fields": _resolve_form_fields(fields, company, user, employee, spec, settings)})
    return success(result)


@frappe.whitelist()
def request_field_options(company: str, field_type: str, txt: str = "", item_code: str | None = None,
                          scope: str | None = None, limit_start: int = 0, limit_page_length: int = 20):
    """Choices for User, Department, Item, UOM and System Select fields, from the ERPNext masters."""
    require_company(company)
    return success(request_lookup.search(company, field_type, txt, item_code, scope, limit_start,
                                         limit_page_length))


# ------------------------------------------------------------------ create


@frappe.whitelist(methods=["POST"])
def create_request(company: str, workflow_definition: str | None = None, subject: str = "",
                   request_id: str = "", values: str | dict = "{}", priority: str = "Normal",
                   required_by: str | None = None, project: str = "", department: str = "",
                   attachments: str | list = "[]", template_key: str | None = None):
    # `request_id` follows `subject` to keep the original positional order of this endpoint.
    require_company(company)
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")
    raw_values = _parse_json(values, "Invalid request values")
    raw_attachments = _parse_json(attachments, "Invalid request attachment", "ATTACHMENT_INVALID")
    payload = dict(company=company, workflow=workflow_definition, subject=subject, values=raw_values,
                   attachments=raw_attachments, priority=priority, required_by=required_by,
                   project=project, department=department)
    if template_key:
        payload["template_key"] = template_key  # absent for old payloads, so their fingerprints still match
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    frappe.get_doc("User", frappe.session.user, for_update=True)
    existing = frappe.db.get_value(REQUEST_DOCTYPE, {"request_id": request_id},
        ["name", "owner", "request_fingerprint"], as_dict=True, for_update=True)
    if existing:
        if existing.owner != frappe.session.user or existing.request_fingerprint != fingerprint:
            templates.throw_error("REQUEST_ID_CONFLICT")
        return success(_detail(_readable_request(existing.name)))
    if template_key:
        workflow_definition = frappe.db.get_value("ASOUD Workflow Definition", {
            "company": company, "template_key": template_key, "status": "Active", "readiness_status": "Ready"},
            "name")
        if not workflow_definition:
            templates.throw_error("TEMPLATE_NOT_AVAILABLE")
    elif not workflow_definition:
        frappe.throw(_("A request type is required"))
    definition = _definition(workflow_definition)
    if not _may_submit(definition.name, frappe.get_roles()):
        frappe.throw(_("You are not allowed to submit this request type"), frappe.PermissionError)
    if definition.company and definition.company != company:
        frappe.throw(_("Workflow company does not match request company"))
    spec = _spec_for(definition)
    employee = _employee_of(company, frappe.session.user)
    if spec and not (employee and spec.available_for(company, frappe.session.user)):
        templates.throw_error("EMPLOYEE_NOT_FOUND")
    if not spec:
        if priority not in HEADER_PRIORITIES:
            frappe.throw(_("Invalid request priority"))
        if required_by and getdate(required_by) < getdate(nowdate()):
            frappe.throw(_("Required-by date cannot be in the past"))
    if not isinstance(raw_values, dict):
        frappe.throw(_("Invalid request values"))
    fields = _fields(definition)
    limits = files.limits_from(spec.attachments if spec else None)
    try:
        uploads = files.parse_uploads(raw_attachments, **limits)
    except files.AttachmentError as error:
        templates.throw_error("ATTACHMENT_INVALID", str(error))
    known = {upload.key for upload in uploads}

    def pending_reference(value):
        if not isinstance(value, str) or value not in known:
            templates.throw_error("ATTACHMENT_INVALID", "فیلد پیوست باید به یک فایل بارگذاری‌شده اشاره کند.")
        return _pending_url(value)

    raw_values = _apply_locked_defaults(fields, raw_values, frappe.session.user)
    normalized = _normalize(fields, raw_values, pending_reference)
    _engine_checks(fields, normalized, company, None)
    validate_link_values(fields, normalized, company)
    if spec:
        normalized = spec.validate(templates.ValidationContext(
            company=company, user=frappe.session.user, employee=employee.name, values=normalized, fields=fields,
            is_update=False, previous=None, definition=definition.name))
    header = _header(spec, normalized, subject, priority, required_by, project, department)
    if not spec:
        for doctype, value in (("Project", header["project"]), ("Department", header["department"])):
            if value and (not frappe.has_permission(doctype, "read", value)
                          or frappe.db.get_value(doctype, value, "company") != company):
                frappe.throw("Invalid or inaccessible request context", frappe.PermissionError)
    _check_subject(header["subject"])
    # Anyone who may submit creates their own request; access is decided by roles and company above.
    doc = frappe.get_doc({
        "doctype": REQUEST_DOCTYPE, "company": company,
        "workflow_definition": definition.name, "request_type": definition.workflow_title,
        "subject": header["subject"], "priority": header["priority"], "required_by": header["required_by"],
        "project": header["project"], "department": header["department"],
        "values_json": json.dumps(normalized, ensure_ascii=False),
        "attachments_json": "[]", "status": "Submitted", "status_key": "submitted",
        "owner": frappe.session.user, "request_id": request_id, "request_fingerprint": fingerprint,
        "template_key": definition.template_key or "", "template_version": definition.template_version or 0,
        "requester_employee": employee.name if employee else None,
    }).insert(ignore_permissions=True)
    urls, entries = _store_new_files(doc, uploads, [], set())
    final = map_attachment_values(fields, normalized, lambda value: urls[value[len(PENDING_PREFIX):]])
    references = attachment_references(fields, final)
    scopes = files.file_scopes(references, {})
    doc.values_json = json.dumps(final, ensure_ascii=False)
    doc.attachments_json = json.dumps([
        files.entry(item["name"], item["filename"], item["file_url"], item["size"],
                    scopes.get(item["file_url"], "general")) for item in entries], ensure_ascii=False)
    doc.search_text = _search_text(doc.name, doc.subject, employee.employee_name if employee else
                                   get_fullname(frappe.session.user), doc.department, doc.project, final)
    doc.save(ignore_permissions=True)
    result = start_workflow_instance(definition=definition.name, subject=doc.subject,
                                     reference_doctype=doc.doctype, reference_name=doc.name)
    instance = result.get("data", {}).get("name", "")
    doc.workflow_instance = instance
    doc.save(ignore_permissions=True)
    if instance:
        _submit_form_task(definition, instance, final, doc.name)
    doc.reload()
    return success(_detail(doc))


# ------------------------------------------------------------------ change and cancel


def _own_running_request(name, not_editable_code: bool = False):
    doc = frappe.get_doc(REQUEST_DOCTYPE, name, for_update=True)
    if doc.owner != frappe.session.user:
        frappe.throw(_("Only the requester can change this request"), frappe.PermissionError)
    require_company(doc.company)
    instance = (frappe.get_doc("ASOUD Workflow Instance", doc.workflow_instance)
                if doc.workflow_instance else None)
    if not instance or instance.status != "Running":
        if not_editable_code:
            templates.throw_error("REQUEST_NOT_EDITABLE")
        frappe.throw(_("Only a request in progress can be changed"))
    return doc, instance


def _activity(instance, action: str, comment: str = "") -> None:
    frappe.get_doc({
        "doctype": "ASOUD Workflow Activity", "workflow_instance": instance.name,
        "workflow_stage": instance.current_stage, "actor": frappe.session.user,
        "action": action, "comment": comment[:1000], "created_on": now_datetime(),
    }).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def cancel_request(name: str, reason: str = ""):
    """The requester withdraws a request that is still in progress."""
    doc, instance = _own_running_request(name)
    frappe.db.set_value("ASOUD Workflow Task", {"workflow_instance": instance.name, "status": "Open"},
                        "status", "Cancelled", update_modified=False)
    instance.status = "Cancelled"
    instance.completed_on = now_datetime()
    instance.save(ignore_permissions=True)
    _activity(instance, "Cancelled", (reason or "").strip())
    doc.db_set("status", "Cancelled")
    doc.reload()
    return success(_detail(doc))


def _json_list(value, message, code=None):
    parsed = _parse_json(value, message, code)
    if not isinstance(parsed, list):
        if code:
            templates.throw_error(code)
        frappe.throw(_(message))
    return parsed


@frappe.whitelist(methods=["POST"])
def update_request(name: str, subject: str = "", values: str | dict = "{}", attachments: str | list = "[]",
                   remove_attachments: str | list = "[]"):
    """The requester edits a request until someone else has acted on it.

    `attachments` adds inline files; `remove_attachments` lists File names of this request
    to delete (form values pointing at them are cleared). An attachment key missing from
    `values` keeps its stored file. The form stage's response is updated too, so later
    stages see the corrected values.
    """
    doc, instance = _own_running_request(name, not_editable_code=True)
    definition = frappe.get_doc("ASOUD Workflow Definition", doc.workflow_definition)
    form_stage = _form_stage(definition)
    if _has_acted(instance.name, form_stage.name):
        templates.throw_error("REQUEST_NOT_EDITABLE")
    spec = _spec_for(definition)
    raw = _parse_json(values, "Invalid request values")
    if not isinstance(raw, dict):
        frappe.throw(_("Invalid request values"))
    fields = json.loads(form_stage.config_json or "{}").get("form_fields", [])
    previous = effective_values(doc.name)
    stored = json.loads(doc.attachments_json or "[]")
    by_name = {item["name"]: item for item in stored}
    remove = set(str(item) for item in _json_list(remove_attachments, "Invalid attachment list", "ATTACHMENT_INVALID"))
    for file_name in remove - set(by_name):
        # Already removed by an earlier attempt is fine; any other File is not this request's.
        if frappe.db.exists("File", file_name):
            templates.throw_error("ATTACHMENT_INVALID")
    removed_urls = {by_name[file_name]["file_url"] for file_name in remove if file_name in by_name}
    kept = [item for item in stored if item["name"] not in remove]
    limits = files.limits_from(spec.attachments if spec else None)
    try:
        uploads = files.parse_uploads(
            _json_list(attachments, "Invalid request attachment", "ATTACHMENT_INVALID"), **{**limits, "max_files": 10 ** 6},
            existing_bytes=sum(int(item.get("size") or 0) for item in kept))
        total_after = len(kept) + len(uploads)
        if total_after > limits["max_files"]:
            raise files.AttachmentError(f"حداکثر {limits['max_files']} پیوست مجاز است.")
    except files.AttachmentError as error:
        templates.throw_error("ATTACHMENT_INVALID", str(error))
    known = {upload.key for upload in uploads}
    allowed_urls = {item["file_url"] for item in kept}
    attachment_keys = {field["key"] for field in fields if field.get("type") == "Attachment"}
    merged = {**raw, **{key: previous.get(key) for key in attachment_keys if key not in raw}}
    merged = _apply_locked_defaults(fields, merged, doc.owner)
    merged = map_attachment_values(fields, merged, lambda value: None if value in removed_urls else value)
    for field in fields:
        if field.get("type") == "Attachment" and field.get("required") and not merged.get(field["key"]):
            templates.throw_error("ATTACHMENT_INVALID", "فایل الزامی نمی‌تواند حذف شود.")

    def update_reference(value):
        if isinstance(value, str) and value in known:
            return _pending_url(value)
        if not isinstance(value, str) or value not in allowed_urls:
            templates.throw_error("ATTACHMENT_INVALID", "فیلد پیوست باید به یک فایل این درخواست اشاره کند.")
        return value

    normalized = _normalize(fields, merged, update_reference)
    _engine_checks(fields, normalized, doc.company, previous)
    validate_link_values(fields, normalized, doc.company)
    employee = _employee_of(doc.company, doc.owner)
    if spec:
        normalized = spec.validate(templates.ValidationContext(
            company=doc.company, user=doc.owner, employee=employee.name if employee else None,
            values=normalized, fields=fields, is_update=True, previous=previous, request_name=doc.name,
            definition=definition.name))
    subject = (subject or "").strip() or doc.subject
    header = _header(spec, normalized, subject, doc.priority, doc.required_by, doc.project, doc.department)
    _check_subject(header["subject"])
    urls, added = _store_new_files(doc, uploads, stored, remove)
    final = map_attachment_values(
        fields, normalized, lambda value: urls[value[len(PENDING_PREFIX):]] if value.startswith(PENDING_PREFIX)
        else value)
    doc.subject = header["subject"]
    if spec:
        doc.priority, doc.required_by = header["priority"], header["required_by"]
        doc.project, doc.department = header["project"], header["department"]
    doc.values_json = json.dumps(final, ensure_ascii=False)
    doc.attachments_json = json.dumps(_entries_with_scopes(
        [{**item, "size": item.get("size") or 0} for item in kept] + added, fields, final), ensure_ascii=False)
    doc.search_text = _search_text(doc.name, doc.subject, _requester_name(doc.owner), doc.department,
                                   doc.project, final)
    doc.save(ignore_permissions=True)
    instance.subject = doc.subject
    instance.save(ignore_permissions=True)
    task = frappe.db.get_value("ASOUD Workflow Task", {
        "workflow_instance": instance.name, "workflow_stage": form_stage.name,
        "status": "Completed"}, "name")
    if task:
        frappe.db.set_value("ASOUD Workflow Task", task, "response_json",
                            json.dumps(final, ensure_ascii=False))
    files.delete_files([file_name for file_name in remove if file_name in by_name])
    _activity(instance, "Edited")
    doc.reload()
    return success(_detail(doc))


# ------------------------------------------------------------------ list and detail


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _names(doctype, names, field, key="name"):
    names = sorted({name for name in names if name})
    if not names:
        return {}
    return {row[key]: row[field] for row in frappe.get_all(
        doctype, filters={key: ["in", names]}, fields=[key, field], limit_page_length=0)}


def _list_item(row, instance_status, owner_names, labels, reasons):
    values = json.loads(row.values_json or "{}")
    key = row.status_key or compute_status_key(instance_status, row.status)
    request_row = {**row, "rejection_reason": reasons.get(row.workflow_instance, ""), "_labels": labels}
    spec = templates.get(row.template_key) if row.template_key else None
    try:
        summary = spec.summarize(values, request_row) if spec else request_serializer.default_summary(
            values, request_row, labels)
    except (KeyError, TypeError, ValueError):
        summary = request_serializer.default_summary(values, request_row, labels)
    summary.setdefault("rejection_reason", request_row["rejection_reason"])
    return {
        "name": row.name, "number": row.name, "company": row.company,
        "workflow_definition": row.workflow_definition, "request_type": row.request_type,
        "template_key": row.template_key or "", "subject": row.subject, "priority": row.priority,
        "required_by": str(row.required_by or ""), "project": row.project or "",
        "department": row.department or "", "workflow_instance": row.workflow_instance or "",
        "status": instance_status or row.status, "display_status": row.display_status or "",
        "status_key": key, "status_label": status_label(key, row.display_status, instance_status),
        "status_group": group_of_status(key), "request_id": row.request_id, "owner": row.owner,
        "requester_name": owner_names.get(row.owner) or get_fullname(row.owner),
        "creation": str(row.creation or ""), "item_count": request_serializer.item_count(values),
        "attachment_count": len(json.loads(row.attachments_json or "[]")), "summary": summary,
        "native_status": row.native_status or "",
    }


@frappe.whitelist()
def list_my_requests(company: str | None = None, template_key: str | None = None, status_group: str = "all",
                     search: str = "", priority: str | None = None, date_from: str | None = None,
                     date_to: str | None = None, limit_start: int = 0, limit_page_length: int = 50):
    """The caller's own requests, newest first, filtered and paginated in SQL.

    `date_from`/`date_to` bound the request date (creation). `meta.counts` ignores `status_group`.
    """
    require_company(company)
    if status_group not in ("all", *GROUP_NAMES):
        frappe.throw(_("Invalid status group"))
    if priority and priority not in PRIORITY_LABELS:
        frappe.throw(_("Invalid request priority"))
    try:
        start = max(0, int(limit_start))
        length = max(1, min(int(limit_page_length), LIST_MAX_PAGE_LENGTH))
    except (TypeError, ValueError):
        frappe.throw(_("Invalid page"))
    filters = [["owner", "=", frappe.session.user]]
    if company:
        filters.append(["company", "=", company])
    if template_key:
        filters.append(["template_key", "=", template_key])
    if priority:
        filters.append(["priority", "=", priority])
    if (search or "").strip():
        filters.append(["search_text", "like", _like(search.strip())])
    if date_from:
        filters.append(["creation", ">=", f"{getdate(date_from)} 00:00:00"])
    if date_to:
        filters.append(["creation", "<=", f"{getdate(date_to)} 23:59:59"])
    grouped = frappe.get_all(REQUEST_DOCTYPE, filters=filters, fields=["status_key", "count(name) as total"],
                             group_by="status_key", limit_page_length=0)
    counts = tab_counts({row["status_key"] or "submitted": row["total"] for row in grouped})
    page_filters = filters + ([["status_key", "in", group_keys(status_group)]] if status_group != "all" else [])
    rows = frappe.get_all(
        REQUEST_DOCTYPE, filters=page_filters,
        fields=["name", "company", "workflow_definition", "request_type", "subject", "priority", "required_by",
                "project", "department", "workflow_instance", "status", "display_status", "request_id", "owner",
                "creation", "template_key", "status_key", "values_json", "attachments_json", "native_status"],
        order_by="creation desc, name desc", limit_start=start, limit_page_length=length)
    instances = [row.workflow_instance for row in rows if row.workflow_instance]
    instance_status = _names("ASOUD Workflow Instance", instances, "status")
    owner_names = _names("Employee", [row.owner for row in rows], "employee_name", key="user_id")
    summary_values = [json.loads(row.values_json or "{}") for row in rows]
    labels = {
        "department": _names("Department", [row.department for row in rows] + [
            value.get("org_unit") for value in summary_values], "department_name"),
        "project": _names("Project", [row.project for row in rows] + [
            value.get("project") for value in summary_values], "project_name"),
        "branch": {value.get("location"): value.get("location") for value in summary_values
                   if value.get("location")},
    }
    reasons = {}
    if instances:
        reasons = {key: item["comment"] or "" for key, item in request_serializer.first_per_key(
            frappe.get_all("ASOUD Workflow Task", filters={"workflow_instance": ["in", instances],
                                                           "status": "Rejected"},
                           fields=["workflow_instance", "comment"], order_by="completed_on desc",
                           limit_page_length=0), "workflow_instance").items()}
    data = [_list_item(row, instance_status.get(row.workflow_instance), owner_names, labels, reasons)
            for row in rows]
    return success(data, meta={"total": counts[status_group], "limit_start": start,
                               "limit_page_length": length, "counts": counts})


@frappe.whitelist()
def get_request(name: str):
    return success(_detail(_readable_request(name)))


# ------------------------------------------------------------------ comments


@frappe.whitelist()
def list_request_comments(name: str, limit_start: int = 0, limit_page_length: int = 50):
    doc = _readable_request(name)
    try:
        start = max(0, int(limit_start))
        length = max(1, min(int(limit_page_length), LIST_MAX_PAGE_LENGTH))
    except (TypeError, ValueError):
        frappe.throw(_("Invalid page"))
    comments, total = request_comments.list_comments(doc, start, length)
    return success(comments, meta={"total": total, "limit_start": start, "limit_page_length": length})


@frappe.whitelist(methods=["POST"])
def add_request_comment(name: str, content: str = ""):
    """Any participant may comment, in any status. Replay-safe through sync.execute_mutation."""
    return success(request_comments.add_comment(_readable_request(name), content))


# ------------------------------------------------------------------ attachments and native documents


@frappe.whitelist()
def get_attachment(name, thumbnail: int | str = 0):
    file = frappe.get_doc("File", name)
    if file.attached_to_doctype != REQUEST_DOCTYPE or not file.is_private:
        frappe.throw("Invalid request attachment", frappe.PermissionError)
    _readable_request(file.attached_to_name)
    if not str(file.file_url).startswith("/private/files/"):
        frappe.throw("Remote attachments are unsupported")
    content = file.get_content()
    if isinstance(content, str):
        content = content.encode()
    if len(content) > MAX_ATTACHMENT_BYTES:
        frappe.throw("File exceeds download limit")
    if str(thumbnail).lower() in {"1", "true"}:
        content = files.thumbnail(content, file.file_name or "")
    return success({"filename": file.file_name, "content_type": files.content_type(file.file_name or ""),
                    "size": len(content), "content_base64": base64.b64encode(content).decode()})


@frappe.whitelist(methods=["POST"])
def create_native_document(name: str):
    """Retries the native document of an approved request whose first attempt failed."""
    from asoud_erp.services.request_native_documents import dispatch

    require_roles(("System Manager", "HR Manager", "Purchase Manager"))
    doc = frappe.get_doc(REQUEST_DOCTYPE, name, for_update=True)
    require_company(doc.company)
    status = frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "status") \
        if doc.workflow_instance else None
    if status != "Completed" or doc.native_status != "Failed":
        templates.throw_error("NATIVE_NOT_RETRYABLE")
    dispatch(doc)
    doc.reload()
    return success(_detail(doc))
