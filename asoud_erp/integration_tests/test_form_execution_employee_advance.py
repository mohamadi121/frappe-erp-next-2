"""Real HRMS draft creation and prerequisite failures; all fixture writes roll back."""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from asoud_erp.services.form_execution.employee_advance import apply


class TestFormExecutionEmployeeAdvance(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        suffix = uuid.uuid4().hex[:8]
        self.company = frappe.get_doc({
            'doctype': 'Company', 'company_name': f'Advance Execution {suffix}',
            'abbr': suffix, 'default_currency': 'USD', 'country': 'United States',
        }).insert().name
        self.user = frappe.get_doc({
            'doctype': 'User', 'email': f'advance-{suffix}@example.test',
            'first_name': 'Advance', 'send_welcome_email': 0, 'roles': [{'role': 'Employee'}],
        }).insert().name
        self.employee = frappe.get_doc({
            'doctype': 'Employee', 'first_name': 'Advance', 'gender': 'Male',
            'date_of_birth': '1990-01-01', 'date_of_joining': '2020-01-01',
            'company': self.company, 'user_id': self.user, 'status': 'Active',
            'create_user_permission': 0,
        }).insert().name
        parent = frappe.db.get_value('Account', {'company': self.company, 'is_group': 1,
                                                   'root_type': 'Asset'}, 'name')
        self.account = frappe.get_doc({
            'doctype': 'Account', 'account_name': f'Advance {suffix}', 'company': self.company,
            'parent_account': parent, 'account_type': 'Receivable', 'account_currency': 'USD',
        }).insert().name
        frappe.db.set_value('Company', self.company, 'default_employee_advance_account', self.account)
        self.request = frappe._dict(company=self.company, requester=self.user,
                                    requester_employee=self.employee, name=f'ADV-{suffix}')
        self.params = {'amount': 1500, 'purpose': 'هزینه سفر', 'repay_from_salary': True}

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()
        super().tearDown()

    def assert_failure(self, message):
        before = frappe.db.count('Employee Advance', {'company': self.company})
        with self.assertRaises(ValueError) as error:
            apply(self.request, self.params)
        self.assertEqual(str(error.exception), message)
        self.assertEqual(frappe.db.count('Employee Advance', {'company': self.company}), before)

    def test_created_draft_and_result_without_holiday_or_salary(self):
        frappe.db.set_value('Employee', self.employee, 'holiday_list', None)
        frappe.db.set_value('Company', self.company, 'default_holiday_list', None)
        frappe.set_user(self.user)
        result = apply(self.request, self.params)
        self.assertEqual((result.status, result.doctype, result.reason), ('Created', 'Employee Advance', ''))
        self.assertEqual(frappe.session.user, self.user)
        doc = frappe.get_doc(result.doctype, result.name)
        self.assertEqual((doc.employee, doc.company, doc.advance_amount, doc.purpose),
                         (self.employee, self.company, 1500, 'هزینه سفر'))
        self.assertEqual((doc.docstatus, doc.status, doc.currency, doc.exchange_rate), (0, 'Draft', 'USD', 1))
        self.assertEqual((str(doc.posting_date), doc.advance_account,
                          doc.repay_unclaimed_amount_from_salary), (nowdate(), self.account, 1))
        self.assertEqual((doc.paid_amount, doc.claimed_amount, doc.return_amount), (0, 0, 0))

    def test_explicit_date_and_employee_lookup(self):
        self.request.requester_employee = None
        self.params.update(posting_date=nowdate(), repay_from_salary=0)
        result = apply(self.request, self.params)
        doc = frappe.get_doc(result.doctype, result.name)
        self.assertEqual((doc.employee, str(doc.posting_date), doc.repay_unclaimed_amount_from_salary),
                         (self.employee, nowdate(), 0))

    def test_missing_account(self):
        frappe.db.set_value('Company', self.company, 'default_employee_advance_account', None)
        self.assert_failure('حساب پیش‌فرض مساعده کارکنان در شرکت تنظیم نشده است.')

    def test_invalid_accounts(self):
        for changes in ({'account_type': None}, {'disabled': 1}, {'is_group': 1},
                        {'company': 'missing-company'}):
            with self.subTest(changes=changes):
                frappe.db.savepoint('invalid_account')
                frappe.db.set_value('Account', self.account, changes)
                self.assert_failure('حساب مساعده کارکنان باید حساب دریافتنی فعال و غیرگروهی همین شرکت باشد.')
                frappe.db.rollback(save_point='invalid_account')
        frappe.db.set_value('Company', self.company, 'default_employee_advance_account', 'missing-account')
        self.assert_failure('حساب مساعده کارکنان باید حساب دریافتنی فعال و غیرگروهی همین شرکت باشد.')

    def test_missing_currency(self):
        frappe.db.set_value('Company', self.company, 'default_currency', None)
        self.assert_failure('واحد پول شرکت مشخص نشده است.')

    def test_missing_company(self):
        self.request.company = None
        self.assert_failure('شرکت درخواست مشخص نشده است.')
        self.request.company = 'missing-company'
        self.assert_failure('شرکت درخواست یافت نشد.')

    def test_employee_scope(self):
        for changes in ({'status': 'Inactive'}, {'user_id': None}, {'company': 'missing-company'}):
            with self.subTest(changes=changes):
                frappe.db.savepoint('employee_scope')
                frappe.db.set_value('Employee', self.employee, changes)
                self.assert_failure('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
                frappe.db.rollback(save_point='employee_scope')
        self.request.requester_employee = 'missing-employee'
        self.assert_failure('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
        self.request.requester_employee = None
        self.request.requester = None
        self.assert_failure('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
