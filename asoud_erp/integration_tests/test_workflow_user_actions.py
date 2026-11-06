"""Native user-action regressions; no mocked DB and no live production writes."""
import json
from uuid import uuid4

import frappe
from frappe.utils import add_to_date, now_datetime

from asoud_erp.api.v1 import forms, workflow, workflow_runtime, workflow_templates
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase, _user
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import EMPLOYEE_B_USER, setup_tenancy
from asoud_erp.services import workflow_user_action


class TestWorkflowUserActions(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()
        cls.account = _user('asoud.action-manager@example.com', ['System Manager'])
        frappe.db.commit()

    def make_action(self, rule=None, **settings):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(item for item in stages.values() if item.stage_type == 'User Task')
        config = {'title': 'اقدام کاربر', 'activity_type': 'Data Entry', 'task_purpose': 'Existing',
            'assignment_type': 'Initiator', 'action_contract_version': 1, 'result_mode': 'Simple',
            'allow_draft': True, 'allow_add_attachments': False,
            'assignment_rule': rule or {'basis': 'Subject', 'subject': 'Initiator'}, **settings}
        workflow.save_stage_settings(definition, stage.name, config)
        workflow.save_start_settings(definition, 'Manual', ['Employee', 'System Manager'], 'General Subject',
            settings={'trigger_type': 'Manual', 'initiator_roles': ['Employee', 'System Manager']})
        return definition, stage.name

    def start(self, definition, user=EMPLOYEE_USER):
        frappe.set_user(user)
        instance = workflow_runtime.start_workflow_instance(definition, 'بررسی اقدام', reason='آزمون')['data']['name']
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance, 'assigned_to': user}, 'name')
        return instance, task

    def test_follow_up_and_blocked_preserve_open_then_complete_once(self):
        definition, _ = self.make_action()
        instance, task = self.start(definition)
        workflow_runtime.save_workflow_task_draft(task, {'action_note': 'اطلاعات نیمه‌تمام'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Running')
        for action, result in [('Follow Up', 'follow_up'), ('Blocked', 'blocked')]:
            with self.assertRaises(frappe.ValidationError):
                workflow_runtime.complete_workflow_task(task, action, response={'action_result': result})
            workflow_runtime.complete_workflow_task(task, action,
                response={'action_result': result, 'action_note': 'شرح علت'})
            detail = workflow_runtime.get_workflow_task(task)['data']
            self.assertEqual(detail['status'], 'Open')
            self.assertEqual(detail['action'], action)
            self.assertEqual(detail['action_values']['action_note'], 'شرح علت')
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Running')
        workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_result': 'done'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_result': 'done'})
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_task': task, 'action': 'Complete'}), 1)

    def test_report_requires_note_and_draft_never_advances(self):
        definition, _ = self.make_action(simple_result_style='Report', allow_original_access=False)
        instance, task = self.start(definition)
        detail = workflow_runtime.get_workflow_task(task)['data']
        self.assertFalse(detail['allow_original_access'])
        self.assertEqual(detail['request_values'], {})
        self.assertFalse(detail['submitted_form'])
        self.assertEqual([field['key'] for field in detail['action_schema']['sections'][0]['fields']], ['action_note'])
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(task, 'Complete', response={})
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(task, 'Follow Up', response={'action_note': 'گزارش'})
        workflow_runtime.save_workflow_task_draft(task, {'action_note': 'نیمه‌تمام'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Running')
        workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_note': 'بررسی انجام شد.'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')

    def test_manual_reassignment_transfers_same_claimed_task_and_preserves_draft(self):
        role = frappe.get_doc({'doctype': 'Role', 'role_name': f'Transfer {uuid4().hex[:10]}'}).insert().name
        for user in (EMPLOYEE_USER, APPROVER_USER):
            frappe.get_doc('User', user).add_roles(role)
        definition, _ = self.make_action({'basis': 'Role', 'role': role},
            simple_result_style='Report', allow_reassign=True)
        instance, task = self.start(definition)
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.get_workflow_task(task, candidate_query='')
        workflow_runtime.complete_workflow_task(task, 'Claim')
        workflow_runtime.save_workflow_task_draft(task, {'action_note': 'اطلاعات محفوظ'})
        before = frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance})
        options = workflow_runtime.get_workflow_task(task, candidate_query='')['data']
        self.assertEqual([row['user'] for row in options['reassignment_candidates']], [APPROVER_USER])
        for user in (EMPLOYEE_USER, EMPLOYEE_B_USER, 'missing@example.com'):
            with self.assertRaises(frappe.PermissionError):
                workflow_runtime.complete_workflow_task(task, 'Reassign', assignee=user)
        result = workflow_runtime.complete_workflow_task(task, 'Reassign', assignee=APPROVER_USER)['data']
        self.assertTrue(result['reassigned'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance}), before)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Running')
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.save_workflow_task_draft(task, {'action_note': 'تغییر غیرمجاز'})
        frappe.set_user(APPROVER_USER)
        detail = workflow_runtime.get_workflow_task(task)['data']
        self.assertEqual(detail['action_values']['action_note'], 'اطلاعات محفوظ')
        self.assertEqual(detail['status'], 'Open')
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_task': task,
            'action': 'Reassigned', 'actor': EMPLOYEE_USER, 'reference_name': APPROVER_USER}), 1)
        workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_note': 'تکمیل توسط مسئول جدید'})

    def test_reassignment_disabled_even_when_call_is_forged(self):
        definition, _ = self.make_action()
        _, task = self.start(definition)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.get_workflow_task(task, candidate_query='')
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.complete_workflow_task(task, 'Reassign', assignee=APPROVER_USER)

    def test_shared_claim_cancels_peers_and_requires_only_one_completion(self):
        role = frappe.get_doc({'doctype': 'Role', 'role_name': f'Action {uuid4().hex[:10]}'}).insert().name
        for user in (EMPLOYEE_USER, APPROVER_USER):
            frappe.get_doc('User', user).add_roles(role)
        definition, stage = self.make_action({'basis': 'Role', 'role': role, 'scope': 'Company'})
        instance, task = self.start(definition)
        self.assertTrue(workflow_runtime.get_workflow_task(task)['data']['requires_claim'])
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_result': 'done'})
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.save_workflow_task_draft(task, {'action_note': 'پیش از دریافت'})
        workflow_runtime.complete_workflow_task(task, 'Claim')
        self.assertEqual(frappe.db.count('ASOUD Workflow Task', {'workflow_instance': instance, 'status': 'Open'}), 1)
        frappe.set_user(APPROVER_USER)
        peer = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance, 'assigned_to': APPROVER_USER}, 'name')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', peer, 'status'), 'Cancelled')
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(peer, 'Claim')
        frappe.set_user(EMPLOYEE_USER)
        workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_result': 'done'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')
        frappe.set_user('Administrator')
        original = frappe.get_doc('ASOUD Workflow Stage', stage)
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, stage, {**json.loads(original.config_json), 'allow_draft': False})
        before = workflow.get_workflow_design(definition)['data']
        copied = workflow_templates.create_from_template(self.company, definition,
            str(frappe.db.get_value('ASOUD Workflow Definition', definition, 'modified')), 'بازطراحی مستقل')['data']
        copied_graph = workflow.get_workflow_design(copied['name'])['data']
        self.assertTrue(all(item['configuration_status'] == 'Pending' for item in copied_graph['stages']))
        self.assertFalse(frappe.db.exists('ASOUD Workflow Instance', {'workflow_definition': copied['name']}))
        self.assertEqual(workflow.get_workflow_design(definition)['data'], before)

    def test_no_employee_account_and_permission_boundaries(self):
        definition, stage = self.make_action()
        instance, task = self.start(definition, self.account)
        self.assertFalse(frappe.db.exists('Employee', {'user_id': self.account}))
        for user in (EMPLOYEE_USER, EMPLOYEE_B_USER):
            frappe.set_user(user)
            with self.assertRaises(frappe.PermissionError):
                workflow_runtime.get_workflow_task(task)
            with self.assertRaises(frappe.PermissionError):
                workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_result': 'done'})
            with self.assertRaises(frappe.PermissionError):
                workflow.save_stage_settings(definition, stage, {})
        frappe.set_user(self.account)
        workflow_runtime.complete_workflow_task(task, 'Complete', response={'action_result': 'done'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')

    def test_existing_form_keeps_tables_and_recomputes_formula_without_entry(self):
        schema = {'kind': 'Request', 'title': 'نتیجه بررسی', 'sections': [{'id': 'main', 'title': 'اصلی', 'fields': [
            {'key': 'quantity', 'label': 'تعداد', 'type': 'Integer', 'required': True},
            {'key': 'price', 'label': 'قیمت', 'type': 'Money', 'required': True},
            {'key': 'total', 'label': 'جمع', 'type': 'Formula', 'formula': {'op': 'multiply', 'inputs': ['quantity', 'price']}},
            {'key': 'secret', 'label': 'اطلاعات محرمانه', 'type': 'Text', 'sensitive': True},
            {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'columns': [
                {'key': 'note', 'label': 'شرح', 'type': 'Text', 'required': True},
                {'key': 'private_note', 'label': 'شرح محرمانه', 'type': 'Text', 'sensitive': True}]},
        ]}]}
        saved = forms.save_form(self.company, schema, client_id=uuid4().hex)['data']
        published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
        definition, _ = self.make_action(result_mode='Form',
            result_form={'form': saved['name'], 'revision': published['active_revision']})
        instance, task = self.start(definition)
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(task, 'Complete', response='null')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')
        values = {'quantity': 2, 'price': 3, 'total': 999, 'secret': 'اطلاعات خصوصی',
            'rows': [{'note': 'ردیف واقعی', 'private_note': 'شرح خصوصی'}]}
        before = frappe.db.count('ASOUD Form Entry', {'form': saved['name']})
        workflow_runtime.complete_workflow_task(task, 'Complete', response=values)
        result = json.loads(frappe.db.get_value('ASOUD Workflow Task', task, 'response_json'))
        self.assertEqual(float(result['total']), 6)
        self.assertEqual(result['rows'], values['rows'])
        self.assertEqual(frappe.db.count('ASOUD Form Entry', {'form': saved['name']}), before)
        context = workflow_runtime._action_context(frappe.get_doc('ASOUD Workflow Instance', instance))
        self.assertEqual(context['request']['secret'], 'محرمانه')
        self.assertEqual(context['request']['rows'][0]['private_note'], 'محرمانه')
        self.assertEqual(result['secret'], 'اطلاعات خصوصی')

    def test_disabled_draft_and_attachment_settings_are_enforced_by_server(self):
        definition, _ = self.make_action(allow_draft=False)
        _, task = self.start(definition)
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.save_workflow_task_draft(task, {'action_result': 'done'})
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.upload_workflow_attachment(task, 'proof.pdf', 'cHJvb2Y=')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', task, 'status'), 'Open')

    def test_form_access_filters_queue_candidates_before_assignment(self):
        role = frappe.get_doc({'doctype': 'Role', 'role_name': f'Action {uuid4().hex[:10]}'}).insert().name
        for user in (EMPLOYEE_USER, APPROVER_USER):
            frappe.get_doc('User', user).add_roles(role)
        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم مسئول مجاز',
            'access': {'mode': 'roles', 'roles': ['Leave Approver']},
            'sections': [{'id': 'main', 'title': 'اصلی', 'fields': [{'key': 'note', 'label': 'شرح', 'type': 'Text'}]}]},
            client_id=uuid4().hex)['data']
        published = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']
        definition, _ = self.make_action({'basis': 'Role', 'role': role}, result_mode='Form',
            result_form={'form': saved['name'], 'revision': published['active_revision']})
        instance, _ = self.start(definition)
        candidates = frappe.get_all('ASOUD Workflow Task', filters={'workflow_instance': instance}, pluck='assigned_to')
        self.assertEqual(candidates, [APPROVER_USER])
        frappe.set_user(APPROVER_USER)
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance}, 'name')
        workflow_runtime.complete_workflow_task(task, 'Claim')
        workflow_runtime.complete_workflow_task(task, 'Complete', response={'note': 'ثبت مجاز'})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')

    def test_role_candidates_filtered_before_200_cap(self):
        role = frappe.get_doc({'doctype': 'Role', 'role_name': f'BulkRole {uuid4().hex[:10]}'}).insert().name
        frappe.get_doc('User', APPROVER_USER).add_roles(role)
        for i in range(210):
            email = f'bulk_{i}_{uuid4().hex[:6]}@example.com'
            if not frappe.db.exists('User', email):
                frappe.get_doc({
                    'doctype': 'User', 'email': email, 'first_name': f'Bulk {i}',
                    'enabled': 0, 'user_type': 'System User'
                }).insert(ignore_permissions=True)
            frappe.get_doc({
                'doctype': 'Has Role', 'parent': email, 'parenttype': 'User',
                'parentfield': 'roles', 'role': role
            }).insert(ignore_permissions=True)
        definition, _ = self.make_action({'basis': 'Role', 'role': role, 'scope': 'Company'})
        instance, _ = self.start(definition)
        assignees = frappe.get_all('ASOUD Workflow Task', filters={'workflow_instance': instance}, pluck='assigned_to')
        self.assertIn(APPROVER_USER, assignees)

    def test_escalation_notifies_and_sorts_deterministically(self):
        esc_role = frappe.get_doc({'doctype': 'Role', 'role_name': f'EscRole {uuid4().hex[:10]}'}).insert().name
        for user in (APPROVER_USER, EMPLOYEE_USER):
            frappe.get_doc('User', user).add_roles(esc_role)
        definition, stage_name = self.make_action()
        stage_doc = frappe.get_doc('ASOUD Workflow Stage', stage_name)
        cfg = json.loads(stage_doc.config_json or '{}')
        cfg['escalation_roles'] = [esc_role]
        cfg['reassign_on_overdue'] = True
        stage_doc.config_json = json.dumps(cfg)
        stage_doc.save(ignore_permissions=True)

        instance, task = self.start(definition)
        # Deadlines run as the scheduler, not a recipient (_notify_user skips its actor).
        frappe.set_user('Administrator')
        workflow_user_action.escalate(task, now_datetime())
        updated_task = frappe.get_doc('ASOUD Workflow Task', task)
        self.assertEqual(updated_task.status, 'Open')
        self.assertIsNotNone(updated_task.escalated_on)
        self.assertEqual(updated_task.assigned_to, sorted([APPROVER_USER, EMPLOYEE_USER])[0])
        notifications = {'document_name': instance, 'subject': 'اقدام نیازمند ارجاع است'}
        self.assertEqual(set(frappe.get_all('Notification Log', filters=notifications,
            pluck='for_user')), {APPROVER_USER, EMPLOYEE_USER})
        workflow_user_action.escalate(task, now_datetime())
        self.assertEqual(frappe.db.count('Notification Log', notifications), 2)
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {
            'workflow_task': task, 'action': 'Escalated'}), 1)

    def test_process_workflow_deadlines_continues_on_error(self):
        definition, _ = self.make_action()
        _, first = self.start(definition)
        _, second = self.start(definition)
        tasks = {first, second}
        for task in tasks:
            frappe.db.set_value('ASOUD Workflow Task', task, {
                'due_on': add_to_date(now_datetime(), hours=-2), 'escalated_on': None})
        before = {task: frappe.db.get_value('ASOUD Workflow Task', task, 'draft_json') for task in tasks}
        visited = []
        original_escalate = workflow_user_action.escalate

        def bad_escalate(t_name, current):
            if t_name in tasks:
                visited.append(t_name)
                if len(visited) == 1:
                    # Prove per-item rollback as well as continuing to a good row.
                    frappe.db.set_value('ASOUD Workflow Task', t_name, 'draft_json', '{"partial": true}')
                    raise ValueError("Simulated failure")
            return original_escalate(t_name, current)

        frappe.set_user('Administrator')
        try:
            workflow_user_action.escalate = bad_escalate
            workflow_runtime.process_workflow_deadlines()
        finally:
            workflow_user_action.escalate = original_escalate
        self.assertEqual(set(visited), tasks)
        self.assertEqual(len(visited), 2)
        failed, succeeded = visited
        self.assertIsNone(frappe.db.get_value('ASOUD Workflow Task', failed, 'escalated_on'))
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Task', failed, 'draft_json'), before[failed])
        self.assertIsNotNone(frappe.db.get_value('ASOUD Workflow Task', succeeded, 'escalated_on'))

    def test_accounts_user_without_employee_record_is_returned(self):
        acct_user = _user(f'acct_{uuid4().hex[:6]}@example.com', ['Accounts User'])
        self.assertFalse(frappe.db.exists('Employee', {'user_id': acct_user}))
        role = frappe.get_doc({'doctype': 'Role', 'role_name': f'AcctRole {uuid4().hex[:10]}'}).insert().name
        frappe.get_doc('User', acct_user).add_roles(role)
        frappe.get_doc({
            'doctype': 'User Permission', 'user': acct_user, 'allow': 'Company',
            'for_value': self.company, 'apply_to_all_doctypes': 1
        }).insert(ignore_permissions=True)
        definition, _ = self.make_action({'basis': 'Role', 'role': role, 'scope': 'Company'})
        instance, _ = self.start(definition)
        assignees = frappe.get_all('ASOUD Workflow Task', filters={'workflow_instance': instance}, pluck='assigned_to')
        self.assertIn(acct_user, assignees)
