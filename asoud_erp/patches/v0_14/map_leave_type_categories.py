"""Give every Leave Type without an ASOUD category one, from its name and LWP flag."""

import frappe

from asoud_erp.services.request_lookup import leave_category_for


def execute() -> None:
    """Safe to run repeatedly: only empty categories are filled."""
    if not frappe.get_meta("Leave Type").has_field("asoud_leave_category"):
        # Fixtures sync after post-model-sync patches on the first migrate that ships the field.
        from frappe.utils.fixtures import sync_fixtures

        sync_fixtures(app="asoud_erp")
        frappe.clear_cache(doctype="Leave Type")
    for row in frappe.get_all("Leave Type", fields=["name", "is_lwp"],
                              filters={"asoud_leave_category": ["is", "not set"]}, limit_page_length=0):
        frappe.db.set_value("Leave Type", row.name, "asoud_leave_category",
                            leave_category_for(row.name, bool(row.is_lwp)), update_modified=False)
