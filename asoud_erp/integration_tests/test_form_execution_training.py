"""Real rows: training enrolment on draft events, HR review for submitted ones, duplicates, scope."""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from asoud_erp.api.v1 import forms, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import open_task
from asoud_erp.services.form_execution.training_enrollment import (
    DUPLICATE_ERROR,
    SUBMITTED_REVIEW,
    apply,
    validate_submit,
)


def make_event(company, submit=False, status='Scheduled', employees=None):
    start = add_days(now_datetime(), 5)
    doc = frappe.get_doc({'doctype': 'Training Event', 'event_name': 'دوره ' + uuid.uuid4().hex[:8],
        'event_status': status, 'type': 'Seminar', 'location': 'تهران', 'introduction': 'x',
        'company': company, 'start_time': start, 'end_time': add_days(start, 1),
        'employees': employees or []}).insert(ignore_permissions=True)
    if submit:
        doc.submit()
    return doc.name


def participants(event):
    return frappe.get_all('Training Event Employee', filters={'parent': event},
                          fields=['employee', 'employee_name', 'status', 'is_mandatory'])


class TestTrainingEnrollmentExecution(FrappeTestCase):
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
        self.definition = frappe.get_doc({'doctype': 'ASOUD Workflow Definition',
            'workflow_code': 'TR-' + token, 'workflow_title': 'آموزش', 'company': self.company,
            'module_key': 'HR', 'target_doctype': 'ASOUD Workflow Request'}).insert().name
        self.request = frappe.get_doc({'doctype': 'ASOUD Workflow Request', 'company': self.company,
            'workflow_definition': self.definition, 'request_type': 'آموزش', 'subject': 'ثبت‌نام',
            'requester_employee': self.employee, 'status': 'Submitted'}).insert()
        frappe.db.set_value('ASOUD Workflow Request', self.request.name, 'owner', self.user)
        self.request = frappe.get_doc('ASOUD Workflow Request', self.request.name)

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()
        super().tearDown()

    def test_draft_event_gets_participant_row(self):
        event = make_event(self.company)
        result = apply(self.request, {'training_event': event, 'notes': '<b>تمایل</b>'})
        self.assertEqual((result.status, result.doctype, result.name), ('Created', 'Training Event', event))
        rows = participants(event)
        self.assertEqual([(r.employee, r.employee_name, r.status, r.is_mandatory) for r in rows],
                         [(self.employee, 'کارمند', 'Open', 0)])
        self.assertEqual(frappe.db.get_value('Training Event', event, 'docstatus'), 0)
        comment = frappe.get_all('Comment', filters={'reference_doctype': 'Training Event',
            'reference_name': event, 'comment_type': 'Comment'}, pluck='content')
        self.assertEqual(comment, ['&lt;b&gt;تمایل&lt;/b&gt;'])

    def test_submitted_event_is_never_amended(self):
        other = frappe.get_doc({'doctype': 'Employee', 'first_name': 'دیگر', 'company': self.company,
            'gender': 'Male', 'date_of_birth': '1990-01-01', 'date_of_joining': '2020-01-01',
            'status': 'Active', 'create_user_permission': 0}).insert().name
        event = make_event(self.company, submit=True, employees=[{'employee': other}])
        modified = frappe.db.get_value('Training Event', event, 'modified')
        result = apply(self.request, {'training_event': event})
        self.assertEqual((result.status, result.reason, result.name), ('needs_review', SUBMITTED_REVIEW, None))
        self.assertEqual([r.employee for r in participants(event)], [other])
        self.assertEqual(frappe.db.get_value('Training Event', event, 'modified'), modified)

    def test_duplicate_is_refused_and_never_added_twice(self):
        event = make_event(self.company)
        apply(self.request, {'training_event': event})
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            apply(self.request, {'training_event': event})
        self.assertEqual(len(participants(event)), 1)
        ctx = {'company': self.company, 'employee': self.employee, 'user': self.user}
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            validate_submit({'training_event': event}, ctx)
        validate_submit({'training_event': make_event(self.company)}, ctx)

    def test_duplicate_in_submitted_event_is_refused_not_reviewed(self):
        event = make_event(self.company, submit=True, employees=[{'employee': self.employee}])
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            apply(self.request, {'training_event': event})

    def test_event_row_is_locked_while_checking(self):
        event = make_event(self.company)
        statements = []
        original = frappe.db.sql

        def spy(query, *args, **kwargs):
            statements.append(' '.join(str(query).split()))
            return original(query, *args, **kwargs)
        frappe.db.sql = spy
        try:
            apply(self.request, {'training_event': event})
        finally:
            frappe.db.sql = original
        self.assertTrue(any('from `tabTraining Event`' in s and s.endswith('for update') for s in statements))

    def test_cancelled_completed_foreign_and_unknown_events(self):
        cancelled = make_event(self.company, submit=True)
        frappe.get_doc('Training Event', cancelled).cancel()
        with self.assertRaisesRegex(ValueError, 'لغو شده'):
            apply(self.request, {'training_event': cancelled})
        with self.assertRaisesRegex(ValueError, 'لغو شده'):
            apply(self.request, {'training_event': make_event(self.company, status='Cancelled')})
        with self.assertRaisesRegex(ValueError, 'برگزار شده'):
            apply(self.request, {'training_event': make_event(self.company, status='Completed')})
        token = uuid.uuid4().hex[:8]
        foreign = frappe.get_doc({'doctype': 'Company', 'company_name': token, 'abbr': token,
            'default_currency': 'USD', 'country': 'United States'}).insert().name
        theirs = make_event(foreign)
        with self.assertRaisesRegex(ValueError, 'متعلق به شرکت'):
            apply(self.request, {'training_event': theirs})
        self.assertEqual(participants(theirs), [])
        with self.assertRaisesRegex(ValueError, 'وجود ندارد'):
            apply(self.request, {'training_event': 'no-such-event'})

    def test_requester_without_active_employee_is_refused(self):
        frappe.db.set_value('Employee', self.employee, 'status', 'Inactive')
        with self.assertRaisesRegex(ValueError, 'پرونده پرسنلی'):
            apply(self.request, {'training_event': make_event(self.company)})


