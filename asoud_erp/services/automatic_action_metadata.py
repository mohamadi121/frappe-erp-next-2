"""Server-owned capabilities, source schemas and least-privilege identity."""

import json
from contextlib import contextmanager
from datetime import date

import frappe

from asoud_erp.services.automatic_action_policy import (
    NUMERIC,
    SYSTEM_FIELDS,
    TEXT,
    VARIABLE,
    normalize_action,
    number,
)
from asoud_erp.services.document_templates import TARGET_FIELDS

DOCUMENTS = ("Material Request", "Journal Entry")
RECORDS = (*DOCUMENTS, "ASOUD Workflow Request")
EDITABLE_TYPES = {"Data", "Small Text", "SmallText", "Text", "Date", "Int", "Float", "Currency", "Percent"}
FORBIDDEN = {
    "name",
    "owner",
    "modified_by",
    "creation",
    "modified",
    "docstatus",
    "status",
    "workflow_state",
    "company",
    "amended_from",
    "naming_series",
    "workflow_instance",
    "request_id",
    "request_fingerprint",
    "values_json",
    "attachments_json",
    "display_status",
    "workflow_definition",
    "request_type",
    "project",
    "department",
}


def service_user(company):
    user = frappe.conf.get("asoud_workflow_service_user")
    companies = frappe.conf.get("asoud_workflow_service_companies") or []
    if (
        not user
        or user in {"Administrator", "Guest"}
        or not isinstance(companies, list)
        or company not in companies
    ):
        raise frappe.PermissionError(
            "Configure a restricted workflow service user and company allowlist first"
        )
    if not frappe.db.get_value("User", user, "enabled") or "System Manager" in frappe.get_roles(user):
        raise frappe.PermissionError("Workflow service user must be enabled and must not be a System Manager")
    if frappe.db.get_value("User", user, "user_type") != "System User":
        raise frappe.PermissionError("Workflow service identity must be a System User")
    if not frappe.has_permission("Company", "read", company, user=user):
        raise frappe.PermissionError("Workflow service user cannot access this company")
    return user


@contextmanager
def identity(company):
    user = service_user(company)
    previous = frappe.session.user
    try:
        frappe.set_user(user)
        yield user
    finally:
        frappe.set_user(previous)


def request_fields(name, company):
    from asoud_erp.api.v1.workflow_request import _fields

    doc = frappe.get_doc("ASOUD Workflow Definition", name)
    if doc.target_doctype != "ASOUD Workflow Request" or doc.company != company:
        raise ValueError("Invalid request type for this company")
    return [{"key": "subject", "label": "عنوان", "type": "Text", "required": True}, *_fields(doc)]


def record_fields(doctype, *, writable=False):
    if doctype not in RECORDS:
        raise ValueError("Record type is not allowlisted")
    fields = []
    for field in frappe.get_meta(doctype).fields:
        if (
            field.fieldtype not in EDITABLE_TYPES
            or field.hidden
            or field.permlevel
            or field.fieldname in FORBIDDEN
            or (writable and (field.read_only or field.set_only_once))
        ):
            continue
        fields.append(
            {
                "key": field.fieldname,
                "label": field.label,
                "type": field.fieldtype,
                "required": bool(field.reqd),
            }
        )
    if not writable:
        fields.extend(
            {"key": key, "label": key, "type": "Text", "required": False} for key in ("name", "status")
        )
    return fields


def prior_stages(definition, stage):
    """Graph ancestry, not visual position. Cyclic/self references are excluded."""
    edges = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={"workflow_definition": definition},
        fields=["from_stage", "to_stage"],
    )

    def reachable(start, backwards):
        seen, pending = set(), [start]
        while pending:
            current = pending.pop()
            for edge in edges:
                source, dest = (
                    (edge.to_stage, edge.from_stage) if backwards else (edge.from_stage, edge.to_stage)
                )
                if source == current and dest not in seen:
                    seen.add(dest)
                    pending.append(dest)
        return seen

    return reachable(stage, True) - reachable(stage, False) - {stage}


def _output_type(row, workflow, visited=None):
    visited = set(visited or ())
    if row.name in visited or row.workflow_definition != workflow.name:
        raise ValueError("Invalid stage output dependency")
    visited.add(row.name)
    config = json.loads(row.config_json or "{}")
    if row.stage_type != "System Action" or config.get("schema_version") != 2:
        return None, None
    op, kind = config["operation"], config["action_type"]
    if kind == "Create Request":
        return "ASOUD Workflow Request", op["request_type"]
    if kind == "Create Document":
        return op["doctype"], None
    if kind == "Send Notification":
        return None, None
    if op["target"]["source"] == "current":
        return workflow.target_doctype, workflow.name
    previous = frappe.get_doc("ASOUD Workflow Stage", op["target"]["stage"])
    return _output_type(previous, workflow, visited)


