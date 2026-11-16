"""Idempotent completion of a workflow task (network-retry safety).

A client that loses the connection after the server has already applied a decision
re-sends the same ``request_id``. Instead of failing on the already-completed task,
the server returns the original outcome. The ``request_id`` is stored on the
completion activity so a retry can find it.
"""
import json

import frappe


def completion_change_json(request_id):
    """The completion activity's ``change_json``; a ``request_id`` makes a retry idempotent."""
    if not request_id:
        return None
    return json.dumps({"request_id": request_id}, ensure_ascii=False)


def previous_completion(task_name, request_id):
    """The stored result of an earlier completion made with the same ``request_id``, or None.

    Only activities written for this exact task are considered, so a ``request_id``
    reused on a different task never returns a foreign result.
    """
    if not request_id:
        return None
    rows = frappe.get_all(
        "ASOUD Workflow Activity",
        filters={"workflow_task": task_name},
        fields=["workflow_instance", "change_json", "created_on"],
        order_by="created_on desc",
        limit_page_length=0,
    )
    for row in rows:
        try:
            data = json.loads(row.change_json or "{}")
        except (TypeError, ValueError):
            continue
        if data.get("request_id") == request_id:
            instance_status = frappe.db.get_value(
                "ASOUD Workflow Instance", row.workflow_instance, "status"
            )
            return {"task": task_name, "instance_status": instance_status}
    return None
