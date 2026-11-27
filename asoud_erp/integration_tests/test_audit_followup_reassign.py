"""Audit follow-up (not for merge): reassignment ownership and a real race between complete and reassign.

The race uses independent database connections; it commits its data and removes it again.
"""

import threading
from unittest.mock import patch
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase, _user
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import setup_tenancy


def _act_in_own_connection(site, sites_path, user, task, action, kwargs, barrier, out):
    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()
    try:
        frappe.set_user(user)
        barrier.wait(timeout=60)
        try:
            workflow_runtime.complete_workflow_task(task, action, **kwargs)
            frappe.db.commit()
            out.append((action, "ok"))
        except Exception as error:  # asserted by the test
            frappe.db.rollback()
            out.append((action, f"{type(error).__name__}"))
    finally:
        frappe.destroy()


class TestAuditReassign(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()
        cls.account = _user("asoud.audit-manager@example.com", ["System Manager"])
        frappe.permissions.add_user_permission("Company", cls.company, cls.account, ignore_permissions=True)
        frappe.db.commit()

    def _definition(self):
        role = frappe.get_doc({"doctype": "Role", "role_name": f"Audit {uuid4().hex[:10]}"}).insert().name
        for user in (EMPLOYEE_USER, APPROVER_USER):
            frappe.get_doc("User", user).add_roles(role)
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(item for item in stages.values() if item.stage_type == "User Task")
        config = {"title": "اقدام کاربر", "activity_type": "Data Entry", "task_purpose": "Existing",
                  "assignment_type": "Initiator", "action_contract_version": 1, "result_mode": "Simple",
                  "allow_draft": True, "allow_add_attachments": False, "simple_result_style": "Report",
                  "allow_reassign": True, "assignment_rule": {"basis": "Role", "role": role}}
        frappe.db.set_value("ASOUD Workflow Definition", definition, "status", "Inactive")
        workflow.save_stage_settings(definition, stage.name, config)
        workflow.save_start_settings(definition, "Manual", ["Employee", "System Manager"], "General Subject",
                                     settings={"trigger_type": "Manual", "initiator_roles": ["Employee", "System Manager"]})
        frappe.db.set_value("ASOUD Workflow Definition", definition, "status", "Active")
        frappe.set_user(EMPLOYEE_USER)
        instance = workflow_runtime.start_workflow_instance(definition, "بررسی اقدام", reason="آزمون")["data"]["name"]
        task = frappe.db.get_value("ASOUD Workflow Task", {"workflow_instance": instance, "assigned_to": EMPLOYEE_USER}, "name")
        return definition, instance, task

    def test_previous_holder_cannot_act_after_reassign_and_new_holder_completes(self):
        _, instance, task = self._definition()
        workflow_runtime.complete_workflow_task(task, "Claim")
        workflow_runtime.complete_workflow_task(task, "Reassign", assignee=APPROVER_USER)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task, "assigned_to"), APPROVER_USER)
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            workflow_runtime.complete_workflow_task(task, "Complete", response={"action_note": "پس از واگذاری"})
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            workflow_runtime.complete_workflow_task(task, "Reassign", assignee=EMPLOYEE_USER)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Running")
        frappe.set_user(APPROVER_USER)
        workflow_runtime.complete_workflow_task(task, "Complete", response={"action_note": "مسئول جدید"})
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Completed")

    def test_reassign_after_completion_is_refused(self):
        _, instance, task = self._definition()
        workflow_runtime.complete_workflow_task(task, "Claim")
        workflow_runtime.complete_workflow_task(task, "Complete", response={"action_note": "انجام شد"})
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            workflow_runtime.complete_workflow_task(task, "Reassign", assignee=APPROVER_USER)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task, "assigned_to"), EMPLOYEE_USER)
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity", {"workflow_task": task, "action": "Reassigned"}), 0)

    def test_complete_and_reassign_at_the_same_moment_never_both_win(self):
        definition, instance, task = self._definition()
        workflow_runtime.complete_workflow_task(task, "Claim")
        frappe.db.commit()
        barrier, out = threading.Barrier(2), []
        site, sites_path = frappe.local.site, frappe.local.sites_path
        try:
            with patch.object(workflow_runtime, "_notify_user"):
                jobs = [("Complete", {"response": {"action_note": "همزمان"}}), ("Reassign", {"assignee": APPROVER_USER})]
                threads = [threading.Thread(target=_act_in_own_connection,
                                            args=(site, sites_path, EMPLOYEE_USER, task, action, kwargs, barrier, out))
                           for action, kwargs in jobs]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=120)
            frappe.db.rollback()
            outcome = dict(out)
            self.assertEqual(len(out), 2, out)
            self.assertEqual(sorted(outcome.values()).count("ok"), 1, out)  # exactly one wins
            status = frappe.db.get_value("ASOUD Workflow Task", task, "status")
            holder = frappe.db.get_value("ASOUD Workflow Task", task, "assigned_to")
            reassigned = frappe.db.count("ASOUD Workflow Activity", {"workflow_task": task, "action": "Reassigned"})
            if outcome["Complete"] == "ok":
                self.assertEqual((status, holder, reassigned), ("Completed", EMPLOYEE_USER, 0))
            else:
                self.assertEqual((status, holder, reassigned), ("Open", APPROVER_USER, 1))
        finally:
            for doctype in ("ASOUD Workflow Activity", "ASOUD Workflow Task"):
                frappe.db.delete(doctype, {"workflow_instance": instance})
            frappe.db.delete("ASOUD Workflow Instance", {"name": instance})
            frappe.db.delete("ASOUD Workflow Transition", {"workflow_definition": definition})
            frappe.db.delete("ASOUD Workflow Stage", {"workflow_definition": definition})
            frappe.db.delete("ASOUD Workflow Definition", {"name": definition})
            frappe.db.commit()
