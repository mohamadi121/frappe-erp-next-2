"""Reserve isolated accounts and definitions for HR grant HTTP permission tests."""

import json
import os
import sys

if __name__ == "__main__":
    bench = os.environ.get("E2E_BENCH_PATH", os.path.expanduser("~/frappe-dev/bench"))
    for app in ("frappe", "erpnext", "hrms"):
        sys.path.insert(0, os.path.join(bench, "apps", app))
    import frappe
    from frappe.utils.password import update_password

    from asoud_erp.api.v1 import role_management
    from asoud_erp.services.delegation import DELEGATE_ROLE

    os.chdir(os.path.join(bench, "sites"))
    frappe.init(site=os.environ.get("E2E_SITE", "asoud.test"))
    frappe.connect()
    frappe.set_user("Administrator")
    action, company, token = sys.argv[1:4]
    if not token.isalnum() or not token.startswith("HG") or len(token) != 14:
        raise ValueError("Invalid test reservation")
    actor = f"grant-actor-{token.lower()}@example.com"
    target = f"grant-target-{token.lower()}@example.com"
    codes = [token + "G", token + "O"]
    try:
        if action == "setup":
            role_management.create_category({"code": token, "title": "آزمون واگذاری منابع انسانی"})
            for code, scope in zip(codes, ("global", "office")):
                role_management.save_role({"code": code, "title": "منابع انسانی",
                    "category": token, "scope": scope, "base_roles": ["HR Manager"]})
            for email, roles in ((actor, ["HR Manager", DELEGATE_ROLE]), (target, ["Sales User"])):
                frappe.get_doc({"doctype": "User", "email": email, "first_name": "آزمون",
                    "send_welcome_email": 0, "user_type": "System User",
                    "roles": [{"role": role} for role in roles]}).insert(ignore_permissions=True)
            update_password(actor, "Http-HR-Grant-42")
            frappe.get_doc({"doctype": "User Permission", "user": actor, "allow": "Company",
                "for_value": company, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
            frappe.db.commit()
            print("@@HR_GRANT@@" + json.dumps({"actor": actor, "target": target,
                                               "global": codes[0], "office": codes[1]}))
        elif action == "cleanup":
            assignments = frappe.get_all("ASOUD Access Assignment", filters={"managed_role": ["in", codes]},
                                          pluck="native_role")
            frappe.db.delete("ASOUD Access Assignment", {"managed_role": ["in", codes]})
            frappe.db.delete("ASOUD Office Role Assignment", {"role_definition": ["in", codes]})
            for user in (actor, target):
                frappe.db.delete("User Permission", {"user": user})
                if frappe.db.exists("User", user):
                    frappe.delete_doc("User", user, ignore_permissions=True)
            for code in codes:
                profile = frappe.db.get_value("ASOUD Role Definition", code, "role_profile")
                if profile:
                    frappe.delete_doc("ASOUD Role Definition", code, ignore_permissions=True)
                    if frappe.db.exists("Role Profile", profile):
                        frappe.delete_doc("Role Profile", profile, ignore_permissions=True)
            for native in assignments:
                if frappe.db.exists("Role", native):
                    frappe.delete_doc("Role", native, ignore_permissions=True)
            if frappe.db.exists("ASOUD Role Category", token):
                frappe.delete_doc("ASOUD Role Category", token, ignore_permissions=True)
            frappe.db.commit()
        else:
            raise ValueError("Unknown fixture action")
    finally:
        frappe.destroy()
