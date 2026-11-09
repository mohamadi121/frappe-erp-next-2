"""Approval stages bound to a pinned ASOUD Form revision (kind 'Stage').

The Stage form kind is added by the parallel C1 change; these tests create the
form through the public form API and will only pass once both branches are
merged. They run on a real site (no database mocks).
"""
import json

import frappe

from asoud_erp.api.v1 import forms, workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import APPROVER_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create, open_task
from asoud_erp.integration_tests.tenancy import setup_tenancy


def _stage_schema(required=True):
    return {"kind": "Stage", "title": "فرم مرحله آزمایشی", "schema_version": 2,
            "sections": [{"id": "main", "title": "اصلی", "fields": [
                {"key": "note", "label": "نظر", "type": "Text", "required": required},
                {"key": "amount", "label": "مبلغ", "type": "Money"},
            ]}]}


class TestStageSupplementaryForm(APITestCase):
    def _stage_form(self, company, required=True):
        saved = forms.save_form(company, _stage_schema(required),
                                client_id=frappe.generate_hash(length=24))["data"]
        published = forms.transition(saved["name"], "publish", saved["draft_version"])["data"]
        return saved["name"], published["active_revision"]

    def _definition(self):
        definition, _ = make_definition(self.company, approvals=1,
                                        fields=[{"key": "amount", "label": "مبلغ", "type": "Currency", "required": True}])
        return definition

    def _stage(self, definition, stage_type):
        return frappe.db.get_value("ASOUD Workflow Stage",
                                   {"workflow_definition": definition, "stage_type": stage_type}, "name")

    def _approval_config(self, **extra):
        config = {"title": "تأیید", "assignment_type": "Direct Manager", "approval_mode": "Any",
                  "allow_reject": True, "allow_return": True}
        config.update(extra)
        return config

    def test_bind_ok_stores_title(self):
        definition = self._definition()
        form, revision = self._stage_form(self.company)
        workflow.save_stage_settings(definition, self._stage(definition, "Approval"),
                                     self._approval_config(supplementary_form={"form": form, "revision": revision}))
        stored = json.loads(frappe.db.get_value("ASOUD Workflow Stage", self._stage(definition, "Approval"), "config_json"))
        self.assertEqual(stored["supplementary_form"]["form"], form)
        self.assertEqual(stored["supplementary_form"]["revision"], revision)
        self.assertEqual(stored["supplementary_form"]["title"], "فرم مرحله آزمایشی")

    def test_non_stage_form_refused(self):
        definition = self._definition()
        saved = forms.save_form(self.company, {"kind": "Request", "title": "درخواست", "schema_version": 2,
                                               "sections": [{"id": "m", "title": "اصلی",
                                                             "fields": [{"key": "a", "label": "الف", "type": "Text"}]}]},
                               client_id=frappe.generate_hash(length=24))["data"]
        forms.transition(saved["name"], "publish", saved["draft_version"])
        revision = frappe.db.get_value("ASOUD Form", saved["name"], "active_revision")
        with self.assertRaisesRegex(frappe.ValidationError, "فرم مرحله"):
            workflow.save_stage_settings(definition, self._stage(definition, "Approval"),
                                         self._approval_config(supplementary_form={"form": saved["name"], "revision": revision}))

    def test_other_company_form_refused(self):
        definition = self._definition()
        second = setup_tenancy()["second"]
        form, revision = self._stage_form(second)
        with self.assertRaisesRegex(frappe.ValidationError, "همین دفتر"):
            workflow.save_stage_settings(definition, self._stage(definition, "Approval"),
                                         self._approval_config(supplementary_form={"form": form, "revision": revision}))

    def test_revision_of_another_form_refused(self):
        definition = self._definition()
        form_a, _ = self._stage_form(self.company)
        form_b, revision_b = self._stage_form(self.company)
        with self.assertRaisesRegex(frappe.ValidationError, "متعلق به این فرم"):
            workflow.save_stage_settings(definition, self._stage(definition, "Approval"),
                                         self._approval_config(supplementary_form={"form": form_a, "revision": revision_b}))

    def test_binding_on_non_approval_stage_refused(self):
        definition = self._definition()
        form, revision = self._stage_form(self.company)
        with self.assertRaisesRegex(frappe.ValidationError, "فقط برای مرحلهٔ تأیید"):
            workflow.save_stage_settings(definition, self._stage(definition, "User Task"),
                                         {"title": "ثبت", "activity_type": "Data Entry", "assignment_type": "Initiator",
                                          "form_fields": [], "supplementary_form": {"form": form, "revision": revision}})

    def test_binding_with_inline_fields_refused(self):
        definition = self._definition()
        form, revision = self._stage_form(self.company)
        with self.assertRaisesRegex(frappe.ValidationError, "خالی باشند"):
            workflow.save_stage_settings(definition, self._stage(definition, "Approval"),
                                         self._approval_config(form_fields=[{"key": "x", "label": "ایکس", "type": "Text"}],
                                                               supplementary_form={"form": form, "revision": revision}))

    def _bound_instance(self, required=True):
        definition = self._definition()
        form, revision = self._stage_form(self.company, required=required)
        workflow.save_stage_settings(definition, self._stage(definition, "Approval"),
                                     self._approval_config(supplementary_form={"form": form, "revision": revision}))
        request = create(self.company, definition, values={"amount": 100})
        task = open_task(request["workflow_instance"], APPROVER_USER)
        self.assertIsNotNone(task)
        return definition, form, revision, request, task

    def test_get_task_returns_supplementary_form(self):
        definition, form, revision, request, task = self._bound_instance()
        frappe.set_user(APPROVER_USER)
        data = workflow_runtime.get_workflow_task(task.name)["data"]
        self.assertEqual(data["supplementary_form"]["form"], form)
        self.assertEqual(data["supplementary_form"]["revision"], revision)
        self.assertEqual(data["supplementary_form"]["title"], "فرم مرحله آزمایشی")
        self.assertEqual(data["supplementary_form"]["values"], {})
        self.assertTrue(data["supplementary_form"]["schema"]["sections"])

    def test_task_without_binding_has_no_supplementary_form(self):
        definition = self._definition()
        request = create(self.company, definition, values={"amount": 100})
        task = open_task(request["workflow_instance"], APPROVER_USER)
        frappe.set_user(APPROVER_USER)
        data = workflow_runtime.get_workflow_task(task.name)["data"]
        self.assertNotIn("supplementary_form", data)

    def test_draft_keeps_values_when_not_resent(self):
        definition, form, revision, request, task = self._bound_instance()
        frappe.set_user(APPROVER_USER)
        workflow_runtime.save_workflow_task_draft(task.name, {}, supplementary_values={"note": "اول", "amount": "5"})
        workflow_runtime.save_workflow_task_draft(task.name, {})  # no supplementary_values
        draft = json.loads(frappe.db.get_value("ASOUD Workflow Task", task.name, "draft_json"))
        self.assertEqual(draft["_supplementary"]["values"], {"note": "اول", "amount": "5"})

    def test_approve_requires_supplementary_values(self):
        definition, form, revision, request, task = self._bound_instance(required=True)
        frappe.set_user(APPROVER_USER)
        with self.assertRaisesRegex(frappe.ValidationError, "الزامی"):
            workflow_runtime.complete_workflow_task(task.name, "Approve")

    def test_reject_stores_optional_values(self):
        definition, form, revision, request, task = self._bound_instance(required=True)
        frappe.set_user(APPROVER_USER)
        workflow_runtime.complete_workflow_task(task.name, "Reject", comment="رد شد",
                                                supplementary_values={"note": "مشکل دارد", "amount": "9"})
        stored = json.loads(frappe.db.get_value("ASOUD Workflow Task", task.name, "response_json"))
        self.assertEqual(stored["_supplementary"]["form"], form)
        self.assertEqual(stored["_supplementary"]["revision"], revision)
        self.assertEqual(stored["_supplementary"]["values"], {"note": "مشکل دارد", "amount": "9"})

    def test_approve_stores_supplementary_shape(self):
        definition, form, revision, request, task = self._bound_instance(required=True)
        frappe.set_user(APPROVER_USER)
        workflow_runtime.complete_workflow_task(task.name, "Approve",
                                                supplementary_values={"note": "تأیید می‌شود", "amount": "12"})
        stored = json.loads(frappe.db.get_value("ASOUD Workflow Task", task.name, "response_json"))
        self.assertEqual(set(stored), {"_supplementary"})
        self.assertEqual(stored["_supplementary"], {"form": form, "revision": revision,
                                                    "values": {"note": "تأیید می‌شود", "amount": "12"}})

    def test_new_revision_does_not_change_pinned_task(self):
        definition, form, revision, request, task = self._bound_instance()
        # Publish a second revision of the same form.
        saved = forms.save_form(self.company, _stage_schema(required=False), name=form,
                                expected_version=frappe.db.get_value("ASOUD Form", form, "draft_version"),
                                client_id=frappe.generate_hash(length=24))["data"]
        forms.transition(form, "publish", saved["draft_version"])
        frappe.set_user(APPROVER_USER)
        data = workflow_runtime.get_workflow_task(task.name)["data"]
        # The task still reads the pinned revision, not the new active one.
        self.assertEqual(data["supplementary_form"]["revision"], revision)
