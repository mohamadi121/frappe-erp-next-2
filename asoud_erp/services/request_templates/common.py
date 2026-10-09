"""Helpers shared by the purchase, supply and leave template specs."""

import frappe
from frappe.utils import getdate, nowdate

from asoud_erp.services.native_payloads import parse_delivery_location
from asoud_erp.services.request_status import priority_label
from asoud_erp.services.request_templates.base import throw_error

SUPPLY_METHOD_LABELS = {"Warehouse": "از انبار", "Purchase": "خرید", "Transfer": "انتقال",
                        "Contract": "قرارداد", "Unspecified": "نامشخص"}


def employee_row(company: str, user: str):
    return frappe.db.get_value(
        "Employee", {"user_id": user, "company": company, "status": "Active"},
        ["name", "employee_name", "department", "branch"], as_dict=True)


def available_for(company: str, user: str) -> bool:
    """Templates are offered to users with an active Employee in the company (CONTRACT 3.1)."""
    return bool(frappe.db.exists("Employee", {"user_id": user, "company": company, "status": "Active"}))


def resolve_defaults(form_fields: list[dict], company: str, user: str) -> dict:
    """``{field_key: {"value", "label"}}`` for the ``default_source`` fields (CONTRACT 3.7)."""
    employee = employee_row(company, user)
    result = {}
    for field in form_fields:
        source = field.get("default_source")
        if source == "today":
            result[field["key"]] = {"value": nowdate(), "label": nowdate()}
        elif source == "session_user":
            result[field["key"]] = {"value": user, "label": employee.employee_name if employee else user}
        elif employee and source == "employee_department" and employee.department:
            label = frappe.db.get_value("Department", employee.department, "department_name")
            result[field["key"]] = {"value": employee.department, "label": label or employee.department}
        elif employee and source == "employee_branch" and employee.branch:
            result[field["key"]] = {"value": employee.branch, "label": employee.branch}
    return result


def check_requester(ctx) -> None:
    """The ``requester`` field is not editable: it is always the signed-in user (CONTRACT 3.6)."""
    if ctx.values.get("requester") != ctx.user:
        throw_error("REQUESTER_MISMATCH")


def check_needed_date(ctx) -> None:
    """``needed_date`` is today or later when created, or when changed on update (CONTRACT 3.4)."""
    value = ctx.values.get("needed_date")
    if not value:
        return
    if ctx.is_update and (ctx.previous or {}).get("needed_date") == value:
        return
    if getdate(value) < getdate(nowdate()):
        throw_error("DATE_IN_PAST")


def memo(key: tuple, compute):
    """Per-request memo: list cards would otherwise query the same record once per row."""
    cache = getattr(frappe.local, "asoud_template_memo", None)
    if cache is None:
        cache = frappe.local.asoud_template_memo = {}
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def cached_value(doctype: str, name: str | None, field: str):
    if not name:
        return None
    return memo((doctype, name, field), lambda: frappe.db.get_value(doctype, name, field))


def label_of(doctype: str, name: str | None, field: str) -> str:
    """A record's display label, falling back to its name."""
    return cached_value(doctype, name, field) or name or ""


def batched_label(request_row: dict | None, group: str, key: str | None, doctype: str, field: str) -> str:
    """Label from the list endpoint's batched lookups (``request_row["_labels"]``), else one memoized query."""
    labels = ((request_row or {}).get("_labels") or {}).get(group) or {}
    return labels.get(key) or label_of(doctype, key, field)


def base_summary(values: dict, request_row: dict | None = None) -> dict:
    """Summary keys shared by purchase and supply (CONTRACT 4.6)."""
    org_unit = values.get("org_unit") or ""
    project = values.get("project") or ""
    return {
        "org_unit": org_unit,
        "org_unit_label": batched_label(request_row, "department", org_unit, "Department", "department_name"),
        "project": project,
        "project_label": batched_label(request_row, "project", project, "Project", "project_name"),
        "priority": values.get("priority") or "Normal",
        "priority_label": priority_label(values.get("priority") or "Normal"),
        "needed_date": values.get("needed_date") or "",
    }


def item_rows(values: dict) -> list[dict]:
    return [row for row in values.get("items") or [] if isinstance(row, dict)]


def stock_flag(row: dict) -> int:
    """``is_stock_item`` of an item row; looked up when the engine did not enrich the row."""
    if row.get("is_stock_item") is not None:
        return int(row["is_stock_item"])
    return int(frappe.db.get_value("Item", row.get("item_code"), "is_stock_item") or 0)



def cost_center_required(company: str) -> bool:
    """``Company.asoud_request_cost_center_required`` (CONTRACT 2.2, 3.4)."""
    return bool(frappe.db.get_value("Company", company, "asoud_request_cost_center_required"))


def check_delivery(company: str, value) -> tuple[str, str]:
    """Parses ``"<kind>:<name>"`` and checks the record exists and belongs to the company."""
    message = "محل تحویل نامعتبر است."
    parsed = parse_delivery_location(value)
    if not parsed:
        frappe.throw(message, exc=frappe.ValidationError)
    kind, name = parsed
    if kind == "branch":
        valid = bool(frappe.db.exists("Branch", name))
    else:
        doctype = "Warehouse" if kind == "warehouse" else "Department"
        row = frappe.db.get_value(doctype, name, ["company", "disabled"], as_dict=True)
        valid = bool(row) and row.company == company and not row.disabled
    if not valid:
        frappe.throw(message, exc=frappe.ValidationError)
    return kind, name
