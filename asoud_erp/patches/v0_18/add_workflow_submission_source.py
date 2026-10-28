"""Add routing metadata only; never rewrite existing stages or submissions."""
import frappe


def execute():
    frappe.reload_doc('asoud_erp', 'doctype', 'asoud_workflow_definition')
