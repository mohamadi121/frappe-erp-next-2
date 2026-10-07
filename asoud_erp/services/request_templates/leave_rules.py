"""Leave rules of the ``leave`` template (CONTRACT 3.6, 4.12); the spec itself is ``leave.py``.

``evaluate_leave`` holds every business rule once. The template ``validate`` raises its
first error, ``preview_leave_request`` returns all of them as data, so the two can never
drift. Pure maths is in ``services.leave_hours``; native documents are created by
``services.request_native_documents``.
"""

import json
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, nowdate

from asoud_erp.services import leave_balance as lb
from asoud_erp.services import leave_hours as lh

KINDS = ("Daily", "Hourly")
#: HRMS rules without a contract error code (max consecutive days, block dates, ...).
HRMS_RULE_CODE = "LEAVE_RULE_VIOLATION"


def _strip(message: str) -> str:
    return frappe.utils.strip_html_tags(message or "").strip()


def _iso(value, field: str) -> date | None:
    """A date value from the client; malformed input is a plain validation error."""
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        frappe.throw(_("{0} must be a YYYY-MM-DD date").format(field))


def _hrms_holiday_list(employee) -> str | None:
    from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

    return employee.get("holiday_list") or get_holiday_list_for_employee(employee.name, raise_exception=False)


# ------------------------------------------------------------------ other leave of the employee


def _segment(row) -> dict | None:
    values = row["values"]
    if values.get("request_kind") == "Hourly":
        day = _iso(values.get("leave_date"), "leave_date")
        try:
            start, end = lh.parse_hhmm(values.get("start_time")), lh.parse_hhmm(values.get("end_time"))
        except lh.LeaveRuleError:
            return None
        return {"name": row.name, "kind": "Hourly", "from": day, "to": day, "start": start, "end": end}
    start_date, end_date = _iso(values.get("start_date"), "start_date"), _iso(values.get("end_date"), "end_date")
    if not (start_date and end_date):
        return None
    return {"name": row.name, "kind": "Daily", "from": start_date, "to": end_date, "start": 0, "end": 1440}


def other_segments(employee: str, from_date: date, to_date: date, exclude_request: str | None) -> list[dict]:
    """Leave of this employee that still blocks the calendar, from the requests table.

    * in-flight requests (``submitted``, ``in_review``, ``returned``);
    * approved requests whose native document is missing or failed;
    * approved requests dated inside the range (hourly leave has no Leave Application, only a
      ledger entry without times, so the request carries the times).
    """
    base = {"template_key": "leave", "requester_employee": employee}
    fields = ["name", "values_json", "required_by"]
    rows = {}
    queries = [
        {"status_key": ["in", list(lb.IN_FLIGHT_STATUS_KEYS)]},
        {"status_key": "approved", "native_status": ["in", ["", "Pending", "Failed"]]},
        {"status_key": "approved", "required_by": ["between", [from_date, to_date]]},
    ]
    for extra in queries:
        for row in frappe.get_all("ASOUD Workflow Request", filters={**base, **extra}, fields=fields,
                                  limit_page_length=0):
            rows[row.name] = row
    result = []
    for name, row in rows.items():
        if name == exclude_request:
            continue
        row["values"] = json.loads(row.values_json or "{}")
        segment = _segment(row)
        if segment and segment["from"] <= to_date and segment["to"] >= from_date:
            result.append(segment)
    return result


def _leave_application_on(employee: str, day: date) -> bool:
    return bool(frappe.db.exists("Leave Application", {
        "employee": employee, "docstatus": ["<", 2], "status": ["in", ["Open", "Approved"]],
        "from_date": ["<=", day], "to_date": [">=", day]}))


# ------------------------------------------------------------------ HRMS dry run


def _dry_run_leave_application(employee, company: str, leave_type: str, start: date, end: date,
                               reason: str, errors: list) -> None:
    """Runs HRMS ``Leave Application.validate`` (plus our overlay hook) on an unsaved document.

    Status stays ``Open``: the real document is created ``Approved`` at the end of the
    approval, but ``Approved`` would trip HRMS' self-approval and block-date checks for the
    requester. Messages queued meanwhile are discarded, earlier ones are kept.
    """
    from hrms.hr.doctype.leave_application.leave_application import (
        InsufficientLeaveBalanceError,
        OverlapError,
    )

    saved = list(frappe.local.message_log or [])
    doc = frappe.new_doc("Leave Application")
    doc.update({"employee": employee.name, "company": company, "leave_type": leave_type,
                "from_date": start, "to_date": end, "half_day": 0, "status": "Open",
                "description": reason or "", "posting_date": nowdate()})
    try:
        doc.run_method("validate")
    except frappe.ValidationError as error:
        message = _strip(str(error))
        if isinstance(error, OverlapError):
            code = "LEAVE_OVERLAP"
        elif isinstance(error, InsufficientLeaveBalanceError):
            code = "INSUFFICIENT_LEAVE_BALANCE"
        else:
            code = HRMS_RULE_CODE
        errors.append({"code": code, "field": "leave_type" if code == "INSUFFICIENT_LEAVE_BALANCE"
                       else "start_date", "message": lh.MESSAGES.get(code) or message})
    finally:
        frappe.local.message_log = saved


