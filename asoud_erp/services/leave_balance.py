"""Leave balance including hourly leave, and the Leave Application validate overlay.

HRMS (version-15, ``leave_application.get_leaves_for_period``) only counts Leave
Ledger Entries whose ``transaction_type`` is ``Leave Application`` or
``Leave Encashment`` (plus expired allocations). The ``ASOUD Workflow Request``
entries of approved hourly leave are therefore invisible to HRMS, and this module
subtracts them (CONTRACT 4.11, 4.12). All arithmetic lives in ``leave_hours``.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from asoud_erp.services import leave_hours as lh
from asoud_erp.services.native_payloads import LEDGER_TRANSACTION_TYPE
from asoud_erp.services.request_templates.base import throw_error

#: ``status_key`` values of a leave request that is still being decided (CONTRACT 5).
IN_FLIGHT_STATUS_KEYS = ("submitted", "in_review", "returned")
LEAVE_TYPE_FIELDS = ["name", "asoud_leave_category", "is_lwp", "allow_negative", "include_holiday"]


def fail(code: str, message: str | None = None) -> None:
    """Template errors travel as ``ValidationError`` with the code in the message title."""
    throw_error(code, message or lh.MESSAGES.get(code))


def raise_rule_error(error: lh.LeaveRuleError) -> None:
    fail(error.code, error.message)


# ------------------------------------------------------------------ employee and company


def active_employee(company: str, user: str | None = None):
    """The active Employee of the session user in ``company`` (never taken from the client)."""
    user = user or frappe.session.user
    row = frappe.db.get_value(
        "Employee", {"user_id": user, "company": company, "status": "Active"},
        ["name", "employee_name", "company", "department", "branch", "holiday_list"], as_dict=True)
    if not row:
        fail("EMPLOYEE_NOT_FOUND", _("No active Employee is linked to this user in this company"))
    return row


def daily_working_hours(company: str) -> float:
    """Company custom field ``asoud_daily_working_hours`` (default 8, CONTRACT 2.2)."""
    value = frappe.db.get_value("Company", company, "asoud_daily_working_hours")
    return float(lh.daily_hours_value(value))


def leave_type_info(leave_type: str):
    return frappe.db.get_value("Leave Type", leave_type, LEAVE_TYPE_FIELDS, as_dict=True)


def leave_type_category(leave_type: str) -> str:
    return frappe.db.get_value("Leave Type", leave_type, "asoud_leave_category") or ""


# ------------------------------------------------------------------ ledger and requests


def hourly_entries(employee: str, leave_type: str | None = None) -> list:
    """Submitted hourly-leave ledger entries of the employee (``leaves`` is negative)."""
    filters = {"employee": employee, "transaction_type": LEDGER_TRANSACTION_TYPE, "docstatus": 1}
    if leave_type:
        filters["leave_type"] = leave_type
    return frappe.get_all("Leave Ledger Entry", filters=filters,
                          fields=["leave_type", "from_date", "leaves", "transaction_name"],
                          limit_page_length=0)


def in_flight_requests(employee: str, exclude_request: str | None = None) -> list:
    """Leave requests of the employee that are still Running, with their parsed values."""
    filters = {"template_key": "leave", "requester_employee": employee,
               "status_key": ["in", list(IN_FLIGHT_STATUS_KEYS)]}
    if exclude_request:
        filters["name"] = ["!=", exclude_request]
    rows = frappe.get_all("ASOUD Workflow Request", filters=filters,
                          fields=["name", "values_json", "required_by"], limit_page_length=0)
    for row in rows:
        row["values"] = json.loads(row.values_json or "{}")
    return rows


def _in_period(value, period) -> bool:
    return bool(value and period and getdate(period[0]) <= getdate(value) <= getdate(period[1]))


def leave_type_rows(employee: str, as_of=None, *, only_allocated: bool = False,
                    exclude_request: str | None = None) -> list[dict]:
    """Per Leave Type balance rows (CONTRACT 4.11 formulas, see ``leave_hours.type_balance``).

    ``only_allocated`` limits the rows to Leave Types HRMS reports an allocation for
    (used by ``get_my_leave_summary``); otherwise every Leave Type with a category.
    """
    from hrms.hr.doctype.leave_application.leave_application import (
        get_leave_allocation_records,
        get_leave_details,
    )

    as_of = getdate(as_of or nowdate())
    allocation = get_leave_details(employee, as_of).get("leave_allocation") or {}
    records = get_leave_allocation_records(employee, as_of)
    infos = {row.name: row for row in frappe.get_all("Leave Type", fields=LEAVE_TYPE_FIELDS,
                                                     limit_page_length=0)}
    names = sorted(allocation) if only_allocated else sorted(
        name for name, info in infos.items() if info.asoud_leave_category)
    ledger = hourly_entries(employee)
    pending = in_flight_requests(employee, exclude_request)
    rows = []
    for name in names:
        info = infos.get(name) or frappe._dict(name=name, asoud_leave_category="", is_lwp=0,
                                               allow_negative=0, include_holiday=0)
        record = records.get(name)
        period = (record.from_date, record.to_date) if record else None
        hourly = -sum(flt(entry.leaves) for entry in ledger
                      if entry.leave_type == name and _in_period(entry.from_date, period))
        inflight = sum(flt((request["values"].get("duration") or {}).get("day_equivalent"))
                       for request in pending
                       if request["values"].get("leave_type") == name
                       and _in_period(request.required_by, period))
        balance = lh.type_balance(native=allocation.get(name), hourly_taken=hourly, inflight=inflight,
                                  is_lwp=bool(cint(info.is_lwp)))
        rows.append({
            "leave_type": name, "category": info.asoud_leave_category or "",
            "label": lh.category_label(info.asoud_leave_category), "is_lwp": cint(info.is_lwp),
            "allow_negative": cint(info.allow_negative), **balance,
        })
    return rows


def balance_for(rows: list[dict], leave_type: str) -> dict:
    row = next((row for row in rows if row["leave_type"] == leave_type), None)
    return row or lh.type_balance(native=None, hourly_taken=0, inflight=0,
                                  is_lwp=bool(cint(frappe.db.get_value("Leave Type", leave_type, "is_lwp"))))


def hourly_taken_in_period(employee: str, leave_type: str, on_date) -> float:
    """Hourly leave of the allocation period that contains ``on_date`` (0 without allocation)."""
    from hrms.hr.doctype.leave_application.leave_application import get_leave_allocation_records

    record = get_leave_allocation_records(employee, getdate(on_date), leave_type).get(leave_type)
    if not record:
        return 0.0
    period = (record.from_date, record.to_date)
    return round(-sum(flt(entry.leaves) for entry in hourly_entries(employee, leave_type)
                      if _in_period(entry.from_date, period)), 6)


# ------------------------------------------------------------------ Leave Application overlay


def validate_leave_application(doc, method=None):
    """Hook on Leave Application ``validate`` (CONTRACT 2.5, 4.12).

    HRMS compares ``leave_balance_for_consumption`` with the days applied for, but does
    not see hourly leave. A full-day leave must not overspend what hourly leave left.
    Runs after HRMS' own validation, so ``total_leave_days`` is already recomputed.
    """
    if doc.get("status") == "Rejected" or not (doc.employee and doc.leave_type and doc.from_date
                                                and doc.to_date):
        return
    info = leave_type_info(doc.leave_type)
    if not info or cint(info.is_lwp) or cint(info.allow_negative):
        return
    hourly = hourly_taken_in_period(doc.employee, doc.leave_type, doc.from_date)
    if not hourly:
        return
    from hrms.hr.doctype.leave_application.leave_application import (
        InsufficientLeaveBalanceError,
        get_leave_balance_on,
    )

    consumption = get_leave_balance_on(
        doc.employee, doc.leave_type, doc.from_date, doc.to_date,
        consider_all_leaves_in_the_allocation_period=True, for_consumption=True,
        leave_application=None if doc.is_new() else doc.name,
    ).get("leave_balance_for_consumption")
    if lh.overlay_insufficient(consumption, hourly, doc.total_leave_days):
        frappe.throw(
            _("Insufficient leave balance for Leave Type {0}: {1} day(s) were already taken as hourly leave")
            .format(frappe.bold(doc.leave_type), lh.round_half_up(hourly, 3)),
            exc=InsufficientLeaveBalanceError, title=_("Insufficient Balance"))
