"""Execution metadata uses real role checks and persists in form revisions."""

from unittest.mock import patch

import frappe

from asoud_erp.api.v1 import forms, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import open_task
from asoud_erp.services.form_execution import EXECUTORS, Result
from asoud_erp.services.session_scope import as_administrator


class ExampleExecutor:
    KIND = 'test_only'
    LABEL = 'اجرای آزمایشی'
    PARAMETERS = {'amount': {'label': 'مبلغ', 'types': ['Money'], 'required': True}}

    def build(self, params, ctx):
        return {'doctype': 'ToDo', 'description': str(params['amount'])}

    def apply(self, request, params):
        raise ValueError('اجرای آزمایشی انجام نشد.')


class TestFormExecution(APITestCase):
    def test_catalog_rejects_employee_and_allows_designer_without_employee(self):
        user = 'execution-' + frappe.generate_hash(length=12) + '@example.com'
        frappe.get_doc({'doctype': 'User', 'email': user, 'first_name': 'آزمایش',
                        'send_welcome_email': 0, 'user_type': 'System User',
                        'roles': [{'role': 'Accounts Manager'}]}).insert()
        self.assertFalse(frappe.db.exists('Employee', {'user_id': user}))
        with patch.dict(EXECUTORS, {'test_only': ExampleExecutor()}, clear=True):
            frappe.set_user(user)
            self.assertEqual(forms.execution_kinds()['data'], [{
                'kind': 'test_only', 'label': 'اجرای آزمایشی',
                'parameters': {'amount': {'label': 'مبلغ', 'types': ['Money'], 'required': True}},
            }])
            frappe.set_user(EMPLOYEE_USER)
            with self.assertRaises(frappe.PermissionError):
                forms.execution_kinds()

    def test_execution_is_validated_and_retained_in_published_revision(self):
        schema = {'kind': 'Request', 'title': 'درخواست آزمایشی', 'schema_version': 2,
                  'execution': {'kind': 'test_only'}, 'sections': [{
                      'id': 'main', 'title': 'اصلی', 'fields': [
                          {'key': 'asked', 'label': 'مبلغ', 'type': 'Money', 'execution_key': 'amount'},
                      ]}]}
        with patch.dict(EXECUTORS, {'test_only': ExampleExecutor()}, clear=True):
            saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
            published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
            revision = forms.get_form(saved['name'])['data']
            self.assertEqual(revision['revision'], published['active_revision'])
            self.assertEqual(revision['schema']['execution'], {'kind': 'test_only'})
            self.assertEqual(revision['schema']['sections'][0]['fields'][0]['execution_key'], 'amount')
            schema['sections'][0]['fields'][0]['execution_key'] = 'unknown'
            with self.assertRaisesRegex(frappe.ValidationError, 'پارامتر'):
                forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))


class NativeExecutor(ExampleExecutor):
    fail = False

    def apply(self, request, params):
        with as_administrator():
            doc = frappe.get_doc(self.build(params, {})).insert(ignore_permissions=True)
        if self.fail:
            raise ValueError('تنظیمات اجرای سند کامل نیست.')
        return Result(status='Created', doctype=doc.doctype, name=doc.name)


