"""Assign / unassign ASOUD role definitions to accounts (site-wide or per office).

* ``scope = global`` definitions reuse the existing ``ASOUD Access Assignment`` mechanism
  (``user_access.attach_roles`` puts the definition's base roles on the User).
* ``scope = office`` definitions are stored as ``ASOUD Office Role Assignment`` rows and
  resolved by ``office_access`` - they are never written to ``User.roles``.

Every grant passes ``delegation.escalation_violation`` and is audited.
"""

import frappe

from asoud_erp.services import security_audit
from asoud_erp.services.delegation import (
    DELEGATE_ROLE,
    OFFICE_CREATOR_ROLE,
    escalation_violation,
)
from asoud_erp.services.office_access import office_roles
from asoud_erp.services.request_access import require_company
from asoud_erp.services.system_admin import SYSTEM_ADMIN_ROLE, is_system_admin, roles_of


def definition_info(code: str) -> dict:
    row = frappe.db.get_value("ASOUD Role Definition", code,
                              ["name", "title", "enabled", "scope", "role_profile"], as_dict=True)
    if not row:
        frappe.throw("نقش یافت نشد.", frappe.DoesNotExistError)
    if not row.enabled:
        frappe.throw("نقش غیرفعال است و قابل اختصاص نیست.")
    base = frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": row.role_profile},
                          pluck="role", limit_page_length=0)
    return {"code": row.name, "title": row.title, "scope": row.scope or "global",
            "profile": row.role_profile, "base_roles": sorted(set(base))}


def _target_user(user: str):
    if user in {"Administrator", "Guest"}:
        frappe.throw("تغییر نقش حساب سیستمی مجاز نیست.", frappe.PermissionError)
    row = frappe.db.get_value("User", user, ["name", "enabled", "user_type"], as_dict=True)
    if not row or row.user_type != "System User":
        frappe.throw("کاربر باید حساب داخلی سامانه داشته باشد.")
    return row


def precheck(code: str, company: str | None = None) -> dict:
    """Authorise a future grant before anything is written (used by multi-step flows)."""
    info = definition_info(code)
    if info["scope"] == "office" and (not company or not frappe.db.exists("Company", company)):
        frappe.throw("برای نقش دفتری، دفتر را مشخص کنید.")
    _gate(frappe.session.user, info, None, company if info["scope"] == "office" else None)
    return info


def _gate(actor: str, info: dict, user: str | None, company: str | None) -> None:
    if user is not None and actor == user:
        frappe.throw("اختصاص یا حذف نقش حساب خودتان مجاز نیست.", frappe.PermissionError)
    admin = is_system_admin(actor)
    held = set(roles_of(actor))
    if company:
        require_company(company)
    office_held = office_roles(actor, company) if (company and not admin) else None
    if office_held is not None:
        office_held = office_held | held
    message = escalation_violation(actor_is_admin=admin, actor_roles=held, granted_roles=info["base_roles"],
                                   actor_office_roles=office_held)
    if message:
        security_audit.record("role.assign", result="denied", actor=actor, target_type="User", target=user,
                              company=company or "", details={"role": info["code"], "reason": message},
                              commit=True)
        frappe.throw(message, frappe.PermissionError)


