import hashlib
import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.access_policy import (
    frappe_roles_for,
    normalize_asoud_roles,
)


def _employee_context(user: str) -> dict | None:
    employee = frappe.db.get_value(
        "Employee",
        {"user_id": user, "status": "Active"},
        ["name", "employee_name", "company"],
        as_dict=True,
    )
    return dict(employee) if employee else None


@frappe.whitelist()
def current_user() -> dict:
    """Return the authenticated identity and server-authoritative access context."""
    user_id = frappe.session.user
    if user_id == "Guest":
        frappe.throw(_("Authentication is required"), frappe.AuthenticationError)

    user = frappe.get_cached_doc("User", user_id)
    roles = sorted(role for role in frappe.get_roles(user_id) if role not in {"All", "Guest"})
    return success(
        {
            "user_id": user_id,
            "full_name": user.full_name,
            "roles": roles,
            "employee": _employee_context(user_id),
        }
    )


@frappe.whitelist(methods=["POST"])
def sync_employee_access(
    party_profile: str,
    email: str,
    personnel_roles: str | list[str],
    access_matrix: str | dict | None = None,
) -> dict:
    """Create/link an Employee user and apply only allow-listed ERPNext roles."""
    if not {"System Manager", "HR Manager"}.intersection(frappe.get_roles()):
        frappe.throw(_("Only HR managers can manage employee access"), frappe.PermissionError)
    profile = _access_profile(party_profile)
    if not profile.employee:
        frappe.throw(_("The party profile is not linked to an employee"))

    values = json.loads(personnel_roles) if isinstance(personnel_roles, str) else personnel_roles
    canonical_roles = normalize_asoud_roles(values)
    frappe_roles = sorted(set(frappe_roles_for(canonical_roles)) | {"Employee"})
    if not canonical_roles:
        frappe.throw(_("Select at least one supported personnel access role"))

    email = (email or "").strip().lower()
    if not email:
        frappe.throw(_("A valid login email is required"))

    employee = frappe.get_doc("Employee", profile.employee)
    matrix = json.loads(access_matrix) if isinstance(access_matrix, str) else access_matrix
    if matrix is not None and not isinstance(matrix, dict):
        frappe.throw(_("Invalid access matrix"))
    if matrix:
        frappe.throw("Fine-grained access matrices are not supported; select a standard role")
    profile.access_permissions = "{}"
    if employee.company != profile.company:
        frappe.throw("Employee company mismatch", frappe.PermissionError)
    if email in {"administrator", "guest", frappe.session.user.lower()}:
        frappe.throw("Protected account cannot be changed", frappe.PermissionError)
    if "System Manager" not in frappe.get_roles() and set(frappe_roles) - set(frappe.get_roles()) - {"Employee"}:
        frappe.throw("You cannot grant roles you do not hold", frappe.PermissionError)
    other = frappe.db.exists("Employee", {"user_id": email, "name": ["!=", employee.name]})
    if other:
        frappe.throw("This login is linked to another Employee", frappe.PermissionError)
    if employee.user_id and employee.user_id != email:
        frappe.throw(_("This employee is already linked to another user"))

    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        if {"System Manager", "HR Manager"}.intersection(frappe.get_roles(email)):
            frappe.throw("Privileged accounts must be managed in system administration", frappe.PermissionError)
        if not user.enabled:
            frappe.throw(_("The selected user is disabled"))
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": employee.first_name or employee.employee_name,
                "send_welcome_email": 0,
                "user_type": "System User",
            }
        )
        user.insert(ignore_permissions=True)

    previous = frappe_roles_for(json.loads(profile.employee_roles or "[]"))
    roles_to_remove = set(previous) - set(frappe_roles)
    retained = [row.role for row in user.roles if row.role not in roles_to_remove]
    user.set("roles", [{"role": role} for role in sorted(set(retained) | set(frappe_roles))])
    user.save(ignore_permissions=True)
    employee.user_id = user.name
    employee.create_user_permission = 1
    employee.save(ignore_permissions=True)

    profile.employee_roles = json.dumps(canonical_roles)
    profile.save(ignore_permissions=True)
    return success(
        {
            "user_id": user.name,
            "employee": employee.name,
            "company": employee.company,
            "personnel_roles": canonical_roles,
            "frappe_roles": frappe_roles,
        }
    )


def _access_profile(name: str):
    if not {"System Manager", "HR Manager"}.intersection(frappe.get_roles()):
        frappe.throw(_("Only HR managers can manage employee access"), frappe.PermissionError)
    profile = frappe.get_doc("ASOUD Party Profile", name, for_update=True)
    from asoud_erp.services.request_access import require_company

    require_company(profile.company)
    if frappe.db.get_value("Employee", profile.employee, "company") != profile.company:
        frappe.throw("Employee company mismatch", frappe.PermissionError)
    if not profile.employee:
        frappe.throw(_("The personnel profile is not linked to an employee"))
    return profile


