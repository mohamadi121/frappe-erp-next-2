"""A request returned for correction can be edited by its owner and is resubmitted."""

import json

import frappe

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, ITEM, APITestCase
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
