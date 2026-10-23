"""Draft equipment delivery and return using ERPNext Asset Movement."""

from datetime import date

KIND = "asset_movement"
LABEL = "جابه‌جایی تجهیزات"
PARAMETERS = {
    "asset": {"label": "تجهیز", "types": ["Link"], "required": True},
    "direction": {"label": "جهت جابه‌جایی", "types": ["Select"], "required": True},
    "date": {"label": "تاریخ جابه‌جایی", "types": ["Date"], "required": False},
    "note": {"label": "توضیحات", "types": ["Text", "LongText"], "required": False},
}


def build(params: dict, ctx: dict) -> dict:
    asset = params.get("asset")
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("تجهیز را انتخاب کنید.")
    direction = params.get("direction")
    if direction not in ("Issue", "Receipt"):
        raise ValueError("جهت جابه‌جایی باید تحویل یا بازگشت باشد.")
    value = params.get("date")
    if value is None or isinstance(value, str) and not value.strip():
        value = ctx["today"]
    try:
        day = date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ValueError("تاریخ جابه‌جایی معتبر نیست.") from None
    note = params.get("note")
    if note is not None and not isinstance(note, str):
        raise ValueError("توضیحات جابه‌جایی معتبر نیست.")
    employee = ctx.get("employee")
    if not employee:
        raise ValueError("پرونده پرسنلی درخواست‌دهنده ثبت نشده است.")
    location = ctx.get("asset_location")
    if not location:
        raise ValueError("مکان تجهیز ثبت نشده یا معتبر نیست.")
    custodian = ctx.get("asset_custodian") or None
    if direction == "Receipt" and custodian != employee:
        raise ValueError("تجهیز در اختیار درخواست‌دهنده نیست و قابل بازگشت نیست.")
    return {
        "doctype": "Asset Movement", "company": ctx["company"], "purpose": direction,
        "docstatus": 0, "transaction_date": day + " 00:00:00",
        "reference_doctype": "ASOUD Workflow Request", "reference_name": ctx["request_name"],
        "assets": [{"asset": asset.strip(), "source_location": location,
                    "target_location": location, "from_employee": custodian,
                    "to_employee": employee if direction == "Issue" else None}],
    }


def apply(request, params: dict):
    import frappe
    from frappe.utils import get_datetime, nowdate

    from asoud_erp.services.request_templates.base import NativeResult
    from asoud_erp.services.session_scope import as_administrator

    employee = frappe.db.get_value("Employee", {
        "user_id": request.owner, "company": request.company, "status": "Active"}, "name")
    if not employee:
        raise ValueError("پرونده پرسنلی درخواست‌دهنده ثبت نشده است.")
    asset_name = params.get("asset")
    if not isinstance(asset_name, str) or not asset_name.strip():
        raise ValueError("تجهیز را انتخاب کنید.")
    asset = frappe.db.get_value("Asset", asset_name.strip(),
                                ["company", "docstatus", "location", "custodian"], as_dict=True)
    if not asset:
        raise ValueError("تجهیز انتخاب‌شده وجود ندارد.")
    if asset.company != request.company:
        raise ValueError("تجهیز انتخاب‌شده متعلق به شرکت درخواست نیست.")
    if asset.docstatus != 1:
        raise ValueError("تجهیز انتخاب‌شده باید تأیید شده باشد.")
    if not asset.location or not frappe.db.exists("Location", asset.location):
        raise ValueError("مکان تجهیز ثبت نشده یا معتبر نیست.")
    payload = build(params, dict(company=request.company, employee=employee, user=request.owner,
        request_name=request.name, today=nowdate(), asset_location=asset.location,
        asset_custodian=asset.custodian))
    previous = frappe.db.get_value("Asset Movement", [
        ["Asset Movement Item", "asset", "=", asset_name.strip()], ["docstatus", "=", 1]],
        "transaction_date", order_by="transaction_date desc")
    if previous and get_datetime(previous) > get_datetime(payload["transaction_date"]):
        raise ValueError("تاریخ جابه‌جایی نمی‌تواند پیش از آخرین جابه‌جایی تجهیز باشد.")
    with as_administrator():
        doc = frappe.get_doc(payload).insert(ignore_permissions=True)
        note = (params.get("note") or "").strip()
        if note:
            # Comment content is HTML in Frappe; user text must remain text.
            from html import escape

            doc.add_comment("Comment", escape(note))
    return NativeResult(status="Created", doctype=doc.doctype, name=doc.name)
