"""Real rows for the void/reissue HTTP spec: an employee-advance form and a request of another company."""

import json
import os
import sys
from uuid import uuid4


def prepare():
    import frappe

    from asoud_erp.api.v1 import forms
    from asoud_erp.integration_tests.fixtures import company
    from asoud_erp.integration_tests.request_fixtures import make_definition

    name = company()
    restore = None
    if not frappe.db.get_value('Company', name, 'default_employee_advance_account'):
        account = frappe.db.get_value('Account', {'company': name, 'is_group': 0, 'account_type': 'Receivable'})
        frappe.db.set_value('Company', name, 'default_employee_advance_account', account)
        restore = name
    definition, _ = make_definition(name, token='E2E-void-' + uuid4().hex[:8], fields=[])
    schema = {'kind': 'Request', 'title': 'E2E ابطال سند', 'workflow': definition,
              'execution': {'kind': 'employee_advance'}, 'sections': [{
                  'id': 'main', 'title': 'اصلی', 'fields': [
                      {'key': 'asked', 'label': 'مبلغ', 'type': 'Money', 'execution_key': 'amount'},
                      {'key': 'why', 'label': 'شرح', 'type': 'LongText', 'execution_key': 'purpose'}]}]}
    saved = forms.save_form(name, schema, client_id=uuid4().hex)['data']
    published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
    return {'form': saved['name'], 'revision': published['active_revision'], 'definition': definition,
            'restore': restore}


def foreign_request(company):
    """A request of another company that already carries an executed document."""
    import frappe

    request = frappe.get_doc({'doctype': 'ASOUD Workflow Request', 'company': company,
                              'request_type': 'E2E', 'subject': 'E2E foreign', 'status': 'Completed',
                              'native_status': 'Created', 'native_doctype': 'Employee Advance',
                              'native_name': 'E2E-none'})
    request.flags.ignore_mandatory = True
    request.flags.ignore_links = True
    request.insert(ignore_permissions=True)
    return {'name': request.name}


def cleanup(form, definition, restore=None, foreign=None):
    import frappe

    requests = frappe.get_all('ASOUD Workflow Request', filters={'workflow_definition': definition},
                              fields=['name', 'workflow_instance', 'native_name'], limit_page_length=0)
    for request in requests:
        if request.native_name:
            frappe.db.delete('Comment', {'reference_doctype': 'Employee Advance', 'reference_name': request.native_name})
        for doctype in ('ASOUD Workflow Activity', 'ASOUD Workflow Task'):
            frappe.db.delete(doctype, {'workflow_instance': request.workflow_instance})
        frappe.db.delete('Notification Log', {'document_name': ['in', [request.name, request.workflow_instance]]})
        frappe.db.delete('Comment', {'reference_doctype': 'ASOUD Workflow Request', 'reference_name': request.name})
        frappe.db.delete('ASOUD Workflow Instance', {'name': request.workflow_instance})
        frappe.db.delete('ASOUD Workflow Request', {'name': request.name})
    for advance in frappe.get_all('Employee Advance', filters={'purpose': 'E2E-void'}, pluck='name'):
        frappe.db.delete('Comment', {'reference_doctype': 'Employee Advance', 'reference_name': advance})
        frappe.db.delete('Employee Advance', {'name': advance})
    if foreign:
        frappe.db.delete('ASOUD Workflow Request', {'name': foreign})
    for doctype in ('ASOUD Form Entry', 'ASOUD Form Revision'):
        frappe.db.delete(doctype, {'form': form})
    frappe.db.delete('ASOUD Form', {'name': form})
    for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'):
        frappe.db.delete(doctype, {'workflow_definition': definition})
    frappe.db.delete('ASOUD Workflow Definition', {'name': definition})
    if restore:
        frappe.db.set_value('Company', restore, 'default_employee_advance_account', None)
    return {'cleaned': True}


def inspect(name):
    import frappe

    return frappe.db.get_value('Employee Advance', name, ['docstatus', 'advance_amount'], as_dict=True)


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
        elif action == 'foreign':
            result = foreign_request(options['company'])
        elif action == 'inspect':
            result = inspect(options['name'])
        elif action == 'cleanup':
            result = cleanup(**options)
        else:
            raise ValueError('invalid fixture action')
        frappe.db.commit()
        print('@@VOID_JSON@@' + json.dumps(result, ensure_ascii=False, default=str))
    finally:
        frappe.destroy()
