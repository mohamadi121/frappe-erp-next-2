"""`get_request.viewer` is derived from the signed-in user's own open task."""

import frappe

from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import ACCOUNTANT_USER, APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create, open_task


class TestRequestViewer(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل"})

    def _viewer(self, user):
        frappe.set_user(user)
        return workflow_request.get_request(self.request["name"])["data"]["viewer"]

    def test_the_owner_has_no_action_card(self):
        self.assertEqual(self._viewer(EMPLOYEE_USER), {"is_requester": True, "open_task": None})

    def test_the_assignee_gets_the_stage_flags_and_is_not_the_requester(self):
        viewer = self._viewer(APPROVER_USER)
        task = open_task(self.request["workflow_instance"], APPROVER_USER)
        self.assertFalse(viewer["is_requester"])
        self.assertEqual(viewer["open_task"], {
            "name": task.name, "stage_title": "تأیید 1", "stage_type": "Approval", "approve_action": "Approve",
            "allow_reject": True, "allow_return": True, "comment_required": False,
            "reject_comment_required": True, "has_form": False})

    def test_a_user_who_is_not_assigned_cannot_read_the_request_or_its_task(self):
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(self.request["name"])

    def test_the_card_disappears_after_the_decision(self):
        act(self.request["workflow_instance"], "Approve")
        self.assertEqual(self._viewer(APPROVER_USER), {"is_requester": False, "open_task": None})

    def test_a_returned_request_offers_the_requester_their_own_task(self):
        act(self.request["workflow_instance"], "Return", comment="اصلاح کنید")
        viewer = self._viewer(EMPLOYEE_USER)
        self.assertTrue(viewer["is_requester"])
        self.assertEqual(viewer["open_task"]["stage_type"], "User Task")
        self.assertEqual(viewer["open_task"]["approve_action"], "Complete")
        self.assertTrue(viewer["open_task"]["has_form"])

    def test_the_task_names_its_request_and_the_assignee_can_open_it(self):
        task = open_task(self.request["workflow_instance"], APPROVER_USER)
        frappe.set_user(APPROVER_USER)
        data = workflow_runtime.get_workflow_task(task.name)["data"]
        request_name = data["request_name"]
        self.assertEqual(data["request_company"], self.company)
        self.assertEqual(request_name, self.request["name"])
        self.assertEqual(workflow_request.get_request(request_name)["data"]["name"], self.request["name"])
