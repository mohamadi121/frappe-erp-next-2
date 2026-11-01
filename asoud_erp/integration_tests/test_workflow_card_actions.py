"""Real database lifecycle and native permission/link guard regression tests."""
import json

import frappe
from frappe.client import delete

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy
from asoud_erp.services.request_templates.seed import ensure_system_templates


class TestWorkflowCardActions(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.foreign_company = setup_tenancy()['second']

    def draft(self):
        return workflow.create_workflow_draft(workflow_title='گردش آزمون منو', company=self.company,
            module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']

    def complete(self, name):
        start = frappe.get_doc('ASOUD Workflow Stage', {'workflow_definition': name, 'stage_type': 'Start'})
        workflow.save_start_settings(name, 'Manual', ['Employee'], 'General Subject')
        workflow.add_workflow_stage(name, 'User Task', start.name)
        task_name = next(row['name'] for row in workflow.get_workflow_design(name)['data']['stages']
                         if row['stage_type'] == 'User Task')
        workflow.save_stage_settings(name, task_name, {'title': 'بررسی', 'activity_type': 'Task',
            'assignment_type': 'Initiator'})
        workflow.add_workflow_stage(name, 'End', task_name)

    def test_delete_unused_draft_removes_only_owned_graph(self):
        name, other = self.draft(), self.draft()
        delete('ASOUD Workflow Definition', name)
        self.assertFalse(frappe.db.exists('ASOUD Workflow Definition', name))
        self.assertFalse(frappe.db.exists('ASOUD Workflow Stage', {'workflow_definition': name}))
        self.assertTrue(frappe.db.exists('ASOUD Workflow Definition', other))

    def test_system_and_employee_delete_are_rejected(self):
        ensure_system_templates(self.company)
        system = frappe.db.get_value('ASOUD Workflow Definition',
            {'company': self.company, 'is_system_template': 1}, 'name')
        with self.assertRaises(frappe.ValidationError):
            delete('ASOUD Workflow Definition', system)
        name = self.draft()
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            delete('ASOUD Workflow Definition', name)
        with self.assertRaises(frappe.PermissionError):
            workflow.set_workflow_status(name, 'Active')

    def test_activate_deactivate_and_reload_without_native_link(self):
        name = self.draft()
        with self.assertRaises(frappe.ValidationError):
            workflow.set_workflow_status(name, 'Active')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', name, 'status'), 'Inactive')
        self.complete(name)
        activated = workflow.set_workflow_status(name, 'Active')['data']
        self.assertEqual(activated['status'], 'Active')
        self.assertFalse(activated['is_locked'])
        self.assertFalse(activated.get('frappe_workflow'))
        self.assertEqual(workflow.get_workflow_design(name)['data']['workflow']['status'], 'Active')
        self.assertEqual(workflow.set_workflow_status(name, 'Inactive')['data']['status'], 'Inactive')
        self.assertTrue(any(row['name'] == name for row in
            workflow.list_workflows(company=self.company, status='Inactive')['data']))

    def test_details_summary_is_fresh_read_only_for_all_three_states(self):
        name = self.draft()
        pending = workflow.get_workflow_design(name)['data']['details_summary']
        self.assertFalse(pending['stages_complete'])
        self.assertFalse(pending['routes_complete'])
        self.complete(name)
        doc = frappe.get_doc('ASOUD Workflow Definition', name)
        # These stale storage fields must not manufacture missing routes.
        self.assertEqual(doc.readiness_status, 'Pending')
        before = doc.as_dict()
        versions = frappe.db.count('Version', {'ref_doctype': doc.doctype, 'docname': name})
        complete = workflow.get_workflow_design(name)['data']['details_summary']
        self.assertEqual(complete, {'steps_count': 2, 'stages_complete': True,
            'routes_complete': True, 'requirements': []})
        self.assertEqual(frappe.get_doc(doc.doctype, name).as_dict(), before)
        self.assertEqual(frappe.db.count('Version', {'ref_doctype': doc.doctype, 'docname': name}), versions)
        workflow.set_workflow_status(name, 'Active')
        self.assertEqual(workflow.get_workflow_design(name)['data']['details_summary'], complete)
        workflow.set_workflow_status(name, 'Inactive')
        self.assertEqual(workflow.get_workflow_design(name)['data']['details_summary'], complete)

    def test_running_and_completed_history_prevent_delete(self):
        for status in ('Running', 'Completed'):
            name = self.draft()
            instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': name,
                'subject': 'سابقهٔ محفوظ', 'status': status}).insert()
            stages = frappe.db.count('ASOUD Workflow Stage', {'workflow_definition': name})
            with self.assertRaises(frappe.ValidationError):
                delete('ASOUD Workflow Definition', name)
            self.assertTrue(frappe.db.exists('ASOUD Workflow Instance', instance.name))
            self.assertEqual(frappe.db.count('ASOUD Workflow Stage', {'workflow_definition': name}), stages)

    def test_other_company_is_rejected_before_status_or_delete(self):
        name = workflow.create_workflow_draft(workflow_title='دفتر دیگر', company=self.foreign_company,
            module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.set_workflow_status(name, 'Inactive')
        with self.assertRaises(frappe.PermissionError):
            delete('ASOUD Workflow Definition', name)

    def test_json_dependency_and_versions_are_preserved(self):
        name, other = self.draft(), self.draft()
        stage = frappe.get_doc('ASOUD Workflow Stage', {'workflow_definition': other})
        stage.config_json = json.dumps({'request_definition': name})
        stage.save()
        with self.assertRaises(frappe.ValidationError):
            delete('ASOUD Workflow Definition', name)
        self.assertTrue(frappe.db.exists('ASOUD Workflow Definition', name))
        versioned = frappe.get_doc('ASOUD Workflow Definition', self.draft())
        versioned.workflow_title = 'ویرایش دارای سابقه'
        versioned.save()
        self.assertTrue(frappe.db.exists('Version', {'ref_doctype': versioned.doctype, 'docname': versioned.name}))
        with self.assertRaises(frappe.ValidationError):
            delete(versioned.doctype, versioned.name)
