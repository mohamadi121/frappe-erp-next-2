"""SEC-BP-04: `account.*` reads must not answer for a foreign company.

Every `account` endpoint gates on roles with `frappe.only_for` and reads with
`frappe.get_all`, which skips User Permissions, so none of them was tenant
scoped. Company B is given coded accounts here, otherwise `list_accounts` answers
with an empty list and the leak is invisible.
"""

import base64

import frappe

from asoud_erp.api.v1 import account, detail_group, floating_detail, voucher, workflow_request
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create, valid_pdf_bytes
from asoud_erp.integration_tests.tenancy import (
    ACCOUNTS_A_USER,
    EMPLOYEE_A_USER,
    EMPLOYEE_B_USER,
    HR_MANAGER_USER,
    MANAGER_USER,
    setup_tenancy,
)


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

    def _linked_detail(self, title: str, party: str) -> str:
        return floating_detail.create_floating_detail(
            title=title, detail_type="Customer", detail_group="10000",
            linked_doctype="ASOUD Party Profile", linked_document=party,
        )["data"]["name"]

    def test_list_only_returns_details_of_accessible_companies(self):
        """F8: the global catalogue is filtered by the linked record's tenant.

        `ASOUD Floating Detail` has no company column, so `list_floating_details`
        answered with every company's rows. It must keep only rows whose linked
        record belongs to a company the caller may access; rows with no linked
        record stay with `System Manager`/`Accounts Manager` only.
        """
        frappe.set_user("Administrator")
        detail_a = self._linked_detail("ASOUD Scope Detail A", self.scope["party_a"])
        detail_b = self._linked_detail("ASOUD Scope Detail B", self.scope["party_b"])
        unlinked = self.detail

        frappe.set_user(ACCOUNTS_A_USER)
        names = {row["name"] for row in floating_detail.list_floating_details()["data"]}
        self.assertIn(detail_a, names)
        self.assertNotIn(detail_b, names)
        self.assertNotIn(unlinked, names)

        frappe.set_user(MANAGER_USER)
        names = {row["name"] for row in floating_detail.list_floating_details()["data"]}
        self.assertIn(detail_a, names)
        self.assertNotIn(detail_b, names)
        self.assertIn(unlinked, names)


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

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class TestRequestCompanyScope(APITestCase):
    """The request endpoints answer for the caller's own company and own requests only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

    def setUp(self):
        super().setUp()
        # No approval stage: the request completes on submit, which is all these checks need.
        definition, _stages = make_definition(self.second, approvals=0)
        self.request_b = create(
            self.second, definition=definition, user=EMPLOYEE_B_USER, values={"reason": "درخواست شرکت دوم"},
            attachments=[{"filename": "a.pdf", "content_base64": b64(valid_pdf_bytes()), "ref": "a"}])
        frappe.set_user(EMPLOYEE_A_USER)

    def test_field_options_of_a_foreign_company_are_refused(self):
        for field_type in ("User", "Department", "Cost Center", "Warehouse", "Delivery Location", "Branch"):
            with self.assertRaises(frappe.PermissionError):
                workflow_request.request_field_options(self.second, field_type)
        self.assertIsInstance(workflow_request.request_field_options(self.company, "Department")["data"], list)

    def test_options_and_list_of_a_foreign_company_are_refused(self):
        with self.assertRaises(frappe.PermissionError):
            workflow_request.request_options(self.second)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.list_my_requests(company=self.second)

    def test_creating_in_a_foreign_company_is_refused(self):
        with self.assertRaises(frappe.PermissionError):
            workflow_request.create_request(
                company=self.second, template_key="leave", request_id="foreign-create-0001", values={})

    def test_a_foreign_request_cannot_be_read_commented_or_downloaded(self):
        name = self.request_b["name"]
        file_name = self.request_b["attachments"][0]["name"]
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(name)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.list_request_comments(name)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.add_request_comment(name, "نباید ثبت شود")
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_attachment(file_name)
        self.assertEqual(frappe.db.count("Comment", {"reference_doctype": "ASOUD Workflow Request",
                                                     "reference_name": name, "comment_type": "Comment"}), 0)

    def test_the_owner_still_reads_their_own_request(self):
        frappe.set_user(EMPLOYEE_B_USER)
        self.assertEqual(workflow_request.get_request(self.request_b["name"])["data"]["company"], self.second)
        self.assertEqual(workflow_request.list_request_comments(self.request_b["name"])["data"], [])

    def test_an_hr_manager_of_another_company_is_refused_and_retry_needs_a_role(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(self.request_b["name"])
        with self.assertRaises(frappe.PermissionError):
            workflow_request.create_native_document(self.request_b["name"])
        frappe.set_user(EMPLOYEE_B_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.create_native_document(self.request_b["name"])
