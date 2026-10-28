"""Read, template, issuance, and payroll-application APIs for Salary Change Orders."""

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.jalali import gregorian_to_jalali
from asoud_erp.services.request_access import require_company
from asoud_erp.services.salary_change_orders import (
    MISSING_MESSAGE,
    calculate_comparison_table,
    default_template,
    format_salary_change_order_print,
    normalize_search,
    validate_template,
)
from asoud_erp.services.transaction_lines import paging

HR_ROLES = ("System Manager", "HR Manager")
PAYROLL_ROLES = ("System Manager", "Payroll Manager", "Accounts Manager")
VIEW_ROLES = ("System Manager", "HR Manager", "Payroll Manager", "Accounts Manager")
REASONS_MAP = {
    "annual": "افزایش سالانه",
    "promotion": "ارتقای شغلی",
    "adjustment": "اصلاح یا تعدیل حقوق",
    "benefits": "تغییر مزایا",
    "other": "سایر",
}


def _template_form_name(company: str) -> str | None:
    return frappe.db.get_value(
        "ASOUD Form",
        {"company": company, "module_key": "salary_change_order"},
        "name",
    )


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
def get_salary_change_order_template(company: str) -> dict:
    erp_documents.require_roles(HR_ROLES, company)
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
def save_salary_change_order_template(
    company: str, revision: int = 0, template: Any = None
) -> dict:
    erp_documents.require_roles(HR_ROLES, company)
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
            frappe.throw(
                _("این قالب توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.")
            )
        doc.draft_json = encoded
        doc.draft_version = (doc.draft_version or 1) + 1
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.save()
    else:
        doc = frappe.get_doc({
            "doctype": "ASOUD Form",
            "title": "قالب حکم افزایش یا تغییر حقوق و مزایا",
            "company": company,
            "kind": "Document",
            "module_key": "salary_change_order",
            "draft_json": encoded,
            "draft_version": 1,
        })
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.insert()
    return success({"revision": doc.draft_version, "template": validated})


@frappe.whitelist()
def publish_salary_change_order_template(company: str, revision: int = 0) -> dict:
    erp_documents.require_roles(HR_ROLES, company)
    require_company(company)
    name = _template_form_name(company)
    if not name or not frappe.db.exists("ASOUD Form", name):
        save_salary_change_order_template(company, 0, default_template())
        name = _template_form_name(company)
    doc = frappe.get_doc("ASOUD Form", name)
    if int(revision) != 0 and int(revision) != doc.draft_version:
        frappe.throw(
            _("این قالب توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.")
        )
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
def list_salary_change_order_people(
    company: str,
    search: str = "",
    limit_start: int = 0,
    limit_page_length: int = 20,
) -> dict:
    erp_documents.require_roles(HR_ROLES, company)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=100)
    rows = frappe.get_all(
        "Employee",
        filters={"company": company, "status": "Active"},
        fields=["name", "employee_name", "employee_number", "department", "designation"],
        order_by="employee_name asc",
    )
    needle = normalize_search(search)
    if needle:
        rows = [
            row
            for row in rows
            if needle
            in normalize_search(
                " ".join(
                    str(row.get(key) or "")
                    for key in ("name", "employee_name", "employee_number")
                )
            )
        ]
    page = rows[start : start + length]
    return success(
        [
            {
                "name": row.name,
                "display_name": row.employee_name or "پرسنل منتسب",
                "employee_number": row.employee_number or "",
                "department": row.department or "",
                "designation": row.designation or "",
            }
            for row in page
        ],
        meta={
            "limit_start": start,
            "limit_page_length": length,
            "count": len(page),
            "total": len(rows),
        },
    )


