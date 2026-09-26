"""Items, stock balances and stock entries on ERPNext `Item`, `Bin` and `Stock Entry`.

Quantities come from ERPNext's `Bin` (per item and warehouse); valuation and
ledger postings stay with the Stock Entry controller.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import normalize_lines, number, paging

ROLES = ("System Manager", "Stock Manager", "Stock User", "Item Manager", "Accounts Manager",
         "Purchase Manager", "Purchase User", "Sales Manager", "Sales User")
WRITE_ROLES = ("System Manager", "Stock Manager", "Stock User", "Item Manager")
PURPOSES = {"Material Receipt", "Material Issue", "Material Transfer"}


def _company_warehouses(company: str) -> list[str]:
    return frappe.get_all("Warehouse", filters={"company": company, "is_group": 0}, pluck="name")


@frappe.whitelist()
def stock_options(company: str) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    return success({
        "warehouses": frappe.get_list("Warehouse", filters={"company": company, "is_group": 0,
                                                            "disabled": 0},
                                      fields=["name", "warehouse_name"], order_by="warehouse_name asc"),
        "item_groups": frappe.get_list("Item Group", filters={"is_group": 0}, pluck="name",
                                       order_by="name asc"),
        "uoms": frappe.get_list("UOM", filters={"enabled": 1}, pluck="name", order_by="name asc"),
        "default_warehouse": frappe.db.get_single_value("Stock Settings", "default_warehouse"),
        "purposes": sorted(PURPOSES),
    })


@frappe.whitelist()
def list_items(company: str, search: str | None = None, item_group: str | None = None,
               stock_only: int = 0, limit_start: int = 0, limit_page_length: int = 20) -> dict:
    """Enabled items with their on-hand quantity across the company's warehouses."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"disabled": 0, "has_variants": 0}
    if item_group:
        filters["item_group"] = item_group
    if cint(stock_only):
        filters["is_stock_item"] = 1
    or_filters = None
    if search:
        term = f"%{search.strip()}%"
        or_filters = {"item_code": ["like", term], "item_name": ["like", term]}
    rows = frappe.get_list("Item", filters=filters, or_filters=or_filters,
                           fields=["name as item_code", "item_name", "item_group", "stock_uom",
                                   "is_stock_item", "image"],
                           order_by="item_name asc", limit_start=start, limit_page_length=length)
    warehouses = _company_warehouses(company)
    if rows and warehouses:
        totals = {
            row.item_code: flt(row.actual_qty)
            for row in frappe.get_all("Bin", filters={"item_code": ["in", [r.item_code for r in rows]],
                                                      "warehouse": ["in", warehouses]},
                                      fields=["item_code", "sum(actual_qty) as actual_qty"],
                                      group_by="item_code")
        }
        for row in rows:
            row["actual_qty"] = totals.get(row.item_code, 0.0)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_item(company: str, item_code: str) -> dict:
    """An item with its UOMs, selling price and quantities per company warehouse."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    item = erp_documents.load("Item", item_code)
    price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    price = frappe.db.get_value("Item Price", {"item_code": item.name, "price_list": price_list,
                                               "uom": item.stock_uom}, "price_list_rate")
    bins = frappe.get_all("Bin", filters={"item_code": item.name,
                                          "warehouse": ["in", _company_warehouses(company) or [""]]},
                          fields=["warehouse", "actual_qty", "projected_qty", "reserved_qty",
                                  "ordered_qty", "valuation_rate"])
    return success({
        "item_code": item.name, "item_name": item.item_name, "item_group": item.item_group,
        "description": item.description or "", "stock_uom": item.stock_uom,
        "is_stock_item": cint(item.is_stock_item), "disabled": cint(item.disabled), "image": item.image or "",
        "uoms": [{"uom": row.uom, "conversion_factor": flt(row.conversion_factor)} for row in item.uoms],
        "selling_price_list": price_list, "selling_rate": flt(price) if price is not None else None,
        "last_purchase_rate": flt(item.last_purchase_rate),
        "warehouses": bins,
        "actual_qty": flt(sum(flt(row.actual_qty) for row in bins)),
    })


@frappe.whitelist(methods=["POST"])
def save_item(item_name: str, item_group: str, stock_uom: str, item_code: str | None = None,
              is_stock_item: int = 1, description: str | None = None, standard_rate=None,
              disabled: int = 0) -> dict:
    """Creates an item, or updates the editable fields of an existing one.

    ``standard_rate`` on creation lets ERPNext create the selling Item Price.
    """
    erp_documents.require_roles(WRITE_ROLES)
    values = {"item_name": (item_name or "").strip(), "item_group": item_group,
              "is_stock_item": cint(is_stock_item), "description": (description or "").strip() or None,
              "disabled": cint(disabled)}
    if not values["item_name"]:
        frappe.throw(_("Item name is required"))
    if item_code and frappe.db.exists("Item", item_code):
        doc = erp_documents.load("Item", item_code, "write")
        doc.update(values)
        doc.save()
    else:
        doc = frappe.new_doc("Item")
        doc.update({**values, "item_code": (item_code or "").strip() or values["item_name"],
                    "stock_uom": stock_uom})
        if standard_rate not in (None, ""):
            try:
                doc.standard_rate = number(standard_rate, "Rate", minimum=0)
            except ValueError as error:
                frappe.throw(_(str(error)))
        doc.insert()
    return success({"item_code": doc.name, "item_name": doc.item_name, "item_group": doc.item_group,
                    "stock_uom": doc.stock_uom, "is_stock_item": cint(doc.is_stock_item),
                    "disabled": cint(doc.disabled)})


@frappe.whitelist()
def stock_balance(company: str, warehouse: str | None = None, item_code: str | None = None,
                  limit_start: int = 0, limit_page_length: int = 50) -> dict:
    """Quantities per item and warehouse from ERPNext `Bin`."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=200)
    warehouses = _company_warehouses(company)
    if warehouse:
        if warehouse not in warehouses:
            frappe.throw(_("Warehouse does not belong to this company"))
        warehouses = [warehouse]
    filters: dict = {"warehouse": ["in", warehouses or [""]]}
    if item_code:
        filters["item_code"] = item_code
    rows = frappe.get_all("Bin", filters=filters,
                          fields=["item_code", "warehouse", "actual_qty", "projected_qty",
                                  "reserved_qty", "ordered_qty", "valuation_rate", "stock_value"],
                          order_by="item_code asc", limit_start=start, limit_page_length=length)
    names = dict(frappe.get_all("Item", filters={"name": ["in", [r.item_code for r in rows] or [""]]},
                                fields=["name", "item_name"], as_list=True))
    for row in rows:
        row["item_name"] = names.get(row.item_code, "")
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


