"""Fill `status_key` and `search_text` of requests created before the request templates."""

import json

import frappe
from frappe.utils import get_fullname

from asoud_erp.services.request_serializer import build_search_text, item_rows_of
from asoud_erp.services.request_status import compute_status_key
from asoud_erp.services.request_templates.lifecycle import request_status_key

DOCTYPE = "ASOUD Workflow Request"


def execute() -> None:
    """Safe to run repeatedly: a row is only written when a value changed."""
    rows = frappe.get_all(
        DOCTYPE, fields=["name", "status", "status_key", "search_text", "workflow_instance", "subject", "owner",
                         "department", "project", "values_json"], limit_page_length=0)
    instances = {row.name: row for row in frappe.get_all(
        "ASOUD Workflow Instance", fields=["name", "status", "current_stage", "workflow_definition"],
        filters={"name": ["in", sorted({row.workflow_instance for row in rows if row.workflow_instance})
                          or [""]]}, limit_page_length=0)}
    employees = {row.user_id: row.employee_name for row in frappe.get_all(
        "Employee", fields=["user_id", "employee_name"], filters={"user_id": ["is", "set"]},
        limit_page_length=0)}
    departments = {row.name: row.department_name for row in frappe.get_all(
        "Department", fields=["name", "department_name"], limit_page_length=0)}
    for row in rows:
        instance = instances.get(row.workflow_instance)
        key = request_status_key(instance, row.status) if instance else compute_status_key(None, row.status)
        values = json.loads(row.values_json or "{}")
        text = build_search_text(
            row.name, row.subject or "", employees.get(row.owner) or get_fullname(row.owner),
            departments.get(row.department) or row.department or "", row.project or "", item_rows_of(values))
        changes = {field: value for field, value in (("status_key", key), ("search_text", text))
                   if (row.get(field) or "") != value}
        if changes:
            frappe.db.set_value(DOCTYPE, row.name, changes, update_modified=False)
