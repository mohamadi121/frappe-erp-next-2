"""Bounded native permission editor; grants are additive, never a second ACL."""
import hashlib
import json

import frappe
from frappe.permissions import add_permission, update_permission_property
from frappe.utils import cint

from asoud_erp.api.v1.responses import success
from asoud_erp.api.v1.role_management import _access, _lock_definitions, _object

ACTIONS = ("read", "create", "write", "delete")
MODULES = {
    "حسابداری": (("Journal Entry", "سند حسابداری"), ("Payment Entry", "دریافت و پرداخت"), ("Account", "حساب‌ها")),
    "اشخاص و شرکت‌ها": (("Customer", "مشتریان"), ("Supplier", "تأمین‌کنندگان"), ("Contact", "مخاطبان")),
    "کالا و انبار": (("Item", "کالاها"), ("Warehouse", "انبارها"), ("Stock Entry", "ورود و خروج انبار")),
    "خرید": (("Material Request", "درخواست کالا"), ("Purchase Order", "سفارش خرید"), ("Purchase Invoice", "فاکتور خرید")),
    "فروش": (("Quotation", "پیش‌فاکتور"), ("Sales Order", "سفارش فروش"), ("Sales Invoice", "فاکتور فروش")),
    "تنظیمات": (("System Settings", "تنظیمات سامانه"),),
    "مدیریت کاربران": (("User", "کاربران"),),
}


def _native(code, user=""):
    digest = hashlib.sha256(json.dumps([code, user]).encode()).hexdigest()[:32]
    return f"ASOUD-ACCESS-{'USER' if user else 'ROLE'}-{digest}"


def _definition(code):
    doc = frappe.get_doc("ASOUD Role Definition", code)
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
    return [{"module": module, "doctype": dt, "title": title,
             "actions": ["read"] if dt in {"User", "System Settings"} else list(ACTIONS)}
            for module, rows in MODULES.items() for dt, title in rows
            if frappe.db.exists("DocType", dt)]


def _grants(role, catalog):
    return {row["doctype"]: sorted({action for perm in frappe.get_meta(row["doctype"]).permissions
            if perm.role == role and not cint(perm.permlevel) and not cint(perm.if_owner)
            for action in ACTIONS if perm.get(action)}) for row in catalog}


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
    inherited = {}
    for row in catalog:
        inherited[row["doctype"]] = sorted({a for p in frappe.get_meta(row["doctype"]).permissions
            if p.role in inherited_roles and not cint(p.permlevel) for a in ACTIONS if p.get(a)})
    grants = _grants(owned, catalog)
    stamp = [str(definition.modified), str(profile.modified), str(subject.modified) if subject else "", grants, inherited]
    token = hashlib.sha256(json.dumps(stamp, sort_keys=True).encode()).hexdigest()
    return {"catalog": catalog, "grants": grants, "inherited": inherited, "token": token,
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
    _lock_definitions()
    data = _object(payload)
    code, user = str(data.get("code") or ""), str(data.get("user") or "")
    if user:
        frappe.db.sql("select name from tabUser where name=%s for update", (user,))
    before = _snapshot(code, user)
    if data.get("token") != before["token"]:
        frappe.throw("اطلاعات دسترسی تغییر کرده؛ صفحه را بازخوانی کنید.", frappe.TimestampMismatchError)
    grants = data.get("grants")
    allowed = {row["doctype"]: set(row["actions"]) for row in before["catalog"]}
    if not isinstance(grants, dict) or set(grants) != set(allowed):
        frappe.throw("ماتریس دسترسی کامل و معتبر نیست.")
    for dt, values in grants.items():
        if not isinstance(values, list) or any(not isinstance(a, str) or a not in allowed[dt] for a in values):
            frappe.throw("عملیات دسترسی مجاز نیست.")
        if values and "read" not in values:
            frappe.throw("ایجاد، ویرایش و حذف نیازمند مشاهده هستند.")
    role = _native(code, user)
    if not frappe.db.exists("Role", role):
        frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
    for dt, values in grants.items():
        exists = frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role, "permlevel": 0, "if_owner": 0})
        if not values and not exists:
            continue
        if not exists:
            add_permission(dt, role)
        for action in ACTIONS:
            update_permission_property(dt, role, 0, action, int(action in values), validate=False)
        from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
        validate_permissions_for_doctype(dt)
        frappe.clear_cache(doctype=dt)
    if user:
        if not frappe.db.exists("ASOUD Access Assignment", {"native_role": role}):
            frappe.get_doc({"doctype": "ASOUD Access Assignment", "user": user,
                "managed_role": code, "native_role": role}).insert(ignore_permissions=True)
        affected = {user}
    else:
        profile = _definition(code).role_profile
        affected = set(frappe.get_all("User", filters={"role_profile_name": profile}, pluck="name"))
        affected.update(frappe.get_all("ASOUD Access Assignment", filters={"managed_role": code}, pluck="user"))
    for name in sorted(affected):
        frappe.get_doc("User", name).save()
        frappe.clear_cache(user=name)
    _definition(code).add_comment("Info", text=f"Access settings updated by {frappe.session.user}; scope: {user or 'role'}")
    return success({"applied": True, "affected_users": len(affected)})


def attach_roles(doc, method=None):
    """Run after native User.validate repopulates its Role Profile roles."""
    if not frappe.db.exists("DocType", "ASOUD Access Assignment"):
        return
    doc.set("roles", [r for r in doc.roles if not r.role.startswith("ASOUD-ACCESS-")])
    codes = set(frappe.get_all("ASOUD Role Definition", filters={"role_profile": doc.role_profile_name}, pluck="name")) if doc.role_profile_name else set()
    assignments = frappe.get_all("ASOUD Access Assignment", filters={"user": doc.name}, fields=["managed_role", "native_role"])
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
