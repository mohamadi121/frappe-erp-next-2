"""Document templates («الگوهای سند») used by the workflow "Create Document" action.

A template maps request, user, company and system values onto a standard
ERPNext document (Journal Entry, Material Request). The document is inserted
through ERPNext's own controller, so its validation, naming and GL posting are
unchanged; this module only stores the mapping (see
`services/document_templates.py`) and runs it.
"""

import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.document_templates import (
    LINK_TARGETS,
    MODULES,
    ORGANIZATION_VALUES,
    PLACEHOLDERS,
    PRESETS,
    REQUEST_BASE_FIELDS,
    SYSTEM_VALUES,
    TARGET_FIELDS,
    USER_VALUES,
    build_document,
    normalize_template,
    render_placeholders,
    resolve_values,
)
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import require_company

DOCTYPE = "ASOUD Document Template"
MANAGER_ROLES = ("System Manager", "Accounts Manager", "Purchase Manager")
# Roles that may save a template of each module.
MODULE_ROLES = {
    "Finance": ("System Manager", "Accounts Manager"),
    "Purchase": ("System Manager", "Purchase Manager"),
}
_LINK_RULES = {
    # DocType: (extra filters, has company)
    "Account": ({"is_group": 0, "disabled": 0}, True),
    "Cost Center": ({"is_group": 0, "disabled": 0}, True),
    "Project": ({"status": ["!=", "Cancelled"]}, True),
    "Warehouse": ({"is_group": 0, "disabled": 0}, True),
}


def _options(values: dict[str, str]) -> list[dict]:
    return [{"key": key, "label": label} for key, label in values.items()]


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "title": doc.template_title,
        "company": doc.company,
        "module": doc.module_key,
        "document_type": doc.document_type,
        "description": doc.description or "",
        "source_workflow": doc.source_workflow or "",
        "preset_key": doc.preset_key or "",
        "status": doc.status,
        "mapping": json.loads(doc.mapping_json or "{}"),
        "create_as_draft": bool(doc.create_as_draft),
        "auto_submit": bool(doc.auto_submit),
        "reusable": bool(doc.reusable),
        "manager_note": doc.manager_note or "",
        "modified": str(doc.modified),
    }


def _request_fields(workflow: str | None) -> dict[str, str] | None:
    """Custom request keys -> field type of a request type, or None without one."""
    if not workflow:
        return None
    from asoud_erp.api.v1.workflow_request import _fields

    definition = frappe.get_doc("ASOUD Workflow Definition", workflow)
    return {
        field["key"]: field.get("type") or "Short Text"
        for field in _fields(definition)
        if isinstance(field, dict) and field.get("key")
    }


@frappe.whitelist()
def document_template_options(company: str, workflow: str | None = None) -> dict:
    """Modules, document types, target fields and value sources for the wizard."""
    require_roles(MANAGER_ROLES)
    require_company(company)
    request_fields = [
        {"key": key, "label": label, "type": value_type}
        for key, (label, value_type) in REQUEST_BASE_FIELDS.items()
    ]
    if workflow:
        definition = frappe.get_doc("ASOUD Workflow Definition", workflow)
        if definition.company and definition.company != company:
            frappe.throw(_("Request type belongs to another company"))
        from asoud_erp.api.v1.workflow_request import _fields

        request_fields += [
            {"key": field["key"], "label": field.get("label") or field["key"],
             "type": field.get("type") or "Short Text"}
            for field in _fields(definition)
            if isinstance(field, dict) and field.get("key") not in REQUEST_BASE_FIELDS
        ]
    return success({
        "modules": [
            {"key": key, "label": module["label"], "description": module["description"],
             "types": module["types"]}
            for key, module in MODULES.items()
        ],
        "fields": TARGET_FIELDS,
        "sources": {
            "request": request_fields,
            "user": _options(USER_VALUES),
            "organization": _options(ORGANIZATION_VALUES),
            "system": _options(SYSTEM_VALUES),
        },
        "placeholders": [f"{{{{{key}}}}}" for key in PLACEHOLDERS],
    })


@frappe.whitelist()
def document_template_link_options(company: str, target_type: str, txt: str = "") -> dict:
    """Account / Cost Center / Project / Warehouse choices for a fixed value."""
    require_roles(MANAGER_ROLES)
    require_company(company)
    if target_type not in LINK_TARGETS:
        frappe.throw(_("Unsupported field type"))
    filters, has_company = _LINK_RULES[target_type]
    filters = {**filters, **({"company": company} if has_company else {})}
    or_filters = None
    if txt:
        or_filters = {"name": ["like", f"%{txt}%"]}
    title_field = {"Account": "account_name", "Cost Center": "cost_center_name",
                   "Project": "project_name", "Warehouse": "warehouse_name"}[target_type]
    rows = frappe.get_list(
        target_type,
        filters=filters,
        or_filters=or_filters,
        fields=["name", f"{title_field} as title"],
        order_by="name asc",
        limit_page_length=50,
    )
    return success([{"value": row.name, "label": row.title or row.name} for row in rows])


