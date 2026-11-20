"""Submitted records enter a real instance without copying their form or values."""
import hashlib
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import forms, workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import ACCOUNTANT_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import EMPLOYEE_B_USER, setup_tenancy
from asoud_erp.services.workflow_submission_source import sanitized


def schema():
    return {'kind': 'Request', 'title': 'فرم اتصال گردش‌کار', 'sections': [
        {'id': 'main', 'title': 'اطلاعات', 'fields': [
            {'key': 'note', 'label': 'توضیح', 'type': 'Text', 'required': True},
            {'key': 'secret', 'label': 'خصوصی', 'type': 'Text', 'sensitive': True},
            {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'columns': [
                {'key': 'title', 'label': 'عنوان', 'type': 'Text'},
                {'key': 'qty', 'label': 'تعداد', 'type': 'Integer'}]},
        ]}]}


class TestWorkflowSubmissionSource(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = setup_tenancy()['second']

    def setUp(self):
        super().setUp()
        self.definition, stages = make_definition(self.company, approvals=0, fields=[])
        workflow.save_start_settings(self.definition, 'Document Event', [], 'Referenced Document')
        self.stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        saved = forms.save_form(self.company, schema(), client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.source = forms.get_form(saved['name'])['data']
        self.config = {'title': 'بررسی ثبت اصلی', 'activity_type': 'Review',
            'assignment_type': 'Initiator', 'submission_source': {
                'form': self.source['name'], 'revision': self.source['revision']}}
        # Design edits require an Inactive workflow (PA-015); re-activate for the
        # submission tests that start instances.
        frappe.db.set_value('ASOUD Workflow Definition', self.definition, 'status', 'Inactive')
        workflow.save_stage_settings(self.definition, self.stage.name, self.config)
        frappe.db.set_value('ASOUD Workflow Definition', self.definition, 'status', 'Active')

    def test_submit_routes_original_entry_once_and_completion_creates_no_request(self):
        frappe.set_user(EMPLOYEE_USER)
        before = frappe.db.count('ASOUD Workflow Request')
        key = uuid4().hex
        values = {'note': 'اطلاعات اصلی', 'secret': 'خصوصی', 'rows': [{'title': 'ردیف', 'qty': 2}]}
        result = forms.submit_form(self.source['name'], self.source['revision'], 'درخواست آزمایشی', values, key)['data']
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.reference_doctype, 'ASOUD Form Entry')
        self.assertEqual(instance.reference_name, result['name'])
        self.assertEqual(forms.submit_form(self.source['name'], self.source['revision'],
            'درخواست آزمایشی', values, key)['data']['name'], result['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {
            'reference_doctype': 'ASOUD Form Entry', 'reference_name': result['name']}), 1)
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance.name}, 'name')
        detail = workflow_runtime.get_workflow_task(task)['data']
        # The snapshot exposes validated stored values, not the raw numeric input.
        stored = json.loads(frappe.db.get_value('ASOUD Form Entry', result['name'], 'values_json'))
        self.assertEqual(stored['rows'], [{'title': 'ردیف', 'qty': '2'}])
        self.assertEqual(detail['submitted_form']['values']['rows'], stored['rows'])
        self.assertNotIn('secret', detail['submitted_form']['values'])
        self.assertNotIn('secret', detail['request_values'])
        self.assertEqual(detail['config']['form_fields'], [])
        workflow_runtime.complete_workflow_task(task, 'Complete', response={})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance.name, 'status'), 'Completed')
        self.assertEqual(frappe.db.count('ASOUD Workflow Request'), before)
        self.assertEqual(json.loads(frappe.db.get_value('ASOUD Form Entry', result['name'], 'values_json'))['secret'], 'خصوصی')

    def test_published_revision_change_requires_explicit_rebinding(self):
        current = forms.get_form(self.source['name'], manage=1)['data']
        changed = schema()
        changed['title'] = 'نسخهٔ جدید'
        saved = forms.save_form(self.company, changed, self.source['name'], current['draft_version'])['data']
        forms.transition(self.source['name'], 'publish', saved['draft_version'])
        new = forms.get_form(self.source['name'])['data']
        before = frappe.db.count('ASOUD Form Entry')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            forms.submit_form(new['name'], new['revision'], 'ثبت نسخه جدید', {'note': 'اطلاعات'}, uuid4().hex)
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_inactive_route_rejects_valid_data_before_creating_an_entry(self):
        doc = frappe.get_doc('ASOUD Workflow Definition', self.definition)
        doc.status = 'Inactive'
        doc.save()
        before = frappe.db.count('ASOUD Form Entry')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            forms.submit_form(self.source['name'], self.source['revision'], 'درخواست معتبر',
                {'note': 'اطلاعات معتبر'}, uuid4().hex)
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_employee_cannot_bind_but_manager_can_share_source_without_changing_default(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.save_stage_settings(self.definition, self.stage.name, self.config)
        frappe.set_user('Administrator')
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        workflow.save_stage_settings(definition, stage.name, self.config)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', definition, 'source_form'), self.source['name'])
        stored = json.loads(frappe.db.get_value('ASOUD Workflow Stage', stage.name, 'config_json'))
        self.assertEqual(stored['source_route'], 'Available')
        from asoud_erp.services.workflow_submission_source import route

        self.assertEqual(route(frappe.get_doc('ASOUD Form', self.source['name']),
            frappe.get_doc('ASOUD Form Revision', self.source['revision'])), self.definition)

    def test_snapshot_filters_sensitive_columns_and_private_attachments(self):
        raw = {'sections': [{'fields': [{'key': 'rows', 'type': 'Table', 'columns': [
            {'key': 'public', 'type': 'Text'}, {'key': 'private', 'type': 'Text', 'sensitive': True}]},
            {'key': 'file', 'type': 'File'}]}]}
        _, values = sanitized(raw, {'rows': [{'public': 'مجاز', 'private': 'محرمانه'}], 'file': '/private/files/x'})
        self.assertEqual(values, {'rows': [{'public': 'مجاز'}]})

    def conditional_route(self):
        source = {'form': self.source['name'], 'revision': self.source['revision']}
        definition = workflow.create_workflow_draft('مسیر مشروط فرم مشترک', 'HR', 'ASOUD Workflow Request',
            company=self.company, start_settings={'trigger_type': 'Document Event', 'initiator_roles': [],
                'submission_source': source, 'source_route': 'Conditional'})['data']['name']
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'Condition', start)
        gate = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Condition'})
        workflow.save_stage_settings(definition, gate, {'title': 'بررسی نوع ارسال', 'condition_version': 2,
            'combine': 'All', 'conditions': [{'id': 'special', 'source_kind': 'Original', 'source_stage': '',
                'source_field': 'note', 'field_type': 'Text', 'operator': 'Equals', 'value': 'ویژه'}]})
        for result in (True, False):
            workflow.add_condition_branch(definition, gate, 'End', result)
        workflow.set_workflow_status(definition, 'Active')
        return definition

    def test_shared_form_uses_one_primary_route_and_retry_never_duplicates(self):
        conditional = self.conditional_route()
        frappe.set_user(EMPLOYEE_USER)
        key = uuid4().hex
        special = forms.submit_form(self.source['name'], self.source['revision'], 'ارسال ویژه', {'note': 'ویژه'}, key)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', special['workflow_instance'], 'workflow_definition'), conditional)
        replay = forms.submit_form(self.source['name'], self.source['revision'], 'ارسال ویژه', {'note': 'ویژه'}, key)['data']
        self.assertEqual(replay['name'], special['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {'reference_doctype': 'ASOUD Form Entry',
            'reference_name': special['name']}), 1)
        ordinary = forms.submit_form(self.source['name'], self.source['revision'], 'ارسال عادی', {'note': 'عادی'}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', ordinary['workflow_instance'], 'workflow_definition'), self.definition)

    def publish_mode(self, mode, selected=None):
        """Only fresh test records; production presets are never changed."""
        current = forms.get_form(self.source['name'], manage=1)['data']
        changed = schema()
        changed['workflow_mode'] = mode
        if selected is not None:
            changed['workflow'] = selected
        saved = forms.save_form(self.company, changed, self.source['name'], current['draft_version'])['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.source = forms.get_form(saved['name'])['data']
        self.config['submission_source']['revision'] = self.source['revision']
        if mode not in {'Fixed', 'Conditional'}:
            # Explicit legacy rebinding still follows the new design guard.
            frappe.db.set_value('ASOUD Workflow Definition', self.definition, 'status', 'Inactive')
            workflow.save_stage_settings(self.definition, self.stage.name, self.config)
            frappe.db.set_value('ASOUD Workflow Definition', self.definition, 'status', 'Active')

    def test_explicit_fixed_beats_matching_condition_and_uses_existing_inbox(self):
        self.publish_mode('Fixed', self.definition)
        other = self.conditional_route()
        # Even an unpublished draft with different intent cannot override it.
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft.update(workflow_mode='Conditional', workflow=other)
        forms.save_form(self.company, draft, current['name'], current['draft_version'])
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaisesRegex(frappe.ValidationError, 'فیلد ناشناخته'):
            forms.submit_form(self.source['name'], self.source['revision'], 'ورودی دستکاری شده',
                {'note': 'ویژه', 'workflow_mode': 'Conditional', 'workflow': other}, uuid4().hex)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'گردش انتخاب شده',
            {'note': 'ویژه'}, uuid4().hex)['data']
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.workflow_definition, self.definition)
        self.assertEqual(instance.reference_name, result['name'])
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance.name}, 'name')
        self.assertIn(task, [row['name'] for row in workflow_runtime.list_my_workflow_tasks()['data']])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {
            'reference_doctype': 'ASOUD Form Entry', 'reference_name': result['name']}), 1)

    def test_explicit_fixed_can_use_independent_legacy_definition(self):
        chosen, _ = make_definition(self.company, approvals=0, fields=[])
        self.publish_mode('Fixed', chosen)
        self.conditional_route()
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'گردش مستقل',
            {'note': 'ویژه'}, uuid4().hex)['data']
        entry = frappe.get_doc('ASOUD Form Entry', result['name'])
        request = frappe.get_doc('ASOUD Workflow Request', entry.reference_name)
        self.assertEqual(request.workflow_definition, chosen)
        self.assertEqual(result['workflow_instance'], request.workflow_instance)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', request.workflow_instance,
            'workflow_definition'), chosen)

    def test_explicit_conditional_ignores_retained_workflow_and_selects_match(self):
        self.publish_mode('Conditional', self.definition)
        chosen = self.conditional_route()
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'مسیر مشروط',
            {'note': 'ویژه'}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'],
            'workflow_definition'), chosen)

    def test_explicit_fixed_inactive_cannot_fall_back_to_matching_condition(self):
        self.publish_mode('Fixed', self.definition)
        self.conditional_route()
        workflow.set_workflow_status(self.definition, 'Inactive')
        before = {dt: frappe.db.count(dt) for dt in
            ('ASOUD Form Entry', 'ASOUD Workflow Instance', 'ASOUD Workflow Task')}
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaisesRegex(frappe.ValidationError, 'فعال و آماده نیست'):
            forms.submit_form(self.source['name'], self.source['revision'], 'انتخاب غیرفعال',
                {'note': 'ویژه'}, uuid4().hex)
        for dt, count in before.items():
            self.assertEqual(frappe.db.count(dt), count)

    def test_invalid_fixed_identifier_rejects_publish_without_replacing_revision(self):
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft.update(workflow_mode='Fixed', workflow='missing-selected-workflow')
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        with self.assertRaisesRegex(frappe.ValidationError, 'وجود ندارد'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.assertEqual(frappe.db.get_value('ASOUD Form', current['name'], 'active_revision'),
            self.source['revision'])

    def test_record_only_requires_approved_policy_not_an_inferred_exemption(self):
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft['workflow_mode'] = 'RecordOnly'
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        before = {dt: frappe.db.count(dt) for dt in
            ('ASOUD Form Entry', 'ASOUD Workflow Instance', 'ASOUD Workflow Task')}
        with self.assertRaisesRegex(frappe.ValidationError, 'سیاست معتبر'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        # Defence in depth for an imported published revision, without rewriting
        # any existing revision. This record is rolled back with the test.
        rev = forms.store(frappe.get_doc({'doctype': 'ASOUD Form Revision',
            'form': current['name'], 'version': 99, 'schema_json': json.dumps(draft)}))
        doc = frappe.get_doc('ASOUD Form', current['name'])
        doc.active_revision = rev.name
        forms.store(doc)
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaisesRegex(frappe.ValidationError, 'سیاست معتبر'):
            forms.submit_form(doc.name, rev.name, 'فقط ثبت نامجاز', {'note': 'ویژه'}, uuid4().hex)
        for dt, count in before.items():
            self.assertEqual(frappe.db.count(dt), count)

    def test_explicit_conditional_without_routes_does_not_create_bare_entry(self):
        draft = schema()
        draft['workflow_mode'] = 'Conditional'
        saved = forms.save_form(self.company, draft, client_id=uuid4().hex)['data']
        before = frappe.db.count('ASOUD Form Entry')
        with self.assertRaisesRegex(frappe.ValidationError, 'هیچ مسیر معتبر'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.assertFalse(frappe.db.get_value('ASOUD Form', saved['name'], 'active_revision'))
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_empty_explicit_mode_preserves_legacy_conditional_routing(self):
        self.publish_mode('')
        chosen = self.conditional_route()
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'فرم قدیمی خالی',
            {'note': 'ویژه'}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'],
            'workflow_definition'), chosen)

    def test_fixed_cannot_select_another_companys_definition(self):
        foreign, _ = make_definition(self.second, approvals=0, fields=[])
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft.update(workflow_mode='Fixed', workflow=foreign)
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        with self.assertRaisesRegex(frappe.ValidationError, 'همین دفتر'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])

    def test_picker_lists_bound_conditional_without_legacy_form_stage(self):
        chosen = self.conditional_route()
        options = forms.get_options(self.company, form=self.source['name'])['data']['workflows']
        self.assertIn(chosen, [row['name'] for row in options])
        self.assertEqual(next(row for row in options if row['name'] == chosen)['fields'], [])

    def test_fixed_foreign_source_rejected_by_picker_and_publish(self):
        other = forms.save_form(self.company, schema(), client_id=uuid4().hex)['data']
        forms.transition(other['name'], 'publish', other['draft_version'])
        current = forms.get_form(other['name'], manage=1)['data']
        draft = schema()
        draft.update(workflow_mode='Fixed', workflow=self.definition)
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        before = forms.get_form(current['name'])['data']['revision']
        count = frappe.db.count('ASOUD Form Revision', {'form': current['name']})
        with self.assertRaisesRegex(frappe.ValidationError, 'فرم مبدأ'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.assertEqual(forms.get_form(current['name'])['data']['revision'], before)
        self.assertEqual(frappe.db.count('ASOUD Form Revision', {'form': current['name']}), count)
        options = forms.get_options(self.company, form=current['name'])['data']['workflows']
        self.assertNotIn(self.definition, [row['name'] for row in options])
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', self.definition,
            'source_form'), self.source['name'])

    def test_conditional_publish_atomically_rebinds_ready_routes(self):
        chosen = self.conditional_route()
        old = self.source['revision']
        self.publish_mode('Conditional')
        for name in (self.definition, chosen):
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', name,
                'source_revision'), self.source['revision'])
            for stage in frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': name},
                    fields=['config_json']):
                source = json.loads(stage.config_json or '{}').get('submission_source')
                if source:
                    self.assertEqual(source['revision'], self.source['revision'])
        self.assertTrue(frappe.db.exists('ASOUD Form Revision', old))
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'اتصال نسخه جدید',
            {'note': 'ویژه'}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'],
            'workflow_definition'), chosen)

    def test_failed_conditional_rebind_preserves_operational_revision_and_all_bindings(self):
        chosen = self.conditional_route()
        old = self.source['revision']
        old_count = frappe.db.count('ASOUD Form Revision', {'form': self.source['name']})
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft.update(workflow_mode='Conditional')
        draft['sections'][0]['fields'][0]['key'] = 'renamed_note'
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        with self.assertRaises(frappe.ValidationError):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.assertEqual(forms.get_form(current['name'])['data']['revision'], old)
        self.assertEqual(frappe.db.count('ASOUD Form Revision', {'form': current['name']}), old_count)
        for name in (self.definition, chosen):
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', name, 'source_revision'), old)
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], old, 'نسخه قبلی سالم', {'note': 'ویژه'}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'],
            'workflow_definition'), chosen)

    def test_record_only_direct_start_guard_does_not_rewrite_existing_execution(self):
        frappe.set_user(EMPLOYEE_USER)
        running = forms.submit_form(self.source['name'], self.source['revision'], 'اجرای قبلی',
            {'note': 'معمولی'}, uuid4().hex)['data']['workflow_instance']
        frappe.set_user('Administrator')
        # Imported explicit revision: publication remains blocked by policy, but
        # the direct-start boundary must independently enforce this saved intent.
        draft = schema()
        draft['workflow_mode'] = 'RecordOnly'
        rev = forms.store(frappe.get_doc({'doctype': 'ASOUD Form Revision', 'form': self.source['name'],
            'version': 99, 'schema_json': json.dumps(draft)}))
        doc = frappe.get_doc('ASOUD Form', self.source['name'])
        doc.active_revision = rev.name
        forms.store(doc)
        # A historical existing instance must not short-circuit the policy check.
        entry = forms.store(frappe.get_doc({'doctype': 'ASOUD Form Entry', 'form': doc.name,
            'revision': rev.name, 'company': self.company, 'subject': 'فقط ثبت', 'values_json': '{}'}))
        # Use a separate unused workflow; existing source cannot be rebound while running.
        candidate, _ = make_definition(self.company, approvals=0, fields=[])
        source = frappe.get_doc('ASOUD Workflow Definition', candidate)
        source.source_form, source.source_revision = doc.name, rev.name
        source.flags.submission_source_service = True
        source.save()
        from asoud_erp.services.workflow_submission_source import assert_reference

        frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': candidate,
            'reference_doctype': 'ASOUD Form Entry', 'reference_name': entry.name,
            'subject': 'سابقه آزمون', 'status': 'Completed'}).insert(ignore_permissions=True)
        with self.assertRaisesRegex(frappe.ValidationError, 'فقط ثبت'):
            assert_reference(source, entry.name)
        with self.assertRaisesRegex(frappe.ValidationError, 'فقط ثبت'):
            workflow_runtime.start_workflow_instance(candidate, 'شروع مستقیم نامجاز', 'ASOUD Form Entry', entry.name)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', running, 'status'), 'Running')
        frappe.set_user(EMPLOYEE_USER)
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': running}, 'name')
        workflow_runtime.complete_workflow_task(task, 'Complete', response={})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', running, 'status'), 'Completed')

    def test_conditional_publish_cannot_rebind_a_running_workflow(self):
        other = self.conditional_route()
        old = self.source['revision']
        frappe.set_user(EMPLOYEE_USER)
        running = forms.submit_form(self.source['name'], old, 'اجرای در حال انجام',
            {'note': 'عادی'}, uuid4().hex)['data']['workflow_instance']
        frappe.set_user('Administrator')
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft['workflow_mode'] = 'Conditional'
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        with self.assertRaisesRegex(frappe.ValidationError, 'در حال اجرا'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.assertEqual(forms.get_form(current['name'])['data']['revision'], old)
        for name in (self.definition, other):
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', name, 'source_revision'), old)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', running, 'status'), 'Running')

    def test_fixed_manual_only_workflow_is_not_selectable_or_publishable(self):
        chosen, _ = make_definition(self.company, approvals=0, fields=[])
        workflow.save_start_settings(chosen, 'Manual', ['Employee'], 'General Subject',
            settings={'trigger_type': 'Manual', 'initiator_roles': ['Employee']})
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft.update(workflow_mode='Fixed', workflow=chosen)
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        with self.assertRaisesRegex(frappe.ValidationError, 'نحوهٔ شروع'):
            forms.transition(saved['name'], 'publish', saved['draft_version'])
        options = forms.get_options(self.company, form=current['name'])['data']['workflows']
        self.assertNotIn(chosen, [row['name'] for row in options])

    def test_publication_rebind_keeps_the_active_design_guard_outside_test_mode(self):
        current = forms.get_form(self.source['name'], manage=1)['data']
        draft = schema()
        draft['workflow_mode'] = 'Conditional'
        saved = forms.save_form(self.company, draft, current['name'], current['draft_version'])['data']
        old_flag = frappe.flags.in_test
        try:
            frappe.flags.in_test = False
            forms.transition(saved['name'], 'publish', saved['draft_version'])
            target = frappe.get_doc('ASOUD Workflow Stage', self.stage.name)
            target.stage_title = 'ویرایش طراحی غیرمجاز'
            with self.assertRaisesRegex(frappe.ValidationError, 'برای حفظ اجراها'):
                target.save()
        finally:
            frappe.flags.in_test = old_flag

    def test_overlapping_conditions_report_conflict_and_create_nothing(self):
        self.conditional_route()
        self.conditional_route()
        before = frappe.db.count('ASOUD Form Entry')
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            forms.submit_form(self.source['name'], self.source['revision'], 'ارسال مبهم', {'note': 'ویژه'}, uuid4().hex)
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before)

    def test_atomic_creation_rolls_back_on_invalid_start(self):
        before = frappe.db.count('ASOUD Workflow Definition')
        with self.assertRaises(frappe.ValidationError):
            workflow.create_workflow_draft('پیش‌نویس نامعتبر', 'HR', 'ASOUD Workflow Request', company=self.company,
                start_settings={'trigger_type': 'Document Event', 'submission_source':
                    {'form': self.source['name'], 'revision': 'missing-revision'}, 'initiator_roles': []})
        self.assertEqual(frappe.db.count('ASOUD Workflow Definition'), before)

    def test_other_company_cannot_claim_source_or_read_its_task(self):
        definition, stages = make_definition(self.second, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, stage.name, self.config)
        # Initiator assignment requires an ordinary user; Administrator is excluded.
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'درخواست اصلی',
            {'note': 'اطلاعات'}, uuid4().hex)['data']
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': result['workflow_instance']}, 'name')
        frappe.set_user(EMPLOYEE_B_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.get_workflow_task(task)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.start_workflow_instance(self.definition, 'تلاش نامجاز', 'ASOUD Form Entry', result['name'])

    def test_document_workflow_keeps_one_native_draft_and_original_entry_reference(self):
        from frappe.utils import nowdate

        from asoud_erp.integration_tests.fixtures import abbr

        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        document = {'kind': 'Document', 'title': 'سند حسابداری آزمایشی', 'target': 'Journal Entry',
            'sections': [{'id': 'main', 'title': 'سند', 'fields': [
                {'key': 'date', 'label': 'تاریخ', 'type': 'Date', 'native_key': 'posting_date'},
                {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'native_key': 'accounts', 'columns': [
                    {'key': 'account', 'label': 'حساب', 'type': 'Link', 'source': 'Account', 'native_key': 'account'},
                    {'key': 'debit', 'label': 'بدهکار', 'type': 'Money', 'native_key': 'debit_in_account_currency'},
                    {'key': 'credit', 'label': 'بستانکار', 'type': 'Money', 'native_key': 'credit_in_account_currency'}]}]}]}
        saved = forms.save_form(self.company, document, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        source = forms.get_form(saved['name'])['data']
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        workflow.save_stage_settings(definition, stage.name, {'title': 'بررسی سند',
            'activity_type': 'Review', 'assignment_type': 'Initiator',
            'submission_source': {'form': source['name'], 'revision': source['revision']}})
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Active')
        equity = frappe.get_all('Account', filters={'company': self.company, 'root_type': 'Equity',
            'is_group': 0}, pluck='name', limit_page_length=1)[0]
        before = frappe.db.count('Journal Entry')
        # The initiator must also have native Journal Entry create/read permissions.
        frappe.set_user(ACCOUNTANT_USER)
        result = forms.submit_form(source['name'], source['revision'], 'ثبت سند اصلی', {
            'date': nowdate(), 'rows': [{'account': f'Cash - {abbr()}', 'debit': 100, 'credit': 0},
                {'account': equity, 'debit': 0, 'credit': 100}]}, uuid4().hex)['data']
        self.assertEqual(result['reference_doctype'], 'Journal Entry')
        self.assertEqual(frappe.db.count('Journal Entry'), before + 1)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', result['workflow_instance'],
            'reference_name'), result['name'])
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': result['workflow_instance']}, 'name')
        detail = workflow_runtime.get_workflow_task(task)['data']
        self.assertEqual(len(detail['submitted_form']['values']['rows']), 2)
        workflow_runtime.complete_workflow_task(task, 'Complete', response={})
        self.assertEqual(frappe.db.count('Journal Entry'), before + 1)
        self.assertEqual(frappe.db.get_value('Journal Entry', result['reference_name'], 'docstatus'), 0)

    def test_document_conditional_route_and_default_fallback(self):
        from frappe.utils import nowdate

        from asoud_erp.integration_tests.fixtures import abbr

        frappe.set_user('Administrator')
        document = {'kind': 'Document', 'title': 'سند شرطی', 'target': 'Journal Entry',
            'sections': [{'id': 'main', 'title': 'سند', 'fields': [
                {'key': 'date', 'label': 'تاریخ', 'type': 'Date', 'native_key': 'posting_date'},
                {'key': 'remark', 'label': 'توضیح', 'type': 'Text', 'native_key': 'user_remark'},
                {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'native_key': 'accounts', 'columns': [
                    {'key': 'account', 'label': 'حساب', 'type': 'Link', 'source': 'Account', 'native_key': 'account'},
                    {'key': 'debit', 'label': 'بدهکار', 'type': 'Money', 'native_key': 'debit_in_account_currency'},
                    {'key': 'credit', 'label': 'بستانکار', 'type': 'Money', 'native_key': 'credit_in_account_currency'}]}]}]}
        saved = forms.save_form(self.company, document, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        source = forms.get_form(saved['name'])['data']
        source_ref = {'form': source['name'], 'revision': source['revision']}

        default_def, default_stages = make_definition(self.company, approvals=0, fields=[])
        default_stage = next(s for s in default_stages.values() if s.stage_type == 'User Task')
        frappe.db.set_value('ASOUD Workflow Definition', default_def, 'status', 'Inactive')
        workflow.save_stage_settings(default_def, default_stage.name, {'title': 'بررسی پیش‌فرض',
            'activity_type': 'Review', 'assignment_type': 'Initiator',
            'submission_source': source_ref, 'source_route': 'Default'})
        frappe.db.set_value('ASOUD Workflow Definition', default_def, 'status', 'Active')

        cond_def = workflow.create_workflow_draft('مسیر مشروط سند', 'HR', 'ASOUD Workflow Request',
            company=self.company, start_settings={'trigger_type': 'Document Event', 'initiator_roles': [],
                'submission_source': source_ref, 'source_route': 'Conditional'})['data']['name']
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': cond_def, 'stage_type': 'Start'})
        workflow.add_workflow_stage(cond_def, 'Condition', start)
        gate = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': cond_def, 'stage_type': 'Condition'})
        workflow.save_stage_settings(cond_def, gate, {'title': 'شرط سند', 'condition_version': 2,
            'combine': 'All', 'conditions': [{'id': 'c1', 'source_kind': 'Original', 'source_stage': '',
                'source_field': 'remark', 'field_type': 'Text', 'operator': 'Equals', 'value': 'ویژه'}]})
        for result in (True, False):
            workflow.add_condition_branch(cond_def, gate, 'End', result)
        workflow.set_workflow_status(cond_def, 'Active')

        equity = frappe.get_all('Account', filters={'company': self.company, 'root_type': 'Equity',
            'is_group': 0}, pluck='name', limit_page_length=1)[0]
        frappe.set_user(ACCOUNTANT_USER)

        res_special = forms.submit_form(source['name'], source['revision'], 'سند ویژه', {
            'date': nowdate(), 'remark': 'ویژه', 'rows': [{'account': f'Cash - {abbr()}', 'debit': 100, 'credit': 0},
                {'account': equity, 'debit': 0, 'credit': 100}]}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', res_special['workflow_instance'], 'workflow_definition'), cond_def)

        res_default = forms.submit_form(source['name'], source['revision'], 'سند عادی', {
            'date': nowdate(), 'remark': 'عادی', 'rows': [{'account': f'Cash - {abbr()}', 'debit': 100, 'credit': 0},
                {'account': equity, 'debit': 0, 'credit': 100}]}, uuid4().hex)['data']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', res_default['workflow_instance'], 'workflow_definition'), default_def)

    def test_only_available_workflow_without_default_saves_ordinary_entry(self):
        # PA-004: Available bindings never auto-route. With no conditional match
        # and no default, the form is saved as an ordinary record (no instance).
        frappe.set_user('Administrator')
        avail_def, avail_stages = make_definition(self.company, approvals=0, fields=[])
        avail_stage = next(s for s in avail_stages.values() if s.stage_type == 'User Task')
        frappe.db.set_value('ASOUD Workflow Definition', avail_def, 'status', 'Inactive')
        workflow.save_stage_settings(avail_def, avail_stage.name, {'title': 'بررسی موجود',
            'activity_type': 'Review', 'assignment_type': 'Initiator',
            'submission_source': {'form': self.source['name'], 'revision': self.source['revision']}, 'source_route': 'Available'})
        stored = json.loads(frappe.db.get_value('ASOUD Workflow Stage', avail_stage.name, 'config_json'))
        self.assertEqual(stored['source_route'], 'Available')
        frappe.db.set_value('ASOUD Workflow Definition', self.definition, 'status', 'Archived')

        before_entry = frappe.db.count('ASOUD Form Entry')
        before_instance = frappe.db.count('ASOUD Workflow Instance')
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(self.source['name'], self.source['revision'], 'ثبت بدون پیش‌فرض', {'note': 'تست'}, uuid4().hex)['data']
        self.assertTrue(result['name'])
        self.assertIsNone(result['workflow_instance'])
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before_entry + 1)
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance'), before_instance)

    def test_document_submission_idempotency_and_sha256_request_key(self):
        from frappe.utils import nowdate

        from asoud_erp.integration_tests.fixtures import abbr

        frappe.set_user('Administrator')
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(s for s in stages.values() if s.stage_type == 'User Task')
        document = {'kind': 'Document', 'title': 'سند حسابداری یکتایی', 'target': 'Journal Entry',
            'sections': [{'id': 'main', 'title': 'سند', 'fields': [
                {'key': 'date', 'label': 'تاریخ', 'type': 'Date', 'native_key': 'posting_date'},
                {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table', 'native_key': 'accounts', 'columns': [
                    {'key': 'account', 'label': 'حساب', 'type': 'Link', 'source': 'Account', 'native_key': 'account'},
                    {'key': 'debit', 'label': 'بدهکار', 'type': 'Money', 'native_key': 'debit_in_account_currency'},
                    {'key': 'credit', 'label': 'بستانکار', 'type': 'Money', 'native_key': 'credit_in_account_currency'}]}]}]}
        saved = forms.save_form(self.company, document, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        source = forms.get_form(saved['name'])['data']
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        workflow.save_stage_settings(definition, stage.name, {'title': 'بررسی سند یکتایی',
            'activity_type': 'Review', 'assignment_type': 'Initiator',
            'submission_source': {'form': source['name'], 'revision': source['revision']}})
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Active')

        equity = frappe.get_all('Account', filters={'company': self.company, 'root_type': 'Equity',
            'is_group': 0}, pluck='name', limit_page_length=1)[0]
        frappe.set_user(ACCOUNTANT_USER)

        key_1 = uuid4().hex
        key_2 = uuid4().hex
        payload_1 = {'date': nowdate(), 'rows': [{'account': f'Cash - {abbr()}', 'debit': 100, 'credit': 0},
            {'account': equity, 'debit': 0, 'credit': 100}]}
        payload_2 = {'date': nowdate(), 'rows': [{'account': f'Cash - {abbr()}', 'debit': 200, 'credit': 0},
            {'account': equity, 'debit': 0, 'credit': 200}]}

        res_1 = forms.submit_form(source['name'], source['revision'], 'سند اول', payload_1, key_1)['data']
        res_2 = forms.submit_form(source['name'], source['revision'], 'سند دوم', payload_2, key_2)['data']
        self.assertNotEqual(res_1['name'], res_2['name'])

        rk_1 = frappe.db.get_value('ASOUD Form Entry', res_1['name'], 'request_key')
        rk_2 = frappe.db.get_value('ASOUD Form Entry', res_2['name'], 'request_key')

        expected_1 = hashlib.sha256(f'{ACCOUNTANT_USER}:{self.company}:{key_1}'.encode()).hexdigest()
        expected_2 = hashlib.sha256(f'{ACCOUNTANT_USER}:{self.company}:{key_2}'.encode()).hexdigest()

        self.assertEqual(rk_1, expected_1)
        self.assertEqual(rk_2, expected_2)
        self.assertEqual(len(rk_1), 64)
        self.assertEqual(len(rk_2), 64)
        self.assertNotEqual(rk_1, rk_2)
        self.assertNotEqual(rk_1, 'accounts')
        self.assertNotEqual(rk_2, 'accounts')

        before_entries = frappe.db.count('ASOUD Form Entry')
        before_journals = frappe.db.count('Journal Entry')
        replay_1 = forms.submit_form(source['name'], source['revision'], 'سند اول', payload_1, key_1)['data']
        self.assertEqual(replay_1['name'], res_1['name'])
        self.assertEqual(frappe.db.count('ASOUD Form Entry'), before_entries)
        self.assertEqual(frappe.db.count('Journal Entry'), before_journals)

