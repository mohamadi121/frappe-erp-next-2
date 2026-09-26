"""IT and service requests on ERPNext `Issue`; equipment on ERPNext `Asset`.

An issue raised here belongs to the session user (``raised_by``); support staff
work on it in ERPNext's Support module, including SLAs and assignment.
"""

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import paging

SUPPORT_ROLES = ("System Manager", "Support Team")
ASSET_ROLES = ("System Manager", "Accounts Manager", "Accounts User", "Quality Manager")


def _my_email() -> str:
    return frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user


def serialize_issue(doc) -> dict:
    return {
        "name": doc.name, "subject": doc.subject, "description": doc.description or "",
        "status": doc.status, "priority": doc.priority or "", "issue_type": doc.issue_type or "",
        "raised_by": doc.raised_by or "", "company": doc.company or "",
        "opening_date": str(doc.opening_date or ""), "resolution_details": doc.resolution_details or "",
        "comments": [
            {"by": row.comment_email, "on": str(row.creation), "text": row.content}
            for row in frappe.get_all("Comment",
                                      filters={"reference_doctype": "Issue", "reference_name": doc.name,
                                               "comment_type": "Comment"},
                                      fields=["comment_email", "creation", "content"],
                                      order_by="creation asc")
        ],
    }


def _own_issue(name: str):
    doc = frappe.get_doc("Issue", name) if frappe.db.exists("Issue", name) else None
    if not doc:
        frappe.throw(_("Issue {0} does not exist").format(name), frappe.DoesNotExistError)
    if doc.raised_by != _my_email() and not set(SUPPORT_ROLES) & set(frappe.get_roles()):
        frappe.throw(_("Not permitted to view this issue"), frappe.PermissionError)
    return doc


@frappe.whitelist()
def issue_options() -> dict:
    return success({
        "issue_types": frappe.get_all("Issue Type", pluck="name", order_by="name asc"),
        "priorities": frappe.get_all("Issue Priority", pluck="name", order_by="name asc"),
    })


@frappe.whitelist(methods=["POST"])
def create_issue(subject: str, description: str | None = None, issue_type: str | None = None,
                 priority: str | None = None, company: str | None = None) -> dict:
    """Any signed-in user may raise an issue for themselves."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Sign in to raise an issue"), frappe.PermissionError)
    title = (subject or "").strip()
    if not 3 <= len(title) <= 140:
        frappe.throw(_("Subject must contain 3 to 140 characters"))
    if company:
        require_company(company)
    doc = frappe.get_doc({
        "doctype": "Issue", "subject": title, "description": (description or "").strip(),
        "issue_type": issue_type or None, "priority": priority or None, "company": company or None,
        "raised_by": _my_email(),
    })
    # Employees have no Issue role in ERPNext; ownership is enforced by raised_by above.
    doc.insert(ignore_permissions=True)
    return success(serialize_issue(doc))


@frappe.whitelist()
def list_my_issues(status: str | None = None, limit_start: int = 0, limit_page_length: int = 20) -> dict:
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"raised_by": _my_email()}
    if status:
        filters["status"] = status
    rows = frappe.get_all("Issue", filters=filters,
                          fields=["name", "subject", "status", "priority", "issue_type", "opening_date"],
                          order_by="creation desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_issue(name: str) -> dict:
    return success(serialize_issue(_own_issue(name)))


@frappe.whitelist(methods=["POST"])
def add_issue_comment(name: str, comment: str) -> dict:
    doc = _own_issue(name)
    text = (comment or "").strip()
    if not text or len(text) > 5000:
        frappe.throw(_("Comment must contain 1 to 5000 characters"))
    doc.add_comment("Comment", text, comment_email=_my_email())
    return success(serialize_issue(doc))


@frappe.whitelist()
def list_my_assets() -> dict:
    """Submitted assets whose custodian is the session user's Employee."""
    employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
    if not employee:
        return success([])
    return success(frappe.get_all("Asset", filters={"custodian": employee, "docstatus": 1},
                                  fields=["name", "asset_name", "item_code", "asset_category", "location",
                                          "status", "purchase_date"],
                                  order_by="asset_name asc"))


@frappe.whitelist()
def list_assets(company: str, search: str | None = None, limit_start: int = 0,
                limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(ASSET_ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    or_filters = None
    if search:
        term = f"%{search.strip()}%"
        or_filters = {"name": ["like", term], "asset_name": ["like", term]}
    rows = frappe.get_list("Asset", filters={"company": company, "docstatus": 1}, or_filters=or_filters,
                           fields=["name", "asset_name", "item_code", "asset_category", "location",
                                   "custodian", "department", "status", "gross_purchase_amount"],
                           order_by="asset_name asc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))
