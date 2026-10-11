import frappe
from frappe.utils import add_to_date, now_datetime

from asoud_erp.api.v1 import projects
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase, _user
from asoud_erp.integration_tests.tenancy import _employee, setup_tenancy

PROJECTS_A_USER = "asoud.scope-projects-user@example.com"


class TestProjects(APITestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Activity Type", "ASOUD Work"):
            frappe.get_doc({"doctype": "Activity Type", "activity_type": "ASOUD Work"}).insert()
        frappe.db.delete("Task")
        frappe.db.delete("ToDo", {"allocated_to": EMPLOYEE_USER})
        frappe.db.delete("Project", {"project_name": "پروژه آزمایشی"})
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


class TestProjectTaskCompanyScope(APITestCase):
    """A Task has no company column; its project's company is the tenant guard.

    `update_task_status` let any Projects Manager/User save any task with
    `ignore_permissions=True` and never tied it to a company (F-P5). A manager
    may only move tasks of projects in a company they can access; an assignee
    keeps moving their own task regardless of the project company.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        if not frappe.db.exists("Activity Type", "ASOUD Work"):
            frappe.get_doc({"doctype": "Activity Type", "activity_type": "ASOUD Work"}).insert()
        _user(PROJECTS_A_USER, ["Projects User", "Employee"])
        _employee(PROJECTS_A_USER, "Scope Projects A", cls.scope["first"])
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # create_task's assign-to commits, so the rows of the previous test are
        # real rows, not rolled-back ones; remove them by the fixed names.
        frappe.db.delete("ToDo", {"allocated_to": EMPLOYEE_USER})
        for project_name in ("پروژه خارجی", "پروژه داخلی"):
            project = frappe.db.get_value("Project", {"project_name": project_name}, "name")
            if project:
                frappe.db.delete("Task", {"project": project})
                frappe.db.delete("Project", project)
        project_b = projects.create_project(self.second, "پروژه خارجی", notes="")["data"]
        self.task_b = projects.create_task(project_b["name"], "کار خارجی")["data"]["name"]
        self.assigned_b = projects.create_task(project_b["name"], "کار خارجی من",
                                               assign_to=[EMPLOYEE_USER])["data"]["name"]
        project_a = projects.create_project(self.company, "پروژه داخلی", notes="")["data"]
        self.task_a = projects.create_task(project_a["name"], "کار داخلی")["data"]["name"]

    def test_a_manager_cannot_move_a_task_of_a_foreign_company(self):
        frappe.set_user(PROJECTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            projects.update_task_status(self.task_b, "Working")
        self.assertEqual(frappe.db.get_value("Task", self.task_b, "status"), "Open")

    def test_a_manager_can_move_a_task_of_the_own_company(self):
        frappe.set_user(PROJECTS_A_USER)
        moved = projects.update_task_status(self.task_a, "Working", progress=40)["data"]
        self.assertEqual((moved["status"], moved["progress"]), ("Working", 40))

    def test_an_assignee_still_moves_their_task_regardless_of_the_project_company(self):
        frappe.set_user(EMPLOYEE_USER)
        moved = projects.update_task_status(self.assigned_b, "Working", progress=40)["data"]
        self.assertEqual((moved["status"], moved["progress"]), ("Working", 40))