def schemas(definition, stage):
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    current = record_fields(workflow.target_doctype)
    if workflow.target_doctype == "ASOUD Workflow Request":
        current = request_fields(definition, workflow.company) + [
            {"key": "name", "label": "شماره درخواست", "type": "Text"},
            {"key": "status", "label": "وضعیت", "type": "Text"},
        ]
    prior = []
    for name in sorted(prior_stages(definition, stage)):
        row = frappe.get_doc("ASOUD Workflow Stage", name)
        config = json.loads(row.config_json or "{}")
        fields, doctype, request_type = [], None, None
        if row.stage_type == "User Task":
            fields = config.get("form_fields", [])
        elif row.stage_type == "System Action" and config.get("schema_version") == 2:
            doctype, request_type = _output_type(row, workflow)
            if doctype == "ASOUD Workflow Request":
                fields = request_fields(request_type, workflow.company) + [
                    {"key": "name", "label": "شماره درخواست", "type": "Text"},
                    {"key": "status", "label": "وضعیت", "type": "Text"},
                ]
            elif doctype:
                fields = record_fields(doctype)
        writable = (
            request_fields(request_type, workflow.company)
            if doctype == "ASOUD Workflow Request"
            else record_fields(doctype, writable=True)
            if doctype
            else []
        )
        prior.append(
            {"id": name, "label": row.stage_title, "doctype": doctype, "fields": fields, "writable": writable}
        )
    return {
        "current": current,
        "stages": prior,
        "writable": (
            request_fields(definition, workflow.company)
            if workflow.target_doctype == "ASOUD Workflow Request"
            else record_fields(workflow.target_doctype, writable=True)
        ),
        "system": [{"key": key, "label": key, "type": value} for key, value in SYSTEM_FIELDS.items()],
    }


def target_doctype(operation, workflow, sources):
    selected = operation.get("target", {"source": "current"})
    if selected["source"] == "current":
        return workflow.target_doctype
    row = next((s for s in sources["stages"] if s["id"] == selected["stage"]), None)
    if not row or not row["doctype"]:
        raise ValueError("Target must be a previous stage with a record output")
    return row["doctype"]


def compatible(source_type, destination):
    return (
        source_type == destination
        or source_type in NUMERIC
        and destination in NUMERIC
        or source_type in TEXT
        and destination in TEXT
    )


def validate_mapping(mapping, fields, sources, *, require_all=True):
    targets = {field["key"]: field for field in fields}
    if set(mapping) - targets.keys():
        raise ValueError("Destination field is not writable or allowlisted")
    for key, field in targets.items():
        entry = mapping.get(key)
        if entry is None:
            if require_all and field.get("required"):
                raise ValueError(f"Required field is not mapped: {field['label']}")
            continue
        if field.get("required") and entry["empty"] != "error":
            raise ValueError(f"Required field cannot skip an empty value: {key}")
        if entry["transform"] == "round2" and field["type"] not in NUMERIC:
            raise ValueError("Rounding requires a numeric destination")
        if entry["transform"] == "trim" and field["type"] not in TEXT:
            raise ValueError("Trim requires a text destination")
        if entry["source"] == "constant":
            if field["type"] in NUMERIC:
                number(entry["value"])
            elif field["type"] == "Date":
                date.fromisoformat(str(entry["value"]))
            elif field["type"] == "Checkbox":
                if type(entry["value"]) is not bool:
                    raise ValueError("Checkbox constant must be a boolean")
            elif field["type"] == "Choice":
                if entry["value"] not in field.get("options", []):
                    raise ValueError("Constant is not one of the field's choices")
            elif not isinstance(entry["value"], str):
                raise ValueError("Text and link constants must be strings")
            if field["type"] in {"Table", "Item Table", "Attachment", "Multi Choice"}:
                raise ValueError("This field requires a typed source, not a constant")
            continue
        if entry["source"] == "stage":
            previous = next((s for s in sources["stages"] if s["id"] == entry["stage"]), None)
            choices = previous["fields"] if previous else []
        else:
            choices = sources[entry["source"]]
        src = next((f for f in choices if f["key"] == entry["value"]), None)
        if not src or not compatible(src["type"], field["type"]):
            raise ValueError(f"Source field does not exist or has an incompatible type: {key}")


