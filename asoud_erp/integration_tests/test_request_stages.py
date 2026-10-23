"""The step list on a request and actor names on the instance history."""

import frappe

from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create


class TestRequestStages(APITestCase):
    def setUp(self):
        super().setUp()
        definition, _stages = make_definition(self.company, approvals=2)
        self.request = create(self.company, definition=definition)

    def _stages(self):
        frappe.set_user(EMPLOYEE_USER)
        return workflow_request.get_request(self.request["name"])["data"]["stages"]

    def test_stages_follow_the_real_instance(self):
        rows = self._stages()
        self.assertEqual([row["title"] for row in rows], ["ثبت درخواست", "تأیید 1", "تأیید 2"])
        self.assertEqual([row["status"] for row in rows], ["done", "active", "pending"])
        self.assertEqual(rows[2]["assigned_on"], "")
        self.assertTrue(rows[1]["assignee_names"])
        act(self.request["workflow_instance"], "Approve")
        self.assertEqual([row["status"] for row in self._stages()], ["done", "done", "active"])

    def test_history_rows_carry_the_actor_full_name(self):
        act(self.request["workflow_instance"], "Approve", comment="تأیید شد")
        frappe.set_user(EMPLOYEE_USER)
        data = workflow_runtime.get_workflow_instance(self.request["workflow_instance"])["data"]
        approve = [row for row in data["activities"] if row["action"] == "Approve"][0]
        self.assertEqual(approve["actor"], APPROVER_USER)
        self.assertEqual(approve["actor_name"], frappe.db.get_value("User", APPROVER_USER, "full_name"))
