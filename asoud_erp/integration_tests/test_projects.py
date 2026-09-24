import frappe
from frappe.utils import add_to_date, now_datetime

from asoud_erp.api.v1 import projects
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase


class TestProjects(APITestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Activity Type", "ASOUD Work"):
            frappe.get_doc({"doctype": "Activity Type", "activity_type": "ASOUD Work"}).insert()
        self.project = projects.create_project(self.company, "پروژه آزمایشی", notes="یادداشت")["data"]
        self.task = projects.create_task(self.project["name"], "طراحی فرم", priority="High",
                                         assign_to=[EMPLOYEE_USER])["data"]

    def test_assignee_moves_task_and_logs_time(self):
        self.assertEqual(self.task["assigned_to"], [EMPLOYEE_USER])
        frappe.set_user(EMPLOYEE_USER)
        mine = projects.list_my_tasks()["data"]
        self.assertEqual([row.name for row in mine], [self.task["name"]])
        moved = projects.update_task_status(self.task["name"], "Working", progress=40)["data"]
        self.assertEqual((moved["status"], moved["progress"]), ("Working", 40))
        start = add_to_date(now_datetime(), hours=-3)
        sheet = projects.create_timesheet([{"activity_type": "ASOUD Work", "from_time": str(start), "hours": 2,
                                            "task": self.task["name"], "description": "پیاده‌سازی"}])["data"]
        self.assertEqual((sheet["docstatus"], sheet["total_hours"]), (0, 2))
        self.assertEqual(sheet["time_logs"][0]["project"], self.project["name"])
        self.assertEqual(projects.list_my_timesheets()["data"][0].name, sheet["name"])
        frappe.set_user("Administrator")
        self.assertEqual(projects.submit_timesheet(sheet["name"])["data"]["docstatus"], 1)
        detail = projects.get_project(self.project["name"])["data"]
        self.assertEqual(detail["tasks"][0]["status"], "Working")

    def test_others_cannot_touch_the_task(self):
        frappe.set_user(APPROVER_USER)
        self.assertEqual(projects.list_my_tasks()["data"], [])
        with self.assertRaises(frappe.PermissionError):
            projects.update_task_status(self.task["name"], "Completed")
        with self.assertRaises(frappe.PermissionError):
            projects.create_timesheet([{"activity_type": "ASOUD Work", "from_time": str(now_datetime()),
                                        "hours": 1, "task": self.task["name"]}])
        with self.assertRaises(frappe.PermissionError):
            projects.list_projects(self.company)

    def test_invalid_input(self):
        with self.assertRaises(frappe.ValidationError):
            projects.update_task_status(self.task["name"], "Done")
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            projects.create_timesheet([{"activity_type": "ASOUD Work", "from_time": str(now_datetime()),
                                        "hours": 30}])
