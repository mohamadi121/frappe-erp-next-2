"""Choices for request form fields: masters behind System Select, User, Department and Item.

The pure helpers (source map, delivery location values, leave type labels) have no
frappe import, so form normalization and the unit tests can use them. The query
functions import frappe lazily and read through the query builder; the endpoint
`request_field_options` calls `search` after `require_company`.
"""

from __future__ import annotations

from typing import Any

MAX_PAGE_LENGTH = 50
DEFAULT_PAGE_LENGTH = 20

# System Select `source` -> `request_field_options.field_type`.
SOURCE_FIELD_TYPES = {
    "cost_center": "Cost Center",
    "project": "Project",
    "warehouse": "Warehouse",
    "branch": "Branch",
    "supplier": "Supplier",
    "leave_type": "Leave Type",
    "delivery_location": "Delivery Location",
}
FIELD_TYPE_SOURCES = {value: key for key, value in SOURCE_FIELD_TYPES.items()}
BASE_FIELD_TYPES = ("User", "Department", "Item", "UOM")
FIELD_TYPES = BASE_FIELD_TYPES + tuple(SOURCE_FIELD_TYPES.values())
ITEM_SCOPES = ("purchase", "all")
DELIVERY_KINDS = ("warehouse", "branch", "department")
LEAVE_CATEGORY_LABELS = {"annual": "سالانه", "sick": "استعلاجی", "unpaid": "بدون حقوق", "other": "سایر"}

ANNUAL_LEAVE_WORDS = ("casual", "privilege", "earned", "سالانه", "استحقاقی")
SICK_LEAVE_WORDS = ("sick", "استعلاجی")

# source -> (doctype, label field, company scoped, fixed filters)
_SIMPLE_SOURCES = {
    "cost_center": ("Cost Center", "cost_center_name", True, {"is_group": 0, "disabled": 0}),
    "project": ("Project", "project_name", True, {"status": "Open"}),
    "warehouse": ("Warehouse", "warehouse_name", True, {"is_group": 0, "disabled": 0}),
    "branch": ("Branch", "name", False, {}),
    "supplier": ("Supplier", "supplier_name", False, {"disabled": 0}),
}
# kind -> (doctype, label field, company scoped, fixed filters)
_DELIVERY_SOURCES = {
    "warehouse": ("Warehouse", "warehouse_name", True, {"is_group": 0, "disabled": 0}),
    "branch": ("Branch", "name", False, {}),
    "department": ("Department", "department_name", True, {"disabled": 0}),
}


def parse_delivery_location(value: Any) -> tuple[str, str]:
    """Splits a `<kind>:<name>` delivery location; kind is warehouse, branch or department."""
    if not isinstance(value, str) or ":" not in value:
        raise ValueError("Invalid delivery location")
    kind, name = value.split(":", 1)
    kind, name = kind.strip(), name.strip()
    if kind not in DELIVERY_KINDS or not name or len(name) > 140:
        raise ValueError("Invalid delivery location")
    return kind, name


