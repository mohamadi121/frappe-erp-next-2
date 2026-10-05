"""SEC-BP-04: purchase_request endpoints must not answer for a foreign company.

`purchase_request_options` builds its item and warehouse option lists with
`frappe.get_all`, which never applies User Permissions, and it never called
`require_company`: an Accounts Manager restricted to Company A received Company
B's warehouse list.
"""

import frappe

from asoud_erp.api.v1 import purchase_request
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import ACCOUNTS_A_USER, setup_tenancy


class TestPurchaseRequestCompanyScope(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

    def test_company_b_really_has_a_warehouse(self):
        self.assertTrue(frappe.get_all("Warehouse", filters={"company": self.second, "is_group": 0},
                                      pluck="name", limit=1))

    def test_purchase_request_options_rejects_foreign_company(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            purchase_request.purchase_request_options(company=self.second)

    def test_own_company_options_still_read(self):
        frappe.set_user(ACCOUNTS_A_USER)
        data = purchase_request.purchase_request_options(company=self.company)["data"]
        self.assertTrue(data["warehouses"])
        foreign = set(frappe.get_all("Warehouse", filters={"company": self.second, "is_group": 0}, pluck="name"))
        self.assertEqual({row["name"] for row in data["warehouses"]} & foreign, set())