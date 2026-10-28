"""Temporarily reserve the existing test office for bootstrap HTTP validation."""

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
        if sys.argv[1] == "setup":
            company = sys.argv[2]
            setup = frappe.get_doc("ASOUD Company Setup", company)
            previous = {"company": company,
                        "first_office_company": frappe.db.get_single_value("ASOUD Settings", "first_office_company"),
                        "first_hr_user": setup.first_hr_user, "office_saved": setup.office_saved}
            token = "lead_" + uuid4().hex[:12]
            year = frappe.get_doc({"doctype": "Fiscal Year", "year": token,
                "year_start_date": "2041-01-01", "year_end_date": "2041-12-31",
                "companies": [{"company": company}]}).insert(ignore_permissions=True)
            frappe.db.set_single_value("ASOUD Settings", "first_office_company", company)
            frappe.db.set_value("ASOUD Company Setup", company, {"first_hr_user": None, "office_saved": 1})
            previous.update({"year": year.name, "username": token})
            frappe.get_doc({"doctype": "User", "email": token + "@example.com", "first_name": "Existing",
                            "username": token, "send_welcome_email": 0}).insert(ignore_permissions=True)
            frappe.db.commit()
            print("@@FIRST_OFFICE@@" + json.dumps(previous))
        else:
            previous = json.loads(sys.argv[2])
            frappe.db.set_single_value("ASOUD Settings", "first_office_company", previous["first_office_company"])
            frappe.db.set_value("ASOUD Company Setup", previous["company"], {
                "first_hr_user": previous["first_hr_user"], "office_saved": previous["office_saved"]})
            frappe.delete_doc("Fiscal Year", previous["year"], ignore_permissions=True, force=True)
            frappe.delete_doc("User", previous["username"] + "@example.com", ignore_permissions=True, force=True)
            frappe.db.commit()
    finally:
        frappe.destroy()
