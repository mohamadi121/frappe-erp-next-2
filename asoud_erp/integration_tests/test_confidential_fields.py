"""Confidential form fields never leave the request through any output (real rows, restricted users)."""

import json
import uuid
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1 import (
    document_templates,
    forms,
    workflow,
    workflow_request,
    workflow_runtime,
)
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    ITEM,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition, native_workflow
from asoud_erp.integration_tests.request_helpers import act
from asoud_erp.integration_tests.service_identity import patch_service_conf
from asoud_erp.services.form_execution import EXECUTORS, Result
from asoud_erp.services.session_scope import as_administrator

SECRET = 'درمان بیماری خاص'
MASK = 'محرمانه'
FIELDS = [
    {'key': 'reason', 'label': 'دلیل', 'type': 'Long Text', 'max_length': 2000},
    {'key': 'amount', 'label': 'مبلغ', 'type': 'Currency'},
]


def form_schema(definition, *, execution=None, sensitive=True):
    schema = {'kind': 'Request', 'title': 'درخواست محرمانه', 'workflow': definition, 'sections': [{
        'id': 'main', 'title': 'اصلی', 'fields': [
            {'key': 'why', 'label': 'علت', 'type': 'LongText', 'workflow_key': 'reason',
             'sensitive': sensitive, **({'execution_key': 'purpose'} if execution else {})},
            {'key': 'sum', 'label': 'مبلغ', 'type': 'Money', 'workflow_key': 'amount'}]}]}
    if execution:
        schema['execution'] = {'kind': execution}
    return schema


class Executor:
    KIND = 'confidential_test'
    LABEL = 'اجرای آزمایشی'
    PARAMETERS = {'purpose': {'label': 'شرح', 'types': ['Text', 'LongText'], 'required': True}}

    def build(self, params, ctx):
        return {'doctype': 'ToDo', 'description': str(params['purpose'])}

    def apply(self, request, params):
        with as_administrator():
            doc = frappe.get_doc(self.build(params, {})).insert(ignore_permissions=True)
        return Result(status='Created', doctype=doc.doctype, name=doc.name)


class FormRequestCase(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1, fields=FIELDS)
        self.manager = self.user_with_roles('Accounts Manager')

    def user_with_roles(self, *roles):
        email = 'conf-' + uuid4().hex[:10] + '@example.test'
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'محدود', 'send_welcome_email': 0,
                        'user_type': 'System User', 'roles': [{'role': role} for role in roles]}
                       ).insert(ignore_permissions=True)
        return email

    def submit(self, *, execution=None, sensitive=True, values=None):
        frappe.set_user('Administrator')
        saved = forms.save_form(self.company, form_schema(self.definition, execution=execution,
                                                          sensitive=sensitive),
                                client_id=frappe.generate_hash(length=24))['data']
        published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
        frappe.set_user(EMPLOYEE_USER)
        entry = forms.submit_form(saved['name'], published['active_revision'], 'درخواست محرمانه',
                                  values or {'why': SECRET, 'sum': 10}, frappe.generate_hash(length=24))['data']
        frappe.set_user('Administrator')
        return entry['reference_name']

    def detail_as(self, user, name):
        frappe.set_user(user)
        try:
            return workflow_request._detail(frappe.get_doc('ASOUD Workflow Request', name))
        finally:
            frappe.set_user('Administrator')


