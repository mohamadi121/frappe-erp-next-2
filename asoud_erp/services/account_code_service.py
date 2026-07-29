import re

import frappe
from frappe import _

LEVEL_FIELD = {
    "Group": "group_code_digits",
    "General": "general_code_digits",
    "Ledger": "ledger_code_digits",
}


def next_account_code(company: str, level: str, parent_account: str | None = None) -> str:
    if level not in LEVEL_FIELD:
        frappe.throw(_("Level must be Group, General or Ledger"))
    if level != "Group" and not parent_account:
        frappe.throw(_("Parent account is required"))

    setup = frappe.get_doc("ASOUD Company Setup", company)
    digits = int(setup.get(LEVEL_FIELD[level]) or 1)
    prefix = ""
    if parent_account:
        prefix = str(frappe.db.get_value("Account", parent_account, "account_number") or "").strip()
        if not prefix:
            frappe.throw(_("Parent account must have an account number"))

    numbers = frappe.get_all(
        "Account",
        filters={"company": company, "parent_account": parent_account or ["is", "not set"]},
        pluck="account_number",
        limit_page_length=0,
    )
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{{digits}}})$")
    used = {int(match.group(1)) for value in numbers if value and (match := pattern.match(str(value)))}
    maximum = (10**digits) - 1
    sequence = next((number for number in range(1, maximum + 1) if number not in used), None)
    if sequence is None:
        frappe.throw(_("No free account code remains for this pattern"))
    return f"{prefix}{sequence:0{digits}d}"

