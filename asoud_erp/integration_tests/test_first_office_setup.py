"""Native first HR account provisioning and Persian input errors on a real site."""

import frappe
from frappe.utils.password import check_password

from asoud_erp.api.v1 import first_office_setup
from asoud_erp.integration_tests import fixtures
from asoud_erp.services import account_state


class TestFirstOfficeSetup(fixtures.APITestCase):
    def setUp(self):
        super().setUp()
        self.username = "lead_" + frappe.generate_hash(length=12).lower()
        self.contact = self.username + "@example.com"
        settings = frappe.get_single("ASOUD Settings")
        settings.first_office_company = self.company
        settings.save(ignore_permissions=True)
        if not frappe.db.exists("ASOUD Company Setup", self.company):
            doc = frappe.get_doc({"doctype": "ASOUD Company Setup", "company": self.company})
        else:
            doc = frappe.get_doc("ASOUD Company Setup", self.company)
        doc.flags.first_office_bootstrap = True
        doc.update({"office_saved": 1, "first_hr_user": None, "bootstrap_completed": 0})
        doc.save(ignore_permissions=True)
        frappe.get_doc({"doctype": "Fiscal Year", "year": "Lead " + self.username,
                        "year_start_date": "2041-01-01", "year_end_date": "2041-12-31",
                        "companies": [{"company": self.company}]}).insert(ignore_permissions=True)

    def create(self, **overrides):
        return first_office_setup.create_hr_lead(**{
            "company": self.company, "full_name": "علی رضایی", "username": self.username,
            "contact": self.contact, "temporary_password": "Secure-Lead-Password-42", **overrides,
        })["data"]

    def test_valid_lead_without_employee_and_idempotent_retry(self):
        employees = frappe.db.count("Employee")
        people = frappe.db.count("ASOUD Party Profile")
        result = self.create()
        self.assertTrue(result["hr_ready"])
        self.assertEqual(result["hr_lead"]["username"], self.username)
        self.assertEqual(check_password(self.contact, "Secure-Lead-Password-42"), self.contact)
        self.assertIn("HR Manager", frappe.get_roles(self.contact))
        self.assertNotIn("System Manager", frappe.get_roles(self.contact))
        self.assertTrue(account_state.get(self.contact)["must_change_password"])
        self.assertTrue(frappe.db.exists("User Permission", {
            "user": self.contact, "allow": "Company", "for_value": self.company,
        }))
        self.assertEqual(frappe.db.count("Employee"), employees)
        self.assertEqual(frappe.db.count("ASOUD Party Profile"), people)
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual(self.create(temporary_password="ignored"), dict(result, idempotent_replay=True))
        self.assertEqual(check_password(self.contact, "Secure-Lead-Password-42"), self.contact)

    def test_status_during_provisioning_lock_never_reports_a_false_empty_lead(self):
        # A separate native connection represents a provisioning transaction holding
        # the shared company lock. No fixture state needs to be committed.
        connection = frappe.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION")
                cursor.execute("SELECT name FROM tabCompany WHERE name=%s FOR UPDATE", (self.company,))
            with self.assertRaisesRegex(frappe.ValidationError, "ثبت مسئول منابع انسانی هنوز در جریان است"):
                first_office_setup.status(self.company)
        finally:
            connection.rollback()
            connection.close()
        self.assertIsNone(first_office_setup.status(self.company)["data"]["hr_lead"])
        created = self.create()
        status = first_office_setup.status(self.company)["data"]
        self.assertEqual(status["hr_lead"]["username"], self.username)
        changed_username = "changed_" + frappe.generate_hash(length=10).lower()
        retry = self.create(username=changed_username, contact="changed_" + self.contact,
                            temporary_password="Changed-Password-42")
        self.assertTrue(retry["idempotent_replay"])
        self.assertEqual(retry["hr_lead"], created["hr_lead"])
        self.assertEqual(retry["hr_lead"]["username"], self.username)
        self.assertFalse(frappe.db.exists("User", {"username": changed_username}))
        self.assertEqual(check_password(self.contact, "Secure-Lead-Password-42"), self.contact)

    def test_duplicate_username_names_the_field(self):
        frappe.get_doc({"doctype": "User", "email": "other_" + self.contact,
                        "first_name": "Existing", "username": self.username,
                        "send_welcome_email": 0}).insert(ignore_permissions=True)
        with self.assertRaisesRegex(frappe.ValidationError, "نام کاربری قبلاً"):
            self.create()
        self.assertFalse(frappe.db.exists("User", self.contact))

    def test_invalid_inputs_do_not_create_accounts(self):
        for values, message in [
            ({"username": "1invalid"}, "نام کاربری"),
            ({"username": "a" * 41}, "نام کاربری"),
            ({"contact": None}, "شماره موبایل یا ایمیل"),
            ({"temporary_password": "short"}, "رمز موقت"),
            ({"temporary_password": "12345678"}, "رمز موقت"),
        ]:
            with self.subTest(values=values):
                with self.assertRaisesRegex(frappe.ValidationError, message):
                    self.create(**values)
                self.assertFalse(frappe.db.exists("User", self.contact))

    def test_non_admin_cannot_provision(self):
        frappe.set_user(fixtures.EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            self.create()

    def test_native_password_policy_failure_is_persian(self):
        settings = frappe.get_single("System Settings")
        settings.enable_password_policy = 1
        settings.minimum_password_score = "4"
        settings.save(ignore_permissions=True)
        frappe.clear_cache(doctype="System Settings")
        with self.assertRaisesRegex(frappe.ValidationError, "رمز موقت ضعیف"):
            self.create(temporary_password="password")
        self.assertFalse(frappe.db.exists("User", self.contact))
