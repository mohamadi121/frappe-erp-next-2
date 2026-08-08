import frappe

from asoud_erp.api.v1.detail_group import DEFAULT_GROUPS


def execute() -> None:
    for code, title, party_role in DEFAULT_GROUPS:
        if frappe.db.exists("ASOUD Detail Group", code):
            frappe.db.set_value("ASOUD Detail Group", code, "group_name", title, update_modified=False)
            continue
        frappe.get_doc(
            {
                "doctype": "ASOUD Detail Group",
                "group_code": code,
                "group_name": title,
                "party_role": party_role,
            }
        ).insert(ignore_permissions=True)
