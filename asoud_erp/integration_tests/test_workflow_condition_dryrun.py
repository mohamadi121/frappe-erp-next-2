"""Real-site tests for the side-effect-free condition dry-run and the safe runtime comment.

Runs on an installed site (no database mocks). The dry-run endpoint is exercised over the
real API, and a real condition activation is checked to prove the Activity comment records
the chosen route without leaking the compared field value.
"""
import json

import frappe
from frappe.deferred_insert import save_to_db

from asoud_erp.api.v1 import forms, workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


class TestWorkflowConditionDryRun(APITestCase):
    def test_system_requester_unit_uses_the_workflow_company_during_real_execution(self):
        definition, gate, _ = self.graph()
        unit = frappe.db.get_value('Employee', {'user_id': EMPLOYEE_USER,
            'company': self.company, 'status': 'Active'}, 'department')
        if not unit:
            from uuid import uuid4

            unit = frappe.get_doc({'doctype': 'Department', 'company': self.company,
                'department_name': f'Condition unit {uuid4().hex[:8]}'}).insert().name
            employee = frappe.db.get_value('Employee', {'user_id': EMPLOYEE_USER,
                'company': self.company, 'status': 'Active'}, 'name')
            frappe.db.set_value('Employee', employee, 'department', unit)
        self.assertTrue(unit)
        workflow.save_start_settings(definition, 'Manual', ['Employee'], 'General Subject',
            settings={'trigger_type': 'Manual', 'initiator_roles': ['Employee']})
        workflow.save_stage_settings(definition, gate, {'title': 'واحد ثبت‌کننده',
            'condition_version': 2, 'combine': 'All', 'conditions': [{
                'id': 'unit', 'source_kind': 'System', 'source_stage': '', 'source_field': 'requester_unit',
                'field_type': 'Text', 'operator': 'Equals', 'value': unit}]})
        self.exits(definition, gate)
        workflow.set_workflow_status(definition, 'Active')
        frappe.set_user(EMPLOYEE_USER)
        instance = workflow_runtime.start_workflow_instance(definition, 'بررسی دفتر ثبت‌کننده', reason='آزمون')['data']['name']
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')
        frappe.set_user('Administrator')

    def test_real_previous_action_report_and_pinned_form_route_without_a_new_request(self):
        from uuid import uuid4

        for mode in ('Simple', 'Form'):
            frappe.set_user('Administrator')
            definition = workflow.create_workflow_draft('شرط نتیجه اقدام قبلی', 'HR',
                'ASOUD Workflow Request', company=self.company)['data']['name']
            workflow.save_start_settings(definition, 'Manual', ['Employee'], 'General Subject',
                settings={'trigger_type': 'Manual', 'initiator_roles': ['Employee']})
            start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
            workflow.add_workflow_stage(definition, 'User Task', start)
            task_stage = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'User Task'})
            workflow.add_workflow_stage(definition, 'Condition', task_stage)
            gate = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Condition'})
            action = {'title': 'اقدام قبلی', 'activity_type': 'Data Entry', 'task_purpose': 'Existing',
                'assignment_type': 'Initiator', 'assignment_rule': {'basis': 'Subject', 'subject': 'Initiator'},
                'action_contract_version': 1, 'result_mode': mode, 'simple_result_style': 'Report'}
            if mode == 'Form':
                saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم نتیجه اقدام',
                    'sections': [{'id': 'main', 'title': 'نتیجه', 'fields': [
                        {'key': 'checked', 'label': 'بررسی شد', 'type': 'Boolean'}]}]}, client_id=uuid4().hex)['data']
                forms.transition(saved['name'], 'publish', saved['draft_version'])
                form = forms.get_form(saved['name'])['data']
                action['result_form'] = {'form': form['name'], 'revision': form['revision']}
            workflow.save_stage_settings(definition, task_stage, action)
            key, kind, value = ('action_note', 'Text', 'تایید') if mode == 'Simple' else ('checked', 'Boolean', 'true')
            rule = {'id': 'prior', 'source_kind': 'Stage', 'source_stage': task_stage,
                'source_field': key, 'field_type': kind, 'operator': 'Contains' if mode == 'Simple' else 'Equals', 'value': value}
            workflow.save_stage_settings(definition, gate, {'title': 'بررسی اقدام', 'condition_version': 2,
                'combine': 'All', 'conditions': [rule]})
            self.exits(definition, gate)
            workflow.set_workflow_status(definition, 'Active')
            before = frappe.db.count('ASOUD Workflow Request')
            frappe.set_user(EMPLOYEE_USER)
            instance = workflow_runtime.start_workflow_instance(definition, 'آزمون خروجی اقدام', reason='آزمون')['data']['name']
            task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance, 'status': 'Open'}, 'name')
            workflow_runtime.complete_workflow_task(task, 'Complete', response={key: 'گزارش تایید شد' if mode == 'Simple' else True})
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance, 'status'), 'Completed')
            self.assertEqual(frappe.db.count('ASOUD Workflow Request'), before)
            self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_instance': instance,
                'workflow_stage': gate, 'action': 'Condition True'}), 1)
        frappe.set_user('Administrator')

    def typed_source(self):
        from uuid import uuid4

        definition, gate, _ = self.graph()
        fields = [
            {'key': 'note', 'label': 'متن', 'type': 'Text'},
            {'key': 'number', 'label': 'عدد', 'type': 'Decimal'},
            {'key': 'integer', 'label': 'عدد صحیح', 'type': 'Integer'},
            {'key': 'money', 'label': 'مبلغ', 'type': 'Money'},
            {'key': 'date', 'label': 'تاریخ', 'type': 'Date'},
            {'key': 'when', 'label': 'تاریخ و ساعت', 'type': 'DateTime'},
            {'key': 'clock', 'label': 'ساعت', 'type': 'Time'},
            {'key': 'choice', 'label': 'انتخاب', 'type': 'Select', 'options': [{'id': 'a', 'label': 'اول'}, {'id': 'b', 'label': 'دوم'}]},
            {'key': 'tags', 'label': 'چند انتخاب', 'type': 'MultiSelect', 'options': ['a', 'b']},
            {'key': 'flag', 'label': 'بله خیر', 'type': 'Boolean'},
            {'key': 'person', 'label': 'پرسنل', 'type': 'Link', 'source': 'Employee'},
            {'key': 'unit', 'label': 'واحد', 'type': 'Link', 'source': 'Department'},
        ]
        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم انواع شرط',
            'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields}]}, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        form = forms.get_form(saved['name'])['data']
        workflow.save_start_settings(definition, 'Document Event', [], 'Referenced Document', settings={
            'trigger_type': 'Document Event', 'initiator_roles': [],
            'submission_source': {'form': form['name'], 'revision': form['revision']}})
        return definition, gate

    def test_all_comparable_schema_types_use_real_metadata_and_the_same_evaluator(self):
        definition, gate = self.typed_source()
        catalog = workflow.workflow_condition_fields(definition, gate)['data']['condition_fields_v2']
        fields = {row['source_field']: row for row in catalog if row['source_kind'] == 'Original'}
        self.assertEqual(fields['choice']['options'], ['a', 'b'])
        self.assertEqual(fields['choice']['option_labels'], {'a': 'اول', 'b': 'دوم'})
        self.assertEqual(fields['person']['link_doctype'], 'Employee')
        tag_a, tag_b = fields['tags']['options']
        self.exits(definition, gate)
        transitions = frappe.get_all('ASOUD Workflow Transition', filters={'from_stage': gate},
            fields=['name', 'to_stage', 'condition_json'], order_by='name')
        cases = [
            ('note', 'Equals', 'متن', 'متن', True), ('note', 'Not Equals', 'متن', 'دیگر', True),
            ('note', 'Contains', 'متن', 'این متن است', True), ('note', 'Not Contains', 'متن', 'دیگر', True),
            ('note', 'Is Empty', None, '', True), ('note', 'Is Set', None, 'متن', True),
            ('number', 'Equals', '0', 0, True), ('number', 'Greater Than', '-2.5', '-1.5', True),
            ('number', 'Less Than', '2.5', '1.5', True), ('money', 'Equals', '0.100000000000000001', '0.100000000000000002', False),
            ('integer', 'Equals', '1', '1.5', None), ('date', 'Equals', '2026-11-19', '2026-11-19', True),
            ('date', 'Greater Than', '2026-11-18', '2026-11-19', True), ('date', 'Less Than', '2026-11-19', '2026-11-18', True),
            ('date', 'Equals', '2026-11-19', '2026-02-31', None),
            ('when', 'Greater Than', '2026-11-19T09:00:00', '2026-11-19T10:00:00', True),
            ('clock', 'Equals', '09:30:00', '09:30', True),
            ('choice', 'Equals', 'a', 'a', True), ('choice', 'Equals', 'a', 'b', False),
            ('choice', 'Equals', 'a', 'invalid', None), ('flag', 'Equals', 'false', False, True),
            ('flag', 'Equals', 'true', False, False), ('tags', 'Contains', tag_a, [tag_a, tag_b], True),
            ('tags', 'Contains', tag_a, [tag_b], False), ('tags', 'Contains', tag_a, ['invalid'], None),
        ]
        for key, operator, value, sample, expected in cases:
            with self.subTest(field=key, operator=operator, sample=sample):
                config = {'title': 'مقایسه', 'condition_version': 2, 'combine': 'All', 'conditions': [{
                    'id': 'test', 'source_kind': 'Original', 'source_stage': '', 'source_field': key,
                    'field_type': fields[key]['field_type'], 'operator': operator,
                    **({'value': value} if value is not None else {})}]}
                result = workflow.test_workflow_condition(definition, gate, config, {'test': sample})['data']
                self.assertIs(result['result'], expected)
                workflow.save_stage_settings(definition, gate, config)
                stored = workflow.get_workflow_design(definition)['data']
                rule = next(row['config']['conditions'][0] for row in stored['stages'] if row['name'] == gate)
                self.assertEqual(rule['source_field'], key)
                self.assertEqual(rule['field_type'], fields[key]['field_type'])
                self.assertEqual(rule['operator'], operator)
                self.assertEqual(frappe.get_all('ASOUD Workflow Transition', filters={'from_stage': gate},
                    fields=['name', 'to_stage', 'condition_json'], order_by='name'), transitions)
        config = {'title': 'ترکیب', 'condition_version': 2, 'combine': 'All', 'conditions': [
            {'id': 'n', 'source_kind': 'Original', 'source_stage': '', 'source_field': 'number',
             'field_type': 'Number', 'operator': 'Greater Than', 'value': '1'},
            {'id': 't', 'source_kind': 'Original', 'source_stage': '', 'source_field': 'note',
             'field_type': 'Text', 'operator': 'Contains', 'value': 'فوری'}]}
        for combine, expected in [('All', False), ('Any', True)]:
            config['combine'] = combine
            for reverse in (False, True):
                if reverse:
                    config['conditions'].reverse()
                result = workflow.test_workflow_condition(definition, gate, config, {'n': 2, 't': 'عادی'})['data']
                self.assertIs(result['result'], expected)
        people = workflow.workflow_condition_fields(definition, gate, 'person', query='')['data']['value_options']
        self.assertTrue(people)
        value = people[0]['value']
        config = {'title': 'شخص', 'condition_version': 2, 'combine': 'All', 'conditions': [{
            'id': 'person', 'source_kind': 'Original', 'source_stage': '', 'source_field': 'person',
            'field_type': 'Text', 'operator': 'Equals', 'value': value}]}
        workflow.save_stage_settings(definition, gate, config)
        selected = workflow.workflow_condition_fields(definition, gate)['data']['condition_fields_v2']
        selected = next(row for row in selected if row['source_kind'] == 'Original' and row['source_field'] == 'person')
        self.assertEqual(selected['option_labels'][value], people[0]['label'])
        self.assertTrue(workflow.test_workflow_condition(definition, gate, config, {'person': value})['data']['result'])
        config['conditions'][0]['value'] = 'missing-person'
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(definition, gate, config)

    def test_reported_jalali_range_uses_iso_and_distinguishes_error_from_false(self):
        definition, gate, _ = self.graph()
        settings = dict(title='بازه تاریخ', condition_version=2, combine='All', conditions=[
            dict(id='date', source_kind='System', source_stage='', source_field='started_on',
                field_type='Date', operator='Between', value='2026-11-18', value_to='2026-11-21')])
        before = {doctype: frappe.db.count(doctype) for doctype in (
            'ASOUD Workflow Request', 'ASOUD Form Entry', 'ASOUD Workflow Instance',
            'ASOUD Workflow Task', 'ASOUD Workflow Activity', 'Notification Log')}
        for sample, expected in [('2026-11-10', False), ('2026-11-19', True),
                ('2026-11-18', True), ('2026-11-21', True), ('invalid-date', None)]:
            result = workflow.test_workflow_condition(definition, gate, settings, {'date': sample})['data']
            self.assertIs(result['result'], expected)
            self.assertEqual(bool(result['rows'][0]['error']), expected is None)
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in before}, before)

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

    def test_dry_run_blank_text_sample_is_a_row_error_and_null_result(self):
        definition, gate, config = self.graph()
        out = workflow.test_workflow_condition(definition, gate, config, {'owner': ''})
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
