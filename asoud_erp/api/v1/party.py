import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.detail_code_service import next_detail_code
from asoud_erp.services.party_validation import (
    is_valid_iranian_legal_id,
    is_valid_iranian_mobile,
    is_valid_iranian_national_code,
    normalize_optional,
)

ALLOWED_ROLES = {"Customer", "Supplier", "Employee", "Shareholder", "Other"}
PARTY_ROLES_WITH_DEFAULT_GROUP = ("Customer", "Supplier", "Employee")


def _default_group_for_role(role: str) -> str | None:
    return frappe.db.get_value(
        "ASOUD Detail Group", {"party_role": role, "disabled": 0}, "name"
    )


def _parse_detail_groups(detail_groups: str | list[str] | None) -> list[str]:
    if not detail_groups:
        return []
    values = json.loads(detail_groups) if isinstance(detail_groups, str) else detail_groups
    normalized = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    for group in normalized:
        if not frappe.db.exists("ASOUD Detail Group", group):
            frappe.throw(_("Detail group does not exist"))
        if int(frappe.db.get_value("ASOUD Detail Group", group, "disabled") or 0):
            frappe.throw(_("Disabled detail group cannot be selected"))
    return normalized


def _parse_roles(roles: str | list[str]) -> list[str]:
    values = json.loads(roles) if isinstance(roles, str) else roles
    normalized = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    invalid = set(normalized) - ALLOWED_ROLES
    if invalid or not normalized:
        frappe.throw(_("Select at least one valid party role"))
    return normalized


def _ensure_customer(title: str, party_type: str, national_id: str | None) -> str:
    existing = frappe.db.exists("Customer", {"tax_id": national_id}) if national_id else None
    if existing:
        return str(existing)
    doc = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": title,
            "customer_type": "Individual" if party_type == "Individual" else "Company",
            "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group"),
            "territory": frappe.db.get_single_value("Selling Settings", "territory"),
            "tax_id": national_id,
        }
    )
    doc.insert()
    return doc.name


def _ensure_supplier(title: str, party_type: str, national_id: str | None) -> str:
    existing = frappe.db.exists("Supplier", {"tax_id": national_id}) if national_id else None
    if existing:
        return str(existing)
    doc = frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": title,
            "supplier_type": "Individual" if party_type == "Individual" else "Company",
            "supplier_group": frappe.db.get_single_value("Buying Settings", "supplier_group"),
            "tax_id": national_id,
        }
    )
    doc.insert()
    return doc.name


def _ensure_employee(
    employee: str | None,
    title: str,
    company: str | None,
    gender: str | None,
    birth_date: str | None,
    date_of_joining: str | None,
    mobile: str | None,
    email: str | None,
) -> str:
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("A valid company is required for an employee"))
    if not gender or not frappe.db.exists("Gender", gender):
        frappe.throw(_("Select a valid gender for the employee"))
    if not birth_date:
        frappe.throw(_("Birth date is required for the employee"))
    if not date_of_joining:
        frappe.throw(_("Date of joining is required for the employee"))

    doc = frappe.get_doc("Employee", employee) if employee else frappe.new_doc("Employee")
    if not employee:
        naming_series = frappe.get_meta("Employee").get_field("naming_series")
        doc.naming_series = next(
            (value for value in (naming_series.options or "").splitlines() if value),
            "HR-EMP-",
        )
    doc.first_name = title
    doc.company = company
    doc.status = "Active"
    doc.gender = gender
    doc.date_of_birth = birth_date
    doc.date_of_joining = date_of_joining
    doc.cell_number = mobile
    doc.personal_email = email
    doc.save(ignore_permissions=True) if employee else doc.insert(ignore_permissions=True)
    return doc.name


def _sync_floating_details(
    profile_name: str,
    title: str,
    roles: list[str],
    primary_role: str | None = None,
    detail_group: str | None = None,
    detail_groups: list[str] | None = None,
) -> None:
    settings = frappe.get_single("ASOUD Settings")
    digits = int(settings.detail_code_digits or 5)
    requested_groups = list(detail_groups or [])
    group_roles: dict[str, str] = {}
    for role in PARTY_ROLES_WITH_DEFAULT_GROUP:
        if role not in roles:
            continue
        default_group = _default_group_for_role(role)
        if not default_group:
            continue
        group = detail_group if role == primary_role and detail_group else default_group
        group_roles[group] = role
        if group not in requested_groups:
            requested_groups.append(group)
    for group in requested_groups:
        if not frappe.db.exists("ASOUD Detail Group", group):
            frappe.throw(_("Detail group does not exist"))
        exists = frappe.db.exists(
            "ASOUD Floating Detail",
            {"linked_doctype": "ASOUD Party Profile", "linked_document": profile_name, "detail_group": group},
        )
        if exists:
            frappe.db.set_value("ASOUD Floating Detail", exists, "title", title)
            continue
        frappe.get_doc(
            {
                "doctype": "ASOUD Floating Detail",
                "detail_code": next_detail_code(group, digits),
                "title": title,
                "detail_type": group_roles.get(group, primary_role or "Other"),
                "detail_group": group,
                "linked_doctype": "ASOUD Party Profile",
                "linked_document": profile_name,
            }
        ).insert()


