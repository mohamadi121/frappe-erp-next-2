"""Add bootstrap metadata without guessing historical HR identities/completion."""

import frappe


def execute():
    frappe.reload_doc("asoud_erp", "doctype", "asoud_company_setup")
