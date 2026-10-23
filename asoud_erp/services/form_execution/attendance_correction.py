"""Append missing punches; leave changes to existing punches for HR review."""

import re
from datetime import date, datetime, time, timedelta

KIND = "attendance_correction"
LABEL = "اصلاح تردد"
PARAMETERS = {
    "date": {"label": "تاریخ تردد", "types": ["Date"], "required": True},
    "kind": {"label": "نوع اصلاح", "types": ["Select"], "required": True},
    "in_time": {"label": "ساعت ورود پیشنهادی", "types": ["Time"], "required": False},
    "out_time": {"label": "ساعت خروج پیشنهادی", "types": ["Time"], "required": False},
    "reason": {"label": "دلیل اصلاح تردد", "types": ["LongText"], "required": False},
}
REVIEW_REASONS = {
    "correct_recorded_time": "نیاز به اقدام HR؛ اصلاح ساعت ثبت‌شده باید با بررسی رکورد اصلی انجام شود.",
    "other": "نیاز به اقدام HR؛ نوع عملیات برای سایر موارد مشخص نشده است.",
}
PUNCHES = {"missing_entry": ("in_time", "IN"), "missing_exit": ("out_time", "OUT")}


def build(params: dict, ctx: dict) -> dict:
    """Build a native payload without importing Frappe or changing the supplied values."""
    if not isinstance(params, dict) or not isinstance(ctx, dict):
        raise ValueError("اطلاعات اصلاح تردد معتبر نیست.")
    if not isinstance(ctx.get("company"), str) or not ctx["company"].strip():
        raise ValueError("شرکت درخواست مشخص نشده است.")
    if not isinstance(ctx.get("employee"), str) or not ctx["employee"].strip():
        raise ValueError("پرونده پرسنلی درخواست‌دهنده ثبت نشده است.")
    day = params.get("date")
    try:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError
        day = date.fromisoformat(day)
    except (TypeError, ValueError):
        raise ValueError("تاریخ تردد معتبر نیست.") from None
    kind = params.get("kind")
    if not isinstance(kind, str) or kind not in (*PUNCHES, *REVIEW_REASONS):
        raise ValueError("نوع اصلاح تردد معتبر نیست.")
    if params.get("reason") is not None and not isinstance(params["reason"], str):
        raise ValueError("دلیل اصلاح تردد باید متن باشد.")
    if kind in REVIEW_REASONS:
        raise ValueError(REVIEW_REASONS[kind])
    key, log_type = PUNCHES[kind]
    clock = params.get(key)
    message = f"{PARAMETERS[key]['label']} معتبر نیست."
    try:
        if not isinstance(clock, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}(:[0-9]{2})?", clock):
            raise ValueError
        if int(clock[:2]) >= 24:
            raise ValueError
        clock = time.fromisoformat(clock)
    except (TypeError, ValueError):
        raise ValueError(message) from None
    next_day = params.get(f"{key}__next_day")
    if next_day is not None and next_day != "" and not isinstance(next_day, bool):
        raise ValueError("گزینه روز بعد معتبر نیست.")
    try:
        timestamp = datetime.combine(day + timedelta(days=1 if next_day else 0), clock)
    except OverflowError:
        raise ValueError("تاریخ تردد معتبر نیست.") from None
    return {
        "doctype": "Employee Checkin", "employee": ctx["employee"], "log_type": log_type,
        "time": timestamp.isoformat(sep=" "), "docstatus": 0,
    }


def apply(request, params: dict):
    """Insert through HRMS; transaction savepoint and result persistence belong to dispatch."""
    import frappe

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    if not request.get("company"):
        frappe.throw("شرکت درخواست مشخص نشده است.")
    if not request.get("owner"):
        frappe.throw("پرونده پرسنلی درخواست‌دهنده ثبت نشده است.")
    # Serialize punches for this employee, including competing approved requests.
    employee = frappe.db.get_value(
        "Employee", {"user_id": request.owner, "company": request.company},
        ["name", "status"], as_dict=True, for_update=True,
    )
    if not employee:
        frappe.throw("پرونده پرسنلی درخواست‌دهنده ثبت نشده است.")
    if employee.status != "Active":
        frappe.throw("پرونده پرسنلی درخواست‌دهنده فعال نیست.")
    ctx = {"company": request.company, "employee": employee.name, "user": request.owner,
           "request_name": request.name, "today": frappe.utils.nowdate()}
    try:
        payload = build(params, ctx)
    except ValueError as error:
        # Only the two explicit review outcomes are converted; malformed input still fails.
        kind = params.get("kind") if isinstance(params, dict) else None
        if isinstance(kind, str) and kind in REVIEW_REASONS and str(error) == REVIEW_REASONS[kind]:
            return NativeResult(status="needs_review", reason=str(error))
        raise
    duplicate = frappe.db.exists("Employee Checkin", {
        "employee": employee.name, "time": payload["time"], "log_type": payload["log_type"],
    })
    if duplicate:
        frappe.throw("برای این کارمند تردد با همین زمان و نوع قبلاً ثبت شده است.")
    if frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"):
        frappe.throw("ثبت تردد به موقعیت مکانی نیاز دارد؛ درخواست باید توسط منابع انسانی بررسی شود.")
    with as_administrator():
        try:
            doc = frappe.get_doc(payload).insert(ignore_permissions=True)
        except frappe.ValidationError:
            frappe.throw("ثبت تردد انجام نشد؛ تنظیمات شیفت و الزامات تردد را بررسی کنید.")
    return NativeResult(status="Created", doctype=doc.doctype, name=doc.name)
