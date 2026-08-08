import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.access_policy import (
    ASOUD_ROLE_TO_FRAPPE_ROLES,
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
) -> dict:
    """Create/link an Employee user and apply only allow-listed ERPNext roles."""
    frappe.only_for("System Manager")
    profile = frappe.get_doc("ASOUD Party Profile", party_profile)
    if not profile.employee:
        frappe.throw(_("The party profile is not linked to an employee"))

    values = json.loads(personnel_roles) if isinstance(personnel_roles, str) else personnel_roles
    canonical_roles = normalize_asoud_roles(values)
    frappe_roles = frappe_roles_for(canonical_roles)
    if not canonical_roles:
        frappe.throw(_("Select at least one supported personnel access role"))

    email = (email or "").strip().lower()
    if not email:
        frappe.throw(_("A valid login email is required"))

    employee = frappe.get_doc("Employee", profile.employee)
    if employee.user_id and employee.user_id != email:
        frappe.throw(_("This employee is already linked to another user"))

    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
        if not user.enabled:
            frappe.throw(_("The selected user is disabled"))
    else:
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": employee.first_name or employee.employee_name,
                "send_welcome_email": 1,
                "user_type": "System User",
            }
        )
        user.insert()

    managed_roles = {role for roles in ASOUD_ROLE_TO_FRAPPE_ROLES.values() for role in roles}
    roles_to_remove = managed_roles - set(frappe_roles)
    if roles_to_remove:
        user.remove_roles(*sorted(roles_to_remove))
    user.add_roles(*frappe_roles)
    employee.user_id = user.name
    employee.create_user_permission = 1
    employee.save()

    profile.employee_roles = json.dumps(canonical_roles)
    profile.save()
    return success(
        {
            "user_id": user.name,
            "employee": employee.name,
            "company": employee.company,
            "personnel_roles": canonical_roles,
            "frappe_roles": frappe_roles,
        }
    )
