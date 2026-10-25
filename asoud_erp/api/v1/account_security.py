"""Password endpoints: change (first-run form and Settings > Security share it), recovery, activation."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import account_recovery, password_service


@frappe.whitelist(methods=["POST"])
def change_password(current_password: str, new_password: str, repeat_password: str) -> dict:
    """The only password-change service. Verifies the current password, applies the policy,
    rate-limits failures, revokes every other session."""
    return success(password_service.change_password(current_password, new_password, repeat_password))


@frappe.whitelist(allow_guest=True)
def recovery_status() -> dict:
    """Whether «رمز عبور خود را فراموش کرده‌اید؟» can really work (outgoing e-mail configured)."""
    return success({"available": account_recovery.recovery_available(),
                    "code_valid_minutes": account_recovery.TTL_MINUTES["password_reset"]})


@frappe.whitelist(allow_guest=True, methods=["POST"])
def request_password_reset(identifier: str) -> dict:
    """Send a one-time code to the account's e-mail. The answer never reveals whether the account exists."""
    return success(account_recovery.request_reset(identifier))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def confirm_password_reset(identifier: str, code: str, new_password: str, repeat_password: str) -> dict:
    """Set a new password with the one-time code; all sessions of the account are revoked."""
    return success(account_recovery.confirm(identifier, code, new_password, repeat_password))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def activate_account(identifier: str, code: str, new_password: str, repeat_password: str) -> dict:
    """Invitation activation: the invited person chooses a personal password with the expiring code."""
    return success(account_recovery.confirm(identifier, code, new_password, repeat_password,
                                            purpose="activation"))
