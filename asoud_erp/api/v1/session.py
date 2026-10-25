"""Session endpoints: post-login state, explicit logout, office selection."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import login_state as state_service
from asoud_erp.services import security_audit


def _require_session() -> str:
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("ورود به حساب لازم است.", frappe.AuthenticationError)
    return user


@frappe.whitelist()
def login_state() -> dict:
    """Everything the app needs right after sign-in: account state, effective roles,
    accessible offices, bootstrap state and the resolved next route."""
    user = _require_session()
    return success(state_service.build(user))


@frappe.whitelist(methods=["POST"])
def logout() -> dict:
    """Revoke the current server session (not just forget it on the device)."""
    user = _require_session()
    sid = frappe.session.sid
    frappe.local.login_manager.logout()
    frappe.db.commit()
    revoked = not frappe.db.exists("Sessions", sid)
    security_audit.record("auth.logout_api", actor=user, result="success" if revoked else "failure",
                          target_type="User", target=user, commit=True)
    return success({"revoked": revoked})


@frappe.whitelist(methods=["POST"])
def select_office(company: str) -> dict:
    """Remember the active office for this account; only an accessible office is accepted."""
    user = _require_session()
    state = state_service.build(user)
    if state["account"]["must_change_password"]:
        frappe.throw("ابتدا رمز موقت را تغییر دهید.", frappe.PermissionError)
    allowed = {office["id"] for office in state["offices"]}
    if company not in allowed:
        security_audit.record("office.select", result="denied", target_type="Company", target=str(company),
                              commit=True)
        frappe.throw("به این دفتر دسترسی ندارید.", frappe.PermissionError)
    frappe.defaults.set_user_default("company", company, user=user)
    return success(state_service.build(user))