def delivery_location_value(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def leave_type_label(category: str, leave_type: str, same_category_count: int) -> str:
    """Persian category label; with several leave types in a category the type name is added."""
    label = LEAVE_CATEGORY_LABELS.get(category, category)
    return label if same_category_count <= 1 else f"{label} — {leave_type}"


def leave_category_for(name: str, is_lwp: bool) -> str:
    """Category of a Leave Type without one: `unpaid` for leave without pay, then by name, else `other`."""
    if is_lwp:
        return "unpaid"
    lowered = (name or "").casefold()
    if any(word in lowered for word in ANNUAL_LEAVE_WORDS):
        return "annual"
    if any(word in lowered for word in SICK_LEAVE_WORDS):
        return "sick"
    return "other"


def page_length(value: Any) -> int:
    """Requested page size, 1..MAX_PAGE_LENGTH (default 20)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_LENGTH
    return max(1, min(number, MAX_PAGE_LENGTH))


def page_start(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------ queries (need frappe)


def search(company: str, field_type: str, txt: str = "", item_code: str | None = None,
           scope: str | None = None, limit_start: Any = 0,
           limit_page_length: Any = DEFAULT_PAGE_LENGTH) -> list[dict]:
    """Rows `{value, label, ...}` for a field type. The caller has checked company access."""
    import frappe
    from frappe import _

    if field_type not in FIELD_TYPES:
        frappe.throw(_("Unsupported field type"))
    start, length = page_start(limit_start), page_length(limit_page_length)
    term = f"%{(txt or '').strip()}%"
    if field_type == "User":
        return _users(company, term, start, length)
    if field_type == "Department":
        return _departments(company, term, start, length)
    if field_type == "Item":
        return _items(term, scope, start, length)
    if field_type == "UOM":
        return _uoms(item_code)
    source = FIELD_TYPE_SOURCES[field_type]
    if source == "leave_type":
        return leave_type_rows(term, start, length)
    if source == "delivery_location":
        return _delivery_locations(company, term, start, length)
    return _simple(source, company, term, start, length)


def _users(company, term, start, length):
    import frappe

    return frappe.get_all(
        "Employee",
        filters={"company": company, "status": "Active", "user_id": ["is", "set"]},
        or_filters={"employee_name": ["like", term], "user_id": ["like", term]},
        fields=["user_id as value", "employee_name as label", "name as employee", "department", "branch"],
        order_by="employee_name asc", limit_start=start, limit_page_length=length)


def _departments(company, term, start, length):
    import frappe

    return frappe.get_all(
        "Department",
        filters={"company": company, "disabled": 0, "department_name": ["like", term]},
        fields=["name as value", "department_name as label"],
        order_by="department_name asc", limit_start=start, limit_page_length=length)


def _items(term, scope, start, length):
    import frappe
    from frappe import _

    if scope not in (None, "", *ITEM_SCOPES):
        frappe.throw(_("Unsupported item scope"))
    filters = {"disabled": 0, "has_variants": 0}
    if scope == "purchase":
        filters["is_purchase_item"] = 1
    return frappe.get_all(
        "Item", filters=filters,
        or_filters={"item_code": ["like", term], "item_name": ["like", term]},
        fields=["name as value", "item_name as label", "item_code", "item_name", "stock_uom",
                "is_stock_item", "item_group"],
        order_by="item_name asc", limit_start=start, limit_page_length=length)


def _uoms(item_code):
    import frappe
    from frappe import _

    from asoud_erp.services.request_link_values import item_uoms

    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Select an item first"))
    return [{"value": row["uom"], "label": row["uom"], "conversion_factor": row["conversion_factor"]}
            for row in item_uoms(item_code)]


def _master_rows(doctype, label_field, filters, term, order_limit):
    import frappe

    rows = frappe.get_all(
        doctype, filters=filters, or_filters={"name": ["like", term], label_field: ["like", term]},
        fields=["name", f"{label_field} as label"], order_by=f"{label_field} asc", **order_limit)
    return [{"name": row["name"], "label": row["label"] or row["name"]} for row in rows]


def _simple(source, company, term, start, length):
    doctype, label_field, scoped, fixed = _SIMPLE_SOURCES[source]
    filters = {**fixed, **({"company": company} if scoped else {})}
    rows = _master_rows(doctype, label_field, filters, term,
                        {"limit_start": start, "limit_page_length": length})
    return [{"value": row["name"], "label": row["label"]} for row in rows]


def leave_type_rows(term: str = "%", start: int = 0, length: int = MAX_PAGE_LENGTH) -> list[dict]:
    """Leave types that have an ASOUD category, with the category label rules applied."""
    import frappe

    everything = frappe.get_all(
        "Leave Type", filters={"asoud_leave_category": ["in", list(LEAVE_CATEGORY_LABELS)]},
        fields=["name", "asoud_leave_category as category", "is_lwp"], order_by="name asc",
        limit_page_length=0)
    per_category: dict[str, int] = {}
    for row in everything:
        per_category[row["category"]] = per_category.get(row["category"], 0) + 1
    needle = term.strip("%").casefold()
    rows = []
    for row in everything:
        label = leave_type_label(row["category"], row["name"], per_category[row["category"]])
        if needle and needle not in label.casefold() and needle not in row["name"].casefold():
            continue
        rows.append({"value": row["name"], "label": label, "category": row["category"],
                     "is_lwp": 1 if row["is_lwp"] else 0})
    return rows[start:start + length]


def _delivery_locations(company, term, start, length):
    window = start + length
    rows: list[dict] = []
    for kind, (doctype, label_field, scoped, fixed) in _DELIVERY_SOURCES.items():
        filters = {**fixed, **({"company": company} if scoped else {})}
        found = _master_rows(doctype, label_field, filters, term, {"limit_page_length": window})
        rows.extend({"value": delivery_location_value(kind, row["name"]), "label": row["label"],
                     "kind": kind} for row in found)
    return rows[start:window]


def validate_source_value(source: str, value: str, company: str | None) -> None:
    """A System Select value must be an enabled record of the company (where scoped)."""
    import frappe
    from frappe import _

    if source == "delivery_location":
        kind, name = parse_delivery_location(value)
        doctype, _label, scoped, fixed = _DELIVERY_SOURCES[kind]
        filters = {**fixed, "name": name, **({"company": company} if scoped and company else {})}
        if not frappe.db.exists(doctype, filters):
            frappe.throw(_("Selected delivery location is not available for this company"))
        return
    if source == "leave_type":
        if not frappe.db.get_value("Leave Type", value, "asoud_leave_category"):
            frappe.throw(_("Selected leave type is not available"))
        return
    doctype, _label, scoped, fixed = _SIMPLE_SOURCES[source]
    filters = {**fixed, "name": value, **({"company": company} if scoped and company else {})}
    if not frappe.db.exists(doctype, filters):
        frappe.throw(_("Selected {0} is not available for this company").format(_(doctype)))
