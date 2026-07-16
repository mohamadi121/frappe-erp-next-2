import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.account_code_service import next_account_code


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
    return success(doc.as_dict())

