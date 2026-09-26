"""Sales invoices on ERPNext `Sales Invoice`.

Prices, taxes, party accounts and due dates come from ERPNext itself
(`set_missing_values`, `set_taxes`, price lists and tax templates).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import normalize_lines, paging

ROLES = ("System Manager", "Accounts Manager", "Accounts User", "Sales Manager", "Sales User")
LIST_STATUSES = {"Draft", "Unpaid", "Overdue", "Partly Paid", "Paid", "Return", "Credit Note Issued",
                 "Cancelled"}


def serialize_invoice(doc) -> dict:
    return {
        "name": doc.name,
        "company": doc.company,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "posting_date": str(doc.posting_date),
        "due_date": str(doc.due_date or ""),
        "currency": doc.currency,
        "is_return": cint(doc.is_return),
        "return_against": doc.return_against or "",
        "taxes_and_charges": doc.taxes_and_charges or "",
        "net_total": flt(doc.net_total),
        "total_taxes_and_charges": flt(doc.total_taxes_and_charges),
        "discount_amount": flt(doc.discount_amount),
        "grand_total": flt(doc.grand_total),
        "rounded_total": flt(doc.rounded_total),
        "outstanding_amount": flt(doc.outstanding_amount),
        "status": doc.status,
        "docstatus": doc.docstatus,
        "remarks": doc.remarks or "",
        "items": [
            {
                "item_code": row.item_code,
                "item_name": row.item_name,
                "qty": flt(row.qty),
                "uom": row.uom,
                "price_list_rate": flt(row.price_list_rate),
                "discount_percentage": flt(row.discount_percentage),
                "rate": flt(row.rate),
                "amount": flt(row.amount),
                "warehouse": row.warehouse or "",
            }
            for row in doc.items
        ],
        "taxes": [
            {"description": row.description, "rate": flt(row.rate), "tax_amount": flt(row.tax_amount)}
            for row in doc.taxes
        ],
    }


@frappe.whitelist()
def selling_options(company: str) -> dict:
    """Customers, tax templates and the selling price list for the invoice form."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    customers = frappe.get_list("Customer", filters={"disabled": 0},
                                fields=["name", "customer_name", "customer_group"],
                                order_by="customer_name asc", limit_page_length=500)
    templates = frappe.get_list("Sales Taxes and Charges Template",
                                filters={"company": company, "disabled": 0},
                                fields=["name", "title", "is_default"], order_by="title asc")
    return success({
        "currency": frappe.get_cached_value("Company", company, "default_currency"),
        "selling_price_list": frappe.db.get_single_value("Selling Settings", "selling_price_list"),
        "customers": customers,
        "tax_templates": templates,
        "warehouses": frappe.get_list("Warehouse", filters={"company": company, "is_group": 0,
                                                            "disabled": 0},
                                      fields=["name", "warehouse_name"], order_by="warehouse_name asc"),
    })


@frappe.whitelist()
def get_item_price(company: str, item_code: str, customer: str | None = None, qty: float = 1,
                   uom: str | None = None, posting_date: str | None = None) -> dict:
    """ERPNext's own line pricing (price list, pricing rules, UOM conversion) for one item."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    from erpnext.stock.get_item_details import get_item_details

    currency = frappe.get_cached_value("Company", company, "default_currency")
    details = get_item_details({
        "doctype": "Sales Invoice",
        "company": company,
        "customer": customer,
        "item_code": item_code,
        "qty": flt(qty) or 1,
        "uom": uom,
        "currency": currency,
        "price_list": frappe.db.get_single_value("Selling Settings", "selling_price_list"),
        "price_list_currency": currency,
        "conversion_rate": 1,
        "plc_conversion_rate": 1,
        "transaction_date": posting_date or nowdate(),
    })
    result = {key: details.get(key) for key in (
        "item_code", "item_name", "uom", "stock_uom", "conversion_factor", "price_list_rate",
        "discount_percentage", "discount_amount", "rate", "item_tax_template", "actual_qty",
    )}
    if not flt(result["rate"]):
        # ERPNext leaves the discounted rate to the form; a pricing rule may already have set it.
        result["rate"] = flt(result["price_list_rate"]) * (1 - flt(result["discount_percentage"]) / 100) \
            - flt(result["discount_amount"])
    return success(result)


@frappe.whitelist(methods=["POST"])
def create_sales_invoice(company: str, customer: str, items, posting_date: str | None = None,
                         due_date: str | None = None, taxes_and_charges: str | None = None,
                         remarks: str | None = None, update_stock: int = 0, submit: int = 0) -> dict:
    """Creates a draft (or, with ``submit=1``, a submitted) sales invoice."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    try:
        lines = normalize_lines(items, rates=True, warehouses=True)
    except ValueError as error:
        frappe.throw(_(str(error)))
    doc = frappe.new_doc("Sales Invoice")
    doc.update({
        "company": company,
        "customer": customer,
        "posting_date": getdate(posting_date or nowdate()),
        "set_posting_time": 1,
        "update_stock": cint(update_stock),
        "remarks": (remarks or "").strip(),
    })
    if due_date:
        doc.due_date = getdate(due_date)
    if taxes_and_charges:
        doc.taxes_and_charges = taxes_and_charges
    for line in lines:
        doc.append("items", line)
    doc.set_missing_values()
    doc.set_taxes()
    doc.calculate_taxes_and_totals()
    erp_documents.insert(doc, submit_now=cint(submit))
    return success(serialize_invoice(doc))


@frappe.whitelist()
def list_sales_invoices(company: str, status: str | None = None, customer: str | None = None,
                        search: str | None = None, from_date: str | None = None,
                        to_date: str | None = None, limit_start: int = 0,
                        limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"company": company}
    if status:
        if status not in LIST_STATUSES:
            frappe.throw(_("Invalid invoice status"))
        filters["status"] = status
    if customer:
        filters["customer"] = customer
    if period := erp_documents.date_range(from_date, to_date):
        filters["posting_date"] = period
    or_filters = None
    if search:
        term = f"%{search.strip()}%"
        or_filters = {"name": ["like", term], "customer_name": ["like", term]}
    rows = frappe.get_list("Sales Invoice", filters=filters, or_filters=or_filters,
                           fields=["name", "customer", "customer_name", "posting_date", "due_date",
                                   "grand_total", "outstanding_amount", "currency", "status",
                                   "docstatus", "is_return"],
                           order_by="posting_date desc, creation desc",
                           limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_sales_invoice(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_invoice(erp_documents.load("Sales Invoice", name)))


@frappe.whitelist(methods=["POST"])
def submit_sales_invoice(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_invoice(erp_documents.submit("Sales Invoice", name)))


@frappe.whitelist(methods=["POST"])
def cancel_sales_invoice(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_invoice(erp_documents.cancel("Sales Invoice", name)))


@frappe.whitelist(methods=["POST"])
def create_sales_return(name: str, submit: int = 0) -> dict:
    """A credit note for the whole of a submitted invoice (ERPNext `make_sales_return`)."""
    erp_documents.require_roles(ROLES)
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

    source = erp_documents.load("Sales Invoice", name)
    if source.docstatus != 1 or source.is_return:
        frappe.throw(_("Only a submitted sales invoice can be returned"))
    doc = make_sales_return(source.name)
    erp_documents.insert(doc, submit_now=cint(submit))
    return success(serialize_invoice(doc))
