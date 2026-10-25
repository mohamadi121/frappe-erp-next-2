"""Assigning role definitions to accounts, site-wide or per office (multi-office access)."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import role_assignment_service as service
from asoud_erp.services.delegation import DELEGATE_ROLE
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import require_company


def _gate():
    # System Manager, or an explicitly delegated account; the per-grant escalation check follows.
    require_roles(("System Manager", DELEGATE_ROLE))


@frappe.whitelist(methods=["POST"])
def assign_role(user: str, role: str, company: str | None = None) -> dict:
    """Give ``user`` the role definition ``role`` (site-wide, or in ``company`` for office-scoped roles)."""
    _gate()
    return success(service.assign(str(user or ""), str(role or ""), company or None))


@frappe.whitelist(methods=["POST"])
def unassign_role(user: str, role: str, company: str | None = None) -> dict:
    _gate()
    return success(service.unassign(str(user or ""), str(role or ""), company or None))


@frappe.whitelist()
def list_office_roles(user: str) -> dict:
    """Per-office role assignments of one account (what the multi-office selector shows)."""
    _gate()
    rows = frappe.get_all("ASOUD Office Role Assignment", filters={"user": user},
                          fields=["company", "role_definition", "granted_by", "creation"],
                          order_by="company asc", limit_page_length=200)
    visible = []
    for row in rows:
        try:
            require_company(row.company)
        except frappe.PermissionError:
            continue
        visible.append({"company": row.company, "role": row.role_definition,
                        "granted_by": row.granted_by, "granted_on": str(row.creation)})
    return success({"user": user, "assignments": visible})
