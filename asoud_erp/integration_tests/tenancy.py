"""Two companies and real users for the access-control (tenant scope) tests.

Company A is the site's default company, created by ERPNext's ``before_tests``.
Company B, its chart of accounts, one posted journal entry per company, the
designations and the users below are created once and committed, so every
access-control module reuses them. Each test still runs inside a transaction
that is rolled back.

The users carry real Frappe roles and a real User Permission on ``Company``, so
``frappe.has_permission`` and ``services.request_access.company_access`` see
exactly what they see in production. Administrator is never used to prove a
denial.
"""

import frappe
from frappe.utils import getdate, nowdate

from asoud_erp.integration_tests.fixtures import _user, company

SECOND_COMPANY = "ASOUD Second Company"
SECOND_ABBR = "ASEC"

ACCOUNTS_A_USER = "asoud.scope-accounts-a@example.com"
ACCOUNTS_B_USER = "asoud.scope-accounts-b@example.com"
HR_MANAGER_USER = "asoud.scope-hr@example.com"
MANAGER_USER = "asoud.scope-manager@example.com"
EMPLOYEE_A_USER = "asoud.scope-employee-a@example.com"
EMPLOYEE_B_USER = "asoud.scope-employee-b@example.com"

DESIGNATION_A = "ASOUD Scope A"
DESIGNATION_B = "ASOUD Scope B"
DEPARTMENT_A = "ASOUD Scope Department A"
DEPARTMENT_B = "ASOUD Scope Department B"

# Distinct, valid IBANs so a leak is provable by value, not by field presence.
IBAN_A = "IR150570000000001111111111"
IBAN_B = "IR150570000000002222222222"

GL_AMOUNT = 1250
GL_REMARK = "ASOUD scope entry"


def ledger(company: str, root_type: str) -> str:
    """A leaf account of ``root_type`` in ``company``, stable across runs."""
    return frappe.get_all(
        "Account",
        filters={"company": company, "root_type": root_type, "is_group": 0},
        pluck="name",
        order_by="name asc",
        limit=1,
    )[0]


def journal(company: str) -> str:
    """The name of this fixture's posted journal entry in ``company``."""
    return frappe.db.get_value("Journal Entry", {"company": company, "user_remark": GL_REMARK}, "name")


def _fiscal_year(target: str) -> str:
    """An active fiscal year covering today for ``target``.

    The shared site ships with a fiscal year that is linked to another company,
    so a posting in the default company would be refused by ERPNext. ERPNext
    caches the per-company list, so the cache entry is dropped afterwards.
    """
    year = str(getdate(nowdate()).year)
    if not frappe.db.exists("Fiscal Year", year):
        frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": year,
                "year_start_date": f"{year}-01-01",
                "year_end_date": f"{year}-12-31",
                "companies": [{"company": target}],
            }
        ).insert(ignore_permissions=True)
    elif not frappe.db.exists("Fiscal Year Company", {"parent": year, "company": target}):
        doc = frappe.get_doc("Fiscal Year", year)
        doc.append("companies", {"company": target})
        doc.save(ignore_permissions=True)
    frappe.cache().hdel("fiscal_years", target)
    return year


def _post_gl(company: str) -> None:
    if journal(company):
        return
    _fiscal_year(company)
    frappe.get_doc(
        {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": company,
            "posting_date": nowdate(),
            "user_remark": GL_REMARK,
            "accounts": [
                {
                    "account": ledger(company, "Expense"),
                    "debit_in_account_currency": GL_AMOUNT,
                    "credit_in_account_currency": 0,
                    "cost_center": frappe.db.get_value("Company", company, "cost_center"),
                },
                {
                    "account": ledger(company, "Equity"),
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": GL_AMOUNT,
                    "cost_center": frappe.db.get_value("Company", company, "cost_center"),
                },
            ],
        }
    ).submit()


def _employee(user: str, first_name: str, target: str, **extra) -> str:
    existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if existing:
        return existing
    return frappe.get_doc(
        {
            "doctype": "Employee",
            "first_name": first_name,
            "gender": "Male",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01",
            "company": target,
            "status": "Active",
            "user_id": user,
            "create_user_permission": 0,
            **extra,
        }
    ).insert(ignore_permissions=True).name


