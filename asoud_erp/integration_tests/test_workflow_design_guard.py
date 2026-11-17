"""A design change can never alter a running instance; an invalid design cannot run (PA-015).

The designer's graph/config mutations (routes, stage settings, stage insertion,
connections) are refused while a workflow is Active or has a Running instance, and
the refusal leaves the database unchanged. ``start_workflow_instance`` refuses to
start a design whose stored graph has an error-severity issue. The backfill patch
freezes the live graph for old Running instances that have no snapshot, only when
the live graph is still consistent with what the instance already executed.
"""
import json
from unittest.mock import patch

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import (
    make_definition,
    patched_specs,
    seed_test_templates,
)
from asoud_erp.integration_tests.request_helpers import act, create


def _graph_fingerprint(definition):
    """A stable fingerprint of the stages and transitions of a definition."""
    stages = frappe.get_all("ASOUD Workflow Stage", filters={"workflow_definition": definition},
                            fields=["name", "stage_type", "config_json"], order_by="name asc")
    edges = frappe.get_all("ASOUD Workflow Transition", filters={"workflow_definition": definition},
                           fields=["name", "from_stage", "to_stage", "transition_label", "condition_json"],
                           order_by="name asc")
    return json.dumps([stages, edges], ensure_ascii=False, sort_keys=True)


class TestDesignGuard(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=2)
        # make_definition keys stages by `stage_type + index`: Start0, User Task1,
        # Approval2, Approval3, End4 for approvals=2.
        self.approval1 = self.stages["Approval2"]
        self.approval2 = self.stages["Approval3"]
        self.end = self.stages["End4"]
        self.form_stage = self.stages["User Task1"]

    def _start(self):
        request = create(self.company, definition=self.definition)
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertEqual(instance.current_stage, self.approval1.name)
        return instance

    def test_save_stage_routes_rejected_on_active(self):
        self._start()
        before = _graph_fingerprint(self.definition)
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval1.name,
                                       {"Approve": self.end.name})
        self.assertEqual(_graph_fingerprint(self.definition), before)

    def test_save_stage_settings_approval_rejected_on_active(self):
        self._start()
        before = self.approval1.config_json
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(self.definition, self.approval1.name,
                                         {"title": "تأیید تغییرشده", "assignment_type": "Direct Manager",
                                          "approval_mode": "Any", "allow_reject": True, "allow_return": True})
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", self.approval1.name, "config_json"), before)

    def test_save_stage_settings_user_task_rejected_on_active(self):
        self._start()
        form_stage = self.form_stage
        before = form_stage.config_json
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(self.definition, form_stage.name,
                                         {"title": "ثبت", "activity_type": "Data Entry",
                                          "assignment_type": "Initiator", "form_fields": []})
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", form_stage.name, "config_json"), before)

    def test_connect_rejected_on_active(self):
        self._start()
        before = _graph_fingerprint(self.definition)
        with self.assertRaises(frappe.ValidationError):
            workflow.connect_workflow_stages(self.definition, self.approval1.name, self.end.name, "ادامه")
        self.assertEqual(_graph_fingerprint(self.definition), before)

    def test_insert_stage_rejected_on_active(self):
        self._start()
        before = _graph_fingerprint(self.definition)
        edge = frappe.db.get_value("ASOUD Workflow Transition",
                                   {"workflow_definition": self.definition, "from_stage": self.approval1.name})
        self.assertTrue(edge)
        with self.assertRaises(frappe.ValidationError):
            workflow.insert_workflow_stage(self.definition, edge, "Approval")
        self.assertEqual(_graph_fingerprint(self.definition), before)

    def test_rejected_when_inactive_but_running(self):
        instance = self._start()
        frappe.db.set_value("ASOUD Workflow Definition", self.definition, "status", "Inactive")
        before = _graph_fingerprint(self.definition)
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval1.name, {"Approve": self.end.name})
        self.assertEqual(_graph_fingerprint(self.definition), before)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Running")

    def test_allowed_when_inactive_and_no_running(self):
        # No instance has started, so the design is editable.
        frappe.db.set_value("ASOUD Workflow Definition", self.definition, "status", "Inactive")
        reply = workflow.save_stage_routes(self.definition, self.approval1.name, {"Approve": self.end.name})["data"]
        self.assertTrue(any(row["from_stage"] == self.approval1.name and row["to_stage"] == self.end.name
                            for row in reply["transitions"]))

    def test_new_instance_keeps_both_approvals_after_attempted_change(self):
        instance = self._start()
        # An attempted reroute that would skip approval 2 is refused.
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval1.name, {"Approve": self.end.name})
        # The instance still needs both approvals to complete.
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Running")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "current_stage"),
                         self.approval2.name)
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")

    def test_old_instance_cannot_skip_approval_via_routes(self):
        instance = self._start()
        # Simulate an old instance that predates the snapshot field.
        frappe.db.set_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json", None)
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval1.name, {"Approve": self.end.name})
        # The instance is untouched: still at approval 1, still running.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "current_stage"),
                         self.approval1.name)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Running")

    def test_no_request_deleted_duplicated_or_reassigned(self):
        request = create(self.company, definition=self.definition)
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        before = frappe.db.get_value("ASOUD Workflow Task",
                                     {"workflow_instance": instance.name, "status": "Open"},
                                     ["name", "assigned_to"], as_dict=True)
        for call in (lambda: workflow.save_stage_routes(self.definition, self.approval1.name,
                                                        {"Approve": self.end.name}),
                     lambda: workflow.save_stage_settings(self.definition, self.approval1.name,
                                                          {"title": "تأیید", "assignment_type": "Direct Manager",
                                                           "approval_mode": "Any", "allow_reject": True,
                                                           "allow_return": True})):
            with self.assertRaises(frappe.ValidationError):
                call()
        self.assertEqual(frappe.db.count("ASOUD Workflow Request", {"name": request["name"]}), 1)
        self.assertEqual(frappe.db.count("ASOUD Workflow Instance", {"name": instance.name}), 1)
        after = frappe.db.get_value("ASOUD Workflow Task",
                                    {"workflow_instance": instance.name, "status": "Open"},
                                    ["name", "assigned_to"], as_dict=True)
        self.assertEqual(after, before)

    def test_start_refuses_invalid_design(self):
        # Corrupt the Active design at the DB level: delete the approval stage so a
        # route dangles. The design is now invalid, so a new request cannot start.
        frappe.db.delete("ASOUD Workflow Stage", self.approval1.name)
        with self.assertRaises(frappe.ValidationError) as caught:
            create(self.company, definition=self.definition)
        self.assertIn("این گردش‌کار معتبر نیست", str(caught.exception))
        self.assertIsNone(frappe.db.get_value("ASOUD Workflow Instance",
                                              {"workflow_definition": self.definition, "status": "Running"}))


