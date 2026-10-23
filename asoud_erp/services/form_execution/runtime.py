"""Load immutable form metadata and native execution inputs after approval."""

import json

import frappe

from asoud_erp.services.form_execution import EXECUTORS
from asoud_erp.services.form_execution.parameters import collect_parameters


def execute(request):
    entry = frappe.db.get_value('ASOUD Form Entry', {
        'reference_doctype': 'ASOUD Workflow Request', 'reference_name': request.name,
        'company': request.company,
    }, ['revision', 'values_json'], as_dict=True)
    if not entry:
        return None
    schema = json.loads(frappe.db.get_value('ASOUD Form Revision', entry.revision, 'schema_json') or '{}')
    execution = schema.get('execution')
    if not execution:
        return None
    executor = EXECUTORS.get(execution.get('kind'))
    if not executor:
        raise ValueError('نوع اجرای این فرم در دسترس نیست.')
    employee = frappe.db.get_value('Employee', {
        'user_id': request.owner, 'company': request.company, 'status': 'Active'}, 'name')
    if not employee:
        raise ValueError('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
    request.requester_employee = employee
    fields = [field for section in schema.get('sections', []) for field in section.get('fields', [])]
    values = json.loads(entry.values_json or '{}')
    # Corrections to the original request can use different workflow field identifiers.
    from asoud_erp.api.v1.workflow_request import effective_values

    current = effective_values(request.name)
    for field in fields:
        source = field.get('workflow_key')
        if source in current:
            values[field['key']] = current[source]
    tasks = []
    start = 0
    while True:
        page = frappe.get_all('ASOUD Workflow Task', filters={
            'workflow_instance': request.workflow_instance, 'status': 'Completed'},
            fields=['name', 'workflow_stage', 'status', 'completed_on', 'response_json'],
            order_by='completed_on asc, name asc', limit_start=start, limit_page_length=200)
        tasks.extend(page)
        if len(page) < 200:
            break
        start += 200
    stages = {row.name: json.loads(row.config_json or '{}').get('form_fields', [])
              for row in frappe.get_all('ASOUD Workflow Stage', filters={
                  'name': ['in', list({task.workflow_stage for task in tasks}) or ['']]},
                  fields=['name', 'config_json'], limit_page_length=0)}
    text_keys = {name for name, spec in executor.PARAMETERS.items()
                 if {'Text', 'LongText'} & set(spec.get('types') or [])}
    params = collect_parameters(fields, values, [{
        'name': task.name, 'status': task.status, 'completed_on': task.completed_on,
        'fields': stages.get(task.workflow_stage, []), 'values': json.loads(task.response_json or '{}'),
    } for task in tasks], request_name=request.name, text_keys=text_keys)
    return executor.apply(request, params)
