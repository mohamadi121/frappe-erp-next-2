"""Real rows for the leave, mission and overtime HTTP spec: own Leave Type and allocation, three forms."""

import json
import os
import random
import sys
from uuid import uuid4


def fields(kind):
    link = [{'key': 'kind', 'label': 'نوع', 'type': 'Link', 'source': 'Leave Type', 'required': True,
             'execution_key': 'leave_type'}]
    dates = [
        {'key': 'start', 'label': 'شروع', 'type': 'Date', 'required': True, 'execution_key': 'from_date'},
        {'key': 'end', 'label': 'پایان', 'type': 'Date', 'required': True, 'execution_key': 'to_date'}]
    if kind == 'leave_application':
        return link + dates + [{'key': 'note', 'label': 'توضیح', 'type': 'LongText', 'sensitive': True,
                                'execution_key': 'description'}]
    if kind == 'mission':
        return dates + [
            {'key': 'where', 'label': 'مقصد', 'type': 'Text', 'required': True, 'execution_key': 'destination'},
            {'key': 'why', 'label': 'هدف', 'type': 'LongText', 'required': True, 'execution_key': 'purpose'}]
    return [
        {'key': 'day', 'label': 'تاریخ', 'type': 'Date', 'required': True, 'execution_key': 'work_date'},
        {'key': 'from', 'label': 'شروع', 'type': 'Time', 'required': True, 'execution_key': 'start_time'},
        {'key': 'to', 'label': 'پایان', 'type': 'Time', 'required': True, 'next_day_allowed': True,
         'execution_key': 'end_time'},
        {'key': 'job', 'label': 'شرح', 'type': 'LongText', 'required': True, 'execution_key': 'purpose'}]


def prepare():
    import frappe
    from frappe.utils import add_days, nowdate

    from asoud_erp.api.v1 import forms
    from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, company
    from asoud_erp.integration_tests.request_fixtures import make_definition

    token = uuid4().hex[:8]
    employee = frappe.db.get_value('Employee', {'user_id': EMPLOYEE_USER}, 'name')
    leave_type = f'E2E-LMO-{token}'
    frappe.get_doc({'doctype': 'Leave Type', 'leave_type_name': leave_type, 'max_leaves_allowed': 30}).insert()
    frappe.get_doc({'doctype': 'Leave Allocation', 'employee': employee, 'leave_type': leave_type,
                    'from_date': add_days(nowdate(), -380), 'to_date': add_days(nowdate(), 300),
                    'new_leaves_allocated': 10}).submit()
    optional = f'E2E-LMO-OPT-{token}'
    frappe.get_doc({'doctype': 'Leave Type', 'leave_type_name': optional, 'is_optional_leave': 1}).insert()
    result = {'leave_type': leave_type, 'optional_type': optional, 'employee': employee, 'forms': {},
              'definitions': [], 'start': add_days(nowdate(), -random.randint(60, 300))}
    for kind in ('leave_application', 'mission', 'overtime'):
        definition, _ = make_definition(company(), token=f'E2E-lmo-{kind[:4]}-{token}', fields=[])
        schema = {'kind': 'Request', 'title': f'E2E {kind}', 'workflow': definition,
                  'execution': {'kind': kind}, 'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields(kind)}]}
        saved = forms.save_form(company(), schema, client_id=uuid4().hex)['data']
        published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
        result['forms'][kind] = {'form': saved['name'], 'revision': published['active_revision']}
        result['definitions'].append(definition)
    return result


def inspect(kind, name):
    import frappe

    doc = frappe.get_doc(kind, name)
    extra = {}
    if kind == 'Leave Application':
        extra = {'ledger': frappe.db.count('Leave Ledger Entry', {'transaction_name': name, 'docstatus': 1}),
                 'attendance': frappe.db.count('Attendance', {'leave_application': name, 'docstatus': 1})}
    if kind == 'Attendance Request':
        extra = {'attendance': frappe.db.count('Attendance', {'attendance_request': name, 'docstatus': 1})}
    return {'docstatus': doc.docstatus, 'text': doc.get('description') or doc.get('explanation'),
            'status': doc.get('status'), 'reason': doc.get('reason'), **extra}


def cleanup(forms, definitions, leave_type, optional_type):
    import frappe

    for definition in definitions:
        for request in frappe.get_all('ASOUD Workflow Request', filters={'workflow_definition': definition},
                                      fields=['name', 'workflow_instance', 'native_doctype', 'native_name'],
                                      limit_page_length=0):
            if request.native_doctype == 'Leave Application' and request.native_name:
                frappe.db.delete('Attendance', {'leave_application': request.native_name})
                frappe.db.delete('Leave Ledger Entry', {'transaction_name': request.native_name})
                frappe.db.delete('Leave Application', {'name': request.native_name})
            if request.native_doctype == 'Attendance Request' and request.native_name:
                frappe.db.delete('Attendance', {'attendance_request': request.native_name})
                frappe.db.delete('Attendance Request', {'name': request.native_name})
            if request.native_name:
                frappe.db.delete('Comment', {'reference_name': request.native_name})
            for doctype in ('ASOUD Workflow Activity', 'ASOUD Workflow Task'):
                frappe.db.delete(doctype, {'workflow_instance': request.workflow_instance})
            frappe.db.delete('Notification Log', {'document_name': ['in', [request.name, request.workflow_instance]]})
            frappe.db.delete('Comment', {'reference_doctype': 'ASOUD Workflow Request', 'reference_name': request.name})
            frappe.db.delete('ASOUD Workflow Instance', {'name': request.workflow_instance})
            frappe.db.delete('ASOUD Workflow Request', {'name': request.name})
    for form in forms:
        for doctype in ('ASOUD Form Entry', 'ASOUD Form Revision'):
            frappe.db.delete(doctype, {'form': form})
        frappe.db.delete('ASOUD Form', {'name': form})
    for definition in definitions:
        for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'):
            frappe.db.delete(doctype, {'workflow_definition': definition})
        frappe.db.delete('ASOUD Workflow Definition', {'name': definition})
    for allocation in frappe.get_all('Leave Allocation', filters={'leave_type': leave_type}, pluck='name'):
        frappe.db.delete('Leave Ledger Entry', {'transaction_name': allocation})
        frappe.db.delete('Leave Allocation', {'name': allocation})
    frappe.db.delete('Leave Type', {'name': ['in', [leave_type, optional_type]]})
    return {'cleaned': True}


if __name__ == '__main__':
    bench = os.path.expanduser('~/frappe-dev/bench')
    for app in ('frappe', 'erpnext', 'hrms'):
        sys.path.insert(0, os.path.join(bench, 'apps', app))
    import frappe

    os.chdir(os.path.join(bench, 'sites'))
    frappe.init(site=os.environ.get('E2E_SITE', 'asoud.test'))
    frappe.connect()
    frappe.set_user('Administrator')
    action = sys.argv[1]
    options = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    try:
        if action == 'prepare':
            result = prepare()
        elif action == 'inspect':
            result = inspect(**options)
        elif action == 'cleanup':
            result = cleanup(**options)
        else:
            raise ValueError('عملیات آزمون معتبر نیست.')
        frappe.db.commit()
        print('@@LMO_JSON@@' + json.dumps(result, ensure_ascii=False, default=str))
    finally:
        frappe.destroy()
