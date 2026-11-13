"""Real-site Wait persistence and scheduler regressions; no production records."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import frappe

from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create
from asoud_erp.services import workflow_wait as waits


class TestWorkflowWait(APITestCase):
    def setUp(self):
        super().setUp()
        # Bench intentionally disables scheduling for tests. Model an enabled
        # isolated site in this test process only; do not edit site_config.
        keys = ('disable_scheduler', 'pause_scheduler', 'maintenance_mode')
        previous = {key: frappe.conf.get(key) for key in keys}
        self.addCleanup(lambda: frappe.conf.update(previous))
        frappe.conf.update({key: False for key in keys})
        frappe.db.set_single_value('System Settings', 'enable_scheduler', 1)

    def setup_wait(self, config=None):
        definition, stages = make_definition(self.company, approvals=0, fields=[
            {'key': 'scheduled', 'label': 'تاریخ برنامه', 'type': 'Date'}])
        task = next(row for row in stages.values() if row.stage_type == 'User Task')
        edge = frappe.db.get_value('ASOUD Workflow Transition', {'from_stage': task.name})
        from asoud_erp.api.v1.workflow import insert_workflow_stage

        result = insert_workflow_stage(definition, edge, 'Wait')['data']
        stage = next(row['name'] for row in result['stages'] if row['stage_type'] == 'Wait')
        value = config or {'wait_version': 1, 'title': 'انتظار آزمایشی', 'wait_type': 'Duration',
            'wait_value': 2, 'wait_unit': 'Minute', 'past_policy': 'Continue'}
        frappe.db.set_value('ASOUD Workflow Stage', stage, {'config_json': json.dumps(value),
            'configuration_status': 'Complete'})
        return definition, stage

    def test_duration_wait_is_persistent_and_does_not_create_a_human_task(self):
        definition, stage = self.setup_wait()
        result = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.current_stage, stage)
        self.assertEqual(instance.status, 'Running')
        self.assertTrue(instance.wait_due_utc)
        self.assertEqual(json.loads(instance.wait_snapshot_json)['state'], 'Waiting')
        self.assertFalse(frappe.db.exists('ASOUD Workflow Task', {'workflow_instance': instance.name, 'status': 'Open'}))

    def enter(self, config=None, values=None):
        definition, stage = self.setup_wait(config)
        result = create(self.company, definition=definition, values=values)
        return definition, stage, result, frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])

    def resume_due(self, instance):
        due = datetime.fromisoformat(json.loads(instance.wait_snapshot_json)['due_utc'])
        with patch.object(waits, 'utc_now', return_value=due + timedelta(seconds=1)):
            waits.run(instance.name)
            waits.run(instance.name)
        instance.reload()

    def test_duration_continues_once_and_a_new_document_load_keeps_schedule(self):
        _, _, _, instance = self.enter()
        original = instance.wait_due_utc
        waits.run(instance.name)  # Too early.
        instance.reload()
        self.assertEqual(instance.wait_due_utc, original)
        self.resume_due(instance)
        self.assertEqual(instance.status, 'Completed')
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {'workflow_instance': instance.name,
            'action': 'Wait Completed'}), 1)
        self.assertEqual(json.loads(instance.wait_snapshot_json)['state'], 'Completed')
        self.assertIsNone(instance.wait_due_utc)

    def test_past_absolute_time_obeys_both_policies(self):
        for policy in ('Continue', 'Error'):
            _, _, _, instance = self.enter({'wait_version': 1, 'title': 'انتظار تاریخ گذشته', 'wait_type': 'Date',
                'wait_value': '2001-01-01T09:00:00', 'past_policy': policy})
            if policy == 'Continue':
                self.assertEqual(instance.status, 'Running')
                waits.run(instance.name)
                instance.reload()
                self.assertEqual(instance.status, 'Completed')
            else:
                self.assertEqual(instance.status, 'Failed')
                self.assertIn('گذشته', json.loads(instance.wait_snapshot_json)['error'])

    def test_cancelled_request_never_resumes(self):
        from asoud_erp.api.v1.workflow_request import cancel_request

        _, _, result, instance = self.enter()
        frappe.set_user(EMPLOYEE_USER)
        cancel_request(result['name'], 'لغو آزمایشی')
        frappe.set_user('Administrator')
        self.resume_due(instance)
        self.assertEqual(instance.status, 'Cancelled')
        self.assertEqual(json.loads(instance.wait_snapshot_json)['state'], 'Cancelled')
        self.assertFalse(frappe.db.exists('ASOUD Workflow Activity', {'workflow_instance': instance.name, 'action': 'Wait Completed'}))

    def test_form_date_changes_are_recalculated_or_kept_and_invalid_values_fail(self):
        initial = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
        updated = (datetime.now(timezone.utc).date() + timedelta(days=20)).isoformat()
        for policy in ('Keep', 'Recalculate'):
            config = {'wait_version': 1, 'title': 'انتظار تاریخ فرم', 'wait_type': 'FormDate',
                'date_source': {'source_kind': 'Original', 'source_stage': '', 'source_field': 'scheduled', 'field_type': 'Date'},
                'offset_direction': 'Before', 'offset_days': 1, 'clock': '09:00', 'date_change_policy': policy}
            _, _, result, instance = self.enter(config, {'scheduled': initial})
            self.assertEqual(instance.status, 'Running', instance.wait_snapshot_json)
            before = instance.wait_due_utc
            source = frappe.get_doc('ASOUD Workflow Request', result['name'])
            source.values_json = json.dumps({'scheduled': updated})
            source.save()
            waits.run(instance.name)
            instance.reload()
            self.assertEqual(instance.wait_due_utc == before, policy == 'Keep')
            source.values_json = '{}'
            source.save()
            waits.run(instance.name)
            instance.reload()
            self.assertEqual(instance.status, 'Failed' if policy == 'Recalculate' else 'Running')

    def test_configuration_edit_cannot_retarget_a_running_wait(self):
        from asoud_erp.api.v1.workflow_wait import save_wait_settings

        definition, stage, _, instance = self.enter()
        due = instance.wait_due_utc
        changed = {'wait_version': 1, 'title': 'تغییر نامعتبر', 'wait_type': 'Duration', 'wait_value': 3, 'wait_unit': 'Day'}
        with self.assertRaises(frappe.ValidationError):
            save_wait_settings(definition, stage, changed)
        instance.reload()
        self.assertEqual(instance.wait_due_utc, due)
        self.resume_due(instance)
        self.assertEqual(instance.status, 'Completed')

    def test_multiple_instances_do_not_share_entry_times_or_receipts(self):
        definition, stage = self.setup_wait()
        first = create(self.company, definition=definition)
        second = create(self.company, definition=definition)
        a = frappe.get_doc('ASOUD Workflow Instance', first['workflow_instance'])
        b = frappe.get_doc('ASOUD Workflow Instance', second['workflow_instance'])
        self.resume_due(a)
        b.reload()
        self.assertEqual(a.status, 'Completed')
        self.assertEqual(b.status, 'Running')
        self.assertEqual(b.current_stage, stage)

    def test_absolute_future_time_does_not_resume_early(self):
        from zoneinfo import ZoneInfo

        definition, stage = self.setup_wait()
        tz, _ = waits.office_zone(definition)
        value = (datetime.now(ZoneInfo(tz)) + timedelta(days=1)).replace(tzinfo=None).isoformat(timespec='seconds')
        frappe.db.set_value('ASOUD Workflow Stage', stage, 'config_json', json.dumps({
            'wait_version': 1, 'wait_type': 'Date', 'wait_value': value, 'past_policy': 'Continue'}))
        result = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.status, 'Running', instance.wait_snapshot_json)
        waits.run(instance.name)
        instance.reload()
        self.assertEqual(instance.status, 'Running')
        self.resume_due(instance)
        self.assertEqual(instance.status, 'Completed')

    def test_previous_completed_action_date_is_read_by_stable_stage_id(self):
        definition, stage = self.setup_wait()
        task = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'User Task'})
        frappe.db.set_value('ASOUD Workflow Stage', stage, 'config_json', json.dumps({
            'wait_version': 1, 'wait_type': 'FormDate', 'date_source': {
                'source_kind': 'Stage', 'source_stage': task, 'source_field': 'scheduled', 'field_type': 'Date'},
            'clock': '09:00', 'offset_direction': 'After', 'offset_days': 1}))
        date = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        result = create(self.company, definition=definition, values={'scheduled': date})
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.status, 'Running', instance.wait_snapshot_json)
        self.assertEqual(json.loads(instance.wait_snapshot_json)['source_value'], date)
        self.resume_due(instance)
        self.assertEqual(instance.status, 'Completed')

    def test_deleted_date_field_blocks_recalculation_but_does_not_erase_history(self):
        config = {'wait_version': 1, 'title': 'انتظار وابسته', 'wait_type': 'FormDate', 'date_source': {
            'source_kind': 'Original', 'source_stage': '', 'source_field': 'scheduled', 'field_type': 'Date'},
            'clock': '09:00', 'offset_direction': 'Same', 'date_change_policy': 'Recalculate'}
        date = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
        definition, _, _, instance = self.enter(config, {'scheduled': date})
        saved = json.loads(instance.wait_snapshot_json)['scheduled_utc']
        task = frappe.get_doc('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'User Task'})
        previous = json.loads(task.config_json)
        previous['form_fields'] = []
        frappe.db.set_value('ASOUD Workflow Stage', task.name, 'config_json', json.dumps(previous))
        waits.run(instance.name)
        instance.reload()
        self.assertEqual(instance.status, 'Failed')
        snapshot = json.loads(instance.wait_snapshot_json)
        self.assertEqual(snapshot['scheduled_utc'], saved)
        self.assertIn('فیلد تاریخ مبدأ', snapshot['error'])

    def test_published_datetime_form_source_reuses_real_form_metadata_and_values(self):
        from uuid import uuid4

        from asoud_erp.api.v1 import forms, workflow, workflow_runtime

        definition, stage = self.setup_wait()
        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم تاریخ‌وساعت واقعی',
            'sections': [{'id': 'main', 'title': 'اطلاعات', 'fields': [
                {'key': 'when', 'label': 'تاریخ برنامه', 'type': 'DateTime'}]}]}, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        source = forms.get_form(saved['name'])['data']
        task = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'User Task'})
        workflow.save_stage_settings(definition, task, {'title': 'بررسی فرم', 'activity_type': 'Review',
            'assignment_type': 'Initiator', 'submission_source': {'form': source['name'], 'revision': source['revision']}})
        frappe.db.set_value('ASOUD Workflow Stage', stage, 'config_json', json.dumps({
            'wait_version': 1, 'wait_type': 'FormDate', 'date_source': {
                'source_kind': 'Original', 'source_stage': '', 'source_field': 'when', 'field_type': 'DateTime'},
            'offset_direction': 'Same', 'date_change_policy': 'Keep'}))
        date = (datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None).isoformat(timespec='seconds')
        frappe.set_user(EMPLOYEE_USER)
        result = forms.submit_form(source['name'], source['revision'], 'ثبت زمان واقعی', {'when': date}, uuid4().hex)['data']
        task_name = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': result['workflow_instance'], 'status': 'Open'})
        workflow_runtime.complete_workflow_task(task_name, 'Complete', response={})
        frappe.set_user('Administrator')
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.status, 'Running', instance.wait_snapshot_json)
        self.assertEqual(instance.reference_doctype, 'ASOUD Form Entry')
        self.resume_due(instance)
        self.assertEqual(instance.status, 'Completed')

    def test_disabled_scheduler_is_explained_without_saving_or_scheduling(self):
        from asoud_erp.api.v1.workflow_wait import get_wait_options, save_wait_settings

        definition, stage = self.setup_wait()
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        previous = frappe.conf.get('pause_scheduler')
        frappe.conf.pause_scheduler = True
        try:
            result = get_wait_options(definition, stage)['data']
            self.assertFalse(result['execution_ready'])
            self.assertIn('غیرفعال', result['blocked_message'])
            original = frappe.db.get_value('ASOUD Workflow Stage', stage, 'config_json')
            with self.assertRaises(frappe.ValidationError):
                save_wait_settings(definition, stage, {'wait_version': 1, 'title': 'انتظار جدید',
                    'wait_type': 'Duration', 'wait_value': 1, 'wait_unit': 'Minute'})
            self.assertEqual(frappe.db.get_value('ASOUD Workflow Stage', stage, 'config_json'), original)
            self.assertFalse(frappe.db.exists('ASOUD Workflow Instance', {'workflow_definition': definition}))
        finally:
            frappe.conf.pause_scheduler = previous
