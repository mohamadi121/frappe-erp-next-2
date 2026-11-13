"""Native path edits preserve shared nodes, history and cancellation semantics."""
import frappe

from asoud_erp.api.v1 import workflow, workflow_paths
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase


class TestWorkflowPathEditing(APITestCase):
    def graph(self):
        name = workflow.create_workflow_draft(company=self.company, workflow_title='ویرایش آزمایشی مسیر',
            module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': name, 'stage_type': 'Start'})
        workflow.add_workflow_stage(name, 'End', start)
        edge = frappe.db.get_value('ASOUD Workflow Transition', {'workflow_definition': name})
        return name, start, edge

    def test_cancel_restores_original_edge_and_removes_only_new_node(self):
        name, start, edge = self.graph()
        before = workflow.get_workflow_design(name)['data']
        reply = workflow.insert_workflow_stage(name, edge, 'Approval', draft_edit=1)['data']
        created = next(row for row in reply['stages'] if row['stage_type'] == 'Approval')['name']
        with self.assertRaises(frappe.ValidationError):
            workflow_paths.discard_inserted_stage(name, created, {'from_stage': start})
        workflow_paths.discard_inserted_stage(name, created, reply['insertion_token'])
        after = workflow.get_workflow_design(name)['data']
        self.assertEqual([row['name'] for row in after['stages']], [row['name'] for row in before['stages']])
        self.assertEqual([(row['from_stage'], row['to_stage'], row['condition']) for row in after['transitions']],
            [(row['from_stage'], row['to_stage'], row['condition']) for row in before['transitions']])

    def test_delete_shared_edge_does_not_delete_shared_target(self):
        name, start, edge = self.graph()
        end = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': name, 'stage_type': 'End'})
        other = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', 'workflow_definition': name,
            'stage_type': 'User Task', 'stage_key': 'other', 'stage_title': 'مسیر دوم',
            'sequence_no': 2, 'config_json': '{}'}).insert().name
        for source, target in ((start, other), (other, end)):
            frappe.get_doc({'doctype': 'ASOUD Workflow Transition', 'workflow_definition': name,
                'from_stage': source, 'to_stage': target}).insert()
        preview = workflow_paths.preview_path_removal(name, edge)['data']
        self.assertEqual(preview['stages'], [])
        workflow_paths.remove_path(name, edge, preview['version'])
        self.assertTrue(frappe.db.exists('ASOUD Workflow Stage', end))
        self.assertEqual(frappe.db.count('ASOUD Workflow Transition', {'workflow_definition': name}), 2)

    def test_cancel_does_not_overwrite_a_concurrent_route_change(self):
        name, _, edge = self.graph()
        reply = workflow.insert_workflow_stage(name, edge, 'Approval', draft_edit=1)['data']
        created = next(row for row in reply['stages'] if row['stage_type'] == 'Approval')['name']
        incoming = frappe.db.get_value('ASOUD Workflow Transition', {'workflow_definition': name, 'to_stage': created})
        frappe.db.set_value('ASOUD Workflow Transition', incoming, 'transition_label', 'مسیر ویرایش‌شده')
        with self.assertRaises(frappe.ValidationError):
            workflow_paths.discard_inserted_stage(name, created, reply['insertion_token'])
        self.assertTrue(frappe.db.exists('ASOUD Workflow Stage', created))
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Transition', incoming, 'transition_label'), 'مسیر ویرایش‌شده')

    def test_exclusive_branch_removal_and_stale_preview_guard(self):
        name, _, edge = self.graph()
        preview = workflow_paths.preview_path_removal(name, edge)['data']
        with self.assertRaises(frappe.ValidationError):
            workflow_paths.remove_path(name, edge, int(preview['version']) - 1)
        workflow_paths.remove_path(name, edge, preview['version'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Stage', {'workflow_definition': name}), 1)
        self.assertFalse(frappe.db.exists('ASOUD Workflow Transition', edge))

    def test_employee_and_active_definition_cannot_remove_paths(self):
        name, _, edge = self.graph()
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_paths.preview_path_removal(name, edge)
        frappe.set_user('Administrator')
        frappe.db.set_value('ASOUD Workflow Definition', name, 'status', 'Active')
        with self.assertRaises(frappe.ValidationError):
            workflow_paths.preview_path_removal(name, edge)

    def test_inactive_definition_with_execution_history_is_not_destructively_edited(self):
        from asoud_erp.integration_tests.request_fixtures import make_definition
        from asoud_erp.integration_tests.request_helpers import create

        name, _ = make_definition(self.company)
        create(self.company, definition=name)
        edge = frappe.db.get_value('ASOUD Workflow Transition', {'workflow_definition': name})
        frappe.db.set_value('ASOUD Workflow Definition', name, 'status', 'Inactive')
        with self.assertRaises(frappe.ValidationError):
            workflow_paths.preview_path_removal(name, edge)
        with self.assertRaises(frappe.ValidationError):
            workflow.insert_workflow_stage(name, edge, 'Approval', draft_edit=1)
