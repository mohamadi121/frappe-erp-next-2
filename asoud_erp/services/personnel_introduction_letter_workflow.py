"""Introduction letter issuance driven by the existing request workflow engine."""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import getdate, nowdate

from asoud_erp.services.personnel_introduction_letters import render_snapshot
from asoud_erp.services.request_templates.base import number_pattern

LETTER_KIND = "ASOUD Personnel Introduction Letter"
REQUEST_KIND = "ASOUD Workflow Request"


def validate_workflow(name, company):
    if not name:
        return
    row = frappe.db.get_value("ASOUD Workflow Definition", name,
        ["company", "target_doctype", "status", "readiness_status", "template_key", "allow_user_submission"],
        as_dict=True) if isinstance(name, str) else None
    if (not row or row.company != company or row.target_doctype != REQUEST_KIND
            or row.status != "Active" or row.readiness_status != "Ready"
            or row.template_key or not row.allow_user_submission):
        frappe.throw(_("گردش کار آمادهٔ معرفی‌نامه در این شرکت یافت نشد."))


def workflow_options(company):
    rows = frappe.get_all("ASOUD Workflow Definition", filters={
        "company": company, "target_doctype": REQUEST_KIND, "status": "Active",
        "readiness_status": "Ready", "allow_user_submission": 1,
    }, fields=["name", "workflow_title", "template_key"], order_by="workflow_title asc", limit_page_length=200)
    return [{"name": row.name, "title": row.workflow_title} for row in rows if not row.template_key]


def _store(entry, data, fingerprint=None):
    values = {"values_json": json.dumps(data, ensure_ascii=False)}
    if fingerprint is not None:
        values["fingerprint"] = fingerprint
    frappe.db.set_value("ASOUD Form Entry", entry.name, values)


def _issue(entry, data):
    from asoud_erp.api.v1.personnel_introduction_letters import _build_print_html, _format_jalali, _letterhead

    number = make_autoname(number_pattern("INTRO", getdate(nowdate())))
    head = _letterhead(entry.company)
    data.update(
        status="Final",
        number=number,
        issue_date=_format_jalali(nowdate()),
        letterhead_snapshot=head,
    )
    values = data.get("values_snapshot", {})
    values.setdefault("letter", {}).update(number=number, issue_date=data["issue_date"])
    rendered = render_snapshot(data["template_snapshot"], values)
    data.update(rendered_html=rendered["html"], values_snapshot=rendered["values"])
    data["print_html"] = _build_print_html(data, head, True)


def submit(entry_name, revision, request_key):
    from asoud_erp.api.v1.workflow_request import _fields_by_name, create_request

    if not isinstance(request_key, str) or not request_key.strip():
        frappe.throw(_("شناسهٔ یکتای ارسال معرفی‌نامه معتبر نیست."))
    entry = frappe.get_doc("ASOUD Form Entry", entry_name, for_update=True)
    if entry.reference_doctype != LETTER_KIND:
        frappe.throw(_("معرفی‌نامه یافت نشد."), frappe.DoesNotExistError)
    try:
        data = json.loads(entry.values_json or "{}")
    except (TypeError, ValueError):
        frappe.throw(_("اطلاعات معرفی‌نامه مخدوش است."))
    if not isinstance(data, dict):
        frappe.throw(_("اطلاعات معرفی‌نامه مخدوش است."))
    if data.get("send_request_key") == request_key:
        return data
    if data.get("status") != "Draft":
        frappe.throw(_("این معرفی‌نامه قبلاً نهایی شده است."))
    if not revision or int(revision) <= 0 or data.get("revision", 1) != int(revision):
        frappe.throw(_("نسخه معرفی‌نامه تغییر کرده است؛ صفحه را تازه‌سازی کنید."))
    workflow = data.get("template_snapshot", {}).get("workflow", "")
    validate_workflow(workflow, entry.company)
    frappe.db.savepoint("introduction_letter_submit")
    try:
        data.update(status="Pending", send_request_key=request_key, revision=data.get("revision", 1) + 1)
        if not workflow:
            _issue(entry, data)
            _store(entry, data)
            return data
        # A submission fingerprint also links the workflow request to this entry.
        # Keep reference_name stable so existing public letter URLs keep working.
        fingerprint = hashlib.sha256(f"introduction:{entry.name}:{request_key}".encode()).hexdigest()
        _store(entry, data, fingerprint)
        declared = {field["key"] for field in _fields_by_name(workflow)
                    if field.get("key") and field.get("type") != "Auto"}
        request_values = {key: data.get(key, "") for key in (
            "employee", "employee_name", "employee_number", "recipient_text", "purpose", "notes", "validity_date",
        ) if key in declared}
        request = create_request(company=entry.company, workflow_definition=workflow,
            subject=entry.subject, values=request_values, request_id=fingerprint)["data"]
        data.update(workflow_request=request["name"], workflow_instance=request["workflow_instance"])
        _store(entry, data)
        # An immediate End stage can fire before create_request returns the link.
        instance = frappe.get_doc("ASOUD Workflow Instance", data["workflow_instance"])
        on_instance_update(instance)
        return json.loads(frappe.db.get_value("ASOUD Form Entry", entry.name, "values_json"))
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception:
        frappe.db.rollback(save_point="introduction_letter_submit")
        raise


def on_instance_update(instance, method=None):
    if instance.reference_doctype != REQUEST_KIND or not instance.reference_name:
        return
    request = frappe.db.get_value(REQUEST_KIND, instance.reference_name,
        ["request_id", "company"], as_dict=True)
    if not request or not request.request_id:
        return
    name = frappe.db.get_value("ASOUD Form Entry", {
        "reference_doctype": LETTER_KIND, "company": request.company, "fingerprint": request.request_id,
    }, "name")
    if not name:
        return
    entry = frappe.get_doc("ASOUD Form Entry", name, for_update=True)
    data = json.loads(entry.values_json or "{}")
    if (data.get("status") != "Pending" or data.get("workflow_instance") != instance.name
            or data.get("workflow_request") != instance.reference_name):
        return
    if data.get("template_snapshot", {}).get("workflow") != instance.workflow_definition:
        frappe.throw(_("گردش کار با نسخهٔ معرفی‌نامه تطابق ندارد."), frappe.PermissionError)
    status = frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status")
    if status == "Completed":
        _issue(entry, data)
    elif status in {"Rejected", "Cancelled", "Failed"}:
        data["status"] = status
    else:
        return
    data["revision"] = data.get("revision", 1) + 1
    _store(entry, data)
