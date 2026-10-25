"""Native Role Profile administration with ASOUD presentation metadata.

No API here assigns roles to users or changes a standard Role/DocPerm.
All definitions are site-wide, like Frappe Role Profiles, not company grants.
"""
import re

import frappe
from frappe.utils import cint

from asoud_erp.api.v1.responses import success
from asoud_erp.services import security_audit
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.role_templates import BASE_ROLES, CATEGORIES, TEMPLATES


def _read_access():
    require_roles(("System Manager", "HR Manager"))


def _access():
    require_roles("System Manager")


def _lock_definitions():
    # Serialize parent graph edits and template creation without changing native data.
    frappe.db.sql("select name from tabRole where name=%s for update", ("System Manager",))


def _object(payload):
    value = frappe.parse_json(payload) if isinstance(payload, str) else payload
    if not isinstance(value, dict):
        frappe.throw("اطلاعات نقش معتبر نیست.")
    return value


def _code(value):
    code = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,39}", code):
        frappe.throw("کد باید ۲ تا ۴۰ حرف انگلیسی، عدد، خط تیره یا زیرخط باشد و با حرف شروع شود.")
    return code


def _base_roles(values, allow_empty=False):
    if allow_empty and values == []:
        return []
    if not isinstance(values, list) or not values or len(values) > len(BASE_ROLES):
        frappe.throw("حداقل یک نقش پایه معتبر انتخاب کنید.")
    if any(not isinstance(role, str) or role not in BASE_ROLES for role in values):
        frappe.throw("نقش پایه خارج از فهرست مجاز است.")
    roles = sorted(set(values))
    for role in roles:
        if not frappe.db.exists("Role", {"name": role, "disabled": 0}):
            frappe.throw(f"نقش پایه فعال در سرور یافت نشد: {role}")
    return roles


def _row(doc):
    profile = frappe.get_doc("Role Profile", doc.role_profile)
    assigned = set(frappe.get_all("User", filters={"role_profile_name": profile.name}, pluck="name"))
    if frappe.db.exists("DocType", "ASOUD Access Assignment"):
        assigned.update(frappe.get_all("ASOUD Access Assignment", filters={"managed_role": doc.name}, pluck="user"))
    return {
        "code": doc.role_code, "title": doc.title, "category": doc.category,
        "parent": doc.parent_role or "", "description": doc.description or "",
        "enabled": bool(doc.enabled), "profile": profile.name,
        "base_roles": sorted(row.role for row in profile.roles),
        "modified": str(doc.modified), "profile_modified": str(profile.modified),
        "assigned_users": len(assigned), "scope": doc.scope or "global", "system": bool(doc.is_system),
    }


@frappe.whitelist()
def catalog():
    _read_access()
    installed = set(frappe.get_all("Role", filters={"disabled": 0}, pluck="name"))
    roles = [_row(frappe.get_doc("ASOUD Role Definition", name))
             for name in frappe.get_all("ASOUD Role Definition", pluck="name", order_by="title asc")]
    return success({
        "system_roles": [system_admin_row()],
        "categories": [{"code": row.name, "title": row.title, "style": row.style}
                       for row in frappe.get_all("ASOUD Role Category",
                           fields=["name", "title", "style"], order_by="creation asc")],
        "roles": roles,
        "base_roles": [{"name": name, "title": label, "description": description,
                        "available": name in installed}
                       for name, (label, description) in BASE_ROLES.items()],
        "templates": [{"code": code, "title": title, "category": category,
                       "base_roles": base, "available": all(role in installed for role in base),
                       "exists": any(role["code"] == code for role in roles)}
                      for code, title, category, base in TEMPLATES],
        "template_categories": CATEGORIES,
    })


def system_admin_row():
    from asoud_erp.services.system_admin import SYSTEM_ADMIN_ROLE, active_named_admins

    return {"code": "SYSTEM_ADMIN", "native_role": SYSTEM_ADMIN_ROLE, "title": "مدیر کل سیستم",
            "scope": "global", "scope_title": "سراسری", "system": True, "editable": False,
            "description": "نقش سیستمی با دسترسی کامل در همین استقرار؛ فهرست مجوزها از "
                           "system_admin_permissions خوانده می‌شود.",
            "holders": active_named_admins()}


