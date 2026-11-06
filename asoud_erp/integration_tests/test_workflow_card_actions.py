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
        # Frappe suppresses Versions in tests unless explicitly requested.
        versioned.save(ignore_version=False)
        self.assertTrue(frappe.db.exists('Version', {'ref_doctype': versioned.doctype, 'docname': versioned.name}))
        with self.assertRaises(frappe.ValidationError):
            delete(versioned.doctype, versioned.name)

    def test_delete_workflow_endpoint(self):
        name = self.draft()
        res = workflow.delete_workflow(name)
        self.assertTrue(res['data']['deleted'])
        self.assertFalse(frappe.db.exists('ASOUD Workflow Definition', name))

        name2 = self.draft()
        frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': name2,
            'subject': 'سابقهٔ اجرا', 'status': 'Running'}).insert()
        with self.assertRaises(frappe.ValidationError):
            workflow.delete_workflow(name2)

    def test_owned_stage_and_transition_versions_prevent_delete(self):
        for doctype, field, value in (
            ('ASOUD Workflow Stage', 'stage_title', 'عنوان دارای سابقه'),
            ('ASOUD Workflow Transition', 'transition_label', 'مسیر دارای سابقه'),
        ):
            with self.subTest(doctype=doctype):
                name = self.draft()
                self.complete(name)
                doc = frappe.get_doc(doctype, {'workflow_definition': name})
                doc.set(field, value)
                doc.save(ignore_version=False)
                versions = frappe.get_all('Version', filters={
                    'ref_doctype': doctype, 'docname': doc.name}, pluck='name')
                self.assertTrue(versions)
                graph = workflow.get_workflow_design(name)['data']
                with self.assertRaises(frappe.ValidationError):
                    workflow.delete_workflow(name)
                self.assertEqual(workflow.get_workflow_design(name)['data'], graph)
                self.assertTrue(all(frappe.db.exists('Version', version) for version in versions))

    def test_stage_update_lock_title_vs_config(self):
        name = self.draft()
        self.complete(name)
        stage_name = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': name, 'stage_type': 'User Task'}, 'name')
        # Legacy edits remain supported, but adoption of v1 must precede tasks.
        stage_doc = frappe.get_doc('ASOUD Workflow Stage', stage_name)
        stage_doc.config_json = json.dumps({'legacy_param': 1})
        stage_doc.save()
        instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': name,
            'subject': 'اجرا', 'status': 'Running'}).insert()
        task = frappe.get_doc({'doctype': 'ASOUD Workflow Task', 'workflow_instance': instance.name,
            'workflow_stage': stage_name, 'task_title': 'تکلیف', 'assigned_to': 'Administrator', 'status': 'Open'}).insert()
        stage_doc.config_json = json.dumps({'legacy_param': 2})
        stage_doc.save()
        self.assertEqual(json.loads(stage_doc.reload().config_json), {'legacy_param': 2})

        v1 = {'action_contract_version': 1,
            'assignment_rule': {'basis': 'Subject', 'subject': 'Initiator'}}
        # An existing task also blocks legacy -> v1 conversion.
        stage_doc.config_json = json.dumps(v1)
        with self.assertRaises(frappe.ValidationError):
            stage_doc.save()

        # A separate, valid v1 stage is configured before any task refers to it.
        v1_name = self.draft()
        self.complete(v1_name)
        v1_stage = frappe.get_doc('ASOUD Workflow Stage',
            {'workflow_definition': v1_name, 'stage_type': 'User Task'})
        config = json.loads(v1_stage.config_json)
        v1_stage.config_json = json.dumps({**config, **v1})
        v1_stage.save()
        v1_instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': v1_name,
            'subject': 'اجرای نسخه یک', 'status': 'Running'}).insert()
        frappe.get_doc({'doctype': 'ASOUD Workflow Task', 'workflow_instance': v1_instance.name,
            'workflow_stage': v1_stage.name, 'task_title': 'تکلیف', 'assigned_to': 'Administrator',
            'status': 'Open'}).insert()
        original_config = json.loads(v1_stage.config_json)
        v1_stage.stage_title = 'عنوان جدید v1'
        v1_stage.save()
        self.assertEqual(v1_stage.reload().stage_title, 'عنوان جدید v1')
        self.assertEqual(json.loads(v1_stage.config_json), original_config)

        for changes in ({'config_json': json.dumps({**original_config, 'allow_draft': False})},
                        {'stage_type': 'Approval'}, {'config_json': '{}'}):
            with self.subTest(changes=changes):
                v1_stage.reload()
                v1_stage.update(changes)
                with self.assertRaises(frappe.ValidationError) as ctx:
                    v1_stage.save()
                self.assertIn('1', str(ctx.exception))
                self.assertIn('کار', str(ctx.exception))
                v1_stage.reload()
                self.assertEqual(v1_stage.stage_type, 'User Task')
                self.assertEqual(json.loads(v1_stage.config_json), original_config)
        self.assertTrue(frappe.db.exists('ASOUD Workflow Task', task.name))
