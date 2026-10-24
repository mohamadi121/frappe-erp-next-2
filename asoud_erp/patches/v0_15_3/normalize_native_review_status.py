"""Normalize the previously persisted executor review status after model sync."""

import frappe


def execute():
    frappe.db.sql("""UPDATE `tabASOUD Workflow Request`
        SET native_status = 'Needs Review' WHERE native_status = 'needs_review'""")
