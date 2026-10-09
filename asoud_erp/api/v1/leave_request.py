"""Leave request endpoints: balance panel and live preview of the leave form (CONTRACT 4.11).

Both act for the active Employee of the session user in ``company``; an ``employee``
argument is never accepted. Names are read-only for the offline layer (``get_*``,
``preview_*``): business errors of the preview come back as data because the mobile
client drops server messages from exceptions.
"""

import frappe
from frappe.utils import cint, getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import leave_balance as lb
from asoud_erp.services import leave_hours as lh
from asoud_erp.services.request_access import require_company


def direct_manager_user(employee: str) -> str:
    """The user the seeded approval stage assigns (``reports_to``), else the HRMS leave approver."""
    from hrms.hr.doctype.leave_application.leave_application import get_leave_approver

    manager = frappe.db.get_value("Employee", employee, "reports_to")
    user = manager and frappe.db.get_value("Employee", {"name": manager, "status": "Active"}, "user_id")
    return user or get_leave_approver(employee) or ""


@frappe.whitelist()
def get_leave_balance(company: str, date: str | None = None) -> dict:
    """Leave balance of the session user, hourly leave deducted (CONTRACT 4.11)."""
    require_company(company)
    employee = lb.active_employee(company)
    as_of = getdate(date or nowdate())
    rows = lb.leave_type_rows(employee.name, as_of)
    return success({
        "employee": employee.name,
        "as_of": str(as_of),
        "daily_working_hours": lb.daily_working_hours(company),
        "leave_approver": direct_manager_user(employee.name),
        "categories": lh.category_rows(rows),
        "leave_types": [
            {"leave_type": row["leave_type"], "category": row["category"], "label": row["label"],
             "is_lwp": row["is_lwp"], "has_allocation": row["has_allocation"],
             "total_leaves": row["total_leaves"], "leaves_taken": row["leaves_taken"],
             "hourly_taken": row["hourly_taken"], "leaves_pending": row["leaves_pending"],
             "remaining": row["remaining"], "available": row["available"]}
            for row in rows
        ],
    })


@frappe.whitelist()
def preview_leave_request(company: str, leave_type: str, request_kind: str, start_date: str | None = None,
                          end_date: str | None = None, leave_date: str | None = None,
                          start_time: str | None = None, end_time: str | None = None) -> dict:
    """Dry run of the leave rules; business errors are returned, not raised (CONTRACT 4.11).

    Incomplete input (a form being typed into) gives ``valid: false`` with no errors and
    no duration.
    """
    from asoud_erp.services.request_templates.leave_rules import evaluate_leave

    require_company(company)
    employee = lb.active_employee(company)
    values = {"leave_type": leave_type, "request_kind": request_kind, "start_date": start_date,
              "end_date": end_date, "leave_date": leave_date, "start_time": start_time,
              "end_time": end_time}
    outcome = evaluate_leave(company, employee, values)
    return success({
        "valid": outcome["complete"] and not outcome["errors"],
        "errors": outcome["errors"],
        "duration": outcome["duration"],
        "balance": outcome["balance"],
        "holidays_excluded": cint(outcome["holidays_excluded"]),
    })
