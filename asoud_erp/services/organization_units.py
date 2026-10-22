"""Native Department operations. No parallel unit or personnel store."""
import json

import frappe


def lock_company(company):
    frappe.db.sql("select name from tabCompany where name=%s for update", company)


def unit(name, company, permission="read"):
    doc = frappe.get_doc("Department", name)
    doc.check_permission(permission)
    if doc.company != company:
        frappe.throw("واحد متعلق به شرکت انتخاب‌شده نیست.", frappe.PermissionError)
    return doc


def validate_parent(name, parent, company):
    seen = {name} if name else set()
    while parent:
        if parent in seen:
            frappe.throw("ارتباط حلقوی بین واحدها مجاز نیست.")
        seen.add(parent)
        doc = frappe.get_doc("Department", parent)
        # ERPNext may have a global root without a company.
        if not doc.company:
            break
        doc.check_permission("read")
        if doc.company != company or doc.disabled:
            frappe.throw("واحد بالادستی باید فعال و متعلق به همین شرکت باشد.")
        parent = doc.parent_department


def references(name, company):
    chart = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "structure_json")
    title = frappe.db.get_value("Department", name, "department_name")
    return [r for r in json.loads(chart or "[]") if r.get("department_id") == name or (
        not r.get("department_id") and r.get("department") and r.get("department") == title)]


def validate_position_units(rows, company):
    for row in rows:
        if not row.get("department_id"):
            continue  # Never match legacy display text to a native unit by name.
        doc = unit(row["department_id"], company)
        if doc.disabled:
            frappe.throw("برای جایگاه، واحد فعال انتخاب کنید.")
        row["department"] = doc.department_name


def guard_department(doc, method=None):
    old = doc.get_doc_before_save()
    company = old.company if old else doc.company
    if not company:
        return
    renamed = bool(old and old.department_name != doc.department_name)
    moved_or_disabled = bool(old and (old.company != doc.company or doc.disabled))
    # Plain saves that keep the protected fields take no company lock.
    if method != "on_trash" and not (moved_or_disabled or renamed):
        return
    lock_company(company)
    linked = references(doc.name, company)
    if method == "on_trash" and linked:
        frappe.throw("واحد دارای جایگاه سازمانی است؛ حذف مجاز نیست.")
    if linked and moved_or_disabled:
        frappe.throw("واحد دارای جایگاه را نمی‌توان غیرفعال یا به شرکت دیگر منتقل کرد.")
    # Legacy rows match by display title only; renaming would orphan them silently.
    if renamed and any(not r.get("department_id") for r in linked):
        frappe.throw("واحد با جایگاه‌های قدیمی بدون شناسه مرتبط است؛ ابتدا جایگاه‌ها را در نمودار سازمانی به این واحد وصل کنید.")


def guard_rename(doc, method=None, *args, **kwargs):
    if doc.company:
        lock_company(doc.company)
    if doc.company and references(doc.name, doc.company):
        frappe.throw("شناسه واحد دارای جایگاه ثابت است؛ عنوان واحد را از فرم ویرایش تغییر دهید.")
