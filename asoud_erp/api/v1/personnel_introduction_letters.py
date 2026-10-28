"""Personnel Introduction Letters API: versioned template builder and HR issuance."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.jalali import gregorian_to_jalali
from asoud_erp.services.personnel_introduction_letters import (
    DEFAULT_TEMPLATE,
    build_print_html,
    normalize_search,
    render_snapshot,
    validate_template,
)
from asoud_erp.services.request_access import require_company

TEMPLATE_DESIGNERS = ("System Manager", "HR Manager")
HR_OPERATIONAL_ROLES = ("System Manager", "HR Manager", "HR User")
INTRO_DOCTYPE = "ASOUD Personnel Introduction Letter"
SERIES = "INTRO-.YYYY.-.#####"


def _is_designer() -> bool:
    if frappe.session.user == "Administrator":
        return True
    return bool(set(frappe.get_roles()) & set(TEMPLATE_DESIGNERS))


def _template_name(company: str) -> str:
    return hashlib.sha256(f"asoud-personnel-introduction-template:{company}".encode()).hexdigest()[:32]


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
        validity_date=data.get("validity_date", ""),
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
            "title": "قالب معرفی‌نامه پرسنل",
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
                "can_manage_template": designer,
                "clauses": data.get("clauses", []),
                "required_recipient": data.get("required_recipient", True),
                "required_purpose": data.get("required_purpose", True),
                "has_expiry": data.get("has_expiry", False),
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
                "can_manage_template": designer,
                "clauses": data.get("clauses", []),
                "required_recipient": data.get("required_recipient", True),
                "required_purpose": data.get("required_purpose", True),
                "has_expiry": data.get("has_expiry", False),
            })
        except Exception:
            pass

    return success({
        "name": doc.name,
        "revision": 1,
        "status": "Draft",
        "can_manage_template": designer,
        "clauses": DEFAULT_TEMPLATE["clauses"],
        "required_recipient": DEFAULT_TEMPLATE["required_recipient"],
        "required_purpose": DEFAULT_TEMPLATE["required_purpose"],
        "has_expiry": DEFAULT_TEMPLATE["has_expiry"],
    })


@frappe.whitelist()
def save_template_draft(
    company: str,
    revision: int = 0,
    clauses: Any = None,
    required_recipient: bool = True,
    required_purpose: bool = True,
    has_expiry: bool = False,
) -> dict:
    require_company(company)
    require_roles(TEMPLATE_DESIGNERS, company=company)

    if isinstance(clauses, str):
        try:
            clauses = json.loads(clauses)
        except Exception:
            frappe.throw(_("قالب ارسال‌شده معتبر نیست."))

    if clauses is None:
        clauses = DEFAULT_TEMPLATE["clauses"]

    if isinstance(required_recipient, str):
        required_recipient = required_recipient.lower() in ("true", "1")
    if isinstance(required_purpose, str):
        required_purpose = required_purpose.lower() in ("true", "1")
    if isinstance(has_expiry, str):
        has_expiry = has_expiry.lower() in ("true", "1")

    payload = {
        "clauses": clauses,
        "required_recipient": bool(required_recipient),
        "required_purpose": bool(required_purpose),
        "has_expiry": bool(has_expiry),
    }

    try:
        normalized = validate_template(payload)
    except ValueError as err:
        frappe.throw(str(err))

    name = _ensure_template(company)
    doc = frappe.get_doc("ASOUD Form", name)
    if doc.company != company:
        frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)

    expected_rev = int(revision) if revision else (doc.draft_version or 1)
    if doc.draft_version and doc.draft_version != expected_rev:
        frappe.throw(_("نسخهٔ پیش‌نویس قالب تغییر کرده است؛ صفحه را تازه‌سازی کنید."))

    new_version = expected_rev + 1
    doc.draft_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    doc.draft_version = new_version
    doc.flags.form_service = True
    doc.flags.ignore_permissions = True
    doc.save()

    return success({
        "name": doc.name,
        "revision": new_version,
        "status": "Draft",
        "clauses": normalized["clauses"],
        "required_recipient": normalized["required_recipient"],
        "required_purpose": normalized["required_purpose"],
        "has_expiry": normalized["has_expiry"],
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
        frappe.throw(_("پیش‌نویسی برای انتشار یافت نشد."))

    try:
        data = json.loads(doc.draft_json)
        normalized = validate_template(data)
    except Exception as err:
        frappe.throw(str(err) if isinstance(err, ValueError) else _("پیش‌نویس قالب معتبر نیست."))

    if revision and int(revision) != (doc.draft_version or 1):
        frappe.throw(_("نسخهٔ پیش‌نویس قالب تغییر کرده است؛ صفحه را تازه‌سازی کنید."))

    last_rev_num = 0
    if doc.active_revision:
        try:
            prev_rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
            last_rev_num = prev_rev.version or 0
        except Exception:
            pass

    new_rev_num = last_rev_num + 1
    schema_encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)

    rev_doc = frappe.get_doc({
        "doctype": "ASOUD Form Revision",
        "parent_form": doc.name,
        "version": new_rev_num,
        "schema_json": schema_encoded,
    })
    rev_doc.flags.form_service = True
    rev_doc.flags.ignore_permissions = True
    rev_doc.insert()

    doc.active_revision = rev_doc.name
    doc.active_version = new_rev_num
    doc.flags.form_service = True
    doc.flags.ignore_permissions = True
    doc.save()

    return success({
        "name": doc.name,
        "revision": new_rev_num,
        "status": "Published",
        "clauses": normalized["clauses"],
        "required_recipient": normalized["required_recipient"],
        "required_purpose": normalized["required_purpose"],
        "has_expiry": normalized["has_expiry"],
    })


def _get_employee_extra(emp_name: str) -> tuple[str, str]:
    nat_id = ""
    try:
        if frappe.db.exists("DocType", "ASOUD Party Profile"):
            nat_id = frappe.db.get_value("ASOUD Party Profile", {"employee": emp_name}, "national_id") or ""
    except Exception:
        pass
    loc = ""
    try:
        if frappe.get_meta("Employee").has_field("work_location"):
            loc = frappe.db.get_value("Employee", emp_name, "work_location") or ""
    except Exception:
        pass
    return nat_id, loc


@frappe.whitelist()
def get_employee_options(company: str) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    employees = frappe.get_all(
        "Employee",
        filters={"company": company, "status": "Active"},
        fields=[
            "name as employee",
            "employee_name",
            "employee_number",
            "department",
            "designation",
            "date_of_joining",
        ],
        order_by="employee_name asc",
        limit_page_length=200,
    )
    for emp in employees:
        emp["employee_number"] = emp.get("employee_number") or ""
        emp["date_of_joining"] = _format_jalali(emp.get("date_of_joining"))
        nat_id, loc = _get_employee_extra(emp["employee"])
        emp["national_id"] = nat_id
        emp["work_location"] = loc
    return success(employees)


@frappe.whitelist()
def list_letters(
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
        filters={"company": company, "reference_doctype": INTRO_DOCTYPE},
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
            recipient = val.get("recipient_name", "") or val.get("bank_name", "") or val.get("recipient_text", "")
            purpose = val.get("purpose", "")
            searchable = normalize_search(f"{emp_name} {emp_num} {doc_num} {recipient} {purpose}")
            if norm_query not in searchable:
                continue

        items.append({
            "name": val.get("name", entry.name),
            "id": val.get("name", entry.name),
            "number": val.get("number", "—"),
            "status": item_status,
            "employee": val.get("employee", ""),
            "employee_name": val.get("employee_name", ""),
            "employee_number": val.get("employee_number", ""),
            "recipient_type": val.get("recipient_type", "bank"),
            "recipient_name": val.get("recipient_name", ""),
            "bank_name": val.get("bank_name", ""),
            "branch_name": val.get("branch_name", ""),
            "recipient_text": val.get("recipient_text", ""),
            "purpose": val.get("purpose", ""),
            "validity_date": val.get("validity_date", ""),
            "issue_date": val.get("issue_date", "—"),
            "creation": str(entry.creation),
        })

    total = len(items)
    start_idx = max(0, int(start))
    length = max(1, min(100, int(page_length)))
    paginated = items[start_idx : start_idx + length]

    return success({"items": paginated, "total": total})


@frappe.whitelist()
def get_letter(name: str) -> dict:
    if not name:
        frappe.throw(_("شناسه معرفی‌نامه الزامی است."))

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"reference_doctype": INTRO_DOCTYPE, "reference_name": name},
        fields=["name", "company", "values_json"],
        limit_page_length=1,
    )
    if not entries:
        entries = frappe.get_all(
            "ASOUD Form Entry",
            filters={"name": name, "reference_doctype": INTRO_DOCTYPE},
            fields=["name", "company", "values_json"],
            limit_page_length=1,
        )

    if not entries:
        frappe.throw(_("معرفی‌نامه یافت نشد."), frappe.DoesNotExistError)

    entry = entries[0]
    require_company(entry.company)
    require_roles(HR_OPERATIONAL_ROLES, company=entry.company)

    try:
        data = json.loads(entry.values_json)
    except Exception:
        frappe.throw(_("داده‌های معرفی‌نامه نامعتبر است."))

    letterhead_html = _letterhead(entry.company)
    data["print_html"] = _build_print_html(data, letterhead_html, data.get("status") == "Final")
    return success(data)


@frappe.whitelist()
def save_draft(
    company: str,
    employee: str,
    recipient_type: str = "bank",
    recipient_name: str = "",
    bank_name: str = "",
    branch_name: str = "",
    purpose: str = "",
    validity_date: str = "",
    notes: str = "",
    request_key: str = "",
    revision: int = 1,
    name: str = "",
) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    if not employee:
        frappe.throw(_("انتخاب پرسنل الزامی است."))
    if not request_key:
        frappe.throw(_("شناسه یکتای درخواست (request_key) الزامی است."))

    # Idempotency check
    existing_key = frappe.get_all(
        "ASOUD Form Entry",
        filters={"company": company, "reference_doctype": INTRO_DOCTYPE, "request_key": request_key},
        fields=["values_json"],
        limit_page_length=1,
    )
    if existing_key:
        try:
            return success(json.loads(existing_key[0].values_json))
        except Exception:
            pass

    emp = frappe.db.get_value(
        "Employee",
        employee,
        ["name", "employee_name", "employee_number", "department", "designation", "status", "company", "date_of_joining"],
        as_dict=True,
    )
    if not emp:
        frappe.throw(_("پرسنل یافت نشد."), frappe.DoesNotExistError)
    if emp.company != company:
        frappe.throw(_("پرسنل به این شرکت تعلق ندارد."), frappe.PermissionError)
    if emp.status != "Active":
        frappe.throw(_("صدور معرفی‌نامه تنها برای پرسنل فعال مجاز است."))

    template_data = _get_active_template_data(company)
    tmpl_clauses = template_data.get("clauses", DEFAULT_TEMPLATE["clauses"])
    req_recipient = template_data.get("required_recipient", True)
    req_purpose = template_data.get("required_purpose", True)

    rec_type = recipient_type.strip() if recipient_type else "bank"
    if rec_type not in {"bank", "organization", "other"}:
        rec_type = "bank"

    bank_clean = (bank_name or "").strip()
    branch_clean = (branch_name or "").strip()
    rec_clean = (recipient_name or "").strip()

    if req_recipient:
        if rec_type == "bank" and not bank_clean:
            frappe.throw(_("نام بانک الزامی است."))
        if rec_type in {"organization", "other"} and not rec_clean:
            frappe.throw(_("نام مرجع دریافت‌کننده الزامی است."))

    purp_clean = (purpose or "").strip()
    if req_purpose and not purp_clean:
        frappe.throw(_("هدف معرفی‌نامه الزامی است."))

    if rec_type == "bank":
        clean_branch = re.sub(r"^شعبه\s*", "", branch_clean)
        recipient_display = f"{bank_clean} ـ شعبه {clean_branch}" if clean_branch else bank_clean
    else:
        recipient_display = rec_clean

    national_id, work_location = _get_employee_extra(employee)
    comp = frappe.db.get_value("Company", company, ["company_name"], as_dict=True)

    values = {
        "employee": {
            "employee_name": emp.employee_name or "",
            "employee_number": emp.employee_number or "",
            "national_id": national_id or "",
            "department": emp.department or "",
            "designation": emp.designation or "",
            "work_location": work_location or "",
            "date_of_joining": _format_jalali(emp.date_of_joining),
        },
        "company": {
            "company_name": comp.company_name if comp else company,
            "representative": "مدیرعامل",
            "representative_position": "مدیرعامل",
        },
        "letter": {
            "recipient": recipient_display,
            "recipient_type": rec_type,
            "bank_name": bank_clean,
            "branch_name": branch_clean,
            "purpose": purp_clean,
            "notes": (notes or "").strip(),
            "validity_date": (validity_date or "").strip(),
            "number": "—",
            "issue_date": "—",
        },
    }

    active_template = {
        "clauses": tmpl_clauses,
        "required_recipient": req_recipient,
        "required_purpose": req_purpose,
        "has_expiry": template_data.get("has_expiry", False),
    }
    rendered = render_snapshot(active_template, values)

    letter_id = name.strip() if name and name.strip() else make_autoname("INTRO-DRAFT-.#####")
    current_rev = int(revision) if revision else 1

    entry_doc = None
    if name and name.strip():
        existing = frappe.get_all(
            "ASOUD Form Entry",
            filters={"reference_doctype": INTRO_DOCTYPE, "reference_name": letter_id},
            fields=["name", "values_json"],
            limit_page_length=1,
        )
        if existing:
            entry_doc = frappe.get_doc("ASOUD Form Entry", existing[0].name)
            try:
                prev_data = json.loads(entry_doc.values_json)
                if revision and int(revision) != prev_data.get("revision", 1):
                    frappe.throw(_("نسخه پیش‌نویس معرفی‌نامه تغییر کرده است؛ صفحه را تازه‌سازی کنید."))
                current_rev = prev_data.get("revision", 1) + 1
            except Exception:
                pass

    letter_data = {
        "name": letter_id,
        "id": letter_id,
        "company": company,
        "employee": employee,
        "employee_name": emp.employee_name or "",
        "employee_number": emp.employee_number or "",
        "recipient_type": rec_type,
        "recipient_name": rec_clean,
        "bank_name": bank_clean,
        "branch_name": branch_clean,
        "recipient_text": recipient_display,
        "purpose": purp_clean,
        "validity_date": (validity_date or "").strip(),
        "notes": (notes or "").strip(),
        "status": "Draft",
        "number": "—",
        "issue_date": "—",
        "revision": current_rev,
        "template_version": template_data.get("revision", 1),
        "rendered_html": rendered["html"],
        "values_snapshot": rendered["values"],
        "template_snapshot": rendered["template"],
    }

    letterhead_html = _letterhead(company)
    letter_data["print_html"] = _build_print_html(letter_data, letterhead_html, False)

    payload_json = json.dumps(letter_data, ensure_ascii=False)

    if entry_doc:
        frappe.db.set_value(
            "ASOUD Form Entry",
            entry_doc.name,
            {"values_json": payload_json, "subject": f"معرفی‌نامه — {emp.employee_name}"},
        )
    else:
        form_name = _template_name(company)
        new_entry = frappe.get_doc({
            "doctype": "ASOUD Form Entry",
            "form": form_name,
            "company": company,
            "subject": f"معرفی‌نامه — {emp.employee_name}",
            "reference_doctype": INTRO_DOCTYPE,
            "reference_name": letter_id,
            "request_key": request_key,
            "values_json": payload_json,
        })
        new_entry.flags.form_service = True
        new_entry.flags.ignore_permissions = True
        new_entry.insert()

    return success(letter_data)


@frappe.whitelist()
def finalize_letter(name: str, revision: int = 0, request_key: str = "") -> dict:
    if not name:
        frappe.throw(_("شناسه معرفی‌نامه الزامی است."))
    if not request_key:
        frappe.throw(_("شناسه یکتای درخواست (request_key) الزامی است."))

    entries = frappe.get_all(
        "ASOUD Form Entry",
        filters={"reference_doctype": INTRO_DOCTYPE, "reference_name": name},
        fields=["name", "company", "values_json"],
        limit_page_length=1,
    )
    if not entries:
        entries = frappe.get_all(
            "ASOUD Form Entry",
            filters={"name": name, "reference_doctype": INTRO_DOCTYPE},
            fields=["name", "company", "values_json"],
            limit_page_length=1,
        )

    if not entries:
        frappe.throw(_("معرفی‌نامه مورد نظر برای نهایی‌سازی یافت نشد."))

    entry_row = entries[0]
    require_company(entry_row.company)
    require_roles(HR_OPERATIONAL_ROLES, company=entry_row.company)

    try:
        data = json.loads(entry_row.values_json)
    except Exception:
        frappe.throw(_("اطلاعات معرفی‌نامه مخدوش است."))

    # Idempotent return if already finalized
    if data.get("status") == "Final":
        letterhead_html = _letterhead(entry_row.company)
        data["print_html"] = _build_print_html(data, letterhead_html, True)
        return success(data)

    if revision and int(revision) != data.get("revision", 1):
        frappe.throw(_("نسخه معرفی‌نامه تغییر کرده است؛ صفحه را تازه‌سازی کنید."))

    official_number = make_autoname(SERIES)
    issue_date_str = _format_jalali(nowdate())

    data["status"] = "Final"
    data["number"] = official_number
    data["issue_date"] = issue_date_str
    data["revision"] = data.get("revision", 1) + 1

    # Re-render snapshot with official number and date:
    vals = data.get("values_snapshot", {})
    if "letter" in vals:
        vals["letter"]["number"] = official_number
        vals["letter"]["issue_date"] = issue_date_str

    template_to_use = data.get("template_snapshot") or DEFAULT_TEMPLATE
    re_rendered = render_snapshot(template_to_use, vals)
    data["rendered_html"] = re_rendered["html"]
    data["values_snapshot"] = re_rendered["values"]

    letterhead_html = _letterhead(entry_row.company)
    data["print_html"] = _build_print_html(data, letterhead_html, True)

    frappe.db.set_value(
        "ASOUD Form Entry",
        entry_row.name,
        {"values_json": json.dumps(data, ensure_ascii=False)},
    )

    return success(data)
