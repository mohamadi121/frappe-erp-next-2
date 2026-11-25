"""Phase B: real concurrent completion, the start-route backstop and the quorum notice.

The concurrency tests use independent database connections (one thread, one connection,
one transaction each), because two sequential calls in one transaction cannot show a
lost update. They commit their data, so they delete everything they created.
"""

import threading
from unittest.mock import patch

import frappe

from asoud_erp.api.v1 import workflow_runtime
from asoud_erp.integration_tests.fixtures import ACCOUNTANT_USER, APPROVER_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create, open_task
from asoud_erp.services.workflow_contract import START_ROUTE


def _complete_in_own_connection(site, sites_path, user, task, action, barrier, out):
    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()
    try:
        frappe.set_user(user)
        barrier.wait(timeout=60)
        try:
            result = workflow_runtime.complete_workflow_task(task, action)
            frappe.db.commit()
            out.append(("ok", result))
        except Exception as error:  # the outcome is asserted by the test
            frappe.db.rollback()
            out.append(("error", f"{type(error).__name__}: {error}"))
    finally:
        frappe.destroy()


class TestPhaseBCore(APITestCase):
    def _definition(self, mode, approvers):
        definition, stages = make_definition(self.company, approvals=1)
        stage = frappe.get_doc("ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Approval"})
        config = frappe.parse_json(stage.config_json)
        config.update(assignment_type="Employee", approver_employees=[
            frappe.db.get_value("Employee", {"user_id": user}) for user in approvers])
        config["approval_mode"] = mode
        stage.config_json = frappe.as_json(config)
        stage.save(ignore_permissions=True)
        return definition, stages

    def _purge(self, definition):
        instances = frappe.get_all("ASOUD Workflow Instance", filters={"workflow_definition": definition}, pluck="name")
        requests = frappe.get_all("ASOUD Workflow Instance", filters={"workflow_definition": definition},
                                  pluck="reference_name")
        for name in instances:
            for doctype in ("ASOUD Workflow Activity", "ASOUD Workflow Task"):
                frappe.db.delete(doctype, {"workflow_instance": name})
            frappe.db.delete("ASOUD Workflow Instance", {"name": name})
        for name in requests:
            frappe.db.delete("ASOUD Workflow Request", {"name": name})
        frappe.db.delete("ASOUD Workflow Transition", {"workflow_definition": definition})
        frappe.db.delete("ASOUD Workflow Stage", {"workflow_definition": definition})
        frappe.db.delete("ASOUD Workflow Definition", {"name": definition})
        frappe.db.commit()

    def _race(self, jobs):
        """jobs: [(user, task, action)] completed at the same moment, each in its own connection."""
        barrier, out = threading.Barrier(len(jobs)), []
        site, sites_path = frappe.local.site, frappe.local.sites_path
        with patch.object(workflow_runtime, "_notify_user"):
            threads = [threading.Thread(target=_complete_in_own_connection,
                                        args=(site, sites_path, user, task, action, barrier, out))
                       for user, task, action in jobs]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=120)
        frappe.db.rollback()  # end this connection's snapshot so it reads what the threads committed
        return out

    def test_same_task_completed_twice_at_once_applies_one_decision(self):
        definition, _ = self._definition("Any", [APPROVER_USER])
        try:
            instance = create(self.company, definition=definition, values={"reason": "دلیل"})["workflow_instance"]
            task = open_task(instance, APPROVER_USER).name
            frappe.db.commit()
            out = self._race([(APPROVER_USER, task, "Approve")] * 2)
            self.assertEqual(sorted(kind for kind, _ in out), ["error", "ok"], out)
            self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Completed")
            decisions = frappe.db.count("ASOUD Workflow Activity", {
                "workflow_instance": instance, "workflow_task": task, "action": "Approve"})
            self.assertEqual(decisions, 1)
        finally:
            self._purge(definition)

    def test_two_approvers_deciding_at_once_never_leave_the_stage_stuck(self):
        definition, _ = self._definition("All", [APPROVER_USER, ACCOUNTANT_USER])
        try:
            instance = create(self.company, definition=definition, values={"reason": "دلیل"})["workflow_instance"]
            first, second = open_task(instance, APPROVER_USER).name, open_task(instance, ACCOUNTANT_USER).name
            frappe.db.commit()
            out = self._race([(APPROVER_USER, first, "Approve"), (ACCOUNTANT_USER, second, "Approve")])
            status = frappe.db.get_value("ASOUD Workflow Instance", instance, "status")
            open_tasks = frappe.db.count("ASOUD Workflow Task", {"workflow_instance": instance, "status": "Open"})
            approvals = frappe.db.count("ASOUD Workflow Activity", {"workflow_instance": instance, "action": "Approve"})
            # Never both decisions recorded while the instance still waits with nothing open.
            self.assertFalse(status == "Running" and open_tasks == 0, (out, status, open_tasks, approvals))
            if all(kind == "ok" for kind, _ in out):
                self.assertEqual(status, "Completed", out)
        finally:
            self._purge(definition)

    def test_a_route_into_start_is_refused_by_the_doctype(self):
        definition, stages = make_definition(self.company, approvals=1)
        with self.assertRaises(frappe.ValidationError) as caught:
            frappe.get_doc({"doctype": "ASOUD Workflow Transition", "workflow_definition": definition,
                            "from_stage": stages["Approval2"].name, "to_stage": stages["Start0"].name,
                            "condition_json": "{}"}).insert(ignore_permissions=True)
        self.assertIn(START_ROUTE, str(caught.exception))

    def test_partial_approval_does_not_tell_the_requester_it_was_approved(self):
        definition, _ = self._definition("All", [APPROVER_USER, ACCOUNTANT_USER])
        instance = create(self.company, definition=definition, values={"reason": "دلیل"})["workflow_instance"]
        titles = []

        def decide(user):
            task = open_task(instance, user).name
            frappe.set_user(user)
            with patch.object(workflow_runtime, "_notify_user",
                              side_effect=lambda _to, title, *a, **k: titles.append(title)):
                workflow_runtime.complete_workflow_task(task, "Approve")
            frappe.set_user("Administrator")

        approved = frappe._("Workflow request approved")
        decide(APPROVER_USER)
        self.assertNotIn(approved, titles)
        self.assertEqual(len(titles), 1)
        decide(ACCOUNTANT_USER)
        self.assertIn(approved, titles)
