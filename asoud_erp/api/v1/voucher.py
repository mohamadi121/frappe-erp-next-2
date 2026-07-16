import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.voucher_service import validate_voucher_lines

ALLOWED_STATUSES = {"Draft", "Pending Approval", "Approved", "Rejected"}


def _parse_lines(lines: str | list[dict]) -> list[dict]:
    values = json.loads(lines) if isinstance(lines, str) else lines
    if not isinstance(values, list):
        frappe.throw(_("Voucher rows are not valid"))
    normalized = [dict(value) for value in values]
    try:
        validate_voucher_lines(normalized)
    except ValueError as exc:
        frappe.throw(_(str(exc)))
    return normalized


def _serialize(doc) -> dict:
    return {
        "name": doc.name,
        "company": doc.company,
        "posting_date": str(doc.posting_date),
        "description": doc.description or "",
        "status": doc.workflow_status,
        "total_debit": float(doc.total_debit or 0),
        "total_credit": float(doc.total_credit or 0),
        "rejection_reason": doc.rejection_reason or "",
        "journal_entry": doc.journal_entry or "",
        "lines": [
            {
                "account": row.account,
                "floating_detail": row.floating_detail or "",
                "description": row.description or "",
                "debit": float(row.debit or 0),
                "credit": float(row.credit or 0),
            }
            for row in doc.lines
        ],
    }


@frappe.whitelist()
def list_vouchers(company: str, status: str | None = None, search: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    filters = {"company": company}
    if status:
        if status not in ALLOWED_STATUSES:
            frappe.throw(_("Voucher status is not valid"))
        filters["workflow_status"] = status
    or_filters = None
    if search:
        term = f"%{search}%"
        or_filters = {"name": ["like", term], "description": ["like", term]}
    names = frappe.get_all(
        "ASOUD Accounting Voucher",
        filters=filters,
        or_filters=or_filters,
        pluck="name",
        order_by="posting_date desc, modified desc",
        limit_page_length=200,
    )
    return success([_serialize(frappe.get_doc("ASOUD Accounting Voucher", name)) for name in names])


@frappe.whitelist(methods=["POST"])
def save_voucher(
    company: str,
    posting_date: str,
    lines: str | list[dict],
    description: str | None = None,
    name: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    values = _parse_lines(lines)
    doc = frappe.get_doc("ASOUD Accounting Voucher", name) if name else frappe.new_doc("ASOUD Accounting Voucher")
    if name and doc.workflow_status != "Draft":
        frappe.throw(_("Only draft vouchers can be edited"))
    doc.company = company
    doc.posting_date = posting_date
    doc.description = (description or "").strip()
    doc.set("lines", [])
    for value in values:
        doc.append(
            "lines",
            {
                "account": value.get("account"),
                "floating_detail": value.get("floating_detail"),
                "description": value.get("description"),
                "debit": value.get("debit") or 0,
                "credit": value.get("credit") or 0,
            },
        )
    doc.save() if name else doc.insert()
    return success(_serialize(doc))


@frappe.whitelist(methods=["POST"])
def submit_for_approval(name: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    doc = frappe.get_doc("ASOUD Accounting Voucher", name)
    if doc.workflow_status not in {"Draft", "Rejected"}:
        frappe.throw(_("Only draft or rejected vouchers can be submitted"))
    doc.workflow_status = "Pending Approval"
    doc.rejection_reason = ""
    doc.save()
    return success(_serialize(doc))


@frappe.whitelist(methods=["POST"])
def approve_voucher(name: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    doc = frappe.get_doc("ASOUD Accounting Voucher", name)
    if doc.workflow_status != "Pending Approval":
        frappe.throw(_("Voucher is not pending approval"))
    journal = frappe.get_doc(
        {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": doc.company,
            "posting_date": doc.posting_date,
            "user_remark": doc.description,
            "accounts": [
                {
                    "account": row.account,
                    "debit_in_account_currency": row.debit,
                    "credit_in_account_currency": row.credit,
                    "user_remark": row.description,
                }
                for row in doc.lines
            ],
        }
    )
    journal.insert()
    journal.submit()
    doc.workflow_status = "Approved"
    doc.journal_entry = journal.name
    doc.approved_by = frappe.session.user
    doc.approved_on = frappe.utils.now()
    doc.save()
    return success(_serialize(doc))


@frappe.whitelist(methods=["POST"])
def reject_voucher(name: str, reason: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not reason or len(reason.strip()) < 3:
        frappe.throw(_("Rejection reason is required"))
    doc = frappe.get_doc("ASOUD Accounting Voucher", name)
    if doc.workflow_status != "Pending Approval":
        frappe.throw(_("Voucher is not pending approval"))
    doc.workflow_status = "Rejected"
    doc.rejection_reason = reason.strip()
    doc.save()
    return success(_serialize(doc))
