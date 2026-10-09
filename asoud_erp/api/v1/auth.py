import hashlib
import json

import frappe
from frappe import _
from frappe import sessions as frappe_sessions

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
    _ensure_data_scope(employee)

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


def _require_hr_manager(action: str = "manage employee access"):
    """«مدیر سیستم» or «مدیر منابع انسانی»; the company check follows in the caller."""
    from asoud_erp.services.erp_documents import require_roles

    try:
        require_roles({"System Manager", "HR Manager"})
    except frappe.PermissionError:
        frappe.throw(_("Only HR managers can {0}").format(action), frappe.PermissionError)


def _linked_user(employee) -> str:
    """The login of an Employee, refusing accounts that must stay under system admin."""
    user_id = employee.user_id
    if not user_id:
        return ""
    if user_id in {"Administrator", "Guest"}:
        frappe.throw("Protected account cannot be changed", frappe.PermissionError)
    if {"System Manager", "HR Manager"}.intersection(frappe.get_roles(user_id)):
        frappe.throw("Privileged accounts must be managed in system administration", frappe.PermissionError)
    return user_id


def _installed_modules() -> list[str]:
    return frappe.get_all(
        "Module Def",
        filters={"app_name": ("in", list(frappe.get_installed_apps()))},
        pluck="name",
    )


def _blocked_modules(user_id: str) -> list[str]:
    """Frappe's own module hiding: a Module Profile or the per-user block list."""
    blocked = set(frappe.get_all("Module Def", pluck="name") if not user_id else [])
    user = frappe.get_cached_doc("User", user_id) if user_id else None
    if not user:
        return sorted(blocked)
    return sorted({*blocked, *user.get_blocked_modules()})


def _frappe_roles(user_id: str) -> list[str]:
    return sorted(role for role in frappe.get_roles(user_id) if role not in {"All", "Guest"})


def _data_scope(user_id: str) -> list[dict]:
    """The native ``User Permission`` rows that limit what this login can see."""
    if not user_id:
        return []
    return [
        {"allow": row.allow, "value": row.for_value or "",
         "apply_to_all_doctypes": int(row.apply_to_all_doctypes or 0)}
        for row in frappe.get_all(
            "User Permission",
            filters={"user": user_id},
            fields=["allow", "for_value", "apply_to_all_doctypes"],
            order_by="allow asc, for_value asc",
            limit_page_length=0,
        )
    ]


def _ensure_data_scope(employee) -> None:
    """Mirror the Employee's Company and Department as native ``User Permission`` rows."""
    if not employee.user_id:
        return
    from frappe.permissions import add_user_permission

    for allow, value in (("Company", employee.company), ("Department", employee.department)):
        if not value:
            continue
        existing = frappe.db.get_value(
            "User Permission",
            {"user": employee.user_id, "allow": allow, "for_value": value},
            ["name", "applicable_for", "apply_to_all_doctypes"],
            as_dict=True,
        )
        if existing:
            if not existing.apply_to_all_doctypes and not existing.applicable_for:
                frappe.db.set_value("User Permission", existing.name, "apply_to_all_doctypes", 1)
            continue
        add_user_permission(allow, value, employee.user_id, ignore_permissions=True)
    frappe.cache.hdel("user_permissions", employee.user_id)


def _account_status(profile) -> dict:
    """«حساب کاربری» of a personnel profile, read from the native User record."""
    from asoud_erp.services.access_policy import access_level_for
    from asoud_erp.services.account_status import account_status, allowed_modules

    employee = frappe.db.get_value("Employee", profile.employee, ["name", "user_id"], as_dict=True)
    user_id = (employee and employee.user_id) or ""
    account = frappe.db.get_value("User", user_id, ["enabled", "last_login", "last_ip"], as_dict=True) if user_id else None
    roles = _frappe_roles(user_id)
    return account_status(
        user_id,
        enabled=account and account.enabled,
        last_login=account and account.last_login,
        last_ip=account and account.last_ip,
        roles=roles,
        modules=allowed_modules(_installed_modules(), _blocked_modules(user_id)),
        data_scope=_data_scope(user_id),
    ) | {
        "employee": employee and employee.name or "",
        "access_level": access_level_for(roles),
    }


