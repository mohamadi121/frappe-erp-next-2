"""Read, template and issuance APIs for the hiring-order document lifecycle."""

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.hiring_orders import (
    MISSING_MESSAGE,
    default_template,
    format_hiring_order_print,
    normalize_search,
    snapshot_payroll,
    validate_template,
)
from asoud_erp.services.jalali import gregorian_to_jalali
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import paging

TEMPLATE_DESIGNERS = ("System Manager", "HR Manager")
HR_OPERATIONAL_ROLES = ("System Manager", "HR Manager", "HR User")
PAYROLL_ROLES = ("System Manager", "Payroll Manager", "Accounts Manager")


def _require_template_designer(company: str) -> None:
    try:
        erp_documents.require_roles(TEMPLATE_DESIGNERS, company)
    except frappe.PermissionError:
        frappe.throw(_("شما اجازهٔ ویرایش یا انتشار قالب حکم استخدام را ندارید."), frappe.PermissionError)


def _require_hr_issuer(company: str) -> None:
    try:
        erp_documents.require_roles(HR_OPERATIONAL_ROLES, company)
    except frappe.PermissionError:
        frappe.throw(_("شما اجازهٔ صدور یا مدیریت احکام استخدام را ندارید."), frappe.PermissionError)


def _template_form_name(company: str) -> str | None:
    return frappe.db.get_value("ASOUD Form", {"company": company, "module_key": "hiring_order"}, "name")


def _format_jalali(d: Any) -> str:
    if not d:
        return ""
    try:
        dt = getdate(d)
        y, m, day = gregorian_to_jalali(dt)
        return f"{y:04d}/{m:02d}/{day:02d}"
    except Exception:
        return str(d)


def _letterhead(company: str) -> str | None:
    import base64

    name = frappe.db.get_value("Company", company, "default_letter_head")
    head = (
        frappe.db.get_value(
            "Letter Head",
            name,
            ["disabled", "source", "content", "image"],
            as_dict=True,
        )
        if name
        else None
    )
    if not head or head.disabled:
        return None
    if head.source == "Image" and head.image:
        file_name = frappe.db.get_value("File", {"file_url": head.image}, "name")
        if file_name:
            data = frappe.get_doc("File", file_name).get_content()
            data = data.encode() if isinstance(data, str) else data
            return (
                '<img style="max-height:80px" src="data:image/png;base64,'
                + base64.b64encode(data).decode()
                + '">'
            )
    return head.content or None


@frappe.whitelist()
def get_hiring_order_template(company: str) -> dict:
    _require_hr_issuer(company)
    require_company(company)
    name = _template_form_name(company)
    if not name or not frappe.db.exists("ASOUD Form", name):
        return success({"template": None})
    doc = frappe.get_doc("ASOUD Form", name)
    if not doc.active_revision:
        return success({"template": None})
    rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
    schema = json.loads(rev.schema_json)
    schema["revision"] = rev.version
    return success({"template": schema})


