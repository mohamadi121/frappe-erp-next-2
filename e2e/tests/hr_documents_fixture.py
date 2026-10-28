"""Fixture helper for HR document Playwright specs."""

import json
import os
import sys
from uuid import uuid4

if __name__ == "__main__":
    bench = os.environ.get("E2E_BENCH_PATH", os.path.expanduser("~/frappe-dev/bench"))
    for app in ("frappe", "erpnext", "hrms"):
        sys.path.insert(0, os.path.join(bench, "apps", app))
    import frappe
    from frappe.utils import nowdate

    os.chdir(os.path.join(bench, "sites"))
    frappe.init(site=os.environ.get("E2E_SITE", "asoud.test"))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        action = sys.argv[1]
        doc_kind = sys.argv[2]
        if action == "setup":
            company = sys.argv[3]
            token = uuid4().hex[:8]

            # Find active employee
            emp = frappe.db.get_value(
                "Employee",
                {"company": company, "status": "Active"},
                ["name", "employee_name"],
                as_dict=True,
            )
            if not emp:
                raise RuntimeError(f"No active employee found for {company}")

            if doc_kind == "contracts":
                from asoud_erp.api.v1 import employment_contracts as api

                tmpl_pub = api.publish_contract_template(company=company)
                saved = api.save_contract_draft(
                    company=company,
                    employee=emp.name,
                    start_date=nowdate(),
                    client_id=f"e2e-cnt-{token}",
                )["data"]
                res = {
                    "id": saved["contract_id"],
                    "employee": emp.name,
                    "employee_name": emp.employee_name,
                    "template_id": tmpl_pub["data"]["template_id"],
                    "revision": saved.get("revision", 1),
                }

            elif doc_kind == "certificates":
                from asoud_erp.api.v1 import employment_certificates as api

                tmpl_pub = api.publish_template(company=company)
                saved = api.save_draft(
                    company=company,
                    employee=emp.name,
                    addressee_name="بانک ملت",
                    purpose="دریافت تسهیلات",
                    request_key=f"e2e-cert-{token}",
                )["data"]
                res = {
                    "id": saved["name"],
                    "employee": emp.name,
                    "employee_name": emp.employee_name,
                    "template_id": tmpl_pub["data"].get("template_id", ""),
                    "revision": saved.get("revision", 1),
                }

            elif doc_kind == "hiring_orders":
                from asoud_erp.api.v1 import hiring_orders as api

                tmpl_pub = api.publish_hiring_order_template(company=company)
                saved = api.save_hiring_order(
                    company=company,
                    request_id=f"e2e-hire-{token}",
                    employee=emp.name,
                    effective_date=nowdate(),
                )["data"]
                res = {
                    "id": saved["name"],
                    "employee": emp.name,
                    "employee_name": emp.employee_name,
                    "template_id": api._template_name(company),
                    "revision": saved.get("revision", 1),
                }

            elif doc_kind == "introduction_letters":
                from asoud_erp.api.v1 import personnel_introduction_letters as api

                tmpl_pub = api.publish_template(company=company)
                saved = api.save_draft(
                    company=company,
                    employee=emp.name,
                    recipient_type="bank",
                    bank_name="بانک تجارت",
                    purpose="گواهی کسر از حقوق",
                    request_key=f"e2e-intro-{token}",
                )["data"]
                res = {
                    "id": saved["name"],
                    "employee": emp.name,
                    "employee_name": emp.employee_name,
                    "template_id": api._template_name(company),
                    "revision": saved.get("revision", 1),
                }

            elif doc_kind == "salary_change_orders":
                from asoud_erp.api.v1 import salary_change_orders as api

                api.publish_salary_change_order_template(company=company)
                saved = api.save_salary_change_order(
                    company=company,
                    request_id=f"e2e-sal-{token}",
                    employee=emp.name,
                    effective_date=nowdate(),
                    reason="annual",
                    description="افزایش سنواتی سالانه",
                )["data"]
                res = {
                    "id": saved["name"],
                    "employee": emp.name,
                    "employee_name": emp.employee_name,
                    "template_id": api._template_form_name(company),
                    "revision": saved.get("revision", 1),
                }
            else:
                raise ValueError(f"Unknown document kind {doc_kind}")

            frappe.db.commit()
            print("@@HR_DOC_JSON@@" + json.dumps(res, ensure_ascii=False))

        elif action == "cleanup":
            doc_id = sys.argv[3]
            if doc_kind == "contracts":
                entry_name = frappe.db.get_value(
                    "ASOUD Form Entry",
                    {"reference_doctype": "Contract", "reference_name": doc_id},
                    "name",
                )
                if entry_name:
                    frappe.db.delete("ASOUD Form Entry", {"name": entry_name})
                if frappe.db.exists("Contract", doc_id):
                    contract = frappe.get_doc("Contract", doc_id)
                    if contract.docstatus == 1:
                        contract.cancel()
                    contract.delete()
            else:
                kind_map = {
                    "certificates": "ASOUD Employment Certificate",
                    "hiring_orders": "ASOUD Hiring Order",
                    "introduction_letters": "ASOUD Personnel Introduction Letter",
                    "salary_change_orders": "ASOUD Salary Change Order",
                }
                k = kind_map[doc_kind]
                entry_name = frappe.db.get_value(
                    "ASOUD Form Entry",
                    {"reference_doctype": k, "reference_name": doc_id},
                    "name",
                ) or doc_id
                if frappe.db.exists("ASOUD Form Entry", entry_name):
                    frappe.db.delete("ASOUD Form Entry", {"name": entry_name})

            frappe.db.commit()
            print("@@HR_DOC_JSON@@{\"cleaned\": true}")
        else:
            raise ValueError(f"Unknown action {action}")
    finally:
        frappe.destroy()
