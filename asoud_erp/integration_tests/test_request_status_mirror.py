"""`status_key` follows the workflow instance through the lifecycle hook."""

import frappe

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, ITEM, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create, open_task, status_key


class TestRequestStatusMirror(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=2)

    def _create(self):
        return create(self.company, definition=self.definition, values={"reason": "دلیل"})

    def test_a_new_request_is_submitted(self):
        request = self._create()
        self.assertEqual(status_key(request["name"]), "submitted")
        self.assertEqual((request["status_key"], request["status_group"], request["status_label"]),
                         ("submitted", "pending", "ارسال شده"))

    def test_the_first_approval_of_two_puts_it_in_review_and_the_second_approves_it(self):
        request = self._create()
        act(request["workflow_instance"], "Approve")
        self.assertEqual(status_key(request["name"]), "in_review")
        act(request["workflow_instance"], "Approve")
        self.assertEqual(status_key(request["name"]), "approved")
        frappe.set_user(EMPLOYEE_USER)
        detail = workflow_request.get_request(request["name"])["data"]
        self.assertEqual((detail["status"], detail["status_key"], detail["status_group"]),
                         ("Completed", "approved", "approved"))
        self.assertFalse(detail["can_cancel"])

    def test_reject_sets_rejected(self):
        request = self._create()
        act(request["workflow_instance"], "Reject", comment="مقدور نیست")
        self.assertEqual(status_key(request["name"]), "rejected")
        frappe.set_user(EMPLOYEE_USER)
        detail = workflow_request.get_request(request["name"])["data"]
        self.assertEqual((detail["status"], detail["rejection_reason"]), ("Rejected", "مقدور نیست"))

    def test_return_sets_returned_and_resubmitting_goes_back_to_review(self):
        request = self._create()
        act(request["workflow_instance"], "Return", comment="لطفاً اصلاح کنید")
        self.assertEqual(status_key(request["name"]), "returned")
        task = open_task(request["workflow_instance"], EMPLOYEE_USER)
        self.assertIsNotNone(task)
        # The requester fixes the form from the cartable; it is submitted again.
        act(request["workflow_instance"], "Complete", user=EMPLOYEE_USER, response={
            "requester": EMPLOYEE_USER, "priority": "High", "reason": "اصلاح‌شده",
            "items": [{"item_code": ITEM, "qty": 3}]})
        self.assertEqual(status_key(request["name"]), "in_review")
        frappe.set_user(EMPLOYEE_USER)
        detail = workflow_request.get_request(request["name"])["data"]
        self.assertEqual(detail["values"]["reason"], "اصلاح‌شده")  # the cartable edit is visible
        self.assertEqual(detail["values"]["items"][0]["qty"], 3)

    def test_cancel_sets_cancelled(self):
        request = self._create()
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.cancel_request(request["name"], "نیاز نیست")
        self.assertEqual(status_key(request["name"]), "cancelled")
        detail = workflow_request.get_request(request["name"])["data"]
        self.assertEqual((detail["status"], detail["status_label"], detail["status_group"]),
                         ("Cancelled", "لغو شده", ""))
        self.assertFalse(detail["can_edit"])

    def test_the_approver_is_not_the_owner(self):
        request = self._create()
        frappe.set_user(APPROVER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.cancel_request(request["name"])
        self.assertEqual(status_key(request["name"]), "submitted")
