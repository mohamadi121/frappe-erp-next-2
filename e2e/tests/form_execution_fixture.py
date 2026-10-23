"""Test-only executor and real rows for the approval execution HTTP spec."""

import json
import os
import sys
from uuid import uuid4


class E2EExecutor:
    KIND = 'e2e_form_execution'
    LABEL = 'اجرای آزمون گردش‌کار'
    PARAMETERS = {
        'amount': {'label': 'مبلغ', 'types': ['Money'], 'required': True},
        'fail_first': {'label': 'آزمون تلاش مجدد', 'types': ['Check'], 'required': False},
    }

    def build(self, params, ctx):
        return {'doctype': 'ToDo', 'description': f"E2E-document-{ctx['request_name']}:{params['amount']}"}

    def apply(self, request, params):
        import frappe

        from asoud_erp.services.form_execution import Result
        from asoud_erp.services.session_scope import as_administrator

        with as_administrator():
            doc = frappe.get_doc(self.build(params, {'request_name': request.name})).insert(ignore_permissions=True)
        if params.get('fail_first') and not frappe.db.exists('ToDo', {'description': 'E2E-ready-' + request.name}):
            raise ValueError('تنظیمات اجرای سند کامل نیست.')
        return Result(status='Created', doctype='ToDo', name=doc.name)


def register():
    from asoud_erp.services.form_execution import EXECUTORS

    EXECUTORS[E2EExecutor.KIND] = E2EExecutor()


def prepare():
    from asoud_erp.api.v1 import forms
    from asoud_erp.integration_tests.fixtures import company
    from asoud_erp.integration_tests.request_fixtures import make_definition

    definition, _ = make_definition(company(), token='E2E-ex-' + uuid4().hex[:8], fields=[
        {'key': 'amount', 'label': 'مبلغ', 'type': 'Currency', 'required': True}])
    schema = {'kind': 'Request', 'title': 'E2E اجرای گردش‌کار', 'workflow': definition,
              'execution': {'kind': E2EExecutor.KIND}, 'sections': [{
                  'id': 'main', 'title': 'اصلی', 'fields': [
                      {'key': 'asked', 'label': 'مبلغ', 'type': 'Money', 'execution_key': 'amount', 'workflow_key': 'amount'},
                      {'key': 'retry', 'label': 'تلاش مجدد', 'type': 'Checkbox', 'execution_key': 'fail_first'},
                  ]}]}
    saved = forms.save_form(company(), schema, client_id=uuid4().hex)['data']
    published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
    return {'form': saved['name'], 'revision': published['active_revision'], 'definition': definition}


def cleanup(form, definition):
    import frappe

    requests = frappe.get_all('ASOUD Workflow Request', filters={'workflow_definition': definition},
                              fields=['name', 'workflow_instance', 'native_name'], limit_page_length=0)
    for request in requests:
        for name in [request.native_name, frappe.db.get_value('ToDo', {'description': 'E2E-ready-' + request.name})]:
            if name:
                frappe.db.delete('ToDo', {'name': name})
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
    register()
    action = sys.argv[1]
    options = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    try:
        if action == 'prepare':
            result = prepare()
        elif action == 'ready':
            frappe.get_doc({'doctype': 'ToDo', 'description': 'E2E-ready-' + options['request']}).insert()
            result = {'ready': True}
        elif action == 'inspect':
            result = frappe.db.get_value('ToDo', options['name'], ['description', 'docstatus'], as_dict=True)
        elif action == 'cleanup':
            result = cleanup(**options)
        else:
            raise ValueError('عملیات آزمون معتبر نیست.')
        frappe.db.commit()
        print('@@EXECUTION_JSON@@' + json.dumps(result, ensure_ascii=False))
    finally:
        frappe.destroy()
