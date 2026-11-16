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

    def test_deactivate_refused_while_instances_are_running(self):
        # PA-038: an Active definition with a Running instance cannot be
        # deactivated or archived until the running instance finishes.
        name = self.draft()
        self.complete(name)
        workflow.set_workflow_status(name, 'Active')
        instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': name,
            'subject': 'اجرای جاری', 'status': 'Running'}).insert()
        with self.assertRaises(frappe.ValidationError):
            workflow.set_workflow_status(name, 'Inactive')
        with self.assertRaises(frappe.ValidationError):
            workflow.set_workflow_status(name, 'Archived')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', name, 'status'), 'Active')
        # Once the instance finishes, deactivation is allowed again.
        frappe.db.set_value('ASOUD Workflow Instance', instance.name, 'status', 'Completed')
        self.assertEqual(workflow.set_workflow_status(name, 'Inactive')['data']['status'], 'Inactive')

    def test_active_or_running_workflow_refuses_graph_edits(self):
        # PA-006: adding a stage or drawing a route must be refused while the
        # definition is Active or has a Running instance, for every stage type.
        name = self.draft()
        self.complete(name)
        stages = workflow.get_workflow_design(name)['data']['stages']
        start = next(row['name'] for row in stages if row['stage_type'] == 'Start')
        task = next(row['name'] for row in stages if row['stage_type'] == 'User Task')
        end = next(row['name'] for row in stages if row['stage_type'] == 'End')
        # Active definition: both graph mutations are refused.
        workflow.set_workflow_status(name, 'Active')
        with self.assertRaises(frappe.ValidationError):
            workflow.add_workflow_stage(name, 'User Task', start)
        with self.assertRaises(frappe.ValidationError):
            workflow.connect_workflow_stages(name, task, end, 'تأیید')
        workflow.set_workflow_status(name, 'Inactive')
        # A Running instance on an Inactive definition blocks the same edits.
        frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': name,
            'subject': 'اجرای جاری', 'status': 'Running'}).insert()
        with self.assertRaises(frappe.ValidationError):
            workflow.add_workflow_stage(name, 'User Task', start)
        with self.assertRaises(frappe.ValidationError):
            workflow.connect_workflow_stages(name, task, end, 'تأیید')
        # The graph is untouched by the refused attempts.
        self.assertEqual(frappe.db.count('ASOUD Workflow Stage', {'workflow_definition': name}), 3)

    def test_incomplete_draft_is_listed_and_searchable_by_title_and_code(self):
        name = self.draft()
        doc = frappe.get_doc('ASOUD Workflow Definition', name)
        self.assertEqual(doc.status, 'Inactive')

        listed = workflow.list_workflows(company=self.company)['data']
        self.assertTrue(any(row['name'] == name for row in listed))
        self.assertTrue(any(row['name'] == name for row in
            workflow.list_workflows(company=self.company, search=doc.workflow_title)['data']))
        self.assertTrue(any(row['name'] == name for row in
            workflow.list_workflows(company=self.company, search=doc.workflow_code)['data']))

    def test_new_draft_start_stage_has_persian_title(self):
        # PA-056: the auto-created Start stage must carry the approved Persian
        # title, not the English "Start".
        name = self.draft()
        start = next(row for row in workflow.get_workflow_design(name)['data']['stages']
                     if row['stage_type'] == 'Start')
        self.assertEqual(start['stage_title'], 'شروع فرایند')

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

    def test_update_request_type_info_requires_company_scope(self):
        # PA-041: an Accounts Manager of another company must not edit the
        # presentation metadata of a foreign definition. The DocType has no
        # User Permission on Company, so without an explicit company guard the
        # global write role alone lets the cross-office edit through.
        name = workflow.create_workflow_draft(workflow_title='دفتر دیگر', company=self.foreign_company,
            module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        original_title = frappe.db.get_value('ASOUD Workflow Definition', name, 'workflow_title')
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.update_request_type_info(name, workflow_title='ویرایش بین‌دفتری')
        # The title was not changed.
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', name, 'workflow_title'), original_title)

    def test_update_stage_positions_requires_company_scope_and_write(self):
        # PA-014: a manager of another company must not move the canvas of a
        # foreign definition; the response must not leak the foreign design.
        name = workflow.create_workflow_draft(workflow_title='دفتر دیگر', company=self.foreign_company,
            module_key='HR', target_doctype='ASOUD Workflow Request')['data']['name']
        stage = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': name, 'stage_type': 'Start'}, 'name')
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.update_stage_positions(name, {stage: {'x': 10, 'y': 20}})
        # The coordinates were not written (still the default 0, not 10).
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Stage', stage, 'position_x'), 0)

    def test_json_dependency_blocks_but_edit_history_alone_does_not(self):
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
        # Issue #47: native deletion also permits edit history on unused graphs.
        delete(versioned.doctype, versioned.name)
        self.assertFalse(frappe.db.exists(versioned.doctype, versioned.name))
        self.assertFalse(frappe.db.exists('Version', {'ref_doctype': versioned.doctype, 'docname': versioned.name}))

    def test_delete_workflow_missing_or_invalid_name_is_persian(self):
        with self.assertRaisesRegex(frappe.ValidationError, 'شناسهٔ گردش‌کار معتبر نیست'):
            workflow.delete_workflow()
        for name in ('', ' ', [], {}, 'x' * 141):
            with self.subTest(name=name), self.assertRaisesRegex(
                    frappe.ValidationError, 'شناسهٔ گردش‌کار معتبر نیست'):
                workflow.delete_workflow(name)
        with self.assertRaisesRegex(frappe.ValidationError, 'گردش‌کار موردنظر یافت نشد'):
            workflow.delete_workflow('MISSING-' + frappe.generate_hash(length=20))

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

    def test_delete_workflow_writes_security_audit(self):
        # PA-042: deleting a workflow must leave an ASOUD Security Audit row in
        # the same savepoint, recording the actor, target and company.
        name = self.draft()
        code = frappe.db.get_value('ASOUD Workflow Definition', name, 'workflow_code')
        workflow.delete_workflow(name)
        self.assertFalse(frappe.db.exists('ASOUD Workflow Definition', name))
        audit = frappe.get_all('ASOUD Security Audit',
            filters={'action': 'workflow.definition.deleted', 'target': name},
            fields=['actor', 'company', 'target_type', 'details'], limit=1)
        self.assertTrue(audit, 'deletion must write a security audit row')
        self.assertEqual(audit[0]['actor'], 'Administrator')
        self.assertEqual(audit[0]['company'], self.company)
        self.assertEqual(audit[0]['target_type'], 'ASOUD Workflow Definition')
        self.assertIn(code, audit[0]['details'])

    def test_edited_unused_workflow_deletion_clears_versions(self):
        name = self.draft()
        self.complete(name)
        doc = frappe.get_doc('ASOUD Workflow Definition', name)
        doc.workflow_title = 'عنوان ویرایش‌شده بدون اجرا'
        doc.save(ignore_version=False)

        stages = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': name}, pluck='name')
        for s in stages:
            stage_doc = frappe.get_doc('ASOUD Workflow Stage', s)
            stage_doc.stage_title = 'مرحلهٔ ویرایش‌شده'
            stage_doc.save(ignore_version=False)

        transitions = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': name}, pluck='name')
        for t in transitions:
            tr_doc = frappe.get_doc('ASOUD Workflow Transition', t)
            tr_doc.transition_label = 'مسیر ویرایش‌شده'
            tr_doc.save(ignore_version=False)

        self.assertTrue(frappe.db.exists('Version', {'ref_doctype': 'ASOUD Workflow Definition', 'docname': name}))
        for s in stages:
            self.assertTrue(frappe.db.exists('Version', {'ref_doctype': 'ASOUD Workflow Stage', 'docname': s}))
        for t in transitions:
            self.assertTrue(frappe.db.exists('Version', {'ref_doctype': 'ASOUD Workflow Transition', 'docname': t}))

        res = workflow.delete_workflow(name)
        self.assertTrue(res['data']['deleted'])
        self.assertFalse(frappe.db.exists('ASOUD Workflow Definition', name))
        self.assertFalse(frappe.db.exists('ASOUD Workflow Stage', {'workflow_definition': name}))
        self.assertFalse(frappe.db.exists('ASOUD Workflow Transition', {'workflow_definition': name}))
        self.assertFalse(frappe.db.exists('Version', {'ref_doctype': 'ASOUD Workflow Definition', 'docname': name}))
        for s in stages:
            self.assertFalse(frappe.db.exists('Version', {'ref_doctype': 'ASOUD Workflow Stage', 'docname': s}))
        for t in transitions:
            self.assertFalse(frappe.db.exists('Version', {'ref_doctype': 'ASOUD Workflow Transition', 'docname': t}))

    def test_workflow_with_instance_refuses_deletion_and_preserves_all(self):
        name = self.draft()
        instance = frappe.get_doc({
            'doctype': 'ASOUD Workflow Instance',
            'workflow_definition': name,
            'subject': 'تست سابقهٔ اجرا',
            'status': 'Running'
        }).insert()

        with self.assertRaises(frappe.ValidationError):
            workflow.delete_workflow(name)

        self.assertTrue(frappe.db.exists('ASOUD Workflow Definition', name))
        self.assertTrue(frappe.db.exists('ASOUD Workflow Instance', instance.name))
        self.assertTrue(frappe.db.exists('ASOUD Workflow Stage', {'workflow_definition': name}))

    def test_native_stage_link_failure_restores_graph_and_versions(self):
        name, other = self.draft(), self.draft()
        self.complete(name)
        doc = frappe.get_doc('ASOUD Workflow Definition', name)
        doc.workflow_title = 'گردش دارای وابستگی خارجی'
        doc.save(ignore_version=False)
        graph = workflow.get_workflow_design(name)['data']
        versions = frappe.get_all('Version', filters={
            'ref_doctype': doc.doctype, 'docname': name}, pluck='name')
        self.assertTrue(versions)
        stage = graph['stages'][0]['name']
        # Legacy external reference accepted by the native schema. The native
        # link guard must fail after Version/transition cleanup has started.
        instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': other,
            'subject': 'وابستگی مرحله', 'status': 'Running', 'current_stage': stage}).insert()
        with self.assertRaises(frappe.ValidationError):
            workflow.delete_workflow(name)
        self.assertEqual(workflow.get_workflow_design(name)['data'], graph)
        self.assertTrue(all(frappe.db.exists('Version', version) for version in versions))
        self.assertEqual(frappe.db.get_value(instance.doctype, instance.name, 'current_stage'), stage)

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
