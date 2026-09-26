"""Quotations, sales orders and deliveries on ERPNext selling documents.

Documents move forward with ERPNext's own mappers, so ordered, delivered and
billed quantities are tracked by ERPNext:

    Quotation ─make_sales_order─▶ Sales Order ─make_delivery_note─▶ Delivery Note
                                              └─make_sales_invoice─▶ Sales Invoice
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.api.v1.selling import ROLES, serialize_invoice
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import normalize_lines, paging

DOCTYPES = {"Quotation": "transaction_date", "Sales Order": "transaction_date", "Delivery Note": "posting_date"}


def serialize_sales_document(doc) -> dict:
    party = doc.party_name if doc.doctype == "Quotation" else doc.customer
    data = {
        "doctype": doc.doctype, "name": doc.name, "company": doc.company, "customer": party,
        "customer_name": doc.customer_name, "currency": doc.currency,
        "date": str(doc.get(DOCTYPES[doc.doctype])),
        "net_total": flt(doc.net_total), "total_taxes_and_charges": flt(doc.total_taxes_and_charges),
        "grand_total": flt(doc.grand_total), "status": doc.status, "docstatus": doc.docstatus,
        "items": [
            {"item_code": row.item_code, "item_name": row.item_name, "qty": flt(row.qty), "uom": row.uom,
             "rate": flt(row.rate), "amount": flt(row.amount), "warehouse": row.get("warehouse") or "",
             "delivered_qty": flt(row.get("delivered_qty")), "prevdoc_docname": row.get("prevdoc_docname") or "",
             "against_sales_order": row.get("against_sales_order") or ""}
            for row in doc.items
        ],
    }
    if doc.doctype == "Quotation":
        data["valid_till"] = str(doc.valid_till or "")
    if doc.doctype == "Sales Order":
        data.update({"delivery_date": str(doc.delivery_date or ""), "per_delivered": flt(doc.per_delivered),
                     "per_billed": flt(doc.per_billed)})
    return data


def _lines(items):
    try:
        return normalize_lines(items, rates=True, warehouses=True)
    except ValueError as error:
        frappe.throw(_(str(error)))


def _finish(doc, submit, serialize=serialize_sales_document):
    doc.set_missing_values()
    doc.calculate_taxes_and_totals()
    erp_documents.insert(doc, submit_now=cint(submit))
    return success(serialize(doc))


def _new(doctype: str, company: str, values: dict, items, taxes_and_charges: str | None, extra_line=None):
    doc = frappe.new_doc(doctype)
    doc.update({"company": company, **values})
    if taxes_and_charges:
        doc.taxes_and_charges = taxes_and_charges
    for line in _lines(items):
        doc.append("items", {**line, **(extra_line or {})})
    doc.set_missing_values()
    doc.set_taxes()
    return doc


@frappe.whitelist(methods=["POST"])
def create_quotation(company: str, customer: str, items, transaction_date: str | None = None,
                     valid_till: str | None = None, taxes_and_charges: str | None = None,
                     submit: int = 0) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    doc = _new("Quotation", company, {
        "quotation_to": "Customer", "party_name": customer,
        "transaction_date": getdate(transaction_date or nowdate()),
        "valid_till": getdate(valid_till) if valid_till else None,
    }, items, taxes_and_charges)
    return _finish(doc, submit)


@frappe.whitelist(methods=["POST"])
def create_sales_order(company: str, customer: str, items, delivery_date: str,
                       transaction_date: str | None = None, taxes_and_charges: str | None = None,
                       submit: int = 0) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    deliver_by = getdate(delivery_date)
    doc = _new("Sales Order", company, {
        "customer": customer, "delivery_date": deliver_by,
        "transaction_date": getdate(transaction_date or nowdate()),
    }, items, taxes_and_charges, extra_line={"delivery_date": deliver_by})
    return _finish(doc, submit)


def _submitted_source(doctype: str, name: str):
    source = erp_documents.load(doctype, name)
    if source.docstatus != 1:
        frappe.throw(_("Only a submitted {0} can be continued").format(_(doctype)))
    return source


@frappe.whitelist(methods=["POST"])
def create_sales_order_from_quotation(quotation: str, delivery_date: str, submit: int = 0) -> dict:
    """Orders a submitted quotation (ERPNext `make_sales_order`)."""
    erp_documents.require_roles(ROLES)
    from erpnext.selling.doctype.quotation.quotation import make_sales_order

    source = _submitted_source("Quotation", quotation)
    doc = make_sales_order(source.name)
    doc.delivery_date = getdate(delivery_date)
    for row in doc.items:
        row.delivery_date = doc.delivery_date
    return _finish(doc, submit)


@frappe.whitelist(methods=["POST"])
def create_delivery_note_from_order(sales_order: str, submit: int = 0) -> dict:
    """Delivers the not-yet-delivered quantities of a submitted sales order."""
    erp_documents.require_roles(ROLES)
    from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

    source = _submitted_source("Sales Order", sales_order)
    return _finish(make_delivery_note(source.name), submit)


@frappe.whitelist(methods=["POST"])
def create_sales_invoice_from(doctype: str, name: str, submit: int = 0) -> dict:
    """Bills the not-yet-billed part of a submitted Sales Order or Delivery Note."""
    erp_documents.require_roles(ROLES)
    if doctype == "Sales Order":
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
    elif doctype == "Delivery Note":
        from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
    else:
        frappe.throw(_("Invoices can be made from a Sales Order or a Delivery Note"))
    source = _submitted_source(doctype, name)
    return _finish(make_sales_invoice(source.name), submit, serialize=serialize_invoice)


def _doctype(doctype: str) -> str:
    if doctype not in DOCTYPES:
        frappe.throw(_("Invalid sales document type"))
    return doctype


@frappe.whitelist()
def list_sales_documents(company: str, doctype: str, customer: str | None = None, status: str | None = None,
                         from_date: str | None = None, to_date: str | None = None, limit_start: int = 0,
                         limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    doctype = _doctype(doctype)
    start, length = paging(limit_start, limit_page_length)
    date_field = DOCTYPES[doctype]
    filters: dict = {"company": company}
    if customer:
        filters["party_name" if doctype == "Quotation" else "customer"] = customer
    if status:
        filters["status"] = status
    if period := erp_documents.date_range(from_date, to_date):
        filters[date_field] = period
    rows = frappe.get_list(doctype, filters=filters,
                           fields=["name", "customer_name", f"{date_field} as date", "grand_total",
                                   "currency", "status", "docstatus"],
                           order_by=f"{date_field} desc, creation desc",
                           limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_sales_document(doctype: str, name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_sales_document(erp_documents.load(_doctype(doctype), name)))


@frappe.whitelist(methods=["POST"])
def submit_sales_document(doctype: str, name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_sales_document(erp_documents.submit(_doctype(doctype), name)))


@frappe.whitelist(methods=["POST"])
def cancel_sales_document(doctype: str, name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_sales_document(erp_documents.cancel(_doctype(doctype), name)))
