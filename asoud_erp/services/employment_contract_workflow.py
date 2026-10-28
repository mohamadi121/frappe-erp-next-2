"""Employment contract workflow and issuance engine."""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import getdate, now_datetime, nowdate

from asoud_erp.services.request_templates.base import number_pattern

CONTRACT_KIND = "Contract"
REQUEST_KIND = "ASOUD Workflow Request"


def validate_workflow(name, company):
    if not name:
        return
    if not isinstance(name, str) or not frappe.db.exists(
        "ASOUD Workflow Definition",
        {
            "name": name,
            "company": company,
            "target_doctype": REQUEST_KIND,
            "status": "Active",
            "readiness_status": "Ready",
        },
    ):
        frappe.throw(_("گردش‌کار آمادهٔ قرارداد در این شرکت یافت نشد."))


def _store(entry, data, fingerprint=None):
    values = {"values_json": json.dumps(data, ensure_ascii=False)}
    if fingerprint is not None:
        values["fingerprint"] = fingerprint
    frappe.db.set_value("ASOUD Form Entry", entry.name, values)


def _build_response(contract, data):
    is_final = contract.docstatus == 1 or data.get("status") == "final"
    is_pending = data.get("status") in {"pending", "in_progress"}
    num = "—" if is_pending else (data.get("contract_number") or ("—" if contract.docstatus == 0 else contract.name))
    return {
        "contract_id": contract.name,
        "contract_number": num,
        "status": "نهایی" if is_final else data.get("status_label", "در جریان"),
        "docstatus": contract.docstatus,
        "is_draft": False if is_final else bool(data.get("is_draft", True)),
        "revision": data.get("revision", 1),
        "workflow_instance": data.get("workflow_instance"),
    }


def _finalize(contract, entry, data):
    from asoud_erp.api.v1.employment_contracts import _format_jalali, _letterhead
    from asoud_erp.services.employment_contract import generate_contract_print_data

    today = nowdate()
    official_number = make_autoname(number_pattern("CNT", getdate(today)))
    emp_company = getattr(contract, "company", None) or frappe.db.get_value("Employee", contract.party_name, "company")

    data.update(
        contract_number=official_number,
        is_draft=False,
        status="final",
        status_label="نهایی",
        finalized_on=str(now_datetime()),
        issue_date=_format_jalali(today),
        employee_name=contract.party_full_name,
    )

    letterhead_html = _letterhead(emp_company)
    data["letterhead_snapshot"] = letterhead_html
    data["letterhead_html"] = letterhead_html

    final_print = generate_contract_print_data(
        is_draft=False,
        contract_number=official_number,
        issue_date=_format_jalali(today),
        employee_name=contract.party_full_name,
        rendered_clauses=data.get("rendered_clauses", []),
        salary_table=data.get("salary_table", []),
        total_monthly_formatted=data.get("formatted_total_monthly", ""),
        letterhead_html=letterhead_html,
        company_name=emp_company,
    )

    contract.contract_terms = final_print["html"]
    contract.is_signed = 1
    contract.signee = contract.party_full_name
    contract.signed_on = now_datetime()
    contract.status = "Active"
    contract.flags.ignore_permissions = True
    contract.submit()
    if contract.end_date:
        frappe.db.set_value("Employee", contract.party_name, "contract_end_date", contract.end_date)