@frappe.whitelist()
def get_salary_change_order_payroll(
    company: str, employee: str, effective_date: str
) -> dict:
    erp_documents.require_roles(PAYROLL_ROLES, company)
    require_company(company)
    if not frappe.db.exists("Employee", {"name": employee, "company": company}):
        frappe.throw(
            _("پرسنل انتخاب‌شده در این شرکت یافت نشد."), frappe.DoesNotExistError
        )
    effective = getdate(effective_date)
    assignment = frappe.get_all(
        "Salary Structure Assignment",
        filters={
            "employee": employee,
            "company": company,
            "docstatus": 1,
            "from_date": ["<=", effective],
        },
        fields=["name", "base", "variable", "currency"],
        order_by="from_date desc, creation desc",
        limit_page_length=1,
    )
    default_curr = frappe.db.get_value("Company", company, "default_currency") or "IRR"
    if not assignment:
        # Return explicit missing state, never silent 0
        missing_rows = [
            {
                "id": "base_salary",
                "title": "حقوق پایه",
                "period": "monthly",
                "old_ref": "payroll.base_salary",
                "new_ref": "document.new.base_salary",
                "previous_amount": None,
                "state": "missing",
                "message": MISSING_MESSAGE,
            },
            {
                "id": "housing",
                "title": "حق مسکن",
                "period": "monthly",
                "old_ref": "payroll.housing",
                "new_ref": "document.new.housing",
                "previous_amount": None,
                "state": "missing",
                "message": MISSING_MESSAGE,
            },
            {
                "id": "food",
                "title": "بن خواربار",
                "period": "monthly",
                "old_ref": "payroll.food",
                "new_ref": "document.new.food",
                "previous_amount": None,
                "state": "missing",
                "message": MISSING_MESSAGE,
            },
        ]
        return success({
            "currency": default_curr,
            "rows": missing_rows,
            "message": MISSING_MESSAGE,
        })

    row = assignment[0]
    base_amount = int(row.base) if row.base is not None else None
    var_amount = int(row.variable) if row.variable is not None else None

    rows = [
        {
            "id": "base_salary",
            "title": "حقوق پایه",
            "period": "monthly",
            "old_ref": "payroll.base_salary",
            "new_ref": "document.new.base_salary",
            "previous_amount": base_amount,
            "state": "available" if base_amount is not None else "missing",
        },
        {
            "id": "housing",
            "title": "حق مسکن",
            "period": "monthly",
            "old_ref": "payroll.housing",
            "new_ref": "document.new.housing",
            "previous_amount": None,
            "state": "missing",
            "message": MISSING_MESSAGE,
        },
        {
            "id": "food",
            "title": "بن خواربار",
            "period": "monthly",
            "old_ref": "payroll.food",
            "new_ref": "document.new.food",
            "previous_amount": None,
            "state": "missing",
            "message": MISSING_MESSAGE,
        },
    ]
    if var_amount is not None:
        rows.append({
            "id": "variable_pay",
            "title": "مزایای متغیر",
            "period": "monthly",
            "old_ref": "payroll.variable",
            "new_ref": "document.new.variable",
            "previous_amount": var_amount,
            "state": "available",
        })

    return success({
        "currency": row.currency or default_curr,
        "rows": rows,
    })


@frappe.whitelist()
def list_salary_change_orders(
    company: str,
    search: str = "",
    status: str = "",
    application_status: str = "",
    limit_start: int = 0,
    limit_page_length: int = 20,
) -> dict:
    erp_documents.require_roles(VIEW_ROLES, company)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=100)

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={
            "company": company,
            "reference_doctype": "ASOUD Salary Change Order",
        },
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

        order_app_status = data.get("application_status") or "not_applied"
        if application_status and application_status != "all" and order_app_status != application_status:
            continue

        emp_name = data.get("employee_name") or ""
        emp_num = data.get("employee_number") or ""
        order_num = data.get("number") or ""
        name = entry.name

        if needle:
            haystack = normalize_search(f"{emp_name} {emp_num} {order_num} {name}")
            if needle not in haystack:
                continue

        status_labels = {
            "draft": "پیش‌نویس",
            "pending": "در جریان",
            "final": "نهایی",
            "rejected": "رد شده",
        }
        app_status_labels = {
            "not_applied": "اعمال‌نشده",
            "applied": "اعمال‌شده",
            "failed": "ناموفق",
        }

        items.append({
            "name": name,
            "number": order_num,
            "employee": data.get("employee") or "",
            "employee_name": emp_name,
            "status": order_status,
            "status_label": status_labels.get(order_status, order_status),
            "application_status": order_app_status,
            "application_status_label": app_status_labels.get(order_app_status, order_app_status),
            "effective_date": data.get("effective_date") or "",
            "issue_date": data.get("issue_date") or "",
            "drafted_on": data.get("drafted_on") or "",
            "reason": data.get("reason") or "annual",
            "reason_label": REASONS_MAP.get(data.get("reason"), data.get("reason")),
            "revision": data.get("revision", 1),
        })

    page = items[start : start + length]
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
def get_salary_change_order(name: str) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    if entry.reference_doctype != "ASOUD Salary Change Order":
        frappe.throw(_("نوع سند برای این عملیات معتبر نیست."))
    erp_documents.require_roles(VIEW_ROLES, entry.company)
    data = json.loads(entry.values_json or "{}")
    try:
        erp_documents.require_roles(PAYROLL_ROLES, entry.company)
    except frappe.PermissionError:
        data["comparison_table"] = {}
        data["values"] = {}
        if data.get("template_snapshot"):
            data["template_snapshot"]["comparison_rows"] = []
    data["name"] = entry.name
    data["company"] = entry.company
    return success(data)


