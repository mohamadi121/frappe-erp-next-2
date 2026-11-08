"""Real definition: the condition field catalog carries the new System fields and
picker/currency metadata, and a stored `started_by` config still validates."""
import json

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import APITestCase


class TestWorkflowConditionCatalog(APITestCase):
    def _definition_with_condition(self):
        definition = workflow.create_workflow_draft(workflow_title='آزمون فهرست فیلدهای شرط',
            company=self.company, module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        workflow.save_start_settings(definition, 'Manual', ['System Manager'], 'General Subject')
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'Condition', start)
        return definition, frappe.db.get_value('ASOUD Workflow Stage',
            {'workflow_definition': definition, 'stage_type': 'Condition'})

    def _system_rows(self, definition, gate):
        rows = workflow.workflow_condition_fields(definition, gate)['data']['condition_fields_v2']
        return {row['source_field']: row for row in rows if row['source_kind'] == 'System'}

    def test_catalog_exposes_new_system_fields_with_metadata(self):
        definition, gate = self._definition_with_condition()
        rows = self._system_rows(definition, gate)
        self.assertIn('requester_unit', rows)
        self.assertEqual(rows['started_by']['value_source'], 'user')
        self.assertEqual(rows['started_by']['link_doctype'], 'User')
        self.assertEqual(rows['started_by']['field_type'], 'Text')
        self.assertEqual(rows['requester_unit']['value_source'], 'department')
        self.assertEqual(rows['requester_unit']['link_doctype'], 'Department')
        self.assertEqual(rows['requester_unit']['field_type'], 'Text')
        # The instance status is always Running while a condition evaluates, so it is not offered.
        self.assertNotIn('status', rows)

    def test_stored_started_by_config_still_validates(self):
        definition, gate = self._definition_with_condition()
        config = dict(title='بررسی ثبت‌کننده', condition_version=2, combine='All', conditions=[
            dict(id='owner', source_kind='System', source_stage='', source_field='started_by',
                field_type='Text', operator='Equals', value='Administrator')])
        workflow.save_stage_settings(definition, gate, config)
        stored = json.loads(frappe.db.get_value('ASOUD Workflow Stage', gate, 'config_json'))
        self.assertEqual(stored['conditions'][0]['source_field'], 'started_by')
        self.assertEqual(stored['conditions'][0]['field_type'], 'Text')

    def test_status_is_not_a_condition_source(self):
        definition, gate = self._definition_with_condition()
        config = dict(title='وضعیت', condition_version=2, combine='All', conditions=[
            dict(id='st', source_kind='System', source_stage='', source_field='status',
                field_type='Select', operator='Equals', value='Running')])
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, gate, config)
