import frappe

from asoud_erp.api.v1.detail_group import DEFAULT_GROUPS


def after_install():
    settings = frappe.get_single("ASOUD Settings")
    settings.accounting_basis = "Accrual"
    settings.display_currency = "Rial"
    settings.auto_generate_account_code = 1
    settings.group_code_digits = 1
    settings.general_code_digits = 2
    settings.ledger_code_digits = 2
    settings.auto_generate_detail_code = 1
    settings.detail_code_digits = 5
    settings.save(ignore_permissions=True)

    for code, title in DEFAULT_GROUPS:
        if not frappe.db.exists("ASOUD Detail Group", code):
            frappe.get_doc(
                {
                    "doctype": "ASOUD Detail Group",
                    "group_code": code,
                    "group_name": title,
                }
            ).insert(ignore_permissions=True)