@frappe.whitelist()
def list_document_templates(company: str, kind: str = "custom", module: str | None = None,
                            document_type: str | None = None, search: str | None = None) -> dict:
    """Saved templates («الگوهای سفارشی») or the built-in presets («الگوهای آماده»)."""
    require_roles(MANAGER_ROLES)
    require_company(company)
    search = (search or "").strip().casefold()

    def keep(row: dict) -> bool:
        return (
            (not module or row["module"] == module)
            and (not document_type or row["document_type"] == document_type)
            and (not search or search in row["title"].casefold())
        )

    if kind == "ready":
        rows = [{**preset, "name": preset["key"], "kind": "ready"} for preset in PRESETS]
        return success([row for row in rows if keep(row)])
    if kind != "custom":
        frappe.throw(_("Invalid template list"))
    names = frappe.get_all(DOCTYPE, filters={"company": company}, pluck="name",
                           order_by="modified desc", limit_page_length=0)
    rows = [{**_serialize(frappe.get_doc(DOCTYPE, name)), "kind": "custom"} for name in names]
    return success([row for row in rows if keep(row)])


@frappe.whitelist()
def get_document_template(name: str) -> dict:
    require_roles(MANAGER_ROLES)
    doc = frappe.get_doc(DOCTYPE, name)
    require_company(doc.company)
    return success(_serialize(doc))


def _validate_links(mapping: dict, document_type: str, company: str) -> None:
    fields = {field["key"]: field for field in TARGET_FIELDS[document_type]}
    for key, entry in mapping.items():
        target_type = fields[key]["type"]
        if target_type not in LINK_TARGETS or entry["source"] != "fixed":
            continue
        filters, has_company = _LINK_RULES[target_type]
        filters = {**filters, "name": entry["value"], **({"company": company} if has_company else {})}
        if not frappe.db.exists(target_type, filters):
            frappe.throw(_("{0} {1} is not usable in this company").format(_(target_type), entry["value"]))


@frappe.whitelist(methods=["POST"])
def save_document_template(company: str, template: str | dict, name: str | None = None,
                           source_workflow: str | None = None, preset_key: str | None = None) -> dict:
    """Create or update a template; `template` follows `normalize_template`."""
    require_roles(MANAGER_ROLES)
    require_company(company)
    raw = json.loads(template) if isinstance(template, str) else template
    if not isinstance(raw, dict):
        frappe.throw(_("Template must be an object"))
    require_roles(MODULE_ROLES.get(raw.get("module"), ("System Manager",)))
    if source_workflow:
        workflow_company = frappe.db.get_value("ASOUD Workflow Definition", source_workflow, "company")
        if workflow_company and workflow_company != company:
            frappe.throw(_("Request type belongs to another company"))
    try:
        normalized = normalize_template(raw, _request_fields(source_workflow))
    except ValueError as error:
        frappe.throw(_(str(error)))
    _validate_links(normalized["mapping"], normalized["document_type"], company)
    values = {
        "template_title": normalized["title"],
        "company": company,
        "module_key": normalized["module"],
        "document_type": normalized["document_type"],
        "description": normalized["description"],
        "source_workflow": source_workflow or None,
        "preset_key": preset_key or None,
        "mapping_json": json.dumps(normalized["mapping"], ensure_ascii=False),
        "create_as_draft": int(normalized["create_as_draft"]),
        "auto_submit": int(normalized["auto_submit"]),
        "reusable": int(normalized["reusable"]),
        "manager_note": normalized["manager_note"],
    }
    if name:
        doc = frappe.get_doc(DOCTYPE, name)
        if doc.company != company:
            frappe.throw(_("Template belongs to another company"), frappe.PermissionError)
        doc.update(values)
        doc.save()
    else:
        doc = frappe.get_doc({"doctype": DOCTYPE, "status": "Active", **values}).insert()
    return success(_serialize(doc))


@frappe.whitelist(methods=["POST"])
def set_document_template_status(name: str, status: str) -> dict:
    require_roles(MANAGER_ROLES)
    if status not in {"Active", "Inactive"}:
        frappe.throw(_("Invalid template status"))
    doc = frappe.get_doc(DOCTYPE, name)
    require_company(doc.company)
    doc.status = status
    doc.save()
    return success(_serialize(doc))


def create_document(template_name: str, context: dict, company: str, *, transfer_values: bool = True,
                    remark: str = ""):
    """Insert (and optionally submit) the ERPNext document of a template.

    Runs inside a workflow "Create Document" step configured by a manager, so
    the document is inserted without the session user's DocType permissions;
    ERPNext's controller validation still applies. Raises on any failure.
    """
    template = frappe.get_doc(DOCTYPE, template_name)
    if template.status != "Active" or template.company != company:
        raise ValueError("Document template is not active for this company")
    values = resolve_values(json.loads(template.mapping_json or "{}"), context,
                            transfer_values=transfer_values)
    if remark and template.document_type == "Journal Entry":
        values["user_remark"] = render_placeholders(remark, context)
    if template.document_type == "Material Request" and not values.get("set_warehouse"):
        values["set_warehouse"] = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    doc = frappe.get_doc(build_document(template.document_type, values, company))
    doc.flags.ignore_permissions = True
    doc.insert()
    if template.auto_submit:
        doc.submit()
    return doc