def serialize_stock_entry(doc) -> dict:
    return {
        "name": doc.name, "company": doc.company, "purpose": doc.purpose,
        "posting_date": str(doc.posting_date), "remarks": doc.remarks or "",
        "total_amount": flt(doc.total_amount), "docstatus": doc.docstatus,
        "items": [
            {"item_code": row.item_code, "item_name": row.item_name, "qty": flt(row.qty), "uom": row.uom,
             "s_warehouse": row.s_warehouse or "", "t_warehouse": row.t_warehouse or "",
             "basic_rate": flt(row.basic_rate), "amount": flt(row.amount)}
            for row in doc.items
        ],
    }


@frappe.whitelist(methods=["POST"])
def create_stock_entry(company: str, purpose: str, items, posting_date: str | None = None,
                       remarks: str | None = None, submit: int = 0) -> dict:
    """Receipt, issue or transfer. Receipts need ``t_warehouse``, issues ``s_warehouse``,
    transfers both; a receipt line may carry ``rate`` as its valuation rate."""
    erp_documents.require_roles(WRITE_ROLES)
    require_company(company)
    if purpose not in PURPOSES:
        frappe.throw(_("Invalid stock entry purpose"))
    try:
        lines = normalize_lines(items, rates=True, target_warehouses=True)
    except ValueError as error:
        frappe.throw(_(str(error)))
    need_source = purpose in {"Material Issue", "Material Transfer"}
    need_target = purpose in {"Material Receipt", "Material Transfer"}
    doc = frappe.new_doc("Stock Entry")
    doc.update({"company": company, "stock_entry_type": purpose, "purpose": purpose,
                "posting_date": getdate(posting_date or nowdate()), "set_posting_time": 1,
                "remarks": (remarks or "").strip() or None})
    for line in lines:
        if need_source != bool(line.get("s_warehouse")) or need_target != bool(line.get("t_warehouse")):
            frappe.throw(_("Warehouses do not match the stock entry purpose"))
        row = {key: line[key] for key in ("item_code", "qty", "uom", "s_warehouse", "t_warehouse",
                                           "description") if key in line}
        if "rate" in line and purpose == "Material Receipt":
            row["basic_rate"] = line["rate"]
        doc.append("items", row)
    doc.set_stock_entry_type()
    erp_documents.insert(doc, submit_now=cint(submit))
    return success(serialize_stock_entry(doc))


@frappe.whitelist()
def list_stock_entries(company: str, purpose: str | None = None, from_date: str | None = None,
                       to_date: str | None = None, limit_start: int = 0, limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"company": company}
    if purpose:
        filters["purpose"] = purpose
    if period := erp_documents.date_range(from_date, to_date):
        filters["posting_date"] = period
    rows = frappe.get_list("Stock Entry", filters=filters,
                           fields=["name", "purpose", "posting_date", "total_amount", "docstatus"],
                           order_by="posting_date desc, creation desc",
                           limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_stock_entry(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_stock_entry(erp_documents.load("Stock Entry", name)))


@frappe.whitelist(methods=["POST"])
def submit_stock_entry(name: str) -> dict:
    erp_documents.require_roles(WRITE_ROLES)
    return success(serialize_stock_entry(erp_documents.submit("Stock Entry", name)))


@frappe.whitelist(methods=["POST"])
def cancel_stock_entry(name: str) -> dict:
    erp_documents.require_roles(WRITE_ROLES)
    return success(serialize_stock_entry(erp_documents.cancel("Stock Entry", name)))
