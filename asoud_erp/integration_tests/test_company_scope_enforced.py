"""SEC-BP-04: `account.*` reads must not answer for a foreign company.

Every `account` endpoint gates on roles with `frappe.only_for` and reads with
`frappe.get_all`, which skips User Permissions, so none of them was tenant
scoped. Company B is given coded accounts here, otherwise `list_accounts` answers
with an empty list and the leak is invisible.
"""

import frappe

from asoud_erp.api.v1 import account, detail_group, floating_detail, voucher
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import ACCOUNTS_A_USER, MANAGER_USER, setup_tenancy


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
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            account.preview_next_code(company=self.second, level="Group")
        with self.assertRaises(frappe.PermissionError):
            account.delete_account(company=self.second, account=self.coded_b[0])

    def test_own_company_accounts_still_read(self):
        frappe.set_user(ACCOUNTS_A_USER)
        self.assertIsInstance(account.list_accounts(company=self.company)["data"], list)
        self.assertTrue(account.preview_chart_template(company=self.company)["data"]["rows"])


class TestFloatingDetailCompanyScope(APITestCase):
    """``ASOUD Floating Detail`` has no company column, so the tenant boundary is
    the document it is linked to: linking or creating one against another
    company's party must be refused."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.party_b = cls.scope["party_b"]
        cls.detail = cls.scope["floating_detail"]

    def test_linking_a_detail_to_a_foreign_party_is_refused(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            floating_detail.link_floating_detail(name=self.detail, party_profile=self.party_b)
        self.assertNotEqual(
            frappe.db.get_value("ASOUD Floating Detail", self.detail, "linked_document"), self.party_b
        )

    def test_creating_a_detail_linked_to_a_foreign_party_is_refused(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            floating_detail.create_floating_detail(
                title="ASOUD Scope Foreign", detail_type="Customer", detail_group="10000",
                linked_doctype="ASOUD Party Profile", linked_document=self.party_b,
            )

    def test_own_company_detail_still_links(self):
        frappe.set_user(ACCOUNTS_A_USER)
        data = floating_detail.link_floating_detail(name=self.detail, party_profile=self.scope["party_a"])["data"]
        self.assertEqual(data["linked_document"], self.scope["party_a"])


class TestDetailGroupCompanyScope(APITestCase):
    """``ASOUD Detail Group`` is a site-wide catalogue, but ``ASOUD Account
    Mapping`` carries a company and must be tenant scoped."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        cls.mapping_b = cls.scope["mapping_b"]

    def test_listing_a_foreign_company_mapping_is_refused(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            detail_group.list_account_mappings(company=self.second)
        self.assertEqual(frappe.db.get_value("ASOUD Account Mapping", self.mapping_b, "company"), self.second)

    def test_saving_a_foreign_company_mapping_is_refused(self):
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            detail_group.save_account_mapping(company=self.second, account=self.scope["coded_accounts_b"][1],
                                              detail_group="20000")

    def test_detail_group_catalogue_stays_site_wide(self):
        """The catalogue has no company column, so it is read as a whole."""
        frappe.set_user(ACCOUNTS_A_USER)
        codes = {row["group_code"] for row in detail_group.list_detail_groups()["data"]}
        self.assertIn("10000", codes)


class TestVoucherCompanyScope(APITestCase):
    """``list_vouchers`` reads with ``frappe.get_all`` and the state changes act on
    a voucher by name, so neither was tenant scoped."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        cls.voucher_b = cls.scope["voucher_b"]

    def test_listing_a_foreign_company_vouchers_is_refused(self):
        self.assertEqual(frappe.db.get_value("ASOUD Accounting Voucher", self.voucher_b, "company"), self.second)
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            voucher.list_vouchers(company=self.second)

    def test_listing_own_company_vouchers_succeeds(self):
        frappe.set_user(ACCOUNTS_A_USER)
        res = voucher.list_vouchers(company=self.company)
        self.assertIsInstance(res.get("data"), list)

    def test_acting_on_a_foreign_voucher_is_refused(self):
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            voucher.submit_for_approval(name=self.voucher_b)
        self.assertEqual(
            frappe.db.get_value("ASOUD Accounting Voucher", self.voucher_b, "workflow_status"), "Draft"
        )

    def test_saving_into_a_foreign_company_is_refused(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            voucher.save_voucher(
                company=self.second,
                posting_date="2026-01-02",
                lines=[
                    {"account": self.scope["coded_accounts_b"][0], "debit": 10, "credit": 0},
                    {"account": self.scope["coded_accounts_b"][1], "debit": 0, "credit": 10},
                ],
            )