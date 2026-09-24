"""Point of sale on ERPNext POS: sessions, items, POS invoices and closing.

Reuses ERPNext's own point-of-sale page functions (profile access, opening
voucher, item search) and closing flow; on closing, ERPNext consolidates the
session's POS invoices into regular Sales Invoices. Standard POS permissions
apply: opening/closing entries need their ERPNext rights (e.g. Sales Manager),
POS invoices need Accounts User/Manager.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import normalize_lines, number, parse_json


def _balances(value, key: str) -> list[dict]:
    rows = parse_json(value, key) or []
    if not isinstance(rows, list):
        frappe.throw(_("{0} must be a list").format(key))
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("mode_of_payment"):
            frappe.throw(_("Each {0} row needs mode_of_payment").format(key))
        try:
            amount = number(row.get("amount", 0), "Amount", minimum=0)
        except ValueError as error:
            frappe.throw(_(str(error)))
        result.append({"mode_of_payment": row["mode_of_payment"], "amount": amount})
    return result


def _open_session(pos_profile: str | None = None) -> dict | None:
    from erpnext.selling.page.point_of_sale.point_of_sale import check_opening_entry

    sessions = check_opening_entry(frappe.session.user)
    if pos_profile:
        sessions = [row for row in sessions if row.pos_profile == pos_profile]
    return sessions[0] if sessions else None


@frappe.whitelist()
def pos_options(company: str) -> dict:
    """POS profiles the session user may use, with warehouse, price list and payment modes."""
    require_company(company)
    from erpnext.selling.page.point_of_sale.point_of_sale import check_pos_profile_access

    profiles = []
    for name in frappe.get_all("POS Profile", filters={"company": company, "disabled": 0}, pluck="name"):
        try:
            check_pos_profile_access(name)
        except frappe.PermissionError:
            continue
        doc = frappe.get_cached_doc("POS Profile", name)
        profiles.append({
            "name": doc.name, "warehouse": doc.warehouse, "selling_price_list": doc.selling_price_list,
            "currency": doc.currency, "customer": doc.customer or "",
            "payments": [{"mode_of_payment": row.mode_of_payment, "default": row.default} for row in doc.payments],
        })
    return success({"profiles": profiles, "open_session": _open_session()})


@frappe.whitelist()
def get_pos_items(pos_profile: str, search_term: str = "", item_group: str | None = None, start: int = 0,
                  page_length: int = 40) -> dict:
    """Items with price and stock for a profile (ERPNext POS item search)."""
    from erpnext.selling.page.point_of_sale.point_of_sale import check_pos_profile_access, get_items

    check_pos_profile_access(pos_profile)
    profile = frappe.get_cached_doc("POS Profile", pos_profile)
    group = item_group or frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]})
    data = get_items(int(start), min(int(page_length), 100), profile.selling_price_list, group, pos_profile,
                     search_term or "")
    return success([
        {key: row.get(key) for key in ("item_code", "item_name", "stock_uom", "uom", "price_list_rate",
                                       "currency", "actual_qty", "item_image")}
        for row in data.get("items", [])
    ])


@frappe.whitelist()
def get_open_pos_session(pos_profile: str | None = None) -> dict:
    return success(_open_session(pos_profile))


@frappe.whitelist(methods=["POST"])
def create_pos_session(pos_profile: str, opening_balances=None) -> dict:
    """Opens a session (POS Opening Entry) for the session user."""
    from erpnext.selling.page.point_of_sale.point_of_sale import create_opening_voucher

    if _open_session(pos_profile):
        frappe.throw(_("A POS session is already open for this profile"))
    company = frappe.db.get_value("POS Profile", pos_profile, "company")
    require_company(company)
    rows = [{"mode_of_payment": row["mode_of_payment"], "opening_amount": row["amount"]}
            for row in _balances(opening_balances, "opening_balances")]
    opening = create_opening_voucher(pos_profile, company, json.dumps(rows))
    return success({"name": opening["name"], "pos_profile": pos_profile, "company": company,
                    "period_start_date": str(opening["period_start_date"])})


def serialize_pos_invoice(doc) -> dict:
    return {
        "name": doc.name, "pos_profile": doc.pos_profile, "customer": doc.customer,
        "posting_date": str(doc.posting_date), "net_total": flt(doc.net_total),
        "total_taxes_and_charges": flt(doc.total_taxes_and_charges), "grand_total": flt(doc.grand_total),
        "rounded_total": flt(doc.rounded_total), "paid_amount": flt(doc.paid_amount),
        "change_amount": flt(doc.change_amount), "status": doc.status, "docstatus": doc.docstatus,
        "items": [{"item_code": row.item_code, "item_name": row.item_name, "qty": flt(row.qty), "rate": flt(row.rate),
                   "amount": flt(row.amount)} for row in doc.items],
        "payments": [{"mode_of_payment": row.mode_of_payment, "amount": flt(row.amount)} for row in doc.payments],
    }


@frappe.whitelist(methods=["POST"])
def create_pos_invoice(pos_profile: str, items, payments, customer: str | None = None) -> dict:
    """A paid POS invoice in the user's open session; stock leaves the profile's warehouse."""
    session = _open_session(pos_profile)
    if not session:
        frappe.throw(_("Open a POS session for this profile first"))
    try:
        lines = normalize_lines(items, rates=True)
    except ValueError as error:
        frappe.throw(_(str(error)))
    profile = frappe.get_cached_doc("POS Profile", pos_profile)
    paid = _balances(payments, "payments")
    if not paid:
        frappe.throw(_("At least one payment is required"))
    doc = frappe.new_doc("POS Invoice")
    doc.update({"company": profile.company, "pos_profile": pos_profile, "is_pos": 1, "update_stock": 1,
                "customer": customer or profile.customer, "set_warehouse": profile.warehouse})
    for line in lines:
        doc.append("items", {**line, "warehouse": profile.warehouse})
    doc.set_missing_values()
    doc.set("payments", [])
    for row in paid:
        doc.append("payments", {"mode_of_payment": row["mode_of_payment"], "amount": row["amount"]})
    doc.calculate_taxes_and_totals()
    doc.insert()
    doc.submit()
    return success(serialize_pos_invoice(doc))


@frappe.whitelist()
def list_pos_invoices(pos_session: str) -> dict:
    """POS invoices of one session (POS Opening Entry), oldest first.

    An open session uses ERPNext's own session query; a closed one lists the
    invoices its closing entry took in.
    """
    from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import get_pos_invoices

    opening = erp_documents.load("POS Opening Entry", pos_session)
    if opening.pos_closing_entry:
        closing = frappe.get_doc("POS Closing Entry", opening.pos_closing_entry)
        return success([{"name": row.pos_invoice, "customer": row.customer, "grand_total": flt(row.grand_total),
                         "posting_date": str(row.posting_date), "is_return": row.is_return}
                        for row in closing.pos_transactions])
    rows = get_pos_invoices(opening.period_start_date, frappe.utils.now_datetime(), opening.pos_profile,
                            opening.user)
    return success([{"name": row.name, "customer": row.customer, "grand_total": flt(row.grand_total),
                     "posting_date": str(row.posting_date), "is_return": row.is_return} for row in rows])


@frappe.whitelist(methods=["POST"])
def close_pos_session(pos_session: str, closing_balances=None) -> dict:
    """Closes a session with the counted amount per payment mode (default: the expected amount).

    ERPNext then consolidates the session's POS invoices into Sales Invoices.
    """
    from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening

    opening = erp_documents.load("POS Opening Entry", pos_session)
    if opening.user != frappe.session.user and not frappe.has_permission("POS Closing Entry", "create"):
        frappe.throw(_("Only the cashier of this session can close it"), frappe.PermissionError)
    if opening.pos_closing_entry or opening.status != "Open":
        frappe.throw(_("This POS session is already closed"))
    counted = {row["mode_of_payment"]: row["amount"] for row in _balances(closing_balances, "closing_balances")}
    closing = make_closing_entry_from_opening(opening)
    for row in closing.payment_reconciliation:
        row.closing_amount = counted.get(row.mode_of_payment, row.expected_amount)
    closing.insert()
    closing.submit()
    closing.reload()
    return success({
        "name": closing.name, "pos_session": opening.name, "status": closing.status,
        "grand_total": flt(closing.grand_total), "net_total": flt(closing.net_total),
        "total_quantity": flt(closing.total_quantity), "invoices": len(closing.pos_transactions),
        "payment_reconciliation": [
            {"mode_of_payment": row.mode_of_payment, "opening_amount": flt(row.opening_amount),
             "expected_amount": flt(row.expected_amount), "closing_amount": flt(row.closing_amount),
             "difference": flt(row.difference)} for row in closing.payment_reconciliation],
    })
