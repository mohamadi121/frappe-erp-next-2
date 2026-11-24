"""Index optional office links only; never infer or migrate legacy ownership."""
import frappe


def execute():
    frappe.reload_doc('asoud_erp', 'doctype', 'asoud_access_assignment')
    frappe.reload_doc('asoud_erp', 'doctype', 'asoud_role_definition')
    frappe.db.add_index('ASOUD Access Assignment', ['company', 'employee'], 'office_employee')
    frappe.db.add_index('ASOUD Access Assignment', ['user', 'company'], 'account_office')
    frappe.db.add_index('ASOUD Role Definition', ['company', 'title'], 'office_title')
