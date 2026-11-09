"""Phase 4 / Phase 8 runtime routes: Reject (scenario 5) and Return for correction (scenario 6).

Runs on a real site with real rows (no database mocks). The reject path must end the
instance as Rejected without running the approval-only stages that follow, cancel the
other open tasks, and keep the decision and its decider in the history. The return path
must reuse the same request and the same form stage (no duplicate design stage), let the
owner correct it, and send the flow back to the configured approval stage on resubmit.
"""
import json

import frappe

from asoud_erp.api.v1 import forms, workflow, workflow_request
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create, open_task, status_key


def _stage_title(instance, stage):
    return frappe.db.get_value("ASOUD Workflow Stage", stage, "stage_title")


def _open_tasks(instance):
    return frappe.get_all("ASOUD Workflow Task",
                          filters={"workflow_instance": instance, "status": "Open"},
                          fields=["name", "workflow_stage", "assigned_to"])


class TestRejectRoute(APITestCase):
    def setUp(self):
        super().setUp()
        # Three approvals so a reject at stage 2 leaves a later approval stage that must not run.
        self.definition, _stages = make_definition(self.company, approvals=3)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل اولیه"})
        self.instance = self.request["workflow_instance"]

    def test_reject_ends_the_instance_and_never_runs_later_approval_stages(self):
        act(self.instance, "Approve")          # stage 1
        act(self.instance, "Reject", comment="مبلغ اشتباه است")  # stage 2
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Rejected")
        self.assertEqual(status_key(self.request["name"]), "rejected")
        # No open task survives the ended instance.
        self.assertEqual(_open_tasks(self.instance), [])
        # The approval stage after the reject (stage 3) never received a task.
        titles = [row.stage_title for row in frappe.get_all(
            "ASOUD Workflow Task", filters={"workflow_instance": self.instance}, fields=["name"])]
        self.assertNotIn("تأیید 3", titles)

    def test_reject_keeps_the_decision_and_its_decider_in_history(self):
        act(self.instance, "Approve")
        act(self.instance, "Reject", comment="مبلغ اشتباه است")
        activity = frappe.get_all("ASOUD Workflow Activity",
                                  filters={"workflow_instance": self.instance, "action": "Reject"},
                                  fields=["actor", "comment"])
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0].actor, APPROVER_USER)
        self.assertEqual(activity[0].comment, "مبلغ اشتباه است")
        # The rejected task itself carries the reason.
        task = frappe.db.get_value("ASOUD Workflow Task",
                                   {"workflow_instance": self.instance, "status": "Rejected"},
                                   ["name", "comment"], as_dict=True)
        self.assertEqual(task.comment, "مبلغ اشتباه است")

    def test_reject_requires_a_reason(self):
        act(self.instance, "Approve")
        with self.assertRaises(frappe.ValidationError):
            act(self.instance, "Reject", comment="")
        # The instance is still running and the stage-2 task is still open.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Running")
        self.assertTrue(_open_tasks(self.instance))


class TestReturnForCorrection(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=2)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل اولیه"})
        self.instance = self.request["workflow_instance"]

    def _form_stage(self):
        return frappe.db.get_value("ASOUD Workflow Stage",
                                   {"workflow_definition": self.definition, "stage_type": "User Task"}, "name")

    def _return_from_second_stage(self):
        act(self.instance, "Approve")
        act(self.instance, "Return", comment="مبلغ را اصلاح کنید")

    def test_return_reuses_the_same_request_and_form_stage(self):
        self._return_from_second_stage()
        self.assertEqual(status_key(self.request["name"]), "returned")
        # The instance is still running and back at the same form stage (no duplicate design stage).
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Running")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "current_stage"),
                         self._form_stage())
        # The correction task is the owner's own task on the same instance.
        task = open_task(self.instance, EMPLOYEE_USER)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task.name, "workflow_instance"), self.instance)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task.name, "workflow_stage"), self._form_stage())

    def test_resubmit_returns_to_the_configured_approval_stage(self):
        self._return_from_second_stage()
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.update_request(self.request["name"], values=json.dumps({"reason": "دلیل اصلاح‌شده"}))
        # The flow restarts at the first approval stage, not the returning one.
        task = open_task(self.instance, APPROVER_USER)
        self.assertEqual(_stage_title(self.instance, frappe.db.get_value(
            "ASOUD Workflow Task", task.name, "workflow_stage")), "تأیید 1")
        self.assertIn(status_key(self.request["name"]), ("submitted", "in_review"))
        # The correction is recorded in the history of the same instance.
        self.assertTrue(frappe.db.exists("ASOUD Workflow Activity",
                                         {"workflow_instance": self.instance, "action": "Resubmitted"}))

    def test_only_the_owner_can_correct_a_returned_request(self):
        self._return_from_second_stage()
        with self.assertRaises(frappe.PermissionError):
            frappe.set_user(APPROVER_USER)
            workflow_request.update_request(self.request["name"], values=json.dumps({"reason": "دوباره"}))
        self.assertEqual(status_key(self.request["name"]), "returned")


class TestResultFormRefusesStageKind(APITestCase):
    """A Stage-kind form is the supplementary-stage concept; it must not be a task result form."""

    def _stage_form(self):
        saved = forms.save_form(self.company, {"kind": "Stage", "title": "فرم مرحله", "schema_version": 2,
                                               "sections": [{"id": "main", "title": "اصلی", "fields": [
                                                   {"key": "note", "label": "نظر", "type": "Text"}]}]},
                                client_id=frappe.generate_hash(length=24))["data"]
        published = forms.transition(saved["name"], "publish", saved["draft_version"])["data"]
        return saved["name"], published["active_revision"]

    def test_result_form_binding_refuses_a_stage_form(self):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(item for item in stages.values() if item.stage_type == "User Task")
        form, revision = self._stage_form()
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, stage.name, {
                "title": "اقدام کاربر", "activity_type": "Data Entry", "task_purpose": "Existing",
                "assignment_type": "Initiator", "action_contract_version": 1, "result_mode": "Form",
                "result_form": {"form": form, "revision": revision},
                "assignment_rule": {"basis": "Subject", "subject": "Initiator"}})
