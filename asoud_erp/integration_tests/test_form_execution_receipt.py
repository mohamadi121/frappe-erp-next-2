"""Receipt confirmation of issued equipment (N6) with real Asset, Asset Movement and task rows."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import request_followup, workflow_runtime
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.services import request_followup_runtime as runtime
from asoud_erp.services.form_execution.asset_movement import apply
from asoud_erp.services.request_native_documents import dispatch

CANCELLED = 'جابه‌جایی این تجهیز لغو شده است و دریافت آن قابل تأیید نیست.'


def make_user(suffix, role='Employee'):
    return frappe.get_doc(dict(doctype='User', email=f'{suffix}@example.com', first_name='Receipt',
        send_welcome_email=0, roles=[dict(role=role)])).insert().name


def make_employee(user, company):
    return frappe.get_doc(dict(doctype='Employee', first_name='Receipt', company=company,
        user_id=user, status='Active', gender='Male', date_of_birth='1990-01-01',
        date_of_joining='2020-01-01', create_user_permission=0)).insert().name


class TestReceiptConfirmation(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        self.suffix = frappe.generate_hash(length=8)
        self.company = frappe.get_doc(dict(doctype='Company', company_name='Receipt ' + self.suffix,
            abbr=self.suffix, default_currency='USD', country='United States',
            chart_of_accounts='Standard')).insert().name
        self.other_company = frappe.get_all('Company', filters={'name': ['!=', self.company]},
                                            pluck='name', limit=1)[0]
        self.user = make_user('r1' + self.suffix)
        self.employee = make_employee(self.user, self.company)
        self.colleague = make_user('r2' + self.suffix)
        make_employee(self.colleague, self.company)
        self.stranger = make_user('r3' + self.suffix)
        make_employee(self.stranger, self.other_company)
        self.no_employee = make_user('r4' + self.suffix)
        self.hr = make_user('r5' + self.suffix, 'HR Manager')
        make_employee(self.hr, self.company)
        self.foreign_hr = make_user('r6' + self.suffix, 'HR Manager')
        make_employee(self.foreign_hr, self.other_company)
        for manager, company in ((self.hr, self.company), (self.foreign_hr, self.other_company)):
            frappe.get_doc(dict(doctype='User Permission', user=manager, allow='Company', for_value=company,
                                apply_to_all_doctypes=1)).insert()
        self.location = frappe.get_doc(dict(doctype='Location', location_name='Receipt ' + self.suffix)).insert().name
        account = frappe.get_all('Account', filters=dict(company=self.company, is_group=0,
            account_type='Fixed Asset'), pluck='name', limit=1)[0]
        category = frappe.get_doc(dict(doctype='Asset Category', asset_category_name='Receipt ' + self.suffix,
            accounts=[dict(company_name=self.company, fixed_asset_account=account)])).insert().name
        item = frappe.get_doc(dict(doctype='Item', item_code='Receipt ' + self.suffix,
            item_group=frappe.get_all('Item Group', filters={'is_group': 0}, pluck='name', limit=1)[0],
            stock_uom='Nos', is_fixed_asset=1, is_stock_item=0, asset_category=category)).insert().name
        self.asset = frappe.get_doc(dict(doctype='Asset', asset_name='لپ‌تاپ ' + self.suffix, item_code=item,
            company=self.company, location=self.location, is_existing_asset=1,
            purchase_date=add_days(nowdate(), -30), available_for_use_date=add_days(nowdate(), -30),
            gross_purchase_amount=100, asset_quantity=1)).insert()
        self.asset.submit()
        self.definition, _ = make_definition(self.company, token='rc' + self.suffix)
        self.instance = frappe.get_doc(dict(doctype='ASOUD Workflow Instance', workflow_definition=self.definition,
            subject='تجهیزات', status='Completed', started_by=self.user)).insert()
        self.request = frappe.get_doc(dict(doctype='ASOUD Workflow Request', company=self.company,
            workflow_definition=self.definition, workflow_instance=self.instance.name,
            request_type='تجهیزات', subject='تجهیزات', status='Completed')).insert()
        self.request.db_set('owner', self.user)
        self.params = dict(asset=self.asset.name, direction='Issue', date=nowdate(), note='تحویل')

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()

    def issue(self):
        """Run the approval dispatcher the way the workflow does and return the open task and movement."""
        with patch('asoud_erp.services.form_execution.runtime.execute',
                   lambda request: apply(request, self.params)):
            dispatch(frappe.get_doc('ASOUD Workflow Request', self.request.name))
        row = frappe.db.get_value('ASOUD Workflow Request', self.request.name,
                                  ['native_status', 'native_name'], as_dict=True)
        self.assertEqual(row.native_status, 'Created')
        task = frappe.get_all('ASOUD Workflow Task', filters={'workflow_instance': self.instance.name},
                              fields=['name', 'status', 'assigned_to', 'task_title', 'workflow_stage',
                                      'draft_json'], limit_page_length=0)
        return task, row.native_name

    def open_one(self):
        tasks, movement = self.issue()
        self.assertEqual(len(tasks), 1)
        return tasks[0].name, movement

    def as_user(self, user, method, *args):
        frappe.set_user(user)
        try:
            return method(*args)
        finally:
            frappe.set_user('Administrator')

    def assert_refused(self, user, error, message, method=None, *args):
        with self.assertRaisesRegex(error, message):
            self.as_user(user, method or request_followup.confirm_receipt, *args)

    # ------------------------------------------------------------------ creation

    def test_dispatch_creates_one_requester_task_for_issue_only(self):
        tasks, movement = self.issue()
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        stage = frappe.db.get_value('ASOUD Workflow Stage', task.workflow_stage, 'stage_type')
        self.assertEqual((task.status, task.assigned_to, stage), ('Open', self.user, 'End'))
        self.assertEqual(task.task_title, 'تأیید دریافت تجهیز: ' + self.asset.asset_name)
        self.assertEqual(json.loads(task.draft_json)['followup'], {
            'kind': 'confirm_receipt', 'doctype': 'Asset Movement', 'name': movement,
            'subject': self.asset.asset_name})
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 0)
        # A repeated dispatch or create call never makes a second task.
        runtime.create_followup(frappe.get_doc('ASOUD Workflow Request', self.request.name),
                        {'kind': 'confirm_receipt', 'doctype': 'Asset Movement', 'name': movement,
                         'subject': self.asset.asset_name, 'assignee': self.user})
        self.assertEqual(frappe.db.count('ASOUD Workflow Task', {'workflow_instance': self.instance.name}), 1)

    def test_receipt_direction_has_no_followup(self):
        frappe.db.set_value('Asset', self.asset.name, 'custodian', self.employee)
        self.params['direction'] = 'Receipt'
        result = apply(self.request, self.params)
        self.assertIsNone(result.followup)

    def test_task_is_listed_and_detailed_for_the_requester_only(self):
        task, movement = self.open_one()
        listed = self.as_user(self.user, workflow_runtime.list_my_workflow_tasks)['data']
        self.assertIn(task, [row['name'] for row in listed])
        self.assertEqual({row['name']: row['followup'] for row in listed}[task], 'confirm_receipt')
        plain = frappe.get_doc(dict(doctype='ASOUD Workflow Task', workflow_instance=self.instance.name,
            workflow_stage=frappe.db.get_value('ASOUD Workflow Task', task, 'workflow_stage'),
            task_title='عادی', assigned_to=self.user, status='Open',
            draft_json=json.dumps({'followup': 'x'}))).insert()
        listed = self.as_user(self.user, workflow_runtime.list_my_workflow_tasks)['data']
        self.assertIsNone({row['name']: row['followup'] for row in listed}[plain.name])
        self.assertNotIn(task, [row['name'] for row in
                                self.as_user(self.colleague, workflow_runtime.list_my_workflow_tasks)['data']])
        detail = self.as_user(self.user, workflow_runtime.get_workflow_task, task)['data']
        self.assertEqual(detail['stage_type'], 'User Task')
        self.assertEqual(detail['config']['activity_type'], 'ConfirmReceipt')
        self.assertTrue(detail['config']['allow_reject'])
        self.assertEqual(detail['document']['doctype'], 'Asset Movement')
        self.assertEqual(detail['document']['name'], movement)
        values = {row['key']: row['value'] for row in detail['document']['values']}
        self.assertEqual(values['asset'], self.asset.asset_name)
        self.assertEqual(values['target_location'], self.location)
        self.assertEqual(values['movement_status'], 'پیش‌نویس')
        self.assertEqual(detail['request_name'], self.request.name)
        self.assertEqual(detail['draft'], {})
        with self.assertRaises(frappe.PermissionError):
            self.as_user(self.colleague, workflow_runtime.get_workflow_task, task)

    def test_generic_task_endpoints_refuse_the_receipt_task(self):
        task, movement = self.open_one()
        for method, args in ((workflow_runtime.complete_workflow_task, (task, 'Complete')),
                             (workflow_runtime.save_workflow_task_draft, (task, '{"followup": {}}'))):
            self.assert_refused(self.user, frappe.PermissionError,
                                'این وظیفه فقط با تأیید یا عدم دریافت تجهیز قابل اقدام است.', method, *args)
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 0)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')

    # ------------------------------------------------------------------ confirm

    def test_requester_confirms_and_becomes_custodian_once(self):
        task, movement = self.open_one()
        response = self.as_user(self.user, request_followup.confirm_receipt, task)['data']
        self.assertEqual(response, {'task': task, 'status': 'Completed', 'movement': {
            'doctype': 'Asset Movement', 'name': movement, 'docstatus': 1}})
        self.assertEqual(frappe.db.get_value('Asset', self.asset.name, 'custodian'), self.employee)
        row = frappe.db.get_value('ASOUD Workflow Task', task, ['status', 'completed_on', 'action'], as_dict=True)
        self.assertEqual(row.status, 'Completed')
        self.assertTrue(row.completed_on)
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_task': task, 'actor': self.user}), 1)
        self.assertEqual(frappe.session.user, 'Administrator')
        self.assert_refused(self.user, frappe.ValidationError, 'دریافت این تجهیز قبلاً تأیید شده است.',
                            request_followup.confirm_receipt, task)
        self.assert_refused(self.user, frappe.ValidationError, 'دریافت این تجهیز قبلاً تأیید شده است.',
                            request_followup.reject_receipt, task, 'دیر')
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 1)

    def test_only_the_requester_with_an_employee_in_the_company_can_confirm(self):
        task, movement = self.open_one()
        message = 'فقط درخواست‌دهنده می‌تواند دریافت تجهیز را تأیید کند.'
        for user in (self.colleague, self.stranger, self.no_employee, self.hr, 'Administrator'):
            self.assert_refused(user, frappe.PermissionError, message, request_followup.confirm_receipt, task)
            self.assert_refused(user, frappe.PermissionError, message, request_followup.reject_receipt, task, 'x')
        # The assignee loses the Employee record of the company: refused as well.
        frappe.db.set_value('Employee', self.employee, 'status', 'Inactive')
        self.assert_refused(self.user, frappe.PermissionError, message, request_followup.confirm_receipt, task)
        frappe.db.set_value('Employee', self.employee, 'status', 'Active')
        # A task re-assigned to somebody who does not own the request is refused too.
        frappe.db.set_value('ASOUD Workflow Task', task, 'assigned_to', self.colleague)
        self.assert_refused(self.colleague, frappe.PermissionError, message, request_followup.confirm_receipt, task)
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 0)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')

    def test_unknown_and_foreign_tasks_get_persian_errors(self):
        self.assert_refused(self.user, frappe.ValidationError, 'وظیفه تأیید دریافت یافت نشد.',
                            request_followup.confirm_receipt, 'missing-' + self.suffix)
        self.assert_refused(self.user, frappe.ValidationError, 'وظیفه تأیید دریافت یافت نشد.',
                            request_followup.confirm_receipt, '')
        plain = frappe.get_doc(dict(doctype='ASOUD Workflow Task', workflow_instance=self.instance.name,
            workflow_stage=frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': self.definition,
                                                                       'stage_type': 'End'}),
            task_title='عادی', assigned_to=self.user, status='Open')).insert()
        self.assert_refused(self.user, frappe.ValidationError, 'این وظیفه تأیید دریافت تجهیز نیست.',
                            request_followup.confirm_receipt, plain.name)

    def test_marker_forged_in_a_draft_cannot_confirm_a_movement_of_another_request(self):
        task, movement = self.open_one()
        other = frappe.get_doc(dict(doctype='ASOUD Workflow Request', company=self.company,
            workflow_definition=self.definition, request_type='تجهیزات', subject='دیگر', status='Completed')).insert()
        other.db_set('owner', self.user)
        frappe.db.set_value('Asset Movement', movement, 'reference_name', other.name)
        self.assert_refused(self.user, frappe.ValidationError, 'جابه‌جایی تجهیز به این درخواست مربوط نیست.',
                            request_followup.confirm_receipt, task)
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 0)

    def test_cancelled_movement_cancels_the_task_and_confirmation_is_refused(self):
        task, movement = self.open_one()
        doc = frappe.get_doc('Asset Movement', movement)
        doc.submit()
        doc.cancel()
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Cancelled')
        self.assert_refused(self.user, frappe.ValidationError, CANCELLED, request_followup.confirm_receipt, task)
        # Even if the task was still open, a cancelled movement is refused with the same sentence.
        frappe.db.set_value('ASOUD Workflow Task', task, 'status', 'Open')
        self.assert_refused(self.user, frappe.ValidationError, CANCELLED, request_followup.confirm_receipt, task)
        self.assert_refused(self.user, frappe.ValidationError, CANCELLED, request_followup.reject_receipt, task, 'x')

    def test_deleted_draft_movement_cancels_the_task(self):
        task, movement = self.open_one()
        frappe.delete_doc('Asset Movement', movement, force=True)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Cancelled')
        self.assert_refused(self.user, frappe.ValidationError, CANCELLED, request_followup.confirm_receipt, task)

    def test_already_submitted_movement_with_open_task(self):
        task, movement = self.open_one()
        frappe.get_doc('Asset Movement', movement).submit()
        self.assert_refused(self.user, frappe.ValidationError, 'این جابه‌جایی قبلاً تأیید شده است.',
                            request_followup.confirm_receipt, task)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')

    def test_erpnext_refusal_is_persian_and_changes_nothing(self):
        task, movement = self.open_one()
        later = frappe.copy_doc(frappe.get_doc('Asset Movement', movement))
        later.transaction_date = add_days(nowdate(), 1) + ' 00:00:00'
        later.insert().submit()
        self.assert_refused(self.user, frappe.ValidationError,
                            'تأیید دریافت انجام نشد؛ وضعیت تجهیز پس از ثبت درخواست تغییر کرده است.',
                            request_followup.confirm_receipt, task)
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 0)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')

    # ------------------------------------------------------------------ reject

    def test_reject_needs_a_reason_keeps_the_draft_and_notifies_the_managers_of_the_company(self):
        task, movement = self.open_one()
        for reason in (None, '', '   '):
            self.assert_refused(self.user, frappe.ValidationError, 'علت عدم دریافت را بنویسید.',
                                request_followup.reject_receipt, task, reason)
        self.assert_refused(self.user, frappe.ValidationError, 'نباید بیشتر از ۵۰۰ نویسه باشد',
                            request_followup.reject_receipt, task, 'ب' * 501)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')
        response = self.as_user(self.user, request_followup.reject_receipt, task, ' تجهیز تحویل نشد <b>x</b> ')['data']
        self.assertEqual(response, {'task': task, 'status': 'Rejected', 'movement': {
            'doctype': 'Asset Movement', 'name': movement, 'docstatus': 0}})
        row = frappe.db.get_value('ASOUD Workflow Task', task, ['status', 'comment', 'completed_on'], as_dict=True)
        self.assertEqual((row.status, row.comment), ('Rejected', 'تجهیز تحویل نشد <b>x</b>'))
        self.assertTrue(row.completed_on)
        self.assertEqual(frappe.db.get_value('Asset Movement', movement, 'docstatus'), 0)
        self.assertFalse(frappe.db.get_value('Asset', self.asset.name, 'custodian'))
        comment = frappe.db.get_value('Comment', dict(reference_doctype='Asset Movement', reference_name=movement,
            comment_type='Comment'), 'content')
        self.assertIn('تجهیز تحویل نشد &lt;b&gt;x&lt;/b&gt;', comment)
        notified = set(frappe.get_all('Notification Log', filters={
            'document_type': 'ASOUD Workflow Instance', 'document_name': self.instance.name,
            'subject': ['like', '%عدم دریافت%']}, pluck='for_user'))
        self.assertIn(self.hr, notified)
        self.assertNotIn(self.foreign_hr, notified)
        self.assertNotIn(self.user, notified)
        self.assert_refused(self.user, frappe.ValidationError, 'عدم دریافت این تجهیز قبلاً ثبت شده است.',
                            request_followup.confirm_receipt, task)
        self.assert_refused(self.user, frappe.ValidationError, 'عدم دریافت این تجهیز قبلاً ثبت شده است.',
                            request_followup.reject_receipt, task, 'دوباره')
