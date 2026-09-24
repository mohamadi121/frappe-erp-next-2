"""Payroll processing on HRMS: structure assignments, payroll entries and salary slips.

The calculation (components, formulas, taxes, insurance) lives in HRMS Salary
Components and Salary Structures. This module assigns structures to employees,
runs a Payroll Entry for a period (HRMS creates the salary slips), and submits
the slips (HRMS books the accrual journal entry).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import number, paging

MANAGER_ROLES = ("System Manager", "HR Manager")
ASSIGNMENT_ROLES = ("System Manager", "HR Manager", "HR User")
FREQUENCIES = {"Monthly", "Fortnightly", "Bimonthly", "Weekly", "Daily"}


@frappe.whitelist()
def payroll_options(company: str) -> dict:
    erp_documents.require_roles(ASSIGNMENT_ROLES)
    require_company(company)
    values = frappe.get_cached_value("Company", company, ["default_payroll_payable_account", "cost_center",
                                                         "default_currency"], as_dict=True)
    return success({
        "currency": values.default_currency,
        "payroll_payable_account": values.default_payroll_payable_account,
        "cost_center": values.cost_center,
        "frequencies": sorted(FREQUENCIES),
        "salary_structures": frappe.get_list("Salary Structure",
                                             filters={"company": company, "docstatus": 1, "is_active": "Yes"},
                                             fields=["name", "payroll_frequency", "currency"],
                                             order_by="name asc"),
    })


# ---------------------------------------------------------------- structure assignments

@frappe.whitelist()
def list_salary_structure_assignments(company: str, employee: str | None = None, limit_start: int = 0,
                                      limit_page_length: int = 50) -> dict:
    erp_documents.require_roles(ASSIGNMENT_ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=200)
    filters: dict = {"company": company, "docstatus": 1}
    if employee:
        filters["employee"] = employee
    rows = frappe.get_list("Salary Structure Assignment", filters=filters,
                           fields=["name", "employee", "employee_name", "salary_structure", "from_date",
                                   "base", "variable", "currency"],
                           order_by="from_date desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist(methods=["POST"])
def create_salary_structure_assignment(employee: str, salary_structure: str, from_date: str, base,
                                       variable=0, payroll_payable_account: str | None = None,
                                       submit: int = 1) -> dict:
    """Gives an employee a salary structure from a date, with its base (and variable) pay.

    Payroll entries pick employees by this payable account (default: the company's).
    """
    erp_documents.require_roles(ASSIGNMENT_ROLES)
    company = frappe.db.get_value("Employee", employee, "company")
    if not company:
        frappe.throw(_("Employee {0} does not exist").format(employee), frappe.DoesNotExistError)
    require_company(company)
    try:
        base_pay = number(base, "Base", minimum=0)
        variable_pay = number(variable or 0, "Variable", minimum=0)
    except ValueError as error:
        frappe.throw(_(str(error)))
    doc = frappe.get_doc({
        "doctype": "Salary Structure Assignment", "employee": employee, "company": company,
        "salary_structure": salary_structure, "from_date": getdate(from_date), "base": base_pay,
        "variable": variable_pay, "currency": frappe.db.get_value("Salary Structure", salary_structure, "currency"),
        "payroll_payable_account": payroll_payable_account
        or frappe.get_cached_value("Company", company, "default_payroll_payable_account"),
    })
    erp_documents.insert(doc, submit_now=cint(submit))
    return success({"name": doc.name, "employee": doc.employee, "salary_structure": doc.salary_structure,
                    "from_date": str(doc.from_date), "base": flt(doc.base), "variable": flt(doc.variable),
                    "docstatus": doc.docstatus})


# ---------------------------------------------------------------- payroll entries

def serialize_payroll_entry(doc) -> dict:
    slips = frappe.get_all("Salary Slip", filters={"payroll_entry": doc.name, "docstatus": ["<", 2]},
                           fields=["name", "employee", "employee_name", "gross_pay", "total_deduction",
                                   "net_pay", "docstatus"], order_by="employee_name asc")
    return {
        "name": doc.name, "company": doc.company, "status": doc.status, "docstatus": doc.docstatus,
        "posting_date": str(doc.posting_date), "start_date": str(doc.start_date), "end_date": str(doc.end_date),
        "payroll_frequency": doc.payroll_frequency, "currency": doc.currency,
        "number_of_employees": cint(doc.number_of_employees),
        "salary_slips_created": cint(doc.salary_slips_created),
        "salary_slips_submitted": cint(doc.salary_slips_submitted),
        "totals": {key: flt(sum(flt(row[key]) for row in slips))
                   for key in ("gross_pay", "total_deduction", "net_pay")},
        "salary_slips": slips,
        "error_message": doc.error_message or "",
    }


@frappe.whitelist(methods=["POST"])
def create_payroll_entry(company: str, start_date: str, end_date: str, posting_date: str | None = None,
                         payroll_frequency: str = "Monthly", department: str | None = None,
                         branch: str | None = None, designation: str | None = None,
                         validate_attendance: int = 0) -> dict:
    """Runs payroll for a period: HRMS picks the employees with an active structure and
    creates their draft salary slips (queued in the background above 30 employees)."""
    erp_documents.require_roles(MANAGER_ROLES)
    require_company(company)
    if payroll_frequency not in FREQUENCIES:
        frappe.throw(_("Invalid payroll frequency"))
    start, end = getdate(start_date), getdate(end_date)
    if start > end:
        frappe.throw(_("Start date must not be after end date"))
    values = frappe.get_cached_value("Company", company, ["default_payroll_payable_account", "cost_center",
                                                         "default_currency"], as_dict=True)
    if not values.default_payroll_payable_account:
        frappe.throw(_("Set the Default Payroll Payable Account of company {0}").format(company))
    doc = frappe.get_doc({
        "doctype": "Payroll Entry", "company": company, "posting_date": getdate(posting_date or nowdate()),
        "payroll_frequency": payroll_frequency, "start_date": start, "end_date": end,
        "department": department or None, "branch": branch or None, "designation": designation or None,
        "validate_attendance": cint(validate_attendance), "cost_center": values.cost_center,
        "currency": values.default_currency, "exchange_rate": 1,
        "payroll_payable_account": values.default_payroll_payable_account,
    })
    doc.insert()
    doc.fill_employee_details()  # HRMS throws when no employee has a matching assignment
    doc.save()
    doc.submit()
    doc.reload()
    return success(serialize_payroll_entry(doc))


@frappe.whitelist(methods=["POST"])
def submit_payroll_salary_slips(payroll_entry: str) -> dict:
    """Submits the draft slips of a payroll entry; HRMS books the payroll accrual journal entry."""
    erp_documents.require_roles(MANAGER_ROLES)
    doc = erp_documents.load("Payroll Entry", payroll_entry, "write")
    if doc.docstatus != 1:
        frappe.throw(_("Submit the payroll entry first"))
    doc.submit_salary_slips()
    doc.reload()
    return success(serialize_payroll_entry(doc))


@frappe.whitelist()
def list_payroll_entries(company: str, limit_start: int = 0, limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(MANAGER_ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    rows = frappe.get_list("Payroll Entry", filters={"company": company},
                           fields=["name", "posting_date", "start_date", "end_date", "payroll_frequency",
                                   "number_of_employees", "status", "docstatus"],
                           order_by="start_date desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_payroll_entry(name: str) -> dict:
    erp_documents.require_roles(MANAGER_ROLES)
    return success(serialize_payroll_entry(erp_documents.load("Payroll Entry", name)))
