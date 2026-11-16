"""A running instance keeps the stage graph it started with (PA-015).

When the designer edits a stage's config or deletes a stage/route after an
instance has started, that instance must keep executing against the graph it
frozen at start, not the live rows. These tests start a request (which auto-
submits the form task and parks the instance at the Approval stage), then mutate
the live design and prove the open task still resolves from the snapshot.
"""
import json

import frappe

from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create


class TestWorkflowGraphSnapshot(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1)
        self.approval = self.stages["Approval2"]
        self.end = self.stages["End3"]

    def _start(self):
        request = create(self.company, definition=self.definition)
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        # The form task is auto-submitted by `create`; the instance sits at the
        # Approval stage with an open task for the direct manager.
        self.assertEqual(instance.current_stage, self.approval.name)
        self.assertTrue(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json"))
        return instance

    def test_open_task_uses_frozen_config_not_live_edit(self):
        instance = self._start()
        # The designer makes a comment mandatory on the approval stage *after* the
        # instance started. The running instance must not be forced to satisfy it.
        live = json.loads(self.approval.config_json)
        live["comment_required"] = True
        self.approval.db_set("config_json", json.dumps(live))
        # No comment: the frozen config has no comment requirement, so it completes.
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")

    def test_open_task_routes_to_a_deleted_route(self):
        instance = self._start()
        # The designer deletes the approval->end route after the instance started.
        # Without the snapshot, `_next_stage` would read the live (now empty) routes
        # and fail with "no next stage"; with it, the frozen route still resolves.
        edge = frappe.db.get_value("ASOUD Workflow Transition",
                                   {"workflow_definition": self.definition, "from_stage": self.approval.name,
                                    "to_stage": self.end.name})
        self.assertTrue(edge)
        frappe.db.delete("ASOUD Workflow Transition", edge)
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")

    def test_old_instance_without_snapshot_falls_back_to_live(self):
        instance = self._start()
        # Simulate an instance created before the snapshot field existed.
        frappe.db.set_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json", None)
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")
