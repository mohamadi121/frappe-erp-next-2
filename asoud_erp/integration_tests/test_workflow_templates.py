"""Real native graph copies, role boundaries and unchanged template records."""
import frappe

from asoud_erp.api.v1 import workflow, workflow_templates
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.services.request_templates.seed import ensure_system_templates


class TestWorkflowTemplates(APITestCase):
    def setUp(self):
        super().setUp()
        ensure_system_templates(self.company)
        self.source = workflow_templates.catalog(self.company)["data"]["items"][0]

    def test_copy_is_unpublished_independent_and_has_no_execution_records(self):
        before = workflow.get_workflow_design(self.source.name)["data"]
        copy = workflow_templates.create_from_template(company=self.company, source=self.source.name,
            source_modified=str(self.source.modified), workflow_title="گردش کپی مستقل")["data"]
        self.assertNotEqual(copy["name"], self.source.name)
        self.assertEqual(copy["status"], "Inactive")
        self.assertTrue(copy["is_locked"])
        self.assertFalse(copy.get("frappe_workflow"))
        self.assertFalse(copy.get("is_system_template"))
        self.assertFalse(copy.get("template_key"))
        self.assertFalse(copy.get("show_in_request_list"))
        after = workflow.get_workflow_design(copy["name"])["data"]
        old_ids = {row["name"] for row in before["stages"]}
        new_ids = {row["name"] for row in after["stages"]}
        self.assertTrue(old_ids.isdisjoint(new_ids))
        self.assertEqual(len(before["transitions"]), len(after["transitions"]))
        for edge in after["transitions"]:
            self.assertIn(edge["from_stage"], new_ids)
            self.assertIn(edge["to_stage"], new_ids)
        self.assertEqual(before, workflow.get_workflow_design(self.source.name)["data"])
        self.assertFalse(frappe.db.exists("ASOUD Workflow Instance", {"workflow_definition": copy["name"]}))

    def test_stale_template_and_employee_are_rejected(self):
        with self.assertRaises(frappe.TimestampMismatchError):
            workflow_templates.create_from_template(self.company, self.source.name, "stale", "گردش مستقل")
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_templates.catalog(self.company)
        with self.assertRaises(frappe.PermissionError):
            workflow_templates.create_from_template(self.company, self.source.name,
                str(self.source.modified), "گردش مستقل")