@frappe.whitelist()
def save_salary_change_order(
    company: str,
    request_id: str,
    revision: int = 0,
    order: str | None = None,
    employee: str = "",
    effective_date: str = "",
    reason: str = "annual",
    description: str = "",
    issue_date: str | None = None,
    drafted_on: str | None = None,
    values: Any = None,
    comparison_rows: Any = None,
) -> dict:
    erp_documents.require_roles(HR_ROLES, company)
    require_company(company)

    # Idempotency check with request_id
    if request_id and not order:
        existing = frappe.db.get_value(
            "ASOUD Form Entry",
            {
                "fingerprint": request_id,
                "company": company,
                "reference_doctype": "ASOUD Salary Change Order",
            },
            "name",
        )
        if existing:
            return get_salary_change_order(existing)

    emp = frappe.db.get_value(
        "Employee",
        {"name": employee, "company": company},
        ["name", "employee_name", "employee_number", "department", "designation"],
        as_dict=True,
    )
    if not emp:
        frappe.throw(
            _("پرسنل انتخاب‌شده در این شرکت یافت نشد."), frappe.DoesNotExistError
        )

    t_name = _template_form_name(company)
    if t_name and frappe.db.exists("ASOUD Form", t_name):
        form_doc = frappe.get_doc("ASOUD Form", t_name)
        if form_doc.active_revision:
            rev_doc = frappe.get_doc("ASOUD Form Revision", form_doc.active_revision)
            template_snapshot = json.loads(rev_doc.schema_json)
            template_snapshot["revision"] = rev_doc.version
        else:
            template_snapshot = default_template()
            template_snapshot["revision"] = 1
    else:
        template_snapshot = default_template()
        template_snapshot["revision"] = 1

    if isinstance(values, str):
        values = json.loads(values)
    values = values or {}

    if isinstance(comparison_rows, str):
        comparison_rows = json.loads(comparison_rows)

    comparison_rows = comparison_rows or template_snapshot.get("comparison_rows") or []
    comparison_table = calculate_comparison_table(comparison_rows)

    today_jalali = _format_jalali(nowdate())

    if order:
        if not frappe.db.exists("ASOUD Form Entry", order):
            frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
        entry = frappe.get_doc("ASOUD Form Entry", order)
        if entry.company != company or entry.reference_doctype != "ASOUD Salary Change Order":
            frappe.throw(
                _("این حکم متعلق به شرکت یا نوع سند انتخاب‌شده نیست."),
                frappe.PermissionError,
            )
        prev_data = json.loads(entry.values_json or "{}")
        if not revision or int(revision) <= 0 or prev_data.get("revision") != int(revision):
            frappe.throw(
                _("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.")
            )
        if prev_data.get("status") in ("final", "pending") or prev_data.get("status") != "draft":
            frappe.throw(
                _("ویرایش حکم در وضعیت نهایی یا در جریان گردش‌کار مجاز نیست.")
            )
        current_rev = prev_data.get("revision", 1) + 1
        status = prev_data.get("status", "draft")
        app_status = prev_data.get("application_status", "not_applied")
        number = prev_data.get("number", "")
    else:
        current_rev = 1
        status = "draft"
        app_status = "not_applied"
        number = ""

    status_labels = {
        "draft": "پیش‌نویس",
        "pending": "در جریان",
        "final": "نهایی",
        "rejected": "رد شده",
    }
    app_status_labels = {
        "not_applied": "اعمال‌نشده",
        "applied": "اعمال‌شده",
        "failed": "ناموفق",
    }

    order_data = {
        "company": company,
        "company_name": frappe.db.get_value("Company", company, "company_name")
        or company,
        "employee": emp.name,
        "employee_name": emp.employee_name or "پرسنل منتسب",
        "employee_number": emp.employee_number or "",
        "status": status,
        "status_label": status_labels.get(status, status),
        "application_status": app_status,
        "application_status_label": app_status_labels.get(app_status, app_status),
        "number": number,
        "effective_date": effective_date,
        "issue_date": issue_date or "",
        "drafted_on": drafted_on or today_jalali,
        "reason": reason,
        "reason_label": REASONS_MAP.get(reason, reason),
        "description": description,
        "department": values.get("unit") or emp.department or "",
        "designation": values.get("position") or emp.designation or "",
        "values": values,
        "template_snapshot": template_snapshot,
        "comparison_table": comparison_table,
        "revision": current_rev,
    }

    encoded = json.dumps(order_data, ensure_ascii=False)
    if order:
        frappe.db.set_value("ASOUD Form Entry", order, "values_json", encoded)
        entry_name = order
    else:
        form_name = t_name or ""
        active_rev = ""
        if t_name and frappe.db.exists("ASOUD Form", t_name):
            f_doc = frappe.get_doc("ASOUD Form", t_name)
            form_name = f_doc.name
            active_rev = f_doc.active_revision or ""

        entry = frappe.get_doc({
            "doctype": "ASOUD Form Entry",
            "form": form_name,
            "revision": active_rev,
            "company": company,
            "subject": f"حکم افزایش/تغییر حقوق — {emp.employee_name or emp.name}",
            "reference_doctype": "ASOUD Salary Change Order",
            "request_key": request_id,
            "fingerprint": request_id,
            "values_json": encoded,
        })
        entry.flags.form_service = True
        entry.flags.ignore_permissions = True
        entry.insert()
        entry_name = entry.name
        order_data["name"] = entry_name
        frappe.db.set_value(
            "ASOUD Form Entry",
            entry_name,
            "values_json",
            json.dumps(order_data, ensure_ascii=False),
        )

    return get_salary_change_order(entry_name)


