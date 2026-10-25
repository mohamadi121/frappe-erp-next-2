import frappe

from asoud_erp.api.v1.detail_group import DEFAULT_GROUPS


def after_install():
    ensure_security_roles()
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

    for code, title, party_role in DEFAULT_GROUPS:
        existing = frappe.db.exists("ASOUD Detail Group", code)
        if not existing:
            frappe.get_doc(
                {
                    "doctype": "ASOUD Detail Group",
                    "group_code": code,
                    "group_name": title,
                    "party_role": party_role,
                }
            ).insert(ignore_permissions=True)
        elif party_role and not frappe.db.get_value(
            "ASOUD Detail Group", existing, "party_role"
        ):
            frappe.db.set_value("ASOUD Detail Group", existing, "party_role", party_role)


SECURITY_ROLES = ("ASOUD Office Creator", "ASOUD Role Assigner")


def ensure_security_roles():
    """Native roles behind the independent «ایجاد دفتر» and «واگذاری نقش» permissions. They grant
    no DocType right by themselves; only the ASOUD gates read them. Idempotent."""
    for name in SECURITY_ROLES:
        if not frappe.db.exists("Role", name):
            frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 0}).insert(ignore_permissions=True)


def after_migrate():
    """Keep installation and migration hooks explicitly idempotent."""
    from asoud_erp.services.request_templates.seed import ensure_system_templates

    ensure_security_roles()
    ensure_system_templates()
    for code, title, party_role in DEFAULT_GROUPS:
        existing = frappe.db.exists("ASOUD Detail Group", code)
        if not existing:
            frappe.get_doc(
                {
                    "doctype": "ASOUD Detail Group",
                    "group_code": code,
                    "group_name": title,
                    "party_role": party_role,
                }
            ).insert(ignore_permissions=True)
        elif party_role and not frappe.db.get_value(
            "ASOUD Detail Group", existing, "party_role"
        ):
            frappe.db.set_value("ASOUD Detail Group", existing, "party_role", party_role)
