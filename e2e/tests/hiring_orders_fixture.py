"""Reserve an unused hiring template and clean only this HTTP test's records."""

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

    from asoud_erp.api.v1 import hiring_orders as api

    os.chdir(os.path.join(bench, "sites"))
    frappe.init(site=os.environ.get("E2E_SITE", "asoud.test"))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        action, company = sys.argv[1:3]
        if action == "setup":
            if api._template_form_name(company):
                raise RuntimeError("Test requires an unused hiring template; existing records are never changed.")
            api.publish_hiring_order_template(company=company)
            employee = api.list_hiring_order_people(company=company)["data"][0]["name"]
            data = api.save_hiring_order(company=company, request_id=uuid4().hex, employee=employee,
                                         effective_date=nowdate())["data"]
            result = {"name": data["name"], "revision": data["revision"], "form": api._template_form_name(company)}
            frappe.db.commit()
            print("@@HIRING_JSON@@" + json.dumps(result))
        elif action == "cleanup":
            name, form = sys.argv[3:5]
            entry = frappe.db.get_value("ASOUD Form Entry", name, ["form", "company"], as_dict=True)
            if not entry or entry.form != form or entry.company != company:
                raise RuntimeError("Refusing cleanup of records outside the test reservation.")
            entries = frappe.get_all("ASOUD Form Entry", filters={"form": form}, pluck="name")
            if entries != [name]:
                raise RuntimeError("Refusing cleanup of a template with another entry.")
            frappe.db.delete("ASOUD Form Entry", {"name": name})
            frappe.db.delete("ASOUD Form Revision", {"form": form})
            frappe.db.delete("Comment", {"reference_doctype": "ASOUD Form", "reference_name": form})
            frappe.db.delete("ASOUD Form", {"name": form, "company": company})
            frappe.db.commit()
        else:
            raise ValueError(action)
    finally:
        frappe.destroy()
