"""Login/onboarding hardening, safe to retry and reversible by hand.

* creates the native roles behind «ایجاد دفتر» / «واگذاری نقش»;
* gives every existing role definition the compatible default scope ``global`` (they were site-wide);
* marks definitions whose profile contains System Manager as system roles;
* backfills ``ASOUD Work Report.reporter`` from the report's Employee login;
* records the first office of an existing deployment in ASOUD Settings.

Reverse (manual): the new fields can be dropped by removing them from the DocType JSON and migrating;
no existing value is overwritten or deleted here.
"""

import frappe


def execute():
    from asoud_erp.install import ensure_security_roles

    ensure_security_roles()
    frappe.reload_doc("asoud_erp", "doctype", "asoud_role_definition")
    frappe.reload_doc("asoud_erp", "doctype", "asoud_work_report")
    frappe.reload_doc("asoud_erp", "doctype", "asoud_settings")
    frappe.reload_doc("asoud_erp", "doctype", "asoud_company_setup")
    frappe.reload_doc("asoud_erp", "doctype", "asoud_party_profile")

    for name in frappe.get_all("ASOUD Role Definition", filters={"scope": ["is", "not set"]}, pluck="name"):
        frappe.db.set_value("ASOUD Role Definition", name, "scope", "global", update_modified=False)
    for row in frappe.get_all("ASOUD Role Definition", fields=["name", "role_profile"]):
        if frappe.db.exists("Has Role", {"parenttype": "Role Profile", "parent": row.role_profile,
                                         "role": "System Manager"}):
            frappe.db.set_value("ASOUD Role Definition", row.name, "is_system", 1, update_modified=False)

    for row in frappe.get_all("ASOUD Work Report", filters={"reporter": ["is", "not set"]},
                              fields=["name", "employee"], limit_page_length=0):
        user = frappe.db.get_value("Employee", row.employee, "user_id") if row.employee else None
        if user:
            frappe.db.set_value("ASOUD Work Report", row.name, "reporter", user, update_modified=False)

    settings = frappe.get_single("ASOUD Settings")
    if not settings.first_office_company:
        company = frappe.db.get_value("ASOUD Company Setup", {"office_saved": 1}, "company", order_by="creation asc")
        if company:
            frappe.db.set_value("ASOUD Settings", None, "first_office_company", company)
