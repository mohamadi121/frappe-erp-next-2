"""Read-only sources for the hiring-order issuance form."""

import frappe
from frappe import _
from frappe.utils import getdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.hiring_orders import (
    MISSING_MESSAGE,
    normalize_search,
    snapshot_payroll,
)
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import paging

HR_ROLES = ("System Manager", "HR Manager")
PAYROLL_ROLES = ("System Manager", "Payroll Manager", "Accounts Manager")


@frappe.whitelist()
def get_hiring_order_template(company: str) -> dict:
    """Published template delivery is intentionally deferred until its immutable store exists."""
    erp_documents.require_roles(HR_ROLES, company)
    require_company(company)
    return success({"template": None})


@frappe.whitelist()
def list_hiring_order_people(company: str, search: str = "", limit_start: int = 0,
                             limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(HR_ROLES, company)
    require_company(company)
    start, length = paging(limit_start, limit_page_length, maximum=100)
    rows = frappe.get_all("Employee", filters={"company": company, "status": "Active"},
                          fields=["name", "employee_name", "employee_number", "department", "designation"],
                          order_by="employee_name asc")
    needle = normalize_search(search)
    if needle:
        rows = [row for row in rows if needle in normalize_search(" ".join(str(row.get(key) or "") for key in
                                                                     ("name", "employee_name", "employee_number")))]
    page = rows[start:start + length]
    return success([{"name": row.name, "display_name": row.employee_name or "پرسنل منتسب",
                     "employee_number": row.employee_number or "", "department": row.department or "",
                     "designation": row.designation or ""} for row in page],
                   meta={"limit_start": start, "limit_page_length": length, "count": len(page), "total": len(rows)})


@frappe.whitelist()
def get_hiring_order_payroll(company: str, employee: str, effective_date: str) -> dict:
    erp_documents.require_roles(PAYROLL_ROLES, company)
    require_company(company)
    if not frappe.db.exists("Employee", {"name": employee, "company": company}):
        frappe.throw(_("پرسنل انتخاب‌شده در این شرکت یافت نشد."), frappe.DoesNotExistError)
    effective = getdate(effective_date)
    assignment = frappe.get_all("Salary Structure Assignment", filters={
        "employee": employee, "company": company, "docstatus": 1, "from_date": ["<=", effective]},
        fields=["name", "base", "variable", "currency"], order_by="from_date desc, creation desc", limit_page_length=1)
    if not assignment:
        return success({"currency": frappe.db.get_value("Company", company, "default_currency"),
                        "rows": snapshot_payroll([{"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "field_ref": "base", "amount": None}])["rows"],
                        "message": MISSING_MESSAGE})
    row = assignment[0]
    payroll = snapshot_payroll([
        {"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "field_ref": "base", "amount": row.base},
        {"id": "variable_pay", "title": "مزایای متغیر", "period": "monthly", "field_ref": "variable", "amount": row.variable},
    ])
    return success({"currency": row.currency or frappe.db.get_value("Company", company, "default_currency"), **payroll})
