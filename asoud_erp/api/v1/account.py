import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.account_code_service import next_account_code


@frappe.whitelist()
def list_accounts(company: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    settings = frappe.get_single("ASOUD Settings")
    group_digits = int(settings.group_code_digits or 1)
    general_digits = group_digits + int(settings.general_code_digits or 2)
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "account_number": ["is", "set"]},
        fields=[
            "name",
            "account_number",
            "account_name",
            "parent_account",
            "root_type",
            "is_group",
            "disabled",
        ],
        order_by="account_number asc",
        limit_page_length=0,
    )
    for row in rows:
        code_length = len(str(row.account_number or ""))
        row["asoud_level"] = (
            "Group" if code_length <= group_digits else "General" if code_length <= general_digits else "Ledger"
        )
    return success(rows)


@frappe.whitelist()
def preview_next_code(company: str, level: str, parent_account: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    return success({"account_number": next_account_code(company, level, parent_account)})


@frappe.whitelist(methods=["POST"])
def create_account(
    company: str,
    account_name: str,
    level: str,
    parent_account: str | None = None,
    account_number: str | None = None,
    auto_code: int | bool = 1,
    root_type: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not account_name or len(account_name.strip()) < 3:
        frappe.throw(_("Account name must contain at least 3 characters"))
    code = next_account_code(company, level, parent_account) if auto_code or not account_number else account_number
    is_group = 1 if level in {"Group", "General"} else 0
    doc = frappe.get_doc(
        {
            "doctype": "Account",
            "company": company,
            "account_name": account_name.strip(),
            "account_number": code,
            "parent_account": parent_account,
            "is_group": is_group,
            "root_type": root_type,
        }
    )
    doc.insert()
    result = doc.as_dict()
    result["asoud_level"] = level
    return success(result)


@frappe.whitelist(methods=["POST"])
def update_account(
    company: str,
    account: str,
    account_name: str,
    parent_account: str | None = None,
    disabled: int | bool = 0,
    root_type: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.db.exists("Account", {"name": account, "company": company}):
        frappe.throw(_("Account does not belong to the selected company"))
    title = str(account_name or "").strip()
    if len(title) < 3:
        frappe.throw(_("Account name must contain at least 3 characters"))
    if parent_account and not frappe.db.exists(
        "Account", {"name": parent_account, "company": company, "is_group": 1}
    ):
        frappe.throw(_("Parent account is not a group in the selected company"))
    doc = frappe.get_doc("Account", account)
    doc.account_name = title
    doc.parent_account = parent_account
    doc.disabled = int(bool(disabled))
    if root_type:
        doc.root_type = root_type
    doc.save()
    result = doc.as_dict()
    result["asoud_level"] = "Group" if doc.is_group else "Ledger"
    return success(result)
