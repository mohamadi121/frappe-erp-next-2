"""Real Start config, routing, authorization and runtime audit; no production calls."""
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import forms, workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase, _user
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


def configure(definition, settings):
    return workflow.save_start_settings(definition, settings['trigger_type'], settings.get('initiator_roles', []),
        'General Subject' if settings['trigger_type'] == 'Manual' else 'Referenced Document', settings=settings)['data']


class TestWorkflowStartSettings(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = setup_tenancy()['second']
        cls.initiator = _user('asoud.start-manager@example.com', ['System Manager'])
        frappe.db.commit()

    def test_selected_employee_role_can_start_only_within_its_company(self):
        definition, _ = make_definition(self.company, approvals=0, fields=[])
        configure(definition, {'trigger_type': 'Manual', 'initiator_roles': ['Employee']})
        frappe.set_user(EMPLOYEE_USER)
        result = workflow_runtime.start_workflow_instance(definition, 'بررسی روزانه', reason='آغاز توسط کاربر مجاز')['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['name'], 'started_by'), EMPLOYEE_USER)
        frappe.set_user('Administrator')
        other, _ = make_definition(self.second, approvals=0, fields=[])
        configure(other, {'trigger_type': 'Manual', 'initiator_roles': ['Employee']})
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.start_workflow_instance(other, 'بررسی دفتر دیگر', reason='علت')

    def test_manual_start_without_employee_requires_role_reason_and_records_actual_actor(self):
        definition, _ = make_definition(self.company, approvals=0, fields=[])
        saved = configure(definition, {'trigger_type': 'Manual', 'initiator_roles': ['System Manager']})
        self.assertEqual(saved['config']['start_settings_version'], 1)
        listed = workflow.list_workflows(company=self.company)['data']
        self.assertTrue(next(row for row in listed if row['name'] == definition)['can_start_manual'])
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.start_workflow_instance(definition, 'شروع امروز')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.start_workflow_instance(definition, 'شروع امروز', reason='بررسی')
        frappe.set_user(self.initiator)
        self.assertFalse(frappe.db.exists('Employee', {'user_id': self.initiator}))
        result = workflow_runtime.start_workflow_instance(definition, 'شروع امروز', reason='بررسی اطلاعات')['data']
        instance = frappe.get_doc('ASOUD Workflow Instance', result['name'])
        self.assertEqual(instance.started_by, self.initiator)
        activity = frappe.get_doc('ASOUD Workflow Activity', {'workflow_instance': instance.name, 'action': 'Workflow Started'})
        self.assertEqual(activity.comment, 'بررسی اطلاعات')
        self.assertEqual(activity.actor, self.initiator)
        with self.assertRaises(frappe.ValidationError):
            configure(definition, {'trigger_type': 'Manual', 'initiator_roles': ['System Manager'], 'allow_manager_restart': True})
        self.assertEqual(configure(definition, {'trigger_type': 'Manual',
            'initiator_roles': ['System Manager']})['name'], saved['name'])

    def test_form_binding_moves_only_source_metadata_and_replays_without_duplicate(self):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        task = next(stage for stage in stages.values() if stage.stage_type == 'User Task')
        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم آزمون شروع', 'sections': [
            {'id': 'main', 'title': 'اطلاعات', 'fields': [{'key': 'note', 'label': 'توضیح', 'type': 'Text'}]}]},
            client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        form = forms.get_form(saved['name'])['data']
        source = {'form': form['name'], 'revision': form['revision']}
        before = json.loads(task.config_json)
        workflow.save_stage_settings(definition, task.name, {**before, 'submission_source': source})
        start_id = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'}, 'name')
        configured = configure(definition, {'trigger_type': 'Document Event', 'submission_source': source,
            'allow_manager_restart': True})
        self.assertEqual(configured['name'], start_id)
        self.assertNotIn('submission_source', json.loads(frappe.db.get_value('ASOUD Workflow Stage', task.name, 'config_json')))
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.start_workflow_instance(definition, 'ارسال نامعتبر', reason='علت')
        frappe.set_user(self.initiator)
        entry = forms.submit_form(form['name'], form['revision'], 'درخواست اصلی', {'note': 'اطلاعات'}, uuid4().hex)['data']
        first = entry['workflow_instance']
        self.assertFalse(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        self.assertEqual(workflow_runtime.start_workflow_instance(definition, 'بازپخش', 'ASOUD Form Entry', entry['name'])['data']['name'], first)
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.start_workflow_instance(definition, 'تکرار', 'ASOUD Form Entry', entry['name'], reason='علت', restart=1)
        task_id = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': first}, 'name')
        workflow_runtime.complete_workflow_task(task_id, 'Complete', response={})
        self.assertTrue(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        second = workflow_runtime.start_workflow_instance(definition, 'بازبینی', 'ASOUD Form Entry', entry['name'],
            reason='بازبینی مدیریتی', restart=1)['data']['name']
        self.assertNotEqual(second, first)
        self.assertFalse(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', first, 'status'), 'Completed')
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_instance': second, 'action': 'Workflow Started'}), 1)

    def test_other_company_and_non_manager_cannot_change_start(self):
        definition, _ = make_definition(self.second, approvals=0, fields=[])
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            configure(definition, {'trigger_type': 'Manual', 'initiator_roles': ['System Manager']})
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            configure(definition, {'trigger_type': 'Manual', 'initiator_roles': ['Employee']})

    def test_manager_restart_by_different_user_and_rejections(self):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم تست مدیر', 'sections': [
            {'id': 'main', 'title': 'اطلاعات', 'fields': [{'key': 'note', 'label': 'توضیح', 'type': 'Text'}]}]},
            client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        form = forms.get_form(saved['name'])['data']
        source = {'form': form['name'], 'revision': form['revision']}
        configure(definition, {'trigger_type': 'Document Event', 'submission_source': source,
            'allow_manager_restart': True})

        # 1. Employee submits entry
        frappe.set_user(EMPLOYEE_USER)
        entry = forms.submit_form(form['name'], form['revision'], 'درخواست کارمند', {'note': 'متن'}, uuid4().hex)['data']
        first = entry['workflow_instance']

        # Complete task to close instance
        task_id = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': first}, 'name')
        assignee = frappe.db.get_value('ASOUD Workflow Task', task_id, 'assigned_to')
        frappe.set_user(assignee)
        workflow_runtime.complete_workflow_task(task_id, 'Complete', response={})

        # 2. Plain employee cannot restart
        frappe.set_user(EMPLOYEE_USER)
        self.assertFalse(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            workflow_runtime.start_workflow_instance(definition, 'شروع مجدد توسط کارمند', 'ASOUD Form Entry', entry['name'], reason='تست', restart=1)

        # 3. Manager of another company cannot restart (and can_restart is False)
        other_manager = _user('other.manager@example.com', ['System Manager'])
        frappe.set_user(other_manager)
        self.assertFalse(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError, frappe.DoesNotExistError)):
            workflow_runtime.start_workflow_instance(definition, 'شروع مجدد دفتر دیگر', 'ASOUD Form Entry', entry['name'], reason='تست', restart=1)

        # 4. When allow_manager_restart is false, manager cannot restart (and can_restart is False)
        frappe.set_user('Administrator')
        configure(definition, {'trigger_type': 'Document Event', 'submission_source': source,
            'allow_manager_restart': False})
        frappe.set_user(self.initiator)
        self.assertFalse(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            workflow_runtime.start_workflow_instance(definition, 'بدون اجازه مدیر', 'ASOUD Form Entry', entry['name'], reason='تست', restart=1)

        # 5. Allowed manager (self.initiator, allow_manager_restart=True, submitter != manager) can restart
        frappe.set_user('Administrator')
        configure(definition, {'trigger_type': 'Document Event', 'submission_source': source,
            'allow_manager_restart': True})
        frappe.set_user(self.initiator)
        self.assertTrue(workflow_runtime.get_workflow_instance(first)['data']['can_restart'])
        second = workflow_runtime.start_workflow_instance(definition, 'شروع مجدد توسط مدیر مجاز', 'ASOUD Form Entry', entry['name'],
            reason='بازبینی مدیریتی ثبت‌شده توسط غیر', restart=1)['data']['name']
        self.assertNotEqual(second, first)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', second, 'started_by'), self.initiator)
