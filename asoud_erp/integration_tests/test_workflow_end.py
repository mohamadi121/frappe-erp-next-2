"""Real-site End audit regressions; only isolated fixtures, no production writes."""
import json

import frappe

from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create


class TestWorkflowEnd(APITestCase):
    def enter(self, outcome='Completed', message='پیام نتیجه آزمایش'):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        end = next(s for s in stages.values() if s.stage_type == 'End')
        end.db_set('config_json', json.dumps({'outcome': outcome, 'result_label': message}))
        result = create(self.company, definition=definition)
        return definition, stages, frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])

    def test_four_outcomes_have_distinct_valid_meanings(self):
        for outcome, expected in [('Completed', 'Completed'), ('Rejected', 'Rejected'),
                ('Cancelled', 'Cancelled'), ('Stopped', 'Failed')]:
            with self.subTest(outcome=outcome):
                _, _, instance = self.enter(outcome)
                self.assertEqual(instance.status, expected)
                self.assertTrue(instance.completed_on)

    def test_end_message_and_outcome_are_audited_once_and_retrievable(self):
        from asoud_erp.api.v1.workflow_runtime import _activate_stage, get_workflow_instance

        _, stages, instance = self.enter()
        end = next(s for s in stages.values() if s.stage_type == 'End')
        _activate_stage(instance, end)
        rows = frappe.get_all('ASOUD Workflow Activity', filters={'workflow_instance': instance.name,
            'action': 'پایان عملیات'}, fields=['comment', 'change_json'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].comment, 'پیام نتیجه آزمایش')
        self.assertEqual(json.loads(rows[0].change_json)['end_context']['outcome'], 'Completed')
        frappe.set_user(EMPLOYEE_USER)
        detail = get_workflow_instance(instance.name)['data']
        self.assertTrue(any(r['action'] == 'پایان عملیات' and r['after']['result_label'] == 'پیام نتیجه آزمایش'
            for r in detail['activities']))

    def test_terminal_instance_cannot_be_reopened_by_a_stale_activation(self):
        from asoud_erp.api.v1.workflow_runtime import _activate_stage

        _, stages, instance = self.enter()
        form = next(s for s in stages.values() if s.stage_type == 'User Task')
        count = frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance.name})
        with self.assertRaises(frappe.ValidationError):
            _activate_stage(instance, form)
        instance.reload()
        self.assertEqual(instance.status, 'Completed')
        self.assertEqual(frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance.name}), count)

    def test_invalid_outcome_is_rejected_not_silently_mapped(self):
        with self.assertRaises(frappe.ValidationError):
            self.enter('Unknown')

    def test_active_end_design_cannot_change_during_execution(self):
        from asoud_erp.api.v1.workflow import save_stage_settings

        definition, stages, _ = self.enter()
        end = next(s for s in stages.values() if s.stage_type == 'End')
        with self.assertRaises(frappe.ValidationError):
            save_stage_settings(definition, end.name, {'title': 'پایان تغییرکرده', 'outcome': 'Rejected'})

    def test_inactive_definition_with_a_running_instance_still_protects_end_settings(self):
        from asoud_erp.api.v1.workflow import save_stage_settings

        definition, stages = make_definition(self.company)
        create(self.company, definition=definition)
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        original = stages['End3'].config_json
        with self.assertRaises(frappe.ValidationError):
            save_stage_settings(definition, stages['End3'].name, {'title': 'پایان جدید', 'outcome': 'Cancelled'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Stage', stages['End3'].name, 'config_json'), original)

    def test_approval_reject_keeps_effective_decision_actor_and_reason(self):
        from asoud_erp.api.v1.workflow import save_stage_routes

        definition, stages = make_definition(self.company)
        approval, end = stages['Approval2'], stages['End3']
        save_stage_routes(definition, approval.name, {'Approve': end.name, 'Reject': end.name})
        request = create(self.company, definition=definition)
        act(request['workflow_instance'], 'Reject', comment='علت رد آزمایشی')
        row = frappe.db.get_value('ASOUD Workflow Activity', {'workflow_instance': request['workflow_instance'],
            'action': 'پایان عملیات'}, ['actor', 'change_json'], as_dict=True)
        context = json.loads(row.change_json)['end_context']
        self.assertEqual(row.actor, APPROVER_USER)
        self.assertEqual(context['outcome'], 'Rejected')
        self.assertEqual(context['decision_reason'], 'علت رد آزمایشی')
        self.assertEqual(json.loads(end.config_json)['outcome'], 'Completed')

    def test_late_human_reply_does_not_reopen_a_finished_instance(self):
        from asoud_erp.api.v1.workflow_runtime import complete_workflow_task

        _, stages, instance = self.enter()
        form = next(s for s in stages.values() if s.stage_type == 'User Task')
        task = frappe.get_doc({'doctype': 'ASOUD Workflow Task', 'workflow_instance': instance.name,
            'workflow_stage': form.name, 'task_title': 'وظیفهٔ قدیمی', 'assigned_to': EMPLOYEE_USER,
            'status': 'Open'}).insert(ignore_permissions=True)
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            complete_workflow_task(task.name, 'Complete')
        instance.reload()
        self.assertEqual(instance.status, 'Completed')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task.name, 'status'), 'Open')

    def test_cancel_end_cancels_pending_tasks_without_deleting_history(self):
        from asoud_erp.api.v1.workflow_runtime import _activate_stage

        definition, stages = make_definition(self.company)
        end, approval = stages['End3'], stages['Approval2']
        end.db_set('config_json', json.dumps({'outcome': 'Cancelled'}))
        request = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        count = frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance.name})
        self.assertEqual(instance.current_stage, approval.name)
        _activate_stage(instance, end)
        self.assertEqual(instance.status, 'Cancelled')
        self.assertEqual(frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance.name}), count)
        self.assertFalse(frappe.db.exists('ASOUD Workflow Task', {'workflow_instance': instance.name, 'status': 'Open'}))

    def test_invalid_incoming_or_outgoing_connection_is_blocked(self):
        from asoud_erp.api.v1.workflow_runtime import _activate_stage

        definition, stages = make_definition(self.company)
        request = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        end = stages['End3']
        frappe.get_doc({'doctype': 'ASOUD Workflow Transition', 'workflow_definition': definition,
            'from_stage': end.name, 'to_stage': stages['User Task1'].name}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            _activate_stage(instance, end)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance.name, 'status'), 'Running')

    def test_design_save_preserves_title_message_routes_and_creates_no_end_event(self):
        from asoud_erp.api.v1.workflow import get_workflow_design, save_stage_settings

        definition, stages = make_definition(self.company, approvals=0, fields=[])
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        end = stages['End2']
        before = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition}, pluck='name')
        count = frappe.db.count('ASOUD Workflow Instance', {'workflow_definition': definition})
        save_stage_settings(definition, end.name, {'title': 'پایان ویرایش‌شده', 'outcome': 'Stopped', 'result_label': 'علت توقف'})
        design = get_workflow_design(definition)['data']
        saved = next(row for row in design['stages'] if row['name'] == end.name)
        self.assertEqual(saved['stage_title'], 'پایان ویرایش‌شده')
        self.assertEqual(saved['config']['outcome'], 'Stopped')
        self.assertEqual(saved['config']['result_label'], 'علت توقف')
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {'workflow_definition': definition}), count)
        self.assertEqual(set(frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition}, pluck='name')), set(before))

    def test_condition_selects_one_of_two_real_end_nodes(self):
        from asoud_erp.api.v1.workflow import insert_workflow_stage

        definition, stages = make_definition(self.company, approvals=0, fields=[
            {'key': 'amount', 'label': 'عدد آزمایش', 'type': 'Number'}])
        edge = frappe.db.get_value('ASOUD Workflow Transition', {'from_stage': stages['User Task1'].name})
        design = insert_workflow_stage(definition, edge, 'Condition')['data']
        condition = next(row['name'] for row in design['stages'] if row['stage_type'] == 'Condition')
        frappe.db.set_value('ASOUD Workflow Stage', condition, {'configuration_status': 'Complete',
            'config_json': json.dumps({'source_kind': 'Form', 'source_field': 'amount', 'operator': 'Greater Than', 'compare_value': '0'})})
        target = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', 'workflow_definition': definition,
            'stage_key': 'rejected-end', 'stage_type': 'End', 'stage_title': 'پایان رد شرطی', 'sequence_no': 99,
            'config_json': json.dumps({'outcome': 'Rejected'}), 'configuration_status': 'Complete'}).insert(ignore_permissions=True)
        outgoing = frappe.db.get_value('ASOUD Workflow Transition', {'from_stage': condition})
        frappe.db.set_value('ASOUD Workflow Transition', outgoing, 'condition_json', json.dumps({'result': True}))
        frappe.get_doc({'doctype': 'ASOUD Workflow Transition', 'workflow_definition': definition,
            'from_stage': condition, 'to_stage': target.name, 'condition_json': json.dumps({'result': False})}).insert(ignore_permissions=True)
        for amount, status in [(1, 'Completed'), (-1, 'Rejected')]:
            result = create(self.company, definition=definition, values={'amount': amount})
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'], 'status'), status)
            self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_instance': result['workflow_instance'], 'action': 'پایان عملیات'}), 1)

    def test_end_message_does_not_send_notifications_or_submit_business_documents(self):
        from unittest.mock import patch

        from asoud_erp.api.v1 import workflow_runtime

        definition, stages = make_definition(self.company)
        request = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        end = stages['End3']
        end.db_set('config_json', json.dumps({'outcome': 'Completed', 'result_label': 'پیام صرفاً برای سابقه'}))
        before = {kind: frappe.db.count(kind) for kind in ('Journal Entry', 'Material Request', 'Notification Log')}
        with patch.object(workflow_runtime, '_notify_user') as notify:
            workflow_runtime._activate_stage(instance, end)
            notify.assert_not_called()
        for kind, count in before.items():
            self.assertEqual(frappe.db.count(kind), count)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Request', request['name'], 'docstatus'), 0)

    def test_end_after_a_real_inline_automatic_action_preserves_its_audit(self):
        from asoud_erp.api.v1.workflow import insert_workflow_stage

        definition, stages = make_definition(self.company)
        edge = frappe.db.get_value('ASOUD Workflow Transition', {'from_stage': stages['Approval2'].name})
        design = insert_workflow_stage(definition, edge, 'System Action')['data']
        automatic = next(row['name'] for row in design['stages'] if row['stage_type'] == 'System Action')
        frappe.db.set_value('ASOUD Workflow Stage', automatic, {'configuration_status': 'Complete',
            'config_json': json.dumps({'action_type': 'Send Notification', 'notify_initiator': True,
                'target_roles': [], 'message': 'اعلان خود اقدام خودکار'})})
        request = create(self.company, definition=definition)
        act(request['workflow_instance'], 'Approve')
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        self.assertEqual(instance.status, 'Completed')
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_instance': instance.name,
            'action': 'System Action Succeeded'}), 1)
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_instance': instance.name,
            'action': 'پایان عملیات'}), 1)
