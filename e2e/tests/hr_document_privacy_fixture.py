"""Reserve snapshot rows for the payroll response permission matrix."""

import json
import os
import sys
from uuid import uuid4

if __name__ == "__main__":
    bench = os.environ.get("E2E_BENCH_PATH", os.path.expanduser("~/frappe-dev/bench"))
    for app in ("frappe", "erpnext", "hrms"):
        sys.path.insert(0, os.path.join(bench, "apps", app))
    import frappe

    os.chdir(os.path.join(bench, "sites"))
    frappe.init(site=os.environ.get("E2E_SITE", "asoud.test"))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        action = sys.argv[1]
        if action == "setup":
            rows = []
            for company in sys.argv[2:4]:
                for kind, data in (
                    ("ASOUD Hiring Order", {"payroll_snapshot": {"rows": [{"amount": 987654321}]}}),
                    ("ASOUD Salary Change Order", {"comparison_table": {"rows": [{"new_amount": 987654321}]}}),
                    ("ASOUD Employment Certificate", {"include_salary": True, "has_salary": True,
                        "salary_rows": [{"amount": 987654321}], "values_snapshot": {"payroll": {"base": 987654321}},
                        "rendered_html": "987654321"}),
                ):
                    entry = frappe.get_doc({"doctype": "ASOUD Form Entry", "company": company,
                        "subject": "آزمون حریم حقوق", "reference_doctype": kind,
                        "request_key": uuid4().hex, "values_json": json.dumps(data)})
                    entry.flags.form_service = True
                    entry.insert(ignore_permissions=True)
                    rows.append({"name": entry.name, "company": company, "kind": kind})
            frappe.db.commit()
            print("@@PRIVACY_JSON@@" + json.dumps(rows))
        elif action == "cleanup":
            for name in sys.argv[2:]:
                if frappe.db.get_value("ASOUD Form Entry", name, "subject") == "آزمون حریم حقوق":
                    frappe.db.delete("ASOUD Form Entry", {"name": name})
            frappe.db.commit()
        else:
            raise ValueError(action)
    finally:
        frappe.destroy()