@frappe.whitelist()
def list_parties(search: str | None = None, role: str | None = None, company: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    filters = {"disabled": 0}
    if company:
        filters["company"] = company
    if role:
        filters["roles_text"] = ["like", f'%"{role}"%']
    or_filters = None
    if search:
        term = f"%{search}%"
        or_filters = {"display_name": ["like", term], "national_id": ["like", term], "mobile": ["like", term]}
    rows = frappe.get_all(
        "ASOUD Party Profile",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "company",
            "party_type",
            "display_name",
            "national_id",
            "mobile",
            "phone",
            "email",
            "website",
            "province",
            "city",
            "address_line",
            "postal_code",
            "bank_name",
            "iban",
            "account_number",
            "birth_date",
            "employee_gender",
            "date_of_joining",
            "father_name",
            "birth_certificate_number",
            "birth_certificate_issue_place",
            "employment_type",
            "job_title",
            "department",
            "description",
            "alias_name",
            "manager_name",
            "registration_number",
            "economic_code",
            "founding_date",
            "secondary_phone",
            "credit_limit",
            "opening_balance",
            "balance_type",
            "card_number",
            "account_holder",
            "region",
            "neighborhood",
            "plaque",
            "unit",
            "latitude",
            "longitude",
            "employee_roles",
            "roles_text",
            "customer",
            "supplier",
            "employee",
            "disabled",
        ],
        order_by="modified desc",
        limit_page_length=200,
    )
    for row in rows:
        row["roles"] = json.loads(row.pop("roles_text") or "[]")
        details = frappe.get_all(
            "ASOUD Floating Detail",
            filters={
                "linked_doctype": "ASOUD Party Profile",
                "linked_document": row["name"],
                "disabled": 0,
            },
            fields=["name", "detail_code", "detail_group", "detail_type"],
            order_by="detail_code asc",
            limit_page_length=0,
        )
        for detail in details:
            detail["group_title"] = frappe.db.get_value(
                "ASOUD Detail Group", detail["detail_group"], "group_name"
            )
        row["floating_details"] = details
        row["detail_groups"] = [value["detail_group"] for value in details]
    return success(rows)