class TestTrainingEnrollmentDispatch(APITestCase):
    def setUp(self):
        super().setUp()
        token = frappe.generate_hash(length=10)
        self.user = frappe.get_doc({'doctype': 'User', 'email': token + '@example.test',
            'first_name': 'درخواست‌کننده', 'send_welcome_email': 0,
            'roles': [{'role': 'Employee'}]}).insert().name
        self.employee = frappe.get_doc({'doctype': 'Employee', 'first_name': 'درخواست‌کننده',
            'company': self.company, 'user_id': self.user, 'gender': 'Male',
            'date_of_birth': '1990-01-01', 'date_of_joining': '2020-01-01', 'status': 'Active',
            'create_user_permission': 0, 'reports_to': self.records['approver']}).insert().name
        self.hr = frappe.get_doc({'doctype': 'User', 'email': 'hr-' + token + '@example.test',
            'first_name': 'منابع انسانی', 'send_welcome_email': 0,
            'roles': [{'role': 'HR Manager'}]}).insert().name

    def approve(self, event):
        definition, _ = make_definition(self.company, fields=[])
        schema = {'kind': 'Request', 'title': 'ثبت‌نام آموزشی', 'workflow': definition,
                  'execution': {'kind': 'training_enrollment'}, 'sections': [{'id': 'main', 'title': 'اصلی',
                  'fields': [{'key': 'ev', 'label': 'دوره', 'type': 'Link', 'source': 'Training Event',
                              'execution_key': 'training_event'}]}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        entry = forms.submit_form(saved['name'], revision, 'ثبت‌نام', {'ev': event},
                                  frappe.generate_hash(length=24))['data']
        request = workflow_request.get_request(entry['reference_name'])['data']
        task = open_task(request['workflow_instance'])
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, 'Approve')
        frappe.set_user('Administrator')
        return workflow_request.get_request(request['name'])['data']

    def test_approval_adds_participant_to_draft_event(self):
        event = make_event(self.company)
        approved = self.approve(event)
        self.assertEqual((approved['native']['status'], approved['native']['name']), ('Created', event))
        self.assertEqual([r.employee for r in participants(event)], [self.employee])

    def test_approval_of_submitted_event_notifies_hr_and_changes_nothing(self):
        event = make_event(self.company, submit=True)
        approved = self.approve(event)
        self.assertEqual(approved['native']['status'], 'Needs Review')
        self.assertEqual(approved['native']['error'], SUBMITTED_REVIEW)
        self.assertEqual(participants(event), [])
        logs = frappe.get_all('Notification Log', filters={
            'document_type': 'ASOUD Workflow Instance', 'document_name': approved['workflow_instance'],
            'email_content': SUBMITTED_REVIEW}, pluck='for_user')
        self.assertIn(self.hr, logs)
        self.assertIn(self.user, logs)
