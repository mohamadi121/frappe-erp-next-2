"""Purchase orders, receipts and invoices on ERPNext buying documents.

Documents are created directly or mapped with ERPNext's own mappers
(Material Request → Purchase Order → Purchase Receipt / Purchase Invoice), so
quantities already ordered, received and billed are tracked by ERPNext.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import normalize_lines, paging

ROLES = ("System Manager", "Purchase Manager", "Purchase User", "Accounts Manager", "Accounts User")
DOCTYPES = {"Purchase Order", "Purchase Receipt", "Purchase Invoice"}


def serialize_purchase(doc) -> dict:
    data = {
        "doctype": doc.doctype, "name": doc.name, "company": doc.company, "supplier": doc.supplier,
        "supplier_name": doc.supplier_name, "currency": doc.currency,
        "net_total": flt(doc.net_total), "total_taxes_and_charges": flt(doc.total_taxes_and_charges),
        "grand_total": flt(doc.grand_total), "status": doc.status, "docstatus": doc.docstatus,
        "taxes_and_charges": doc.taxes_and_charges or "",
        "items": [
            {"item_code": row.item_code, "item_name": row.item_name, "qty": flt(row.qty), "uom": row.uom,
             "rate": flt(row.rate), "amount": flt(row.amount), "warehouse": row.get("warehouse") or "",
             "material_request": row.get("material_request") or "",
             "purchase_order": row.get("purchase_order") or ""}
            for row in doc.items
        ],
    }
    if doc.doctype == "Purchase Order":
        data.update({"transaction_date": str(doc.transaction_date), "schedule_date": str(doc.schedule_date),
                     "per_received": flt(doc.per_received), "per_billed": flt(doc.per_billed)})
    else:
        data["posting_date"] = str(doc.posting_date)
    if doc.doctype == "Purchase Invoice":
        data.update({"bill_no": doc.bill_no or "", "bill_date": str(doc.bill_date or ""),
                     "due_date": str(doc.due_date or ""), "outstanding_amount": flt(doc.outstanding_amount)})
    return data


def _finish(doc, submit):
    doc.set_missing_values()
    doc.calculate_taxes_and_totals()
    erp_documents.insert(doc, submit_now=cint(submit))
    return success(serialize_purchase(doc))


def _lines(items):
    try:
        return normalize_lines(items, rates=True, warehouses=True)
    except ValueError as error:
        frappe.throw(_(str(error)))


@frappe.whitelist()
def buying_options(company: str) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    return success({
        "currency": frappe.get_cached_value("Company", company, "default_currency"),
        "buying_price_list": frappe.db.get_single_value("Buying Settings", "buying_price_list"),
        "suppliers": frappe.get_list("Supplier", filters={"disabled": 0},
                                     fields=["name", "supplier_name", "supplier_group"],
                                     order_by="supplier_name asc", limit_page_length=500),
        "tax_templates": frappe.get_list("Purchase Taxes and Charges Template",
                                         filters={"company": company, "disabled": 0},
                                         fields=["name", "title", "is_default"], order_by="title asc"),
        "warehouses": frappe.get_list("Warehouse", filters={"company": company, "is_group": 0,
                                                            "disabled": 0},
                                      fields=["name", "warehouse_name"], order_by="warehouse_name asc"),
    })


@frappe.whitelist(methods=["POST"])
def create_purchase_order(company: str, supplier: str, items, schedule_date: str,
                          transaction_date: str | None = None, taxes_and_charges: str | None = None,
                          submit: int = 0) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    lines = _lines(items)
    required_by = getdate(schedule_date)
    doc = frappe.new_doc("Purchase Order")
    doc.update({"company": company, "supplier": supplier, "schedule_date": required_by,
                "transaction_date": getdate(transaction_date or nowdate())})
    if taxes_and_charges:
        doc.taxes_and_charges = taxes_and_charges
    for line in lines:
        doc.append("items", {**line, "schedule_date": required_by})
    doc.set_missing_values()
    doc.set_taxes()
    return _finish(doc, submit)


@frappe.whitelist(methods=["POST"])
def create_purchase_order_from_request(material_request: str, supplier: str, submit: int = 0) -> dict:
    """Orders the not-yet-ordered quantities of a submitted purchase Material Request."""
    erp_documents.require_roles(ROLES)
    from erpnext.stock.doctype.material_request.material_request import make_purchase_order

    source = erp_documents.load("Material Request", material_request)
    if source.docstatus != 1 or source.material_request_type != "Purchase":
        frappe.throw(_("Only a submitted purchase request can be ordered"))
    doc = make_purchase_order(source.name)
    doc.supplier = supplier
    return _finish(doc, submit)


@frappe.whitelist(methods=["POST"])
def create_purchase_receipt_from_order(purchase_order: str, submit: int = 0) -> dict:
    """Receives the not-yet-received quantities of a submitted purchase order."""
    erp_documents.require_roles(ROLES)
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

    source = erp_documents.load("Purchase Order", purchase_order)
    if source.docstatus != 1:
        frappe.throw(_("Only a submitted purchase order can be received"))
    return _finish(make_purchase_receipt(source.name), submit)


@frappe.whitelist(methods=["POST"])
def create_purchase_invoice(company: str, supplier: str, items, posting_date: str | None = None,
                            bill_no: str | None = None, bill_date: str | None = None,
                            taxes_and_charges: str | None = None, update_stock: int = 0,
                            submit: int = 0) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    lines = _lines(items)
    doc = frappe.new_doc("Purchase Invoice")
    doc.update({"company": company, "supplier": supplier, "posting_date": getdate(posting_date or nowdate()),
                "set_posting_time": 1, "bill_no": (bill_no or "").strip() or None,
                "bill_date": getdate(bill_date) if bill_date else None, "update_stock": cint(update_stock)})
    if taxes_and_charges:
        doc.taxes_and_charges = taxes_and_charges
    for line in lines:
        doc.append("items", line)
    doc.set_missing_values()
    doc.set_taxes()
    return _finish(doc, submit)


@frappe.whitelist(methods=["POST"])
def create_purchase_invoice_from_order(purchase_order: str, bill_no: str | None = None,
                                       bill_date: str | None = None, submit: int = 0) -> dict:
    """Bills the not-yet-billed amounts of a submitted purchase order."""
    erp_documents.require_roles(ROLES)
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

    source = erp_documents.load("Purchase Order", purchase_order)
    if source.docstatus != 1:
        frappe.throw(_("Only a submitted purchase order can be billed"))
    doc = make_purchase_invoice(source.name)
    doc.bill_no = (bill_no or "").strip() or None
    doc.bill_date = getdate(bill_date) if bill_date else None
    return _finish(doc, submit)


def _doctype(doctype: str) -> str:
    if doctype not in DOCTYPES:
        frappe.throw(_("Invalid buying document type"))
    return doctype


@frappe.whitelist()
def list_purchase_documents(company: str, doctype: str, supplier: str | None = None,
                            status: str | None = None, from_date: str | None = None,
                            to_date: str | None = None, limit_start: int = 0,
                            limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    doctype = _doctype(doctype)
    start, length = paging(limit_start, limit_page_length)
    date_field = "transaction_date" if doctype == "Purchase Order" else "posting_date"
    filters: dict = {"company": company}
    if supplier:
        filters["supplier"] = supplier
    if status:
        filters["status"] = status
    if period := erp_documents.date_range(from_date, to_date):
        filters[date_field] = period
    rows = frappe.get_list(doctype, filters=filters,
                           fields=["name", "supplier", "supplier_name", f"{date_field} as date",
                                   "grand_total", "currency", "status", "docstatus"],
                           order_by=f"{date_field} desc, creation desc",
                           limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_purchase_document(doctype: str, name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_purchase(erp_documents.load(_doctype(doctype), name)))


@frappe.whitelist(methods=["POST"])
def submit_purchase_document(doctype: str, name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_purchase(erp_documents.submit(_doctype(doctype), name)))


@frappe.whitelist(methods=["POST"])
def cancel_purchase_document(doctype: str, name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_purchase(erp_documents.cancel(_doctype(doctype), name)))
