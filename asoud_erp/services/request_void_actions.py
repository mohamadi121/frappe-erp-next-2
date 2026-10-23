"""Frappe side of void and reissue (rules in ``request_void``). Called by thin endpoints."""

from html import escape

import frappe
from frappe import _
from frappe.utils import get_fullname, now_datetime

from asoud_erp.services import request_void as rules
from asoud_erp.services.request_templates import base as templates
from asoud_erp.services.request_templates.lifecycle import notify_native_result
from asoud_erp.services.session_scope import as_administrator

REQUEST_DOCTYPE = "ASOUD Workflow Request"
SAVEPOINT = "asoud_void_native"


def _fail(key: str, code: str = "NATIVE_NOT_VOIDABLE") -> None:
    templates.throw_error(code, rules.ERRORS[key])


def _activity(doc, action: str, comment: str, reference_doctype: str, reference_name: str) -> None:
    stage = frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "current_stage")
    frappe.get_doc({
        "doctype": "ASOUD Workflow Activity", "workflow_instance": doc.workflow_instance,
        "workflow_stage": stage, "actor": frappe.session.user, "action": action,
        "comment": comment[:1000], "created_on": now_datetime(),
        "reference_doctype": reference_doctype, "reference_name": reference_name,
    }).insert(ignore_permissions=True)


def marker_actions(instance: str) -> list[str]:
    return frappe.get_all("ASOUD Workflow Activity", filters={
        "workflow_instance": instance, "action": ["in", ["Voided", "Reissued"]]},
        order_by="created_on asc, creation asc", pluck="action", limit_page_length=0)


def last_void(instance: str, privileged: bool) -> dict:
    """``{reason, by_name, on, reference}`` of the latest void; empty for non-privileged callers."""
    if not privileged or not instance:
        return {}
    row = frappe.db.get_value("ASOUD Workflow Activity", {"workflow_instance": instance, "action": "Voided"},
                              ["comment", "actor", "created_on", "reference_name"], as_dict=True,
                              order_by="created_on desc, creation desc")
    if not row:
        return {}
    return {"reason": row.comment or "", "by_name": get_fullname(row.actor), "on": str(row.created_on or ""),
            "reference": row.reference_name or ""}


def void(doc, reason) -> None:
    """Voids ``doc.native_name``; ``doc`` is the locked request. Raises a Persian ValidationError."""
    try:
        text = rules.clean_reason(reason)
    except ValueError as error:
        templates.throw_error("VOID_REASON_REQUIRED", str(error))
    instance_status = frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "status") \
        if doc.workflow_instance else None
    if not rules.can_void(instance_status, doc.native_status, doc.native_name):
        _fail("not_voidable")
    doctype, name = doc.native_doctype, doc.native_name
    docstatus = frappe.db.get_value(doctype, name, "docstatus") if frappe.db.exists(doctype, name) else None
    try:
        plan = rules.void_plan(doctype, docstatus)
    except ValueError as error:
        templates.throw_error("NATIVE_NOT_VOIDABLE", str(error))
    frappe.db.savepoint(SAVEPOINT)
    try:
        with as_administrator():
            if plan == "cancel":
                target = frappe.get_doc(doctype, name)
                target.flags.ignore_permissions = True
                target.cancel()
            elif plan == "mark":
                _mark_draft(doctype, name, doc.name, text)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception:  # noqa: BLE001 - ERPNext refuses with link/validation errors; nothing may stay half done
        frappe.db.rollback(save_point=SAVEPOINT)
        frappe.clear_messages()
        templates.throw_error("NATIVE_VOID_FAILED", rules.ERRORS["cancel_failed"])
    frappe.db.set_value(REQUEST_DOCTYPE, doc.name, {"native_status": rules.VOIDED, "native_error": ""},
                        update_modified=False)
    _activity(doc, "Voided", text, doctype, name)
    notify_native_result(doc.name, text, _("سند درخواست {0} ابطال شد.").format(doc.name))


def _mark_draft(doctype: str, name: str, request: str, reason: str) -> None:
    """A draft is left in place (never deleted) with a comment; a checkin is hidden from auto attendance."""
    target = frappe.get_doc(doctype, name)
    target.add_comment("Comment", escape(f"ابطال‌شده از درخواست {request}: {reason}"))
    if doctype == "Employee Checkin" and not target.attendance:
        frappe.db.set_value(doctype, name, "skip_auto_attendance", 1, update_modified=False)


def reissue(doc) -> None:
    """Runs the executor again after a void; a repeat after a reissue changes nothing."""
    if doc.native_status == "Created" and rules.already_reissued(marker_actions(doc.workflow_instance)):
        return
    if doc.native_status != rules.VOIDED:
        _fail("not_reissuable", "NATIVE_NOT_REISSUABLE")
    if doc.template_key:
        _fail("template", "NATIVE_NOT_REISSUABLE")
    from asoud_erp.services.request_native_documents import dispatch

    _activity(doc, "Reissued", "", doc.native_doctype or "", doc.native_name or "")
    frappe.db.set_value(REQUEST_DOCTYPE, doc.name, {
        "native_status": "", "native_doctype": "", "native_name": "", "native_error": ""}, update_modified=False)
    doc.reload()
    dispatch(doc)
