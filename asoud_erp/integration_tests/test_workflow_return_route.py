"""Server-side guard: a Return route must not point at an End or Wait stage.

The app blocks this in the route editor; the server is the second line of
defense. Reject -> End stays allowed (the "end as rejected" path).
"""
import json

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition


class TestWorkflowReturnRoute(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1)
        self.approval = self.stages["Approval2"]
        self.end = self.stages["End3"]
        self.user_task = self.stages["User Task1"]

    def _actions(self):
        return {json.loads(row.condition_json)["action"]: row.to_stage
                for row in frappe.get_all("ASOUD Workflow Transition",
                                          filters={"from_stage": self.approval.name},
                                          fields=["to_stage", "condition_json"])}

    def test_return_to_end_is_refused(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            workflow.save_stage_routes(self.definition, self.approval.name,
                                       {"Approve": self.end.name, "Return": self.end.name})
        self.assertIn("مسیر بازگشت برای اصلاح باید به یک ایستگاه قابل‌اجرای قبلی برود.", str(ctx.exception))

    def test_return_to_a_user_task_is_saved(self):
        workflow.save_stage_routes(self.definition, self.approval.name,
                                   {"Approve": self.end.name, "Return": self.user_task.name})
        self.assertEqual(self._actions().get("Return"), self.user_task.name)

    def test_reject_to_end_stays_allowed(self):
        workflow.save_stage_routes(self.definition, self.approval.name,
                                   {"Approve": self.end.name, "Reject": self.end.name})
        self.assertEqual(self._actions().get("Reject"), self.end.name)
