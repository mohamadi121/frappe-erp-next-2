"""Real persisted snapshots must not bypass payroll permissions."""

import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1 import employment_certificates, hiring_orders, salary_change_orders
from asoud_erp.integration_tests.fixtures import company
from asoud_erp.integration_tests.tenancy import HR_MANAGER_USER, setup_tenancy


class TestHRDocumentPrivacy(FrappeTestCase):
    def test_legacy_final_prints_never_acquire_the_current_letterhead(self):
        from frappe.utils import nowdate

        from asoud_erp.api.v1 import employment_contracts, personnel_introduction_letters

        frappe.set_user("Administrator")
        head = frappe.get_doc({"doctype": "Letter Head", "letter_head_name": uuid4().hex,
                               "source": "HTML", "content": "<p>CURRENT-HEADER-MUST-NOT-LEAK</p>"}).insert()
        frappe.db.set_value("Company", company(), "default_letter_head", head.name)
        for kind, endpoint, status, html_key in (
            ("ASOUD Hiring Order", hiring_orders.print_hiring_order, "final", "html"),
            ("ASOUD Salary Change Order", salary_change_orders.print_salary_change_order, "final", "html"),
            ("ASOUD Employment Certificate", employment_certificates.get_certificate, "Final", "print_html"),
            ("ASOUD Personnel Introduction Letter", personnel_introduction_letters.print_letter, "Final", "print_html"),
        ):
            with self.subTest(kind=kind):
                entry = self._entry(kind, {"status": status, "number": "LEGACY-123", "rendered_html": "متن قدیمی"})
                original = entry.values_json
                result = endpoint(entry.name)["data"]
                self.assertTrue(result["letterhead_missing"])
                self.assertNotIn("CURRENT-HEADER-MUST-NOT-LEAK", result[html_key])
                self.assertIn("LEGACY-123", result[html_key])
                self.assertEqual(frappe.db.get_value("ASOUD Form Entry", entry.name, "values_json"), original)
        employee = frappe.db.get_value("Employee", {"company": company(), "status": "Active"}, "name")
        draft = employment_contracts.save_contract_draft(company(), employee, nowdate(), client_id=uuid4().hex)["data"]
        name = draft["contract_id"]
        entry = frappe.db.get_value("ASOUD Form Entry", {"reference_name": name}, "name")
        data = json.loads(frappe.db.get_value("ASOUD Form Entry", entry, "values_json"))
        data.update(contract_number="LEGACY-123", status="final")
        data.pop("letterhead_html", None)
        data.pop("letterhead_snapshot", None)
        frappe.db.set_value("ASOUD Form Entry", entry, "values_json", json.dumps(data))
        frappe.db.set_value("Contract", name, "docstatus", 1)
        result = employment_contracts.get_contract_print(name)["data"]
        self.assertTrue(result["letterhead_missing"])
        self.assertNotIn("CURRENT-HEADER-MUST-NOT-LEAK", result["html"])

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
