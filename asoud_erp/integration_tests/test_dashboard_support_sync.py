import frappe

from asoud_erp.api.v1 import dashboard, selling, support, sync
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    CUSTOMER,
    EMPLOYEE_USER,
    SERVICE,
    APITestCase,
)


class TestDashboard(APITestCase):
    def test_home_summary_counts_todays_sales(self):
        before = dashboard.get_home_summary(self.company)["data"]
        invoice = selling.create_sales_invoice(self.company, CUSTOMER, [{"item_code": SERVICE, "qty": 1}],
                                               submit=1)["data"]
        after = dashboard.get_home_summary(self.company)["data"]
        self.assertAlmostEqual(after["today_sales"], before["today_sales"] + invoice["grand_total"])
        self.assertEqual(after["open_documents"]["unpaid_sales_invoices"],
                         before["open_documents"]["unpaid_sales_invoices"] + 1)
        self.assertIsInstance(after["bank_and_cash"]["total"], float)

    def test_figures_the_user_cannot_read_are_null(self):
        frappe.set_user(EMPLOYEE_USER)
        summary = dashboard.get_home_summary(self.company)["data"]
        self.assertIsNone(summary["today_sales"])
        self.assertIsNone(summary["bank_and_cash"])
        self.assertIsNotNone(summary["open_documents"]["my_open_tasks"])

    def test_system_summary_is_for_system_managers(self):
        data = dashboard.get_system_summary()["data"]
        self.assertGreaterEqual(data["users"]["active"], 3)
        self.assertGreater(data["storage"]["database_bytes"], 0)
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            dashboard.get_system_summary()


class TestSupport(APITestCase):
    def test_issue_belongs_to_its_raiser(self):
        frappe.set_user(EMPLOYEE_USER)
        issue = support.create_issue("پرینتر کار نمی‌کند", "طبقه دوم")["data"]
        self.assertEqual(issue["raised_by"], EMPLOYEE_USER)
        self.assertEqual(support.list_my_issues()["data"][0].name, issue["name"])
        commented = support.add_issue_comment(issue["name"], "هنوز مشکل دارد")["data"]
        self.assertEqual(commented["comments"][-1]["text"], "هنوز مشکل دارد")
        frappe.set_user(APPROVER_USER)
        with self.assertRaises(frappe.PermissionError):
            support.get_issue(issue["name"])
        self.assertEqual(support.list_my_issues()["data"], [])

    def test_short_subject_is_rejected(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            support.create_issue("ab")


class TestSyncReplay(APITestCase):
    def test_request_key_is_bound_to_its_user(self):
        frappe.set_user(EMPLOYEE_USER)
        payload = {"subject": "درخواست تکراری"}
        first = sync.execute_mutation("asoud-test-key-1", "asoud_erp.api.v1.support.create_issue", payload)
        again = sync.execute_mutation("asoud-test-key-1", "asoud_erp.api.v1.support.create_issue", payload)
        self.assertEqual(first, again)
        self.assertEqual(frappe.db.count("Issue", {"subject": "درخواست تکراری"}), 1)
        frappe.set_user(APPROVER_USER)
        other = sync.execute_mutation("asoud-test-key-1", "asoud_erp.api.v1.support.create_issue", payload)
        self.assertEqual(other["error"]["code"], "INVALID_REQUEST_KEY")
