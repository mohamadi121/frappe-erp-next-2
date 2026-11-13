"""Submitted records enter a real instance without copying their form or values."""
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import forms, workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import ACCOUNTANT_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import EMPLOYEE_B_USER, setup_tenancy
from asoud_erp.services.workflow_submission_source import sanitized


def schema():
    return {'kind': 'Request', 'title': 'فرم اتصال گردش‌کار', 'sections': [
        {'id': 'main', 'title': 'اطلاعات', 'fields': [
            {'key': 'note', 'label': 'توضیح', 'type': 'Text', 'required': True},
            {'key': 'secret', 'label': 'خصوصی', 'type': 'Text', 'sensitive': True},
            {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'columns': [
                {'key': 'title', 'label': 'عنوان', 'type': 'Text'},
                {'key': 'qty', 'label': 'تعداد', 'type': 'Integer'}]},
        ]}]}


class TestWorkflowSubmissionSource(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = setup_tenancy()['second']

    def setUp(self):
        super().setUp()
        self.definition, stages = make_definition(self.company, approvals=0, fields=[])
        self.stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        saved = forms.save_form(self.company, schema(), client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.source = forms.get_form(saved['name'])['data']
        self.config = {'title': 'بررسی ثبت اصلی', 'activity_type': 'Review',
            'assignment_type': 'Initiator', 'submission_source': {
                'form': self.source['name'], 'revision': self.source['revision']}}
        workflow.save_stage_settings(self.definition, self.stage.name, self.config)

    def test_submit_routes_original_entry_once_and_completion_creates_no_request(self):
        frappe.set_user(EMPLOYEE_USER)
        before = frappe.db.count('ASOUD Workflow Request')
        key = uuid4().hex
        values = {'note': 'اطلاعات اصلی', 'secret': 'خصوصی', 'rows': [{'title': 'ردیف', 'qty': 2}]}
        result = forms.submit_form(self.source['name'], self.source['revision'], 'درخواست آزمایشی', values, key)['data']
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.reference_doctype, 'ASOUD Form Entry')
        self.assertEqual(instance.reference_name, result['name'])
        self.assertEqual(forms.submit_form(self.source['name'], self.source['revision'],
            'درخواست آزمایشی', values, key)['data']['name'], result['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {
            'reference_doctype': 'ASOUD Form Entry', 'reference_name': result['name']}), 1)
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance.name}, 'name')
        detail = workflow_runtime.get_workflow_task(task)['data']
        # The snapshot exposes validated stored values, not the raw numeric input.
        stored = json.loads(frappe.db.get_value('ASOUD Form Entry', result['name'], 'values_json'))
        self.assertEqual(stored['rows'], [{'title': 'ردیف', 'qty': '2'}])
        self.assertEqual(detail['submitted_form']['values']['rows'], stored['rows'])
        self.assertNotIn('secret', detail['submitted_form']['values'])
        self.assertNotIn('secret', detail['request_values'])
        self.assertEqual(detail['config']['form_fields'], [])
        workflow_runtime.complete_workflow_task(task, 'Complete', response={})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance.name, 'status'), 'Completed')
        self.assertEqual(frappe.db.count('ASOUD Workflow Request'), before)
        self.assertEqual(json.loads(frappe.db.get_value('ASOUD Form Entry', result['name'], 'values_json'))['secret'], 'خصوصی')

    def test_published_revision_change_requires_explicit_rebinding(self):
        current = forms.get_form(self.source['name'], manage=1)['data']
        changed = schema()
        changed['title'] = 'نسخهٔ جدید'
        saved = forms.save_form(self.company, changed, self.source['name'], current['draft_version'])['data']
        forms.transition(self.source['name'], 'publish', saved['draft_version'])
        new = forms.get_form(self.source['name'])['data']
        before = frappe.db.count('ASOUD Form Entry')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            forms.submit_form(new['name'], new['revision'], 'ثبت نسخه جدید', {'note': 'اطلاعات'}, uuid4().hex)
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_inactive_route_rejects_valid_data_before_creating_an_entry(self):
        doc = frappe.get_doc('ASOUD Workflow Definition', self.definition)
        doc.status = 'Inactive'
        doc.save()
        before = frappe.db.count('ASOUD Form Entry')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            forms.submit_form(self.source['name'], self.source['revision'], 'درخواست معتبر',
                {'note': 'اطلاعات معتبر'}, uuid4().hex)
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_employee_cannot_bind_but_manager_can_share_source_without_changing_default(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.save_stage_settings(self.definition, self.stage.name, self.config)
        frappe.set_user('Administrator')
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        workflow.save_stage_settings(definition, stage.name, self.config)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', definition, 'source_form'), self.source['name'])
        stored = json.loads(frappe.db.get_value('ASOUD Workflow Stage', stage.name, 'config_json'))
        self.assertEqual(stored['source_route'], 'Available')
        from asoud_erp.services.workflow_submission_source import route

        self.assertEqual(route(frappe.get_doc('ASOUD Form', self.source['name']),
            frappe.get_doc('ASOUD Form Revision', self.source['revision'])), self.definition)

    def test_snapshot_filters_sensitive_columns_and_private_attachments(self):
        raw = {'sections': [{'fields': [{'key': 'rows', 'type': 'Table', 'columns': [
            {'key': 'public', 'type': 'Text'}, {'key': 'private', 'type': 'Text', 'sensitive': True}]},
            {'key': 'file', 'type': 'File'}]}]}
        _, values = sanitized(raw, {'rows': [{'public': 'مجاز', 'private': 'محرمانه'}], 'file': '/private/files/x'})
        self.assertEqual(values, {'rows': [{'public': 'مجاز'}]})

    def conditional_route(self):
        source = {'form': self.source['name'], 'revision': self.source['revision']}
        definition = workflow.create_workflow_draft('مسیر مشروط فرم مشترک', 'HR', 'ASOUD Workflow Request',
            company=self.company, start_settings={'trigger_type': 'Document Event', 'initiator_roles': [],
                'submission_source': source, 'source_route': 'Conditional'})['data']['name']
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'Condition', start)
        gate = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Condition'})
        workflow.save_stage_settings(definition, gate, {'title': 'بررسی نوع ارسال', 'condition_version': 2,
            'combine': 'All', 'conditions': [{'id': 'special', 'source_kind': 'Original', 'source_stage': '',
                'source_field': 'note', 'field_type': 'Text', 'operator': 'Equals', 'value': 'ویژه'}]})
        for result in (True, False):
            workflow.add_condition_branch(definition, gate, 'End', result)
        workflow.set_workflow_status(definition, 'Active')
        return definition

    def test_shared_form_uses_one_primary_route_and_retry_never_duplicates(self):
        conditional = self.conditional_route()
        frappe.set_user(EMPLOYEE_USER)
        key = uuid4().hex
        special = forms.submit_form(self.source['name'], self.source['revision'], 'ارسال ویژه', {'note': 'ویژه'}, key)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', special['workflow_instance'], 'workflow_definition'), conditional)
        replay = forms.submit_form(self.source['name'], self.source['revision'], 'ارسال ویژه', {'note': 'ویژه'}, key)['data']
        self.assertEqual(replay['name'], special['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {'reference_doctype': 'ASOUD Form Entry',
            'reference_name': special['name']}), 1)
        ordinary = forms.submit_form(self.source['name'], self.source['revision'], 'ارسال عادی', {'note': 'عادی'}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', ordinary['workflow_instance'], 'workflow_definition'), self.definition)

    def test_overlapping_conditions_report_conflict_and_create_nothing(self):
        self.conditional_route()
        self.conditional_route()
        before = frappe.db.count('ASOUD Form Entry')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            forms.submit_form(self.source['name'], self.source['revision'], 'ارسال مبهم', {'note': 'ویژه'}, uuid4().hex)
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_atomic_creation_rolls_back_on_invalid_start(self):
        before = frappe.db.count('ASOUD Workflow Definition')
        with self.assertRaises(frappe.ValidationError):
            workflow.create_workflow_draft('پیش‌نویس نامعتبر', 'HR', 'ASOUD Workflow Request', company=self.company,
                start_settings={'trigger_type': 'Document Event', 'submission_source':
                    {'form': self.source['name'], 'revision': 'missing-revision'}, 'initiator_roles': []})
        self.assertEqual(frappe.db.count('ASOUD Workflow Definition'), before)

    def test_other_company_cannot_claim_source_or_read_its_task(self):
        definition, stages = make_definition(self.second, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, stage.name, self.config)
        # Initiator assignment requires an ordinary user; Administrator is excluded.
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'درخواست اصلی',
            {'note': 'اطلاعات'}, uuid4().hex)['data']
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': result['workflow_instance']}, 'name')
        frappe.set_user(EMPLOYEE_B_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.get_workflow_task(task)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.start_workflow_instance(self.definition, 'تلاش نامجاز', 'ASOUD Form Entry', result['name'])

    def test_document_workflow_keeps_one_native_draft_and_original_entry_reference(self):
        from frappe.utils import nowdate

        from asoud_erp.integration_tests.fixtures import abbr

        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        document = {'kind': 'Document', 'title': 'سند حسابداری آزمایشی', 'target': 'Journal Entry',
            'sections': [{'id': 'main', 'title': 'سند', 'fields': [
                {'key': 'date', 'label': 'تاریخ', 'type': 'Date', 'native_key': 'posting_date'},
                {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'native_key': 'accounts', 'columns': [
                    {'key': 'account', 'label': 'حساب', 'type': 'Link', 'source': 'Account', 'native_key': 'account'},
                    {'key': 'debit', 'label': 'بدهکار', 'type': 'Money', 'native_key': 'debit_in_account_currency'},
                    {'key': 'credit', 'label': 'بستانکار', 'type': 'Money', 'native_key': 'credit_in_account_currency'}]}]}]}
        saved = forms.save_form(self.company, document, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        source = forms.get_form(saved['name'])['data']
        workflow.save_stage_settings(definition, stage.name, {'title': 'بررسی سند',
            'activity_type': 'Review', 'assignment_type': 'Initiator',
            'submission_source': {'form': source['name'], 'revision': source['revision']}})
        equity = frappe.get_all('Account', filters={'company': self.company, 'root_type': 'Equity',
            'is_group': 0}, pluck='name', limit_page_length=1)[0]
        before = frappe.db.count('Journal Entry')
        # The initiator must also have native Journal Entry create/read permissions.
        frappe.set_user(ACCOUNTANT_USER)
        result = forms.submit_form(source['name'], source['revision'], 'ثبت سند اصلی', {
            'date': nowdate(), 'rows': [{'account': f'Cash - {abbr()}', 'debit': 100, 'credit': 0},
                {'account': equity, 'debit': 0, 'credit': 100}]}, uuid4().hex)['data']
        self.assertEqual(result['reference_doctype'], 'Journal Entry')
        self.assertEqual(frappe.db.count('Journal Entry'), before + 1)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'],
            'reference_name'), result['name'])
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': result['workflow_instance']}, 'name')
        detail = workflow_runtime.get_workflow_task(task)['data']
        self.assertEqual(len(detail['submitted_form']['values']['rows']), 2)
        workflow_runtime.complete_workflow_task(task, 'Complete', response={})
        self.assertEqual(frappe.db.count('Journal Entry'), before + 1)
        self.assertEqual(frappe.db.get_value('Journal Entry', result['reference_name'], 'docstatus'), 0)
