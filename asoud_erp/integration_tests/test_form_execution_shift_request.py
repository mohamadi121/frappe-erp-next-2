"""Real HRMS rows exercise atomic draft creation and native overlap checks."""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.services.form_execution.shift_request import NATIVE_ERROR, apply


class TestShiftExecution(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        token = uuid.uuid4().hex[:8]
        self.company = frappe.get_doc({'doctype': 'Company', 'company_name': token,
            'abbr': token, 'default_currency': 'USD', 'country': 'United States'}).insert().name
        self.user = frappe.get_doc({'doctype': 'User', 'email': token + '@example.test',
            'first_name': 'کارمند', 'send_welcome_email': 0}).insert().name
        self.people = []
        for index in range(2):
            self.people.append(frappe.get_doc({'doctype': 'Employee', 'first_name': 'کارمند',
                'company': self.company, 'gender': 'Male', 'date_of_birth': '1990-01-01',
                'date_of_joining': '2020-01-01', 'status': 'Active',
                'user_id': self.user if index == 0 else None, 'create_user_permission': 0,
                'shift_request_approver': 'Administrator'}).insert().name)
        self.shifts = []
        for index in range(2):
            self.shifts.append(frappe.get_doc({'doctype': 'Shift Type',
                'name': token + str(index), 'start_time': '08:00:00',
                'end_time': '16:00:00'}).insert().name)
        self.request = frappe._dict(company=self.company, owner=self.user,
                                   requester_employee=self.people[0])
        self.params = {'kind': 'self_change', 'from_date': '2030-01-01',
                       'shift_type': self.shifts[0]}

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()
        super().tearDown()

    def swap(self):
        return {**self.params, 'kind': 'swap_with_colleague', 'colleague': self.people[1],
                'colleague_shift_type': self.shifts[1]}

    def test_self_and_open_end(self):
        result = apply(self.request, self.params)
        doc = frappe.get_doc(result.doctype, result.name)
        self.assertEqual((doc.employee, doc.shift_type, doc.status, doc.docstatus, doc.to_date),
                         (self.people[0], self.shifts[0], 'Draft', 0, None))

    def test_swap(self):
        result = apply(self.request, self.swap())
        rows = frappe.get_all('Shift Request', filters={'company': self.company},
                             fields=['employee', 'shift_type', 'docstatus'])
        self.assertEqual({(r.employee, r.shift_type, r.docstatus) for r in rows},
                         {(self.people[0], self.shifts[0], 0), (self.people[1], self.shifts[1], 0)})
        self.assertEqual(result.status, 'Created')

    def test_second_insert_failure_rolls_back_first(self):
        frappe.db.set_value('Employee', self.people[1], 'default_shift', self.shifts[1])
        with self.assertRaisesRegex(ValueError, NATIVE_ERROR):
            apply(self.request, self.swap())
        self.assertEqual(frappe.db.count('Shift Request', {'company': self.company}), 0)

    def test_request_overlap(self):
        apply(self.request, self.params)
        with self.assertRaisesRegex(ValueError, NATIVE_ERROR):
            apply(self.request, self.params)
        self.assertEqual(frappe.db.count('Shift Request', {'company': self.company}), 1)

    def test_assignment_overlap(self):
        doc = frappe.get_doc({'doctype': 'Shift Assignment', 'employee': self.people[0],
            'company': self.company, 'shift_type': self.shifts[0], 'start_date': '2029-01-01',
            'status': 'Active'}).insert()
        doc.submit()
        with self.assertRaisesRegex(ValueError, NATIVE_ERROR):
            apply(self.request, self.params)
        self.assertEqual(frappe.db.count('Shift Request', {'company': self.company}), 0)
        frappe.db.set_value('Shift Assignment', doc.name, 'status', 'Inactive')
        self.assertEqual(apply(self.request, self.params).status, 'Created')

    def test_inactive_colleague(self):
        frappe.db.set_value('Employee', self.people[1], 'status', 'Inactive')
        with self.assertRaisesRegex(ValueError, 'فعال'):
            apply(self.request, self.swap())
        self.assertEqual(frappe.db.count('Shift Request', {'company': self.company}), 0)

    def test_other_company_colleague(self):
        frappe.db.set_value('Employee', self.people[1], 'company', 'شرکت دیگر')
        with self.assertRaisesRegex(ValueError, 'شرکت'):
            apply(self.request, self.swap())
        self.assertEqual(frappe.db.count('Shift Request', {'company': self.company}), 0)

    def test_missing_approver_and_unknown_shift(self):
        with self.assertRaisesRegex(ValueError, 'وجود ندارد'):
            apply(self.request, {**self.params, 'shift_type': 'ناشناخته'})
        frappe.db.set_value('Employee', self.people[0], 'shift_request_approver', None)
        with self.assertRaisesRegex(ValueError, 'تأییدکننده'):
            apply(self.request, self.params)
        self.assertEqual(frappe.db.count('Shift Request', {'company': self.company}), 0)

    def test_department_approver_fallback(self):
        department = frappe.get_doc({'doctype': 'Department', 'department_name': uuid.uuid4().hex[:8],
            'company': self.company, 'shift_request_approver': [{'approver': 'Administrator'}]}).insert()
        frappe.db.set_value('Employee', self.people[0],
                            {'department': department.name, 'shift_request_approver': None})
        result = apply(self.request, self.params)
        self.assertEqual(frappe.db.get_value('Shift Request', result.name, 'approver'), 'Administrator')
