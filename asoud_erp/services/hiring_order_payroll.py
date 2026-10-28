"""Resolve components using an unsaved native HRMS payroll preview."""

import frappe
from frappe.utils import getdate


def component_amounts(company, employee, assignment, effective_date):
    from hrms.payroll.doctype.payroll_entry.payroll_entry import get_start_end_dates
    from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

    structure = frappe.get_doc("Salary Structure", assignment.salary_structure)
    effective = getdate(effective_date)
    try:
        dates = get_start_end_dates(structure.payroll_frequency, effective, company)
        target = frappe.get_doc({
            "doctype": "Salary Slip", "employee": employee, "company": company,
            "posting_date": effective, "start_date": effective, "end_date": dates.end_date,
        })
        slip = make_salary_slip(structure.name, target_doc=target, employee=employee,
                                posting_date=effective, for_preview=1)
    except frappe.PermissionError:
        raise
    except (frappe.ValidationError, frappe.DoesNotExistError):
        # An absent fiscal/payroll prerequisite or an invalid formula has no amount.
        frappe.clear_messages()
        return {}
    return {row.salary_component: row.amount for row in [*slip.earnings, *slip.deductions]}
