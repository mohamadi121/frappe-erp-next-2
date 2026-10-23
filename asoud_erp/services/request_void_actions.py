"""Frappe side of void and reissue (rules in ``request_void``). Called by thin endpoints."""

import json
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


EFFECTS = "Execution Effects"


def _activity(doc, action: str, comment: str, reference_doctype: str, reference_name: str,
              change: dict | None = None) -> None:
    stage = frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "current_stage")
    row = {
        "doctype": "ASOUD Workflow Activity", "workflow_instance": doc.workflow_instance,
        "workflow_stage": stage, "actor": frappe.session.user, "action": action,
        "comment": comment[:1000], "created_on": now_datetime(),
        "reference_doctype": reference_doctype, "reference_name": reference_name,
    }
    if change:
        row["change_json"] = json.dumps(change, ensure_ascii=False)
    frappe.get_doc(row).insert(ignore_permissions=True)


def record_effects(request, before: dict, after: dict) -> None:
    """Remembers what an executor changed outside its document, so a void can undo it."""
    if not request.get("workflow_instance"):
        return
    _activity(request, EFFECTS, "", "", "", {"before": before, "after": after, "labels": {}})


def _latest(instance: str, action: str):
    return frappe.db.get_value("ASOUD Workflow Activity", {"workflow_instance": instance, "action": action},
                               ["comment", "actor", "created_on", "reference_name", "change_json"], as_dict=True,
                               order_by="created_on desc, creation desc")


def _change(row) -> dict:
    try:
        value = json.loads(row.change_json) if row and row.change_json else {}
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def voided_documents(doctype: str) -> set[str]:
    """Names of ``doctype`` documents left behind by a void; executors' duplicate checks ignore them."""
    names = set()
    rows = frappe.get_all("ASOUD Workflow Activity", filters={"action": "Voided", "change_json": ["like", "%voided%"]},
                          pluck="change_json", limit_page_length=0)
    for raw in rows:
        try:
            for kind, name in json.loads(raw).get("voided", []):
                if kind == doctype:
                    names.add(name)
        except (TypeError, ValueError):
            continue
    return names


def marker_actions(instance: str) -> list[str]:
    return frappe.get_all("ASOUD Workflow Activity", filters={
        "workflow_instance": instance, "action": ["in", ["Voided", "Reissued"]]},
        order_by="created_on asc, creation asc", pluck="action", limit_page_length=0)


def last_void(instance: str, privileged: bool) -> dict:
    """``{reason, by_name, on, reference}`` of the latest void; empty for non-privileged callers."""
    if not privileged or not instance:
        return {}
    row = _latest(instance, "Voided")
    if not row:
        return {}
    return {"reason": row.comment or "", "by_name": get_fullname(row.actor), "on": str(row.created_on or ""),
            "reference": row.reference_name or "", "reissue_blocked": _change(row).get("reissue_blocked", "")}


def reissue_blocker(instance: str) -> str:
    """The Persian reason recorded by the last void why a reissue is impossible; empty when possible."""
    row = _latest(instance, "Voided") if instance else None
    return _change(row).get("reissue_blocked", "") if row else ""


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
    voided: list = []
    blocker = ""
    try:
        with as_administrator():
            _void_one(plan, doctype, name, doc.name, text)
            if doctype == "Exit Interview":
                blocker = _void_exit(doc, text, voided)
            elif doctype == "Training Event":
                blocker = _void_training(doc, name, voided)
        blocker = blocker or rules.reissue_blocker(doctype, plan)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception:  # noqa: BLE001 - ERPNext refuses with link/validation errors; nothing may stay half done
        frappe.db.rollback(save_point=SAVEPOINT)
        frappe.clear_messages()
        templates.throw_error("NATIVE_VOID_FAILED", rules.ERRORS["cancel_failed"])
    frappe.db.set_value(REQUEST_DOCTYPE, doc.name, {"native_status": rules.VOIDED, "native_error": ""},
                        update_modified=False)
    _activity(doc, "Voided", text, doctype, name,
              {"before": {}, "after": {}, "labels": {}, "voided": voided, "reissue_blocked": blocker})
    notify_native_result(doc.name, text, _("سند درخواست {0} ابطال شد.").format(doc.name))


def _void_one(plan: str, doctype: str, name: str, request: str, reason: str) -> None:
    if plan == "cancel":
        target = frappe.get_doc(doctype, name)
        target.flags.ignore_permissions = True
        target.cancel()
    elif plan == "mark":
        _mark_draft(doctype, name, request, reason)


def _void_exit(doc, reason: str, voided: list) -> str:
    """The settlement statement is voided like the interview and the relieving date is restored."""
    effects = _latest(doc.workflow_instance, EFFECTS)
    change = _change(effects)
    statement = (change.get("after") or {}).get("statement")
    if statement and frappe.db.exists("Full and Final Statement", statement):
        plan = rules.void_plan("Full and Final Statement", frappe.db.get_value("Full and Final Statement", statement, "docstatus"))
        _void_one(plan, "Full and Final Statement", statement, doc.name, reason)
        voided.append(["Full and Final Statement", statement])
    if not effects or "relieving_date" not in (change.get("before") or {}):
        return rules.ERRORS["no_effects"]
    employee = frappe.db.get_value(REQUEST_DOCTYPE, doc.name, "requester_employee") or frappe.db.get_value(
        "Employee", {"user_id": doc.owner, "company": doc.company}, "name")
    person = frappe.get_doc("Employee", employee)
    if str(person.relieving_date or "") == str((change.get("after") or {}).get("relieving_date") or ""):
        person.relieving_date = change["before"]["relieving_date"] or None
        person.flags.ignore_permissions = True
        person.save()
    return ""


def _void_training(doc, event: str, voided: list) -> str:
    """A participant row of a draft event is removed (a child row, not a document); a submitted event is left."""
    row = frappe.db.get_value("Training Event", event, "docstatus")
    if row != 0:
        return rules.reissue_blocker("Training Event", "mark", row)
    employee = frappe.db.get_value("Employee", {"user_id": doc.owner, "company": doc.company}, "name")
    target = frappe.get_doc("Training Event", event)
    kept = [item for item in target.employees if item.employee != employee]
    if len(kept) != len(target.employees):
        target.set("employees", kept)
        target.flags.ignore_permissions = True
        target.save()
        voided.append(["Training Event Employee", employee])
    return ""


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
    blocked = reissue_blocker(doc.workflow_instance)
    if blocked:
        templates.throw_error("NATIVE_NOT_REISSUABLE", blocked)
    from asoud_erp.services.request_native_documents import dispatch

    _activity(doc, "Reissued", "", doc.native_doctype or "", doc.native_name or "")
    frappe.db.set_value(REQUEST_DOCTYPE, doc.name, {
        "native_status": "", "native_doctype": "", "native_name": "", "native_error": ""}, update_modified=False)
    doc.reload()
    dispatch(doc)
