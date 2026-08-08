import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1.party import save_party
from asoud_erp.api.v1.setup import save_office

test_ignore = ["Company", "Customer", "Supplier", "Employee", "Gender"]


class TestASOUDPartyProfile(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
                ignore_permissions=True
            )
        for gender in ("Male", "Female", "Other"):
            if not frappe.db.exists("Gender", gender):
                frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(
                    ignore_permissions=True
                )
        office = save_office(
            "Personal", f"ASOUD Employee Test {frappe.generate_hash(length=6)}"
        )
        self.company = office["data"]["company"]

    def test_employee_role_creates_and_updates_one_erpnext_employee(self):
        created = save_party(
            party_type="Individual",
            display_name="ASOUD Test Employee",
            roles=["Employee"],
            company=self.company,
            employee_gender="Male",
            birth_date="1990-01-01",
            date_of_joining="2026-01-01",
            primary_role="Employee",
        )
        profile_name = created["data"]["name"]
        profile = frappe.get_doc("ASOUD Party Profile", profile_name)
        employee_name = profile.employee

        self.assertTrue(frappe.db.exists("Employee", employee_name))
        employee = frappe.get_doc("Employee", employee_name)
        self.assertEqual(employee.company, self.company)
        self.assertEqual(employee.gender, "Male")

        save_party(
            name=profile_name,
            party_type="Individual",
            display_name="ASOUD Test Employee Updated",
            roles=["Employee"],
            company=self.company,
            employee_gender="Female",
            birth_date="1991-02-03",
            date_of_joining="2026-02-01",
            primary_role="Employee",
        )
        updated = frappe.get_doc("Employee", employee_name)
        self.assertEqual(updated.employee_name, "ASOUD Test Employee Updated")
        self.assertEqual(updated.gender, "Female")
        self.assertEqual(
            frappe.db.count("Employee", {"name": employee_name}),
            1,
        )

        details = frappe.get_all(
            "ASOUD Floating Detail",
            filters={"linked_document": profile_name, "detail_type": "Employee"},
            pluck="name",
        )
        self.assertEqual(len(details), 1)