@frappe.whitelist()
def send_salary_change_order_for_review(
    name: str, revision: int, request_id: str
) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    erp_documents.require_roles(HR_ROLES, entry.company)
    data = json.loads(entry.values_json or "{}")

    if not revision or int(revision) <= 0 or data.get("revision") != int(revision):
        frappe.throw(
            _("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.")
        )
    if data.get("status") != "draft":
        frappe.throw(_("وضعیت یا نسخهٔ حکم برای این اقدام معتبر نیست."))

    data["status"] = "pending"
    data["status_label"] = "در جریان"
    data["revision"] = data.get("revision", 1) + 1
    frappe.db.set_value(
        "ASOUD Form Entry", entry.name, "values_json", json.dumps(data, ensure_ascii=False)
    )
    return get_salary_change_order(entry.name)


@frappe.whitelist()
def approve_salary_change_order(name: str, revision: int, request_id: str) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    erp_documents.require_roles(HR_ROLES, entry.company)
    data = json.loads(entry.values_json or "{}")

    if not revision or int(revision) <= 0 or data.get("revision") != int(revision):
        frappe.throw(
            _("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.")
        )
    if data.get("status") != "pending":
        frappe.throw(_("تنها احکام در جریان بررسی قابل تأیید نهایی هستند."))

    if not data.get("number"):
        count = (
            frappe.db.count(
                "ASOUD Form Entry",
                {
                    "reference_doctype": "ASOUD Salary Change Order",
                    "company": entry.company,
                },
            )
            + 1
        )
        try:
            jy, _, _ = gregorian_to_jalali(now_datetime())
        except Exception:
            jy = 1405
        data["number"] = f"SAL-{jy:04d}-{count:03d}"

    data["status"] = "final"
    data["status_label"] = "نهایی"
    data["issue_date"] = _format_jalali(nowdate())
    data["approved_by"] = frappe.session.user
    data["approved_on"] = str(now_datetime())
    data["revision"] = data.get("revision", 1) + 1
    frappe.db.set_value(
        "ASOUD Form Entry", entry.name, "values_json", json.dumps(data, ensure_ascii=False)
    )
    return get_salary_change_order(entry.name)


@frappe.whitelist()
def reject_salary_change_order(name: str, revision: int, reason: str = "") -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    erp_documents.require_roles(HR_ROLES, entry.company)
    data = json.loads(entry.values_json or "{}")

    if not revision or int(revision) <= 0 or data.get("revision") != int(revision):
        frappe.throw(
            _("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید.")
        )
    if data.get("status") not in ("draft", "pending"):
        frappe.throw(_("وضعیت حکم برای رد شدن معتبر نیست."))

    data["status"] = "rejected"
    data["status_label"] = "رد شده"
    data["rejection_reason"] = reason
    data["rejected_by"] = frappe.session.user
    data["rejected_on"] = str(now_datetime())
    data["revision"] = data.get("revision", 1) + 1
    frappe.db.set_value(
        "ASOUD Form Entry", entry.name, "values_json", json.dumps(data, ensure_ascii=False)
    )
    return get_salary_change_order(entry.name)