class TestDetailAndSearch(FormRequestCase):
    def test_form_flag_masks_the_value_for_a_user_without_a_task(self):
        name = self.submit()
        self.assertEqual(self.detail_as(ACCOUNTANT_USER, name)['values']['reason'], MASK)
        self.assertEqual(self.detail_as(self.manager, name)['values']['reason'], MASK)

    def test_owner_participant_and_hr_see_the_value(self):
        name = self.submit()
        for user in (EMPLOYEE_USER, APPROVER_USER, 'Administrator'):
            self.assertEqual(self.detail_as(user, name)['values']['reason'], SECRET, user)

    def test_http_read_by_a_restricted_user_is_refused(self):
        name = self.submit()
        for user in (ACCOUNTANT_USER, self.manager):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                workflow_request.get_request(name)

    def test_an_unflagged_field_stays_visible(self):
        name = self.submit(sensitive=False)
        self.assertEqual(self.detail_as(ACCOUNTANT_USER, name)['values']['reason'], SECRET)

    def test_search_text_leaves_out_the_items_of_a_form_flagged_table(self):
        frappe.set_user(EMPLOYEE_USER)
        definition, _stages = make_definition(self.company, approvals=1)
        with patch.object(workflow_runtime, '_notify_user'):
            request = workflow_request.create_request(
                self.company, definition, 'اقلام', 'conf-items-' + uuid4().hex[:8],
                values={'items': [{'item_code': ITEM, 'qty': 1}]})['data']
        frappe.set_user('Administrator')
        self.assertIn(ITEM, frappe.db.get_value('ASOUD Workflow Request', request['name'], 'search_text'))
        schema = {'kind': 'Request', 'sections': [{'id': 'main', 'title': 'اصلی', 'fields': [
            {'key': 'lines', 'label': 'اقلام', 'type': 'Table', 'workflow_key': 'items', 'sensitive': True,
             'columns': []}]}]}
        form = frappe.get_doc({'doctype': 'ASOUD Form', 'title': 'اقلام ' + uuid4().hex[:6],
                               'company': self.company})
        form.flags.form_service = True
        form.insert()
        revision = frappe.get_doc({'doctype': 'ASOUD Form Revision', 'form': form.name, 'version': 1,
                                   'company': self.company, 'schema_json': json.dumps(schema)})
        revision.flags.form_service = True
        revision.insert(ignore_permissions=True)
        entry = frappe.get_doc({
            'doctype': 'ASOUD Form Entry', 'form': form.name, 'revision': revision.name, 'company': self.company,
            'subject': 'اقلام', 'values_json': '{}', 'reference_doctype': 'ASOUD Workflow Request',
            'reference_name': request['name'], 'request_key': uuid.uuid4().hex, 'fingerprint': uuid.uuid4().hex})
        entry.flags.form_service = True
        entry.insert(ignore_permissions=True)
        workflow_request.refresh_search_text(request['name'])
        text = frappe.db.get_value('ASOUD Workflow Request', request['name'], 'search_text')
        self.assertNotIn(ITEM, text)
        self.assertIn(request['name'], text)


class TestActivityChange(FormRequestCase):
    def test_resubmit_activity_never_shows_a_form_flagged_value(self):
        name = self.submit()
        instance = frappe.db.get_value('ASOUD Workflow Request', name, 'workflow_instance')
        act(instance, 'Return', comment='اصلاح کنید')
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.update_request(name, values=json.dumps({'reason': 'علت تازه خصوصی', 'amount': 10}))
        change = frappe.get_all('ASOUD Workflow Activity', filters={
            'workflow_instance': instance, 'action': 'Resubmitted'}, pluck='change_json')[0]
        self.assertNotIn(SECRET, change)
        self.assertNotIn('علت تازه خصوصی', change)
        self.assertEqual(json.loads(change)['after']['reason'], MASK)
        frappe.set_user(self.manager)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.get_workflow_instance(instance)
        frappe.set_user(APPROVER_USER)
        data = workflow_runtime.get_workflow_instance(instance)['data']
        self.assertNotIn(SECRET, json.dumps(data, ensure_ascii=False, default=str))
        self.assertNotIn('علت تازه خصوصی', json.dumps(data, ensure_ascii=False, default=str))


