"""Real rows: settlement drafts, atomic rollback and duplicate prevention."""

import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.services.form_execution.exit import DUPLICATE_ERROR, NATIVE_ERROR, apply, validate_submit


class TestExitExecution(FrappeTestCase):
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
            'workflow_code': 'EX-' + token, 'workflow_title': 'تسویه', 'company': self.company,
            'module_key': 'HR', 'target_doctype': 'ASOUD Workflow Request'}).insert().name
        form = frappe.get_doc({'doctype': 'ASOUD Form', 'title': 'تسویه ' + token,
            'company': self.company})
        form.flags.form_service = True
        form.insert()
        revision = frappe.get_doc({'doctype': 'ASOUD Form Revision', 'form': form.name,
            'version': 1, 'company': self.company,
            'schema_json': json.dumps({'kind': 'Request', 'execution': {'kind': 'exit'}, 'sections': []}),
            })
        revision.flags.form_service = True
        self.revision = revision.insert(ignore_permissions=True).name
        self.request = self.make_request()
        self.params = {'last_working_day': '2030-02-01', 'notes': 'یادداشت'}

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()
        super().tearDown()

    def make_request(self, status='Submitted'):
        doc = frappe.get_doc({'doctype': 'ASOUD Workflow Request', 'company': self.company,
            'workflow_definition': self.definition, 'request_type': 'تسویه', 'subject': 'تسویه حساب',
            'requester_employee': self.employee, 'status': status}).insert()
        frappe.db.set_value('ASOUD Workflow Request', doc.name, 'owner', self.user)
        entry = frappe.get_doc({'doctype': 'ASOUD Form Entry', 'form': frappe.db.get_value(
            'ASOUD Form Revision', self.revision, 'form'), 'revision': self.revision,
            'company': self.company, 'subject': 'تسویه', 'values_json': '{}',
            'reference_doctype': 'ASOUD Workflow Request', 'reference_name': doc.name,
            'request_key': uuid.uuid4().hex, 'fingerprint': uuid.uuid4().hex})
        entry.flags.form_service = True
        entry.insert(ignore_permissions=True)
        return frappe.get_doc('ASOUD Workflow Request', doc.name)

    def counts(self):
        return [frappe.db.count(d, {'employee': self.employee})
                for d in ('Exit Interview', 'Full and Final Statement')]

    def test_creates_both_drafts_and_relieving_date(self):
        result = apply(self.request, self.params)
        self.assertEqual((result.status, result.doctype), ('Created', 'Exit Interview'))
        interview = frappe.get_doc('Exit Interview', result.name)
        self.assertEqual((interview.docstatus, interview.status, interview.employee), (0, 'Pending', self.employee))
        statement = frappe.get_doc('Full and Final Statement', {'employee': self.employee})
        self.assertEqual((statement.docstatus, str(statement.relieving_date)), (0, '2030-02-01'))
        self.assertEqual(str(frappe.db.get_value('Employee', self.employee, 'relieving_date')), '2030-02-01')

    def test_failure_rolls_back_all_three(self):
        original = frappe.get_doc

        def failing(*args, **kwargs):
            doc = original(*args, **kwargs)
            if isinstance(args[0], dict) and args[0].get('doctype') == 'Full and Final Statement':
                doc.insert = lambda **kwargs: frappe.throw('native refusal')
            return doc
        frappe.get_doc = failing
        try:
            with self.assertRaisesRegex(ValueError, NATIVE_ERROR):
                apply(self.request, self.params)
        finally:
            frappe.get_doc = original
        self.assertEqual(self.counts(), [0, 0])
        self.assertIsNone(frappe.db.get_value('Employee', self.employee, 'relieving_date'))

    def test_duplicate_on_submit_and_apply(self):
        other = self.make_request()
        ctx = {'company': self.company, 'employee': self.employee, 'user': self.user}
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            validate_submit(self.params, ctx)
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            apply(self.request, self.params)
        self.assertEqual(self.counts(), [0, 0])
        frappe.db.set_value('ASOUD Workflow Request', self.request.name, 'status', 'Cancelled')
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            validate_submit(self.params, ctx)
        frappe.db.set_value('ASOUD Workflow Request', other.name, 'status', 'Rejected')
        validate_submit(self.params, ctx)

    def test_existing_statement_blocks_until_cancelled(self):
        frappe.db.set_value('ASOUD Workflow Request', self.request.name, 'status', 'Cancelled')
        frappe.db.set_value('Employee', self.employee, 'relieving_date', '2030-01-15')
        statement = frappe.get_doc({'doctype': 'Full and Final Statement', 'employee': self.employee,
            'company': self.company, 'transaction_date': '2030-01-10',
            'relieving_date': '2030-01-15'}).insert()
        ctx = {'company': self.company, 'employee': self.employee, 'user': self.user}
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            validate_submit(self.params, ctx)
        new = self.make_request()
        with self.assertRaisesRegex(ValueError, DUPLICATE_ERROR):
            apply(new, self.params)
        frappe.db.set_value('Full and Final Statement', statement.name, 'docstatus', 2)
        self.assertEqual(apply(new, self.params).status, 'Created')
