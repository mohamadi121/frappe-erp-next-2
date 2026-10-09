import frappe

from asoud_erp.api.v1 import (
    account,
    detail_group,
    floating_detail,
    party,
    purchase_request,
    role_management,
    setup,
    voucher,
    workflow,
)
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import EMPLOYEE_A_USER, setup_tenancy


class TestRoleGateEnforcement(APITestCase):
    """SEC-BP-07: erp_documents.require_roles must enforce role gates in test mode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()

    def test_employee_denied_on_role_gated_endpoints(self):
        frappe.set_user(EMPLOYEE_A_USER)
        # Endpoints that require System Manager / Accounts Manager / Accounts User
        # should deny an Employee even when calling within their own company.
        endpoints = [
            lambda: account.list_accounts(company=self.company),
            lambda: detail_group.list_detail_groups(),
            lambda: floating_detail.preview_next_detail_code(detail_group="10000"),
            lambda: party.disable_party(name=self.scope["party_a"]),
            lambda: purchase_request.purchase_request_options(company=self.company),
            lambda: role_management.catalog(),
            lambda: setup.get_settings(),
            lambda: voucher.list_vouchers(company=self.company),
            lambda: workflow.list_workflows(company=self.company),
        ]
        for call in endpoints:
            with self.subTest(call=call):
                with self.assertRaises(frappe.PermissionError):
                    call()
