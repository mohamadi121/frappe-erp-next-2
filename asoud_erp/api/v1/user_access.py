"""Bounded native permission editor; grants are additive, never a second ACL."""
import hashlib
import json

import frappe
from frappe.utils import cint

from asoud_erp.api.v1.responses import success
from asoud_erp.api.v1.role_management import _access, _object
from asoud_erp.services.permission_catalog import (
    ADVANCED_ONLY,
    MEDIUM_ACTIONS,
    catalog_rows,
)

ACTIONS = MEDIUM_ACTIONS  # the legacy matrix; advanced extras travel in the *_advanced keys


def _native(code, user=""):
    digest = hashlib.sha256(json.dumps([code, user]).encode()).hexdigest()[:32]
    return f"ASOUD-ACCESS-{'USER' if user else 'ROLE'}-{digest}"


def _definition(code):
    doc = frappe.get_doc("ASOUD Role Definition", code)
    if doc.get('template_key'):
        frappe.throw('پروفایل دفتر را از بخش پروفایل‌های دسترسی بررسی کنید.', frappe.PermissionError)
    if not doc.enabled:
        frappe.throw("نقش غیرفعال است.")
    return doc


def _user(name):
    if name in {"Administrator", "Guest", frappe.session.user}:
        frappe.throw("تغییر حساب سیستمی یا حساب خودتان در این صفحه مجاز نیست.")
    doc = frappe.get_doc("User", name)
    if doc.user_type != "System User":
        frappe.throw("کاربر باید حساب داخلی سامانه داشته باشد.")
    return doc


def _catalog():
    return catalog_rows(lambda dt: bool(frappe.db.exists("DocType", dt)),
                        lambda dt: bool(frappe.get_meta(dt).is_submittable))


def _grants(role, catalog, actions=ACTIONS):
    return {row["doctype"]: sorted({action for perm in frappe.get_meta(row["doctype"]).permissions
            if perm.role == role and not cint(perm.permlevel) and not cint(perm.if_owner)
            for action in actions if perm.get(action)}) for row in catalog}


def _snapshot(code, user=""):
    definition = _definition(code)
    catalog = _catalog()
    owned = _native(code, user)
    subject = _user(user) if user else None
    profile = frappe.get_doc("Role Profile", definition.role_profile)
    if any(not frappe.db.exists("Role", {"name": row.role, "disabled": 0}) for row in profile.roles):
        frappe.throw("یکی از نقش‌های پایه غیرفعال یا حذف شده است؛ ابتدا نقش را اصلاح کنید.")
    inherited_roles = set(row.role for row in profile.roles)
    if subject:
        inherited_roles.update(frappe.get_roles(user))
        inherited_roles.add(_native(code))
    inherited_roles.discard(owned)
    inherited, inherited_advanced = {}, {}
    for row in catalog:
        perms = frappe.get_meta(row["doctype"]).permissions
        inherited[row["doctype"]] = sorted({a for p in perms
            if p.role in inherited_roles and not cint(p.permlevel) for a in ACTIONS if p.get(a)})
        inherited_advanced[row["doctype"]] = sorted({a for p in perms
            if p.role in inherited_roles and not cint(p.permlevel) for a in ADVANCED_ONLY if p.get(a)})
    grants = _grants(owned, catalog)
    advanced = _grants(owned, catalog, ADVANCED_ONLY)
    stamp = [str(definition.modified), str(profile.modified), str(subject.modified) if subject else "", grants,
             advanced, inherited, inherited_advanced]
    token = hashlib.sha256(json.dumps(stamp, sort_keys=True).encode()).hexdigest()
    return {"catalog": catalog, "grants": grants, "advanced_grants": advanced, "inherited": inherited,
            "inherited_advanced": inherited_advanced, "token": token,
            "levels": ["simple", "medium", "advanced"],
            "base_roles": sorted(row.role for row in profile.roles)}


@frappe.whitelist()
def directory(code, search="", candidates=0):
    _access()
    definition = _definition(code)
    excluded = {"Administrator", "Guest", frappe.session.user}
    filters = {"user_type": "System User", "name": ["not in", sorted(excluded)]}
    if not cint(candidates):
        assigned = set(frappe.get_all("ASOUD Access Assignment", filters={"managed_role": code}, pluck="user"))
        assigned.update(frappe.get_all("User", filters={"role_profile_name": definition.role_profile}, pluck="name"))
        assigned -= excluded
        if not assigned:
            return success([])
        filters["name"] = ["in", sorted(assigned)]
    text = str(search or "").strip()[:100]
    rows = frappe.get_all("User", filters=filters,
        or_filters={"full_name": ["like", f"%{text}%"], "mobile_no": ["like", f"%{text}%"], "name": ["like", f"%{text}%"]} if text else None,
        fields=["name", "full_name", "first_name", "last_name", "mobile_no", "enabled", "modified"],
        order_by="full_name asc", limit_page_length=100)
    return success(rows)


@frappe.whitelist()
def editor(code, user=""):
    _access()
    return success(_snapshot(code, user))


@frappe.whitelist(methods=["POST"])
def apply(payload):
    _access()
    # Old global grants remain readable; no new grant may guess its office.
    frappe.throw('این مسیر مجوز سراسری می‌سازد؛ دفتر و پرونده را از تب دسترسی‌های حساب مشخص کنید.')


def attach_roles(doc, method=None):
    """Run after native User.validate repopulates its Role Profile roles."""
    if not frappe.db.exists("DocType", "ASOUD Access Assignment"):
        return
    doc.set("roles", [r for r in doc.roles if not r.role.startswith(("ASOUD-ACCESS-", "ASOUD-OFFICE-"))])
    codes = set(frappe.get_all("ASOUD Role Definition", filters={"role_profile": doc.role_profile_name}, pluck="name")) if doc.role_profile_name else set()
    assignments = frappe.get_all("ASOUD Access Assignment", filters={"user": doc.name}, fields=["managed_role", "native_role", "company"])
    scoped = [row for row in assignments if row.company]
    assignments = [row for row in assignments if not row.company]
    for row in scoped:
        doc.append_roles(row.native_role)
    codes.update(row.managed_role for row in assignments)
    for code in codes:
        definition = frappe.get_doc("ASOUD Role Definition", code)
        if not definition.enabled:
            continue
        profile = frappe.get_doc("Role Profile", definition.role_profile)
        doc.append_roles(*[r.role for r in profile.roles
                           if frappe.db.exists("Role", {"name": r.role, "disabled": 0})])
        for native in [_native(code), *[r.native_role for r in assignments if r.managed_role == code]]:
            if frappe.db.exists("Role", {"name": native, "disabled": 0}):
                doc.append_roles(native)


@frappe.whitelist(methods=["POST"])
def update_user(payload):
    _access()
    data = _object(payload)
    doc = _user(str(data.get("user") or ""))
    if str(doc.modified) != data.get("modified"):
        frappe.throw("کاربر تغییر کرده؛ اطلاعات را بازخوانی کنید.", frappe.TimestampMismatchError)
    first = str(data.get("first_name") or "").strip()
    last = str(data.get("last_name") or "").strip()
    mobile = str(data.get("mobile_no") or "").strip()
    if not first or max(len(first), len(last), len(mobile)) > 140:
        frappe.throw("نام و اطلاعات کاربر معتبر نیست.")
    if data.get("enabled") not in (0, 1):
        frappe.throw("وضعیت کاربر معتبر نیست.")
    doc.update({"first_name": first, "last_name": last, "mobile_no": mobile, "enabled": data["enabled"]})
    doc.save()
    return success({"saved": True})
