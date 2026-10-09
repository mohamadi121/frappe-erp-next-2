"""A restricted workflow service identity for tests that run system actions."""

from unittest.mock import patch

import frappe

SERVICE_USER = "asoud.service@example.com"
SERVICE_ROLES = ["Accounts User", "Accounts Manager", "Purchase User", "Stock User", "Stock Manager"]


def ensure_service_user() -> str:
    """Create (once) an enabled System User that is not a System Manager."""
    if not frappe.db.exists("User", SERVICE_USER):
        frappe.get_doc({"doctype": "User", "email": SERVICE_USER, "first_name": "asoud.service",
                        "send_welcome_email": 0, "user_type": "System User",
                        "roles": [{"role": role} for role in SERVICE_ROLES]}).insert(ignore_permissions=True)
    return SERVICE_USER


def patch_service_conf(testcase, company: str) -> str:
    """Point site config at the service user for one test; restored on cleanup."""
    user = ensure_service_user()
    patcher = patch.dict(frappe.conf, {"asoud_workflow_service_user": user,
                                       "asoud_workflow_service_companies": [company]})
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return user
