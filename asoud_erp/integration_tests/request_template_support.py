"""Shared helpers of the purchase, supply and leave request template integration tests.

Run on the bench like the other integration modules, for example::

    bench --site <site> run-tests --app asoud_erp --skip-test-records \
        --module asoud_erp.integration_tests.test_leave_request_template

The fixtures of ``fixtures.py`` give a requester (``EMPLOYEE_USER``) whose direct manager is
``APPROVER_USER``. The system templates are seeded once and committed, like the other fixtures;
each test then runs in a transaction that is rolled back.
"""

import json
import uuid
from contextlib import contextmanager

import frappe
from frappe.utils import add_days, getdate, nowdate

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import (
    APPROVER_USER,
    EMPLOYEE_USER,
    ITEM,
    LEAVE_TYPE,
    APITestCase,
    abbr,
    warehouse,
)
from asoud_erp.services.request_templates.seed import ensure_system_templates

DEPARTMENT = "ASOUD Request Department"
BRANCH = "ASOUD Request Branch"


def ensure_department(company: str) -> str:
    name = f"{DEPARTMENT} - {abbr()}"
    if not frappe.db.exists("Department", name):
        parent = frappe.db.get_value("Department", {"company": company, "is_group": 1}, "name")
        frappe.get_doc({"doctype": "Department", "department_name": DEPARTMENT, "company": company,
                        "parent_department": parent or "All Departments"}).insert(ignore_permissions=True)
    return name


def ensure_branch() -> str:
    if not frappe.db.exists("Branch", BRANCH):
        frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
    return BRANCH


def weekday(offset: int) -> str:
    """The first Monday-to-Friday date at or after today + ``offset`` days."""
    day = getdate(add_days(nowdate(), offset))
    while day.weekday() >= 5:
        day = getdate(add_days(day, 1))
    return str(day)


def error_codes() -> list:
    """Error codes (message ``title``) queued by the last ``frappe.throw``."""
    codes = []
    for entry in frappe.local.message_log or []:
        entry = entry if isinstance(entry, dict) else json.loads(entry)
        codes.append(entry.get("title"))
    return codes


class TemplateTestCase(APITestCase):
    """Requester session, seeded templates, one-company defaults and request helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        ensure_system_templates(cls.company)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.department = ensure_department(self.company)
        self.branch = ensure_branch()
        frappe.db.set_value("Employee", self.records["employee"], {"department": self.department,
                                                                     "branch": self.branch})
        frappe.db.set_value("Company", self.company, {"asoud_daily_working_hours": 8,
                                                      "asoud_request_cost_center_required": 0})
        frappe.db.set_value("Leave Type", LEAVE_TYPE, "asoud_leave_category", "annual")
        frappe.db.set_single_value("Stock Settings", "default_warehouse", warehouse())
        frappe.set_user(EMPLOYEE_USER)

    # ---------------------------------------------------------------- assertions

    @contextmanager
    def assertCode(self, code: str):
        """The block raises a ValidationError whose message title is the contract error ``code``."""
        frappe.clear_messages()
        with self.assertRaises(frappe.ValidationError):
            yield
        self.assertIn(code, error_codes())

    def assertNotified(self, request_name: str, user: str):
        """``user`` got an in-app alert about request ``request_name`` (or about its workflow instance)."""
        instance = self.row(request_name).workflow_instance
        self.assertTrue(frappe.db.exists("Notification Log", {
            "for_user": user, "subject": ["like", f"%{request_name}%"],
            "document_name": ["in", [request_name, instance]]}), f"{user} was not notified about {request_name}")

    # ---------------------------------------------------------------- requests

    def create(self, template_key: str, values: dict, subject: str = "", request_id: str | None = None) -> dict:
        return workflow_request.create_request(
            company=self.company, template_key=template_key, subject=subject,
            request_id=request_id or f"test-{uuid.uuid4().hex}", values=json.dumps(values))["data"]

    def decide(self, name: str, action: str = "Approve", comment: str = "ok", probe_session: bool = False) -> None:
        """The direct manager decides the open approval task of request ``name``.

        With ``probe_session`` the approver gets a recognisable ``sid`` and ``session.data`` first
        (``frappe.set_user`` would reset both); they must be exactly the same objects and values when
        the decision, including the post-approval hook, is done.
        """
        from asoud_erp.api.v1.workflow_runtime import complete_workflow_task

        user = frappe.session.user
        try:
            frappe.set_user(APPROVER_USER)
            sid, data = "sid-of-the-approver", frappe._dict(csrf_token="csrf-of-the-approver")
            form_dict = frappe.local.form_dict
            if probe_session:
                frappe.session.sid, frappe.session.data = sid, data
            instance = frappe.db.get_value("ASOUD Workflow Request", name, "workflow_instance")
            task = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": instance, "status": "Open", "assigned_to": APPROVER_USER}, "name")
            complete_workflow_task(task, action, comment=comment)
            if probe_session:
                self.assertEqual(frappe.session.user, APPROVER_USER)
                self.assertEqual(frappe.session.sid, sid)
                self.assertIs(frappe.session.data, data)
                self.assertEqual(dict(frappe.session.data), {"csrf_token": "csrf-of-the-approver"})
                self.assertIs(frappe.local.form_dict, form_dict)
        finally:
            frappe.set_user(user)

    def row(self, name: str):
        return frappe.db.get_value(
            "ASOUD Workflow Request", name,
            ["name", "template_key", "status_key", "native_doctype", "native_name", "native_status",
             "native_error", "workflow_instance", "subject", "required_by", "department", "priority"],
            as_dict=True)

    def instance_status(self, name: str) -> str:
        return frappe.db.get_value("ASOUD Workflow Instance", self.row(name).workflow_instance, "status")

    # ---------------------------------------------------------------- values

    def requester(self) -> dict:
        return {"requester": EMPLOYEE_USER, "org_unit": self.department}

    def purchase_values(self, **extra) -> dict:
        return {**self.requester(), "needed_date": weekday(10), "priority": "High", "reason": "تجهیز واحد",
                "items": [{"item_code": ITEM, "qty": 2, "uom": "Nos", "description": "شرح", "note": "یادداشت"}],
                **extra}


def make_leave_type(name: str, days: float, category: str = "annual", employee: str | None = None) -> str:
    """A Leave Type with an allocation for the requester for the current year (rolled back)."""
    from frappe.utils import get_year_ending, get_year_start

    if not frappe.db.exists("Leave Type", name):
        frappe.get_doc({"doctype": "Leave Type", "leave_type_name": name, "max_leaves_allowed": days,
                        "asoud_leave_category": category}).insert(ignore_permissions=True)
    employee = employee or frappe.db.get_value("Employee", {"user_id": EMPLOYEE_USER}, "name")
    previous = frappe.session.user
    try:
        frappe.set_user("Administrator")
        frappe.get_doc({"doctype": "Leave Allocation", "employee": employee, "leave_type": name,
                        "from_date": get_year_start(nowdate()), "to_date": get_year_ending(nowdate()),
                        "new_leaves_allocated": days}).submit()
    finally:
        frappe.set_user(previous)
    return name
