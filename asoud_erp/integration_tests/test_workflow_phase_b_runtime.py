"""Phase B runtime edge tests: cancel, double approval, replay, stale tasks, quorum,
return/resubmit history and the frozen route after a live edit.

These run on a real site (no database mocks). Each test drives the real
``complete_workflow_task`` / ``cancel_request`` endpoints and asserts the concrete
instance, task and activity rows that the behaviour must produce.
"""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create, open_task, status_key
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy

# Three independent approvers (none is the request initiator).
APPROVERS = [APPROVER_USER, ACCOUNTANT_USER, MANAGER_USER]


def _actions(instance):
    """The instance's activity actions in chronological order (oldest first)."""
    rows = frappe.get_all("ASOUD Workflow Activity",
                          filters={"workflow_instance": instance},
                          fields=["action", "created_on"],
                          order_by="created_on asc, name asc", limit_page_length=0)
    return [row.action for row in rows]


def _quorum_definition(company, mode):
    """A one-approval definition whose stage is decided by the three test approvers."""
    definition, _stages = make_definition(company, approvals=1)
    stage = frappe.get_doc("ASOUD Workflow Stage",
                           {"workflow_definition": definition, "stage_type": "Approval"})
    config = frappe.parse_json(stage.config_json)
    config.update(assignment_type="Employee", approver_employees=[
        frappe.db.get_value("Employee", {"user_id": user}) for user in APPROVERS])
    config["approval_mode"] = mode
    stage.config_json = frappe.as_json(config)
    stage.save(ignore_permissions=True)
    return definition