@frappe.whitelist()
def save_hiring_order_template(company: str, revision: int = 0, template: Any = None) -> dict:
    _require_template_designer(company)
    require_company(company)
    if isinstance(template, str):
        template = json.loads(template)
    template = template or default_template()
    validated = validate_template(template)
    name = _template_form_name(company)
    encoded = json.dumps(validated, ensure_ascii=False)

    if name and frappe.db.exists("ASOUD Form", name):
        doc = frappe.get_doc("ASOUD Form", name)
        if int(revision) != 0 and int(revision) != doc.draft_version:
            frappe.throw(_("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))
        doc.draft_json = encoded
        doc.draft_version = (doc.draft_version or 1) + 1
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.save()
    else:
        doc = frappe.get_doc({
            "doctype": "ASOUD Form",
            "title": "قالب حکم استخدام",
            "company": company,
            "kind": "Document",
            "module_key": "hiring_order",
            "draft_json": encoded,
            "draft_version": 1,
        })
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.insert()
    return success({"revision": doc.draft_version, "template": validated})


@frappe.whitelist()
def publish_hiring_order_template(company: str, revision: int = 0) -> dict:
    _require_template_designer(company)
    require_company(company)
    name = _template_form_name(company)
    if not name or not frappe.db.exists("ASOUD Form", name):
        save_hiring_order_template(company, 0, default_template())
        name = _template_form_name(company)
    doc = frappe.get_doc("ASOUD Form", name)
    if int(revision) != 0 and int(revision) != doc.draft_version:
        frappe.throw(_("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))
    schema_json = doc.draft_json or json.dumps(default_template(), ensure_ascii=False)
    version = int(frappe.db.count("ASOUD Form Revision", {"form": doc.name})) + 1
    rev = frappe.get_doc({
        "doctype": "ASOUD Form Revision",
        "form": doc.name,
        "version": version,
        "schema_json": schema_json,
        "published_by": frappe.session.user,
        "published_on": now_datetime(),
    })
    rev.flags.form_service = True
    rev.flags.ignore_permissions = True
    rev.insert()
    doc.active_revision = rev.name
    doc.flags.form_service = True
    doc.flags.ignore_permissions = True
    doc.save()
    published = json.loads(rev.schema_json)
    published["revision"] = rev.version
    return success({"revision": rev.version, "template": published})


@frappe.whitelist()
def list_hiring_order_people(company: str, search: str = "", limit_start: int = 0,
                             limit_page_length: int = 20) -> dict:
    _require_hr_issuer(company)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=100)
    rows = frappe.get_all("Employee", filters={"company": company, "status": "Active"},
                          fields=["name", "employee_name", "employee_number", "department", "designation"],
                          order_by="employee_name asc")
    needle = normalize_search(search)
    if needle:
        rows = [row for row in rows if needle in normalize_search(" ".join(str(row.get(key) or "") for key in
                                                                         ("name", "employee_name", "employee_number")))]
    page = rows[start:start + length]
    return success([{"name": row.name, "display_name": row.employee_name or "پرسنل منتسب",
                     "employee_number": row.employee_number or "", "department": row.department or "",
                     "designation": row.designation or ""} for row in page],
                   meta={"limit_start": start, "limit_page_length": length, "count": len(page), "total": len(rows)})


@frappe.whitelist()
def get_hiring_order_payroll(company: str, employee: str, effective_date: str) -> dict:
    erp_documents.require_roles(PAYROLL_ROLES, company)
    require_company(company)
    if not frappe.db.exists("Employee", {"name": employee, "company": company}):
        frappe.throw(_("پرسنل انتخاب‌شده در این شرکت یافت نشد."), frappe.DoesNotExistError)
    effective = getdate(effective_date)
    assignment = frappe.get_all("Salary Structure Assignment", filters={
        "employee": employee, "company": company, "docstatus": 1, "from_date": ["<=", effective]},
        fields=["name", "base", "variable", "currency"], order_by="from_date desc, creation desc", limit_page_length=1)
    if not assignment:
        return success({"currency": frappe.db.get_value("Company", company, "default_currency"),
                        "rows": snapshot_payroll([{"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "field_ref": "base", "amount": None}])["rows"],
                        "message": MISSING_MESSAGE})
    row = assignment[0]
    payroll = snapshot_payroll([
        {"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "field_ref": "base", "amount": row.base},
        {"id": "variable_pay", "title": "مزایای متغیر", "period": "monthly", "field_ref": "variable", "amount": row.variable},
    ])
    return success({"currency": row.currency or frappe.db.get_value("Company", company, "default_currency"), **payroll})


@frappe.whitelist()
def list_hiring_orders(company: str, search: str = "", status: str = "",
                       limit_start: int = 0, limit_page_length: int = 20) -> dict:
    _require_hr_issuer(company)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=100)

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"company": company, "reference_doctype": "ASOUD Hiring Order"},
        fields=["name", "values_json", "modified"],
        order_by="modified desc",
    )

    items = []
    needle = normalize_search(search)
    for entry in entries:
        try:
            data = json.loads(entry.values_json or "{}")
        except Exception:
            continue
        order_status = data.get("status") or "draft"
        if status and status != "all" and order_status != status:
            continue

        emp_name = data.get("employee_name") or ""
        emp_num = data.get("employee_number") or ""
        order_num = data.get("number") or ""
        name = entry.name

        if needle:
            haystack = normalize_search(f"{emp_name} {emp_num} {order_num} {name}")
            if needle not in haystack:
                continue

        status_labels = {"draft": "پیش‌نویس", "pending": "در جریان", "final": "نهایی"}
        items.append({
            "name": name,
            "number": order_num,
            "employee": data.get("employee") or "",
            "employee_name": emp_name,
            "status": order_status,
            "status_label": status_labels.get(order_status, order_status),
            "effective_date": data.get("effective_date") or "",
            "issue_date": data.get("issue_date") or "",
            "drafted_on": data.get("drafted_on") or "",
            "revision": data.get("revision", 1),
        })

    page = items[start:start + length]
    return success(
        {"items": page},
        meta={
            "limit_start": start,
            "limit_page_length": length,
            "count": len(page),
            "total": len(items),
        },
    )


@frappe.whitelist()
def get_hiring_order(name: str) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    _require_hr_issuer(entry.company)
    data = json.loads(entry.values_json or "{}")
    data["name"] = entry.name
    data["company"] = entry.company
    return success(data)


@frappe.whitelist()
def save_hiring_order(
    company: str,
    request_id: str,
    revision: int = 0,
    order: str | None = None,
    employee: str = "",
    effective_date: str = "",
    issue_date: str | None = None,
    drafted_on: str | None = None,
    values: Any = None,
    payroll_rows: Any = None,
) -> dict:
    _require_hr_issuer(company)
    require_company(company)

    if request_id and not order:
        existing = frappe.db.get_value(
            "ASOUD Form Entry",
            {"fingerprint": request_id, "company": company, "reference_doctype": "ASOUD Hiring Order"},
            "name",
        )
        if existing:
            return get_hiring_order(existing)

    emp = frappe.db.get_value(
        "Employee",
        {"name": employee, "company": company},
        ["name", "employee_name", "employee_number", "department", "designation"],
        as_dict=True,
    )
    if not emp:
        frappe.throw(_("پرسنل انتخاب‌شده در این شرکت یافت نشد."), frappe.DoesNotExistError)

    t_name = _template_form_name(company)
    if not t_name or not frappe.db.exists("ASOUD Form", t_name):
        frappe.throw(_("قالب منتشرشدهٔ حکم استخدام برای این شرکت وجود ندارد."))
    form_doc = frappe.get_doc("ASOUD Form", t_name)
    if not form_doc.active_revision:
        frappe.throw(_("قالب منتشرشدهٔ حکم استخدام برای این شرکت وجود ندارد."))

    rev_doc = frappe.get_doc("ASOUD Form Revision", form_doc.active_revision)
    template_snapshot = json.loads(rev_doc.schema_json)
    template_snapshot["revision"] = rev_doc.version

    if isinstance(values, str):
        values = json.loads(values)
    values = values or {}

    if isinstance(payroll_rows, str):
        payroll_rows = json.loads(payroll_rows)

    if payroll_rows:
        payroll_snapshot = snapshot_payroll(payroll_rows)
    else:
        p_res = get_hiring_order_payroll(company, employee, effective_date)
        payroll_snapshot = p_res.get("data") or {}

    today_jalali = _format_jalali(nowdate())

    if order:
        if not frappe.db.exists("ASOUD Form Entry", order):
            frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
        entry = frappe.get_doc("ASOUD Form Entry", order)
        prev_data = json.loads(entry.values_json or "{}")
        if int(revision) != 0 and prev_data.get("revision") != int(revision):
            frappe.throw(_("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))
        current_rev = prev_data.get("revision", 1) + 1
        status = prev_data.get("status", "draft")
        number = prev_data.get("number", "")
    else:
        current_rev = 1
        status = "draft"
        number = ""

    status_labels = {"draft": "پیش‌نویس", "pending": "در جریان", "final": "نهایی"}
    order_data = {
        "company": company,
        "company_name": frappe.db.get_value("Company", company, "company_name") or company,
        "employee": emp.name,
        "employee_name": emp.employee_name or "پرسنل منتسب",
        "employee_number": emp.employee_number or "",
        "status": status,
        "status_label": status_labels.get(status, status),
        "number": number,
        "effective_date": effective_date,
        "issue_date": issue_date or "",
        "drafted_on": drafted_on or today_jalali,
        "department": values.get("unit") or emp.department or "",
        "designation": values.get("position") or emp.designation or "",
        "location": values.get("location") or "",
        "values": values,
        "template_snapshot": template_snapshot,
        "payroll_snapshot": payroll_snapshot,
        "revision": current_rev,
    }

    encoded = json.dumps(order_data, ensure_ascii=False)
    if order:
        frappe.db.set_value("ASOUD Form Entry", order, "values_json", encoded)
        entry_name = order
    else:
        entry = frappe.get_doc({
            "doctype": "ASOUD Form Entry",
            "form": form_doc.name,
            "revision": form_doc.active_revision,
            "company": company,
            "subject": f"حکم استخدام — {emp.employee_name or emp.name}",
            "reference_doctype": "ASOUD Hiring Order",
            "request_key": request_id,
            "fingerprint": request_id,
            "values_json": encoded,
        })
        entry.flags.form_service = True
        entry.flags.ignore_permissions = True
        entry.insert()
        entry_name = entry.name
        order_data["name"] = entry_name
        frappe.db.set_value("ASOUD Form Entry", entry_name, "values_json", json.dumps(order_data, ensure_ascii=False))

    return get_hiring_order(entry_name)


@frappe.whitelist()
def send_hiring_order_for_review(name: str, revision: int, request_id: str) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    _require_hr_issuer(entry.company)
    data = json.loads(entry.values_json or "{}")

    if int(revision) != 0 and data.get("revision") != int(revision):
        frappe.throw(_("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))
    if data.get("status") != "draft":
        frappe.throw(_("وضعیت یا نسخهٔ حکم برای این اقدام معتبر نیست."))

    data["status"] = "pending"
    data["status_label"] = "در جریان"
    data["revision"] = data.get("revision", 1) + 1
    frappe.db.set_value("ASOUD Form Entry", entry.name, "values_json", json.dumps(data, ensure_ascii=False))
    return get_hiring_order(entry.name)


@frappe.whitelist()
def print_hiring_order(name: str) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    _require_hr_issuer(entry.company)
    data = json.loads(entry.values_json or "{}")
    data["name"] = entry.name
    data["company"] = entry.company
    data["company_name"] = frappe.db.get_value("Company", entry.company, "company_name") or entry.company

    head = _letterhead(entry.company)
    html = format_hiring_order_print(data, letterhead_html=head)
    return success({
        "html": html,
        "status": data.get("status"),
        "number": data.get("number") or "—",
        "draft_banner": data.get("status") != "final",
    })
