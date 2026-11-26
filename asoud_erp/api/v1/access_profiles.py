"""Office-scoped adapters for the existing native permission/profile structures."""
import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import office_permission_profiles as service


@frappe.whitelist()
def list_profiles(company):
    return success(service.list_profiles(company))


@frappe.whitelist(methods=['POST'])
def save_catalog_layout(company, modules, version):
    from asoud_erp.services import access_catalog_layout

    return success(access_catalog_layout.save(company, frappe.parse_json(modules), version))


@frappe.whitelist()
def get_profile(company, name):
    return success(service.get_profile(company, name))


@frappe.whitelist(methods=['POST'])
def save_profile(company, title, grants, description='', name=None, modified=None):
    return success(service.save_profile(company, title, description, frappe.parse_json(grants), name, modified))


@frappe.whitelist(methods=['POST'])
def delete_profile(company, name, modified):
    return success(service.delete_profile(company, name, modified))


@frappe.whitelist()
def list_accounts(company):
    return success(service.list_accounts(company))


@frappe.whitelist()
def get_account(company, employee):
    return success(service.get_account(company, employee))


@frappe.whitelist(methods=['POST'])
def create_account(company, employee, contact=None, method='email', invite=0, delivery=None):
    return success(service.create_account(company, employee, contact, method, bool(frappe.utils.cint(invite)), delivery))


@frappe.whitelist(methods=['POST'])
def save_account_access(company, employee, grants, token, profile=None):
    return success(service.save_account_access(company, employee, frappe.parse_json(grants), token, profile))


@frappe.whitelist(methods=['POST'])
def invite_account(company, employee, registered=0, delivery=None):
    return success(service.invite_account(company, employee, registered=bool(frappe.utils.cint(registered)),
                                          delivery=delivery))


@frappe.whitelist()
def get_legacy_report(company):
    return success(service.legacy_report(company))