@frappe.whitelist()
def get_account_status(party_profile: str) -> dict:
    """«فعال/غیرفعال کردن حساب»: the state of the linked login account."""
    profile = _access_profile(party_profile)
    return success(_account_status(profile))


@frappe.whitelist()
def get_login_history(party_profile: str, limit=None) -> dict:
    """«مشاهده سوابق ورود»: native Activity Log events plus the open sessions."""
    from asoud_erp.services.account_status import history_limit, login_history

    profile = _access_profile(party_profile)
    employee = frappe.db.get_value("Employee", profile.employee, ["name", "user_id"], as_dict=True)
    user_id = (employee and employee.user_id) or ""
    account = frappe.db.get_value("User", user_id, ["last_login", "last_ip"], as_dict=True) if user_id else None
    size = history_limit(limit)
    events = frappe.get_all(
        "Activity Log",
        filters={"user": user_id, "operation": ["in", ["Login", "Logout"]]},
        fields=["creation", "operation", "status", "ip_address"],
        order_by="creation desc",
        limit_page_length=size,
    ) if user_id else []
    sessions = frappe.db.sql(
        "select `lastupdate`, `status`, `ipaddress`, `sessiondata` from `tabSessions`"
        " where `user` = %s order by `lastupdate` desc limit %s",
        (user_id, size),
        as_dict=True,
    ) if user_id else []
    return success(login_history(account and account.last_login, account and account.last_ip, events, sessions))


@frappe.whitelist(methods=["POST"])
def set_account_enabled(party_profile: str, enabled, request_id: str) -> dict:
    """«فعال/غیرفعال کردن حساب»: Frappe's own ``User.enabled``, idempotent per request ID."""
    from asoud_erp.services.personnel_native import fingerprint

    _require_hr_manager("change an account")
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")
    target = 1 if frappe.utils.cint(enabled) else 0
    profile = _access_profile(party_profile)
    employee = frappe.get_doc("Employee", profile.employee)
    user_id = _linked_user(employee)
    if not user_id:
        frappe.throw(_("This personnel profile has no login account yet"))
    if user_id == frappe.session.user:
        frappe.throw("You cannot disable your own account", frappe.PermissionError)

    digest = fingerprint({"party": profile.name, "action": "account_enabled", "enabled": target})
    existing = frappe.db.get_value(
        "ASOUD Personnel Operation",
        {"request_id": request_id},
        ["name", "party", "action", "fingerprint"],
        as_dict=True,
        for_update=True,
    )
    if existing:
        if existing.party != profile.name or existing.action != "account_enabled" or existing.fingerprint != digest:
            frappe.throw("Request ID conflict")
        return success({"request_id": request_id, "replayed": True} | _account_status(profile))

    user = frappe.get_doc("User", user_id, for_update=True)
    user.enabled = target
    user.save(ignore_permissions=True)
    if not target:
        # Disabling an account must also end its open sessions.
        frappe_sessions.clear_sessions(user=user_id)
    frappe.get_doc({
        "doctype": "ASOUD Personnel Operation",
        "party": profile.name,
        "request_id": request_id,
        "action": "account_enabled",
        "fingerprint": digest,
    }).insert(ignore_permissions=True)
    return success({"request_id": request_id, "replayed": False} | _account_status(profile))


def _access_profile(name: str):
    _require_hr_manager()
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
    status = _account_status(profile)
    return success({
        "party_profile": profile.name,
        "employee": employee.name,
        "user_id": employee.user_id or "",
        "email": user.name if user else "",
        "enabled": bool(user.enabled) if user else False,
        "roles": json.loads(profile.employee_roles or "[]"),
        "access_matrix": matrix,
        "access_level": status["access_level"],
        "modules": status["modules"],
        "data_scope": status["data_scope"],
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
    from asoud_erp.services.account_status import can_resend_invitation, resend_blocked_message

    login = frappe.db.get_value("User", email.strip().lower(), "last_login")
    if frappe.db.exists("User", email.strip().lower()) and not can_resend_invitation(email.strip().lower(), login):
        # «ارسال مجدد دعوت» is only for a created account that never signed in.
        frappe.throw(resend_blocked_message(bool(login)))
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