class TestSnapshotBackfill(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1)
        # make_definition keys stages by `stage_type + index`: Start0, User Task1,
        # Approval2, End3 for approvals=1.
        self.approval = self.stages["Approval2"]
        self.end = self.stages["End3"]

    def _old_instance(self):
        request = create(self.company, definition=self.definition)
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        # Simulate an instance started before the snapshot field existed.
        frappe.db.set_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json", None)
        return instance

    def test_consistent_instance_gets_marked_snapshot_and_follows_it(self):
        instance = self._old_instance()
        from asoud_erp.patches.v0_19.backfill_graph_snapshots import execute

        execute()
        snapshot = frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json")
        self.assertTrue(snapshot)
        data = json.loads(snapshot)
        self.assertEqual(data["snapshot_source"], "backfill_live_graph")
        # The designer now reroutes approval -> end at the DB level (bypassing the
        # guard, as a direct DB edit would). The backfilled instance must still
        # follow its frozen route and complete.
        edge = frappe.db.get_value("ASOUD Workflow Transition",
                                   {"workflow_definition": self.definition, "from_stage": self.approval.name,
                                    "to_stage": self.end.name})
        frappe.db.delete("ASOUD Workflow Transition", edge)
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")

    def test_inconsistent_instance_untouched_and_logged(self):
        instance = self._old_instance()
        # Corrupt the live graph: the instance's current stage no longer exists.
        frappe.db.delete("ASOUD Workflow Stage", self.approval.name)
        from asoud_erp.patches.v0_19.backfill_graph_snapshots import execute

        with patch.object(frappe, "log_error") as log_error:
            execute()
        self.assertIsNone(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json"))
        self.assertTrue(log_error.called, "an inconsistent instance must be logged for review")
        self.assertEqual(log_error.call_args.kwargs.get("title"), "PA-015 snapshot backfill needs review")
        self.assertIn(instance.name, log_error.call_args.kwargs.get("message", ""))

    def test_second_run_is_a_noop(self):
        instance = self._old_instance()
        from asoud_erp.patches.v0_19.backfill_graph_snapshots import execute

        execute()
        first = frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json")
        self.assertTrue(first)
        execute()
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json"), first)


class TestSystemTemplatesStart(APITestCase):
    """The start-time check must not block the real system request types.

    The seeded system templates (leave/purchase/supply) are started through
    ``create_request``; their Start stage has no usable Manual trigger
    (``initiator_roles`` is empty), so the designer's activation rules reject
    them. The start-time check must only reject *structural* breakage, so a
    request can still be created for a healthy template, and a DB-corrupted one
    (an orphan approval / dangling route) is refused.
    """

    def setUp(self):
        super().setUp()
        self.specs = patched_specs()
        self.specs.__enter__()
        self.definitions = seed_test_templates(self.company)

    def tearDown(self):
        self.specs.__exit__()
        super().tearDown()

    def _approval_stage(self, definition):
        return frappe.db.get_value("ASOUD Workflow Stage",
                                   {"workflow_definition": definition, "stage_type": "Approval"}, "name")

    def test_create_request_works_for_the_seeded_system_templates(self):
        # The regression: with the old check every leave/purchase request was
        # refused because the seeded Start has no trigger_type/initiator_roles.
        for key in ("leave", "purchase"):
            result = create(self.company, template_key=key)
            instance = frappe.get_doc("ASOUD Workflow Instance", result["workflow_instance"])
            self.assertEqual(instance.status, "Running", key)
            self.assertEqual(instance.workflow_definition, self.definitions[key])

    def test_a_db_corrupted_system_template_is_refused(self):
        definition = self.definitions["leave"]
        # Corrupt the design at the DB level: delete the approval stage so the
        # form stage's route dangles. The graph is now structurally broken.
        frappe.db.delete("ASOUD Workflow Stage", self._approval_stage(definition))
        with self.assertRaises(frappe.ValidationError) as caught:
            create(self.company, template_key="leave")
        self.assertIn("این گردش‌کار معتبر نیست", str(caught.exception))
        self.assertIsNone(frappe.db.get_value("ASOUD Workflow Instance",
                                               {"workflow_definition": definition, "status": "Running"}))
