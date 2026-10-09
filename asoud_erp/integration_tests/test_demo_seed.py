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
from frappe.utils import get_year_ending, getdate, nowdate

from asoud_erp.demo import markers as m
from asoud_erp.demo import seed as demo_seed

PASSWORD = "asoud-demo-123"


def _delete_robustly(doctype: str, name: str, attempts: int = 5) -> None:
    """Delete one doc, retrying transient row locks from concurrent workers."""
    import time

    for attempt in range(attempts):
        try:
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, ignore_permissions=True)
            return
        except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))


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
        "material_requests": frappe.db.count("Material Request", {"company": m.COMPANY}),
        "definitions": frappe.db.count("ASOUD Workflow Definition", {"company": m.COMPANY}),
        "requests": frappe.db.count("ASOUD Workflow Request", {"company": m.COMPANY}),
    }


def demo_request(key: str):
    return frappe.db.get_value(
        "ASOUD Workflow Request", {"request_id": m.REQUEST_IDS[key]},
        ["name", "template_key", "status_key", "native_doctype", "native_name", "native_status"], as_dict=True)


def leave_requests_seeded() -> bool:
    """The leave requests are skipped in the last days of the calendar year (no room for them)."""
    holidays = {str(day) for day in frappe.get_all(
        "Holiday", filters={"parent": ["like", f"{m.HOLIDAY_LIST}%"]}, pluck="holiday_date")}
    return m.demo_leave_dates(getdate(nowdate()), getdate(get_year_ending(nowdate())), holidays) is not None


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
        leaves = leave_requests_seeded()
        self.assertEqual(
            (before["employees"], before["users"],
             before["profiles"], before["definitions"], before["requests"]),
            (12, 4, 12, 3, 6 if leaves else 3))
        # ERPNext adds its own standard departments to every new company, so
        # only the four demo departments are asserted by name.
        for name in m.DEPARTMENTS:
            self.assertTrue(frappe.db.exists(
                "Department", {"company": m.COMPANY, "department_name": name}), name)
        self.assertEqual(before["leave_allocations"], 24)
        self.assertEqual(before["assignments"], 12)
        # Two seeded applications, plus the one our approved daily leave request created.
        self.assertEqual(before["leave_applications"], 3 if leaves else 2)
        self.assertEqual(before["material_requests"], 2)
        self.assertGreaterEqual(before["sales_invoices"], 2)
        self.assertGreaterEqual(before["purchase_orders"], 1)
        self.assertGreaterEqual(before["stock_entries"], 1)
        self.assertGreater(before["attendance"], 12)
        self.assertEqual(request_status(m.REQUEST_IDS["purchase-approved"]), "Completed")
        self.assertEqual(request_status(m.REQUEST_IDS["purchase-rejected"]), "Rejected")
        self.assertEqual(request_status(m.REQUEST_IDS["supply-approved"]), "Completed")
        if leaves:
            self.assertEqual(request_status(m.REQUEST_IDS["leave-approved"]), "Completed")
            self.assertEqual(request_status(m.REQUEST_IDS["leave-pending"]), "Running")
            self.assertEqual(request_status(m.REQUEST_IDS["leave-cancelled"]), "Cancelled")
        # The demo company has exactly the three system templates, and requests use their numbering.
        templates = frappe.get_all(
            "ASOUD Workflow Definition", filters={"company": m.COMPANY},
            fields=["template_key", "is_system_template", "workflow_code"], order_by="template_key asc")
        self.assertEqual([row.template_key for row in templates], ["leave", "purchase", "supply"])
        self.assertTrue(all(row.is_system_template for row in templates))
        for key, prefix in (("purchase-approved", "PR-"), ("supply-approved", "SP-")):
            self.assertTrue(demo_request(key).name.startswith(prefix), key)
        # Approval created the native documents through the post-approval hook.
        purchase = demo_request("purchase-approved")
        self.assertEqual((purchase.native_status, purchase.native_doctype), ("Created", "Material Request"))
        self.assertEqual(frappe.db.get_value("Material Request", purchase.native_name, "material_request_type"),
                         "Purchase")
        supply = demo_request("supply-approved")
        self.assertEqual(frappe.db.get_value("Material Request", supply.native_name, "material_request_type"),
                         "Material Transfer")
        self.assertEqual(demo_request("purchase-rejected").native_status or "", "")
        if leaves:
            approved = demo_request("leave-approved")
            self.assertEqual((approved.native_status, approved.native_doctype), ("Created", "Leave Application"))
            self.assertEqual(frappe.db.get_value("Leave Application", approved.native_name, "asoud_request"),
                             approved.name)
            self.assertEqual(demo_request("leave-pending").native_status or "", "")
        for title, _max_leaves in m.LEAVE_TYPES:
            self.assertTrue(frappe.db.get_value("Leave Type", title, "asoud_leave_category"), title)
        newcomer = m.demo_email("newcomer")
        self.assertFalse(frappe.db.get_value("User", newcomer, "last_login"))
        self.assertIn("HR Manager", frappe.get_roles(m.demo_email("hr-manager")))
        employee = frappe.db.get_value(
            "Employee", {"user_id": m.demo_email("employee")},
            ["reports_to", "designation"], as_dict=True)
        manager = frappe.db.get_value(
            "Employee", {"user_id": m.demo_email("sales-manager")}, "name")
        self.assertEqual(employee.reports_to, manager)
        self.assertIn(m.FA_MARKER, employee.designation)
        # Every party and every trade document uses the company currency (IRR):
        # a USD document against an IRR party account is rejected by ERPNext.
        for title in m.CUSTOMERS:
            party = frappe.db.get_value(
                "Customer", title, ["default_currency", "default_price_list"], as_dict=True)
            self.assertEqual((party.default_currency, party.default_price_list),
                             (m.CURRENCY, m.PRICE_LIST_SELLING))
        for title in m.SUPPLIERS:
            party = frappe.db.get_value(
                "Supplier", title, ["default_currency", "default_price_list"], as_dict=True)
            self.assertEqual((party.default_currency, party.default_price_list),
                             (m.CURRENCY, m.PRICE_LIST_BUYING))
        for doctype in ("Sales Invoice", "Purchase Invoice",
                        "Purchase Order", "Purchase Receipt"):
            currencies = frappe.get_all(
                doctype, filters={"company": m.COMPANY}, pluck="currency")
            self.assertTrue(currencies, doctype)
            self.assertEqual(set(currencies), {"IRR"}, doctype)

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
            # A Queued repost (scheduler off) must still reset cleanly.
            demo_items = [code for code, _title, _stock, _rate in m.ITEMS]
            for riv in frappe.get_all("Repost Item Valuation",
                                       filters={"item_code": ["in", demo_items]},
                                       pluck="name"):
                frappe.db.set_value("Repost Item Valuation", riv, "status", "Queued")
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
                            "Stock Entry", "Material Request", "Repost Item Valuation",
                            "ASOUD Party Profile",
                            "ASOUD Workflow Definition", "ASOUD Workflow Request"):
                filters = {"company": m.COMPANY}
                self.assertEqual(frappe.db.count(doctype, filters), 0, doctype)
            for title, _max_leaves in m.LEAVE_TYPES:
                self.assertFalse(frappe.db.exists("Leave Type", title))
            self.assertFalse(frappe.db.exists("Salary Structure", m.SALARY_STRUCTURE))
            for price_list in (m.PRICE_LIST_SELLING, m.PRICE_LIST_BUYING):
                self.assertFalse(frappe.db.exists("Price List", price_list))
            # Ledger rows of the seed's vouchers are purged with the vouchers.
            for table in ("GL Entry", "Stock Ledger Entry", "Payment Ledger Entry"):
                self.assertEqual(frappe.db.count(table, {"company": m.COMPANY}), 0, table)
            self.assertTrue(frappe.db.exists("Employee", unrelated))
            self.assertEqual(frappe.db.get_value("Employee", unrelated, "company"), others[0])
        finally:
            _delete_robustly("Employee", unrelated)
            frappe.db.commit()
