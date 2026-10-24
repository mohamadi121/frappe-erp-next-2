"""Real rows: employment certificate issuance after approval, salary rules, numbering, download gate."""

import os
import re

import frappe
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import forms, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import open_task
from asoud_erp.integration_tests.test_payroll import STRUCTURE, setup_payroll
from asoud_erp.services import certificate_access
from asoud_erp.services.form_execution import certificate_issue as cert
from asoud_erp.services.request_native_documents import dispatch

OK = {'recipient': 'بانک ملی', 'purpose': 'bank'}


def pdf_text(file_name):
    """Text of the PDF through poppler's pdftotext; None when the tool is not installed."""
    import shutil
    import subprocess

    if not shutil.which('pdftotext'):
        return None
    content = frappe.get_doc('File', file_name).get_content()
    return subprocess.run(['pdftotext', '-', '-'], input=content, capture_output=True, check=True).stdout.decode()


def series_value(prefix):
    rows = frappe.db.sql('select `current` from `tabSeries` where name = %s', (prefix,))
    return rows[0][0] if rows else 0


class CertificateCase(APITestCase):
    def setUp(self):
        super().setUp()
        self.files = []
        token = frappe.generate_hash(length=10)
        self.head = frappe.get_doc({'doctype': 'Letter Head', 'letter_head_name': 'سربرگ ' + token,
            'source': 'HTML', 'content': '<div>سربرگ شرکت آزمون</div>'}).insert().name
        frappe.db.set_value('Company', self.company, 'default_letter_head', self.head)
        self.user = frappe.get_doc({'doctype': 'User', 'email': token + '@example.test',
            'first_name': 'درخواست‌کننده', 'send_welcome_email': 0, 'roles': [{'role': 'Employee'}]}).insert().name
        self.employee = self.make_employee(self.user)
        self.hr = frappe.get_doc({'doctype': 'User', 'email': 'hr-' + token + '@example.test',
            'first_name': 'منابع انسانی', 'send_welcome_email': 0, 'roles': [{'role': 'HR Manager'}]}).insert().name
        # Company read comes from the Employee role, which linking an Employee record grants (as for a real HR manager).
        self.make_employee(self.hr)
        self.other = frappe.get_doc({'doctype': 'User', 'email': 'other-' + token + '@example.test',
            'first_name': 'همکار', 'send_welcome_email': 0, 'roles': [{'role': 'Employee'}]}).insert().name
        self.make_employee(self.other)
        self.stranger = frappe.get_doc({'doctype': 'User', 'email': 'none-' + token + '@example.test',
            'first_name': 'بدون پرونده', 'send_welcome_email': 0, 'roles': [{'role': 'Employee'}]}).insert().name

    def tearDown(self):
        super().tearDown()
        for path in self.files:
            if os.path.exists(path):
                os.remove(path)

    def make_employee(self, user):
        return frappe.get_doc({'doctype': 'Employee', 'first_name': 'درخواست‌کننده', 'company': self.company,
            'user_id': user, 'gender': 'Male', 'date_of_birth': '1990-01-01', 'date_of_joining': '2020-03-20',
            'status': 'Active', 'create_user_permission': 0, 'create_user': 0,
            'reports_to': self.records['approver']}).insert().name

    def request(self):
        doc = frappe.get_doc({'doctype': 'ASOUD Workflow Request', 'company': self.company,
            'workflow_definition': make_definition(self.company, fields=[])[0], 'request_type': 'گواهی',
            'subject': 'گواهی اشتغال', 'requester_employee': self.employee, 'status': 'Submitted'}).insert()
        frappe.db.set_value('ASOUD Workflow Request', doc.name, 'owner', self.user)
        return frappe.get_doc('ASOUD Workflow Request', doc.name)

    def issue(self, params=None, request=None):
        result = cert.apply(request or self.request(), {**OK, **(params or {})})
        if result.name:
            self.files.append(frappe.get_doc('File', result.name).get_full_path())
        return result

    def assignment(self, base, from_date, submit=True, currency='IRR'):
        setup_payroll(self.company)
        doc = frappe.get_doc({'doctype': 'Salary Structure Assignment', 'employee': self.employee,
            'salary_structure': STRUCTURE, 'from_date': from_date, 'company': self.company, 'base': base,
            'currency': currency}).insert()
        if submit:
            doc.submit()
        return doc

    def approve(self, values, before_approval=None):
        definition, _ = make_definition(self.company, fields=[])
        schema = {'kind': 'Request', 'title': 'گواهی اشتغال', 'workflow': definition,
                  'execution': {'kind': 'certificate_issue'}, 'sections': [{'id': 'main', 'title': 'اصلی', 'fields': [
                      {'key': 'rec', 'label': 'مرجع', 'type': 'Text', 'execution_key': 'recipient'},
                      {'key': 'pur', 'label': 'هدف', 'type': 'Select', 'execution_key': 'purpose',
                       'options': [{'id': 'bank', 'label': 'ارائه به بانک'}, {'id': 'other', 'label': 'سایر'}]},
                      {'key': 'cmp', 'label': 'حقوق', 'type': 'Select', 'execution_key': 'include_compensation',
                       'options': [{'id': 'no', 'label': 'خیر'}, {'id': 'yes', 'label': 'بله'}]}]}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        entry = forms.submit_form(saved['name'], revision, 'گواهی', values, frappe.generate_hash(length=24))['data']
        request = workflow_request.get_request(entry['reference_name'])['data']
        task = open_task(request['workflow_instance'])
        self.approver = task.assigned_to
        if before_approval:
            frappe.set_user('Administrator')
            before_approval()
        frappe.set_user(self.approver)
        workflow_runtime.complete_workflow_task(task.name, 'Approve')
        frappe.set_user('Administrator')
        approved = workflow_request.get_request(request['name'])['data']
        if approved['native'].get('name'):
            self.files.append(frappe.get_doc('File', approved['native']['name']).get_full_path())
        return approved


class TestCertificateIssue(CertificateCase):
    def test_issued_without_salary_is_a_numbered_private_pdf(self):
        request = self.request()
        result = self.issue(request=request)
        self.assertEqual((result.status, result.doctype, result.reason), ('Created', 'File', ''))
        file = frappe.get_doc('File', result.name)
        self.assertTrue(re.fullmatch(r'CERT-\d{4}-\d{5}\.pdf', file.file_name))
        self.assertEqual((file.is_private, file.attached_to_doctype, file.attached_to_name, file.attached_to_field),
                         (1, 'ASOUD Workflow Request', request.name, 'certificate'))
        self.assertTrue(file.file_url.startswith('/private/files/'))
        self.assertTrue(file.get_content().startswith(b'%PDF-'))
        text = pdf_text(result.name)
        if text is not None:  # pdftotext drops zero-width joiners and adds direction marks
            text = ''.join(char for char in text if char not in '\u202a\u202b\u202c\u200c')
            for expected in (cert.number_of(file.file_name), 'بانک ملی', 'سربرگ شرکت آزمون', 'درخواستکننده',
                             frappe.db.get_value('Company', self.company, 'company_name')):
                self.assertIn(expected, text)
            self.assertNotIn('حقوق', text)

    def test_issued_with_salary_uses_latest_submitted_assignment(self):
        self.assignment(10000000, add_days(nowdate(), -400))
        self.assignment(25000000, add_days(nowdate(), -30))
        self.assignment(99000000, add_days(nowdate(), -10), submit=False)
        self.assignment(88000000, add_days(nowdate(), 30))
        self.assertEqual(cert._salary(self.employee, self.company, nowdate()), {'base': 25000000.0, 'currency': frappe.db.get_value('Company', self.company, 'default_currency')})
        other_company = frappe.get_all('Company', filters={'name': ['!=', self.company]}, pluck='name', limit=1)
        if other_company:
            self.assertIsNone(cert._salary(self.employee, other_company[0], nowdate()))
        result = self.issue({'include_compensation': 'yes'})
        self.assertEqual(result.status, 'Created')
        self.assertTrue(frappe.get_doc('File', result.name).get_content().startswith(b'%PDF-'))

    def test_salary_asked_without_any_record_is_needs_review_and_takes_no_number(self):
        before = series_value(cert.SERIES.split('.')[0])
        request = self.request()
        result = cert.apply(request, {**OK, 'include_compensation': 'yes'})
        self.assertEqual((result.status, result.reason, result.name), ('needs_review', cert.REVIEW_SALARY, None))
        self.assertEqual(series_value(cert.SERIES.split('.')[0]), before)
        self.assertFalse(frappe.db.exists('File', {'attached_to_name': request.name}))

    def test_unsubmitted_or_zero_salary_record_is_not_used(self):
        self.assignment(5000000, add_days(nowdate(), -5), submit=False)
        self.assertEqual(self.issue({'include_compensation': 'yes'}).status, 'needs_review')
        self.assignment(0, add_days(nowdate(), -4))
        self.assertEqual(self.issue({'include_compensation': 'yes'}).status, 'needs_review')

    def test_inactive_or_relieved_employee_is_needs_review(self):
        frappe.db.set_value('Employee', self.employee, 'relieving_date', add_days(nowdate(), -1))
        self.assertEqual(self.issue().reason, cert.REVIEW_NOT_EMPLOYED)
        frappe.db.set_value('Employee', self.employee, {'relieving_date': None, 'status': 'Inactive'})
        result = self.issue()
        self.assertEqual((result.status, result.reason), ('needs_review', cert.REVIEW_NOT_EMPLOYED))

    def test_no_letterhead_is_needs_review(self):
        frappe.db.set_value('Company', self.company, 'default_letter_head', None)
        self.assertEqual(self.issue().reason, cert.REVIEW_LETTERHEAD)

    def test_numbers_increment(self):
        first = frappe.get_doc('File', self.issue().name).file_name[:-4]
        second = frappe.get_doc('File', self.issue().name).file_name[:-4]
        self.assertEqual(first[:-5], second[:-5])
        self.assertEqual(int(second[-5:]), int(first[-5:]) + 1)

    def test_apply_twice_for_one_request_issues_once(self):
        request = self.request()
        first = self.issue(request=request)
        second = cert.apply(request, OK)
        self.assertEqual((second.status, second.name), ('Created', first.name))
        self.assertEqual(frappe.db.count('File', {'attached_to_name': request.name,
                                                   'attached_to_field': 'certificate'}), 1)


class TestCertificateDispatch(CertificateCase):
    def test_approval_attaches_certificate_and_redispatch_does_not_issue_twice(self):
        approved = self.approve({'rec': 'بانک ملی', 'pur': 'bank', 'cmp': 'no'})
        self.assertEqual((approved['native']['status'], approved['native']['doctype']), ('Created', 'File'))
        name = approved['native']['name']
        request = frappe.get_doc('ASOUD Workflow Request', approved['name'])
        dispatch(request)
        request.reload()
        self.assertEqual(request.native_name, name)
        self.assertEqual(frappe.db.count('File', {'attached_to_name': request.name, 'attached_to_field': 'certificate'}), 1)
        self.assertEqual(approved['execution']['state'], 'succeeded')

    def test_failed_request_retry_reuses_the_issued_file(self):
        approved = self.approve({'rec': 'بانک ملی', 'pur': 'bank', 'cmp': 'no'})
        frappe.db.set_value('ASOUD Workflow Request', approved['name'],
                            {'native_status': 'Failed', 'native_name': '', 'native_doctype': ''})
        frappe.set_user('Administrator')
        again = workflow_request.create_native_document(approved['name'])['data']
        self.assertEqual(again['native']['name'], approved['native']['name'])
        self.assertEqual(frappe.db.count('File', {'attached_to_name': approved['name'],
                                                   'attached_to_field': 'certificate'}), 1)

    def test_inactive_requester_reaches_hr_as_needs_review(self):
        def leave():
            frappe.db.set_value('Employee', self.employee, {'status': 'Left', 'relieving_date': add_days(nowdate(), -3)})
        approved = self.approve({'rec': 'بانک ملی', 'pur': 'bank', 'cmp': 'no'}, before_approval=leave)
        self.assertEqual(approved['native']['status'], 'Needs Review')
        self.assertEqual(approved['native']['error'], cert.REVIEW_NOT_EMPLOYED)
        self.assertFalse(frappe.db.exists('File', {'attached_to_name': approved['name'],
                                                    'attached_to_field': 'certificate'}))

    def test_salary_form_answer_without_record_is_needs_review(self):
        approved = self.approve({'rec': 'بانک ملی', 'pur': 'bank', 'cmp': 'yes'})
        self.assertEqual((approved['native']['status'], approved['native']['error']),
                         ('Needs Review', cert.REVIEW_SALARY))


class TestCertificateDownload(CertificateCase):
    def setUp(self):
        super().setUp()
        self.approved = self.approve({'rec': 'بانک ملی', 'pur': 'bank', 'cmp': 'no'})
        self.name = self.approved['name']
        self.file = self.approved['native']['name']

    def as_user(self, user, call, *args):
        frappe.set_user(user)
        try:
            return call(*args)
        finally:
            frappe.set_user('Administrator')

    def test_requester_hr_and_system_manager_download(self):
        for user in (self.user, self.hr, 'Administrator'):
            data = self.as_user(user, workflow_request.get_certificate, self.name)['data']
            self.assertEqual(data['content_type'], 'application/pdf')
            self.assertRegex(data['number'], r'CERT-\d{4}-\d{5}')
            self.assertTrue(data['content_base64'].startswith('JVBERi'))

    def manager_without_employee(self, role, company):
        """A manager account with no Employee record, limited to one company like a real multi-company site."""
        email = f'{role.split()[0].lower()}-noemp-{frappe.generate_hash(length=8)}@example.test'
        user = frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': 'مدیر بدون پرونده',
                               'send_welcome_email': 0, 'roles': [{'role': role}]}).insert().name
        # The Employee role gives Company read (as on a real site); the site drops it from User.roles on save.
        frappe.get_doc({'doctype': 'Has Role', 'parent': user, 'parenttype': 'User', 'parentfield': 'roles',
                        'role': 'Employee'}).insert(ignore_permissions=True)
        frappe.permissions.add_user_permission('Company', company, user, ignore_permissions=True)
        frappe.clear_cache(user=user)
        self.assertFalse(frappe.db.exists('Employee', {'user_id': user}))
        return user

    def test_hr_manager_without_employee_record_downloads_only_for_their_company(self):
        foreign = frappe.get_doc({'doctype': 'Company', 'company_name': 'C' + frappe.generate_hash(length=6),
                                  'abbr': frappe.generate_hash(length=5).upper(), 'default_currency': 'USD',
                                  'country': 'United States'}).insert().name
        own_hr = self.manager_without_employee('HR Manager', self.company)
        foreign_hr = self.manager_without_employee('HR Manager', foreign)
        data = self.as_user(own_hr, workflow_request.get_certificate, self.name)['data']
        self.assertTrue(data['content_base64'].startswith('JVBERi'))
        self.assertTrue(frappe.has_permission('File', 'read', doc=self.file, user=own_hr))
        self.assertIsNotNone(self.as_user(own_hr, workflow_request.get_request, self.name)['data']['certificate'])
        for call in (workflow_request.get_certificate, workflow_request.get_attachment):
            with self.assertRaises(frappe.PermissionError):
                self.as_user(foreign_hr, call, self.name if call is workflow_request.get_certificate else self.file)
        self.assertFalse(frappe.has_permission('File', 'read', doc=self.file, user=foreign_hr))

    def test_system_manager_without_employee_record_downloads_in_their_company(self):
        manager = self.manager_without_employee('System Manager', self.company)
        data = self.as_user(manager, workflow_request.get_certificate, self.name)['data']
        self.assertRegex(data['number'], r'CERT-\d{4}-\d{5}')

    def test_other_users_get_a_persian_permission_error(self):
        for user in (self.other, self.stranger, self.approver):
            with self.assertRaises(frappe.PermissionError):
                self.as_user(user, workflow_request.get_certificate, self.name)
            with self.assertRaises(frappe.PermissionError):
                self.as_user(user, workflow_request.get_attachment, self.file)
            self.assertFalse(frappe.has_permission('File', 'read', doc=self.file, user=user))
        for user in (self.user, self.hr):
            self.assertTrue(frappe.has_permission('File', 'read', doc=self.file, user=user))
        with self.assertRaisesRegex(frappe.PermissionError, certificate_access.DENIED):
            self.as_user(self.other, workflow_request.get_certificate, self.name)

    def test_detail_exposes_the_certificate_only_to_allowed_viewers(self):
        mine = self.as_user(self.user, workflow_request.get_request, self.name)['data']['certificate']
        self.assertEqual(set(mine), {'number', 'filename', 'issued_on'})
        approver = self.as_user(self.approver, workflow_request.get_request, self.name)['data']
        self.assertIsNone(approver['certificate'])
        self.assertIsNotNone(self.as_user(self.hr, workflow_request.get_request, self.name)['data']['certificate'])

    def test_not_issued_gives_persian_error(self):
        request = self.request()
        with self.assertRaisesRegex(frappe.ValidationError, certificate_access.NOT_ISSUED):
            self.as_user(self.user, workflow_request.get_certificate, request.name)

    def test_file_listing_hides_certificate_from_non_owner(self):
        frappe.set_user(self.approver)
        try:
            names = frappe.get_list('File', filters={'attached_to_name': self.name}, pluck='name')
        finally:
            frappe.set_user('Administrator')
        self.assertNotIn(self.file, names)
