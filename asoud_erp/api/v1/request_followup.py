"""Receipt confirmation of issued equipment (N6). Contract: docs/api/form-execution.md."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import request_followup_runtime as runtime


@frappe.whitelist(methods=["POST"])
def confirm_receipt(task: str) -> dict:
    """The requester confirms receiving the equipment; the Asset Movement is submitted."""
    return success(runtime.confirm(task))


@frappe.whitelist(methods=["POST"])
def reject_receipt(task: str, reason: str | None = None) -> dict:
    """The requester reports not receiving the equipment, with a reason; the movement stays a draft."""
    return success(runtime.reject(task, reason))
