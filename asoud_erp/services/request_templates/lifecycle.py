"""Workflow instance lifecycle hook: status mirror and post-approval dispatch.

`on_instance_update` runs on every `ASOUD Workflow Instance` save. It keeps the stored
`status_key` of the request in step with the instance and, when a template request is
finally approved (the instance becomes `Completed`), creates its native document.
"""

import frappe
from frappe import _

from asoud_erp.services.request_status import compute_status_key

REQUEST_DOCTYPE = "ASOUD Workflow Request"
ERROR_LIMIT = 1000
MANAGER_ROLES = ("HR Manager", "System Manager")


def request_status_key(instance, request_status: str | None = None) -> str:
    """The status key of the request an instance runs for (queries only while it is running)."""
    status = instance.status
    if status != "Running":
        return compute_status_key(status, request_status)
    from asoud_erp.api.v1.workflow_request import form_stage_name

    form_stage = form_stage_name(instance.workflow_definition)
    submitted = acted = False
    if form_stage:
        submitted = bool(frappe.db.exists("ASOUD Workflow Task", {
            "workflow_instance": instance.name, "workflow_stage": form_stage, "status": "Completed"}))
    acted_filters = {"workflow_instance": instance.name, "status": ["in", ["Completed", "Rejected"]]}
    if form_stage:
        acted_filters["workflow_stage"] = ["!=", form_stage]
    acted = bool(frappe.db.exists("ASOUD Workflow Task", acted_filters))
    return compute_status_key(
        status, request_status, at_form_stage=bool(form_stage) and instance.current_stage == form_stage,
        form_submitted=submitted, non_form_acted=acted)


def on_instance_update(doc, method=None) -> None:
    """`ASOUD Workflow Instance` `on_update` hook."""
    if doc.reference_doctype != REQUEST_DOCTYPE or not doc.reference_name:
        return
    request = frappe.db.get_value(
        REQUEST_DOCTYPE, doc.reference_name, ["name", "status", "status_key", "template_key"], as_dict=True)
    if not request:
        return
    key = request_status_key(doc, request.status)
    if key != request.status_key:
        frappe.db.set_value(REQUEST_DOCTYPE, request.name, "status_key", key, update_modified=False)
    if request.template_key and doc.status == "Completed" and doc.has_value_changed("status"):
        dispatch_native_document(request.name)


def dispatch_native_document(request_name: str) -> None:
    """Creates the native document of an approved request; a failure never un-approves it.

    `request_native_documents.dispatch` handles the expected business failures itself.
    Anything else is caught here, rolled back to a savepoint and recorded as `Failed`,
    so the final approval is always kept.
    """
    from asoud_erp.services.request_native_documents import dispatch

    request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
    frappe.db.savepoint("asoud_native_dispatch")
    try:
        dispatch(request)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception as error:  # the approval must survive any native failure
        frappe.db.rollback(save_point="asoud_native_dispatch")
        frappe.clear_messages()
        frappe.log_error(title="Native document creation failed", message=frappe.get_traceback())
        record_native_failure(request_name, str(error) or error.__class__.__name__)


def record_native_failure(request_name: str, error: str) -> None:
    """Marks the request `Failed` with the error and notifies the people who can fix it."""
    frappe.db.set_value(REQUEST_DOCTYPE, request_name, {
        "native_status": "Failed", "native_error": (error or "")[:ERROR_LIMIT]}, update_modified=False)
    request = frappe.db.get_value(REQUEST_DOCTYPE, request_name, ["owner", "workflow_instance"], as_dict=True)
    managers = frappe.get_all("Has Role", filters={"role": ["in", list(MANAGER_ROLES)], "parenttype": "User"},
                              pluck="parent", limit_page_length=0)
    enabled = set(frappe.get_all("User", filters={"name": ["in", managers or [""]], "enabled": 1}, pluck="name"))
    for user in dict.fromkeys([request.owner, *[manager for manager in managers if manager in enabled]]):
        if not user or user in {"Guest", "Administrator"}:
            continue
        # In-app alert, like the workflow runtime's notifications; recipients are the requester and managers.
        frappe.get_doc({
            "doctype": "Notification Log", "for_user": user, "from_user": frappe.session.user, "type": "Alert",
            "subject": _("Creating the document for request {0} failed").format(request_name),
            "document_type": "ASOUD Workflow Instance" if request.workflow_instance else REQUEST_DOCTYPE,
            "document_name": request.workflow_instance or request_name,
            "email_content": (error or "")[:500], "read": 0,
        }).insert(ignore_permissions=True)
