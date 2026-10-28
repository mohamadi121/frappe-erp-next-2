"""Salary change order issuance driven by the existing request engine and lifecycle."""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import nowdate

from asoud_erp.services.jalali import current_jalali_year

ORDER_KIND = "ASOUD Salary Change Order"
REQUEST_KIND = "ASOUD Workflow Request"


def validate_workflow(name, company):
    if not name:
        return
    if not isinstance(name, str) or not frappe.db.exists("ASOUD Workflow Definition", {
        "name": name, "company": company, "target_doctype": REQUEST_KIND,
        "status": "Active", "readiness_status": "Ready",
    }):
        frappe.throw(_("گردش‌کار آمادهٔ حکم تغییر حقوق در این شرکت یافت نشد."))


def _store(entry, data):
    frappe.db.set_value("ASOUD Form Entry", entry.name, "values_json",
                        json.dumps(data, ensure_ascii=False))


def _finalize(data, entry=None):
    from asoud_erp.api.v1.salary_change_orders import _format_jalali, _letterhead

    number = make_autoname(f"SAL-{current_jalali_year()}-.#####")
    company = data.get("company")
    if not company and entry:
        company = entry.company
    letterhead_snapshot = _letterhead(company) if company else None

    data.update(
        status="final",
        status_label="نهایی",
        issue_date=_format_jalali(nowdate()),
        number=number,
        approved_by=frappe.session.user,
        approved_on=str(frappe.utils.now_datetime()),
        letterhead_snapshot=letterhead_snapshot,
    )


def submit(entry_name, revision, request_id):
    from asoud_erp.api.v1.workflow_request import create_request

    entry = frappe.get_doc("ASOUD Form Entry", entry_name, for_update=True)
    if entry.reference_doctype != ORDER_KIND:
        frappe.throw(_("حکم مورد نظر یافت نشد."), frappe.DoesNotExistError)
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw(_("شناسهٔ یکتای ارسال باید بین هشت تا صد نویسه باشد."))
    data = json.loads(entry.values_json or "{}")
    if data.get("send_request_id") == request_id:
        return data
    if not revision or int(revision) <= 0 or data.get("revision") != int(revision):
        frappe.throw(_("این حکم توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))
    if data.get("status") != "draft":
        frappe.throw(_("وضعیت یا نسخهٔ حکم برای این اقدام معتبر نیست."))
    workflow = data.get("template_snapshot", {}).get("workflow")
    validate_workflow(workflow, entry.company)
    frappe.db.savepoint("salary_change_order_submit")
    try:
        data.update(status="pending", status_label="در جریان", send_request_id=request_id,
                    revision=data["revision"] + 1)
        if not workflow:
            _store(entry, data)
            return data
        _store(entry, data)
        request_key = hashlib.sha256(f"{entry.name}:{request_id}".encode()).hexdigest()
        result = create_request(company=entry.company, workflow_definition=workflow,
                                subject=entry.subject, values={}, request_id=request_key)["data"]
        request = frappe.get_doc(REQUEST_KIND, result["name"])
        data.update(workflow_request=request.name, workflow_instance=request.workflow_instance)
        frappe.db.set_value("ASOUD Form Entry", entry.name, "reference_name", request.name)
        _store(entry, data)
        on_instance_update(frappe.get_doc("ASOUD Workflow Instance", request.workflow_instance))
        return json.loads(frappe.db.get_value("ASOUD Form Entry", entry.name, "values_json"))
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception:
        frappe.db.rollback(save_point="salary_change_order_submit")
        raise


def on_instance_update(instance):
    if instance.reference_doctype != REQUEST_KIND or not instance.reference_name:
        return
    name = frappe.db.get_value("ASOUD Form Entry", {
        "reference_doctype": ORDER_KIND, "reference_name": instance.reference_name,
    }, "name")
    if not name:
        return
    status = frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status")
    if status not in {"Completed", "Rejected", "Cancelled", "Failed"}:
        return
    entry = frappe.get_doc("ASOUD Form Entry", name, for_update=True)
    data = json.loads(entry.values_json or "{}")
    if data.get("status") != "pending" or data.get("workflow_instance") != instance.name:
        return
    request_company = frappe.db.get_value(REQUEST_KIND, instance.reference_name, "company")
    if request_company != entry.company or data.get("template_snapshot", {}).get("workflow") != instance.workflow_definition:
        frappe.throw(_("گردش‌کار با شرکت یا نسخهٔ حکم تطابق ندارد."), frappe.PermissionError)
    if status == "Completed":
        _finalize(data, entry)
    else:
        key, label = {"Rejected": ("rejected", "ردشده"), "Cancelled": ("cancelled", "لغوشده"),
                      "Failed": ("failed", "ناموفق")}[status]
        data.update(status=key, status_label=label)
    data["revision"] += 1
    _store(entry, data)
