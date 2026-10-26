"""Administrator-only, online first-office steps. Service enforces all gates."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import first_office_setup as service


@frappe.whitelist(methods=["POST"])
def status(company: str):
    return success(service.status(company))


@frappe.whitelist(methods=["POST"])
def create_hr_lead(company: str, full_name: str, username: str, contact: str, temporary_password: str):
    return success(service.create_hr_lead(company, full_name, username, contact, temporary_password))


@frappe.whitelist(methods=["POST"])
def complete(company: str):
    return success(service.complete(company))