@frappe.whitelist()
def system_admin_permissions():
    """«مدیر کل سیستم» with scope «سراسری» and its full permission list, derived from the real
    permissions: every DocType right of ``System Manager`` (so a module added tomorrow appears
    automatically) plus the ASOUD capabilities, each with the server gate that enforces it."""
    from asoud_erp.services.permission_catalog import capabilities_for

    _read_access()
    rights = ("read", "write", "create", "delete", "submit", "cancel", "amend",
              "report", "export", "import", "print", "email", "share")
    by_doctype: dict[str, set[str]] = {}
    for table in ("DocPerm", "Custom DocPerm"):
        for perm in frappe.get_all(table, filters={"role": "System Manager", "permlevel": 0},
                                   fields=["parent", *rights], limit_page_length=0):
            by_doctype.setdefault(perm.parent, set()).update(r for r in rights if perm.get(r))
    documents = [{"doctype": dt, "actions": sorted(actions)} for dt, actions in sorted(by_doctype.items())
                 if actions]
    return success({**system_admin_row(), "capabilities": capabilities_for([], True),
                    "document_permissions": documents, "document_permission_count": len(documents)})


@frappe.whitelist(methods=["POST"])
def create_category(payload):
    _access()
    _lock_definitions()
    data = _object(payload)
    code = _code(data.get("code"))
    if frappe.db.exists("ASOUD Role Category", code):
        frappe.throw("کد دسته قبلاً ثبت شده است.")
    title = str(data.get("title") or "").strip()
    style = data.get("style", "system")
    if not title or len(title) > 140 or style not in {row["style"] for row in CATEGORIES}:
        frappe.throw("عنوان یا سبک دسته معتبر نیست.")
    doc = frappe.get_doc({"doctype": "ASOUD Role Category", "category_code": code,
                          "title": title, "style": style}).insert()
    security_audit.record("role.category_create", target_type="ASOUD Role Category", target=doc.name)
    return success({"code": doc.name, "title": doc.title, "style": doc.style})


def _save(data):
    code = _code(data.get("code"))
    title = str(data.get("title") or "").strip()
    if not title or len(title) > 140:
        frappe.throw("نام نقش الزامی است و حداکثر ۱۴۰ نویسه دارد.")
    description = str(data.get("description") or "").strip()
    if len(description) > 2000:
        frappe.throw("توضیحات حداکثر ۲۰۰۰ نویسه دارد.")
    category = str(data.get("category") or "")
    if not frappe.db.exists("ASOUD Role Category", category):
        frappe.throw("دسته نقش را انتخاب کنید.")
    parent = str(data.get("parent") or "")
    if parent and not frappe.db.exists("ASOUD Role Definition", parent):
        frappe.throw("نقش والد یافت نشد.")
    scope = str(data.get("scope") or "global")
    if scope not in ("global", "office"):
        frappe.throw("محدوده نقش باید سراسری یا دفتری باشد.")
    profile_name = f"ASOUD:{code}"
    exists = frappe.db.exists("ASOUD Role Definition", code)
    if exists:
        doc = frappe.get_doc("ASOUD Role Definition", code)
        profile = frappe.get_doc("Role Profile", doc.role_profile)
        if (str(doc.modified) != data.get("modified") or
                str(profile.modified) != data.get("profile_modified")):
            frappe.throw("نقش تغییر کرده است؛ فهرست را بازخوانی کنید.", frappe.TimestampMismatchError)
    else:
        if data.get("modified") or frappe.db.exists("Role Profile", profile_name):
            frappe.throw("کد یا پروفایل نقش با اطلاعات موجود تداخل دارد.")
        doc = frappe.new_doc("ASOUD Role Definition")
        doc.role_code = code
        profile = frappe.new_doc("Role Profile")
        profile.role_profile = profile_name
    current_roles = sorted(row.role for row in (profile.roles or []))
    requested_roles = data.get("base_roles")
    # Metadata-only edits preserve even roles later disabled in native Frappe.
    unchanged = exists and isinstance(requested_roles, list) and requested_roles == current_roles
    if not unchanged:
        if exists and frappe.db.exists("DocType", "ASOUD Access Assignment") and frappe.db.exists(
            "ASOUD Access Assignment", {"managed_role": doc.name}
        ):
            frappe.throw("این نقش تخصیص شخصی دارد؛ برای تغییر مجوزهای مشترک از دسترسی‌های این نقش استفاده کنید. تغییر نقش‌های پایه نیازمند بازبینی تخصیص‌ها در مدیریت بومی است.")
        roles = _base_roles(requested_roles, allow_empty=True)
        profile.set("roles", [{"role": role} for role in roles])
        # Empty manual profiles grant no access. Existing permissions are not inferred.
        profile.save()
    final_roles = sorted(row.role for row in profile.roles)
    if "System Manager" in final_roles and scope != "global":
        frappe.throw("نقشی که شامل مدیر کل سیستم است فقط می‌تواند سراسری باشد.")
    before_roles = current_roles if exists else []
    doc.update({"title": title, "category": category, "parent_role": parent or None,
                "description": description, "enabled": cint(data.get("enabled", 1)),
                "role_profile": profile.name, "scope": scope,
                "is_system": 1 if "System Manager" in final_roles else 0})
    doc.save()
    security_audit.record("role.update" if exists else "role.create", target_type="ASOUD Role Definition",
                          target=doc.name, details={"scope": scope, "base_roles": final_roles})
    if final_roles != before_roles:
        security_audit.record("role.permission_change", target_type="ASOUD Role Definition", target=doc.name,
                              details={"added": sorted(set(final_roles) - set(before_roles)),
                                       "removed": sorted(set(before_roles) - set(final_roles))})
    return _row(doc)