@frappe.whitelist()
def apply_salary_change_order_to_payroll(name: str, operation_id: str) -> dict:
    """Applies the approved salary change to the payroll subsystem idempotently with audit trail."""
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)

    # Permission check: MUST have payroll executor role
    erp_documents.require_roles(PAYROLL_ROLES, entry.company)

    data = json.loads(entry.values_json or "{}")

    # CRITICAL: order MUST be approved (final)
    if data.get("status") != "final":
        frappe.throw(
            _("اعمال بر سیستم حقوق و دستمزد تنها پس از تأیید نهایی حکم مجاز است.")
        )

    # Idempotency check: if already applied with this operation_id, return immediately
    if (
        data.get("application_status") == "applied"
        and data.get("applied_operation_id") == operation_id
    ):
        return get_salary_change_order(entry.name)

    emp_id = data.get("employee")
    effective_str = data.get("effective_date") or nowdate()
    effective_dt = getdate(effective_str)

    new_base = 0
    new_var = 0
    comp_table = data.get("comparison_table") or {}
    for r in comp_table.get("rows", []):
        row_id = r.get("id") or ""
        old_ref = r.get("old_ref") or ""
        if row_id == "base_salary" or "base" in old_ref:
            new_base = r.get("new_amount") or 0
        elif row_id in ("variable", "bonus") or "variable" in old_ref:
            new_var = r.get("new_amount") or 0

    # Retrieve existing assignment for structural configuration (salary_structure & payable account)
    existing_assignments = frappe.get_all(
        "Salary Structure Assignment",
        filters={"employee": emp_id, "company": entry.company, "docstatus": 1},
        fields=["name", "salary_structure", "payroll_payable_account", "currency"],
        order_by="from_date desc",
        limit_page_length=1,
    )
    if existing_assignments:
        struct_name = existing_assignments[0].salary_structure
        payable_acc = existing_assignments[0].payroll_payable_account
        curr = existing_assignments[0].currency
    else:
        struct_name = frappe.db.get_value(
            "Salary Structure", {"company": entry.company, "docstatus": 1}, "name"
        )
        payable_acc = frappe.get_cached_value(
            "Company", entry.company, "default_payroll_payable_account"
        )
        curr = (
            frappe.db.get_value("Company", entry.company, "default_currency") or "IRR"
        )

    if struct_name:
        new_assign = frappe.get_doc({
            "doctype": "Salary Structure Assignment",
            "employee": emp_id,
            "company": entry.company,
            "salary_structure": struct_name,
            "from_date": effective_dt,
            "base": new_base,
            "variable": new_var,
            "currency": curr,
            "payroll_payable_account": payable_acc,
        })
        new_assign.flags.ignore_permissions = True
        erp_documents.insert(new_assign, submit_now=True)

    data["application_status"] = "applied"
    data["application_status_label"] = "اعمال‌شده بر حقوق"
    data["applied_operation_id"] = operation_id
    data["applied_by"] = frappe.session.user
    data["applied_on"] = str(now_datetime())
    data["revision"] = data.get("revision", 1) + 1

    frappe.db.set_value(
        "ASOUD Form Entry", entry.name, "values_json", json.dumps(data, ensure_ascii=False)
    )
    return get_salary_change_order(entry.name)


@frappe.whitelist()
def print_salary_change_order(name: str) -> dict:
    if not frappe.db.exists("ASOUD Form Entry", name):
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    entry = frappe.get_doc("ASOUD Form Entry", name)
    require_company(entry.company)
    if entry.reference_doctype != "ASOUD Salary Change Order":
        frappe.throw(_("نوع سند برای این عملیات معتبر نیست."))
    erp_documents.require_roles(VIEW_ROLES, entry.company)
    data = json.loads(entry.values_json or "{}")
    try:
        erp_documents.require_roles(PAYROLL_ROLES, entry.company)
    except frappe.PermissionError:
        data["comparison_table"] = {}
        data["values"] = {}
        if data.get("template_snapshot"):
            data["template_snapshot"]["comparison_rows"] = []
    data["name"] = entry.name
    data["company"] = entry.company
    data["company_name"] = (
        frappe.db.get_value("Company", entry.company, "company_name") or entry.company
    )

    head = _letterhead(entry.company)
    html = format_salary_change_order_print(data, letterhead_html=head)
    return success({
        "html": html,
        "status": data.get("status"),
        "number": data.get("number") or "—",
        "draft_banner": data.get("status") != "final",
    })
