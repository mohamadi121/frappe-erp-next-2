"""Receipts and payments on ERPNext `Payment Entry`.

Accounts come from ERPNext: the party account from `get_party_details`, the
bank/cash account from the Mode of Payment's company account. Payment Entry's
own validation sets exchange rates, amounts and allocations.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import (
    PARTY_TYPES,
    PAYMENT_TYPES,
    normalize_references,
    number,
    paging,
)

ROLES = ("System Manager", "Accounts Manager", "Accounts User")


def serialize_payment(doc) -> dict:
    return {
        "name": doc.name,
        "company": doc.company,
        "payment_type": doc.payment_type,
        "posting_date": str(doc.posting_date),
        "mode_of_payment": doc.mode_of_payment or "",
        "party_type": doc.party_type,
        "party": doc.party,
        "party_name": doc.party_name,
        "paid_from": doc.paid_from,
        "paid_to": doc.paid_to,
        "paid_amount": flt(doc.paid_amount),
        "received_amount": flt(doc.received_amount),
        "unallocated_amount": flt(doc.unallocated_amount),
        "reference_no": doc.reference_no or "",
        "reference_date": str(doc.reference_date or ""),
        "remarks": doc.remarks or "",
        "status": doc.status,
        "docstatus": doc.docstatus,
        "references": [
            {
                "reference_doctype": row.reference_doctype,
                "reference_name": row.reference_name,
                "total_amount": flt(row.total_amount),
                "outstanding_amount": flt(row.outstanding_amount),
                "allocated_amount": flt(row.allocated_amount),
            }
            for row in doc.references
        ],
    }


@frappe.whitelist()
def payment_options(company: str) -> dict:
    """Modes of payment with their account in this company, and company bank accounts."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    accounts = {
        row.parent: row.default_account
        for row in frappe.get_all("Mode of Payment Account", filters={"company": company},
                                  fields=["parent", "default_account"])
    }
    modes = [
        {**row, "account": accounts.get(row.name)}
        for row in frappe.get_list("Mode of Payment", filters={"enabled": 1},
                                   fields=["name", "type"], order_by="name asc")
    ]
    return success({
        "currency": frappe.get_cached_value("Company", company, "default_currency"),
        "modes_of_payment": modes,
        "bank_accounts": frappe.get_list("Bank Account", filters={"company": company,
                                                                  "is_company_account": 1},
                                         fields=["name", "account_name", "account", "bank"]),
    })


@frappe.whitelist()
def list_outstanding_documents(company: str, party_type: str, party: str) -> dict:
    """Unpaid invoices of a party (ERPNext `get_outstanding_reference_documents`)."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    if party_type not in PARTY_TYPES:
        frappe.throw(_("Invalid party type"))
    from erpnext.accounts.doctype.payment_entry.payment_entry import (
        get_outstanding_reference_documents,
    )
    from erpnext.accounts.party import get_party_account

    rows = get_outstanding_reference_documents({
        "company": company,
        "party_type": party_type,
        "party": party,
        "party_account": get_party_account(party_type, party, company),
        "get_outstanding_invoices": True,
    }) or []
    return success([
        {
            "reference_doctype": row.get("voucher_type"),
            "reference_name": row.get("voucher_no"),
            "posting_date": str(row.get("posting_date") or ""),
            "due_date": str(row.get("due_date") or ""),
            "invoice_amount": flt(row.get("invoice_amount")),
            "outstanding_amount": flt(row.get("outstanding_amount")),
            "currency": row.get("currency"),
        }
        for row in rows
    ])


@frappe.whitelist(methods=["POST"])
def create_payment_entry(company: str, payment_type: str, party_type: str, party: str, amount,
                         mode_of_payment: str, posting_date: str | None = None,
                         reference_no: str | None = None, reference_date: str | None = None,
                         references=None, remarks: str | None = None, submit: int = 0) -> dict:
    """A receipt from (``Receive``) or a payment to (``Pay``) a customer, supplier or employee."""
    erp_documents.require_roles(ROLES)
    require_company(company)
    if payment_type not in PAYMENT_TYPES:
        frappe.throw(_("Payment type must be Receive or Pay"))
    if party_type not in PARTY_TYPES:
        frappe.throw(_("Invalid party type"))
    try:
        paid = number(amount, "Amount", minimum=0, allow_equal=False)
        allocations = normalize_references(references, party_type, paid)
    except ValueError as error:
        frappe.throw(_(str(error)))
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_party_details
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

    posting = getdate(posting_date or nowdate())
    party_details = get_party_details(company, party_type, party, posting)
    bank_account = get_bank_cash_account(mode_of_payment, company)["account"]
    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    currencies = {party_details["party_account_currency"],
                  frappe.get_cached_value("Account", bank_account, "account_currency")}
    if currencies != {company_currency}:
        frappe.throw(_("Payments in a currency other than the company currency are not supported yet"))
    receive = payment_type == "Receive"
    doc = frappe.new_doc("Payment Entry")
    doc.update({
        "payment_type": payment_type,
        "company": company,
        "posting_date": posting,
        "mode_of_payment": mode_of_payment,
        "party_type": party_type,
        "party": party,
        "party_name": party_details["party_name"],
        "paid_from": party_details["party_account"] if receive else bank_account,
        "paid_to": bank_account if receive else party_details["party_account"],
        "paid_amount": paid,
        "received_amount": paid,
        "source_exchange_rate": 1,
        "target_exchange_rate": 1,
        "reference_no": (reference_no or "").strip() or None,
        "reference_date": getdate(reference_date) if reference_date else None,
        "remarks": (remarks or "").strip() or None,
    })
    for row in allocations:
        doc.append("references", row)
    erp_documents.insert(doc, submit_now=cint(submit))
    return success(serialize_payment(doc))


@frappe.whitelist()
def list_payment_entries(company: str, payment_type: str | None = None, party: str | None = None,
                         from_date: str | None = None, to_date: str | None = None,
                         limit_start: int = 0, limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"company": company}
    if payment_type:
        if payment_type not in PAYMENT_TYPES | {"Internal Transfer"}:
            frappe.throw(_("Invalid payment type"))
        filters["payment_type"] = payment_type
    if party:
        filters["party"] = party
    if period := erp_documents.date_range(from_date, to_date):
        filters["posting_date"] = period
    rows = frappe.get_list("Payment Entry", filters=filters,
                           fields=["name", "payment_type", "posting_date", "party_type", "party",
                                   "party_name", "mode_of_payment", "paid_amount", "status", "docstatus"],
                           order_by="posting_date desc, creation desc",
                           limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_payment_entry(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_payment(erp_documents.load("Payment Entry", name)))


@frappe.whitelist(methods=["POST"])
def submit_payment_entry(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_payment(erp_documents.submit("Payment Entry", name)))


@frappe.whitelist(methods=["POST"])
def cancel_payment_entry(name: str) -> dict:
    erp_documents.require_roles(ROLES)
    return success(serialize_payment(erp_documents.cancel("Payment Entry", name)))