def validate_config(definition, stage, raw):
    config = normalize_action(raw)
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    sources = schemas(definition, stage)
    op, kind = config["operation"], config["action_type"]
    if kind == "Create Document":
        if op["doctype"] not in DOCUMENTS:
            raise ValueError("Document type is not allowlisted")
        validate_mapping(op["mapping"], TARGET_FIELDS[op["doctype"]], sources)
    elif kind == "Create Request":
        pending, seen = [op["request_type"]], set()
        while pending:
            name = pending.pop()
            if name == definition:
                raise ValueError("Automatic request creation must not form a recursive cycle")
            if name in seen:
                continue
            seen.add(name)
            if len(seen) > 100:
                raise ValueError("Automatic request dependency graph is too large")
            for row in frappe.get_all(
                "ASOUD Workflow Stage",
                filters={"workflow_definition": name, "stage_type": "System Action"},
                pluck="config_json",
            ):
                other = json.loads(row or "{}")
                if other.get("schema_version") == 2 and other.get("action_type") == "Create Request":
                    pending.append(other["operation"]["request_type"])
        validate_mapping(op["mapping"], request_fields(op["request_type"], workflow.company), sources)
    elif kind in {"Update Fields", "Calculate Value"}:
        target_doctype(op, workflow, sources)
        fields = (
            sources["writable"]
            if op["target"]["source"] == "current"
            else next(s["writable"] for s in sources["stages"] if s["id"] == op["target"]["stage"])
        )
        if kind == "Update Fields":
            validate_mapping(op["mapping"], fields, sources, require_all=False)
        else:
            field = next((f for f in fields if f["key"] == op["field"] and f["type"] in NUMERIC), None)
            if not field:
                raise ValueError("Calculation destination must be an editable numeric field")
            validate_mapping(op["inputs"], [{"key": k, "type": field["type"]} for k in op["inputs"]], sources)
    elif kind == "Change Status":
        from frappe.model.workflow import get_workflow

        native = get_workflow(target_doctype(op, workflow, sources))
        if op["transition"] not in {t.action for t in native.transitions}:
            raise ValueError("Transition does not belong to the native workflow")
    elif kind == "Send Notification":
        allowed = {f["key"] for f in sources["current"] if f["type"] not in {"Table", "Item Table"}}
        if set(VARIABLE.findall(op["message"])) - allowed:
            raise ValueError("Message contains an unknown or non-scalar variable")
        for user in op["recipients"]:
            if user != "initiator" and (
                user in {"Administrator", "Guest"} or not frappe.db.get_value("User", user, "enabled")
            ):
                raise ValueError("Recipient does not exist or is disabled")
    else:
        target_doctype(op, workflow, sources)
        fields = record_fields(op["doctype"])
        field = next((f for f in fields if f["key"] == op["lookup_field"]), None)
        if not field:
            raise ValueError("Lookup field is not allowlisted")
        validate_mapping({field["key"]: op["lookup"]}, [field], sources)
    return config


def validate_permissions(definition, stage, config):
    """Activation-time role checks; record/state-dependent checks repeat at runtime."""
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    sources = schemas(definition, stage)
    kind, op = config["action_type"], config["operation"]
    with identity(workflow.company):
        if not frappe.has_permission(workflow.target_doctype, "read"):
            raise frappe.PermissionError("Service user cannot read the workflow source type")
        if kind.startswith("Create"):
            doctype = "ASOUD Workflow Request" if kind == "Create Request" else op["doctype"]
            permission = "create"
        elif kind in {"Update Fields", "Calculate Value", "Change Status"}:
            doctype, permission = target_doctype(op, workflow, sources), "write"
        else:
            doctype, permission = workflow.target_doctype, "read"
        if not frappe.has_permission(doctype, permission):
            raise frappe.PermissionError(f"Service user lacks {permission} permission on {doctype}")
        if op.get("initial_state") == "Submitted" and not frappe.has_permission(doctype, "submit"):
            raise frappe.PermissionError("Service user cannot submit this document type")


def execution_permission(doc, user=None, permission_type=None):
    from asoud_erp.services.request_access import company_access

    if permission_type not in (None, "read", "select"):
        return False
    definition = frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "workflow_definition")
    company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
    return None if company_access(company, user) else False


def execution_query(user=None):
    from asoud_erp.services.request_access import company_access

    allowed = [
        company for company in frappe.get_all("Company", pluck="name") if company_access(company, user)
    ]
    if not allowed:
        return "1=0"
    return (
        "`tabASOUD Action Execution`.`workflow_instance` IN (SELECT i.name FROM `tabASOUD Workflow Instance` i "
        "JOIN `tabASOUD Workflow Definition` d ON d.name=i.workflow_definition WHERE d.company IN ("
        + ",".join(frappe.db.escape(company) for company in allowed)
        + "))"
    )