def _party(display_name: str, target: str, roles: list[str], **extra) -> str:
    existing = frappe.db.get_value("ASOUD Party Profile", {"display_name": display_name}, "name")
    if existing:
        return existing
    return frappe.get_doc(
        {
            "doctype": "ASOUD Party Profile",
            "party_type": "Individual",
            "display_name": display_name,
            "company": target,
            "roles_text": frappe.as_json(roles),
            "employee_roles": "[]",
            "disabled": 0,
            **extra,
        }
    ).insert(ignore_permissions=True).name


def _designation(name: str) -> str:
    if not frappe.db.exists("Designation", name):
        frappe.get_doc({"doctype": "Designation", "designation_name": name}).insert(ignore_permissions=True)
    return name


def _department(name: str, target: str) -> str:
    existing = frappe.db.get_value("Department", {"department_name": name, "company": target}, "name")
    if existing:
        return existing
    return frappe.get_doc(
        {"doctype": "Department", "department_name": name, "company": target, "is_group": 0}
    ).insert(ignore_permissions=True).name


def setup_tenancy() -> dict:
    """Idempotently creates the second company, its postings and the test users."""
    frappe.set_user("Administrator")
    first = company()
    second = SECOND_COMPANY
    if not frappe.db.exists("Company", second):
        frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": second,
                "abbr": SECOND_ABBR,
                "default_currency": "USD",
                "country": "United States",
                "chart_of_accounts": "Standard",
            }
        ).insert(ignore_permissions=True)
    _designation(DESIGNATION_A)
    _designation(DESIGNATION_B)
    _department(DEPARTMENT_A, first)
    _department(DEPARTMENT_B, second)

    _user(ACCOUNTS_A_USER, ["Accounts User"])
    _user(ACCOUNTS_B_USER, ["Accounts Manager"])
    _user(HR_MANAGER_USER, ["HR Manager", "HR User"])
    _user(MANAGER_USER, ["Accounts Manager"])
    _user(EMPLOYEE_A_USER, ["Employee"])
    _user(EMPLOYEE_B_USER, ["Employee"])
    for user in (ACCOUNTS_A_USER, HR_MANAGER_USER, MANAGER_USER):
        if not frappe.db.exists("User Permission", {"user": user, "allow": "Company", "for_value": first}):
            frappe.permissions.add_user_permission("Company", first, user, ignore_permissions=True)
    _employee(ACCOUNTS_A_USER, "Scope Accounts A", first)
    _employee(ACCOUNTS_B_USER, "Scope Manager A", first)
    _employee(HR_MANAGER_USER, "Scope HR", first)
    _employee(MANAGER_USER, "Scope Manager", first)

    employee_a = _employee(EMPLOYEE_A_USER, "Scope Employee A", first)
    employee_b = _employee(EMPLOYEE_B_USER, "Scope Employee B", second)

    _post_gl(first)
    _post_gl(second)

    party_a = _party("ASOUD Scope Party A", first, ["Customer"], iban=IBAN_A, bank_name="Bank A",
                     account_number="1000000001", card_number="6100000000000001")
    party_b = _party("ASOUD Scope Party B", second, ["Customer"], iban=IBAN_B, bank_name="Bank B",
                     account_number="2000000002", card_number="6200000000000002")
    personnel_a = _party("ASOUD Scope Personnel A", first, ["Employee"], employee=employee_a,
                         job_title=DESIGNATION_A, department=DEPARTMENT_A, iban=IBAN_A,
                         employee_gender="Male", birth_date="1990-01-01", date_of_joining="2020-01-01")
    personnel_b = _party("ASOUD Scope Personnel B", second, ["Employee"], employee=employee_b,
                         job_title=DESIGNATION_B, department=DEPARTMENT_B, iban=IBAN_B,
                         employee_gender="Male", birth_date="1990-01-01", date_of_joining="2020-01-01")
    frappe.db.commit()
    return {
        "first": first,
        "second": second,
        "party_a": party_a,
        "party_b": party_b,
        "personnel_a": personnel_a,
        "personnel_b": personnel_b,
        "employee_a": employee_a,
        "employee_b": employee_b,
    }