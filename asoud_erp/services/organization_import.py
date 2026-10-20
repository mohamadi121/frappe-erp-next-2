"""Extend the existing chart import with native Departments, in one transaction."""
import json

import frappe
from erpnext.setup.doctype.department.department import get_abbreviated_name

from asoud_erp.services.organization_contract import validate_rows
from asoud_erp.services.organization_employees import normalize_assignments
from asoud_erp.services.organization_units import unit, validate_parent


def plan(company, payload, current):
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict) or not isinstance(data.get("units"), list):
        frappe.throw("ساختار فایل ورود معتبر نیست.")
    if data.get("template") and current:
        frappe.throw("ساختار موجود است؛ قالب جدید روی آن اعمال نمی‌شود.")
    normalized = validate_rows(data["units"])
    sources = {str(r.get("code", "")).strip(): r for r in data["units"]}
    names, units, pending = {}, [], list(normalized)
    while pending:
        ready = [r for r in pending if not r["parent"] or r["parent"] in names]
        if not ready:
            frappe.throw("حلقه یا مرجع نامعتبر در واحدها وجود دارد.")
        for row in ready:
            source = sources[row["code"]]
            explicit = str(source.get("name") or "").strip()
            parent = names.get(row["parent"], "") or str(source.get("parent_id") or "").strip()
            if explicit:
                doc = unit(explicit, company)
                if doc.disabled:
                    frappe.throw("واحد تطبیق‌یافته غیرفعال است.")
                if parent and doc.parent_department != parent:
                    frappe.throw("ورود فایل اجازه جابه‌جایی واحد موجود را ندارد.")
                name, title = doc.name, doc.department_name
            else:
                frappe.has_permission("Department", "create", throw=True)
                name, title = get_abbreviated_name(row["title"], company), row["title"]
                if name in names.values() or frappe.db.exists("Department", name):
                    frappe.throw("واحد تکراری است؛ برای تطبیق، شناسه واقعی را در ستون name وارد کنید.")
                if parent and frappe.db.exists("Department", parent):
                    parent_doc = unit(parent, company)
                    validate_parent(None, parent, company)
                    if not parent_doc.is_group:
                        frappe.throw("واحد بالادستی باید پذیرش زیرواحد داشته باشد.")
            names[row["code"]] = name
            units.append(dict(code=row["code"], name=name, title=title, parent=parent,
                action="match" if explicit else "create"))
            pending.remove(row)
    if not isinstance(data.get("rows"), list):
        frappe.throw("فهرست جایگاه‌های فایل معتبر نیست.")
    additions = validate_rows([*current, *data["rows"]])[len(current):]
    titles = {r["name"]: r["title"] for r in units}
    for row in additions:
        reference = row.get("department_id", "")
        if reference in names:
            row["department_id"] = names[reference]
            row["department"] = titles[names[reference]]
        elif reference:
            doc = unit(reference, company)
            if doc.disabled:
                frappe.throw("واحد جایگاه غیرفعال است.")
            row["department"] = doc.department_name
    rows = validate_rows([*current, *additions])
    rows = normalize_assignments(rows, company)
    return dict(units=units, rows=rows, additions=additions)


def apply_units(units, company):
    for row in units:
        if row["action"] == "match":
            continue
        doc = frappe.get_doc(dict(doctype="Department", company=company,
            department_name=row["title"], parent_department=row["parent"] or None, is_group=1))
        doc.insert()
        if doc.name != row["name"]:
            frappe.throw("نام‌گذاری سفارشی واحد با پیش‌نمایش متفاوت است؛ ورود متوقف شد.")
