"""Form values that name ERPNext records: User, Department and Item rows.

`normalize_form_response` checks their shape; this module resolves them against
the standard masters. A "User" value must be the ERPNext user of an active
Employee of the request company (Employee is authoritative for HR identity).
Item rows reuse ERPNext's end-of-life check and UOM conversion factor.
"""

import frappe
from frappe import _
from frappe.utils import flt


def workflow_company(instance_name: str) -> str | None:
    """The company of the document a workflow instance runs on."""
    instance = frappe.db.get_value(
        "ASOUD Workflow Instance",
        instance_name,
        ["workflow_definition", "reference_doctype", "reference_name"],
        as_dict=True,
    )
    if not instance:
        return None
    if instance.reference_doctype and instance.reference_name:
        if frappe.get_meta(instance.reference_doctype).has_field("company"):
            company = frappe.db.get_value(instance.reference_doctype, instance.reference_name, "company")
            if company:
                return company
    return frappe.db.get_value("ASOUD Workflow Definition", instance.workflow_definition, "company")


def validate_link_values(fields: list, values: dict, company: str | None) -> dict:
    """Checks User/Department/Item Table values in place and enriches item rows."""
    for field in fields:
        key = field.get("key")
        value = values.get(key)
        if value in (None, "", []):
            continue
        field_type = field.get("type")
        if field_type == "User":
            _validate_user(value, company)
        elif field_type == "Department":
            _validate_department(value, company)
        elif field_type == "Item Table":
            values[key] = [_item_row(row) for row in value]
    return values


def _validate_user(user: str, company: str | None) -> None:
    filters = {"user_id": user, "status": "Active"}
    if company:
        filters["company"] = company
    enabled = frappe.db.get_value("User", user, "enabled")
    if not enabled or not frappe.db.exists("Employee", filters):
        frappe.throw(_("Selected user is not an active employee of this company"))


def _validate_department(department: str, company: str | None) -> None:
    row = frappe.db.get_value("Department", department, ["company", "disabled"], as_dict=True)
    if not row or row.disabled or (company and row.company != company):
        frappe.throw(_("Selected department does not belong to this company"))


def item_uoms(item_code: str) -> list[dict]:
    """Stock UOM first, then the item's (or its template's) UOM conversions."""
    from erpnext.stock.get_item_details import get_conversion_factor

    item = frappe.db.get_value("Item", item_code, ["stock_uom", "variant_of"], as_dict=True)
    if not item:
        return []
    parents = [item_code] + ([item.variant_of] if item.variant_of else [])
    uoms = frappe.get_all(
        "UOM Conversion Detail",
        filters={"parenttype": "Item", "parent": ["in", parents]},
        pluck="uom",
    )
    result = []
    for uom in dict.fromkeys([item.stock_uom, *uoms]):
        factor = get_conversion_factor(item_code, uom)["conversion_factor"]
        result.append({"uom": uom, "conversion_factor": flt(factor)})
    return result


def _item_row(row: dict) -> dict:
    from erpnext.stock.doctype.item.item import validate_end_of_life

    item_code = row["item_code"]
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "stock_uom", "has_variants", "disabled", "end_of_life"],
        as_dict=True,
    )
    if not item:
        frappe.throw(_("Item {0} does not exist").format(item_code))
    if item.has_variants:
        frappe.throw(_("Item {0} is a template; select one of its variants").format(item_code))
    validate_end_of_life(item_code, item.end_of_life, item.disabled)
    uom = row.get("uom") or item.stock_uom
    factor = next((u["conversion_factor"] for u in item_uoms(item_code) if u["uom"] == uom), None)
    if factor is None:
        frappe.throw(_("UOM {0} is not defined for item {1}").format(uom, item_code))
    return {
        "item_code": item_code,
        "item_name": item.item_name,
        "qty": row["qty"],
        "uom": uom,
        "stock_uom": item.stock_uom,
        "conversion_factor": factor,
        "stock_qty": flt(row["qty"] * factor, 6),
        "description": row.get("description") or "",
    }
