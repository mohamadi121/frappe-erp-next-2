"""Phase 3: a form-submission start fires once on the real final submit, is
idempotent on retry, records the submitted record's version, and a published
workflow's start method cannot be changed while an instance is running.

Runs on an installed site with real rows (no frappe.db mocks).
"""
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import forms, workflow
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition


def _schema():
    return {'kind': 'Request', 'title': 'فرم شروع فاز سه', 'sections': [
        {'id': 'main', 'title': 'اطلاعات', 'fields': [
            {'key': 'note', 'label': 'توضیح', 'type': 'Text', 'required': True}]}]}


class TestWorkflowStartPhase3(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _ = make_definition(self.company, approvals=0, fields=[])
        saved = forms.save_form(self.company, _schema(), client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        self.source = forms.get_form(saved['name'])['data']
        workflow.save_start_settings(
            self.definition, 'Document Event', [], 'Referenced Document',
            settings={'trigger_type': 'Document Event',
                      'submission_source': {'form': self.source['name'], 'revision': self.source['revision']}})

    def _submit(self, key):
        frappe.set_user(EMPLOYEE_USER)
        return forms.submit_form(self.source['name'], self.source['revision'], 'درخواست فاز سه',
                                 {'note': 'متن اصلی'}, key)['data']

    def test_draft_does_not_start_and_final_submit_starts_once(self):
        # Opening/saving the form (draft) creates no instance.
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance',
                                         {'workflow_definition': self.definition}), 0)
        result = self._submit(uuid4().hex)
        self.assertTrue(result['workflow_instance'])
        instances = frappe.get_all('ASOUD Workflow Instance',
                                   {'workflow_definition': self.definition}, pluck='name')
        self.assertEqual(len(instances), 1)
        instance = frappe.get_doc('ASOUD Workflow Instance', instances[0])
        self.assertEqual(instance.reference_doctype, 'ASOUD Form Entry')
        self.assertEqual(instance.reference_name, result['name'])

    def test_retry_of_the_same_submit_does_not_create_a_second_instance(self):
        key = uuid4().hex
        first = self._submit(key)
        # A retry / second tab with the same request key returns the same entry.
        second = self._submit(key)
        self.assertEqual(second['name'], first['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance',
                                         {'reference_doctype': 'ASOUD Form Entry',
                                          'reference_name': first['name']}), 1)

    def test_start_event_records_request_id_and_record_version(self):
        result = self._submit(uuid4().hex)
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        activity = frappe.get_doc('ASOUD Workflow Activity',
                                  {'workflow_instance': instance.name, 'action': 'Workflow Started'})
        change = json.loads(activity.change_json or '{}')
        self.assertEqual(change.get('start_mode'), 'Document Event')
        self.assertEqual(activity.reference_doctype, 'ASOUD Form Entry')
        self.assertEqual(activity.reference_name, result['name'])
        # The start event is traceable to the exact version of the submitted record.
        entry_modified = frappe.db.get_value('ASOUD Form Entry', result['name'], 'modified')
        self.assertEqual(change.get('reference_modified'), entry_modified)

    def test_changing_start_method_of_a_running_workflow_is_refused(self):
        result = self._submit(uuid4().hex)
        self.assertTrue(result['workflow_instance'])
        # While an instance is running, the start method cannot be silently changed.
        with self.assertRaises(frappe.ValidationError):
            workflow.save_start_settings(
                self.definition, 'Manual', ['System Manager'], 'General Subject',
                settings={'trigger_type': 'Manual', 'initiator_roles': ['System Manager']})
        # The running instance is unaffected and still running.
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance',
                                             result['workflow_instance'], 'status'), 'Running')
