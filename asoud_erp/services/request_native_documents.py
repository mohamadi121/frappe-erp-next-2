"""Native ERPNext/HRMS documents created after a request is finally approved (CONTRACT 4.12).

``lifecycle.on_instance_update`` calls ``dispatch(request)`` when the workflow instance
becomes ``Completed``; ``workflow_request.create_native_document`` calls it again to retry a
failed request. Payload mapping is pure (``native_payloads``). Rules kept here:

* idempotent: an existing document is found by ``asoud_request`` (Material Request, Leave
  Application) or ``(transaction_type, transaction_name)`` (Leave Ledger Entry);
* the work runs in a savepoint; any failure rolls back only the native document, records
  ``native_status = Failed`` and never un-approves the request;
* native documents are drafts (docstatus 0), except the Leave Application, which our workflow
  already approved, and the Leave Ledger Entry, which HRMS itself always submits.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, getdate

from asoud_erp.services import leave_balance as lb
from asoud_erp.services import leave_hours as lh
from asoud_erp.services import native_payloads as payloads
from asoud_erp.services.request_templates import base
from asoud_erp.services.request_templates.lifecycle import record_native_failure
from asoud_erp.services.session_scope import as_administrator

SAVEPOINT = "asoud_native_doc"
ERROR_LIMIT = 1000


def effective_values(request) -> dict:
    """The request values: ``values_json`` overlaid with what the form task was completed with.

    Delegates to the engine's ``workflow_request.effective_values``: edits made through the
    cartable after a Return live in the task response, not in ``values_json`` (CONTRACT 4.12).
    """
    from asoud_erp.api.v1.workflow_request import effective_values as engine_effective_values

    return engine_effective_values(request.name)


# ------------------------------------------------------------------ dispatch


def dispatch(request) -> None:
    """Creates the native document of an approved template request, once.

    Safe to call repeatedly: ``Created`` and ``Skipped`` requests are left alone, a
    ``Failed`` one is tried again (the retry endpoint).
    """
    spec = base.get(request.get("template_key"))
    if not spec:
        return
    if frappe.db.get_value("ASOUD Workflow Request", request.name, "native_status") in ("Created", "Skipped"):
        return
    frappe.db.savepoint(SAVEPOINT)
    try:
        result = spec.on_approved(request)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise  # the transaction is already gone; the approval is retried as a whole
    except Exception as error:  # noqa: BLE001 - nothing here may undo the approval (CONTRACT 4.12)
        frappe.db.rollback(save_point=SAVEPOINT)
        if not isinstance(error, (frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError,
                                  ValueError)):
            frappe.log_error(title=f"Native document of {request.name} failed")
        message = _error_text(error)
        frappe.clear_messages()
        # Marks the request Failed and notifies the requester, HR Managers and System Managers.
        record_native_failure(request.name, message[:ERROR_LIMIT])
        return
    frappe.db.set_value("ASOUD Workflow Request", request.name, {
        "native_doctype": result.doctype or "", "native_name": result.name or "",
        "native_status": result.status, "native_error": result.reason or "",
    }, update_modified=False)


def _error_text(error: Exception) -> str:
    """``CODE: message`` when the error was raised with a contract code as its title."""
    code = ""
    for entry in reversed(frappe.local.message_log or []):
        entry = entry if isinstance(entry, dict) else _loads(entry)
        if entry.get("title"):
            code = entry["title"]
            break
    text = frappe.utils.strip_html_tags(str(error) or error.__class__.__name__).strip()
    return f"{code}: {text}" if code.isupper() and not text.startswith(code) else text


def _loads(entry) -> dict:
    try:
        value = json.loads(entry)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# ------------------------------------------------------------------ Material Request


def _complete_rows(values: dict) -> dict:
    """Item rows need ``stock_uom`` and ``conversion_factor``; the engine normally adds them."""
    rows = []
    for row in values.get("items") or []:
        if not row.get("stock_uom"):
            row = {**row, "stock_uom": frappe.db.get_value("Item", row.get("item_code"), "stock_uom")}
        rows.append(row)
    return {**values, "items": rows}



def _has_stock_items(values: dict) -> bool:
    for row in values.get("items") or []:
        flag = row.get("is_stock_item")
        if flag is not None:
            if cint(flag):
                return True
            continue
        if frappe.db.get_value("Item", row.get("item_code"), "is_stock_item"):
            return True
    return False


def _default_warehouse(company: str) -> str | None:
    """``Stock Settings.default_warehouse`` when it belongs to the request's company.

    ERPNext refuses a stock item row without a warehouse, so a site without a usable default
    leaves such a request ``Failed`` until one is set (CONTRACT 4.12 names this warehouse).
    """
    warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    if warehouse and frappe.db.get_value("Warehouse", warehouse, "company") == company:
        return warehouse
    return None


def create_material_request(request, template_key: str) -> base.NativeResult:
    """Draft Material Request of a purchase or supply request (CONTRACT 4.12)."""
    existing = frappe.db.get_value("Material Request", {"asoud_request": request.name}, "name")
    if existing:
        return base.NativeResult(status="Created", doctype="Material Request", name=existing)
    values = _complete_rows(effective_values(request))
    default_warehouse = _default_warehouse(request.company)
    if template_key == "purchase" and not default_warehouse and _has_stock_items(values):
        base.throw_error("DEFAULT_WAREHOUSE_REQUIRED")
    payload = payloads.material_request_payload(
        template_key=template_key, request_name=request.name, company=request.company,
        creation_date=str(getdate(request.creation)), values=values,
        default_warehouse=default_warehouse)
    if payload is None:
        return base.NativeResult(status="Skipped", reason=payloads.NO_NATIVE_DOCUMENT)
    doc = frappe.get_doc(payload)
    # Contract 4.12: the system creates the draft on the requester's behalf; the approver who
    # triggers it is usually a manager without Material Request or Comment permission.
    with as_administrator():
        doc.insert(ignore_permissions=True)
        doc.add_comment("Comment", _("Created from request {0}").format(request.name))
    return base.NativeResult(status="Created", doctype="Material Request", name=doc.name)


# ------------------------------------------------------------------ leave


def _requester_employee(request):
    name = request.get("requester_employee") or frappe.db.get_value(
        "Employee", {"user_id": request.owner, "company": request.company, "status": "Active"}, "name")
    if not name:
        base.throw_error("EMPLOYEE_NOT_FOUND")
    return frappe.db.get_value("Employee", name, ["name", "employee_name", "holiday_list"], as_dict=True)


def create_leave_document(request) -> base.NativeResult:
    """Daily leave becomes an approved Leave Application, hourly leave a Leave Ledger Entry."""
    values = effective_values(request)
    employee = _requester_employee(request)
    if values.get("request_kind") == "Hourly":
        return _create_hourly_ledger_entry(request, values, employee)
    return _create_leave_application(request, values, employee)


def _create_leave_application(request, values: dict, employee) -> base.NativeResult:
    existing = frappe.db.get_value("Leave Application", {"asoud_request": request.name}, "name")
    if existing:
        return base.NativeResult(status="Created", doctype="Leave Application", name=existing)
    payload = payloads.leave_application_payload(
        request_name=request.name, employee=employee.name, company=request.company, values=values,
        creation_date=str(getdate(request.creation)), approver=frappe.session.user)
    doc = frappe.get_doc(payload)
    # Contract 4.12: HRMS' own validate() and on_submit() run in full (balance, overlap, block
    # days, Attendance); only permission checks are skipped because the approver is not the
    # employee. A failure is recorded as native_status = Failed by dispatch().
    # Administrator only because HRMS validate_leave_access (in get_leave_balance_on) refuses a manager who is not the leave approver.
    with as_administrator():
        doc.insert(ignore_permissions=True)
        doc.submit()
    return base.NativeResult(status="Created", doctype="Leave Application", name=doc.name)


def _create_hourly_ledger_entry(request, values: dict, employee) -> base.NativeResult:
    existing = frappe.db.get_value(
        "Leave Ledger Entry",
        {"transaction_type": payloads.LEDGER_TRANSACTION_TYPE, "transaction_name": request.name}, "name")
    if existing:
        return base.NativeResult(status="Created", doctype="Leave Ledger Entry", name=existing)
    daily_hours = lb.daily_working_hours(request.company)
    # The stored duration may predate a cartable edit after a Return, so it is recomputed.
    duration = lh.hourly_duration(values.get("start_time"), values.get("end_time"), daily_hours)
    values = {**values, "duration": duration}
    info = lb.leave_type_info(values["leave_type"])
    # Administrator only because HRMS validate_leave_access (in get_leave_details) refuses a manager who is not the leave approver.
    with as_administrator():
        rows = lb.leave_type_rows(employee.name, getdate(values["leave_date"]), exclude_request=request.name)
    if lh.exceeds_remaining(duration["day_equivalent"], lb.balance_for(rows, info.name),
                            is_lwp=bool(cint(info.is_lwp)), allow_negative=bool(cint(info.allow_negative))):
        lb.fail("INSUFFICIENT_LEAVE_BALANCE")
    holiday_list = employee.holiday_list or _holiday_list(employee.name)
    payload = payloads.leave_ledger_payload(
        request_name=request.name, employee=employee.name, employee_name=employee.employee_name,
        company=request.company, values=values, daily_hours=daily_hours, is_lwp=bool(cint(info.is_lwp)),
        holiday_list=holiday_list)
    # Same as HRMS' create_leave_ledger_entry: ledger rows are posted by the system, not by a user.
    doc = frappe.get_doc(payload)
    doc.flags.ignore_permissions = 1
    doc.submit()
    return base.NativeResult(status="Created", doctype="Leave Ledger Entry", name=doc.name)


def _holiday_list(employee: str) -> str:
    from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

    return get_holiday_list_for_employee(employee, raise_exception=False) or ""