# ------------------------------------------------------------------ rule engine


def evaluate_leave(company: str, employee, values: dict, *, exclude_request: str | None = None,
                   today: date | None = None, dry_run_hrms: bool = True,
                   check_backdated: bool = True) -> dict:
    """All leave rules for ``values``; never raises for business errors.

    Returns ``{"errors": [{code, field, message}], "duration": dict | None,
    "balance": dict | None, "holidays_excluded": int, "complete": bool}``. ``balance`` is the
    ``preview_leave_request`` balance object. ``complete`` is false while required inputs are
    still missing (a form being typed into), in which case ``errors`` stays empty.
    """
    today = today or getdate(nowdate())
    errors: list[dict] = []

    def add(code: str, field: str | None, message: str | None = None) -> None:
        if not any(error["code"] == code for error in errors):
            errors.append({"code": code, "field": field, "message": message or lh.MESSAGES[code]})

    kind = values.get("request_kind") or "Daily"
    if kind not in KINDS:
        frappe.throw(_("Request kind must be Daily or Hourly"))
    leave_type = values.get("leave_type")
    info = lb.leave_type_info(leave_type) if leave_type else None
    if leave_type and not info:
        frappe.throw(_("Leave Type {0} does not exist").format(leave_type))
    result = {"errors": errors, "duration": None, "balance": None, "holidays_excluded": 0,
              "complete": False}
    daily_hours = lb.daily_working_hours(company)
    restrict_backdated = check_backdated and bool(
        frappe.db.get_single_value("HR Settings", "restrict_backdated_leave_application"))
    include_holiday = bool(info and cint(info.include_holiday))

    if kind == "Daily":
        start, end = _iso(values.get("start_date"), "start_date"), _iso(values.get("end_date"), "end_date")
        if not (leave_type and start and end):
            return _with_balance(result, employee, info, exclude_request, None, start)
        result["complete"] = True
        if end < start:
            add("INVALID_DATE_RANGE", "end_date")
        else:
            if restrict_backdated and start < today:
                add("DATE_IN_PAST", "start_date")
            try:
                from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days

                days = flt(get_number_of_leave_days(employee.name, leave_type, start, end, 0, None,
                                                    holiday_list=_hrms_holiday_list(employee)))
            except frappe.ValidationError as error:
                days = None
                add(HRMS_RULE_CODE, "start_date", _strip(str(error)))
            if days is not None:
                if days <= 0:
                    add("LEAVE_ALL_HOLIDAYS", "start_date")
                else:
                    result["duration"] = lh.daily_duration(days)
                    result["holidays_excluded"] = 0 if include_holiday else max(
                        int(date_diff(end, start) + 1 - days), 0)
            if other_segments(employee.name, start, end, exclude_request):
                add("LEAVE_OVERLAP", "start_date")
    else:
        day = _iso(values.get("leave_date"), "leave_date")
        start_time, end_time = values.get("start_time"), values.get("end_time")
        if not (leave_type and day and start_time and end_time):
            return _with_balance(result, employee, info, exclude_request, None, day)
        result["complete"] = True
        if restrict_backdated and day < today:
            add("DATE_IN_PAST", "leave_date")
        others = other_segments(employee.name, day, day, exclude_request)
        try:
            start_minutes, end_minutes = lh.parse_hhmm(start_time, "start_time"), lh.parse_hhmm(end_time, "end_time")
            other_minutes = sum(o["end"] - o["start"] for o in others if o["kind"] == "Hourly")
            result["duration"] = lh.hourly_duration(start_time, end_time, daily_hours, other_minutes)
        except lh.LeaveRuleError as error:
            add(error.code, error.field, error.message)
            start_minutes = end_minutes = None
        if not include_holiday:
            holiday_list = _hrms_holiday_list(employee)
            if holiday_list and frappe.db.exists("Holiday", {"parent": holiday_list, "parenttype": "Holiday List",
                                                             "holiday_date": day}):
                add("HOURLY_ON_HOLIDAY", "leave_date")
        if (any(o["kind"] == "Daily" for o in others) or _leave_application_on(employee.name, day)
                or (start_minutes is not None and any(
                    o["kind"] == "Hourly" and lh.minutes_overlap(start_minutes, end_minutes, o["start"], o["end"])
                    for o in others))):
            add("LEAVE_OVERLAP", "leave_date")
    if dry_run_hrms and kind == "Daily" and result["duration"] and not errors:
        _dry_run_leave_application(employee, company, leave_type, start, end,
                                   str(values.get("reason") or ""), errors)
    return _with_balance(result, employee, info, exclude_request,
                         (result["duration"] or {}).get("day_equivalent"), start if kind == "Daily" else day)