class TestAutomaticActions(APITestCase):
    def setUp(self):
        super().setUp()
        patch_service_conf(self, self.company)
        self.token = uuid4().hex[:8]
        self.expense = frappe.get_all('Account', filters={
            'company': self.company, 'root_type': 'Expense', 'is_group': 0}, pluck='name', limit=1)[0]
        self.liability = frappe.get_all('Account', filters={
            'company': self.company, 'root_type': 'Liability', 'is_group': 0,
            'account_type': ['not in', ['Receivable', 'Payable', 'Bank', 'Cash', 'Stock']]},
            pluck='name', limit=1)[0]

    def definition(self, action_config):
        definition = frappe.get_doc({
            'doctype': 'ASOUD Workflow Definition', 'workflow_code': 'conf-' + self.token,
            'workflow_title': 'درخواست محرمانه ' + self.token, 'company': self.company, 'module_key': 'HR',
            'target_doctype': 'ASOUD Workflow Request', 'status': 'Active', 'readiness_status': 'Ready',
            'allow_user_submission': 1, 'frappe_workflow': native_workflow()}).insert()
        fields = [{'key': 'reason', 'label': 'دلیل', 'type': 'Long Text', 'max_length': 2000,
                   'sensitive': True},
                  {'key': 'amount', 'label': 'مبلغ', 'type': 'Number'}]
        configs = [('Start', {'title': 'شروع'}),
                   ('User Task', {'title': 'ثبت', 'activity_type': 'Data Entry',
                                  'assignment_type': 'Initiator', 'form_fields': fields}),
                   ('System Action', action_config),
                   ('End', {'title': 'پایان', 'outcome': 'Completed'})]
        stages = [frappe.get_doc({
            'doctype': 'ASOUD Workflow Stage', 'workflow_definition': definition.name,
            'stage_key': f'{kind}-{index}-{self.token}', 'stage_title': config['title'], 'stage_type': kind,
            'sequence_no': index + 1, 'config_json': json.dumps(config),
            'configuration_status': 'Complete'}).insert() for index, (kind, config) in enumerate(configs)]
        for first, second in zip(stages, stages[1:]):
            frappe.get_doc({'doctype': 'ASOUD Workflow Transition', 'workflow_definition': definition.name,
                            'from_stage': first.name, 'to_stage': second.name}).insert()
        return definition.name

    def submit(self, definition):
        frappe.set_user(EMPLOYEE_USER)
        request = workflow_request.create_request(
            self.company, definition, 'درخواست محرمانه', 'conf-act-' + uuid4().hex[:8],
            values={'reason': SECRET, 'amount': 5})['data']
        frappe.set_user('Administrator')
        return request

    def test_notification_text_and_activity_comment_hide_a_confidential_value(self):
        definition = self.definition({'title': 'اعلان', 'action_type': 'Send Notification',
                                      'target_roles': ['Accounts User'], 'notify_initiator': False,
                                      'message': 'علت: {{reason}} مبلغ: {{amount}}'})
        request = self.submit(definition)
        logs = frappe.get_all('Notification Log', filters={
            'for_user': ACCOUNTANT_USER, 'document_name': request['workflow_instance']},
            fields=['subject', 'email_content'])
        self.assertTrue(logs)
        for log in logs:
            self.assertNotIn(SECRET, f'{log.subject} {log.email_content}')
        self.assertIn(f'علت: {MASK} مبلغ: 5.0', ' '.join(log.email_content or '' for log in logs))
        comment = frappe.db.get_value('ASOUD Workflow Activity', {
            'workflow_instance': request['workflow_instance'], 'action': 'System Action Succeeded'}, 'comment')
        self.assertEqual(comment, f'علت: {MASK} مبلغ: 5.0')

    def test_created_document_does_not_receive_a_confidential_value(self):
        definition = self.definition({'title': 'ثبت سند', 'action_type': 'Change Status',
                                      'request_status': 'در حال ثبت'})
        template = document_templates.save_document_template(self.company, {
            'title': 'سند ' + self.token, 'module': 'Finance', 'document_type': 'Journal Entry',
            'mapping': {'posting_date': {'source': 'system', 'value': 'today'},
                        'title': {'source': 'request', 'value': 'reason'},
                        'amount': {'source': 'request', 'value': 'amount'},
                        'debit_account': {'source': 'fixed', 'value': self.expense},
                        'credit_account': {'source': 'fixed', 'value': self.liability}}},
            source_workflow=definition)['data']
        stage = frappe.db.get_value('ASOUD Workflow Stage', {
            'workflow_definition': definition, 'stage_type': 'System Action'}, 'name')
        workflow.save_stage_settings(definition, stage, {
            'title': 'ثبت سند', 'action_type': 'Create Document', 'document_template': template['name'],
            'document_remark': 'بر اساس {{RequestNo}}'})
        request = self.submit(definition)
        name = frappe.db.get_value('ASOUD Workflow Activity', {
            'workflow_instance': request['workflow_instance'], 'action': 'System Action Succeeded'},
            'reference_name')
        self.assertTrue(name)
        entry = frappe.get_doc('Journal Entry', name)
        self.assertNotIn(SECRET, json.dumps(entry.as_dict(), default=str, ensure_ascii=False))
        self.assertEqual(entry.title, MASK)


