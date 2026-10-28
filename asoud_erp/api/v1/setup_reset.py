"""Temporary destructive operation: authenticated, gated and never queued."""
import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import setup_reset as service


@frappe.whitelist(methods=['POST'])
def preview():
    return success(service.preview())


@frappe.whitelist(methods=['POST'])
def perform(token=None, password=None, confirmation=None, backup_confirmed=0):
    return success(service.perform(token, password, confirmation, backup_confirmed))


@frappe.whitelist(methods=['POST'])
def status(job=None, preview_token=None):
    return success(service.status(job, preview_token))
