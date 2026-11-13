"""Server-side guard: a Return route must not point at an End or Wait stage.

The app blocks this in the route editor; the server is the second line of
defense. Reject -> End stays allowed (the "end as rejected" path).
"""
import json

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create


class TestWorkflowReturnRoute(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1)
        self.approval = self.stages["Approval2"]
        self.end = self.stages["End3"]
        self.user_task = self.stages["User Task1"]

    def _actions(self):
        return {json.loads(row.condition_json)["action"]: row.to_stage
                for row in frappe.get_all("ASOUD Workflow Transition",
                                          filters={"from_stage": self.approval.name},
                                          fields=["to_stage", "condition_json"])}

    def test_return_to_end_is_refused(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            workflow.save_stage_routes(self.definition, self.approval.name,
                                       {"Approve": self.end.name, "Return": self.end.name})
        self.assertIn("مسیر بازگشت برای اصلاح باید به یک ایستگاه قابل‌اجرای قبلی برود.", str(ctx.exception))

    def test_return_to_a_user_task_is_saved(self):
        workflow.save_stage_routes(self.definition, self.approval.name,
                                   {"Approve": self.end.name, "Return": self.user_task.name})
        self.assertEqual(self._actions().get("Return"), self.user_task.name)

    def test_reject_to_end_stays_allowed(self):
        workflow.save_stage_routes(self.definition, self.approval.name,
                                   {"Approve": self.end.name, "Reject": self.end.name})
        self.assertEqual(self._actions().get("Reject"), self.end.name)

    def test_reject_to_normal_end_is_rejected_not_successful(self):
        workflow.save_stage_routes(self.definition, self.approval.name,
            {'Approve': self.end.name, 'Reject': self.end.name})
        request = create(self.company, definition=self.definition)
        act(request['workflow_instance'], 'Reject', comment='رد درخواست')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance',
            request['workflow_instance'], 'status'), 'Rejected')
        self.assertEqual(json.loads(frappe.db.get_value('ASOUD Workflow Stage',
            self.end.name, 'config_json'))['outcome'], 'Completed')

    def test_approve_cannot_select_rejected_end(self):
        self.end.db_set('config_json', json.dumps({'title': 'پایان رد', 'outcome': 'Rejected'}))
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval.name,
                {'Approve': self.end.name})

    def test_approve_does_not_fall_back_to_a_reject_only_route(self):
        from asoud_erp.api.v1 import workflow_runtime

        workflow.save_stage_routes(self.definition, self.approval.name,
            {'Approve': '', 'Reject': self.end.name})
        request = create(self.company, definition=self.definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        self.assertIsNone(workflow_runtime._next_stage(instance, self.approval.name, 'Approve'))

    def test_legacy_persian_approval_label_remains_executable(self):
        edge = frappe.get_doc('ASOUD Workflow Transition', frappe.db.get_value(
            'ASOUD Workflow Transition', {'from_stage': self.approval.name}, 'name'))
        edge.condition_json = '{}'
        edge.transition_label = 'تأیید'
        edge.save()
        request = create(self.company, definition=self.definition)
        act(request['workflow_instance'], 'Approve')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', request['workflow_instance'], 'status'), 'Completed')

    def test_missing_destination_has_a_clear_error(self):
        with self.assertRaises(frappe.ValidationError) as error:
            workflow.save_stage_routes(self.definition, self.approval.name,
                {'Approve': 'removed-stage'})
        self.assertIn('مقصد', str(error.exception))

    def test_real_targets_survive_rename_and_select_without_creating_nodes(self):
        definition, stages = make_definition(self.company, approvals=2)
        source, next_stage = stages['Approval2'], stages['Approval3']
        count = frappe.db.count('ASOUD Workflow Stage', {'workflow_definition': definition})
        workflow.save_stage_routes(definition, source.name, {'Approve': next_stage.name,
            'Reject': next_stage.name, 'Return': stages['User Task1'].name})
        next_stage.stage_title = 'رسیدگی مجدد'
        next_stage.save()
        design = workflow.get_workflow_design(definition)['data']
        saved = {row['condition']['action']: row['to_stage'] for row in design['transitions']
            if row['from_stage'] == source.name}
        self.assertEqual(saved, {'Approve': next_stage.name, 'Reject': next_stage.name,
            'Return': stages['User Task1'].name})
        self.assertEqual(frappe.db.count('ASOUD Workflow Stage', {'workflow_definition': definition}), count)
        request = create(self.company, definition=definition)
        act(request['workflow_instance'], 'Reject', comment='برای رسیدگی بیشتر')
        self.assertTrue(frappe.db.exists('ASOUD Workflow Task', {'workflow_instance': request['workflow_instance'],
            'workflow_stage': next_stage.name, 'status': 'Open'}))
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', request['workflow_instance'], 'status'), 'Running')

    def test_explicit_return_and_approve_execute_on_the_same_request(self):
        workflow.save_stage_routes(self.definition, self.approval.name, {'Approve': self.end.name,
            'Reject': '', 'Return': self.user_task.name})
        for action in ('Approve', 'Return'):
            with self.subTest(action=action):
                request = create(self.company, definition=self.definition)
                act(request['workflow_instance'], action, comment='تصمیم آزمایشی')
                instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
                self.assertEqual(instance.reference_name, request['name'])
                self.assertEqual(instance.current_stage, self.end.name if action == 'Approve' else self.user_task.name)
                self.assertEqual(instance.status, 'Completed' if action == 'Approve' else 'Running')
                self.assertEqual(frappe.db.count('ASOUD Workflow Instance',
                    {'reference_doctype': 'ASOUD Workflow Request', 'reference_name': request['name']}), 1)

    def test_automatic_return_prefers_modern_result_form_over_older_form(self):
        definition, stages = make_definition(self.company, approvals=1)
        from uuid import uuid4

        from asoud_erp.api.v1 import forms

        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم نتیجه اصلاح',
            'sections': [{'id': 'main', 'title': 'نتیجه', 'fields': [{'key': 'note', 'label': 'گزارش', 'type': 'Text'}]}]},
            client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        form = forms.get_form(saved['name'])['data']
        newer = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', 'workflow_definition': definition,
            'stage_key': 'modern-form', 'stage_title': 'گزارش جدید', 'stage_type': 'User Task',
            'sequence_no': 2, 'config_json': '{}'}).insert()
        workflow.save_stage_settings(definition, newer.name, {'title': 'گزارش جدید',
            'action_contract_version': 1, 'result_mode': 'Form', 'activity_type': 'Data Entry',
            'task_purpose': 'Existing', 'assignment_type': 'Initiator',
            'assignment_rule': {'basis': 'Subject', 'subject': 'Initiator'},
            'result_form': {'form': form['name'], 'revision': form['revision']}})
        request = create(self.company, definition=definition)
        # A real completed task represents a later action in this execution.
        from frappe.utils import add_to_date, now_datetime
        original = frappe.get_doc('ASOUD Workflow Task', frappe.db.get_value('ASOUD Workflow Task',
            {'workflow_instance': request['workflow_instance'], 'workflow_stage': stages['User Task1'].name}, 'name'))
        task = frappe.copy_doc(original)
        task.workflow_stage = newer.name
        task.completed_on = add_to_date(now_datetime(), seconds=1)
        task.insert(ignore_permissions=True)
        act(request['workflow_instance'], 'Return', comment='اصلاح آخرین فرم')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', request['workflow_instance'],
            'current_stage'), newer.name)

    def test_return_cannot_point_to_a_later_executable_stage(self):
        later = frappe.get_doc({'doctype': 'ASOUD Workflow Stage',
            'workflow_definition': self.definition, 'stage_key': 'later-correction',
            'stage_title': 'اقدام بعدی', 'stage_type': 'User Task', 'sequence_no': 99,
            'config_json': '{}', 'configuration_status': 'Pending'}).insert().name
        before = frappe.get_all('ASOUD Workflow Transition', filters={
            'workflow_definition': self.definition}, fields=['name', 'from_stage', 'to_stage'], order_by='name')
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval.name,
                {'Approve': self.end.name, 'Return': later})
        self.assertEqual(frappe.get_all('ASOUD Workflow Transition', filters={
            'workflow_definition': self.definition}, fields=['name', 'from_stage', 'to_stage'], order_by='name'), before)

    def test_comment_policy_is_enforced_even_with_legacy_disabled_reason_flags(self):
        for required in (False, True):
            for action in ('Approve', 'Reject', 'Return'):
                with self.subTest(required=required, action=action):
                    definition, stages = make_definition(self.company, approvals=1)
                    stage = stages['Approval2']
                    settings = {**json.loads(stage.config_json), 'comment_required': required,
                        'reject_comment_required': False}
                    workflow.save_stage_settings(definition, stage.name, settings)
                    design = workflow.get_workflow_design(definition)['data']
                    stored = next(row['config'] for row in design['stages'] if row['name'] == stage.name)
                    self.assertEqual(stored['comment_required'], required)
                    request = create(self.company, definition=definition, values={'reason': 'اطلاعات اصلی'})
                    if required or action != 'Approve':
                        with self.assertRaises(frappe.ValidationError):
                            act(request['workflow_instance'], action, comment='')
                        self.assertTrue(frappe.db.exists('ASOUD Workflow Task', {
                            'workflow_instance': request['workflow_instance'], 'status': 'Open'}))
                        act(request['workflow_instance'], action, comment='دلیل تصمیم')
                    else:
                        act(request['workflow_instance'], action, comment='')
                    self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {
                        'reference_doctype': 'ASOUD Workflow Request', 'reference_name': request['name']}), 1)
