"""The office cards use the same authorised scope and selection as login."""
import frappe

from asoud_erp.api.v1 import setup
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.tenancy import setup_tenancy


class TestOfficeNavigation(APITestCase):
    def setUp(self):
        super().setUp()
        self.second = setup_tenancy()['second']
        for company in (self.company, self.second):
            doc = (frappe.get_doc('ASOUD Company Setup', company)
                   if frappe.db.exists('ASOUD Company Setup', company)
                   else frappe.get_doc({'doctype': 'ASOUD Company Setup', 'company': company}))
            doc.office_saved = 1
            doc.save(ignore_permissions=True)

    def test_employee_lists_and_selects_only_own_office(self):
        frappe.set_user(EMPLOYEE_USER)
        rows = setup.list_offices()['data']['offices']
        self.assertIn(self.company, [row['company'] for row in rows])
        self.assertNotIn(self.second, [row['company'] for row in rows])
        self.assertNotIn('national_id', next(row for row in rows if row['company'] == self.company))
        selected = setup.set_default_office(self.company)['data']
        self.assertEqual(selected['company'], self.company)
        with self.assertRaises(frappe.PermissionError):
            setup.set_default_office(self.second)
        self.assertEqual(frappe.defaults.get_user_default('company'), self.company)

    def test_admin_selected_second_office_is_not_replaced_by_first(self):
        setup.set_default_office(self.second)
        self.assertEqual(setup.get_setup_status()['data']['company'], self.second)
        self.assertEqual(setup.list_offices()['data']['selected_office'], self.second)

    def test_guest_cannot_list_offices(self):
        frappe.set_user('Guest')
        with self.assertRaises(frappe.AuthenticationError):
            setup.list_offices()

    def test_create_additional_office_does_not_edit_selected_office(self):
        setup.set_default_office(self.second)
        old = frappe.db.get_value('Company', self.second, 'company_name')
        name = 'Office Navigation ' + frappe.generate_hash(length=10)
        created = setup.save_office(office_type='Personal', company_name=name,
            phone='09123456789', landline='02112345678')['data']
        self.assertEqual(created['company'], name)
        self.assertEqual(created['landline'], '02112345678')
        self.assertEqual(frappe.db.get_value('Company', self.second, 'company_name'), old)
        setup.set_default_office(name)
        self.assertEqual(setup.get_setup_status()['data']['company'], name)
