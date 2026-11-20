"""Real-site tests for multi-approver decision modes (PA-067).

An Approval stage can require Any, All or Majority of its approvers. The
runtime counts Approve decisions per activation round and advances the stage
only when the configured mode is satisfied; a Reject or Return still cancels
the whole stage.
"""

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy

# Three independent approvers (none is the request initiator).
APPROVERS = [APPROVER_USER, ACCOUNTANT_USER, MANAGER_USER]


class TestApprovalQuorum(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Creates MANAGER_USER (an Employee of the default company) as a third approver.
        setup_tenancy()

    def _definition(self, mode, approvers=APPROVERS):
        definition, _stages = make_definition(self.company, approvals=1)
        stage = frappe.get_doc("ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Approval"})
        config = frappe.parse_json(stage.config_json)
        config.update(assignment_type="Employee", approver_employees=[
            frappe.db.get_value("Employee", {"user_id": user}) for user in approvers])
        config["approval_mode"] = mode
        stage.config_json = frappe.as_json(config)
        stage.save(ignore_permissions=True)
        return definition

    def _request(self, mode, approvers=APPROVERS):
        return create(self.company, definition=self._definition(mode, approvers), values={"reason": "دلیل"})

    def _open_count(self, instance):
        return frappe.db.count("ASOUD Workflow Task", {
            "workflow_instance": instance, "status": "Open"})

    def _instance(self, name):
        return frappe.get_doc("ASOUD Workflow Instance", name)

    def test_majority_advances_when_more_than_half_approve(self):
        request = self._request("Majority")
        instance = request["workflow_instance"]
        act(instance, "Approve", user=APPROVERS[0])
        # 1 of 3 is not a majority: the stage is still running.
        self.assertEqual(self._instance(instance).status, "Running")
        self.assertEqual(self._open_count(instance), 2)
        act(instance, "Approve", user=APPROVERS[1])
        # 2 of 3 is a majority: the stage advances to End and completes.
        self.assertEqual(self._instance(instance).status, "Completed")
        self.assertEqual(self._open_count(instance), 0)

    def test_majority_first_approval_keeps_the_stage_running(self):
        request = self._request("Majority")
        instance = request["workflow_instance"]
        act(instance, "Approve", user=APPROVERS[0])
        self.assertEqual(self._instance(instance).status, "Running")
        # The other two approvers keep their Open tasks.
        self.assertEqual(sorted(self._open_assignees(instance)), sorted(APPROVERS[1:]))
        # A Persian activity explains how many more approvals are needed.
        comments = frappe.get_all("ASOUD Workflow Activity",
            filters={"workflow_instance": instance, "action": "Approve"}, pluck="comment")
        self.assertTrue(any("۱ تأیید دیگر لازم است" in (c or "") for c in comments))

    def test_all_mode_requires_every_approver(self):
        request = self._request("All")
        instance = request["workflow_instance"]
        act(instance, "Approve", user=APPROVERS[0])
        self.assertEqual(self._instance(instance).status, "Running")
        self.assertEqual(self._open_count(instance), 2)
        act(instance, "Approve", user=APPROVERS[1])
        self.assertEqual(self._instance(instance).status, "Running")
        self.assertEqual(self._open_count(instance), 1)
        act(instance, "Approve", user=APPROVERS[2])
        self.assertEqual(self._instance(instance).status, "Completed")
        self.assertEqual(self._open_count(instance), 0)

    def test_any_mode_advances_on_the_first_approval(self):
        request = self._request("Any")
        instance = request["workflow_instance"]
        act(instance, "Approve", user=APPROVERS[0])
        self.assertEqual(self._instance(instance).status, "Completed")
        # The other approvers' tasks are cancelled, not left dangling.
        self.assertEqual(self._open_count(instance), 0)
        cancelled = frappe.db.count("ASOUD Workflow Task", {
            "workflow_instance": instance, "status": "Cancelled"})
        self.assertEqual(cancelled, 2)

    def test_reject_still_cancels_the_whole_stage(self):
        request = self._request("Majority")
        instance = request["workflow_instance"]
        act(instance, "Approve", user=APPROVERS[0])
        act(instance, "Reject", comment="رد شد", user=APPROVERS[1])
        self.assertEqual(self._instance(instance).status, "Rejected")
        self.assertEqual(self._open_count(instance), 0)

    def test_save_stage_settings_rejects_an_unknown_mode(self):
        definition, _stages = make_definition(self.company, approvals=1)
        frappe.db.set_value("ASOUD Workflow Definition", definition, "status", "Inactive")
        stage = frappe.get_doc("ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Approval"})
        with self.assertRaisesRegex(frappe.ValidationError, "حالت رأی‌گیری مرحلهٔ تأیید نامعتبر است"):
            workflow.save_stage_settings(definition, stage.name, {
                "title": "تأیید", "assignment_type": "Employee",
                "approver_employees": [frappe.db.get_value("Employee", {"user_id": APPROVER_USER})],
                "approval_mode": "Quorum"})

    def test_save_stage_settings_accepts_majority(self):
        definition, _stages = make_definition(self.company, approvals=1)
        frappe.db.set_value("ASOUD Workflow Definition", definition, "status", "Inactive")
        stage = frappe.get_doc("ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Approval"})
        workflow.save_stage_settings(definition, stage.name, {
            "title": "تأیید", "assignment_type": "Employee",
            "approver_employees": [frappe.db.get_value("Employee", {"user_id": APPROVER_USER})],
            "approval_mode": "Majority"})
        saved = frappe.parse_json(frappe.db.get_value("ASOUD Workflow Stage", stage.name, "config_json"))
        self.assertEqual(saved["approval_mode"], "Majority")

    def _open_assignees(self, instance):
        return frappe.get_all("ASOUD Workflow Task", filters={
            "workflow_instance": instance, "status": "Open"}, pluck="assigned_to")