def submit(contract_id: str, revision: int | None = None, request_id: str | None = None) -> dict:
    from asoud_erp.api.v1.workflow_request import create_request

    contract = frappe.get_doc("Contract", contract_id, for_update=True)
    emp_company = frappe.db.get_value("Employee", contract.party_name, "company")

    entry_name = frappe.db.get_value(
        "ASOUD Form Entry",
        {"reference_doctype": "Contract", "reference_name": contract.name},
        "name",
    )
    entry = frappe.get_doc("ASOUD Form Entry", entry_name, for_update=True) if entry_name else None
    data = json.loads(entry.values_json or "{}") if entry else {}

    # Request-key replay
    if request_id and data.get("send_request_id") == request_id:
        return _build_response(contract, data)

    # Double finalize check: reject if already final, pending, or rejected
    if contract.docstatus == 1 or data.get("status") in {"final", "pending", "in_progress", "rejected"}:
        frappe.throw(_("این قرارداد قبلاً نهایی شده است."))

    # Revision match
    if revision is not None and int(revision) > 0:
        current_rev = data.get("revision", 1)
        if int(revision) != current_rev:
            frappe.throw(_("این قرارداد توسط کاربر دیگری تغییر کرده است؛ اطلاعات را تازه کنید."))

    # Check for active workflow
    workflow = data.get("template_snapshot", {}).get("workflow") or data.get("workflow")
    validate_workflow(workflow, emp_company)
    # Legacy document-target definitions cannot be run by the request engine.
    if not workflow and frappe.db.exists(
        "ASOUD Workflow Definition",
        {"target_doctype": CONTRACT_KIND, "company": emp_company, "status": "Active"},
    ):
        frappe.throw(_("گردش‌کار قرارداد باید از نوع درخواست باشد و به نسخهٔ قالب متصل شود."))

    frappe.db.savepoint("contract_finalize")
    try:
        new_rev = data.get("revision", 1) + 1
        data["revision"] = new_rev
        if request_id:
            data["send_request_id"] = request_id

        if not workflow:
            # HR documents without configured approval use the existing direct issuance policy
            _finalize(contract, entry, data)
            if entry:
                _store(entry, data)
            return _build_response(contract, data)

        # Workflow defined: set pending and start real workflow request
        data.update(
            status="pending",
            status_label="در جریان",
            is_draft=True,
        )
        contract.status = "In Progress"
        contract.flags.ignore_permissions = True
        contract.save()
        if entry:
            _store(entry, data)

        req_token = request_id or frappe.generate_hash(length=12)
        request_key = hashlib.sha256(f"{entry.name if entry else contract.name}:{req_token}".encode()).hexdigest()
        result = create_request(
            company=emp_company,
            workflow_definition=workflow,
            subject=entry.subject if entry else f"قرارداد کار {contract.party_full_name}",
            values={},
            request_id=request_key,
        )["data"]
        request = frappe.get_doc(REQUEST_KIND, result["name"])
        data.update(workflow_request=request.name, workflow_instance=request.workflow_instance)
        if entry:
            _store(entry, data, fingerprint=request_key)

        # In case the workflow finishes immediately (e.g. 0 approval stages)
        on_instance_update(frappe.get_doc("ASOUD Workflow Instance", request.workflow_instance))
        if entry:
            data = json.loads(frappe.db.get_value("ASOUD Form Entry", entry.name, "values_json") or "{}")
        contract.reload()
        return _build_response(contract, data)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception:
        frappe.db.rollback(save_point="contract_finalize")
        raise


def on_instance_update(instance, method=None):
    if instance.reference_doctype != REQUEST_KIND or not instance.reference_name:
        return
    request = frappe.db.get_value(REQUEST_KIND, instance.reference_name, ["request_id", "company"], as_dict=True)
    if not request or not request.request_id:
        return
    entry_name = frappe.db.get_value(
        "ASOUD Form Entry",
        {"reference_doctype": "Contract", "fingerprint": request.request_id},
        "name",
    )
    if not entry_name:
        return
    status = frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status")
    if status not in {"Completed", "Rejected", "Cancelled", "Failed"}:
        return
    entry = frappe.get_doc("ASOUD Form Entry", entry_name, for_update=True)
    data = json.loads(entry.values_json or "{}")
    if data.get("status") != "pending" or data.get("workflow_instance") != instance.name:
        return
    contract = frappe.get_doc("Contract", entry.reference_name, for_update=True)
    if status == "Completed":
        _finalize(contract, entry, data)
    else:
        key, label = {
            "Rejected": ("rejected", "ردشده"),
            "Cancelled": ("cancelled", "لغوشده"),
            "Failed": ("failed", "ناموفق"),
        }[status]
        data.update(status=key, status_label=label, is_draft=True)
        contract.status = "Rejected" if status == "Rejected" else "Cancelled"
        contract.flags.ignore_permissions = True
        contract.save()
    data["revision"] = data.get("revision", 1) + 1
    _store(entry, data)
