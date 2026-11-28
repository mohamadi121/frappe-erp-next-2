"""The api_contract.manifest endpoint: a read-only, machine-readable contract."""

import frappe

from asoud_erp.api.v1 import api_contract
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase


class TestApiContractManifest(APITestCase):
    def test_manifest_lists_methods_with_their_classification(self):
        data = api_contract.manifest()["data"]
        assert data["api_version"] == "v1"
        assert data["method_count"] == len(data["methods"])
        # A known read and a known write, each with its registry classification.
        read = data["methods"]["asoud_erp.api.v1.selling.list_sales_invoices"]
        assert (read["kind"], read["pilot"]) == ("read", True)
        assert read["parameters"]["company"]["required"] is True
        write = data["methods"]["asoud_erp.api.v1.support.create_issue"]
        assert (write["kind"], write["pilot"], write["http"]) == ("write", True, ["POST"])
        # The outbox protocol method is not a tool.
        assert "asoud_erp.api.v1.sync.execute_mutation" not in data["methods"]

    def test_manifest_matches_the_committed_artifact(self):
        from pathlib import Path

        from asoud_erp.services import api_manifest

        data = api_contract.manifest()["data"]
        committed = (
            Path(__file__).resolve().parent.parent.parent / "docs" / "api" / "manifest.json"
        ).read_text(encoding="utf-8")
        assert api_manifest.manifest_to_json(data) == committed

    def test_guest_cannot_read_the_manifest(self):
        frappe.set_user("Guest")
        try:
            with self.assertRaises(frappe.AuthenticationError):
                api_contract.manifest()
        finally:
            frappe.set_user("Administrator")

    def test_an_ordinary_employee_can_read_the_manifest(self):
        frappe.set_user(EMPLOYEE_USER)
        try:
            data = api_contract.manifest()["data"]
            assert data["method_count"] > 0
        finally:
            frappe.set_user("Administrator")
