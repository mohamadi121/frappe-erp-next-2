"""Employment Contracts API: versioned template builder and personnel contracts issuance."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.employment_contract import (
    DEFAULT_CLAUSES,
    DEFAULT_SALARY_ROWS,
    calculate_salary_items,
    generate_contract_print_data,
    get_field_catalog,
    mask_contract_salary,
    normalize_search_term,
    render_contract_articles,
    validate_contract_template,
)
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.jalali import gregorian_to_jalali
from asoud_erp.services.request_access import require_company

TEMPLATE_DESIGNERS = ("System Manager", "HR Manager")
HR_OPERATIONAL_ROLES = ("System Manager", "HR Manager", "HR User")
PAYROLL_ROLES = ("System Manager", "Payroll Manager", "Accounts Manager")


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
    return hashlib.sha256(f"asoud-contract-template:{company}".encode()).hexdigest()[:32]


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
    head = frappe.db.get_value("Letter Head", name, ["disabled", "source", "content", "image"], as_dict=True) if name else None
    if not head or head.disabled:
        return None
    if head.source == "Image" and head.image:
        file_name = frappe.db.get_value("File", {"file_url": head.image}, "name")
        if file_name:
            data = frappe.get_doc("File", file_name).get_content()
            data = data.encode() if isinstance(data, str) else data
            return '<img style="max-height:80px" src="data:image/png;base64,' + base64.b64encode(data).decode() + '">'
    return head.content or None


def _ensure_company_contract_template(company: str) -> str:
    name = _template_name(company)
    if not frappe.db.exists("ASOUD Form", name):
        normalized = validate_contract_template(DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS)
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        doc = frappe.get_doc({
            "doctype": "ASOUD Form",
            "name": name,
            "company": company,
            "kind": "Document",
            "module_key": "HR",
            "title": normalized["title"],
            "draft_json": encoded,
            "draft_version": 1,
        })
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.insert(set_name=name)
    return name


def _get_active_template_data(company: str) -> dict[str, Any]:
    name = _ensure_company_contract_template(company)
    if frappe.db.exists("ASOUD Form", name):
        doc = frappe.get_doc("ASOUD Form", name)
        if doc.active_revision:
            rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
            try:
                parsed = json.loads(rev.schema_json)
                parsed["template_id"] = doc.name
                parsed["company"] = company
                parsed["version"] = rev.version
                return parsed
            except Exception:
                pass
        if doc.draft_json:
            try:
                parsed = json.loads(doc.draft_json)
                parsed["template_id"] = doc.name
                parsed["company"] = company
                parsed["version"] = doc.draft_version or 1
                return parsed
            except Exception:
                pass
    return {
        "template_id": name,
        "company": company,
        "title": "قالب قرارداد کار",
        "version": 1,
        "clauses": DEFAULT_CLAUSES,
        "salary_rows": DEFAULT_SALARY_ROWS,
    }


@frappe.whitelist()
def get_contract_template(company: str, template_id: str | None = None) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    name = template_id or _template_name(company)
    designer = _is_designer()

    if frappe.db.exists("ASOUD Form", name):
        doc = frappe.get_doc("ASOUD Form", name)
        if doc.company != company:
            frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)

        has_draft = bool(doc.draft_json)
        draft_version = doc.draft_version or 1
        active_version = 0

        clauses = DEFAULT_CLAUSES
        salary_rows = DEFAULT_SALARY_ROWS
        title = doc.title or "قالب قرارداد کار"

        if doc.active_revision:
            rev = frappe.get_doc("ASOUD Form Revision", doc.active_revision)
            active_version = rev.version
            if not (designer and has_draft):
                try:
                    schema = json.loads(rev.schema_json)
                    clauses = schema.get("clauses", clauses)
                    salary_rows = schema.get("salary_rows", salary_rows)
                    title = schema.get("title", title)
                except Exception:
                    pass

        if designer and has_draft:
            try:
                schema = json.loads(doc.draft_json)
                clauses = schema.get("clauses", clauses)
                salary_rows = schema.get("salary_rows", salary_rows)
                title = schema.get("title", title)
            except Exception:
                pass

        return success({
            "template_id": doc.name,
            "title": title,
            "company": company,
            "version": active_version or 1,
            "draft_version": draft_version,
            "has_draft": has_draft,
            "can_edit_template": designer,
            "clauses": clauses,
            "salary_rows": salary_rows,
        })

    return success({
        "template_id": name,
        "title": "قالب قرارداد کار",
        "company": company,
        "version": 1,
        "draft_version": 1,
        "has_draft": False,
        "can_edit_template": designer,
        "clauses": DEFAULT_CLAUSES,
        "salary_rows": DEFAULT_SALARY_ROWS,
    })


@frappe.whitelist()
def save_contract_template(company: str, clauses: Any, salary_rows: Any, title: str = "قالب قرارداد کار",
                           expected_version: int = 0, client_id: str | None = None,
                           workflow: str | None = None) -> dict:
    require_company(company)
    require_roles(TEMPLATE_DESIGNERS, company=company)

    if isinstance(clauses, str):
        try:
            clauses = json.loads(clauses)
        except Exception:
            frappe.throw(_("فرمت اطلاعات مواد قرارداد نامعتبر است."))
    if isinstance(salary_rows, str):
        try:
            salary_rows = json.loads(salary_rows)
        except Exception:
            frappe.throw(_("فرمت اطلاعات اقلام حقوقی نامعتبر است."))

    if workflow:
        from asoud_erp.services.employment_contract_workflow import validate_workflow
        validate_workflow(workflow, company)

    try:
        normalized = validate_contract_template(clauses, salary_rows, title, workflow=workflow)
    except ValueError as err:
        frappe.throw(str(err))

    name = _template_name(company)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)

    if frappe.db.exists("ASOUD Form", name):
        doc = frappe.get_doc("ASOUD Form", name)
        if doc.company != company:
            frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)
        if int(expected_version) != 0 and int(expected_version) != doc.draft_version:
            frappe.throw(_("نسخه پیش‌نویس قالب تغییر کرده است؛ لطفاً صفحه را تازه‌سازی کنید."))
        doc.draft_json = encoded
        doc.draft_version = (doc.draft_version or 1) + 1
        doc.title = normalized["title"]
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.save()
    else:
        doc = frappe.get_doc({
            "doctype": "ASOUD Form",
            "name": name,
            "company": company,
            "kind": "Document",
            "module_key": "HR",
            "title": normalized["title"],
            "draft_json": encoded,
            "draft_version": 1,
        })
        doc.flags.form_service = True
        doc.flags.ignore_permissions = True
        doc.insert(set_name=name)

    return success({
        "template_id": doc.name,
        "company": company,
        "title": doc.title,
        "draft_version": doc.draft_version,
        "clauses": normalized["clauses"],
        "salary_rows": normalized["salary_rows"],
    })


@frappe.whitelist()
def publish_contract_template(company: str, template_id: str | None = None, expected_version: int = 0,
                              change_note: str = "") -> dict:
    require_company(company)
    require_roles(TEMPLATE_DESIGNERS, company=company)

    name = template_id or _template_name(company)
    if not frappe.db.exists("ASOUD Form", name):
        save_contract_template(company, DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS)

    doc = frappe.get_doc("ASOUD Form", name)
    if doc.company != company:
        frappe.throw(_("دسترسی به قالب این شرکت مجاز نیست."), frappe.PermissionError)

    if int(expected_version) != 0 and int(expected_version) != doc.draft_version:
        frappe.throw(_("نسخه پیش‌نویس قالب تغییر کرده است؛ لطفاً صفحه را تازه‌سازی کنید."))

    schema_json = doc.draft_json or json.dumps({
        "title": doc.title or "قالب قرارداد کار",
        "clauses": DEFAULT_CLAUSES,
        "salary_rows": DEFAULT_SALARY_ROWS,
    }, ensure_ascii=False)

    version = int(frappe.db.count("ASOUD Form Revision", {"form": doc.name})) + 1
    rev = frappe.get_doc({
        "doctype": "ASOUD Form Revision",
        "form": doc.name,
        "version": version,
        "schema_json": schema_json,
        "published_by": frappe.session.user,
        "published_on": now_datetime(),
        "change_note": (change_note or "")[:500],
    })
    rev.flags.form_service = True
    rev.flags.ignore_permissions = True
    rev.insert()

    doc.active_revision = rev.name
    doc.draft_version = (doc.draft_version or 1) + 1
    doc.flags.form_service = True
    doc.flags.ignore_permissions = True
    doc.save()

    return success({
        "template_id": doc.name,
        "version": rev.version,
        "draft_version": doc.draft_version,
        "published_on": str(rev.published_on),
    })


@frappe.whitelist()
def get_contract_field_catalog(company: str) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)
    has_payroll = _has_payroll_permission(company)
    return success(get_field_catalog(has_payroll_permission=has_payroll))


@frappe.whitelist()
def prepare_contract(company: str, employee: str, template_version: int | None = None) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    if not frappe.db.exists("Employee", employee):
        frappe.throw(_("پرسنل مورد نظر در سیستم یافت نشد."))

    emp = frappe.db.get_value(
        "Employee", employee,
        ["name", "employee_name", "first_name", "last_name", "father_name", "national_id",
         "department", "designation", "date_of_joining", "cell_number", "current_address",
         "current_postal_code", "company"],
        as_dict=True,
    )
    if emp.company != company:
        frappe.throw(_("این پرسنل متعلق به شرکت دیگری است."), frappe.PermissionError)

    comp = frappe.db.get_value(
        "Company", company,
        ["company_name", "tax_id", "phone_no", "email"],
        as_dict=True,
    )

    template_data = _get_active_template_data(company)
    clauses = template_data.get("clauses", DEFAULT_CLAUSES)
    salary_rows = template_data.get("salary_rows", DEFAULT_SALARY_ROWS)

    has_payroll = _has_payroll_permission(company)
    salary_values: dict[str, Any] = {}

    if has_payroll:
        assignments = frappe.get_all(
            "Salary Structure Assignment",
            filters={"employee": employee, "company": company, "docstatus": 1, "from_date": ["<=", nowdate()]},
            fields=["base", "variable", "currency"],
            order_by="from_date desc, creation desc",
            limit_page_length=1,
        )
        if assignments and assignments[0].base:
            salary_values["payroll.base_salary"] = assignments[0].base

    salary_calc = calculate_salary_items(salary_rows if has_payroll else [], salary_values)

    context = {
        "personnel": {
            "employee_name": emp.employee_name or "",
            "first_name": emp.first_name or "",
            "last_name": emp.last_name or "",
            "father_name": emp.father_name or "",
            "national_id": emp.national_id or "",
            "employee_number": emp.name,
            "department": emp.department or "",
            "job_title": emp.designation or "",
            "date_of_joining": _format_jalali(emp.date_of_joining),
            "mobile": emp.cell_number or "",
            "address": emp.current_address or "",
            "postal_code": emp.current_postal_code or "",
        },
        "company": {
            "company_name": comp.company_name or company,
            "national_id": comp.tax_id or "",
            "legal_representative": comp.company_name or "",
            "phone": comp.phone_no or "",
            "email": comp.email or "",
        },
        "contract": {
            "contract_type": "مدت‌معین",
            "start_date": _format_jalali(nowdate()),
            "end_date": "",
            "work_location": comp.company_name or "",
            "creation_date": _format_jalali(nowdate()),
        },
    }

    rendered_clauses = render_contract_articles(clauses, context)

    return success({
        "employee_info": context["personnel"],
        "company_info": context["company"],
        "template_version": template_data.get("version", 1),
        "rendered_clauses": rendered_clauses,
        "salary_table": salary_calc["items"],
        "total_monthly": salary_calc["total_monthly"],
        "formatted_total_monthly": salary_calc["formatted_total_monthly"],
    })


@frappe.whitelist()
def list_contracts(company: str, search: str | None = None, status: str | None = None,
                   start: int = 0, page_length: int = 20) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    company_employees = frappe.get_all("Employee", filters={"company": company}, pluck="name")
    if not company_employees:
        return success([], meta={"total": 0, "start": int(start), "page_length": int(page_length)})

    filters: dict[str, Any] = {
        "party_type": "Employee",
        "party_name": ["in", company_employees],
    }

    status_str = (status or "all").strip().lower()
    if status_str in {"draft", "پیش‌نویس"}:
        filters["docstatus"] = 0
        filters["status"] = ["!=", "In Progress"]
    elif status_str in {"in_progress", "در جریان"}:
        filters["docstatus"] = 0
        filters["status"] = "In Progress"
    elif status_str in {"final", "نهایی"}:
        filters["docstatus"] = 1
    else:
        filters["docstatus"] = ["<", 2]

    contracts = frappe.get_all(
        "Contract",
        filters=filters,
        fields=["name", "party_name", "party_full_name", "start_date", "end_date",
                "status", "is_signed", "docstatus", "creation"],
        order_by="creation desc",
    )

    # Link each contract with its snapshot in ASOUD Form Entry if available
    contract_names = [c.name for c in contracts]
    entries = {}
    if contract_names:
        raw_entries = frappe.get_all(
            "ASOUD Form Entry",
            filters={"reference_doctype": "Contract", "reference_name": ["in", contract_names]},
            fields=["reference_name", "values_json", "revision"],
        )
        for e in raw_entries:
            try:
                entries[e.reference_name] = json.loads(e.values_json)
            except Exception:
                entries[e.reference_name] = {}

    norm_query = normalize_search_term(search)

    rows = []
    for c in contracts:
        snap = entries.get(c.name, {})
        contract_number = snap.get("contract_number") or c.name

        emp_code = c.party_name or ""
        emp_name = c.party_full_name or ""

        if norm_query:
            searchable = f"{normalize_search_term(emp_name)} {normalize_search_term(emp_code)} {normalize_search_term(contract_number)}"
            if norm_query not in searchable:
                continue

        status_label = "پیش‌نویس"
        status_code = "draft"
        if c.docstatus == 1:
            status_label = "نهایی"
            status_code = "final"
        elif c.status == "In Progress":
            status_label = "در جریان"
            status_code = "in_progress"

        rows.append({
            "name": contract_number,
            "contract_id": c.name,
            "employee": emp_code,
            "employee_name": emp_name,
            "contract_type": snap.get("contract_type") or "مدت‌معین",
            "start_date": str(c.start_date or ""),
            "end_date": str(c.end_date or ""),
            "jalali_start_date": _format_jalali(c.start_date),
            "jalali_end_date": _format_jalali(c.end_date),
            "status": status_label,
            "status_code": status_code,
            "docstatus": c.docstatus,
            "is_signed": cint(c.is_signed),
            "template_version": snap.get("template_version", 1),
        })

    total = len(rows)
    start_idx = max(0, int(start))
    limit = max(1, int(page_length))
    paginated = rows[start_idx: start_idx + limit]

    return success(paginated, meta={"total": total, "start": start_idx, "page_length": limit})


@frappe.whitelist()
def save_contract_draft(company: str, employee: str, start_date: str, end_date: str | None = None,
                        contract_type: str = "مدت‌معین", work_location: str | None = None,
                        subject: str | None = None, notes: str | None = None,
                        salary_values: Any = None, contract_id: str | None = None,
                        client_id: str | None = None, revision: int = 0,
                        workflow: str | None = None) -> dict:
    require_company(company)
    require_roles(HR_OPERATIONAL_ROLES, company=company)

    if len(str(notes or "")) > 10000:
        frappe.throw(_("طول یادداشت قرارداد بیش از حد مجاز است."))
    if len(str(work_location or "")) > 500:
        frappe.throw(_("طول محل کار بیش از حد مجاز است."))

    if not frappe.db.exists("Employee", employee):
        frappe.throw(_("پرسنل مورد نظر در سیستم یافت نشد."))
    emp = frappe.db.get_value("Employee", employee, ["name", "employee_name", "company"], as_dict=True)
    if emp.company != company:
        frappe.throw(_("این پرسنل متعلق به شرکت دیگری است."), frappe.PermissionError)

    if client_id and not contract_id:
        existing_entry = frappe.db.get_value(
            "ASOUD Form Entry",
            {"fingerprint": client_id, "company": company},
            ["reference_name"],
            as_dict=True,
        )
        if existing_entry and frappe.db.exists("Contract", existing_entry.reference_name):
            return get_contract(existing_entry.reference_name)

    # Stored amounts are resolved at the effective date; client amounts are never authoritative.
    assignments = frappe.get_all(
        "Salary Structure Assignment",
        filters={"employee": employee, "company": company, "docstatus": 1,
                 "from_date": ["<=", getdate(start_date)]},
        fields=["base"], order_by="from_date desc, creation desc", limit_page_length=1,
    )
    salary_values = {"payroll.base_salary": assignments[0].base} if assignments else {}

    template_data = _get_active_template_data(company)
    clauses = template_data.get("clauses", DEFAULT_CLAUSES)
    salary_rows = template_data.get("salary_rows", DEFAULT_SALARY_ROWS)

    salary_calc = calculate_salary_items(salary_rows, salary_values)

    context = {
        "personnel": {
            "employee_name": emp.employee_name or "",
            "employee_number": emp.name,
        },
        "company": {
            "company_name": company,
            "legal_representative": company,
        },
        "contract": {
            "contract_type": contract_type or "مدت‌معین",
            "start_date": _format_jalali(start_date),
            "end_date": _format_jalali(end_date),
            "work_location": work_location or company,
            "creation_date": _format_jalali(nowdate()),
        },
    }
    rendered_clauses = render_contract_articles(clauses, context)

    if contract_id:
        contract = frappe.get_doc("Contract", contract_id)
        if contract.party_type != "Employee" or contract.party_name != employee:
            frappe.throw(_("این قرارداد متعلق به این پرسنل نیست."), frappe.PermissionError)
        if contract.docstatus != 0:
            frappe.throw(_("قرارداد نهایی‌شده قابل ویرایش نیست."))
    else:
        contract = frappe.new_doc("Contract")
        contract.party_type = "Employee"
        contract.party_name = employee

    contract.update({
        "party_full_name": emp.employee_name,
        "start_date": getdate(start_date),
        "end_date": getdate(end_date) if end_date else None,
        "is_signed": 0,
        "status": "Unsigned",
    })

    print_data = generate_contract_print_data(
        is_draft=True,
        contract_number="شماره پس از صدور",
        issue_date=_format_jalali(nowdate()),
        employee_name=emp.employee_name,
        rendered_clauses=rendered_clauses,
        salary_table=salary_calc["items"],
        total_monthly_formatted=salary_calc["formatted_total_monthly"],
        company_name=company,
    )
    contract.contract_terms = print_data["html"]
    contract.flags.ignore_permissions = True
    contract.save()

    contract_wf = workflow or template_data.get("workflow", "")
    if contract_wf:
        from asoud_erp.services.employment_contract_workflow import validate_workflow
        validate_workflow(contract_wf, company)

    snapshot = {
        "contract_id": contract.name,
        "contract_number": "پیش‌نویس",
        "contract_type": contract_type or "مدت‌معین",
        "work_location": work_location or company,
        "notes": notes or "",
        "template_version": template_data.get("version", 1),
        "template_snapshot": {"workflow": contract_wf},
        "workflow": contract_wf,
        "rendered_clauses": rendered_clauses,
        "salary_table": salary_calc["items"],
        "total_monthly": salary_calc["total_monthly"],
        "formatted_total_monthly": salary_calc["formatted_total_monthly"],
        "salary_values": salary_values,
        "is_draft": True,
    }

    template_name = template_data.get("template_id") or _template_name(company)
    existing_entry_name = frappe.db.get_value(
        "ASOUD Form Entry",
        {"reference_doctype": "Contract", "reference_name": contract.name},
        "name",
    )
    current_rev = 1
    if existing_entry_name:
        prev_data = json.loads(frappe.db.get_value("ASOUD Form Entry", existing_entry_name, "values_json") or "{}")
        if prev_data.get("status") in {"final", "pending", "in_progress"}:
            frappe.throw(_("قرارداد نهایی‌شده قابل ویرایش نیست."))
        if revision and int(revision) != 0 and prev_data.get("revision", 1) != int(revision):
            frappe.throw(_("این قرارداد توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))
        current_rev = prev_data.get("revision", 1) + 1

    snapshot["revision"] = current_rev
    snapshot["status"] = "draft"

    if existing_entry_name:
        frappe.db.set_value("ASOUD Form Entry", existing_entry_name, "values_json", json.dumps(snapshot, ensure_ascii=False))
    else:
        entry = frappe.get_doc({
            "doctype": "ASOUD Form Entry",
            "form": template_name,
            "company": company,
            "subject": subject or f"قرارداد کار {emp.employee_name}",
            "values_json": json.dumps(snapshot, ensure_ascii=False),
            "reference_doctype": "Contract",
            "reference_name": contract.name,
            "fingerprint": client_id,
        })
        entry.flags.form_service = True
        entry.flags.ignore_permissions = True
        entry.insert()

    return success({
        "contract_id": contract.name,
        "contract_number": "پیش‌نویس",
        "employee": employee,
        "employee_name": emp.employee_name,
        "start_date": str(contract.start_date),
        "end_date": str(contract.end_date or ""),
        "status": "پیش‌نویس",
        "is_draft": True,
        "revision": current_rev,
    })


@frappe.whitelist()
def finalize_contract(contract_id: str, client_id: str | None = None,
                      revision: int | None = None, request_id: str | None = None) -> dict:
    if not frappe.db.exists("Contract", contract_id):
        frappe.throw(_("قرارداد مورد نظر یافت نشد."))

    contract = frappe.get_doc("Contract", contract_id)
    emp_company = frappe.db.get_value("Employee", contract.party_name, "company")
    require_company(emp_company)
    require_roles(HR_OPERATIONAL_ROLES, company=emp_company)

    from asoud_erp.services.employment_contract_workflow import submit

    res = submit(contract_id, revision=revision, request_id=request_id or client_id)
    return success(res)


@frappe.whitelist()
def send_contract_for_review(contract_id: str, revision: int | None = None, request_id: str | None = None) -> dict:
    return finalize_contract(contract_id=contract_id, revision=revision, request_id=request_id)


@frappe.whitelist()
def get_contract(contract_id: str) -> dict:
    if not frappe.db.exists("Contract", contract_id):
        frappe.throw(_("قرارداد مورد نظر یافت نشد."))

    contract = frappe.get_doc("Contract", contract_id)
    emp_company = frappe.db.get_value("Employee", contract.party_name, "company")
    require_company(emp_company)
    require_roles(HR_OPERATIONAL_ROLES, company=emp_company)

    entry_name = frappe.db.get_value(
        "ASOUD Form Entry",
        {"reference_doctype": "Contract", "reference_name": contract.name},
        "name",
    )
    snapshot = {}
    if entry_name:
        try:
            snapshot = json.loads(frappe.db.get_value("ASOUD Form Entry", entry_name, "values_json") or "{}")
        except Exception:
            snapshot = {}

    if not _has_payroll_permission(emp_company):
        snapshot = mask_contract_salary(snapshot)

    is_draft = contract.docstatus == 0
    contract_number = snapshot.get("contract_number") if not is_draft else "پیش‌نویس"

    print_payload = generate_contract_print_data(
        is_draft=is_draft,
        contract_number=contract_number,
        issue_date=snapshot.get("issue_date", _format_jalali(contract.creation)),
        employee_name=snapshot.get("employee_name", contract.party_full_name),
        rendered_clauses=snapshot.get("rendered_clauses", []),
        salary_table=snapshot.get("salary_table", []),
        total_monthly_formatted=snapshot.get("formatted_total_monthly", ""),
        letterhead_html=_letterhead(emp_company) if is_draft else snapshot.get("letterhead_html"),
        company_name=emp_company,
    )

    return success({
        "contract_id": contract.name,
        "contract_number": contract_number,
        "employee": contract.party_name,
        "employee_name": contract.party_full_name,
        "company": emp_company,
        "start_date": str(contract.start_date or ""),
        "end_date": str(contract.end_date or ""),
        "jalali_start_date": _format_jalali(contract.start_date),
        "jalali_end_date": _format_jalali(contract.end_date),
        "status": "نهایی" if contract.docstatus == 1 else (snapshot.get("status_label") or ("در جریان" if contract.status == "In Progress" else ("ردشده" if contract.status == "Rejected" else "پیش‌نویس"))),
        "docstatus": contract.docstatus,
        "is_signed": cint(contract.is_signed),
        "revision": snapshot.get("revision", 1),
        "template_version": snapshot.get("template_version", 1),
        "rendered_clauses": snapshot.get("rendered_clauses", []),
        "salary_table": snapshot.get("salary_table", []),
        "total_monthly": snapshot.get("total_monthly", 0),
        "formatted_total_monthly": snapshot.get("formatted_total_monthly", ""),
        "print_payload": print_payload,
    })


@frappe.whitelist()
def get_contract_print(contract_id: str) -> dict:
    detail = get_contract(contract_id)
    return success(detail["data"]["print_payload"])
