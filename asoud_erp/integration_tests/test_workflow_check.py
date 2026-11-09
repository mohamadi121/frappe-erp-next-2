"""Real-site tests for the read-only workflow validity check and simulation."""
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


class TestWorkflowCheck(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = setup_tenancy()['second']

    def _stage_names(self, definition):
        return {row['stage_type']: row['name'] for row in
                frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': definition},
                               fields=['name', 'stage_type'])}

    def _counts(self):
        return (frappe.db.count('ASOUD Workflow Instance'),
                frappe.db.count('ASOUD Workflow Task'),
                frappe.db.count('Notification Log'))

    def _ready_definition(self, company):
        """A make_definition graph whose Start stage carries a valid trigger config."""
        definition, _ = make_definition(company, approvals=1, fields=[])
        start = self._stage_names(definition)['Start']
        frappe.db.set_value('ASOUD Workflow Stage', start, 'config_json',
                            json.dumps({"title": "شروع", "trigger_type": "Manual",
                                        "initiator_roles": ["Employee"]}, ensure_ascii=False))
        return definition

    def test_validate_reports_ok_on_complete_graph(self):
        definition = self._ready_definition(self.company)
        result = workflow.validate_workflow(definition)['data']
        self.assertTrue(result['ok'])
        self.assertEqual(result['issues'], [])

    def test_validate_reports_stage_invalid_when_start_lacks_trigger(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        result = workflow.validate_workflow(definition)['data']
        self.assertFalse(result['ok'])
        self.assertIn('stage_invalid', [issue['code'] for issue in result['issues']])

    def test_validate_reports_unreachable_stage(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        # A stage with no incoming route is unreachable from Start.
        orphan = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', 'workflow_definition': definition,
            'stage_key': 'orphan-check', 'stage_title': 'متروک', 'stage_type': 'User Task',
            'sequence_no': 99, 'configuration_status': 'Complete',
            'config_json': '{"title": "متروک", "activity_type": "Task", "assignment_type": "Initiator"}'}).insert()
        result = workflow.validate_workflow(definition)['data']
        self.assertFalse(result['ok'])
        self.assertIn('disconnected', [issue['code'] for issue in result['issues']])
        self.assertTrue(frappe.db.exists('ASOUD Workflow Stage', orphan.name))

    def test_validate_reports_disabled_form_as_missing(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        user_task = next(row['name'] for row in frappe.get_all('ASOUD Workflow Stage',
            filters={'workflow_definition': definition, 'stage_type': 'User Task'}, fields=['name']))
        # A disabled form of the same company must not count as an available source.
        form = frappe.get_doc({'doctype': 'ASOUD Form', 'title': 'فرم غیرفعال ' + uuid4().hex[:6],
                               'company': self.company, 'disabled': 1})
        form.flags.form_service = True
        form.insert()
        stage = frappe.get_doc('ASOUD Workflow Stage', user_task)
        config = json.loads(stage.config_json or '{}')
        config['submission_source'] = {'form': form.name, 'revision': '1'}
        stage.config_json = json.dumps(config, ensure_ascii=False)
        stage.save()
        result = workflow.validate_workflow(definition)['data']
        self.assertFalse(result['ok'])
        self.assertIn('form_missing', [issue['code'] for issue in result['issues']])

    def test_simulate_approve_reject_and_return_paths(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        names = self._stage_names(definition)
        user_task, approval, end = names['User Task'], names['Approval'], names['End']

        approve = workflow.simulate_workflow(definition, [
            {'stage': user_task, 'action': 'Complete'},
            {'stage': approval, 'action': 'Approve'}])['data']
        self.assertEqual([step['stage'] for step in approve['steps']],
                         [names['Start'], user_task, approval, end])
        self.assertEqual(approve['status'], 'finished')
        self.assertEqual(approve['outcome'], 'Completed')

        # Reject has no route in this graph, so the instance ends as Rejected.
        reject = workflow.simulate_workflow(definition, [
            {'stage': user_task, 'action': 'Complete'},
            {'stage': approval, 'action': 'Reject'}])['data']
        self.assertEqual(reject['status'], 'finished')
        self.assertEqual(reject['outcome'], 'Rejected')
        self.assertNotIn(user_task, [step['stage'] for step in reject['steps']][2:])

    def test_simulate_waits_for_a_missing_decision(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        names = self._stage_names(definition)
        result = workflow.simulate_workflow(definition, [{'stage': names['User Task'], 'action': 'Complete'}])['data']
        self.assertEqual(result['status'], 'needs_decision')
        self.assertEqual(result['waiting_stage'], names['Approval'])
        self.assertEqual(result['allowed_actions'], ['Approve', 'Reject', 'Return'])

    def test_simulate_writes_nothing(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        names = self._stage_names(definition)
        before = self._counts()
        for decisions in ([], [{'stage': names['User Task'], 'action': 'Complete'},
                               {'stage': names['Approval'], 'action': 'Approve'}]):
            workflow.simulate_workflow(definition, decisions)
        self.assertEqual(self._counts(), before)
        self.assertFalse(frappe.db.exists('ASOUD Workflow Instance',
                                          {'workflow_definition': definition}))

    def test_role_gate_and_company_scope(self):
        definition, _ = make_definition(self.company, approvals=1, fields=[])
        # A user without the design roles is rejected before any read.
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.validate_workflow(definition)
        with self.assertRaises(frappe.PermissionError):
            workflow.simulate_workflow(definition, [])
        # A manager of another company is rejected by company scope.
        other, _ = make_definition(self.second, approvals=1, fields=[])
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.validate_workflow(other)

    def test_user_without_employee_record_can_validate(self):
        definition = self._ready_definition(self.company)
        # Administrator has no Employee record; the check must still work.
        self.assertFalse(frappe.db.exists('Employee', {'user_id': 'Administrator'}))
        result = workflow.validate_workflow(definition)['data']
        self.assertTrue(result['ok'])
