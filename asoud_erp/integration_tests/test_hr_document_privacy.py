"""Real persisted snapshots must not bypass payroll permissions."""

import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1 import employment_certificates, hiring_orders, salary_change_orders
from asoud_erp.integration_tests.fixtures import company
from asoud_erp.integration_tests.tenancy import HR_MANAGER_USER, setup_tenancy


class TestHRDocumentPrivacy(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _entry(self, kind, data):
        frappe.set_user("Administrator")
        entry = frappe.get_doc({"doctype": "ASOUD Form Entry", "company": company(),
                               "reference_doctype": kind, "reference_name": uuid4().hex,
                               "request_key": uuid4().hex, "values_json": json.dumps(data)})
        entry.flags.form_service = True
        entry.insert(ignore_permissions=True)
        return entry

    def test_hiring_detail_and_print_mask_payroll_without_permission(self):
        entry = self._entry("ASOUD Hiring Order", {"payroll_snapshot": {"rows": [{"amount": 987654321}]}})
        self.assertEqual(hiring_orders.get_hiring_order(entry.name)["data"]["payroll_snapshot"]["rows"][0]["amount"], 987654321)
        frappe.set_user(HR_MANAGER_USER)
        for endpoint in (hiring_orders.get_hiring_order, hiring_orders.print_hiring_order):
            self.assertNotIn("987654321", json.dumps(endpoint(entry.name)))

    def test_salary_detail_and_print_mask_payroll_without_permission(self):
        entry = self._entry("ASOUD Salary Change Order", {"comparison_table": {"rows": [{"new_amount": 987654321}]}})
        self.assertEqual(salary_change_orders.get_salary_change_order(entry.name)["data"]["comparison_table"]["rows"][0]["new_amount"], 987654321)
        frappe.set_user(HR_MANAGER_USER)
        for endpoint in (salary_change_orders.get_salary_change_order, salary_change_orders.print_salary_change_order):
            self.assertNotIn("987654321", json.dumps(endpoint(entry.name)))

    def test_certificate_salary_is_removed_from_nested_snapshots(self):
        entry = self._entry("ASOUD Employment Certificate", {
            "status": "Draft", "has_salary": True, "include_salary": True,
            "salary_rows": [{"id": "base", "amount": 987654321}],
            "template_snapshot": {"clauses": [{"id": "body", "title": "متن", "body": "حقوق {{payroll.base}}"}], "salary_enabled": True,
                                  "salary_rows": [{"id": "base", "title": "حقوق", "field_ref": "payroll.base", "period": "monthly"}]},
            "values_snapshot": {"employee": {"employee_name": "مینا"}, "payroll": {"base": 987654321}},
            "rendered_html": "987654321", "print_html": "987654321"})
        frappe.set_user(HR_MANAGER_USER)
        data = employment_certificates.get_certificate(entry.reference_name)["data"]
        self.assertNotIn("987654321", json.dumps(data))
        self.assertFalse(data["include_salary"])

    def test_order_endpoints_reject_other_snapshot_types(self):
        for kind, endpoints in (
            ("ASOUD Salary Change Order", (hiring_orders.get_hiring_order, hiring_orders.print_hiring_order)),
            ("ASOUD Hiring Order", (salary_change_orders.get_salary_change_order, salary_change_orders.print_salary_change_order)),
        ):
            entry = self._entry(kind, {})
            frappe.set_user(HR_MANAGER_USER)
            for endpoint in endpoints:
                with self.assertRaises(frappe.ValidationError):
                    endpoint(entry.name)
