import json

import frappe
from frappe import _
from frappe.utils import getdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.jalali import jalali_fiscal_period
from asoud_erp.services.party_validation import is_valid_iranian_legal_id
from asoud_erp.services.setup_service import (
    ALLOWED_CHART_TEMPLATES,
    ALLOWED_DISPLAY_CURRENCIES,
    ALLOWED_OFFICE_TYPES,
    normalize_digits,
    normalize_enabled_roles,
    unique_abbreviation,
    validate_economic_code,
)


def _setup(company: str):
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Company does not exist"))
    if not frappe.has_permission("Company", ptype="read", doc=company):
        frappe.throw(_("You do not have access to this company"), frappe.PermissionError)
    if not frappe.db.exists("ASOUD Company Setup", company):
        frappe.throw(_("ASOUD setup does not exist for this company"))
    return frappe.get_doc("ASOUD Company Setup", company)


def _serialize_setup(doc) -> dict:
    roles = json.loads(doc.enabled_roles_json or "[]")
    return {
        "company": doc.company,
        "office_type": doc.office_type,
        "national_id": doc.national_id or "",
        "economic_code": doc.economic_code or "",
        "owner_full_name": doc.owner_full_name or "",
        "registration_number": doc.registration_number or "",
        "activity_type": doc.activity_type or "Commercial",
        "company_type": doc.company_type or "",
        "parent_office": doc.parent_office or "",
        "phone": doc.phone or "",
        "email": doc.email or "",
        "website": doc.website or "",
        "province": doc.province or "Tehran",
        "city": doc.city or "Tehran",
        "address": doc.address or "",
        "postal_code": doc.postal_code or "",
        "description": doc.description or "",
        "modified": str(doc.modified or ""),
        "accounting_basis": "Accrual",
        "display_currency": doc.display_currency or "Rial",
        "fiscal_year_start_month": int(doc.fiscal_year_start_month or 1),
        "fiscal_year_start_day": int(doc.fiscal_year_start_day or 1),
        "fiscal_year": int(doc.fiscal_year or 1405),
        "chart_template": doc.chart_template or "Iran Standard",
        "auto_generate_detail_code": bool(doc.auto_generate_detail_code),
        "enabled_roles": roles,
        "office_saved": bool(doc.office_saved),
        "accounting_saved": bool(doc.accounting_saved),
        "roles_saved": bool(doc.roles_saved),
        "complete": bool(doc.office_saved and doc.accounting_saved and doc.roles_saved),
    }


@frappe.whitelist()
def get_setup_status(company: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    selected = company
    if not selected:
        candidates = frappe.get_all(
            "ASOUD Company Setup", pluck="company", order_by="roles_saved desc, modified desc"
        )
        selected = next(
            (value for value in candidates if frappe.has_permission("Company", ptype="read", doc=value)),
            None,
        )
    if not selected:
        return success({"company": None, "office_saved": False, "accounting_saved": False, "roles_saved": False, "complete": False})
    return success(_serialize_setup(_setup(str(selected))))


@frappe.whitelist(methods=["POST"])
def save_office(
    office_type: str,
    company_name: str,
    national_id: str | None = None,
    economic_code: str | None = None,
    auto_generate_detail_code: int | bool = 1,
    company: str | None = None,
    owner_full_name: str | None = None,
    registration_number: str | None = None,
    activity_type: str | None = None,
    company_type: str | None = None,
    parent_office: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    website: str | None = None,
    province: str | None = None,
    city: str | None = None,
    address: str | None = None,
    postal_code: str | None = None,
    fiscal_year: str | None = None,
    chart_template: str | None = None,
    description: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if company and not frappe.has_permission("Company", ptype="write", doc=company):
        frappe.throw(_("You cannot edit this company"), frappe.PermissionError)
    if not company and not frappe.has_permission("Company", ptype="create"):
        frappe.throw(_("You cannot create a company"), frappe.PermissionError)
    office_type = str(office_type or "").strip()
    title = str(company_name or "").strip()
    if office_type not in ALLOWED_OFFICE_TYPES:
        frappe.throw(_("Office type must be Personal or Legal"))
    if len(title) < 3:
        frappe.throw(_("Company name must contain at least 3 characters"))
    normalized_id = normalize_digits(national_id)
    if (
        office_type == "Legal"
        and normalized_id
        and not is_valid_iranian_legal_id(normalized_id)
    ):
        frappe.throw(_("Iranian legal entity ID is not valid"))
    try:
        normalized_economic_code = validate_economic_code(economic_code)
    except ValueError as exc:
        frappe.throw(_(str(exc)))

    if company:
        company_doc = frappe.get_doc("Company", company)
        company_doc.company_name = title
        company_doc.save()
    else:
        duplicate = frappe.db.get_value("Company", {"company_name": title}, "name")
        if duplicate:
            if frappe.db.exists("ASOUD Company Setup", duplicate):
                existing = frappe.get_doc("ASOUD Company Setup", duplicate)
                same_identity = (
                    existing.office_type == office_type
                    and (existing.national_id or "") == (normalized_id or "")
                )
                if same_identity:
                    return success(_serialize_setup(existing))
            frappe.throw(_("A company with this name already exists"))
        try:
            abbreviation = unique_abbreviation(title, lambda value: bool(frappe.db.exists("Company", {"abbr": value})))
        except ValueError as exc:
            frappe.throw(_(str(exc)))
        company_doc = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": title,
                "abbr": abbreviation,
                "default_currency": "IRR",
                "country": "Iran",
            }
        )
        company_doc.insert()

    setup_exists = bool(frappe.db.exists("ASOUD Company Setup", company_doc.name))
    setup = (
        frappe.get_doc("ASOUD Company Setup", company_doc.name)
        if setup_exists
        else frappe.new_doc("ASOUD Company Setup")
    )
    setup.company = company_doc.name
    setup.office_type = office_type
    setup.national_id = normalized_id or None
    setup.economic_code = normalized_economic_code
    setup.owner_full_name = str(owner_full_name or "").strip()
    setup.registration_number = str(registration_number or "").strip()
    setup.activity_type = str(activity_type or "Commercial").strip()
    setup.company_type = str(company_type or "").strip()
    setup.parent_office = str(parent_office or "").strip()
    setup.phone = str(phone or "").strip()
    setup.email = str(email or "").strip()
    setup.website = str(website or "").strip()
    setup.province = str(province or "Tehran").strip()
    setup.city = str(city or "Tehran").strip()
    setup.address = str(address or "").strip()
    setup.postal_code = str(postal_code or "").strip()
    setup.fiscal_year = str(fiscal_year or "1405").strip()
    if chart_template:
        setup.chart_template = str(chart_template).strip()
    setup.description = str(description or "").strip()
    setup.auto_generate_detail_code = int(bool(auto_generate_detail_code))
    setup.office_saved = 1
    setup.save() if setup_exists else setup.insert()
    return success(_serialize_setup(setup))


