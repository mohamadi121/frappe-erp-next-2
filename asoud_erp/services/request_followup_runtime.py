"""Database side of follow-up tasks: create, confirm, reject and cancel (N6, docs/api/form-execution.md)."""

import json
from html import escape

import frappe
from frappe.utils import now_datetime

from asoud_erp.services import request_followup as rules
from asoud_erp.services.request_access import company_access
from asoud_erp.services.session_scope import as_administrator

TASK = "ASOUD Workflow Task"
REQUEST = "ASOUD Workflow Request"
ALERT_ROLES = ("HR Manager", "Stock Manager")
NOT_REQUESTER = "فقط درخواست‌دهنده می‌تواند دریافت تجهیز را تأیید کند."
NOT_FOUND = "وظیفه تأیید دریافت یافت نشد."
NOT_RECEIPT = "این وظیفه تأیید دریافت تجهیز نیست."
FOREIGN = "جابه‌جایی تجهیز به این درخواست مربوط نیست."
ALREADY_SUBMITTED = "این جابه‌جایی قبلاً تأیید شده است."
NATIVE_REFUSED = ("تأیید دریافت انجام نشد؛ وضعیت تجهیز پس از ثبت درخواست تغییر کرده است. "
                  "موضوع را به منابع انسانی اطلاع دهید.")
STATUS_LABELS = {0: "پیش‌نویس", 1: "تأییدشده", 2: "لغوشده"}


def _fail(message: str, error=None):
    frappe.throw(message, error or frappe.ValidationError)


# ------------------------------------------------------------------ create


def _end_stage(definition: str) -> str:
    stage = frappe.db.get_value("ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "End"},
                                "name", order_by="sequence_no desc") or frappe.db.get_value(
        "ASOUD Workflow Stage", {"workflow_definition": definition}, "name", order_by="sequence_no desc")
    if not stage:
        raise ValueError("مراحل گردش کار درخواست برای ثبت وظیفه تأیید دریافت در دسترس نیست.")
    return stage


def _existing(instance: str, marker: dict) -> str | None:
    for row in frappe.get_all(TASK, filters={"workflow_instance": instance},
                              fields=["name", "draft_json"], limit_page_length=0):
        found = rules.followup_of(row.draft_json)
        if found and (found["kind"], found["name"]) == (marker["kind"], marker["name"]):
            return row.name
    return None


def create_followup(request, raw: dict) -> str:
    """The follow-up task of ``raw`` (an executor's ``followup``) for the requester; one per document."""
    marker = rules.normalize(raw, request.owner)
    instance = request.get("workflow_instance")
    if not instance:
        raise ValueError("درخواست گردش کار ندارد و وظیفه تأیید دریافت ثبت نمی‌شود.")
    if not frappe.db.get_value("User", request.owner, "enabled"):
        raise ValueError("حساب کاربری درخواست‌دهنده فعال نیست.")
    existing = _existing(instance, marker)
    if existing:
        return existing
    definition = frappe.db.get_value("ASOUD Workflow Instance", instance, "workflow_definition")
    task = frappe.get_doc({
        "doctype": TASK, "workflow_instance": instance, "workflow_stage": _end_stage(definition),
        "task_title": rules.task_title(marker), "assigned_to": request.owner, "status": "Open",
        "assigned_on": now_datetime(), "draft_json": json.dumps({rules.MARKER: marker}, ensure_ascii=False),
    }).insert(ignore_permissions=True)
    _activity(task, "تخصیص وظیفه")
    _notify(request.owner, task.task_title, instance, "پس از دریافت تجهیز آن را تأیید کنید.")
    return task.name


def _activity(task, action: str, comment: str = "") -> None:
    frappe.get_doc({"doctype": "ASOUD Workflow Activity", "workflow_instance": task.workflow_instance,
                    "workflow_task": task.name, "workflow_stage": task.workflow_stage,
                    "actor": frappe.session.user, "action": action, "comment": comment,
                    "created_on": now_datetime()}).insert(ignore_permissions=True)


def _notify(user: str, subject: str, instance: str, message: str = "") -> None:
    if not user or user in ("Guest", "Administrator"):
        return
    frappe.get_doc({"doctype": "Notification Log", "for_user": user, "from_user": frappe.session.user,
                    "type": "Alert", "subject": subject[:140], "document_type": "ASOUD Workflow Instance",
                    "document_name": instance, "email_content": message[:500], "read": 0}
                   ).insert(ignore_permissions=True)


# ------------------------------------------------------------------ detail for the cartable


def detail_document(marker: dict) -> dict:
    """The ``document`` block of ``get_workflow_task`` for a follow-up task (read for the assignee)."""
    movement = frappe.db.get_value(marker["doctype"], marker["name"],
                                   ["transaction_date", "docstatus"], as_dict=True)
    row = frappe.db.get_value("Asset Movement Item", {"parent": marker["name"]},
                              ["asset", "target_location"], as_dict=True) if movement else None
    asset_name = (frappe.db.get_value("Asset", row.asset, "asset_name") if row else None) or marker.get("subject")
    values = [("asset", "تجهیز", asset_name),
              ("transaction_date", "تاریخ تحویل", str(movement.transaction_date)[:10] if movement else None),
              ("target_location", "مکان تحویل", row.target_location if row else None),
              ("movement_status", "وضعیت", STATUS_LABELS.get(movement.docstatus) if movement else "لغوشده")]
    return {"doctype": marker["doctype"], "name": marker["name"],
            "values": [{"key": key, "label": label, "value": value, "read_only": True}
                       for key, label, value in values if value not in (None, "")]}


