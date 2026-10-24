"""Real rows for the confidential-field HTTP spec: a form whose free text field is `sensitive`."""

import json
import os
import sys
from uuid import uuid4


def prepare():
    from asoud_erp.api.v1 import forms
    from asoud_erp.integration_tests.fixtures import company
    from asoud_erp.integration_tests.request_fixtures import make_definition

    definition, _ = make_definition(company(), token='E2E-conf-' + uuid4().hex[:8], fields=[
        {'key': 'reason', 'label': 'دلیل', 'type': 'Long Text', 'max_length': 2000}])
    schema = {'kind': 'Request', 'title': 'E2E محرمانه', 'workflow': definition, 'sections': [{
        'id': 'main', 'title': 'اصلی', 'fields': [
            {'key': 'why', 'label': 'علت', 'type': 'LongText', 'workflow_key': 'reason', 'sensitive': True}]}]}
    saved = forms.save_form(company(), schema, client_id=uuid4().hex)['data']
    published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
    return {'form': saved['name'], 'revision': published['active_revision'], 'definition': definition}


def cleanup(form, definition):
    import frappe

    requests = frappe.get_all('ASOUD Workflow Request', filters={'workflow_definition': definition},
                              fields=['name', 'workflow_instance'], limit_page_length=0)
    for request in requests:
        for doctype in ('ASOUD Workflow Activity', 'ASOUD Workflow Task'):
            frappe.db.delete(doctype, {'workflow_instance': request.workflow_instance})
        frappe.db.delete('Notification Log', {'document_name': ['in', [request.name, request.workflow_instance]]})
        frappe.db.delete('ASOUD Workflow Instance', {'name': request.workflow_instance})
        frappe.db.delete('ASOUD Workflow Request', {'name': request.name})
    for doctype in ('ASOUD Form Entry', 'ASOUD Form Revision'):
        frappe.db.delete(doctype, {'form': form})
    frappe.db.delete('ASOUD Form', {'name': form})
    for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'):
        frappe.db.delete(doctype, {'workflow_definition': definition})
    frappe.db.delete('ASOUD Workflow Definition', {'name': definition})
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
        result = prepare() if action == 'prepare' else cleanup(**options)
        frappe.db.commit()
        print('@@CONFIDENTIAL_JSON@@' + json.dumps(result, ensure_ascii=False))
    finally:
        frappe.destroy()