def assign(user: str, code: str, company: str | None = None) -> dict:
    from asoud_erp.api.v1 import user_access
    from asoud_erp.api.v1.role_management import _lock_definitions

    actor = frappe.session.user
    info = definition_info(code)
    _target_user(user)
    if info["scope"] == "office":
        if not company or not frappe.db.exists("Company", company):
            frappe.throw("برای نقش دفتری، دفتر را مشخص کنید.")
    elif company:
        frappe.throw("این نقش سراسری است و به دفتر مشخص وابسته نیست.")
    if SYSTEM_ADMIN_ROLE in info["base_roles"] and info["scope"] != "global":
        frappe.throw("نقش مدیر کل فقط می‌تواند سراسری باشد.")
    _gate(actor, info, user, company)
    _lock_definitions()
    frappe.db.sql("select name from tabUser where name=%s for update", (user,))

    if info["scope"] == "office":
        key = f"{user}|{company}|{code}"
        if frappe.db.exists("ASOUD Office Role Assignment", {"assignment_key": key}):
            created = False
        else:
            frappe.get_doc({"doctype": "ASOUD Office Role Assignment", "user": user, "company": company,
                            "role_definition": code, "granted_by": actor}).insert(ignore_permissions=True)
            created = True
    else:
        native = user_access._native(code, user)
        if not frappe.db.exists("Role", native):
            frappe.get_doc({"doctype": "Role", "role_name": native, "desk_access": 1}).insert(ignore_permissions=True)
        created = not frappe.db.exists("ASOUD Access Assignment", {"native_role": native})
        if created:
            frappe.get_doc({"doctype": "ASOUD Access Assignment", "user": user, "managed_role": code,
                            "native_role": native}).insert(ignore_permissions=True)
        frappe.get_doc("User", user).save(ignore_permissions=True)
        frappe.clear_cache(user=user)

    if created:
        security_audit.record("role.assign", target_type="User", target=user, company=company or "",
                              details={"role": code, "scope": info["scope"], "base_roles": info["base_roles"]})
        if SYSTEM_ADMIN_ROLE in info["base_roles"]:
            security_audit.record("admin.authority_transfer", target_type="User", target=user,
                                  details={"role": code})
        if OFFICE_CREATOR_ROLE in info["base_roles"]:
            security_audit.record("office.create_permission_grant", target_type="User", target=user,
                                  company=company or "", details={"role": code})
        if info["scope"] == "office":
            security_audit.record("role.scope_assigned", target_type="User", target=user, company=company,
                                  details={"role": code})
    return {"user": user, "role": code, "scope": info["scope"], "company": company, "assigned": True,
            "already_assigned": not created}


def unassign(user: str, code: str, company: str | None = None) -> dict:
    from asoud_erp.api.v1 import user_access
    from asoud_erp.api.v1.role_management import _lock_definitions

    actor = frappe.session.user
    info = frappe.db.get_value("ASOUD Role Definition", code, ["scope", "role_profile"], as_dict=True)
    if not info:
        frappe.throw("نقش یافت نشد.", frappe.DoesNotExistError)
    detail = definition_info_even_if_disabled(code)
    _target_user(user)
    _gate(actor, detail, user, company)
    _lock_definitions()
    frappe.db.sql("select name from tabUser where name=%s for update", (user,))
    removed = False
    if (info.scope or "global") == "office":
        name = frappe.db.get_value("ASOUD Office Role Assignment",
                                   {"user": user, "company": company, "role_definition": code}, "name")
        if name:
            frappe.delete_doc("ASOUD Office Role Assignment", name, ignore_permissions=True)
            removed = True
    else:
        native = user_access._native(code, user)
        name = frappe.db.get_value("ASOUD Access Assignment", {"native_role": native, "user": user}, "name")
        if name:
            frappe.delete_doc("ASOUD Access Assignment", name, ignore_permissions=True)
            removed = True
            _drop_orphan_base_roles(user, detail["base_roles"], native)
    if removed:
        security_audit.record("role.unassign", target_type="User", target=user, company=company or "",
                              details={"role": code, "scope": info.scope})
        if SYSTEM_ADMIN_ROLE in detail["base_roles"]:
            security_audit.record("admin.authority_transfer", target_type="User", target=user,
                                  details={"role": code, "direction": "revoked"})
    return {"user": user, "role": code, "company": company, "removed": removed}


def definition_info_even_if_disabled(code: str) -> dict:
    row = frappe.db.get_value("ASOUD Role Definition", code, ["role_profile"], as_dict=True)
    base = frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": row.role_profile},
                          pluck="role", limit_page_length=0)
    return {"code": code, "base_roles": sorted(set(base))}


def _drop_orphan_base_roles(user: str, base_roles: list[str], native: str) -> None:
    """Remove the base roles only this definition contributed, then re-save the User."""
    doc = frappe.get_doc("User", user)
    still = set()
    profile = doc.role_profile_name
    if profile:
        still |= set(frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": profile},
                                    pluck="role", limit_page_length=0))
    rest = frappe.get_all("ASOUD Access Assignment", filters={"user": user, "native_role": ["!=", native]},
                          fields=["managed_role"], limit_page_length=0)
    for row in rest:
        prof = frappe.db.get_value("ASOUD Role Definition", row.managed_role, "role_profile")
        still |= set(frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": prof},
                                    pluck="role", limit_page_length=0))
    drop = set(base_roles) - still - {"Employee"}
    doc.set("roles", [r for r in doc.roles if r.role not in drop and r.role != native])
    doc.save(ignore_permissions=True)
    frappe.clear_cache(user=user)


__all__ = ["assign", "unassign", "definition_info", "DELEGATE_ROLE"]
