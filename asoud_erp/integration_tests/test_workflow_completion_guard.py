"""Integration tests (CI-only, real site) for the two workflow fixes.

F-4: the specialised HR modules finalize/issue a document when their workflow instance
completes. A failure inside that finalization must roll back to a savepoint, mark the entry
``Failed`` with a Persian reason, log the error, and keep the approval (instance Completed).
F-7: ``start_workflow_instance`` with a ``request_id`` must be idempotent for non-configured
starts too (the 'Workflow Started' activity is the receipt the duplicate lookup reads).

These run on an installed bench; they are not run locally.
"""

import json
from unittest import mock
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import hiring_orders as hiring
from asoud_erp.api.v1 import workflow_runtime
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import HR_MANAGER_USER, setup_tenancy
from asoud_erp.services.hiring_orders import default_template


class TestSpecialisedCompletionGuard(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def _definition(self):
        definition, stages = make_definition(company(), approvals=1, fields=[])
        for stage in stages.values():
            if stage.stage_type == "Approval":
                config = json.loads(stage.config_json)
                config.update(assignment_type="Role", approver_roles=["System Manager"])
                frappe.db.set_value("ASOUD Workflow Stage", stage.name, "config_json", json.dumps(config))
        return definition

    def _publish_template(self, definition):
        # Build from the default template: get_hiring_order_template returns
        # {"template": None} on a fresh site where nothing is published yet.
        template = default_template()
        template["workflow"] = definition
        saved = hiring.save_hiring_order_template(company(), template=template)["data"]
        hiring.publish_hiring_order_template(company(), revision=saved["revision"])

    def _draft(self):
        employee = frappe.db.get_value("Employee", {"company": company(), "status": "Active"}, "name")
        return hiring.save_hiring_order(company=company(), employee=employee,
                                        effective_date="2026-01-01", request_id=uuid4().hex)["data"]

    def _send(self, draft):
        sent = hiring.send_hiring_order_for_review(draft["name"], draft["revision"], uuid4().hex)["data"]
        return json.loads(frappe.db.get_value("ASOUD Form Entry", draft["name"], "values_json")) or sent

    def _open_task(self, instance_name):
        return frappe.db.get_value("ASOUD Workflow Task",
                                   {"workflow_instance": instance_name, "status": "Open"},
                                   ["name", "assigned_to"], as_dict=True)

    def test_completion_failure_marks_entry_failed_and_keeps_the_approval(self):
        frappe.set_user(HR_MANAGER_USER)
        definition = self._definition()
        self._publish_template(definition)
        draft = self._draft()
        data = self._send(draft)
        instance_name = data["workflow_instance"]
        task = self._open_task(instance_name)
        self.assertTrue(task)

        from asoud_erp.services import hiring_order_workflow

        logs_before = frappe.db.count("Error Log")
        with mock.patch.object(hiring_order_workflow, "_finalize",
                               side_effect=KeyError("payroll.base_salary")):
            frappe.set_user(task.assigned_to)
            workflow_runtime.complete_workflow_task(task.name, "Approve", comment="تأیید آزمون")

        # The approval is kept: the instance is Completed even though finalization failed.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance_name, "status"), "Completed")
        # The entry is marked Failed with a Persian reason (not the raw English KeyError).
        entry = json.loads(frappe.db.get_value("ASOUD Form Entry", draft["name"], "values_json"))
        self.assertEqual(entry["status"], "failed")
        self.assertIn("ناموفق", entry["status_label"])
        self.assertRegex(entry["failure_reason"], r"[؀-ۿ]")
        self.assertNotIn("KeyError", entry["failure_reason"])
        self.assertNotIn("payroll.base_salary", entry["failure_reason"])
        # The failure is logged, not swallowed.
        self.assertGreater(frappe.db.count("Error Log"), logs_before)

    def test_completion_success_finalizes_without_a_failure(self):
        frappe.set_user(HR_MANAGER_USER)
        definition = self._definition()
        self._publish_template(definition)
        draft = self._draft()
        data = self._send(draft)
        instance_name = data["workflow_instance"]
        task = self._open_task(instance_name)
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, "Approve", comment="تأیید آزمون")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance_name, "status"), "Completed")
        entry = json.loads(frappe.db.get_value("ASOUD Form Entry", draft["name"], "values_json"))
        self.assertEqual(entry["status"], "final")
        self.assertRegex(entry["number"], r"^HIRE-\d{4}-\d+$")
        self.assertNotIn("failure_reason", entry)


class TestNonConfiguredStartIdempotency(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def test_same_request_id_returns_the_same_instance_for_a_non_configured_start(self):
        frappe.set_user(HR_MANAGER_USER)
        definition, _ = make_definition(company(), approvals=1, fields=[])
        request_id = "req-" + uuid4().hex[:16]
        first = workflow_runtime.start_workflow_instance(
            definition=definition, subject="آزمون شروع تکراری", request_id=request_id)["data"]
        second = workflow_runtime.start_workflow_instance(
            definition=definition, subject="آزمون شروع تکراری", request_id=request_id)["data"]
        self.assertEqual(first["name"], second["name"])
        self.assertEqual(
            frappe.db.count("ASOUD Workflow Instance", {"workflow_definition": definition}), 1)
        # The receipt activity carries the request_id so the lookup can match it.
        activity = frappe.db.get_value("ASOUD Workflow Activity",
                                       {"workflow_instance": first["name"], "action": "Workflow Started"},
                                       "change_json")
        self.assertEqual(json.loads(activity)["request_id"], request_id)

    def test_a_non_configured_start_without_request_id_is_not_deduplicated(self):
        frappe.set_user(HR_MANAGER_USER)
        definition, _ = make_definition(company(), approvals=1, fields=[])
        first = workflow_runtime.start_workflow_instance(
            definition=definition, subject="آزمون شروع بدون شناسه")["data"]
        second = workflow_runtime.start_workflow_instance(
            definition=definition, subject="آزمون شروع بدون شناسه")["data"]
        self.assertNotEqual(first["name"], second["name"])
        self.assertEqual(
            frappe.db.count("ASOUD Workflow Instance", {"workflow_definition": definition}), 2)
