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
        self.assertEqual({row['kind'] for row in forms.execution_kinds()['data']},
                         {'employee_advance', 'attendance_correction', 'asset_movement', 'shift_request', 'exit',
                          'training_enrollment'})
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


class TestRegisteredFormExecution(APITestCase):
    def setUp(self):
        super().setUp()
        self.token = frappe.generate_hash(length=10)
        self.user = frappe.get_doc({
            'doctype': 'User', 'email': self.token + '@example.test', 'first_name': 'درخواست‌کننده',
            'send_welcome_email': 0, 'roles': [{'role': 'Employee'}],
        }).insert().name
        self.employee = frappe.get_doc({
            'doctype': 'Employee', 'first_name': 'درخواست‌کننده', 'company': self.company,
            'user_id': self.user, 'gender': 'Male', 'date_of_birth': '1990-01-01',
            'date_of_joining': '2020-01-01', 'status': 'Active', 'create_user_permission': 0,
            'reports_to': self.records['approver'],
        }).insert().name

    def approve_form(self, kind, fields, values):
        definition, _ = make_definition(self.company, fields=[])
        schema = {'kind': 'Request', 'title': 'درخواست اجرای نهایی', 'workflow': definition,
                  'execution': {'kind': kind}, 'sections': [
                      {'id': 'main', 'title': 'اصلی', 'fields': fields}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        entry = forms.submit_form(saved['name'], revision, 'اجرای نهایی', values,
                                  frappe.generate_hash(length=24))['data']
        request = workflow_request.get_request(entry['reference_name'])['data']
        self.assertNotEqual(request['native']['status'], 'Created')
        task = open_task(request['workflow_instance'])
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, 'Approve')
        frappe.set_user('Administrator')
        approved = workflow_request.get_request(request['name'])['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', request['workflow_instance'], 'status'),
                         'Completed')
        return approved

    def attendance(self, kind):
        from frappe.utils import nowdate

        return self.approve_form('attendance_correction', [
            {'key': 'day', 'label': 'تاریخ', 'type': 'Date', 'execution_key': 'date'},
            {'key': 'correction', 'label': 'نوع اصلاح', 'type': 'Select', 'execution_key': 'kind',
             'options': [{'id': kind, 'label': 'اصلاح تردد'}]},
            {'key': 'clock', 'label': 'ورود', 'type': 'Time', 'execution_key': 'in_time'},
        ], {'day': nowdate(), 'correction': kind, 'clock': '08:12:34'})

    def test_attendance_other_notifies_and_is_terminal(self):
        from asoud_erp.services.form_execution.attendance_correction import REVIEW_REASONS
        from asoud_erp.services.request_native_documents import dispatch

        hr = frappe.get_doc({
            'doctype': 'User', 'email': 'hr-' + self.token + '@example.test', 'first_name': 'منابع انسانی',
            'send_welcome_email': 0, 'roles': [{'role': 'HR Manager'}],
        }).insert().name
        before = frappe.db.count('Employee Checkin', {'employee': self.employee})
        request = self.attendance('other')
        reason = REVIEW_REASONS['other']
        self.assertEqual(request['native']['status'], 'Needs Review')
        self.assertEqual(request['native']['error'], reason)
        self.assertEqual(request['execution']['state'], 'needs_review')
        self.assertEqual(request['execution']['label'], 'نیازمند بررسی')
        self.assertEqual(request['execution']['error'], reason)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Request', request['name'], 'native_error'), reason)
        filters = {'document_type': 'ASOUD Workflow Instance', 'document_name': request['workflow_instance'],
                   'email_content': reason}
        logs = frappe.get_all('Notification Log', filters=filters, fields=['for_user', 'email_content'])
        for user in (self.user, hr):
            self.assertEqual([row.email_content for row in logs if row.for_user == user], [reason])
        self.assertEqual(frappe.db.count('Employee Checkin', {'employee': self.employee}), before)
        # Previously stored review results are normalized without changing their reason.
        from asoud_erp.patches.v0_15_3.normalize_native_review_status import execute

        frappe.db.set_value('ASOUD Workflow Request', request['name'], 'native_status', 'needs_review')
        execute()
        execute()
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Request', request['name'],
                                           ['native_status', 'native_error']), ('Needs Review', reason))
        with patch.object(EXECUTORS['attendance_correction'], 'apply',
                          side_effect=AssertionError('اجرای تکراری')) as apply:
            dispatch(frappe.get_doc('ASOUD Workflow Request', request['name']))
            apply.assert_not_called()
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Request', request['name'], 'native_status'),
                         'Needs Review')
        self.assertEqual(frappe.db.count('Notification Log', filters), len(logs))
        self.assertEqual(frappe.db.count('Employee Checkin', {'employee': self.employee}), before)
        frappe.set_user(self.user)
        masked = workflow_request.get_request(request['name'])['data']
        self.assertEqual(masked['execution']['state'], 'needs_review')
        self.assertEqual(masked['execution']['error'], '')
        self.assertEqual(masked['native']['error'], '')

    def test_attendance_missing_entry_creates_native_checkin(self):
        from frappe.utils import nowdate

        frappe.db.set_single_value('HR Settings', 'allow_geolocation_tracking', 0)
        request = self.attendance('missing_entry')
        self.assertEqual(request['native']['status'], 'Created', request['native']['error'])
        doc = frappe.get_doc(request['native']['doctype'], request['native']['name'])
        self.assertEqual((doc.doctype, doc.employee, doc.log_type, str(doc.time), doc.docstatus),
                         ('Employee Checkin', self.employee, 'IN', nowdate() + ' 08:12:34', 0))

    def test_employee_advance_creates_native_draft(self):
        from frappe.utils import nowdate

        account = frappe.db.get_value('Company', self.company, 'default_employee_advance_account')
        request = self.approve_form('employee_advance', [
            {'key': 'asked', 'label': 'مبلغ', 'type': 'Money', 'execution_key': 'amount'},
            {'key': 'why', 'label': 'شرح', 'type': 'LongText', 'execution_key': 'purpose'},
            {'key': 'repay', 'label': 'بازپرداخت', 'type': 'Checkbox', 'execution_key': 'repay_from_salary'},
        ], {'asked': 1250, 'why': 'هزینه ضروری', 'repay': True})
        self.assertEqual(request['native']['status'], 'Created', request['native']['error'])
        doc = frappe.get_doc(request['native']['doctype'], request['native']['name'])
        self.assertEqual((doc.doctype, doc.employee, doc.company, doc.docstatus, doc.advance_amount),
                         ('Employee Advance', self.employee, self.company, 0, 1250))
        self.assertEqual((doc.purpose, str(doc.posting_date), doc.advance_account,
                          doc.repay_unclaimed_amount_from_salary), ('هزینه ضروری', nowdate(), account, 1))

    def test_asset_issue_creates_native_draft(self):
        from frappe.utils import add_days, nowdate

        location = frappe.get_doc({'doctype': 'Location', 'location_name': self.token}).insert().name
        account = frappe.db.get_value('Account', {'company': self.company, 'is_group': 0,
                                                   'account_type': 'Fixed Asset'}, 'name')
        category = frappe.get_doc({'doctype': 'Asset Category', 'asset_category_name': self.token,
                                   'accounts': [{'company_name': self.company,
                                                 'fixed_asset_account': account}]}).insert().name
        item = frappe.get_doc({'doctype': 'Item', 'item_code': self.token, 'is_fixed_asset': 1,
                               'is_stock_item': 0, 'stock_uom': 'Nos', 'asset_category': category,
                               'item_group': frappe.db.get_value('Item Group', {'is_group': 0}, 'name')}).insert()
        asset = frappe.get_doc({'doctype': 'Asset', 'asset_name': self.token, 'item_code': item.name,
                                'company': self.company, 'location': location, 'is_existing_asset': 1,
                                'custodian': self.employee, 'purchase_date': add_days(nowdate(), -30),
                                'available_for_use_date': add_days(nowdate(), -30),
                                'gross_purchase_amount': 100, 'asset_quantity': 1}).insert()
        asset.submit()
        request = self.approve_form('asset_movement', [
            {'key': 'equipment', 'label': 'تجهیز', 'type': 'Link', 'source': 'Asset', 'execution_key': 'asset'},
            {'key': 'way', 'label': 'جهت', 'type': 'Select', 'execution_key': 'direction',
             'options': [{'id': 'issue', 'label': 'تحویل'}]},
        ], {'equipment': asset.name, 'way': 'issue'})
        self.assertEqual(request['native']['status'], 'Created', request['native']['error'])
        doc = frappe.get_doc(request['native']['doctype'], request['native']['name'])
        self.assertEqual((doc.doctype, doc.company, doc.docstatus, doc.purpose),
                         ('Asset Movement', self.company, 0, 'Issue'))
        self.assertEqual((doc.reference_doctype, doc.reference_name), ('ASOUD Workflow Request', request['name']))
        self.assertEqual((doc.assets[0].asset, doc.assets[0].to_employee, doc.assets[0].target_location),
                         (asset.name, self.employee, location))

    def test_shift_request_creates_native_draft(self):
        frappe.db.set_value('Employee', self.employee, 'shift_request_approver', 'Administrator')
        shift = frappe.get_doc({'doctype': 'Shift Type', 'name': self.token,
                               'start_time': '08:00:00', 'end_time': '16:00:00'}).insert()
        request = self.approve_form('shift_request', [
            {'key': 'mode', 'label': 'نوع', 'type': 'Select', 'execution_key': 'kind',
             'options': [{'id': 'self_change', 'label': 'تغییر شیفت خودم'}]},
            {'key': 'day', 'label': 'شروع', 'type': 'Date', 'execution_key': 'from_date'},
            {'key': 'proposed', 'label': 'شیفت', 'type': 'Link', 'source': 'Shift Type',
             'execution_key': 'shift_type'},
        ], {'mode': 'self_change', 'day': '2030-01-01', 'proposed': shift.name})
        self.assertEqual(request['native']['status'], 'Created', request['native']['error'])
        doc = frappe.get_doc(request['native']['doctype'], request['native']['name'])
        self.assertEqual((doc.employee, doc.shift_type, doc.docstatus, doc.status),
                         (self.employee, shift.name, 0, 'Draft'))

    def test_exit_creates_settlement_drafts_and_blocks_second_submit(self):
        from asoud_erp.services.form_execution.exit import DUPLICATE_ERROR

        fields = [{'key': 'last', 'label': 'آخرین روز', 'type': 'Date', 'execution_key': 'last_working_day'},
                  {'key': 'why', 'label': 'علت', 'type': 'Text', 'execution_key': 'reason'}]
        values = {'last': '2030-02-01', 'why': 'استعفا'}
        request = self.approve_form('exit', fields, values)
        self.assertEqual(request['native']['status'], 'Created', request['native']['error'])
        self.assertEqual((request['native']['doctype'], frappe.db.get_value(
            'Exit Interview', request['native']['name'], 'docstatus')), ('Exit Interview', 0))
        statement = frappe.get_doc('Full and Final Statement', {'employee': self.employee})
        self.assertEqual((statement.docstatus, str(statement.relieving_date)), (0, '2030-02-01'))
        self.assertEqual(str(frappe.db.get_value('Employee', self.employee, 'relieving_date')), '2030-02-01')
        with self.assertRaisesRegex(frappe.ValidationError, DUPLICATE_ERROR):
            self.approve_form('exit', fields, values)
