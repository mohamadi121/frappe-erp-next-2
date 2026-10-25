"""Loading and state changes of ERPNext documents under the caller's permissions."""

import frappe
from frappe import _
from frappe.utils import getdate

from asoud_erp.services.request_access import require_company


def require_roles(roles, company=None) -> None:
    """Like ``frappe.only_for``, but also enforced while tests run.

    With ``company`` the roles an account holds only in that office (per-office role
    assignments) count as well; without it only the global roles do.
    """
    roles = (roles,) if isinstance(roles, str) else tuple(roles)
    if frappe.session.user == "Administrator":
        return
    if set(roles) & set(frappe.get_roles()):
        return
    if company:
        from asoud_erp.services.office_access import office_roles

        if set(roles) & office_roles(frappe.session.user, company):
            return
    frappe.throw(_("Not permitted"), frappe.PermissionError)


def load(doctype: str, name: str, ptype: str = "read"):
    """The document, if the session user has ``ptype`` on it and access to its company."""
    if not name or not frappe.db.exists(doctype, name):
        frappe.throw(_("{0} {1} does not exist").format(_(doctype), name), frappe.DoesNotExistError)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission(ptype)
    if doc.meta.has_field("company"):
        require_company(doc.company)
    return doc


def submit(doctype: str, name: str):
    doc = load(doctype, name, "submit")
    if doc.docstatus != 0:
        frappe.throw(_("Only a draft can be submitted"))
    doc.submit()
    return doc


def cancel(doctype: str, name: str):
    doc = load(doctype, name, "cancel")
    if doc.docstatus != 1:
        frappe.throw(_("Only a submitted document can be cancelled"))
    doc.cancel()
    return doc


def insert(doc, submit_now: bool = False):
    """Inserts (and optionally submits) with ERPNext permission checks intact."""
    doc.insert()
    if submit_now:
        doc.submit()
    return doc


def date_range(from_date: str | None, to_date: str | None) -> list | None:
    """A Frappe filter value for an optional, inclusive date range."""
    if from_date and to_date:
        start, end = getdate(from_date), getdate(to_date)
        if start > end:
            frappe.throw(_("From date must not be after to date"))
        return ["between", [start, end]]
    if from_date:
        return [">=", getdate(from_date)]
    if to_date:
        return ["<=", getdate(to_date)]
    return None


def list_meta(start: int, length: int, rows: list) -> dict:
    return {"limit_start": start, "limit_page_length": length, "count": len(rows)}
