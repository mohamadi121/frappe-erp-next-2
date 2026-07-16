import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1.setup import (
    get_setup_status,
    save_office,
    update_company_settings,
    update_enabled_roles,
)


class TestASOUDCompanySetup(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
                ignore_permissions=True
            )
        self.company_name = f"ASOUD Setup Test {frappe.generate_hash(length=6)}"

    def test_complete_personal_office_flow_is_persistent(self):
        office = save_office("Personal", self.company_name)
        company = office["data"]["company"]
        self.assertTrue(frappe.db.exists("Company", company))
        self.assertFalse(office["data"]["complete"])

        settings = update_company_settings(company, "Toman", 1, "Iran Standard", 1)
        self.assertTrue(settings["data"]["accounting_saved"])

        completed = update_enabled_roles(company, ["Accounts Manager"])
        self.assertTrue(completed["data"]["complete"])
        self.assertIn("System Manager", completed["data"]["enabled_roles"])

        restored = get_setup_status(company)
        self.assertTrue(restored["data"]["complete"])

    def test_duplicate_retry_returns_the_existing_setup(self):
        first = save_office("Personal", self.company_name)
        second = save_office("Personal", self.company_name)
        self.assertEqual(first["data"]["company"], second["data"]["company"])

    def test_invalid_legal_id_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            save_office("Legal", self.company_name, national_id="11111111111")
