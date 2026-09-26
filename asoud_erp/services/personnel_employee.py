"""Employee owns shared HR fields; Party Profile owns Iranian extensions.

Profile columns are retained for backwards compatibility, never preferred over
an existing Employee. This module does not create payroll or employment masters.
"""
import hashlib

import frappe

# Keys also kept as columns on ASOUD Party Profile (legacy search cache).
PROFILE_CACHE_FIELDS = {
    "display_name": "employee_name", "mobile": "cell_number", "email": "personal_email",
    "birth_date": "date_of_birth", "date_of_joining": "date_of_joining",
    "employee_gender": "gender", "job_title": "designation", "department": "department",
    "employment_type": "employment_type", "address_line": "current_address",
}

EMPLOYEE_FIELDS = {
    **PROFILE_CACHE_FIELDS,
    "marital_status": "marital_status", "blood_group": "blood_group",
    "emergency_contact_name": "person_to_be_contacted", "emergency_phone": "emergency_phone_number",
    "emergency_relation": "relation", "company_email": "company_email", "branch": "branch",
    "reports_to": "reports_to", "final_confirmation_date": "final_confirmation_date",
    "contract_end_date": "contract_end_date", "notice_number_of_days": "notice_number_of_days",
}

# Persian labels of Employee fields, for change history. Values are never exposed.
EMPLOYEE_FIELD_LABELS = {
    "employee_name": "نام", "cell_number": "موبایل", "personal_email": "ایمیل",
    "date_of_birth": "تولد", "date_of_joining": "شروع کار", "gender": "جنسیت",
    "designation": "سمت", "department": "واحد سازمانی", "employment_type": "نوع استخدام",
    "current_address": "آدرس", "marital_status": "وضعیت تأهل", "blood_group": "گروه خونی",
    "person_to_be_contacted": "تماس اضطراری", "emergency_phone_number": "تلفن اضطراری",
    "relation": "نسبت تماس اضطراری", "company_email": "ایمیل سازمانی", "branch": "شعبه",
    "reports_to": "مدیر مستقیم", "final_confirmation_date": "پایان دوره آزمایشی",
    "contract_end_date": "پایان قرارداد", "notice_number_of_days": "مهلت اعلام",
    "bank_name": "اطلاعات بانکی", "bank_ac_no": "اطلاعات بانکی", "iban": "اطلاعات بانکی",
    "status": "وضعیت همکاری", "relieving_date": "تاریخ پایان همکاری", "image": "تصویر",
}

LINK_FIELDS = {"job_title": ("Designation", "designation_name"),
               "department": ("Department", "department_name"),
               "employment_type": ("Employment Type", "employee_type_name"),
               "branch": ("Branch", "branch"),
               "reports_to": ("Employee", "employee_name")}


def resolve_link(key, value, company):
    if not value or key not in LINK_FIELDS:
        return value
    doctype, title_field = LINK_FIELDS[key]
    if frappe.db.exists(doctype, value):
        return value
    filters = {title_field: value}
    if key in {"department", "reports_to"}:
        filters["company"] = company
    matches = frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=2)
    if len(matches) != 1:
        frappe.throw(f"Select an existing {doctype}; the supplied name is missing or ambiguous")
    return matches[0]


def profile_options(company):
    result = {}
    for key, (doctype, _) in LINK_FIELDS.items():
        if key == "reports_to":
            continue
        filters = {"company": company, "is_group": 0} if key == "department" else {}
        result[key] = frappe.get_all(doctype, filters=filters, pluck="name", order_by="name", limit_page_length=0)
    result["reports_to"] = frappe.get_all("Employee", filters={"company": company, "status": "Active"},
                                          fields=["name", "employee_name", "designation"],
                                          order_by="employee_name", limit_page_length=0)
    return result


def employee_for(person, lock=False):
    if not person.get("employee"):
        frappe.throw("Link this profile to an Employee before recording HR transactions")
    if lock:
        frappe.db.sql("select name from `tabEmployee` where name=%s for update", (person.employee,))
    employee = frappe.get_doc("Employee", person.employee, for_update=lock)
    if employee.company != person.company:
        frappe.throw("Employee company mismatch", frappe.PermissionError)
    return employee


def shared_values(person):
    if not person.get("employee"):
        return {}
    employee = employee_for(person)
    result = {key: str(employee.get(field) or "") for key, field in EMPLOYEE_FIELDS.items()
              if employee.meta.has_field(field)}
    result["employee_status"] = employee.status
    result["disabled"] = employee.status != "Active"
    return result


def profile_revision(person, lock=False):
    employee = employee_for(person, lock=lock) if person.get("employee") else None
    value = f"{person.modified}|{employee.name if employee else ''}|{employee.modified if employee else ''}"
    return hashlib.sha256(value.encode()).hexdigest()


def write_shared(person, values):
    employee = employee_for(person, lock=True)
    for key, target in EMPLOYEE_FIELDS.items():
        if key not in values:
            continue
        if not employee.meta.has_field(target):
            if values[key]:
                frappe.throw(f"Employee field {target} is unavailable; install the matching HRMS version")
            continue
        value = resolve_link(key, values[key] or None, employee.company)
        if key == "display_name":
            if not str(value or "").strip():
                frappe.throw("Name is required")
            if str(value).strip() != employee.employee_name:
                employee.first_name = str(value).strip()
                employee.middle_name = None
                employee.last_name = None
            continue
        # Link validation is intentionally left to the standard controller.
        employee.set(target, value)
    if "department" in values and employee.department:
        company = frappe.db.get_value("Department", employee.department, "company")
        if company and company != employee.company:
            frappe.throw("Department company mismatch")
    if "reports_to" in values and employee.reports_to:
        if employee.reports_to == employee.name:
            frappe.throw("An employee cannot report to themselves")
        if frappe.db.get_value("Employee", employee.reports_to, "company") != employee.company:
            frappe.throw("The manager must belong to the same company")
    employee.save(ignore_permissions=True)
    return employee


def refresh_profile_cache(employee, method=None):
    """Keep legacy search columns usable after a change made in ERPNext itself."""
    values = {key: employee.get(field) for key, field in PROFILE_CACHE_FIELDS.items()
              if employee.meta.has_field(field)}
    for name in frappe.get_all("ASOUD Party Profile", filters={"employee": employee.name,
                              "company": employee.company}, pluck="name"):
        # The Employee controller has already validated and authorized the write.
        frappe.db.set_value("ASOUD Party Profile", name, values, update_modified=False)