class TestFormExecutionRuntime(APITestCase):
    def submit(self, *, approvals=1, step_fields=None):
        definition, stages = make_definition(self.company, approvals=approvals, fields=[
            {'key': 'amount', 'label': 'مبلغ', 'type': 'Currency', 'required': True}])
        if step_fields:
            stage = next(stage for stage in stages.values() if stage.stage_type == 'Approval')
            import json
            config = json.loads(stage.config_json)
            config['form_fields'] = step_fields
            stage.config_json = json.dumps(config)
            stage.save(ignore_permissions=True)
        schema = {'kind': 'Request', 'title': 'درخواست اجرا', 'workflow': definition,
                  'execution': {'kind': 'test_only'}, 'sections': [{
                      'id': 'main', 'title': 'اصلی', 'fields': [
                          {'key': 'asked', 'label': 'مبلغ', 'type': 'Money',
                           'workflow_key': 'amount', 'execution_key': 'amount'}]}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
        frappe.set_user(EMPLOYEE_USER)
        entry = forms.submit_form(saved['name'], published['active_revision'], 'درخواست اجرای آزمون',
                                  {'asked': 125}, frappe.generate_hash(length=24))['data']
        return workflow_request.get_request(entry['reference_name'])['data']

    def decide(self, request, action, response=None):
        task = open_task(request['workflow_instance'])
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, action, comment='دلیل تصمیم آزمون', response=response)
        frappe.set_user('Administrator')
        return workflow_request.get_request(request['name'])['data']

    def test_final_approval_creates_native_draft_once(self):
        with patch.dict(EXECUTORS, {'test_only': NativeExecutor()}, clear=True):
            request = self.submit()
            approved = self.decide(request, 'Approve')
            self.assertEqual(approved['native']['status'], 'Created')
            name = approved['native']['name']
            self.assertEqual(frappe.db.get_value('ToDo', name, ['description', 'docstatus']), ('125.0', 0))
            from asoud_erp.services.request_native_documents import dispatch
            dispatch(frappe.get_doc('ASOUD Workflow Request', request['name']))
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Request', request['name'], 'native_name'), name)

    def test_failure_rolls_back_only_native_write_and_retry_creates_document(self):
        executor = NativeExecutor()
        executor.fail = True
        with patch.dict(EXECUTORS, {'test_only': executor}, clear=True):
            request = self.submit()
            before = frappe.db.count('ToDo')
            approved = self.decide(request, 'Approve')
            self.assertEqual(approved['native']['status'], 'Failed')
            self.assertIn('تنظیمات اجرای سند کامل نیست.', approved['native']['error'])
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', request['workflow_instance'], 'status'), 'Completed')
            self.assertEqual(frappe.db.count('ToDo'), before)
            executor.fail = False
            retried = workflow_request.create_native_document(request['name'])['data']
            self.assertEqual(retried['native']['status'], 'Created')
            self.assertEqual(frappe.db.count('ToDo'), before + 1)

    def test_rejected_request_does_not_execute(self):
        with patch.dict(EXECUTORS, {'test_only': NativeExecutor()}, clear=True):
            request = self.submit()
            before = frappe.db.count('ToDo')
            rejected = self.decide(request, 'Reject')
            self.assertNotEqual(rejected['native']['status'], 'Created')
            self.assertEqual(frappe.db.count('ToDo'), before)

    def test_completed_approval_parameters_override_requested_amount(self):
        with patch.dict(EXECUTORS, {'test_only': NativeExecutor()}, clear=True):
            request = self.submit(step_fields=[{'key': 'approved', 'label': 'مبلغ مصوب',
                                                'type': 'Currency', 'execution_key': 'amount'}])
            approved = self.decide(request, 'Approve', {'approved': 75})
            self.assertEqual(approved['native']['status'], 'Created')
            self.assertEqual(frappe.db.get_value('ToDo', approved['native']['name'], 'description'), '75.0')

    def test_employee_lookup_requires_active_record_in_request_company(self):
        with patch.dict(EXECUTORS, {'test_only': NativeExecutor()}, clear=True):
            request = self.submit()
            frappe.set_user('Administrator')
            employee = frappe.db.get_value('Employee', {'user_id': EMPLOYEE_USER, 'company': self.company})
            frappe.db.set_value('Employee', employee, 'status', 'Inactive')
            approved = self.decide(request, 'Approve')
            self.assertEqual(approved['native']['status'], 'Failed')
            self.assertEqual(approved['native']['error'], 'پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')

    def test_workflow_completed_during_submit_executes_after_entry_is_saved(self):
        with patch.dict(EXECUTORS, {'test_only': NativeExecutor()}, clear=True):
            request = self.submit(approvals=0)
            self.assertEqual(request['native']['status'], 'Created')
            self.assertEqual(frappe.db.get_value('ToDo', request['native']['name'], 'docstatus'), 0)

    def test_stage_mapping_must_match_attached_form_kind(self):
        import json

        from asoud_erp.api.v1 import workflow

        other = ExampleExecutor()
        other.PARAMETERS = {'purpose': {'label': 'دلیل', 'types': ['LongText'], 'required': False}}
        with patch.dict(EXECUTORS, {'test_only': NativeExecutor(), 'other': other}, clear=True):
            request = self.submit()
            frappe.set_user('Administrator')
            stage = frappe.db.get_value('ASOUD Workflow Stage', {
                'workflow_definition': request['workflow_definition'], 'stage_type': 'Approval'},
                ['name', 'config_json'], as_dict=True)
            config = json.loads(stage.config_json)
            config['form_fields'] = [{'key': 'note', 'label': 'دلیل مصوب', 'type': 'Long Text',
                                      'execution_key': 'purpose'}]
            with self.assertRaisesRegex(frappe.ValidationError, 'پارامتر'):
                workflow.save_stage_settings(request['workflow_definition'], stage.name, config)
            config['form_fields'] = [{'key': 'approved', 'label': 'مبلغ مصوب', 'type': 'Currency',
                                      'execution_key': 'amount'}]
            workflow.save_stage_settings(request['workflow_definition'], stage.name, config)
            stored = json.loads(frappe.db.get_value('ASOUD Workflow Stage', stage.name, 'config_json'))
            self.assertEqual(stored['form_fields'][0]['execution_key'], 'amount')
