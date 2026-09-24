"""Employee self-service on HRMS: leave, check-in, missions, advances, expense claims.

Every method acts for the active Employee linked to the session user; an
``employee`` argument is never accepted. Approvals follow HRMS: the leave
approver sets the status and submits.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.self_service import (
    LOG_TYPES,
    TRAVEL_TYPES,
    coordinates,
    date_span,
    iso_date,
    normalize_costings,
    normalize_expenses,
    normalize_itinerary,
)
from asoud_erp.services.transaction_lines import number, paging

MY_LIST_LIMIT = 50


def _me():
    name = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
    if not name:
        frappe.throw(_("No active Employee is linked to this user"), frappe.PermissionError)
    return frappe.get_cached_doc("Employee", name)


def _validated(call):
    try:
        return call()
    except ValueError as error:
        frappe.throw(_(str(error)))


def _mine(doctype: str, fields: list[str], limit_start=0, limit_page_length=20, order_by=None):
    start, length = paging(limit_start, limit_page_length, maximum=MY_LIST_LIMIT)
    rows = frappe.get_all(doctype, filters={"employee": _me().name}, fields=fields,
                          order_by=order_by or "creation desc", limit_start=start,
                          limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


def _own(doctype: str, name: str, ptype: str = "read"):
    doc = erp_documents.load(doctype, name, ptype)
    if doc.employee != _me().name:
        frappe.throw(_("This document belongs to another employee"), frappe.PermissionError)
    return doc


# ---------------------------------------------------------------- leave

def serialize_leave(doc) -> dict:
    return {
        "name": doc.name, "employee": doc.employee, "employee_name": doc.employee_name,
        "leave_type": doc.leave_type, "from_date": str(doc.from_date), "to_date": str(doc.to_date),
        "half_day": cint(doc.half_day), "half_day_date": str(doc.half_day_date or ""),
        "total_leave_days": flt(doc.total_leave_days), "description": doc.description or "",
        "leave_approver": doc.leave_approver or "", "status": doc.status, "docstatus": doc.docstatus,
    }


@frappe.whitelist()
def get_my_leave_summary(date: str | None = None) -> dict:
    """Leave types with allocation, taken, pending and remaining days (HRMS `get_leave_details`)."""
    from hrms.hr.doctype.leave_application.leave_application import get_leave_details

    me = _me()
    details = get_leave_details(me.name, getdate(date or nowdate()))
    return success({
        "employee": me.name,
        "leave_approver": details.get("leave_approver") or "",
        "leave_without_pay_types": details.get("lwps") or [],
        "balances": [{"leave_type": leave_type, **values}
                     for leave_type, values in (details.get("leave_allocation") or {}).items()],
    })


@frappe.whitelist()
def get_leave_days(leave_type: str, from_date: str, to_date: str, half_day: int = 0,
                   half_day_date: str | None = None) -> dict:
    """Working days a leave would take, after holidays and half day (HRMS rules)."""
    from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days

    start, end = _validated(lambda: date_span(from_date, to_date))
    days = get_number_of_leave_days(_me().name, leave_type, start, end, cint(half_day),
                                    half_day_date or None)
    return success({"leave_type": leave_type, "from_date": start, "to_date": end, "days": flt(days)})


@frappe.whitelist(methods=["POST"])
def create_leave_application(leave_type: str, from_date: str, to_date: str, reason: str | None = None,
                             half_day: int = 0, half_day_date: str | None = None) -> dict:
    """An open leave application for the approver configured in HRMS."""
    from hrms.hr.doctype.leave_application.leave_application import get_leave_approver

    me = _me()
    start, end = _validated(lambda: date_span(from_date, to_date))
    doc = frappe.new_doc("Leave Application")
    doc.update({
        "employee": me.name, "company": me.company, "leave_type": leave_type,
        "from_date": start, "to_date": end, "half_day": cint(half_day),
        "half_day_date": iso_date(half_day_date, "Half day date") if cint(half_day) and half_day_date
        else None,
        "description": (reason or "").strip(), "leave_approver": get_leave_approver(me.name),
        "posting_date": nowdate(), "status": "Open",
    })
    doc.insert()
    return success(serialize_leave(doc))


@frappe.whitelist()
def list_my_leave_applications(limit_start: int = 0, limit_page_length: int = 20) -> dict:
    return _mine("Leave Application", ["name", "leave_type", "from_date", "to_date", "total_leave_days",
                                       "status", "docstatus"], limit_start, limit_page_length,
                 order_by="from_date desc")


@frappe.whitelist(methods=["POST"])
def cancel_leave_application(name: str) -> dict:
    """Withdraws one's own leave application while it is still open (HRMS status ``Cancelled``)."""
    doc = _own("Leave Application", name, "write")
    if doc.docstatus != 0 or doc.status != "Open":
        frappe.throw(_("Only an open, unsubmitted leave application can be withdrawn"))
    doc.status = "Cancelled"
    # HRMS keeps `status` at a higher permlevel (approvers); ownership and state are checked above.
    doc.save(ignore_permissions=True)
    return success(serialize_leave(doc))


