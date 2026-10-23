"""`get_request.execution` keeps the approval apart from what was done afterwards."""

import json

import frappe

from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create

ERROR = "LEAVE_BALANCE: مانده مرخصی کافی نیست"


class TestRequestExecution(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        self.name = self.request["name"]

    def _execution(self, user=EMPLOYEE_USER):
        frappe.set_user(user)
        return workflow_request.get_request(self.name)["data"]["execution"]

    def _approve_with(self, template_key, native_status="", native_error=""):
        act(self.request["workflow_instance"], "Approve")
        frappe.db.set_value("ASOUD Workflow Request", self.name, {
            "template_key": template_key, "native_status": native_status, "native_error": native_error,
            "native_name": "DOC-1" if native_status == "Created" else ""}, update_modified=False)

    def test_a_request_without_execution_is_not_applicable_even_when_approved(self):
        act(self.request["workflow_instance"], "Approve")
        block = self._execution()
        self.assertEqual((block["state"], block["label"]), ("not_applicable", ""))

    def test_waiting_for_approval_does_not_claim_any_execution(self):
        frappe.db.set_value("ASOUD Workflow Request", self.name, "template_key", "leave", update_modified=False)
        block = self._execution()
        self.assertEqual(block["state"], "not_started")
        self.assertEqual(block["label"], "اجرا پس از تأیید نهایی انجام می‌شود")

    def test_approved_without_a_result_says_not_executed(self):
        self._approve_with("leave")
        block = self._execution()
        self.assertEqual(block["state"], "not_started")
        self.assertEqual(block["label"], "تأیید شده، اجرا انجام نشده")

    def test_a_created_native_document_is_a_success_with_its_reference(self):
        self._approve_with("leave", "Created")
        block = self._execution()
        self.assertEqual((block["state"], block["reference"]), ("succeeded", "DOC-1"))

    def test_a_failed_execution_shows_the_error_to_a_manager_only(self):
        self._approve_with("leave", "Failed", ERROR)
        owner = self._execution()
        self.assertEqual((owner["state"], owner["error"]), ("failed", ""))
        self.assertNotIn("LEAVE_BALANCE", json.dumps(owner, ensure_ascii=False))
        self.assertEqual(self._execution("Administrator")["error"], ERROR)

    def test_a_rejected_request_is_not_a_failed_execution(self):
        act(self.request["workflow_instance"], "Reject", comment="نامناسب")
        frappe.db.set_value("ASOUD Workflow Request", self.name, "template_key", "leave", update_modified=False)
        self.assertEqual(self._execution()["state"], "not_applicable")

    def test_activity_rows_carry_the_before_and_after_values(self):
        instance = frappe.get_doc("ASOUD Workflow Instance", self.request["workflow_instance"])
        if not frappe.db.has_column("ASOUD Workflow Activity", "change_json"):
            self.skipTest("run bench migrate: ASOUD Workflow Activity.change_json is not on the site yet")
        workflow_request._activity(instance, "Edited", "اصلاح", before={"reason": "الف"}, after={"reason": "ب"})
        frappe.set_user(EMPLOYEE_USER)
        rows = workflow_runtime.get_workflow_instance(instance.name)["data"]["activities"]
        edited = next(row for row in rows if row["action"] == "Edited")
        self.assertEqual((edited["before"], edited["after"]), ({"reason": "الف"}, {"reason": "ب"}))
        self.assertEqual(next(row for row in rows if row["action"] != "Edited")["before"], {})