@frappe.whitelist(methods=["POST"])
def save_role(payload):
    _access()
    _lock_definitions()
    frappe.db.savepoint("asoud_role_save")
    try:
        result = _save(_object(payload))
    except Exception:
        frappe.db.rollback(save_point="asoud_role_save")
        raise
    return success(result)


@frappe.whitelist(methods=["POST"])
def apply_templates(codes):
    _access()
    _lock_definitions()
    codes = frappe.parse_json(codes) if isinstance(codes, str) else codes
    templates = {row[0]: row for row in TEMPLATES}
    if not isinstance(codes, list) or not codes or any(not isinstance(c, str) or c not in templates for c in codes):
        frappe.throw("الگوهای انتخاب‌شده معتبر نیستند.")
    frappe.db.savepoint("asoud_role_templates")
    created, skipped = [], []
    try:
        for code in dict.fromkeys(codes):
            if frappe.db.exists("ASOUD Role Definition", code):
                skipped.append(code)
                continue
            _, title, category, base = templates[code]
            _base_roles(base)
            if not frappe.db.exists("ASOUD Role Category", category):
                category_data = next(row for row in CATEGORIES if row["code"] == category)
                frappe.get_doc({"doctype": "ASOUD Role Category", "category_code": category,
                                "title": category_data["title"], "style": category_data["style"]}).insert()
            _save({"code": code, "title": title, "category": category, "base_roles": base,
                   "description": "الگوی استاندارد؛ دسترسی‌ها مطابق نقش‌های پایه نصب‌شده سرور است."})
            created.append(code)
    except Exception:
        frappe.db.rollback(save_point="asoud_role_templates")
        raise
    return success({"created": created, "skipped": skipped})


@frappe.whitelist()
def permission_preview(roles):
    _read_access()
    roles = _base_roles(frappe.parse_json(roles) if isinstance(roles, str) else roles)
    parents = set()
    for table in ("DocPerm", "Custom DocPerm"):
        parents.update(frappe.get_all(table, filters={"role": ["in", roles]}, pluck="parent"))
    rights = ("read", "write", "create", "delete", "submit", "cancel", "amend",
              "report", "export", "import", "print", "email", "share", "select")
    rows = []
    for doctype in sorted(parents):
        # get_meta applies Custom DocPerm overrides; do not union stale defaults.
        for perm in frappe.get_meta(doctype).permissions:
            if perm.role in roles:
                rows.append({"doctype": doctype, "role": perm.role,
                             "level": cint(perm.permlevel), "owner_only": bool(perm.if_owner),
                             "actions": [right for right in rights if perm.get(right)]})
    return success(rows)