@frappe.whitelist(methods=["POST"])
def save_party(
    party_type: str,
    display_name: str,
    roles: str | list[str],
    national_id: str | None = None,
    mobile: str | None = None,
    email: str | None = None,
    name: str | None = None,
    company: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    province: str | None = None,
    city: str | None = None,
    address_line: str | None = None,
    postal_code: str | None = None,
    bank_name: str | None = None,
    iban: str | None = None,
    account_number: str | None = None,
    birth_date: str | None = None,
    employee_gender: str | None = None,
    date_of_joining: str | None = None,
    father_name: str | None = None,
    birth_certificate_number: str | None = None,
    birth_certificate_issue_place: str | None = None,
    employment_type: str | None = None,
    job_title: str | None = None,
    department: str | None = None,
    description: str | None = None,
    primary_role: str | None = None,
    detail_group: str | None = None,
    detail_groups: str | list[str] | None = None,
    secondary_phone: str | None = None,
    alias_name: str | None = None,
    manager_name: str | None = None,
    registration_number: str | None = None,
    economic_code: str | None = None,
    founding_date: str | None = None,
    credit_limit: str | float | None = None,
    opening_balance: str | float | None = None,
    balance_type: str | None = None,
    card_number: str | None = None,
    account_holder: str | None = None,
    region: str | None = None,
    neighborhood: str | None = None,
    plaque: str | None = None,
    unit: str | None = None,
    latitude: str | float | None = None,
    longitude: str | float | None = None,
    employee_roles: str | list[str] | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if party_type not in {"Individual", "Organization"}:
        frappe.throw(_("Party type must be Individual or Organization"))
    if not display_name or len(display_name.strip()) < 3:
        frappe.throw(_("Display name must contain at least 3 characters"))
    selected_roles = _parse_roles(roles)
    selected_groups = _parse_detail_groups(detail_groups)
    if primary_role and primary_role not in selected_roles:
        frappe.throw(_("Primary role must be one of the selected roles"))
    if detail_group and not primary_role:
        frappe.throw(_("Primary role is required when selecting a detail group"))
    national_id = normalize_optional(national_id)
    mobile = normalize_optional(mobile)
    email = normalize_optional(email)
    if national_id and party_type == "Individual" and not is_valid_iranian_national_code(national_id):
        frappe.throw(_("Iranian national code is not valid"))
    if national_id and party_type == "Organization" and not is_valid_iranian_legal_id(national_id):
        frappe.throw(_("Iranian legal entity ID must contain 11 valid digits"))
    if mobile and not is_valid_iranian_mobile(mobile):
        frappe.throw(_("Iranian mobile number is not valid"))

    if name:
        doc = frappe.get_doc("ASOUD Party Profile", name)
    else:
        duplicate = frappe.db.exists("ASOUD Party Profile", {"national_id": national_id}) if national_id else None
        if duplicate:
            frappe.throw(_("A party with this national ID already exists"))
        doc = frappe.new_doc("ASOUD Party Profile")

    title = display_name.strip()
    doc.party_type = party_type
    doc.company = normalize_optional(company)
    doc.display_name = title
    doc.national_id = national_id
    doc.mobile = mobile
    doc.phone = normalize_optional(phone)
    doc.email = email
    doc.website = normalize_optional(website)
    doc.province = normalize_optional(province)
    doc.city = normalize_optional(city)
    doc.address_line = normalize_optional(address_line)
    doc.postal_code = normalize_optional(postal_code)
    doc.bank_name = normalize_optional(bank_name)
    doc.iban = normalize_optional(iban)
    doc.account_number = normalize_optional(account_number)
    doc.birth_date = normalize_optional(birth_date)
    doc.employee_gender = normalize_optional(employee_gender)
    doc.date_of_joining = normalize_optional(date_of_joining)
    doc.father_name = normalize_optional(father_name)
    doc.birth_certificate_number = normalize_optional(birth_certificate_number)
    doc.birth_certificate_issue_place = normalize_optional(birth_certificate_issue_place)
    doc.employment_type = normalize_optional(employment_type)
    doc.job_title = normalize_optional(job_title)
    doc.department = normalize_optional(department)
    doc.description = normalize_optional(description)
    doc.secondary_phone = normalize_optional(secondary_phone)
    doc.alias_name = normalize_optional(alias_name)
    doc.manager_name = normalize_optional(manager_name)
    doc.registration_number = normalize_optional(registration_number)
    doc.economic_code = normalize_optional(economic_code)
    doc.founding_date = normalize_optional(founding_date)
    doc.credit_limit = float(credit_limit or 0)
    doc.opening_balance = float(opening_balance or 0)
    doc.balance_type = normalize_optional(balance_type) or "None"
    doc.card_number = normalize_optional(card_number)
    doc.account_holder = normalize_optional(account_holder)
    doc.region = normalize_optional(region)
    doc.neighborhood = normalize_optional(neighborhood)
    doc.plaque = normalize_optional(plaque)
    doc.unit = normalize_optional(unit)
    doc.latitude = float(latitude) if latitude not in (None, "") else None
    doc.longitude = float(longitude) if longitude not in (None, "") else None
    doc.employee_roles = json.dumps(
        json.loads(employee_roles) if isinstance(employee_roles, str) else (employee_roles or [])
    )
    doc.roles_text = json.dumps(selected_roles)
    if "Customer" in selected_roles and not doc.customer:
        doc.customer = _ensure_customer(title, party_type, national_id)
    if "Supplier" in selected_roles and not doc.supplier:
        doc.supplier = _ensure_supplier(title, party_type, national_id)
    if "Employee" in selected_roles:
        if party_type != "Individual":
            frappe.throw(_("An employee must be an individual party"))
        doc.employee = _ensure_employee(
            doc.employee,
            title,
            doc.company,
            doc.employee_gender,
            doc.birth_date,
            doc.date_of_joining,
            mobile,
            email,
        )
    doc.save() if name else doc.insert()
    _sync_floating_details(
        doc.name,
        title,
        selected_roles,
        primary_role=primary_role,
        detail_group=detail_group,
        detail_groups=selected_groups,
    )

    result = doc.as_dict()
    result["roles"] = selected_roles
    result["detail_groups"] = selected_groups
    result.pop("roles_text", None)
    return success(result)


@frappe.whitelist(methods=["POST"])
def disable_party(name: str) -> dict:
    """Logically disable a party profile; linked ERPNext records are preserved."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.db.exists("ASOUD Party Profile", name):
        frappe.throw(_("Party profile does not exist"))
    doc = frappe.get_doc("ASOUD Party Profile", name)
    doc.disabled = 1
    doc.save()
    return success({"name": doc.name, "disabled": True})
