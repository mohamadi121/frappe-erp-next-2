"""Post-login state: what the app needs, in one server-authoritative answer."""

import frappe

from asoud_erp.services import account_state, office_access, post_login
from asoud_erp.services.credential_policy import normalize_mobile
from asoud_erp.services.delegation import DELEGATE_ROLE, OFFICE_CREATOR_ROLE
from asoud_erp.services.request_access import company_access
from asoud_erp.services.system_admin import is_system_admin, roles_of


def saved_offices() -> list[dict]:
    return frappe.get_all("ASOUD Company Setup", filters={"office_saved": 1},
                          fields=["company", "office_type", "owner_full_name"], order_by="creation asc",
                          limit_page_length=0)


def first_office_exists() -> bool:
    return bool(frappe.db.exists("ASOUD Company Setup", {"office_saved": 1}))


def admin_profile_complete(user: str) -> bool:
    row = frappe.db.get_value("User", user, ["first_name", "last_name", "mobile_no"], as_dict=True)
    if not row or not (row.first_name or "").strip() or not (row.last_name or "").strip():
        return False
    try:
        return bool(normalize_mobile(row.mobile_no))
    except ValueError:
        return False


def accessible_offices(user: str, admin: bool) -> list[dict]:
    """Offices the account may enter, with the effective roles it holds in each."""
    global_roles = set(roles_of(user))
    per_office = office_access.office_role_map(user)
    offices = []
    for office in saved_offices():
        company = office["company"]
        if not (admin or company_access(company, user)):
            continue
        offices.append({
            "id": company, "title": company, "office_type": office.office_type,
            "roles": sorted(global_roles | set(per_office.get(company, ()))),
            "office_roles": sorted(per_office.get(company, ())),
        })
    return offices


def build(user: str | None = None) -> dict:
    user = user or frappe.session.user
    row = frappe.db.get_value("User", user, ["enabled", "user_type", "full_name", "first_name", "last_name",
                                             "mobile_no", "email"], as_dict=True)
    active = bool(row and row.enabled)
    admin = bool(active and is_system_admin(user))
    roles = roles_of(user)
    state = account_state.get(user)
    expired = account_state.temp_password_expired(user)
    must_change = bool(state.get("must_change_password"))
    offices = accessible_offices(user, admin) if active else []
    selected = frappe.defaults.get_user_default("company", user=user) if active else None
    exists = first_office_exists()
    complete = admin_profile_complete(user) if admin else True
    nxt = post_login.resolve_next_route(
        active=active, must_change_password=must_change or expired, is_system_admin=admin,
        first_office_exists=exists, admin_profile_complete=complete,
        office_ids=[o["id"] for o in offices], selected_office=selected)
    held = set(roles)
    return {
        "user": {"id": user, "full_name": (row and row.full_name) or "", "first_name": (row and row.first_name) or "",
                 "last_name": (row and row.last_name) or "", "mobile": (row and row.mobile_no) or "",
                 "email": (row and row.email) or ""},
        "account": {"active": active, "must_change_password": must_change or expired,
                    "temporary_password_expired": expired},
        "roles": roles,
        "is_system_admin": admin,
        "role_title": "مدیر کل سیستم" if admin else "",
        "scope": "global" if admin else "office",
        "capabilities": {
            "create_office": admin or OFFICE_CREATOR_ROLE in held,
            "manage_roles": admin,
            "delegate_roles": admin or DELEGATE_ROLE in held,
            "register_personnel": admin or bool(held & {"HR Manager", "HR User"}),
        },
        "offices": offices,
        "selected_office": nxt["office"] or (selected if selected in {o["id"] for o in offices} else None),
        "first_office_exists": exists,
        "admin_profile_complete": complete,
        "verification": {"mobile_verified": bool(state.get("mobile_verified")),
                         "email_verified": bool(state.get("email_verified"))},
        "next": nxt,
    }
