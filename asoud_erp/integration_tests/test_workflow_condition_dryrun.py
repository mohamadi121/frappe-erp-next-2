"""Real-site tests for the side-effect-free condition dry-run and the safe runtime comment.

Runs on an installed site (no database mocks). The dry-run endpoint is exercised over the
real API, and a real condition activation is checked to prove the Activity comment records
the chosen route without leaking the compared field value.
"""
import json

import frappe
from frappe.deferred_insert import save_to_db

from asoud_erp.api.v1 import workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


class TestWorkflowConditionDryRun(APITestCase):
    def graph(self, expected='Administrator', company=None):
        definition = workflow.create_workflow_draft(workflow_title='آزمون آزمایش شرط',
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

    def exits(self, definition, gate, true_title='پایان برقراری'):
        for result in (True, False):
            workflow.add_condition_branch(definition, gate, 'End', result)
        rows = {json.loads(row.condition_json)['result']: row.to_stage for row in frappe.get_all(
            'ASOUD Workflow Transition', filters={'workflow_definition': definition, 'from_stage': gate},
            fields=['condition_json', 'to_stage'])}
        workflow.save_stage_settings(definition, rows[True], {'title': true_title, 'outcome': 'Completed'})
        workflow.save_stage_settings(definition, rows[False], {'title': 'پایان رد', 'outcome': 'Rejected'})
        return rows

    def test_dry_run_reports_per_row_and_final_result(self):
        definition, gate, config = self.graph()
        true = workflow.test_workflow_condition(definition, gate, config, {'owner': 'Administrator'})
        self.assertEqual(true['data']['result'], True)
        self.assertEqual(true['data']['rows'], [{'id': 'owner', 'result': True, 'error': None}])
        false = workflow.test_workflow_condition(definition, gate, config, {'owner': 'someone-else'})
        self.assertEqual(false['data']['result'], False)
        self.assertEqual(false['data']['rows'], [{'id': 'owner', 'result': False, 'error': None}])

    def test_dry_run_missing_sample_is_a_row_error_and_null_result(self):
        definition, gate, config = self.graph()
        out = workflow.test_workflow_condition(definition, gate, config, {})
        self.assertIsNone(out['data']['result'])
        self.assertEqual(out['data']['rows'], [
            {'id': 'owner', 'result': None, 'error': 'برای این شرط مقدار نمونه وارد نشده است.'}])

    def test_dry_run_invalid_range_is_a_validation_error(self):
        definition, gate, _ = self.graph()
        bad = dict(title='بازه', condition_version=2, combine='All', conditions=[
            dict(id='r', source_kind='System', source_stage='', source_field='started_on',
                field_type='Date', operator='Between', value='2026-01-31', value_to='2026-01-01')])
        with self.assertRaises(frappe.ValidationError):
            workflow.test_workflow_condition(definition, gate, bad, {'r': '2026-01-15'})

    def test_dry_run_is_read_only(self):
        definition, gate, config = self.graph()
        before = {doctype: frappe.db.count(doctype) for doctype in
                  ('ASOUD Workflow Activity', 'ASOUD Workflow Task', 'ASOUD Workflow Instance')}
        workflow.test_workflow_condition(definition, gate, config, {'owner': 'Administrator'})
        after = {doctype: frappe.db.count(doctype) for doctype in before}
        self.assertEqual(before, after)

    def test_dry_run_requires_the_designer_role(self):
        definition, gate, config = self.graph()
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.test_workflow_condition(definition, gate, config, {'owner': 'Administrator'})
        frappe.set_user('Administrator')

    def test_dry_run_company_scope(self):
        foreign = setup_tenancy()['second']
        definition, gate, config = self.graph(company=foreign)
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.test_workflow_condition(definition, gate, config, {'owner': 'Administrator'})
        frappe.set_user('Administrator')

    def test_runtime_comment_records_route_without_the_field_value(self):
        definition, gate, _ = self.graph(expected='Administrator')
        self.exits(definition, gate)
        workflow.set_workflow_status(definition, 'Active')
        instance = workflow_runtime.start_workflow_instance(definition, 'آزمون اجرای شرط')['data']['name']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')
        activity = frappe.get_all('ASOUD Workflow Activity', filters={'workflow_instance': instance,
            'workflow_stage': gate}, fields=['action', 'comment'], limit=1)[0]
        self.assertEqual(activity.action, 'Condition True')
        self.assertIn('پایان برقراری', activity.comment)
        self.assertIn('نتیجه: برقرار است؛ مسیر:', activity.comment)
        self.assertNotIn('Administrator', activity.comment)

    def test_failing_condition_keeps_the_error_log_after_rollback(self):
        # A System `requester_unit` condition raises at runtime for Administrator (no
        # Employee/department), so the condition stage fails and the request rolls back.
        definition = workflow.create_workflow_draft(workflow_title='آزمون ثبت خطای شرط',
            company=self.company, module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        workflow.save_start_settings(definition, 'Manual', ['System Manager'], 'General Subject')
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'Condition', start)
        gate = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Condition'})
        config = dict(title='بررسی واحد ثبت‌کننده', condition_version=2, combine='All', conditions=[
            dict(id='unit', source_kind='System', source_stage='', source_field='requester_unit',
                field_type='Text', operator='Is Set')])
        workflow.save_stage_settings(definition, gate, config)
        self.exits(definition, gate)
        workflow.set_workflow_status(definition, 'Active')
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.start_workflow_instance(definition, 'آزمون خطای شرط')
        # frappe.throw does not roll back in tests; the rollback below stands in for the request one.
        instance = frappe.db.get_value('ASOUD Workflow Instance',
            {'workflow_definition': definition, 'started_by': 'Administrator', 'status': 'Running'})
        self.assertTrue(instance, 'the failing instance row should still be in the open transaction')
        frappe.db.rollback()
        save_to_db()
        logs = frappe.get_all('Error Log', filters={'reference_doctype': 'ASOUD Workflow Instance',
            'reference_name': instance}, fields=['reference_name', 'method'], limit=1)
        self.assertTrue(logs, 'deferred Error Log row is missing after the rollback')
        self.assertEqual(logs[0].reference_name, instance)
        self.assertEqual(logs[0].method, 'خطا در ارزیابی شرط گردش کار')
