"""Add technical wait persistence; do not reinterpret or rewrite legacy executions."""
import frappe


def execute():
    frappe.reload_doc('asoud_erp', 'doctype', 'asoud_workflow_instance')
    frappe.db.add_index('ASOUD Workflow Instance', ['status', 'wait_due_utc'], 'wait_dispatch')