@frappe.whitelist()
def get_company_settings(company: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    return success(_serialize_setup(_setup(company)))


@frappe.whitelist(methods=["POST"])
def update_company_settings(
    company: str,
    display_currency: str,
    fiscal_year_start_month: int,
    chart_template: str,
    fiscal_year_start_day: int = 1,
    fiscal_year: int = 1405,
    auto_generate_detail_code: int | bool = 1,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if display_currency not in ALLOWED_DISPLAY_CURRENCIES:
        frappe.throw(_("Display currency must be Rial or Toman"))
    if chart_template not in ALLOWED_CHART_TEMPLATES:
        frappe.throw(_("Chart template is not valid"))
    month = int(fiscal_year_start_month)
    day = int(fiscal_year_start_day)
    year = int(fiscal_year)
    if not 1 <= month <= 12:
        frappe.throw(_("Fiscal year start month must be between 1 and 12"))
    if not 1 <= day <= 31:
        frappe.throw(_("Fiscal year start day must be between 1 and 31"))
    if not 1300 <= year <= 1600:
        frappe.throw(_("Fiscal year must be a valid Solar Hijri year"))
    setup = _setup(company)
    setup.accounting_basis = "Accrual"
    setup.display_currency = display_currency
    setup.fiscal_year_start_month = month
    setup.fiscal_year_start_day = day
    setup.fiscal_year = str(year)
    setup.chart_template = chart_template
    setup.auto_generate_detail_code = int(bool(auto_generate_detail_code))
    setup.accounting_saved = 1
    setup.save()
    return success(_serialize_setup(setup))


@frappe.whitelist()
def list_fiscal_years(company: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    _setup(company)
    fiscal_year_names = frappe.get_all(
        "Fiscal Year Company",
        filters={"company": company},
        pluck="parent",
        limit_page_length=0,
    )
    rows = frappe.get_all(
        "Fiscal Year",
        filters={"name": ["in", fiscal_year_names]},
        fields=["name", "year", "year_start_date", "year_end_date", "disabled"],
        order_by="year_start_date desc",
        limit_page_length=0,
    )
    return success(rows)


@frappe.whitelist(methods=["POST"])
def create_fiscal_year(
    company: str,
    fiscal_year: int,
    start_month: int,
    start_day: int,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    _setup(company)
    year = int(fiscal_year)
    if not 1300 <= year <= 1600:
        frappe.throw(_("Fiscal year must be a valid Solar Hijri year"))
    try:
        start_date, end_date = jalali_fiscal_period(year, int(start_month), int(start_day))
    except ValueError as exc:
        frappe.throw(_(str(exc)))
    title = str(year)
    if frappe.db.exists("Fiscal Year", title):
        doc = frappe.get_doc("Fiscal Year", title)
        if getdate(doc.year_start_date) != start_date or getdate(doc.year_end_date) != end_date:
            frappe.throw(_("The existing fiscal year uses a different date range"))
        if not any(row.company == company for row in doc.companies):
            doc.append("companies", {"company": company})
            doc.save()
    else:
        doc = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": title,
                "year_start_date": start_date,
                "year_end_date": end_date,
                "companies": [{"company": company}],
            }
        )
        doc.insert()
    setup = _setup(company)
    setup.fiscal_year = title
    setup.fiscal_year_start_month = int(start_month)
    setup.fiscal_year_start_day = int(start_day)
    setup.save()
    return success(
        {
            "name": doc.name,
            "year": title,
            "year_start_date": str(start_date),
            "year_end_date": str(end_date),
            "disabled": False,
        }
    )


@frappe.whitelist()
def get_enabled_roles(company: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    setup = _setup(company)
    return success({"company": company, "enabled_roles": json.loads(setup.enabled_roles_json or "[]")})


@frappe.whitelist(methods=["POST"])
def update_enabled_roles(company: str, roles: str | list[str]) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    values = json.loads(roles) if isinstance(roles, str) else roles
    try:
        normalized = normalize_enabled_roles(values)
    except ValueError as exc:
        frappe.throw(_(str(exc)))
    setup = _setup(company)
    setup.enabled_roles_json = json.dumps(normalized)
    setup.roles_saved = 1
    setup.save()
    return success(_serialize_setup(setup))


@frappe.whitelist()
def get_settings() -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    settings = frappe.get_single("ASOUD Settings")
    return success(
        {
            "accounting_basis": "Accrual",
            "display_currency": settings.display_currency,
            "auto_generate_account_code": bool(settings.auto_generate_account_code),
            "group_code_digits": settings.group_code_digits,
            "general_code_digits": settings.general_code_digits,
            "ledger_code_digits": settings.ledger_code_digits,
            "auto_generate_detail_code": bool(settings.auto_generate_detail_code),
            "detail_code_digits": settings.detail_code_digits,
        }
    )


@frappe.whitelist(methods=["POST"])
def update_settings(
    display_currency: str,
    auto_generate_account_code: int | bool = 1,
    group_code_digits: int = 1,
    general_code_digits: int = 2,
    ledger_code_digits: int = 2,
    auto_generate_detail_code: int | bool = 1,
    detail_code_digits: int = 5,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if display_currency not in {"Rial", "Toman"}:
        frappe.throw(_("Display currency must be Rial or Toman"))
    digits = int(detail_code_digits)
    if not 3 <= digits <= 12:
        frappe.throw(_("Detail code digits must be between 3 and 12"))
    level_digits = [int(group_code_digits), int(general_code_digits), int(ledger_code_digits)]
    if any(value < 1 or value > 4 for value in level_digits):
        frappe.throw(_("Account level code digits must be between 1 and 4"))

    settings = frappe.get_single("ASOUD Settings")
    settings.accounting_basis = "Accrual"
    settings.display_currency = display_currency
    settings.auto_generate_account_code = int(bool(auto_generate_account_code))
    settings.group_code_digits = level_digits[0]
    settings.general_code_digits = level_digits[1]
    settings.ledger_code_digits = level_digits[2]
    settings.auto_generate_detail_code = int(bool(auto_generate_detail_code))
    settings.detail_code_digits = digits
    settings.save()
    return get_settings()


@frappe.whitelist()
def get_account_code_settings(company: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    setup = _setup(company)
    return success(
        {
            "company": company,
            "auto_generate_account_code": bool(setup.auto_generate_account_code),
            "group_code_digits": int(setup.group_code_digits or 1),
            "general_code_digits": int(setup.general_code_digits or 2),
            "ledger_code_digits": int(setup.ledger_code_digits or 2),
        }
    )


@frappe.whitelist(methods=["POST"])
def update_account_code_settings(
    company: str,
    auto_generate_account_code: int | bool = 1,
    group_code_digits: int = 1,
    general_code_digits: int = 2,
    ledger_code_digits: int = 2,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    setup = _setup(company)
    values = [int(group_code_digits), int(general_code_digits), int(ledger_code_digits)]
    if any(value < 1 or value > 4 for value in values):
        frappe.throw(_("Account level code digits must be between 1 and 4"))
    setup.auto_generate_account_code = int(bool(auto_generate_account_code))
    setup.group_code_digits, setup.general_code_digits, setup.ledger_code_digits = values
    setup.save()
    return get_account_code_settings(company)
