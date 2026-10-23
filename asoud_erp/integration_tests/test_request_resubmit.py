"""A request returned for correction can be edited by its owner and is resubmitted."""

import json

import frappe

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create, open_task, status_key


class TestRequestResubmit(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=2)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل اولیه"})
        self.instance = self.request["workflow_instance"]

    def _detail(self, user=EMPLOYEE_USER):
        frappe.set_user(user)
        return workflow_request.get_request(self.request["name"])["data"]

    def _edit(self, user=EMPLOYEE_USER, reason="دلیل اصلاح‌شده"):
        frappe.set_user(user)
        return workflow_request.update_request(
            self.request["name"], values=json.dumps({"reason": reason}))["data"]

    def _return_from_second_stage(self):
        act(self.instance, "Approve")
        act(self.instance, "Return", comment="مبلغ را اصلاح کنید")

    def test_returned_request_is_editable_by_its_owner_with_the_reason(self):
        self._return_from_second_stage()
        detail = self._detail()
        self.assertEqual(detail["status_key"], "returned")
        self.assertEqual(detail["return_reason"], "مبلغ را اصلاح کنید")
        self.assertTrue(detail["can_edit"])
        self.assertEqual(self._edit()["values"]["reason"], "دلیل اصلاح‌شده")

    def test_resubmitting_records_the_change_and_restarts_from_the_first_review_stage(self):
        self._return_from_second_stage()
        self._edit()
        detail = self._detail()
        self.assertIn(detail["status_key"], ("submitted", "in_review"))
        self.assertFalse(detail["can_edit"])
        self.assertEqual(detail["return_reason"], "")
        activity = frappe.get_all(
            "ASOUD Workflow Activity", filters={"workflow_instance": self.instance, "action": "Resubmitted"},
            fields=["change_json", "actor"])
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0].actor, EMPLOYEE_USER)
        self.assertEqual(json.loads(activity[0].change_json),
                         {"before": {"reason": "دلیل اولیه"}, "after": {"reason": "دلیل اصلاح‌شده"}})
        # Stage 1 reviews again: the open task is the first approval, not the returning one.
        task = open_task(self.instance, APPROVER_USER)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", frappe.db.get_value(
            "ASOUD Workflow Task", task.name, "workflow_stage"), "stage_title"), "تأیید 1")
        # Nothing is deleted: both the old approval and the return stay in the history.
        actions = [row.action for row in frappe.get_all(
            "ASOUD Workflow Task", filters={"workflow_instance": self.instance}, fields=["action"])]
        self.assertIn("Return", actions)
        self.assertGreaterEqual(actions.count("Approve"), 1)

    def test_a_second_resubmit_is_refused(self):
        self._return_from_second_stage()
        self._edit()
        with self.assertRaises(frappe.ValidationError):
            self._edit(reason="دوباره")
        self.assertEqual(self._detail()["values"]["reason"], "دلیل اصلاح‌شده")

    def test_only_the_owner_can_resubmit(self):
        self._return_from_second_stage()
        with self.assertRaises(frappe.PermissionError):
            self._edit(user=APPROVER_USER)
        self.assertEqual(status_key(self.request["name"]), "returned")

    def test_an_approved_request_cannot_be_edited(self):
        act(self.instance, "Approve")
        act(self.instance, "Approve")
        self.assertEqual(status_key(self.request["name"]), "approved")
        self.assertFalse(self._detail()["can_edit"])
        with self.assertRaises(frappe.ValidationError):
            self._edit()

    def test_a_rejected_or_cancelled_request_cannot_be_edited(self):
        act(self.instance, "Reject", comment="رد شد")
        self.assertFalse(self._detail()["can_edit"])
        with self.assertRaises(frappe.ValidationError):
            self._edit()
        other = create(self.company, definition=self.definition, values={"reason": "دیگر"})
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.cancel_request(other["name"])
        with self.assertRaises(frappe.ValidationError):
            workflow_request.update_request(other["name"], values=json.dumps({"reason": "x"}))

    def test_a_request_that_was_never_returned_keeps_the_first_edit_rules(self):
        self.assertTrue(self._detail()["can_edit"])
        self.assertEqual(self._detail()["return_reason"], "")
        self._edit()
        act(self.instance, "Approve")
        self.assertFalse(self._detail()["can_edit"])
