import frappe

from asoud_erp.api.v1 import projects
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import EMPLOYEE_A_USER, setup_tenancy


class TestProjectsTimesheet(APITestCase):
    """SEC-BP-05: create_timesheet must not accept a foreign or unvalidated project."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        if not frappe.db.exists("Activity Type", "ASOUD Work"):
            frappe.get_doc({"doctype": "Activity Type", "activity_type": "ASOUD Work"}).insert(ignore_permissions=True)
        cls.project_b = frappe.get_doc(
            {
                "doctype": "Project",
                "project_name": "Foreign Project B",
                "company": cls.second,
            }
        ).insert(ignore_permissions=True).name

    def test_create_timesheet_rejects_foreign_project(self):
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            projects.create_timesheet(
                [
                    {
                        "activity_type": "ASOUD Work",
                        "from_time": "2026-01-05 09:00:00",
                        "hours": 8,
                        "project": self.project_b,
                    }
                ]
            )
        self.assertEqual(frappe.db.count("Timesheet Detail", {"project": self.project_b}), 0)

    def test_create_timesheet_rejects_unknown_project(self):
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises((frappe.DoesNotExistError, frappe.ValidationError)):
            projects.create_timesheet(
                [
                    {
                        "activity_type": "ASOUD Work",
                        "from_time": "2026-01-05 09:00:00",
                        "hours": 8,
                        "project": "NON-EXISTENT-PROJECT-12345",
                    }
                ]
            )
