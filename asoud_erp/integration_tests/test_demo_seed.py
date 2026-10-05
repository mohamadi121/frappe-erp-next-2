"""Integration test for the re-runnable demo seed, on a real site.

The manager runs this on the bench after merge::

    bench --site <site> run-tests --app asoud_erp --skip-test-records \
        --module asoud_erp.integration_tests.test_demo_seed

``force=True`` keeps the tests independent of the site's developer_mode.
The seed commits by itself (``bench execute`` semantics), so the class
resets the demo data again in ``tearDownClass`` and leaves the site clean
for the other modules.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.demo import markers as m
from asoud_erp.demo import seed as demo_seed

PASSWORD = "asoud-demo-123"


def demo_counts() -> dict:
    exists_user = sum(
        1 for local, _index, _roles, _note in m.USERS
        if frappe.db.exists("User", m.demo_email(local)))
    return {
        "employees": frappe.db.count("Employee", {"company": m.COMPANY}),
        "departments": frappe.db.count("Department", {"company": m.COMPANY}),
        "users": exists_user,
        "profiles": frappe.db.count("ASOUD Party Profile", {"company": m.COMPANY}),
        "leave_allocations": frappe.db.count(
            "Leave Allocation", {"company": m.COMPANY, "docstatus": 1}),
        "leave_applications": frappe.db.count(
            "Leave Application", {"company": m.COMPANY, "docstatus": 1}),
        "assignments": frappe.db.count(
            "Salary Structure Assignment", {"company": m.COMPANY, "docstatus": 1}),
        "attendance": frappe.db.count("Attendance", {"company": m.COMPANY, "docstatus": 1}),
        "sales_invoices": frappe.db.count(
            "Sales Invoice", {"company": m.COMPANY, "docstatus": 1}),
        "purchase_orders": frappe.db.count("Purchase Order", {"company": m.COMPANY}),
        "stock_entries": frappe.db.count("Stock Entry", {"company": m.COMPANY, "docstatus": 1}),
        "definitions": frappe.db.count("ASOUD Workflow Definition", {"company": m.COMPANY}),
        "requests": frappe.db.count("ASOUD Workflow Request", {"company": m.COMPANY}),
    }


def request_status(request_id: str) -> str:
    name = frappe.db.get_value("ASOUD Workflow Request", {"request_id": request_id},
                               "workflow_instance")
    return frappe.db.get_value("ASOUD Workflow Instance", name, "status")


class TestDemoSeed(FrappeTestCase):
    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        try:
            demo_seed.run(reset=True, force=True)
        finally:
            super().tearDownClass()

    def setUp(self):
        frappe.set_user("Administrator")

    def test_guard_refuses_without_developer_mode_unless_forced(self):
        self.assertIsNotNone(m.guard_error("erp.local", True, False))
        self.assertIsNotNone(m.guard_error("asoud.test", False, False))
        self.assertIsNone(m.guard_error("asoud.test", True, False))
        previous = frappe.conf.developer_mode
        frappe.conf.developer_mode = 0
        self.addCleanup(setattr, frappe.conf, "developer_mode", previous)
        with self.assertRaises(frappe.PermissionError):
            demo_seed.run(force=False)
        frappe.conf.developer_mode = previous

    def test_seed_is_idempotent(self):
        demo_seed.run(force=True, password=PASSWORD)
        before = demo_counts()
        second = demo_seed.run(force=True, password=PASSWORD)
        after = demo_counts()
        self.assertEqual(before, after)
        created = [value["created"] for value in second["summary"].values()
                   if isinstance(value, dict)]
        self.assertTrue(created)
        self.assertEqual(sum(created), 0, second["summary"])
        self.assertEqual(
            (before["employees"], before["departments"], before["users"],
             before["profiles"], before["definitions"], before["requests"]),
            (12, 4, 4, 12, 2, 4))
        self.assertEqual(before["leave_allocations"], 24)
        self.assertEqual(before["assignments"], 12)
        self.assertEqual(before["leave_applications"], 2)
        self.assertGreaterEqual(before["sales_invoices"], 2)
        self.assertGreaterEqual(before["purchase_orders"], 1)
        self.assertGreaterEqual(before["stock_entries"], 1)
        self.assertGreater(before["attendance"], 12)
        self.assertEqual(request_status(m.REQUEST_IDS["leave-approved"]), "Completed")
        self.assertEqual(request_status(m.REQUEST_IDS["leave-pending"]), "Running")
        self.assertEqual(request_status(m.REQUEST_IDS["purchase-rejected"]), "Rejected")
        self.assertEqual(request_status(m.REQUEST_IDS["leave-cancelled"]), "Cancelled")
        newcomer = m.demo_email("newcomer")
        self.assertIsNone(frappe.db.get_value("User", newcomer, "last_login"))
        self.assertIn("HR Manager", frappe.get_roles(m.demo_email("hr-manager")))
        employee = frappe.db.get_value(
            "Employee", {"user_id": m.demo_email("employee")},
            ["reports_to", "designation"], as_dict=True)
        manager = frappe.db.get_value(
            "Employee", {"user_id": m.demo_email("sales-manager")}, "name")
        self.assertEqual(employee.reports_to, manager)
        self.assertIn(m.FA_MARKER, employee.designation)

    def test_reset_removes_marked_records_and_keeps_unrelated(self):
        others = [name for name in frappe.get_all("Company", pluck="name")
                  if name != m.COMPANY]
        self.assertTrue(others, "the site needs a non-demo company for this test")
        if not frappe.db.exists("Gender", "Male"):
            frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
        unrelated = frappe.get_doc({
            "doctype": "Employee", "first_name": "Unrelated", "last_name": "Employee",
            "company": others[0], "gender": "Male",
            "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01",
            "status": "Active",
        }).insert(ignore_permissions=True).name
        try:
            demo_seed.run(force=True, password=PASSWORD)
            self.assertTrue(frappe.db.exists("Company", m.COMPANY))
            deleted = demo_seed.run(reset=True, force=True)["summary"]["deleted"]
            self.assertTrue(deleted.get("Company"), deleted)
            self.assertFalse(frappe.db.exists("Company", m.COMPANY))
            for local, _index, _roles, _note in m.USERS:
                self.assertFalse(frappe.db.exists("User", m.demo_email(local)))
            for code, _title, _stock, _rate in m.ITEMS:
                self.assertFalse(frappe.db.exists("Item", code))
            for title in m.CUSTOMERS:
                self.assertFalse(frappe.db.exists("Customer", title))
            for title in m.SUPPLIERS:
                self.assertFalse(frappe.db.exists("Supplier", title))
            for doctype in ("Employee", "Department", "Warehouse", "Attendance",
                            "Leave Allocation", "Leave Application",
                            "Salary Structure Assignment", "Sales Invoice",
                            "Purchase Order", "Purchase Receipt", "Purchase Invoice",
                            "Stock Entry", "ASOUD Party Profile",
                            "ASOUD Workflow Definition", "ASOUD Workflow Request"):
                filters = {"company": m.COMPANY}
                self.assertEqual(frappe.db.count(doctype, filters), 0, doctype)
            for title, _max_leaves in m.LEAVE_TYPES:
                self.assertFalse(frappe.db.exists("Leave Type", title))
            self.assertFalse(frappe.db.exists("Salary Structure", m.SALARY_STRUCTURE))
            # Ledger rows of the seed's vouchers are purged with the vouchers.
            for table in ("GL Entry", "Stock Ledger Entry", "Payment Ledger Entry"):
                self.assertEqual(frappe.db.count(table, {"company": m.COMPANY}), 0, table)
            self.assertTrue(frappe.db.exists("Employee", unrelated))
            self.assertEqual(frappe.db.get_value("Employee", unrelated, "company"), others[0])
        finally:
            if frappe.db.exists("Employee", unrelated):
                frappe.delete_doc("Employee", unrelated, ignore_permissions=True)
                frappe.db.commit()
