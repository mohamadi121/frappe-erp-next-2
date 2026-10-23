"""Void and reissue of an executed native document, for every executor kind, on real rows."""

import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import forms, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import open_task

REASON = 'سند به اشتباه صادر شده است.'
REQUEST = 'ASOUD Workflow Request'


class TestRequestVoid(APITestCase):
    def setUp(self):
        super().setUp()
        self.token = uuid.uuid4().hex[:10]
        self.user = self._user('req-' + self.token, 'Employee')
        self.employee = frappe.get_doc({
            'doctype': 'Employee', 'first_name': 'درخواست‌کننده', 'company': self.company,
            'user_id': self.user, 'gender': 'Male', 'date_of_birth': '1990-01-01',
            'date_of_joining': '2020-01-01', 'status': 'Active', 'create_user_permission': 0,
            'reports_to': self.records['approver']}).insert().name
        self.hr = self._user('hr-' + self.token, 'HR Manager')

    def _user(self, name, role):
        user = frappe.get_doc({'doctype': 'User', 'email': name + '@example.test', 'first_name': name,
                               'send_welcome_email': 0, 'user_type': 'System User',
                               'roles': [{'role': role}]}).insert().name
        # The role-profile hook keeps only the first role on insert; extra roles are written as HR does.
        for extra in dict.fromkeys(['Employee', role]):
            if not frappe.db.exists('Has Role', {'parent': user, 'role': extra}):
                frappe.get_doc({'doctype': 'Has Role', 'parent': user, 'parenttype': 'User',
                                'parentfield': 'roles', 'role': extra}).insert(ignore_permissions=True)
        frappe.clear_cache(user=user)
        return user

    # ------------------------------------------------------------------ helpers

    def approve_form(self, kind, fields, values):
        definition, _ = make_definition(self.company, fields=[])
        schema = {'kind': 'Request', 'title': 'درخواست ابطال', 'workflow': definition,
                  'execution': {'kind': kind}, 'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        entry = forms.submit_form(saved['name'], revision, 'اجرای نهایی', values,
                                  frappe.generate_hash(length=24))['data']
        request = workflow_request.get_request(entry['reference_name'])['data']
        task = open_task(request['workflow_instance'])
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, 'Approve')
        frappe.set_user('Administrator')
        approved = workflow_request.get_request(request['name'])['data']
        self.assertEqual(approved['native']['status'], 'Created', approved['native']['error'])
        return approved

    def advance(self):
        return self.approve_form('employee_advance', [
            {'key': 'asked', 'label': 'مبلغ', 'type': 'Money', 'execution_key': 'amount'},
            {'key': 'why', 'label': 'شرح', 'type': 'LongText', 'execution_key': 'purpose'},
        ], {'asked': 1250, 'why': 'هزینه ضروری'})

    def asset(self):
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
                                'purchase_date': add_days(nowdate(), -30),
                                'available_for_use_date': add_days(nowdate(), -30), 'custodian': self.employee,
                                'gross_purchase_amount': 100, 'asset_quantity': 1}).insert()
        asset.submit()
        return self.approve_form('asset_movement', [
            {'key': 'equipment', 'label': 'تجهیز', 'type': 'Link', 'source': 'Asset', 'execution_key': 'asset'},
            {'key': 'way', 'label': 'جهت', 'type': 'Select', 'execution_key': 'direction',
             'options': [{'id': 'issue', 'label': 'تحویل'}]},
        ], {'equipment': asset.name, 'way': 'issue'})

    def checkin(self):
        frappe.db.set_single_value('HR Settings', 'allow_geolocation_tracking', 0)
        return self.approve_form('attendance_correction', [
            {'key': 'day', 'label': 'تاریخ', 'type': 'Date', 'execution_key': 'date'},
            {'key': 'correction', 'label': 'نوع اصلاح', 'type': 'Select', 'execution_key': 'kind',
             'options': [{'id': 'missing_entry', 'label': 'فراموشی ورود'}]},
            {'key': 'clock', 'label': 'ورود', 'type': 'Time', 'execution_key': 'in_time'},
        ], {'day': nowdate(), 'correction': 'missing_entry', 'clock': '08:12:34'})

    def shift(self):
        frappe.db.set_value('Employee', self.employee, 'shift_request_approver', 'Administrator')
        shift = frappe.get_doc({'doctype': 'Shift Type', 'name': self.token,
                                'start_time': '08:00:00', 'end_time': '16:00:00'}).insert()
        return self.approve_form('shift_request', [
            {'key': 'mode', 'label': 'نوع', 'type': 'Select', 'execution_key': 'kind',
             'options': [{'id': 'self_change', 'label': 'تغییر شیفت خودم'}]},
            {'key': 'day', 'label': 'شروع', 'type': 'Date', 'execution_key': 'from_date'},
            {'key': 'proposed', 'label': 'شیفت', 'type': 'Link', 'source': 'Shift Type',
             'execution_key': 'shift_type'},
        ], {'mode': 'self_change', 'day': '2030-01-01', 'proposed': shift.name})

    def exit(self):
        return self.approve_form('exit', [
            {'key': 'last', 'label': 'آخرین روز', 'type': 'Date', 'execution_key': 'last_working_day'},
            {'key': 'why', 'label': 'علت', 'type': 'Text', 'execution_key': 'reason'},
        ], {'last': '2030-02-01', 'why': 'استعفا'})

    def training(self):
        from asoud_erp.integration_tests.test_form_execution_training import make_event

        self.event = make_event(self.company)
        return self.approve_form('training_enrollment', [
            {'key': 'course', 'label': 'دوره', 'type': 'Link', 'source': 'Training Event',
             'execution_key': 'training_event'},
        ], {'course': self.event})

    def void(self, request, reason=REASON, user=None):
        frappe.set_user(user or self.hr)
        try:
            return workflow_request.void_native_document(request['name'], reason)['data']
        finally:
            frappe.set_user('Administrator')

    def reissue(self, request, user=None):
        frappe.set_user(user or self.hr)
        try:
            return workflow_request.reissue_native_document(request['name'])['data']
        finally:
            frappe.set_user('Administrator')

    def activities(self, request, action=None):
        filters = {'workflow_instance': request['workflow_instance']}
        if action:
            filters['action'] = action
        return frappe.get_all('ASOUD Workflow Activity', filters=filters, order_by='creation asc, name asc',
                              fields=['action', 'comment', 'actor', 'created_on', 'reference_doctype',
                                      'reference_name'])

    def comments(self, doctype, name):
        return frappe.get_all('Comment', filters={'reference_doctype': doctype, 'reference_name': name,
                                                  'comment_type': 'Comment'}, pluck='content')

    def assert_voided(self, request, voided):
        self.assertEqual((voided['native']['status'], voided['execution']['state'], voided['execution']['label']),
                         ('Voided', 'voided', 'سند ابطال شد'))
        self.assertEqual(voided['native']['name'], request['native']['name'])
        row = self.activities(request, 'Voided')[0]
        self.assertEqual((row.comment, row.actor, row.reference_doctype, row.reference_name),
                         (REASON, self.hr, request['native']['doctype'], request['native']['name']))
        self.assertTrue(row.created_on)
        self.assertEqual(voided['execution']['void']['reason'], REASON)
        self.assertEqual(voided['execution']['void']['reference'], request['native']['name'])
        self.assertTrue(voided['execution']['can_reissue'])
        self.assertFalse(voided['execution']['can_void'])

    # ------------------------------------------------------------------ per executor kind

    def test_employee_advance_draft_is_marked_and_reissued_as_a_fresh_document(self):
        request = self.advance()
        old = request['native']['name']
        voided = self.void(request)
        self.assert_voided(request, voided)
        # A draft cannot be cancelled in Frappe and is never deleted: it stays, with a comment.
        self.assertEqual(frappe.db.get_value('Employee Advance', old, 'docstatus'), 0)
        self.assertEqual(len(self.comments('Employee Advance', old)), 1)
        self.assertIn(REASON, self.comments('Employee Advance', old)[0])
        reissued = self.reissue(request)
        self.assertEqual(reissued['native']['status'], 'Created')
        self.assertNotEqual(reissued['native']['name'], old)
        self.assertEqual(frappe.db.get_value('Employee Advance', reissued['native']['name'], 'advance_amount'), 1250)
        self.assertTrue(frappe.db.exists('Employee Advance', old))
        history = self.activities(request)
        self.assertEqual([(row.action, row.reference_name) for row in history if row.action in ('Voided', 'Reissued')],
                         [('Voided', old), ('Reissued', old)])
        # Idempotent: a repeat creates nothing.
        before = frappe.db.count('Employee Advance')
        again = self.reissue(request)
        self.assertEqual((again['native']['name'], frappe.db.count('Employee Advance')),
                         (reissued['native']['name'], before))
        self.assertEqual(len(self.activities(request, 'Reissued')), 1)

    def test_submitted_asset_movement_is_cancelled_not_deleted_then_reissued(self):
        request = self.asset()
        old = request['native']['name']
        frappe.get_doc('Asset Movement', old).submit()
        voided = self.void(request)
        self.assert_voided(request, voided)
        self.assertEqual(frappe.db.get_value('Asset Movement', old, 'docstatus'), 2)
        reissued = self.reissue(request)
        self.assertEqual(reissued['native']['status'], 'Created', reissued['native']['error'])
        new = reissued['native']['name']
        self.assertNotEqual(new, old)
        self.assertEqual(frappe.db.get_value('Asset Movement', new, 'docstatus'), 0)
        self.assertEqual(frappe.db.get_value('Asset Movement', old, 'docstatus'), 2)

    def test_draft_asset_movement_stays_for_hr(self):
        request = self.asset()
        old = request['native']['name']
        self.assert_voided(request, self.void(request))
        self.assertEqual(frappe.db.get_value('Asset Movement', old, 'docstatus'), 0)

    def test_checkin_is_neutralised_for_auto_attendance_never_deleted_and_reissue_reports_duplicate(self):
        request = self.checkin()
        old = request['native']['name']
        self.assert_voided(request, self.void(request))
        self.assertEqual(frappe.db.get_value('Employee Checkin', old, 'skip_auto_attendance'), 1)
        # The checkin cannot be removed, so HRMS refuses the same punch again: the reissue fails
        # with its Persian reason, keeps the old link in history and can be retried after HR acts.
        failed = self.reissue(request)
        self.assertEqual(failed['native']['status'], 'Failed')
        self.assertIn('قبلاً ثبت شده است', failed['native']['error'])
        self.assertTrue(frappe.db.exists('Employee Checkin', old))
        self.assertEqual(self.activities(request, 'Reissued')[0].reference_name, old)

    def test_shift_request_draft_is_marked_and_reissue_reports_the_overlap(self):
        request = self.shift()
        old = request['native']['name']
        self.assert_voided(request, self.void(request))
        self.assertEqual(frappe.db.get_value('Shift Request', old, 'docstatus'), 0)
        # HRMS refuses an overlapping Shift Request and the old draft is still there for HR.
        failed = self.reissue(request)
        self.assertEqual(failed['native']['status'], 'Failed')
        self.assertIn('هم‌پوشانی', failed['native']['error'])
        self.assertTrue(frappe.db.exists('Shift Request', old))

    def test_exit_voids_the_interview_and_reissue_waits_for_hr_to_handle_the_open_statement(self):
        request = self.exit()
        old = request['native']['name']
        self.assert_voided(request, self.void(request))
        self.assertTrue(frappe.db.exists('Exit Interview', old))
        failed = self.reissue(request)
        self.assertEqual(failed['native']['status'], 'Failed')
        self.assertIn('تسویه حساب باز', failed['native']['error'])
        self.assertTrue(failed['execution']['can_void'] is False)
        self.assertEqual(self.activities(request, 'Reissued')[0].reference_name, old)

    def test_training_event_is_never_cancelled(self):
        request = self.training()
        event = request['native']['name']
        self.assertEqual(event, self.event)
        frappe.get_doc('Training Event', event).submit()
        self.assert_voided(request, self.void(request))
        self.assertEqual(frappe.db.get_value('Training Event', event, 'docstatus'), 1)
        self.assertEqual(len(self.comments('Training Event', event)), 1)
        failed = self.reissue(request)
        self.assertEqual(failed['native']['status'], 'Failed')

    # ------------------------------------------------------------------ rules

    def test_reason_is_required_and_bounded(self):
        request = self.advance()
        for reason in ('', '   '):
            with self.assertRaisesRegex(frappe.ValidationError, 'دلیل ابطال سند را بنویسید'):
                self.void(request, reason)
        with self.assertRaisesRegex(frappe.ValidationError, 'حداکثر ۵۰۰'):
            self.void(request, 'ا' * 501)
        self.assertEqual(frappe.db.get_value(REQUEST, request['name'], 'native_status'), 'Created')
        self.assertFalse(self.activities(request, 'Voided'))

    def test_second_void_and_reissue_before_void_are_refused(self):
        request = self.advance()
        with self.assertRaisesRegex(frappe.ValidationError, 'فقط پس از ابطال'):
            self.reissue(request)
        self.void(request)
        with self.assertRaisesRegex(frappe.ValidationError, 'سند اجراشده‌ای وجود ندارد'):
            self.void(request)
        self.assertEqual(len(self.activities(request, 'Voided')), 1)

    def test_only_an_hr_manager_in_the_company_may_void_or_reissue(self):
        request = self.advance()
        approver = self.records['approver']
        for user in (self.user, approver):
            with self.assertRaises(frappe.PermissionError):
                self.void(request, user=user)
            with self.assertRaises(frappe.PermissionError):
                self.reissue(request, user=user)
        # System Manager alone is not HR Manager.
        system = self._user('sys-' + self.token, 'System Manager')
        with self.assertRaises(frappe.PermissionError):
            self.void(request, user=system)
        # HR Manager restricted to another company.
        other = frappe.get_all('Company', filters={'name': ['!=', self.company]}, pluck='name', limit=1)[0]
        frappe.get_doc({'doctype': 'User Permission', 'user': self.hr, 'allow': 'Company',
                        'for_value': other}).insert()
        frappe.clear_cache(user=self.hr)
        with self.assertRaises(frappe.PermissionError):
            self.void(request)
        self.assertEqual(frappe.db.get_value(REQUEST, request['name'], 'native_status'), 'Created')

    def test_hr_manager_without_employee_record_can_void(self):
        self.assertFalse(frappe.db.exists('Employee', {'user_id': self.hr}))
        request = self.advance()
        self.assert_voided(request, self.void(request))

    def test_viewer_flags_follow_the_role(self):
        request = self.advance()
        frappe.set_user(self.hr)
        hr_view = workflow_request.get_request(request['name'])['data']
        frappe.set_user(self.user)
        own_view = workflow_request.get_request(request['name'])['data']
        frappe.set_user('Administrator')
        self.assertEqual((hr_view['execution']['can_void'], hr_view['execution']['can_reissue']), (True, False))
        self.assertEqual((own_view['execution']['can_void'], own_view['execution']['can_reissue']), (False, False))

    def test_request_without_executed_document_cannot_be_voided(self):
        request = self.advance()
        frappe.db.set_value(REQUEST, request['name'], 'native_status', 'Needs Review')
        with self.assertRaisesRegex(frappe.ValidationError, 'سند اجراشده‌ای وجود ندارد'):
            self.void(request)

    def test_cancel_refused_by_erpnext_changes_nothing(self):
        request = self.asset()
        old = request['native']['name']
        frappe.get_doc('Asset Movement', old).submit()
        # A later submitted movement of the same asset makes ERPNext refuse the cancel of this one? Use a
        # link instead: a Comment is not a link, so block through the document's own validation.
        from unittest.mock import patch

        from frappe.model.document import Document
        with patch.object(Document, 'cancel', side_effect=frappe.ValidationError('x')):
            with self.assertRaisesRegex(frappe.ValidationError, 'ابطال سند انجام نشد'):
                self.void(request)
        self.assertEqual(frappe.db.get_value('Asset Movement', old, 'docstatus'), 1)
        self.assertEqual(frappe.db.get_value(REQUEST, request['name'], 'native_status'), 'Created')
        self.assertFalse(self.activities(request, 'Voided'))

    def test_template_request_is_voidable_but_not_reissuable(self):
        request = self.advance()
        frappe.db.set_value(REQUEST, request['name'], 'template_key', 'leave')
        self.void(request)
        with self.assertRaisesRegex(frappe.ValidationError, 'صدور مجدد برای این نوع'):
            self.reissue(request)


class TestVoidIsRegistered(FrappeTestCase):
    def test_voided_is_an_option_of_the_native_status_field(self):
        options = frappe.get_meta(REQUEST).get_field('native_status').options.split('\n')
        self.assertIn('Voided', options)
        self.assertTrue(json.dumps(options))
