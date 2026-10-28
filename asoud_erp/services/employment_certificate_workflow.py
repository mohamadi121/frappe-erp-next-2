"""Certificate issuance through the existing request workflow and its real events."""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import nowdate

from asoud_erp.services.employment_certificates import DEFAULT_TEMPLATE, render_snapshot

CERT_KIND = "ASOUD Employment Certificate"
REQUEST_KIND = "ASOUD Workflow Request"


def validate_workflow(name, company):
    if not name:
        return
    row = frappe.db.get_value("ASOUD Workflow Definition", name,
        ["company", "target_doctype", "status", "readiness_status", "allow_user_submission", "template_key"],
        as_dict=True) if isinstance(name, str) else None
    if (not row or row.company != company or row.target_doctype != REQUEST_KIND
            or row.status != "Active" or row.readiness_status != "Ready"
            or not row.allow_user_submission or row.template_key):
        frappe.throw(_("گردش‌کار آمادهٔ گواهی اشتغال در این شرکت یافت نشد."))


def _store(entry, data, fingerprint=None):
    values = {"values_json": json.dumps(data, ensure_ascii=False, sort_keys=True)}
    if fingerprint:
        values["fingerprint"] = fingerprint
    frappe.db.set_value("ASOUD Form Entry", entry.name, values)


def _issue(entry, data):
    from asoud_erp.api.v1.employment_certificates import (
        SERIES,
        _build_print_html,
        _format_jalali,
        _letterhead,
    )

    data.update(status="Final", number=make_autoname(SERIES), issue_date=_format_jalali(nowdate()))
    values = data.get("values_snapshot", {})
    values.setdefault("certificate", {}).update(number=data["number"], date=data["issue_date"])
    rendered = render_snapshot(data.get("template_snapshot", DEFAULT_TEMPLATE), values, data.get("salary_rows"))
    data["rendered_html"] = rendered["html"]
    data["values_snapshot"] = rendered["values"]
    data["letterhead_html"] = _letterhead(entry.company)
    data["print_html"] = _build_print_html(data, data["letterhead_html"], True)


def submit(entry_name, revision, request_key):
    from asoud_erp.api.v1.workflow_request import _fields_by_name, create_request

    entry = frappe.get_doc("ASOUD Form Entry", entry_name, for_update=True)
    if entry.reference_doctype != CERT_KIND:
        frappe.throw(_("گواهی مورد نظر یافت نشد."))
    if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 140:
        frappe.throw(_("شناسه یکتای ارسال گواهی معتبر نیست."))
    try:
        data = json.loads(entry.values_json)
    except (TypeError, ValueError):
        frappe.throw(_("اطلاعات گواهی مخدوش است."))
    if not isinstance(data, dict):
        frappe.throw(_("اطلاعات گواهی مخدوش است."))
    if data.get("finalize_request_key") == request_key:
        return data
    try:
        matches = int(revision) > 0 and int(revision) == data.get("revision", 1)
    except (TypeError, ValueError):
        matches = False
    if not matches:
        frappe.throw(_("نسخه گواهی تغییر کرده است؛ صفحه را تازه‌سازی کنید."))
    if data.get("status") != "Draft":
        frappe.throw(_("فقط پیش‌نویس گواهی قابل ارسال است."))
    workflow = data.get("template_snapshot", {}).get("workflow", "")
    validate_workflow(workflow, entry.company)
    # Legacy document-target definitions cannot be run by the request engine.
    if not workflow and frappe.db.exists("ASOUD Workflow Definition", {
            "company": entry.company, "target_doctype": CERT_KIND, "status": "Active"}):
        frappe.throw(_("گردش‌کار گواهی باید از نوع درخواست باشد و به نسخهٔ قالب متصل شود."))
    frappe.db.savepoint("certificate_submit")
    try:
        data.update(status="Pending", finalize_request_key=request_key, revision=data["revision"] + 1)
        if not workflow:
            _issue(entry, data)
            _store(entry, data)
            return data
        fingerprint = hashlib.sha256(f"certificate:{entry.name}:{request_key}".encode()).hexdigest()
        _store(entry, data, fingerprint)
        declared = {field["key"] for field in _fields_by_name(workflow)
                    if field.get("key") and field.get("type") != "Auto"}
        values = {key: data.get(key, "") for key in (
            "employee", "employee_name", "employee_number", "addressee_type", "addressee_name",
            "addressee_title", "purpose", "notes", "location",
        ) if key in declared}
        request = create_request(company=entry.company, workflow_definition=workflow,
            subject=entry.subject, values=values, request_id=fingerprint)["data"]
        data.update(workflow_request=request["name"], workflow_instance=request["workflow_instance"])
        _store(entry, data)
        on_instance_update(frappe.get_doc("ASOUD Workflow Instance", data["workflow_instance"]))
        return json.loads(frappe.db.get_value("ASOUD Form Entry", entry.name, "values_json"))
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception:
        frappe.db.rollback(save_point="certificate_submit")
        raise


def on_instance_update(instance, method=None):
    if instance.reference_doctype != REQUEST_KIND or not instance.reference_name:
        return
    request = frappe.db.get_value(REQUEST_KIND, instance.reference_name, ["company", "request_id"], as_dict=True)
    if not request or not request.request_id:
        return
    name = frappe.db.get_value("ASOUD Form Entry", {
        "reference_doctype": CERT_KIND, "company": request.company, "fingerprint": request.request_id,
    }, "name")
    if not name:
        return
    entry = frappe.get_doc("ASOUD Form Entry", name, for_update=True)
    data = json.loads(entry.values_json or "{}")
    if (data.get("status") != "Pending" or data.get("workflow_instance") != instance.name
            or data.get("workflow_request") != instance.reference_name):
        return
    if data.get("template_snapshot", {}).get("workflow") != instance.workflow_definition:
        frappe.throw(_("گردش‌کار با نسخهٔ گواهی تطابق ندارد."), frappe.PermissionError)
    status = instance.status or frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status")
    if status == "Completed":
        _issue(entry, data)
    elif status in {"Rejected", "Cancelled", "Failed"}:
        data["status"] = status
    else:
        return
    data["revision"] = data.get("revision", 1) + 1
    _store(entry, data)