@frappe.whitelist()
def list_leave_approvals() -> dict:
    """Open leave applications waiting for the session user as leave approver."""
    rows = frappe.get_list("Leave Application",
                           filters={"leave_approver": frappe.session.user, "status": "Open",
                                    "docstatus": 0},
                           fields=["name", "employee", "employee_name", "leave_type", "from_date",
                                   "to_date", "total_leave_days", "description"],
                           order_by="from_date asc", limit_page_length=100)
    return success(rows)


def _decide_leave(name: str, status: str):
    doc = erp_documents.load("Leave Application", name, "write")
    if doc.leave_approver != frappe.session.user and "HR Manager" not in frappe.get_roles():
        frappe.throw(_("Only the leave approver can decide this application"), frappe.PermissionError)
    if doc.docstatus != 0 or doc.status != "Open":
        frappe.throw(_("This leave application is already decided"))
    doc.status = status
    doc.save()
    doc.submit()
    return doc


@frappe.whitelist(methods=["POST"])
def approve_leave_application(name: str) -> dict:
    return success(serialize_leave(_decide_leave(name, "Approved")))


@frappe.whitelist(methods=["POST"])
def reject_leave_application(name: str, reason: str | None = None) -> dict:
    doc = _decide_leave(name, "Rejected")
    if reason and reason.strip():
        doc.add_comment("Comment", reason.strip())
    return success(serialize_leave(doc))


# ---------------------------------------------------------------- check-in

@frappe.whitelist(methods=["POST"])
def create_checkin(log_type: str, latitude=None, longitude=None, device_id: str | None = None) -> dict:
    """Records an HRMS Employee Checkin now; attendance is derived by HRMS shift rules."""
    if log_type not in LOG_TYPES:
        frappe.throw(_("Log type must be IN or OUT"))
    location = _validated(lambda: coordinates(latitude, longitude))
    me = _me()
    doc = frappe.new_doc("Employee Checkin")
    doc.update({"employee": me.name, "log_type": log_type, "time": now_datetime(),
                "device_id": (device_id or "mobile")[:140]})
    if location:
        doc.latitude, doc.longitude = location
    doc.insert()
    return success({"name": doc.name, "employee": doc.employee, "log_type": doc.log_type,
                    "time": str(doc.time), "shift": doc.shift or "", "attendance": doc.attendance or ""})