def _with_balance(result: dict, employee, info, exclude_request, day_equivalent, as_of) -> dict:
    """Adds the balance object and the INSUFFICIENT_LEAVE_BALANCE rule (``day_equivalent <= available``).

    The balance is read as of the leave's own date, so a leave in next year's allocation period
    is checked against that allocation.
    """
    if not info:
        return result
    rows = lb.leave_type_rows(employee.name, as_of, exclude_request=exclude_request)
    balance = lb.balance_for(rows, info.name)
    result["balance"] = lh.preview_balance(info.name, balance, day_equivalent or 0)
    if day_equivalent and lh.exceeds_available(day_equivalent, balance, is_lwp=bool(cint(info.is_lwp)),
                                              allow_negative=bool(cint(info.allow_negative))):
        if not any(error["code"] == "INSUFFICIENT_LEAVE_BALANCE" for error in result["errors"]):
            result["errors"].append({"code": "INSUFFICIENT_LEAVE_BALANCE", "field": "leave_type",
                                     "message": lh.MESSAGES["INSUFFICIENT_LEAVE_BALANCE"]})
    return result


# ------------------------------------------------------------------ template callables


def validate(ctx) -> dict:
    """Runs ``evaluate_leave`` and raises its first error with the contract code."""
    from asoud_erp.services.request_templates import common

    common.check_requester(ctx)
    employee = lb.active_employee(ctx.company, ctx.user)
    previous = ctx.previous or {}
    # On an edit the date rules only apply to what changed (like ``needed_date`` of purchase).
    unchanged = ctx.is_update and all(ctx.values.get(key) == previous.get(key)
                                      for key in ("request_kind", "start_date", "leave_date"))
    outcome = evaluate_leave(ctx.company, employee, ctx.values, exclude_request=ctx.request_name,
                             check_backdated=not unchanged)
    if outcome["errors"]:
        error = outcome["errors"][0]
        lb.fail(error["code"], error["message"])
    if not outcome["duration"]:
        frappe.throw(_("The leave duration could not be computed"), exc=frappe.ValidationError)
    return {**ctx.values, "duration": outcome["duration"]}


def build_subject(values: dict) -> str:
    """«مرخصی سالانه (روزانه)»: the client-supplied subject is ignored (CONTRACT 3.6)."""
    return lh.leave_subject(lb.leave_type_category(values.get("leave_type") or ""),
                            values.get("request_kind") or "Daily")


def leave_type_label(leave_type: str | None) -> str:
    """Persian category label; ``<category> \u2014 <Leave Type>`` when several types share a category."""
    from asoud_erp.services.request_templates import common

    if not leave_type:
        return ""
    category = common.cached_value("Leave Type", leave_type, "asoud_leave_category") or ""
    label = lh.category_label(category)
    if category and common.memo(("leave_types_in", category), lambda: frappe.db.count(
            "Leave Type", {"asoud_leave_category": category})) > 1:
        return f"{label} \u2014 {leave_type}"
    return label


def summarize(values: dict, request_row: dict) -> dict:
    from asoud_erp.services.request_templates import common

    hourly = values.get("request_kind") == "Hourly"
    leave_type = values.get("leave_type")
    category = (common.cached_value("Leave Type", leave_type, "asoud_leave_category") or "") if leave_type else ""
    from_date = values.get("leave_date") if hourly else values.get("start_date")
    to_date = values.get("leave_date") if hourly else values.get("end_date")
    return {
        "leave_type": leave_type or "", "leave_type_label": leave_type_label(leave_type),
        "category": category, "category_label": lh.category_label(category) if category else "",
        "request_kind": values.get("request_kind") or "Daily",
        "from_date": from_date, "to_date": to_date,
        "start_time": values.get("start_time") if hourly else None,
        "end_time": values.get("end_time") if hourly else None,
        "duration": values.get("duration"),
        "location": values.get("location") or "",
        "location_label": common.batched_label(request_row, "branch", values.get("location"), "Branch", "name"),
        "rejection_reason": (request_row or {}).get("rejection_reason") or "",
    }