# ------------------------------------------------------------------ act


def _lock(task_name):
    """The task and its request, locked, after every access check (requester only)."""
    if not isinstance(task_name, str) or not task_name.strip() or not frappe.db.sql(
            "select name from `tabASOUD Workflow Task` where name=%s for update", task_name.strip()):
        _fail(NOT_FOUND)
    task = frappe.get_doc(TASK, task_name.strip())
    marker = rules.followup_of(task.draft_json)
    if not marker:
        _fail(NOT_RECEIPT)
    request = frappe.db.get_value(REQUEST, {"workflow_instance": task.workflow_instance},
                                  ["name", "company", "owner"], as_dict=True)
    user = frappe.session.user
    if (not request or task.assigned_to != user or request.owner != user or not company_access(request.company)
            or not frappe.db.exists("Employee", {"user_id": user, "company": request.company, "status": "Active"})):
        _fail(NOT_REQUESTER, frappe.PermissionError)
    message = rules.closed_message(task.status)
    if message:
        _fail(message)
    return task, marker, request


def _draft_movement(task, marker, request):
    row = frappe.db.sql("select name, docstatus, company, reference_doctype, reference_name from `tabAsset Movement` "
                        "where name=%s for update", marker["name"], as_dict=True)
    if not row:
        _fail(rules.closed_message("Cancelled"))
    movement = row[0]
    if movement.docstatus == 2:
        _fail(rules.closed_message("Cancelled"))
    if (movement.reference_doctype, movement.reference_name, movement.company) != (REQUEST, request.name, request.company):
        _fail(FOREIGN)
    if movement.docstatus == 1:
        _fail(ALREADY_SUBMITTED)
    return movement


def _close(task, status: str, action: str, comment: str, marker: dict, movement) -> dict:
    task.status, task.action, task.comment = status, action, comment
    task.completed_on = now_datetime()
    task.response_json = json.dumps({"followup": marker, "result": status}, ensure_ascii=False)
    task.save(ignore_permissions=True)
    return {"task": task.name, "status": status, "movement": {
        "doctype": marker["doctype"], "name": movement.name,
        "docstatus": frappe.db.get_value("Asset Movement", movement.name, "docstatus")}}


def confirm(task_name) -> dict:
    """The requester received the equipment: submit the movement (ERPNext sets the custodian)."""
    task, marker, request = _lock(task_name)
    movement = _draft_movement(task, marker, request)
    frappe.db.savepoint("asoud_receipt_confirm")
    try:
        with as_administrator():
            doc = frappe.get_doc("Asset Movement", movement.name)
            doc.flags.ignore_permissions = True
            doc.submit()
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception as error:  # ERPNext validation text is English; the reason is logged, not shown
        frappe.db.rollback(save_point="asoud_receipt_confirm")
        frappe.log_error(title=f"Receipt confirmation of {movement.name} failed",
                         message=frappe.utils.strip_html_tags(str(error)))
        frappe.clear_messages()
        _fail(NATIVE_REFUSED)
    result = _close(task, "Completed", "Complete", "", marker, movement)
    _activity(task, "تأیید دریافت تجهیز")
    return result


def reject(task_name, reason) -> dict:
    """The requester did not receive the equipment: keep the draft, tell HR and the asset managers."""
    task, marker, request = _lock(task_name)
    try:
        reason = rules.clean_reason(reason)
    except ValueError as error:
        _fail(str(error))
    movement = _draft_movement(task, marker, request)
    doc = frappe.get_doc("Asset Movement", movement.name)
    with as_administrator():
        # Comment content is HTML in Frappe; the user's text must stay text.
        doc.add_comment("Comment", "عدم دریافت تجهیز توسط درخواست‌دهنده: " + escape(reason))
    result = _close(task, "Rejected", "Reject", reason, marker, movement)
    _activity(task, "عدم دریافت تجهیز", reason)
    for user in _alert_users(request):
        _notify(user, "عدم دریافت تجهیز در " + request.name, task.workflow_instance, reason)
    return result


def _alert_users(request) -> list[str]:
    holders = frappe.get_all("Has Role", filters={"role": ["in", list(ALERT_ROLES)], "parenttype": "User"},
                             pluck="parent", limit_page_length=0)
    enabled = frappe.get_all("User", filters={"name": ["in", holders or [""]], "enabled": 1}, pluck="name")
    return [user for user in dict.fromkeys(enabled)
            if user not in ("Administrator", "Guest", request.owner) and company_access(request.company, user)]


# ------------------------------------------------------------------ movement lifecycle hook


def cancel_open_tasks(doc, method=None) -> None:
    """``Asset Movement`` ``on_cancel`` / ``on_trash``: its open follow-up task can no longer be acted on."""
    instance = frappe.db.get_value(REQUEST, {"name": doc.get("reference_name") or ""}, "workflow_instance") \
        if doc.get("reference_doctype") == REQUEST else None
    if not instance:
        return
    for row in frappe.get_all(TASK, filters={"workflow_instance": instance, "status": "Open"},
                              fields=["name", "draft_json"], limit_page_length=0):
        marker = rules.followup_of(row.draft_json)
        if marker and marker["name"] == doc.name:
            frappe.db.set_value(TASK, row.name, {"status": "Cancelled", "completed_on": now_datetime()})