@frappe.whitelist()
def list_my_checkins(from_date: str | None = None, to_date: str | None = None,
                     limit_start: int = 0, limit_page_length: int = 20) -> dict:
    start, length = paging(limit_start, limit_page_length, maximum=MY_LIST_LIMIT)
    filters: dict = {"employee": _me().name}
    if from_date or to_date:
        low = f"{from_date} 00:00:00" if from_date else "1900-01-01 00:00:00"
        high = f"{to_date} 23:59:59" if to_date else "2999-12-31 23:59:59"
        filters["time"] = ["between", [low, high]]
    rows = frappe.get_all("Employee Checkin", filters=filters,
                          fields=["name", "log_type", "time", "shift", "attendance"],
                          order_by="time desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


# ---------------------------------------------------------------- missions (Travel Request)

@frappe.whitelist()
def mission_options() -> dict:
    return success({
        "travel_types": sorted(TRAVEL_TYPES),
        "purposes": frappe.get_all("Purpose of Travel", pluck="name", order_by="name asc"),
        "expense_types": frappe.get_all("Expense Claim Type", pluck="name", order_by="name asc"),
    })


@frappe.whitelist(methods=["POST"])
def create_travel_request(travel_type: str, purpose_of_travel: str, itinerary, description: str | None = None,
                          costings=None) -> dict:
    """A mission (مأموریت) as a draft HRMS Travel Request for the session user's Employee."""
    if travel_type not in TRAVEL_TYPES:
        frappe.throw(_("Travel type must be Domestic or International"))
    rows = _validated(lambda: normalize_itinerary(itinerary))
    costs = _validated(lambda: normalize_costings(costings))
    me = _me()
    doc = frappe.new_doc("Travel Request")
    doc.update({"employee": me.name, "company": me.company, "travel_type": travel_type,
                "purpose_of_travel": purpose_of_travel, "description": (description or "").strip()})
    for row in rows:
        doc.append("itinerary", row)
    for row in costs:
        doc.append("costings", row)
    # HRMS grants Travel Request only to System Manager; the employee is fixed to the caller above.
    doc.insert(ignore_permissions=True)
    return success({"name": doc.name, "travel_type": doc.travel_type,
                    "purpose_of_travel": doc.purpose_of_travel, "docstatus": doc.docstatus,
                    "itinerary": rows, "costings": costs})


@frappe.whitelist()
def list_my_travel_requests(limit_start: int = 0, limit_page_length: int = 20) -> dict:
    return _mine("Travel Request", ["name", "travel_type", "purpose_of_travel", "docstatus", "creation"],
                 limit_start, limit_page_length)


# ---------------------------------------------------------------- advances (مساعده)

@frappe.whitelist(methods=["POST"])
def create_employee_advance(amount, purpose: str, posting_date: str | None = None) -> dict:
    """A draft salary advance (HRMS Employee Advance); the expense approver submits it."""
    value = _validated(lambda: number(amount, "Amount", minimum=0, allow_equal=False))
    if not (purpose or "").strip():
        frappe.throw(_("Purpose is required"))
    me = _me()
    doc = frappe.new_doc("Employee Advance")
    doc.update({"employee": me.name, "company": me.company, "advance_amount": value,
                "purpose": purpose.strip(), "posting_date": getdate(posting_date or nowdate()),
                "currency": frappe.get_cached_value("Company", me.company, "default_currency"),
                "exchange_rate": 1})
    doc.insert()
    return success({"name": doc.name, "advance_amount": flt(doc.advance_amount), "purpose": doc.purpose,
                    "status": doc.status, "docstatus": doc.docstatus})


@frappe.whitelist()
def list_my_employee_advances(limit_start: int = 0, limit_page_length: int = 20) -> dict:
    return _mine("Employee Advance", ["name", "posting_date", "advance_amount", "paid_amount",
                                      "claimed_amount", "status", "docstatus"],
                 limit_start, limit_page_length)


# ---------------------------------------------------------------- expense claims

@frappe.whitelist(methods=["POST"])
def create_expense_claim(expenses, remark: str | None = None) -> dict:
    """A draft expense claim; the expense approver approves and submits it in HRMS."""
    rows = _validated(lambda: normalize_expenses(expenses))
    me = _me()
    doc = frappe.new_doc("Expense Claim")
    doc.update({"employee": me.name, "company": me.company, "posting_date": nowdate(),
                "remark": (remark or "").strip()})
    for row in rows:
        doc.append("expenses", {**row, "sanctioned_amount": row["amount"]})
    doc.insert()
    return success({"name": doc.name, "total_claimed_amount": flt(doc.total_claimed_amount),
                    "approval_status": doc.approval_status, "status": doc.status,
                    "docstatus": doc.docstatus})


@frappe.whitelist()
def list_my_expense_claims(limit_start: int = 0, limit_page_length: int = 20) -> dict:
    return _mine("Expense Claim", ["name", "posting_date", "total_claimed_amount", "approval_status",
                                   "status", "docstatus"], limit_start, limit_page_length)


# ---------------------------------------------------------------- payroll and attendance (read-only)

@frappe.whitelist()
def list_my_salary_slips(limit_start: int = 0, limit_page_length: int = 12) -> dict:
    """Submitted salary slips of the session user, newest period first."""
    start, length = paging(limit_start, limit_page_length, maximum=MY_LIST_LIMIT)
    rows = frappe.get_all("Salary Slip", filters={"employee": _me().name, "docstatus": 1},
                          fields=["name", "start_date", "end_date", "posting_date", "currency", "gross_pay",
                                  "total_deduction", "net_pay", "rounded_total", "status"],
                          order_by="start_date desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_my_salary_slip(name: str) -> dict:
    doc = _own("Salary Slip", name)
    if doc.docstatus != 1:
        frappe.throw(_("Salary slip {0} is not issued yet").format(name), frappe.PermissionError)

    def components(rows):
        return [{"component": row.salary_component, "abbr": row.abbr, "amount": flt(row.amount)} for row in rows]

    return success({
        "name": doc.name, "start_date": str(doc.start_date), "end_date": str(doc.end_date),
        "posting_date": str(doc.posting_date), "currency": doc.currency,
        "payment_days": flt(doc.payment_days), "total_working_days": flt(doc.total_working_days),
        "gross_pay": flt(doc.gross_pay), "total_deduction": flt(doc.total_deduction),
        "net_pay": flt(doc.net_pay), "rounded_total": flt(doc.rounded_total),
        "earnings": components(doc.earnings), "deductions": components(doc.deductions),
    })


@frappe.whitelist()
def list_my_attendance(from_date: str, to_date: str) -> dict:
    """Submitted attendance records of the session user in a date range (at most 100 days)."""
    start, end = _validated(lambda: date_span(from_date, to_date))
    if (getdate(end) - getdate(start)).days > 100:
        frappe.throw(_("The range may cover at most 100 days"))
    rows = frappe.get_all("Attendance", filters={"employee": _me().name, "docstatus": 1,
                                                 "attendance_date": ["between", [start, end]]},
                          fields=["name", "attendance_date", "status", "leave_type", "shift", "working_hours",
                                  "in_time", "out_time", "late_entry", "early_exit"],
                          order_by="attendance_date asc")
    return success(rows)


@frappe.whitelist()
def get_my_holidays(from_date: str, to_date: str) -> dict:
    """Holidays and weekly offs from the Holiday List that applies to the session user."""
    from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

    start, end = _validated(lambda: date_span(from_date, to_date))
    holiday_list = get_holiday_list_for_employee(_me().name, raise_exception=False)
    if not holiday_list:
        return success({"holiday_list": None, "holidays": []})
    rows = frappe.get_all("Holiday", filters={"parent": holiday_list, "parenttype": "Holiday List",
                                              "holiday_date": ["between", [start, end]]},
                          fields=["holiday_date", "description", "weekly_off"], order_by="holiday_date asc")
    return success({"holiday_list": holiday_list, "holidays": rows})
