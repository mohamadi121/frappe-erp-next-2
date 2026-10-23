"""Validate workflow overrides against forms attached to that workflow."""

import json

import frappe

from asoud_erp.services.form_execution.schema import validate_parameter_fields


def validate_for_workflow(definition: str, fields: list[dict]) -> None:
    if not any('execution_key' in field for field in fields):
        return
    company = frappe.db.get_value('ASOUD Workflow Definition', definition, 'company')
    start = 0
    kinds = set()
    while True:
        forms = frappe.get_all('ASOUD Form', filters={'company': company, 'kind': 'Request'},
                               fields=['draft_json', 'active_revision'], order_by='name asc',
                               limit_start=start, limit_page_length=100)
        revisions = {row.name: row.schema_json for row in frappe.get_all('ASOUD Form Revision',
                     filters={'name': ['in', [row.active_revision for row in forms if row.active_revision] or ['']]},
                     fields=['name', 'schema_json'], limit_page_length=100)}
        for form in forms:
            for raw in (form.draft_json, revisions.get(form.active_revision)):
                schema = json.loads(raw or '{}')
                if schema.get('workflow') == definition and schema.get('execution'):
                    kinds.add(schema['execution']['kind'])
        if len(forms) < 100:
            break
        start += 100
    for kind in kinds:
        validate_parameter_fields(fields, kind)