@frappe.whitelist()
def get_employee_access(party_profile: str):
    profile = _access_profile(party_profile)
    employee = frappe.get_doc("Employee", profile.employee)
    user = frappe.get_doc("User", employee.user_id) if employee.user_id else None
    try:
        matrix = json.loads(profile.access_permissions or "{}")
    except (TypeError, ValueError):
        matrix = {}
    return success({
        "party_profile": profile.name,
        "employee": employee.name,
        "user_id": employee.user_id or "",
        "email": user.name if user else "",
        "enabled": bool(user.enabled) if user else False,
        "roles": json.loads(profile.employee_roles or "[]"),
        "access_matrix": matrix,
    })


@frappe.whitelist()
def list_employee_invitations(company: str):
    if not {"System Manager", "HR Manager"}.intersection(frappe.get_roles()):
        frappe.throw(_("Only HR managers can manage invitations"), frappe.PermissionError)
    from asoud_erp.services.request_access import require_company

    require_company(company)
    rows = frappe.get_all(
        "ASOUD Employee Invitation",
        filters={"company": company},
        fields=["name", "party_profile", "email", "status", "method", "sent_at"],
        order_by="creation desc",
    )
    for row in rows:
        queues = frappe.get_all("Email Queue", filters={"reference_doctype": "ASOUD Employee Invitation",
            "reference_name": row["name"]}, pluck="status")
        if queues:
            row["status"] = "Sent" if all(value == "Sent" for value in queues) else "Error" if "Error" in queues else "Queued"
        row["personnel"] = frappe.db.get_value(
            "ASOUD Party Profile", row["party_profile"], "display_name"
        ) or ""
    return success({"rows": rows})


@frappe.whitelist(methods=["POST"])
def send_employee_invitation(party_profile, email, personnel_roles, request_id,
                             access_matrix=None, method="ایمیل"):
    profile = _access_profile(party_profile)
    if method != "ایمیل":
        frappe.throw("Only email invitations are implemented")
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")
    roles = json.loads(personnel_roles) if isinstance(personnel_roles, str) else personnel_roles
    matrix = json.loads(access_matrix) if isinstance(access_matrix, str) else (access_matrix or {})
    fingerprint = hashlib.sha256(json.dumps([party_profile, email.strip().lower(), roles, matrix], sort_keys=True).encode()).hexdigest()
    existing = frappe.db.get_value("ASOUD Employee Invitation", {"request_id": request_id},
        ["name", "request_fingerprint", "status"], as_dict=True, for_update=True)
    if existing:
        if existing.request_fingerprint != fingerprint:
            frappe.throw("Request ID conflict")
        return success({"name": existing.name, "status": existing.status})
    if not frappe.db.exists("Email Account", {"enable_outgoing": 1}):
        frappe.throw("Configure an outgoing Email Account before sending invitations")
    result = sync_employee_access(party_profile, email, roles, matrix)["data"]
    invitation = frappe.get_doc({"doctype": "ASOUD Employee Invitation", "company": profile.company,
        "party_profile": profile.name, "email": email.strip().lower(), "status": "Queued", "method": method,
        "roles": json.dumps(result["personnel_roles"]), "access_matrix": "{}",
        "request_id": request_id, "request_fingerprint": fingerprint}).insert(ignore_permissions=True)
    user = frappe.get_doc("User", result["user_id"])
    link = user._reset_password(send_email=False)
    from html import escape

    frappe.sendmail(recipients=[user.name], subject="ASOUD account invitation",
        message='Set your account password: <a href="' + escape(link, quote=True) + '">Activate account</a>',
        reference_doctype=invitation.doctype, reference_name=invitation.name, delayed=True)
    return success({"name": invitation.name, "status": "Queued"})


@frappe.whitelist(methods=["POST"])
def delete_employee_access(party_profile):
    profile = _access_profile(party_profile)
    employee = frappe.get_doc("Employee", profile.employee, for_update=True)
    if employee.user_id:
        user_id = employee.user_id
        if user_id in {"Administrator", "Guest", frappe.session.user} or {"System Manager", "HR Manager"}.intersection(frappe.get_roles(user_id)):
            frappe.throw("Protected account cannot be unlinked", frappe.PermissionError)
        if frappe.db.exists("Employee", {"user_id": user_id, "name": ["!=", employee.name]}):
            frappe.throw("Shared login must be managed in system administration", frappe.PermissionError)
        user = frappe.get_doc("User", user_id, for_update=True)
        managed = set(frappe_roles_for(json.loads(profile.employee_roles or "[]"))) | {"Employee"}
        user.set("roles", [{"role": row.role} for row in user.roles if row.role not in managed])
        user.save(ignore_permissions=True)
        employee.user_id = None
        employee.save(ignore_permissions=True)
        for name in frappe.get_all("User Permission", filters={"user": user_id, "allow": "Employee", "for_value": employee.name}, pluck="name"):
            frappe.delete_doc("User Permission", name, ignore_permissions=True)
    profile.employee_roles = "[]"
    profile.access_permissions = "{}"
    profile.save(ignore_permissions=True)
    return success({"party_profile": profile.name, "deleted": True})
