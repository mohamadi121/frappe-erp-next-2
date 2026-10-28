"""Seeding of the system request templates (against the test specs, not the real forms)."""

import dataclasses
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import workflow, workflow_request
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import patched_specs, seed_test_templates
from asoud_erp.services.request_templates import base as templates
from asoud_erp.services.request_templates import seed

TABLES = ("ASOUD Workflow Definition", "ASOUD Workflow Stage", "ASOUD Workflow Transition")


class TestRequestTemplatesSeed(APITestCase):
    def setUp(self):
        super().setUp()
        self.specs = patched_specs()
        self.specs.__enter__()
        self.definitions = seed_test_templates(self.company)

    def tearDown(self):
        self.specs.__exit__()
        super().tearDown()

    def _stages(self, definition):
        return {row.stage_type: row for row in frappe.get_all(
            "ASOUD Workflow Stage", filters={"workflow_definition": definition},
            fields=["name", "stage_type", "stage_title", "config_json", "stage_key", "sequence_no"])}

    def test_seeding_twice_changes_nothing(self):
        self.assertEqual(set(self.definitions), {"purchase", "leave"})
        before = {table: frappe.db.count(table) for table in TABLES}
        first = [frappe.get_doc("ASOUD Workflow Definition", name).as_dict() for name in self.definitions.values()]
        summary = seed.ensure_system_templates(self.company)
        self.assertEqual(summary, {"created": 0, "updated": 0, "skipped": 2})
        self.assertEqual({table: frappe.db.count(table) for table in TABLES}, before)
        again = [frappe.get_doc("ASOUD Workflow Definition", name).as_dict() for name in self.definitions.values()]
        self.assertEqual([row.modified for row in first], [row.modified for row in again])

    def test_definition_stages_and_flags(self):
        abbr = frappe.get_cached_value("Company", self.company, "abbr")
        definition = frappe.get_doc("ASOUD Workflow Definition", self.definitions["leave"])
        self.assertEqual(definition.workflow_code, f"SYS-LEAVE-{abbr}")
        self.assertEqual((definition.template_key, definition.template_version, definition.is_system_template),
                         ("leave", 1, 1))
        self.assertEqual((definition.status, definition.readiness_status, definition.creation_mode),
                         ("Active", "Ready", "Template"))
        self.assertEqual(definition.frappe_workflow, "ASOUD-SYSTEM-REQUEST-NATIVE")
        stages = self._stages(definition.name)
        self.assertEqual(sorted(stages), ["Approval", "End", "Start", "User Task"])
        approval = json.loads(stages["Approval"].config_json)
        self.assertEqual((approval["assignment_type"], approval["approval_mode"]), ("Direct Manager", "Any"))
        self.assertEqual(workflow_request.form_stage_name(definition.name), stages["User Task"].name)

    def test_one_definition_per_company_and_template(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({
                "doctype": "ASOUD Workflow Definition", "workflow_code": "dup-" + uuid4().hex[:6],
                "workflow_title": "تکراری", "company": self.company, "module_key": "HR",
                "target_doctype": "ASOUD Workflow Request", "template_key": "leave",
                "frappe_workflow": "ASOUD-SYSTEM-REQUEST-NATIVE"}).insert()

    def test_a_version_bump_rewrites_only_the_form_fields(self):
        name = self.definitions["purchase"]
        stages = self._stages(name)
        workflow.save_stage_settings(name, stages["Approval"].name, {
            "title": "تأیید مالی", "assignment_type": "Role", "approver_roles": ["HR Manager"],
            "approval_mode": "All", "allow_reject": True, "allow_return": False})
        edited = frappe.db.get_value("ASOUD Workflow Stage", stages["Approval"].name, ["stage_title", "config_json"])
        spec = templates.get("purchase")
        extra = {"key": "extra_note", "label": "یادداشت", "type": "Short Text"}
        templates._REGISTRY["purchase"] = dataclasses.replace(
            spec, version=2, form_fields=[*spec.form_fields, extra])
        self.assertEqual(seed.ensure_system_templates(self.company), {"created": 0, "updated": 1, "skipped": 1})
        form = json.loads(frappe.db.get_value("ASOUD Workflow Stage", stages["User Task"].name, "config_json"))
        self.assertEqual(form["form_fields"][-1]["key"], "extra_note")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Definition", name, "template_version"), 2)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", stages["Approval"].name,
                                             ["stage_title", "config_json"]), edited)
        self.assertEqual(seed.ensure_system_templates(self.company), {"created": 0, "updated": 0, "skipped": 2})

    def test_admin_cannot_save_the_system_form_stage(self):
        name = self.definitions["leave"]
        stages = self._stages(name)
        before = frappe.db.get_value("ASOUD Workflow Stage", stages["User Task"].name, "config_json")
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(name, stages["User Task"].name, {
                "title": "فرم", "activity_type": "Data Entry", "assignment_type": "Initiator",
                "form_fields": [{"key": "only", "label": "تنها", "type": "Short Text"}]})
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", stages["User Task"].name, "config_json"), before)
        workflow.save_stage_settings(name, stages["Approval"].name, {
            "title": "تأیید", "assignment_type": "Direct Manager", "approval_mode": "Any"})

    def test_a_company_inserted_later_is_seeded(self):
        token = uuid4().hex[:4].upper()
        company = frappe.get_doc({
            "doctype": "Company", "company_name": "ASOUD Seed " + token, "abbr": "S" + token,
            "default_currency": "USD", "country": "United States", "chart_of_accounts": "Standard",
        }).insert(ignore_permissions=True)
        seeded = frappe.get_all("ASOUD Workflow Definition", filters={"company": company.name},
                                pluck="template_key")
        self.assertEqual(sorted(seeded), ["leave", "purchase"])
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Definition", f"SYS-LEAVE-S{token}", "company"),
                         company.name)

    def _orphan_with_user_edits(self):
        name = self.definitions["leave"]
        stages = self._stages(name)
        extra = frappe.get_doc({
            "doctype": "ASOUD Workflow Stage", "workflow_definition": name,
            "stage_key": "seed-extra-" + uuid4().hex[:8], "stage_type": "User Task",
            "stage_title": "بررسی تکمیلی", "sequence_no": 2,
            "config_json": json.dumps({"instructions": "یادداشت کاربر"}),
        }).insert(ignore_permissions=True)
        form = stages["User Task"]
        config = json.loads(form.config_json)
        config["form_fields"] = [*config["form_fields"],
                                 {"key": "custom_note", "label": "یادداشت", "type": "Short Text"}]
        frappe.db.set_value("ASOUD Workflow Stage", form.name, "config_json", json.dumps(config))
        transition = frappe.db.get_value("ASOUD Workflow Transition", {
            "workflow_definition": name, "from_stage": form.name}, "name")
        frappe.db.set_value("ASOUD Workflow Transition", transition,
                            {"to_stage": extra.name, "transition_label": "بررسی کاربر"})
        frappe.get_doc({"doctype": "ASOUD Workflow Transition", "workflow_definition": name,
                        "from_stage": extra.name, "to_stage": stages["Approval"].name,
                        "transition_label": "ادامه", "sequence_no": 2}).insert(ignore_permissions=True)
        frappe.db.delete("ASOUD Workflow Definition", {"name": name})
        return name, stages, extra.name

    def _snapshot_rows(self, definition):
        return {table: frappe.get_all(table, filters={"workflow_definition": definition},
                                      fields=["*"], order_by="name") for table in TABLES[1:]}

    def test_adopts_orphan_stages_and_edited_routes_without_duplicates(self):
        name, _, extra = self._orphan_with_user_edits()
        before = self._snapshot_rows(name)
        self.assertEqual(seed.ensure_system_templates(self.company),
                         {"created": 1, "updated": 0, "skipped": 1})
        self.assertEqual(self._snapshot_rows(name), before)
        self.assertEqual(frappe.db.count("ASOUD Workflow Stage", {
            "workflow_definition": name, "stage_type": "Start"}), 1)
        self.assertTrue(frappe.db.exists("ASOUD Workflow Stage", extra))
        definition = frappe.get_doc("ASOUD Workflow Definition", name).as_dict()
        self.assertEqual(seed.ensure_system_templates(self.company),
                         {"created": 0, "updated": 0, "skipped": 2})
        self.assertEqual(self._snapshot_rows(name), before)
        self.assertEqual(frappe.get_doc("ASOUD Workflow Definition", name).as_dict(), definition)

    def test_repairs_only_missing_rows_and_relinks_detached_deterministic_rows(self):
        name, stages, extra = self._orphan_with_user_edits()
        end = stages["End"].name
        frappe.db.delete("ASOUD Workflow Transition", {"to_stage": end})
        frappe.db.delete("ASOUD Workflow Stage", {"name": end})
        start = stages["Start"].name
        frappe.db.set_value("ASOUD Workflow Stage", start, "workflow_definition", "")
        first = frappe.db.get_value("ASOUD Workflow Transition", {"from_stage": start}, "name")
        frappe.db.set_value("ASOUD Workflow Transition", first, "workflow_definition", "")
        self.assertEqual(seed.ensure_system_templates(self.company)["created"], 1)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", start, "workflow_definition"), name)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Transition", first, "workflow_definition"), name)
        self.assertEqual(frappe.db.count("ASOUD Workflow Stage", {
            "workflow_definition": name, "stage_type": "Start"}), 1)
        self.assertEqual(frappe.db.count("ASOUD Workflow Stage", {"workflow_definition": name}), 5)
        self.assertEqual(frappe.db.count("ASOUD Workflow Transition", {"workflow_definition": name}), 4)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage", extra, "stage_title"), "بررسی تکمیلی")
        after = self._snapshot_rows(name)
        self.assertEqual(seed.ensure_system_templates(self.company)["created"], 0)
        self.assertEqual(self._snapshot_rows(name), after)

    def test_multiple_orphan_starts_are_rejected_without_changes(self):
        name, _, extra = self._orphan_with_user_edits()
        frappe.db.set_value("ASOUD Workflow Stage", extra, "stage_type", "Start")
        before = self._snapshot_rows(name)
        with self.assertRaisesRegex(frappe.ValidationError, "بیش از یک مرحله شروع"):
            seed.ensure_system_templates(self.company)
        self.assertFalse(frappe.db.exists("ASOUD Workflow Definition", name))
        self.assertEqual(self._snapshot_rows(name), before)

    def test_a_stage_owned_by_another_definition_is_not_adopted(self):
        name, stages, _ = self._orphan_with_user_edits()
        foreign = self.definitions["purchase"]
        frappe.db.set_value("ASOUD Workflow Stage", stages["End"].name, "workflow_definition", foreign)
        before = self._snapshot_rows(foreign)
        with self.assertRaisesRegex(frappe.ValidationError, "متعلق به گردش‌کار دیگری"):
            seed.ensure_system_templates(self.company)
        self.assertFalse(frappe.db.exists("ASOUD Workflow Definition", name))
        self.assertEqual(self._snapshot_rows(foreign), before)

    def test_failed_repair_rolls_back_the_new_parent(self):
        name, stages, _ = self._orphan_with_user_edits()
        frappe.db.set_value("ASOUD Workflow Stage", stages["Start"].name, "stage_type", "User Task")
        before = self._snapshot_rows(name)
        with self.assertRaisesRegex(frappe.ValidationError, "شناسه مرحله شروع"):
            seed.ensure_system_templates(self.company)
        self.assertFalse(frappe.db.exists("ASOUD Workflow Definition", name))
        self.assertEqual(self._snapshot_rows(name), before)
