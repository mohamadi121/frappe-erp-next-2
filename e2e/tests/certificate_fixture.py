"""Real rows for the certificate download spec: a published T3-style form, a letter head, foreign users."""

import json
import os
import sys
from uuid import uuid4

PASSWORD = 'E2e-Pw-Cert-2026'
FOREIGN_EMPLOYEE = 'e2e.cert.foreign@example.com'
FOREIGN_HR = 'e2e.cert.foreignhr@example.com'
NO_EMPLOYEE = 'e2e.cert.noemployee@example.com'


def make_user(email, roles, company=None):
    import frappe
    from frappe.utils.password import update_password

    if not frappe.db.exists('User', email):
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'E2E Cert', 'send_welcome_email': 0,
                        'roles': [{'role': role} for role in roles]}).insert(ignore_permissions=True)
    update_password(email, PASSWORD)
    if company:
        frappe.get_doc({'doctype': 'Employee', 'first_name': 'E2E Cert', 'gender': 'Male',
                        'date_of_birth': '1990-01-01', 'date_of_joining': '2020-01-01', 'company': company,
                        'status': 'Active', 'user_id': email, 'create_user_permission': 0}).insert(
            ignore_permissions=True)
        frappe.get_doc({'doctype': 'User Permission', 'user': email, 'allow': 'Company', 'for_value': company,
                        'apply_to_all_doctypes': 1}).insert(ignore_permissions=True)
    frappe.clear_cache(user=email)


def prepare():
    import frappe

    from asoud_erp.api.v1 import forms
    from asoud_erp.integration_tests.fixtures import company
    from asoud_erp.integration_tests.request_fixtures import make_definition

    own = company()
    second = frappe.db.get_value('Company', {'name': ['!=', own], 'company_name': 'E2E Second Company'}, 'name')
    if not second:
        raise ValueError('E2E second company is missing; run the global setup first')
    previous = frappe.db.get_value('Company', own, 'default_letter_head')
    head = frappe.get_doc({'doctype': 'Letter Head', 'letter_head_name': 'E2E cert ' + uuid4().hex[:8],
                           'content': '<div>سربرگ آزمون</div>'}).insert(ignore_permissions=True).name
    frappe.db.set_value('Company', own, 'default_letter_head', head)
    make_user(FOREIGN_EMPLOYEE, ['Employee'], second)
    make_user(FOREIGN_HR, ['HR Manager'], second)
    frappe.get_doc('User', FOREIGN_HR).add_roles('Employee')
    make_user(NO_EMPLOYEE, ['Employee'])
    definition, _ = make_definition(own, token='E2E-cert-' + uuid4().hex[:8], fields=[])
    schema = {'kind': 'Request', 'title': 'E2E گواهی اشتغال', 'workflow': definition,
              'execution': {'kind': 'certificate_issue'}, 'sections': [{'id': 'main', 'title': 'اصلی', 'fields': [
                  {'key': 'recipient', 'label': 'مرجع', 'type': 'Text', 'execution_key': 'recipient'},
                  {'key': 'purpose', 'label': 'هدف', 'type': 'Select', 'execution_key': 'purpose',
                   'options': [{'id': 'bank', 'label': 'ارائه به بانک'}, {'id': 'other', 'label': 'سایر'}]}]}]}
    saved = forms.save_form(own, schema, client_id=uuid4().hex)['data']
    published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
    return {'form': saved['name'], 'revision': published['active_revision'], 'definition': definition,
            'head': head, 'previous_head': previous, 'company': own}


def cleanup(form, definition, head, previous_head, company):
    import frappe

    requests = frappe.get_all('ASOUD Workflow Request', filters={'workflow_definition': definition},
                              fields=['name', 'workflow_instance'], limit_page_length=0)
    for request in requests:
        for file in frappe.get_all('File', filters={'attached_to_doctype': 'ASOUD Workflow Request',
                                                    'attached_to_name': request.name}, pluck='name'):
            path = frappe.get_doc('File', file).get_full_path()
            frappe.db.delete('File', {'name': file})
            if os.path.exists(path):
                os.remove(path)
        for doctype in ('ASOUD Workflow Activity', 'ASOUD Workflow Task'):
            frappe.db.delete(doctype, {'workflow_instance': request.workflow_instance})
        frappe.db.delete('Notification Log', {'document_name': ['in', [request.name, request.workflow_instance]]})
        frappe.db.delete('Comment', {'reference_doctype': 'ASOUD Workflow Request', 'reference_name': request.name})
        frappe.db.delete('ASOUD Workflow Instance', {'name': request.workflow_instance})
        frappe.db.delete('ASOUD Workflow Request', {'name': request.name})
    for doctype in ('ASOUD Form Entry', 'ASOUD Form Revision'):
        frappe.db.delete(doctype, {'form': form})
    frappe.db.delete('ASOUD Form', {'name': form})
    for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'):
        frappe.db.delete(doctype, {'workflow_definition': definition})
    frappe.db.delete('ASOUD Workflow Definition', {'name': definition})
    frappe.db.set_value('Company', company, 'default_letter_head', previous_head)
    frappe.db.delete('Letter Head', {'name': head})
    for email in (FOREIGN_EMPLOYEE, FOREIGN_HR, NO_EMPLOYEE):
        frappe.db.delete('User Permission', {'user': email})
        frappe.db.delete('Employee', {'user_id': email})
        frappe.db.delete('Has Role', {'parent': email})
        frappe.db.delete('User', {'name': email})
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
        elif action == 'cleanup':
            result = cleanup(**options)
        else:
            raise ValueError('unknown fixture action')
        frappe.db.commit()
        print('@@CERT_JSON@@' + json.dumps(result, ensure_ascii=False))
    finally:
        frappe.destroy()
