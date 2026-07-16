import frappe
from frappe import _

from asoud_erp.api.v1.responses import success


@frappe.whitelist()
def get_settings() -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    settings = frappe.get_single("ASOUD Settings")
    return success(
        {
            "accounting_basis": "Accrual",
            "display_currency": settings.display_currency,
            "auto_generate_account_code": bool(settings.auto_generate_account_code),
            "group_code_digits": settings.group_code_digits,
            "general_code_digits": settings.general_code_digits,
            "ledger_code_digits": settings.ledger_code_digits,
            "auto_generate_detail_code": bool(settings.auto_generate_detail_code),
            "detail_code_digits": settings.detail_code_digits,
        }
    )


@frappe.whitelist(methods=["POST"])
def update_settings(
    display_currency: str,
    auto_generate_account_code: int | bool = 1,
    group_code_digits: int = 1,
    general_code_digits: int = 2,
    ledger_code_digits: int = 2,
    auto_generate_detail_code: int | bool = 1,
    detail_code_digits: int = 5,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if display_currency not in {"Rial", "Toman"}:
        frappe.throw(_("Display currency must be Rial or Toman"))
    digits = int(detail_code_digits)
    if not 3 <= digits <= 12:
        frappe.throw(_("Detail code digits must be between 3 and 12"))
    level_digits = [int(group_code_digits), int(general_code_digits), int(ledger_code_digits)]
    if any(value < 1 or value > 4 for value in level_digits):
        frappe.throw(_("Account level code digits must be between 1 and 4"))

    settings = frappe.get_single("ASOUD Settings")
    settings.accounting_basis = "Accrual"
    settings.display_currency = display_currency
    settings.auto_generate_account_code = int(bool(auto_generate_account_code))
    settings.group_code_digits = level_digits[0]
    settings.general_code_digits = level_digits[1]
    settings.ledger_code_digits = level_digits[2]
    settings.auto_generate_detail_code = int(bool(auto_generate_detail_code))
    settings.detail_code_digits = digits
    settings.save()
    return get_settings()
