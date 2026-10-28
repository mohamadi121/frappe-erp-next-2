"""Employment Certificates API: versioned template builder and HR issuance."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.employment_certificates import (
    DEFAULT_TEMPLATE,
    build_print_html,
    normalize_search,
    render_snapshot,
    validate_template,
)
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.jalali import gregorian_to_jalali
from asoud_erp.services.request_access import require_company

TEMPLATE_DESIGNERS = ("System Manager", "HR Manager")
HR_OPERATIONAL_ROLES = ("System Manager", "HR Manager", "HR User")
PAYROLL_ROLES = ("System Manager", "Payroll Manager", "Accounts Manager")
CERT_DOCTYPE = "ASOUD Employment Certificate"
SERIES = "CERT-.YYYY.-.#####"


def _is_designer() -> bool:
    if frappe.session.user == "Administrator":
        return True
    return bool(set(frappe.get_roles()) & set(TEMPLATE_DESIGNERS))


def _has_payroll_permission(company: str) -> bool:
    if frappe.session.user == "Administrator":
        return True
    roles = set(frappe.get_roles())
    if roles & set(PAYROLL_ROLES):
        return True
    from asoud_erp.services.office_access import office_roles

    return bool(set(PAYROLL_ROLES) & office_roles(frappe.session.user, company))


def _template_name(company: str) -> str:
    return hashlib.sha256(f"asoud-employment-certificate-template:{company}".encode()).hexdigest()[:32]


def _format_jalali(d: Any) -> str:
    if not d:
        return ""
    try:
        dt = getdate(d)
        y, m, day = gregorian_to_jalali(dt)
        return f"{y}/{m:02d}/{day:02d}"
    except Exception:
        return str(d)


def _letterhead(company: str) -> str | None:
    name = frappe.db.get_value("Company", company, "default_letter_head")
    head = (
        frappe.db.get_value("Letter Head", name, ["disabled", "source", "content", "image"], as_dict=True)
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
            return '<img style="max-height:80px" src="data:image/png;base64,' + base64.b64encode(data).decode() + '">'
    return head.content or None


def _build_print_html(data: dict, letterhead_html: str | None, is_final: bool) -> str:
    return build_print_html(
        rendered_html=data.get("rendered_html") or "",
        letterhead_html=letterhead_html,
        number=data.get("number", "—"),
        issue_date=data.get("issue_date", "—"),
        is_final=is_final,
    )


def _ensure_template(company: str) -> str:
    name = _template_name(company)
    if not frappe.db.exists("ASOUD Form", name):
        normalized = validate_template(DEFAULT_TEMPLATE)
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        doc = frappe.get_doc({
            "doctype": "ASOUD Form",
            "name": name,
            "company": company,
            "kind": "Document",
            "module_key": "HR",
            "title": "قالب گواهی اشتغال به کار",
            "draft_json": encoded,
            "draft_version": 1,
        })
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.insert(set_name=name)
    return name


def _get_active_template_data(company: str) -> dict[str, Any]:
    name = _ensure_template(company)
    if frappe.db.exists("ASOUD Form", name):
        doc = frappe.get_doc("ASOUD Form", name)
        if doc.active_revision:
            rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
            try:
                parsed = json.loads(rev.schema_json)
                parsed["revision"] = rev.version
                parsed["status"] = "Published"
                parsed["name"] = doc.name
                return parsed
            except Exception:
                pass
        if doc.draft_json:
            try:
                parsed = json.loads(doc.draft_json)
                parsed["revision"] = doc.draft_version or 1
                parsed["status"] = "Draft"
                parsed["name"] = doc.name
                return parsed
            except Exception:
                pass
    fallback = dict(DEFAULT_TEMPLATE)
    fallback["name"] = name
    fallback["revision"] = 1
    fallback["status"] = "Draft"
    return fallback


@frappe.whitelist()
def get_template(company: str) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    name = _ensure_template(company)
    doc = frappe.get_doc("ASOUD Form", name)
    if doc.company != company:
        frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)

    designer = _is_designer()
    if designer and doc.draft_json:
        try:
            data = json.loads(doc.draft_json)
            return success({
                "name": doc.name,
                "revision": doc.draft_version or 1,
                "status": "Draft",
                "clauses": data.get("clauses", []),
                "salary_enabled": data.get("salary_enabled", False),
                "salary_rows": data.get("salary_rows", []),
            })
        except Exception:
            pass

    if doc.active_revision:
        rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
        try:
            data = json.loads(rev.schema_json)
            return success({
                "name": doc.name,
                "revision": rev.version,
                "status": "Published",
                "clauses": data.get("clauses", []),
                "salary_enabled": data.get("salary_enabled", False),
                "salary_rows": data.get("salary_rows", []),
            })
        except Exception:
            pass

    data = json.loads(doc.draft_json) if doc.draft_json else DEFAULT_TEMPLATE
    return success({
        "name": doc.name,
        "revision": doc.draft_version or 1,
        "status": "Draft",
        "clauses": data.get("clauses", []),
        "salary_enabled": data.get("salary_enabled", False),
        "salary_rows": data.get("salary_rows", []),
    })


@frappe.whitelist()
def save_template_draft(
    company: str,
    revision: int = 0,
    clauses: Any = None,
    salary_enabled: bool = False,
    salary_rows: Any = None,
) -> dict:
    require_company(company)
    require_roles(TEMPLATE_DESIGNERS, company=company)

    if isinstance(clauses, str):
        clauses = json.loads(clauses)
    if isinstance(salary_rows, str):
        salary_rows = json.loads(salary_rows)

    try:
        normalized = validate_template({
            "clauses": clauses or [],
            "salary_enabled": bool(salary_enabled),
            "salary_rows": salary_rows or [],
        })
    except ValueError as err:
        frappe.throw(str(err))

    name = _ensure_template(company)
    doc = frappe.get_doc("ASOUD Form", name)
    if doc.company != company:
        frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)

    if int(revision) != 0 and int(revision) != doc.draft_version:
        frappe.throw(_("نسخه پیش‌نویس تغییر کرده است؛ صفحه را تازه‌سازی کنید."))

    doc.draft_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    doc.draft_version = (doc.draft_version or 1) + 1
    doc.flags.form_service = True
    doc.flags.ignore_permissions = True
    doc.save()

    return success({
        "name": doc.name,
        "revision": doc.draft_version,
        "status": "Draft",
        "clauses": normalized["clauses"],
        "salary_enabled": normalized["salary_enabled"],
        "salary_rows": normalized["salary_rows"],
    })


@frappe.whitelist()
def publish_template(company: str, revision: int = 0) -> dict:
    require_company(company)
    require_roles(TEMPLATE_DESIGNERS, company=company)

    name = _ensure_template(company)
    doc = frappe.get_doc("ASOUD Form", name)
    if doc.company != company:
        frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)

    if not doc.draft_json:
        frappe.throw(_("پیش‌نویسی برای انتشار وجود ندارد."))

    if int(revision) != 0 and int(revision) != doc.draft_version:
        frappe.throw(_("نسخه پیش‌نویس تغییر کرده است؛ صفحه را تازه‌سازی کنید."))

    data = json.loads(doc.draft_json)
    try:
        normalized = validate_template(data)
    except ValueError as err:
        frappe.throw(str(err))

    new_version = 1
    if doc.active_revision:
        last_rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
        new_version = (last_rev.version or 1) + 1

    rev = frappe.get_doc({
        "doctype": "ASOUD Form Revision",
        "form": doc.name,
        "version": new_version,
        "schema_json": json.dumps(normalized, ensure_ascii=False, sort_keys=True),
        "published_by": frappe.session.user,
        "published_on": now_datetime(),
        "change_note": f"انتشار نسخه {new_version}",
    })
    rev.flags.form_service = True
    rev.flags.ignore_permissions = True
    rev.insert()

    doc.active_revision = rev.name
    doc.flags.form_service = True
    doc.flags.ignore_permissions = True
    doc.save()

    return success({
        "name": doc.name,
        "revision": rev.version,
        "status": "Published",
        "clauses": normalized["clauses"],
        "salary_enabled": normalized["salary_enabled"],
        "salary_rows": normalized["salary_rows"],
    })


@frappe.whitelist()
def get_employee_options(company: str) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    employees = frappe.get_all(
        "Employee",
        filters={"company": company, "status": "Active"},
        fields=["name", "employee_name", "department", "designation", "date_of_joining"],
        order_by="employee_name asc",
    )
    return success(employees)


@frappe.whitelist()
def list_certificates(
    company: str,
    query: str = "",
    status: str = "",
    start: int = 0,
    page_length: int = 20,
) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"company": company, "reference_doctype": CERT_DOCTYPE},
        fields=["name", "values_json", "creation"],
        order_by="creation desc",
    )

    status_filter = (status or "").strip().lower()
    norm_query = normalize_search(query)

    items = []
    for entry in entries:
        try:
            val = json.loads(entry.values_json)
        except Exception:
            continue

        item_status = val.get("status", "Draft")
        if status_filter:
            if status_filter in {"draft", "پیش‌نویس"} and item_status != "Draft":
                continue
            if status_filter in {"final", "نهایی"} and item_status != "Final":
                continue
            if status_filter in {"pending", "در جریان"} and item_status not in {"In Progress", "Pending"}:
                continue

        if norm_query:
            emp_name = val.get("employee_name", "")
            emp_num = val.get("employee_number", "")
            doc_num = val.get("number", "")
            addressee = val.get("addressee_name", "")
            purpose = val.get("purpose", "")
            searchable = normalize_search(f"{emp_name} {emp_num} {doc_num} {addressee} {purpose}")
            if norm_query not in searchable:
                continue

        items.append({
            "name": val.get("name") or entry.name,
            "employee": val.get("employee", ""),
            "employee_name": val.get("employee_name", ""),
            "employee_number": val.get("employee_number", ""),
            "number": val.get("number", "—"),
            "addressee_type": val.get("addressee_type", ""),
            "addressee_name": val.get("addressee_name", ""),
            "addressee_title": val.get("addressee_title", ""),
            "purpose": val.get("purpose", ""),
            "status": item_status,
            "creation": str(entry.creation),
            "issue_date": val.get("issue_date", ""),
        })

    total = len(items)
    start_idx = max(0, int(start))
    length = max(1, int(page_length))
    paged = items[start_idx : start_idx + length]

    return success({"items": paged, "total": total})


@frappe.whitelist()
def get_certificate(name: str) -> dict:
    if not name:
        frappe.throw(_("شناسه گواهی الزامی است."))

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"reference_doctype": CERT_DOCTYPE, "reference_name": name},
        fields=["name", "company", "values_json"],
        limit_page_length=1,
    )
    if not entries:
        # Also try entry name directly
        entries = frappe.get_all(
            "ASOUD Form Entry",
            filters={"name": name, "reference_doctype": CERT_DOCTYPE},
            fields=["name", "company", "values_json"],
            limit_page_length=1,
        )

    if not entries:
        frappe.throw(_("گواهی مورد نظر یافت نشد."), frappe.DoesNotExistError)

    entry = entries[0]
    require_company(entry.company)
    require_roles(HR_OPERATIONAL_ROLES, company=entry.company)

    try:
        data = json.loads(entry.values_json)
    except Exception:
        frappe.throw(_("اطلاعات گواهی ذخیره‌شده مخدوش است."))

    return _certificate_response(data, entry.company)


def _certificate_response(data: dict, company: str) -> dict:
    # All read/retry/finalize paths apply the same policy to persisted snapshots.
    if not _has_payroll_permission(company) or not data.get("include_salary"):
        data["salary_rows"] = []
        data["has_salary"] = False
        data["include_salary"] = False
        values = data.get("values_snapshot")
        if isinstance(values, dict):
            values.pop("payroll", None)
        tmpl = data.get("template_snapshot")
        if tmpl:
            stripped = dict(tmpl, salary_enabled=False, salary_rows=[])
            rendered = render_snapshot(stripped, data.get("values_snapshot") or {}, None)
            data["template_snapshot"] = rendered["template"]
            data["values_snapshot"] = rendered["values"]
            data["rendered_html"] = rendered["html"]
        else:
            data["rendered_html"] = ""
    data["print_html"] = _build_print_html(data, _letterhead(company), data.get("status") == "Final")
    return success(data)


@frappe.whitelist()
def save_draft(
    company: str,
    employee: str,
    addressee_type: str = "",
    addressee_name: str = "",
    addressee_title: str = "",
    purpose: str = "",
    request_key: str = "",
    revision: int = 0,
    name: str = "",
    notes: str = "",
    include_salary: bool = False,
    location: str = "",
) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    if not request_key:
        frappe.throw(_("شناسه یکتای درخواست (request_key) الزامی است."))

    if not employee or not frappe.db.exists("Employee", employee):
        frappe.throw(_("پرسنل مورد نظر در سیستم یافت نشد."))

    emp = frappe.db.get_value(
        "Employee",
        employee,
        ["name", "employee_name", "department", "designation", "date_of_joining", "status", "company", "user_id"],
        as_dict=True,
    )
    if emp.company != company:
        frappe.throw(_("این پرسنل متعلق به شرکت دیگری است."), frappe.PermissionError)

    if emp.status != "Active":
        frappe.throw(_("تنها برای پرسنل فعال امکان صدور گواهی وجود دارد."))

    if not emp.date_of_joining:
        frappe.throw(_("تاریخ شروع به کار کارمند در سیستم ثبت نشده است."))

    if not (addressee_name or "").strip():
        frappe.throw(_("نام مخاطب گواهی الزامی است."))

    national_id = frappe.db.get_value("ASOUD Party Profile", {"employee": employee}, "national_id") or ""

    # Idempotency check on request_key:
    existing_key_entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"request_key": request_key},
        fields=["name", "values_json", "reference_name"],
        limit_page_length=1,
    )
    if existing_key_entries:
        try:
            stored = json.loads(existing_key_entries[0].values_json)
            if stored.get("employee") == employee and stored.get("company") == company:
                letterhead_html = _letterhead(company)
                stored["print_html"] = _build_print_html(stored, letterhead_html, stored.get("status") == "Final")
                return _certificate_response(stored, company)
        except Exception:
            pass
        frappe.throw(_("کلید درخواست تکراری با اطلاعات متفاوت ارسال شده است."))

    comp = frappe.db.get_value("Company", company, ["company_name"], as_dict=True)
    template_data = _get_active_template_data(company)
    tmpl_clauses = template_data.get("clauses", DEFAULT_TEMPLATE["clauses"])
    tmpl_salary_enabled = template_data.get("salary_enabled", False)
    tmpl_salary_rows = template_data.get("salary_rows", DEFAULT_TEMPLATE["salary_rows"])

    has_payroll = _has_payroll_permission(company)
    should_include_salary = tmpl_salary_enabled and bool(include_salary) and has_payroll

    salary_source_rows = []
    if should_include_salary:
        assignments = frappe.get_all(
            "Salary Structure Assignment",
            filters={"employee": employee, "company": company, "docstatus": 1, "from_date": ["<=", nowdate()]},
            fields=["base", "variable", "currency"],
            order_by="from_date desc, creation desc",
            limit_page_length=1,
        )
        base_amount = assignments[0].base if (assignments and assignments[0].base) else None
        for row in tmpl_salary_rows:
            salary_source_rows.append({
                "id": row["id"],
                "title": row["title"],
                "amount": base_amount if row.get("field_ref") == "payroll.base" else None,
                "period": row.get("period", "monthly"),
            })

    values = {
        "employee": {
            "employee_name": emp.employee_name or "",
            "employee_number": emp.name or "",
            "national_id": national_id or "",
            "department": emp.department or "",
            "designation": emp.designation or "",
            "date_of_joining": _format_jalali(emp.date_of_joining),
        },
        "company": {
            "company_name": comp.company_name if comp else company,
        },
        "certificate": {
            "addressee_name": addressee_name.strip(),
            "addressee_type": addressee_type.strip(),
            "addressee_title": addressee_title.strip(),
            "purpose": purpose.strip(),
            "location": location.strip() or (comp.company_name if comp else company),
            "number": "—",
            "date": "—",
        },
    }

    active_template = {
        "clauses": tmpl_clauses,
        "salary_enabled": should_include_salary,
        "salary_rows": tmpl_salary_rows if should_include_salary else [],
    }
    rendered = render_snapshot(active_template, values, salary_source_rows if should_include_salary else None)

    cert_id = name.strip() if name.strip() else make_autoname("CERT-DRAFT-.#####")
    current_rev = int(revision) if revision else 1

    entry_doc = None
    if name.strip():
        existing = frappe.get_all(
            "ASOUD Form Entry",
            filters={"reference_doctype": CERT_DOCTYPE, "reference_name": cert_id},
            fields=["name", "values_json"],
            limit_page_length=1,
        )
        if not existing:
            frappe.throw(_("گواهی مورد نظر یافت نشد."))
        entry_doc = frappe.get_doc("ASOUD Form Entry", existing[0].name, for_update=True)
        if entry_doc.company != company:
            frappe.throw(_("این گواهی متعلق به شرکت انتخاب‌شده نیست."), frappe.PermissionError)
        try:
            prev_data = json.loads(entry_doc.values_json)
        except (ValueError, TypeError):
            frappe.throw(_("اطلاعات گواهی ذخیره‌شده مخدوش است."))
        if prev_data.get("status") != "Draft":
            frappe.throw(_("فقط پیش‌نویس گواهی قابل ویرایش است."))
        if not revision or int(revision) != prev_data.get("revision", 1):
            frappe.throw(_("نسخه پیش‌نویس گواهی تغییر کرده است؛ صفحه را تازه‌سازی کنید."))
        current_rev = prev_data.get("revision", 1) + 1

    cert_data = {
        "name": cert_id,
        "company": company,
        "employee": employee,
        "employee_name": emp.employee_name or "",
        "employee_number": emp.name,
        "number": "—",
        "addressee_type": addressee_type.strip(),
        "addressee_name": addressee_name.strip(),
        "addressee_title": addressee_title.strip(),
        "purpose": purpose.strip(),
        "location": location.strip(),
        "notes": notes.strip(),
        "status": "Draft",
        "include_salary": should_include_salary,
        "revision": current_rev,
        "template_version": template_data.get("revision", 1),
        "template_snapshot": active_template,
        "values_snapshot": values,
        "rendered_html": rendered["html"],
        "salary_rows": rendered["salary_rows"],
        "has_salary": should_include_salary,
        "issue_date": "",
    }

    letterhead_html = _letterhead(company)
    cert_data["print_html"] = _build_print_html(cert_data, letterhead_html, False)
    payload_json = json.dumps(cert_data, ensure_ascii=False, sort_keys=True)

    if entry_doc:
        frappe.db.set_value(
            "ASOUD Form Entry",
            entry_doc.name,
            {"values_json": payload_json, "subject": f"گواهی اشتغال — {emp.employee_name}"},
        )
    else:
        form_name = _template_name(company)
        new_entry = frappe.get_doc({
            "doctype": "ASOUD Form Entry",
            "form": form_name,
            "company": company,
            "subject": f"گواهی اشتغال — {emp.employee_name}",
            "reference_doctype": CERT_DOCTYPE,
            "reference_name": cert_id,
            "request_key": request_key,
            "values_json": payload_json,
        })
        new_entry.flags.form_service = True
        new_entry.flags.ignore_permissions = True
        new_entry.insert()

    return _certificate_response(cert_data, company)


@frappe.whitelist()
def finalize_certificate(name: str, revision: int = 0, request_key: str = "") -> dict:
    if not name:
        frappe.throw(_("شناسه گواهی الزامی است."))
    if not request_key:
        frappe.throw(_("شناسه یکتای درخواست (request_key) الزامی است."))

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"reference_doctype": CERT_DOCTYPE, "reference_name": name},
        fields=["name", "company", "values_json"],
        limit_page_length=1,
    )
    if not entries:
        entries = frappe.get_all(
            "ASOUD Form Entry",
            filters={"name": name, "reference_doctype": CERT_DOCTYPE},
            fields=["name", "company", "values_json"],
            limit_page_length=1,
        )

    if not entries:
        frappe.throw(_("گواهی مورد نظر برای نهایی‌سازی یافت نشد."))

    entry_row = entries[0]
    require_company(entry_row.company)
    require_roles(HR_OPERATIONAL_ROLES, company=entry_row.company)

    try:
        data = json.loads(entry_row.values_json)
    except Exception:
        frappe.throw(_("اطلاعات گواهی مخدوش است."))

    # Idempotent return if already finalized
    if data.get("status") == "Final":
        letterhead_html = _letterhead(entry_row.company)
        data["print_html"] = _build_print_html(data, letterhead_html, True)
        return _certificate_response(data, entry_row.company)

    if revision and int(revision) != data.get("revision", 1):
        frappe.throw(_("نسخه گواهی تغییر کرده است؛ صفحه را تازه‌سازی کنید."))

    official_number = make_autoname(SERIES)
    issue_date_str = _format_jalali(nowdate())

    data["status"] = "Final"
    data["number"] = official_number
    data["issue_date"] = issue_date_str
    data["revision"] = data.get("revision", 1) + 1

    # Re-render snapshot with official number and date:
    vals = data.get("values_snapshot", {})
    if "certificate" in vals:
        vals["certificate"]["number"] = official_number
        vals["certificate"]["date"] = issue_date_str

    tmpl = data.get("template_snapshot", DEFAULT_TEMPLATE)
    salary_rows = data.get("salary_rows")
    rendered = render_snapshot(tmpl, vals, salary_rows)
    data["rendered_html"] = rendered["html"]

    letterhead_html = _letterhead(entry_row.company)
    data["print_html"] = _build_print_html(data, letterhead_html, True)

    frappe.db.set_value(
        "ASOUD Form Entry",
        entry_row.name,
        {"values_json": json.dumps(data, ensure_ascii=False, sort_keys=True)},
    )

    return _certificate_response(data, entry_row.company)
