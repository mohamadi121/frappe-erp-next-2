"""Create, approve and read requests as the fixture employee and manager."""

from unittest.mock import patch
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER


def create(company, definition=None, template_key=None, user=EMPLOYEE_USER, values=None, **kwargs):
    """Creates a request as `user` and returns the detail; the caller's user is restored."""
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        with patch.object(workflow_runtime, "_notify_user"):
            return workflow_request.create_request(
                company=company, workflow_definition=definition, template_key=template_key,
                subject=kwargs.pop("subject", "درخواست آزمایشی"), request_id=kwargs.pop(
                    "request_id", "request-" + uuid4().hex[:16]), values=values or {}, **kwargs)["data"]
    finally:
        frappe.set_user(previous)


def open_task(instance, assignee=None):
    filters = {"workflow_instance": instance, "status": "Open"}
    if assignee:
        filters["assigned_to"] = assignee
    return frappe.db.get_value("ASOUD Workflow Task", filters, ["name", "assigned_to"], as_dict=True)


def act(instance, action, comment=None, response=None, user=APPROVER_USER):
    """Completes the open task of `instance` as `user` (the manager by default)."""
    previous = frappe.session.user
    task = open_task(instance, user)
    frappe.set_user(user)
    try:
        with patch.object(workflow_runtime, "_notify_user"):
            return workflow_runtime.complete_workflow_task(task.name, action, comment=comment, response=response)
    finally:
        frappe.set_user(previous)


def status_key(name):
    return frappe.db.get_value("ASOUD Workflow Request", name, "status_key")


def valid_pdf_bytes(size: int | None = None) -> bytes:
    """A small parseable PDF, optionally padded to an exact byte size."""
    from io import BytesIO

    from pypdf import PdfWriter

    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=1, height=1)
    writer.write(stream)
    data = stream.getvalue()
    if size is not None and size > len(data):
        data += b"x" * (size - len(data))
    return data

def clear_request_records():
    """Remove persisted request-engine rows from the shared test site."""
    frappe.db.sql(
        "delete from `tabComment` "
        "where reference_doctype = 'ASOUD Workflow Request'"
    )
    frappe.db.sql(
        "delete from `tabFile` "
        "where attached_to_doctype = 'ASOUD Workflow Request'"
    )
    frappe.db.sql(
        "delete from `tabNotification Log` "
        "where document_type in ('ASOUD Workflow Request', 'ASOUD Workflow Task')"
    )
    for doctype in (
        "ASOUD Workflow Activity",
        "ASOUD Workflow Task",
        "ASOUD Workflow Instance",
        "ASOUD Workflow Request",
    ):
        frappe.db.sql(f"delete from `tab{doctype}`")

