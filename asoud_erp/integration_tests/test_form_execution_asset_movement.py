"""Exercise the executor directly with real ERPNext masters and transactions."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from asoud_erp.services.form_execution.asset_movement import apply


class TestAssetMovementExecution(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        self.suffix = frappe.generate_hash(length=8)
        self.company = frappe.get_doc(dict(doctype='Company',
            company_name='Equipment ' + self.suffix, abbr=self.suffix,
            default_currency='USD', country='United States',
            chart_of_accounts='Standard')).insert().name
        self.user = frappe.get_doc(dict(doctype='User', email=self.suffix + '@example.com',
            first_name='Equipment', send_welcome_email=0,
            roles=[dict(role='Employee')])).insert().name
        self.employee = frappe.get_doc(dict(doctype='Employee', first_name='Equipment',
            company=self.company, user_id=self.user, status='Active', gender='Male',
            date_of_birth='1990-01-01', date_of_joining='2020-01-01',
            create_user_permission=0)).insert().name
        self.location = frappe.get_doc(dict(doctype='Location',
            location_name='Equipment ' + self.suffix)).insert().name
        account = frappe.get_all('Account', filters=dict(company=self.company,
            is_group=0, account_type='Fixed Asset'), pluck='name', limit=1)[0]
        category = frappe.get_doc(dict(doctype='Asset Category',
            asset_category_name='Equipment ' + self.suffix,
            accounts=[dict(company_name=self.company, fixed_asset_account=account)])).insert().name
        item = frappe.get_doc(dict(doctype='Item', item_code='Equipment ' + self.suffix,
            item_group=frappe.get_all('Item Group', filters={'is_group': 0}, pluck='name', limit=1)[0],
            stock_uom='Nos', is_fixed_asset=1, is_stock_item=0, asset_category=category)).insert().name
        self.asset = frappe.get_doc(dict(doctype='Asset', asset_name='Equipment', item_code=item,
            company=self.company, location=self.location, is_existing_asset=1,
            purchase_date=add_days(nowdate(), -30), available_for_use_date=add_days(nowdate(), -30),
            gross_purchase_amount=100, asset_quantity=1)).insert()
        self.asset.submit()
        definition = frappe.get_doc(dict(doctype='ASOUD Workflow Definition',
            workflow_code=self.suffix, workflow_title='تجهیزات', company=self.company,
            module_key='HR', creation_mode='Custom', target_doctype='ASOUD Workflow Request',
            status='Inactive', readiness_status='Pending')).insert()
        self.request = frappe.get_doc(dict(doctype='ASOUD Workflow Request',
            company=self.company, workflow_definition=definition.name,
            request_type='تجهیزات', subject='تجهیزات', status='Completed')).insert()
        self.request.db_set('owner', self.user)
        self.params = dict(asset=self.asset.name, direction='Issue', date=nowdate(), note='تحویل تجهیز')

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()

    def test_issue_draft_result_and_comment_without_holiday_or_advance_account(self):
        frappe.db.set_value('Company', self.company, {
            'default_holiday_list': None, 'default_employee_advance_account': None})
        frappe.set_user(self.user)
        result = apply(self.request, self.params)
        self.assertEqual(frappe.session.user, self.user)
        self.assertEqual((result.status, result.doctype, result.reason), ('Created', 'Asset Movement', ''))
        doc = frappe.get_doc(result.doctype, result.name)
        self.assertEqual((doc.docstatus, doc.company, doc.purpose), (0, self.company, 'Issue'))
        self.assertEqual(str(doc.transaction_date), nowdate() + ' 00:00:00')
        self.assertEqual((doc.reference_doctype, doc.reference_name),
                         ('ASOUD Workflow Request', self.request.name))
        row = doc.assets[0]
        self.assertEqual((row.asset, row.to_employee, row.from_employee, row.target_location),
                         (self.asset.name, self.employee, None, self.location))
        self.assertFalse(frappe.db.get_value('Asset', self.asset.name, 'custodian'))
        self.assertEqual(frappe.db.get_value('Comment', dict(reference_doctype=doc.doctype,
            reference_name=doc.name, comment_type='Comment'), 'content'), 'تحویل تجهیز')

    def test_receipt_requires_requester_custodian(self):
        self.params['direction'] = 'Receipt'
        self.assert_failure('تجهیز در اختیار درخواست‌دهنده نیست و قابل بازگشت نیست.')
        other = frappe.copy_doc(frappe.get_doc('Employee', self.employee))
        other.user_id = None
        other.insert()
        frappe.db.set_value('Asset', self.asset.name, 'custodian', other.name)
        self.assert_failure('تجهیز در اختیار درخواست‌دهنده نیست و قابل بازگشت نیست.')
        frappe.db.set_value('Asset', self.asset.name, 'custodian', self.employee)
        result = apply(self.request, self.params)
        doc = frappe.get_doc(result.doctype, result.name)
        self.assertEqual((doc.docstatus, doc.purpose), (0, 'Receipt'))
        self.assertEqual((doc.assets[0].from_employee, doc.assets[0].to_employee,
                          doc.assets[0].target_location), (self.employee, None, self.location))
        self.assertEqual(frappe.db.get_value('Asset', self.asset.name, 'custodian'), self.employee)

    def assert_failure(self, message):
        before = frappe.db.count('Asset Movement')
        with self.assertRaisesRegex(ValueError, message):
            apply(self.request, self.params)
        self.assertEqual(frappe.db.count('Asset Movement'), before)

    def test_unknown_asset(self):
        self.params['asset'] = 'missing-' + self.suffix
        self.assert_failure('تجهیز انتخاب‌شده وجود ندارد.')

    def test_draft_and_cancelled_asset(self):
        for status in (0, 2):
            frappe.db.set_value('Asset', self.asset.name, 'docstatus', status)
            self.assert_failure('تجهیز انتخاب‌شده باید تأیید شده باشد.')

    def test_other_company(self):
        other = frappe.get_all('Company', filters={'name': ['!=', self.company]}, pluck='name', limit=1)[0]
        frappe.db.set_value('Asset', self.asset.name, 'company', other)
        self.assert_failure('تجهیز انتخاب‌شده متعلق به شرکت درخواست نیست.')

    def test_missing_and_unknown_location(self):
        for location in (None, 'missing-' + self.suffix):
            frappe.db.set_value('Asset', self.asset.name, 'location', location)
            self.assert_failure('مکان تجهیز ثبت نشده یا معتبر نیست.')

    def test_requester_must_have_active_employee_in_company(self):
        frappe.db.set_value('Employee', self.employee, 'status', 'Inactive')
        self.assert_failure('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
        frappe.db.set_value('Employee', self.employee, 'status', 'Active')
        self.request.company = frappe.get_all('Company', filters={'name': ['!=', self.company]},
                                              pluck='name', limit=1)[0]
        self.assert_failure('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')
        self.request.company = self.company
        self.request.owner = 'Administrator'
        self.assert_failure('پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')

    def test_movement_date_query_matches_only_submitted_rows_for_this_asset(self):
        result = apply(self.request, self.params)
        doc = frappe.get_doc(result.doctype, result.name)
        doc.transaction_date = add_days(nowdate(), 1) + ' 00:00:00'
        doc.save()
        other_asset = frappe.copy_doc(self.asset).insert()
        other_asset.submit()
        unrelated = frappe.copy_doc(doc)
        unrelated.assets[0].asset = other_asset.name
        unrelated.insert().submit()
        # Future drafts and submitted movements of another asset must not block today.
        self.assertEqual(apply(self.request, self.params).status, 'Created')
        doc.submit()
        self.assert_failure('تاریخ جابه‌جایی نمی‌تواند پیش از آخرین جابه‌جایی تجهیز باشد.')
