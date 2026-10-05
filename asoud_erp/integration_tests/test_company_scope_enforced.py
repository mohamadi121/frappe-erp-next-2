"""SEC-BP-04: `account.*` reads must not answer for a foreign company.

Every `account` endpoint gates on roles with `frappe.only_for` and reads with
`frappe.get_all`, which skips User Permissions, so none of them was tenant
scoped. Company B is given coded accounts here, otherwise `list_accounts` answers
with an empty list and the leak is invisible.
"""

import frappe

from asoud_erp.api.v1 import account
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import ACCOUNTS_A_USER, setup_tenancy


class TestAccountCompanyScope(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        cls.coded_b = cls.scope["coded_accounts_b"]

    def test_company_b_really_has_coded_accounts(self):
        self.assertTrue(self.coded_b)
        self.assertTrue(frappe.get_all("Account", filters={"company": self.second,
                                                          "account_number": ["is", "set"]}, pluck="name", limit=1))

    def test_account_list_endpoints_reject_foreign_company(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            account.list_accounts(company=self.second)
        with self.assertRaises(frappe.PermissionError):
            account.preview_chart_template(company=self.second)

    def test_account_write_endpoints_reject_foreign_company(self):
        frappe.set_user("asoud.scope-manager@example.com")
        with self.assertRaises(frappe.PermissionError):
            account.preview_next_code(company=self.second, level="Group")
        with self.assertRaises(frappe.PermissionError):
            account.delete_account(company=self.second, account=self.coded_b[0])

    def test_own_company_accounts_still_read(self):
        frappe.set_user(ACCOUNTS_A_USER)
        self.assertIsInstance(account.list_accounts(company=self.company)["data"], list)
        self.assertTrue(account.preview_chart_template(company=self.company)["data"]["rows"])