class TestRequesterCancel(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1)

    def test_cancel_marks_instance_and_open_tasks_cancelled(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Running")
        self.assertTrue(open_task(instance, APPROVER_USER))
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.cancel_request(request["name"], "دیگر لازم نیست")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Cancelled")
        self.assertEqual(status_key(request["name"]), "cancelled")
        self.assertFalse(frappe.db.exists("ASOUD Workflow Task",
                                          {"workflow_instance": instance, "status": "Open"}))
        self.assertEqual(frappe.db.count("ASOUD Workflow Task",
                                         {"workflow_instance": instance, "status": "Cancelled"}), 1)
        # The cancellation is recorded in the history with the requester as actor.
        self.assertEqual(frappe.get_all("ASOUD Workflow Activity",
                                        filters={"workflow_instance": instance, "action": "Cancelled"},
                                        fields=["actor", "comment"]),
                         [{"actor": EMPLOYEE_USER, "comment": "دیگر لازم نیست"}])

    def test_only_the_requester_can_cancel(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        frappe.set_user(APPROVER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.cancel_request(request["name"])
        self.assertEqual(status_key(request["name"]), "submitted")

    def test_cancelling_twice_is_refused_cleanly(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.cancel_request(request["name"], "انصراف")
        with self.assertRaises(frappe.ValidationError):
            workflow_request.cancel_request(request["name"])
        # The second attempt changed nothing: still one cancellation in the history.
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": request["workflow_instance"],
                                          "action": "Cancelled"}), 1)


class TestDoubleApproval(APITestCase):
    """A double click on the same approval task, with the stage still current.

    The app does not send a request_id, so the second click must be refused by the
    task status, not applied twice. An All-mode quorum keeps the stage current after
    the first approval, which is exactly the double-click window.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def test_second_approval_of_the_same_task_without_request_id_is_refused(self):
        request = create(self.company, definition=_quorum_definition(self.company, "All"),
                         values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        task = open_task(instance, APPROVERS[0])
        frappe.set_user(APPROVERS[0])
        with patch.object(workflow_runtime, "_notify_user"):
            workflow_runtime.complete_workflow_task(task.name, "Approve")
            # The stage is still running (1 of 3 approvals); a second click on the
            # same task must be refused, not applied twice.
            with self.assertRaises(frappe.ValidationError) as ctx:
                workflow_runtime.complete_workflow_task(task.name, "Approve")
        self.assertIn("از پیش انجام شده", str(ctx.exception))
        # No second decision was recorded: the first approval wrote its completion
        # activity plus the "one more approval needed" note, and nothing else.
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": instance, "action": "Approve"}), 2)
        self.assertEqual(frappe.db.count("ASOUD Workflow Task",
                                         {"workflow_instance": instance, "status": "Open"}), 2)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Running")


class TestNetworkReplay(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1)

    def test_replaying_an_approval_with_the_same_request_id_creates_nothing_new(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        task = open_task(instance, APPROVER_USER)
        request_id = "req-" + uuid4().hex[:12]
        frappe.set_user(APPROVER_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            first = workflow_runtime.complete_workflow_task(task.name, "Approve", request_id=request_id)
            replay = workflow_runtime.complete_workflow_task(task.name, "Approve", request_id=request_id)
        self.assertEqual(first["data"], replay["data"])
        self.assertEqual(replay["data"]["instance_status"], "Completed")
        # The replay returned the stored result: no second activity, no new task.
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": instance, "action": "Approve"}), 1)
        self.assertEqual(frappe.db.count("ASOUD Workflow Task",
                                         {"workflow_instance": instance}), 2)


class TestStaleTask(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=2)

    def test_completing_a_task_after_the_instance_moved_on_is_refused(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        old_task = open_task(instance, APPROVER_USER)
        act(instance, "Approve")  # the instance moves to the second approval stage
        frappe.set_user(APPROVER_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            with self.assertRaises(frappe.ValidationError) as ctx:
                workflow_runtime.complete_workflow_task(old_task.name, "Approve")
        self.assertIn("دیگر در مرحلهٔ جاری", str(ctx.exception))
        # The stale task was not completed a second time and no second decision was recorded.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", old_task.name, "status"), "Completed")
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": instance, "action": "Approve"}), 1)

    def test_completing_a_task_after_the_instance_was_rejected_is_refused(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        old_task = open_task(instance, APPROVER_USER)
        act(instance, "Reject", comment="رد شد")
        frappe.set_user(APPROVER_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            with self.assertRaises(frappe.ValidationError) as ctx:
                workflow_runtime.complete_workflow_task(old_task.name, "Approve")
        self.assertIn("دیگر در مرحلهٔ جاری", str(ctx.exception))
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", old_task.name, "status"), "Rejected")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Rejected")


class TestQuorumExecution(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def test_majority_third_approver_after_the_stage_advanced_is_refused(self):
        request = create(self.company, definition=_quorum_definition(self.company, "Majority"),
                         values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        act(instance, "Approve", user=APPROVERS[0])
        act(instance, "Approve", user=APPROVERS[1])  # 2 of 3: the stage advances to End
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Completed")
        # The third approver's task was cancelled with the advance; a late click is refused.
        late_task = frappe.db.get_value("ASOUD Workflow Task",
                                        {"workflow_instance": instance, "assigned_to": APPROVERS[2]},
                                        "name")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", late_task, "status"), "Cancelled")
        frappe.set_user(APPROVERS[2])
        with patch.object(workflow_runtime, "_notify_user"):
            with self.assertRaises(frappe.ValidationError) as ctx:
                workflow_runtime.complete_workflow_task(late_task, "Approve")
        # The instance is already finished, so the guard refuses it as a stale task.
        self.assertIn("دیگر در مرحلهٔ جاری", str(ctx.exception))
        # The two approvals wrote three rows (the first also the "one more needed" note);
        # the late click added nothing.
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": instance, "action": "Approve"}), 3)


class TestReturnResubmitApprove(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1)

    def test_return_resubmit_approve_reaches_end_with_an_ordered_history(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل اولیه"})
        instance = request["workflow_instance"]
        act(instance, "Return", comment="مبلغ را اصلاح کنید")
        self.assertEqual(status_key(request["name"]), "returned")
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.update_request(request["name"], values=json.dumps({"reason": "دلیل اصلاح‌شده"}))
        self.assertIn(status_key(request["name"]), ("submitted", "in_review"))
        act(instance, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Completed")
        self.assertEqual(status_key(request["name"]), "approved")
        # The history keeps the whole round: return, correction, re-approval, end.
        actions = _actions(instance)
        for expected in ("Return", "Resubmitted", "Approve", "پایان عملیات"):
            self.assertIn(expected, actions)
        self.assertLess(actions.index("Return"), actions.index("Resubmitted"))
        self.assertLess(actions.index("Resubmitted"), actions.index("Approve"))
        self.assertLess(actions.index("Approve"), actions.index("پایان عملیات"))


class TestSnapshotAfterLiveEdit(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1)
        self.approval = self.stages["Approval2"]
        self.end = self.stages["End3"]
        self.form = self.stages["User Task1"]

    def _delete_route(self, from_stage, to_stage):
        edge = frappe.db.get_value("ASOUD Workflow Transition",
                                   {"workflow_definition": self.definition,
                                    "from_stage": from_stage, "to_stage": to_stage})
        self.assertTrue(edge)
        frappe.db.delete("ASOUD Workflow Transition", edge)

    def test_instance_started_before_a_route_edit_keeps_the_old_route_after_return(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertTrue(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json"))
        # The designer deletes both routes after the instance started.
        self._delete_route(self.approval.name, self.end.name)
        self._delete_route(self.form.name, self.approval.name)
        # The frozen route still resolves: the approval completes to End.
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")

    def test_instance_started_before_a_route_edit_keeps_the_old_route_after_resubmit(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertTrue(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json"))
        self._delete_route(self.approval.name, self.end.name)
        self._delete_route(self.form.name, self.approval.name)
        act(instance.name, "Return", comment="برای اصلاح")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Running")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "current_stage"),
                         self.form.name)
        # The resubmit follows the frozen form -> approval route, not the deleted live one.
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.update_request(request["name"], values=json.dumps({"reason": "دلیل اصلاح‌شده"}))
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "current_stage"),
                         self.approval.name)
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")