class TestExecutionCopies(FormRequestCase):
    def approve(self, name):
        instance = frappe.db.get_value('ASOUD Workflow Request', name, 'workflow_instance')
        act(instance, 'Approve')
        return workflow_request._detail(frappe.get_doc('ASOUD Workflow Request', name))

    def test_a_confidential_text_parameter_reaches_the_native_document_as_a_pointer(self):
        with patch.dict(EXECUTORS, {'confidential_test': Executor()}, clear=True):
            name = self.submit(execution='confidential_test')
            done = self.approve(name)
            self.assertEqual(done['native']['status'], 'Created', done['native'])
            text = frappe.db.get_value('ToDo', done['native']['name'], 'description')
            self.assertEqual(text, f'{MASK}؛ جزئیات در درخواست {name} است.')
            self.assertNotIn(SECRET, text)

    def test_the_same_parameter_is_copied_when_the_field_is_not_confidential(self):
        with patch.dict(EXECUTORS, {'confidential_test': Executor()}, clear=True):
            name = self.submit(execution='confidential_test', sensitive=False)
            done = self.approve(name)
            self.assertEqual(frappe.db.get_value('ToDo', done['native']['name'], 'description'), SECRET)


class TestExitCommentIsNotCopied(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        token = uuid.uuid4().hex[:8]
        self.company = frappe.get_doc({'doctype': 'Company', 'company_name': token, 'abbr': token,
            'default_currency': 'USD', 'country': 'United States'}).insert().name
        self.user = frappe.get_doc({'doctype': 'User', 'email': token + '@example.test',
            'first_name': 'کارمند', 'send_welcome_email': 0}).insert().name
        self.employee = frappe.get_doc({'doctype': 'Employee', 'first_name': 'کارمند',
            'company': self.company, 'gender': 'Male', 'date_of_birth': '1990-01-01',
            'date_of_joining': '2020-01-01', 'status': 'Active', 'user_id': self.user,
            'create_user_permission': 0}).insert().name
        definition = frappe.get_doc({'doctype': 'ASOUD Workflow Definition',
            'workflow_code': 'EX-' + token, 'workflow_title': 'تسویه', 'company': self.company,
            'module_key': 'HR', 'target_doctype': 'ASOUD Workflow Request'}).insert().name
        form = frappe.get_doc({'doctype': 'ASOUD Form', 'title': 'تسویه ' + token, 'company': self.company})
        form.flags.form_service = True
        form.insert()
        schema = {'kind': 'Request', 'execution': {'kind': 'exit'}, 'sections': [{
            'id': 'main', 'title': 'اصلی', 'fields': [
                {'key': 'day', 'label': 'روز', 'type': 'Date', 'execution_key': 'last_working_day'},
                {'key': 'why', 'label': 'علت', 'type': 'LongText', 'execution_key': 'notes',
                 'sensitive': True}]}]}
        revision = frappe.get_doc({'doctype': 'ASOUD Form Revision', 'form': form.name, 'version': 1,
                                   'company': self.company, 'schema_json': json.dumps(schema)})
        revision.flags.form_service = True
        revision.insert(ignore_permissions=True)
        self.request = frappe.get_doc({'doctype': 'ASOUD Workflow Request', 'company': self.company,
            'workflow_definition': definition, 'request_type': 'تسویه', 'subject': 'تسویه حساب',
            'requester_employee': self.employee, 'status': 'Submitted'}).insert()
        frappe.db.set_value('ASOUD Workflow Request', self.request.name, 'owner', self.user)
        entry = frappe.get_doc({'doctype': 'ASOUD Form Entry', 'form': form.name, 'revision': revision.name,
            'company': self.company, 'subject': 'تسویه',
            'values_json': json.dumps({'day': '2030-02-01', 'why': SECRET}, ensure_ascii=False),
            'reference_doctype': 'ASOUD Workflow Request', 'reference_name': self.request.name,
            'request_key': uuid.uuid4().hex, 'fingerprint': uuid.uuid4().hex})
        entry.flags.form_service = True
        entry.insert(ignore_permissions=True)
        self.request.reload()

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()
        super().tearDown()

    def test_exit_interview_comment_holds_a_pointer_not_the_notes(self):
        from asoud_erp.services.form_execution.runtime import execute

        result = execute(self.request)
        self.assertEqual(result.status, 'Created')
        contents = frappe.get_all('Comment', filters={
            'reference_doctype': 'Exit Interview', 'reference_name': result.name, 'comment_type': 'Comment'},
            pluck='content')
        self.assertEqual(contents, [f'{MASK}؛ جزئیات در درخواست {self.request.name} است.'])
