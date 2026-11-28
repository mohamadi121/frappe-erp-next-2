"""Shared protection for finalizing a document once its workflow instance completes.

The native request path (``request_templates.lifecycle.dispatch_native_document``) and the five
specialised HR modules (contract, certificate, introduction letter, hiring order, salary change)
all finalize or issue a document when its workflow instance becomes ``Completed``. A failure
inside that finalization must never undo the approval: it rolls back to a savepoint, records the
failure, and logs it. This module is the single implementation of that protection, so the native
path and the specialised modules share one mechanism instead of each carrying a copy.
"""

import re

import frappe

_PERSIAN = re.compile(r"[\u0600-\u06ff]")


def run_guarded(action, on_failure, *, savepoint, log_title):
    """Run ``action`` inside a savepoint with the native-path failure protection.

    ``on_failure(reason)`` records the failure (e.g. marks the entry ``Failed`` with a reason).
    Deadlock/timeout are re-raised because the transaction is already gone; any other error rolls
    back to ``savepoint``, is logged, and is handed to ``on_failure``. The approval itself is
    never undone and the error is never swallowed silently.
    """
    frappe.db.savepoint(savepoint)
    try:
        action()
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
        raise
    except Exception as error:  # noqa: BLE001 - the approval must survive any completion failure
        frappe.db.rollback(save_point=savepoint)
        frappe.clear_messages()
        frappe.log_error(title=log_title, message=frappe.get_traceback())
        on_failure(str(error) or error.__class__.__name__)


def persian_reason(error_text, fallback):
    """``error_text`` when it already reads Persian, otherwise the Persian ``fallback`` sentence.

    The stored failure reason is shown to users, so it must be a Persian sentence; a raw English
    error (a ``KeyError`` or an ERPNext message) is replaced by the module's Persian fallback.
    """
    text = (error_text or "").strip()
    return text if _PERSIAN.search(text) else fallback
