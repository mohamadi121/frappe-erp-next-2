"""Native records, real APIs and real condition activation; no database mocks."""
import json

import frappe

from asoud_erp.api.v1 import workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


class TestWorkflowConditionV2(APITestCase):
    def graph(self, expected='Administrator', company=None):
        definition = workflow.create_workflow_draft(workflow_title='آزمون شرط ترکیبی',
            company=company or self.company, module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        workflow.save_start_settings(definition, 'Manual', ['System Manager'], 'General Subject')
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'Condition', start)
        gate = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Condition'})
        config = dict(title='بررسی ثبت‌کننده', condition_version=2, combine='All', conditions=[
            dict(id='owner', source_kind='System', source_stage='', source_field='started_by',
                field_type='Text', operator='Equals', value=expected)])
        workflow.save_stage_settings(definition, gate, config)
        return definition, gate, config

    def exits(self, definition, gate):
        for result in (True, False):
            workflow.add_condition_branch(definition, gate, 'End', result)
        return {json.loads(row.condition_json)['result']: row.to_stage for row in frappe.get_all(
            'ASOUD Workflow Transition', filters={'workflow_definition': definition, 'from_stage': gate},
            fields=['condition_json', 'to_stage'])}

    def test_real_execution_selects_exactly_one_boolean_output(self):
        for expected, outcome, action in [('Administrator', 'Completed', 'Condition True'),
                ('not-the-initiator', 'Rejected', 'Condition False')]:
            definition, gate, _ = self.graph(expected)
            exits = self.exits(definition, gate)
            workflow.save_stage_settings(definition, exits[False], {'title': 'پایان با رد', 'outcome': 'Rejected'})
            workflow.set_workflow_status(definition, 'Active')
            instance = workflow_runtime.start_workflow_instance(definition, 'آزمون اجرای شرط')['data']['name']
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), outcome)
            rows = frappe.get_all('ASOUD Workflow Activity', filters={'workflow_instance': instance,
                'workflow_stage': gate}, pluck='action')
            self.assertEqual(rows, [action])
            self.assertFalse(frappe.db.exists('ASOUD Workflow Task', {'workflow_instance': instance}))

    def test_activation_requires_both_exits_and_save_preserves_identity(self):
        definition, gate, config = self.graph()
        with self.assertRaises(frappe.ValidationError):
            workflow.set_workflow_status(definition, 'Active')
        exits = self.exits(definition, gate)
        original = frappe.db.get_value('ASOUD Workflow Transition', {'from_stage': gate,
            'to_stage': exits[True]}, 'name')
        workflow.connect_workflow_stages(definition, gate, exits[False], 'شرط برقرار است', {'result': True})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Transition', original, 'to_stage'), exits[False])
        self.assertEqual(json.loads(frappe.db.get_value('ASOUD Workflow Stage', gate, 'config_json'))['conditions'], config['conditions'])
        workflow.connect_workflow_stages(definition, gate, '', 'شرط برقرار نیست', {'result': False})
        self.assertEqual(frappe.db.count('ASOUD Workflow Transition', {'from_stage': gate}), 1)
        with self.assertRaises(frappe.ValidationError):
            workflow.set_workflow_status(definition, 'Active')

    def test_stale_field_and_unprivileged_or_foreign_designer_are_rejected(self):
        definition, gate, config = self.graph()
        config['conditions'][0]['source_field'] = 'removed_field'
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, gate, config)
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.workflow_condition_fields(definition, gate)
        frappe.set_user('Administrator')
        other = setup_tenancy()['second']
        foreign, foreign_gate, _ = self.graph(company=other)
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.workflow_condition_fields(foreign, foreign_gate)

    def test_active_definition_cannot_change_rules_or_add_exits(self):
        definition, gate, config = self.graph()
        self.exits(definition, gate)
        workflow.set_workflow_status(definition, 'Active')
        config['conditions'][0]['value'] = 'changed'
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, gate, config)
        with self.assertRaises(frappe.ValidationError):
            workflow.add_condition_branch(definition, gate, 'End', True)
        stored = json.loads(frappe.db.get_value('ASOUD Workflow Stage', gate, 'config_json'))
        self.assertEqual(stored['conditions'][0]['value'], 'Administrator')
