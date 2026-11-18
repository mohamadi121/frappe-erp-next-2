"""PA-066: a stored «ویرایش محدود» (Limited Edit) survives an untouched app save, and
Limited Edit is no longer offered as a new choice. Real config_json is read from the DB
before and after each save; no mocks of frappe.db."""
import json

import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import APITestCase, _user
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import setup_tenancy

LIMITED_EDIT_MESSAGE = "ویرایش محدود دیگر قابل انتخاب نیست"


def _user_task_config(document_access):
    return {"title": "بررسی", "activity_type": "Data Entry", "assignment_type": "Initiator",
            "document_access": document_access}


class TestWorkflowDocumentAccess(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()
        cls.manager = _user('asoud.doc-access-manager@example.com', ['System Manager'])
        frappe.db.commit()

    def _definition_and_stage(self):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        # Design edits are only allowed on an inactive workflow with no running instance
        # (assert_editable); make_definition creates an Active one, so deactivate it first.
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        stage = next(item for item in stages.values() if item.stage_type == 'User Task')
        return definition, stage

    def _store(self, stage, document_access):
        # Simulate a record saved by an older app that already stored this value.
        frappe.db.set_value('ASOUD Workflow Stage', stage.name, 'config_json',
                            json.dumps(_user_task_config(document_access), ensure_ascii=False))

    def _stored_access(self, stage):
        return json.loads(frappe.db.get_value('ASOUD Workflow Stage', stage.name, 'config_json'))['document_access']

    def test_app_031_rewrite_of_stored_limited_edit_is_protected(self):
        definition, stage = self._definition_and_stage()
        self._store(stage, 'Limited Edit')
        # App 0.31.0 re-sends Edit for a stored Limited Edit without the change flag.
        result = workflow.save_stage_settings(definition, stage.name, _user_task_config('Edit'))
        self.assertEqual(self._stored_access(stage), 'Limited Edit')
        # The save is not a silent no-op: the response carries a Persian notice.
        self.assertIn('ویرایش محدود', result['meta']['notice'])
        self.assertIn('به‌روزرسانی', result['meta']['notice'])

    def test_stored_limited_edit_resent_is_kept(self):
        definition, stage = self._definition_and_stage()
        self._store(stage, 'Limited Edit')
        workflow.save_stage_settings(definition, stage.name, _user_task_config('Limited Edit'))
        self.assertEqual(self._stored_access(stage), 'Limited Edit')

    def test_read_only_from_031_is_applied_without_notice(self):
        # 0.31.0 offers Read Only / Edit. Picking Read Only for a stored Limited Edit is
        # unambiguous, so it is applied (no protection, no notice).
        definition, stage = self._definition_and_stage()
        self._store(stage, 'Limited Edit')
        result = workflow.save_stage_settings(definition, stage.name, _user_task_config('Read Only'))
        self.assertEqual(self._stored_access(stage), 'Read Only')
        self.assertNotIn('notice', result['meta'])

    def test_explicit_change_from_limited_edit_is_saved(self):
        definition, stage = self._definition_and_stage()
        self._store(stage, 'Limited Edit')
        result = workflow.save_stage_settings(definition, stage.name,
            {**_user_task_config('Edit'), 'document_access_changed': True})
        self.assertEqual(self._stored_access(stage), 'Edit')
        # A genuine explicit change is applied, not protected, so no notice.
        self.assertNotIn('notice', result['meta'])
        # The change flag itself is never stored in config_json.
        self.assertNotIn('document_access_changed', json.loads(
            frappe.db.get_value('ASOUD Workflow Stage', stage.name, 'config_json')))
        workflow.save_stage_settings(definition, stage.name,
            {**_user_task_config('Read Only'), 'document_access_changed': True})
        self.assertEqual(self._stored_access(stage), 'Read Only')

    def test_new_limited_edit_choice_is_rejected(self):
        definition, stage = self._definition_and_stage()
        self._store(stage, 'Read Only')
        with self.assertRaises(frappe.ValidationError) as ctx:
            workflow.save_stage_settings(definition, stage.name, _user_task_config('Limited Edit'))
        self.assertIn(LIMITED_EDIT_MESSAGE, str(ctx.exception))
        # The stored value is untouched by the rejected save.
        self.assertEqual(self._stored_access(stage), 'Read Only')

    def test_plain_edit_and_read_only_pass_through(self):
        definition, stage = self._definition_and_stage()
        self._store(stage, 'Read Only')
        workflow.save_stage_settings(definition, stage.name, _user_task_config('Edit'))
        self.assertEqual(self._stored_access(stage), 'Edit')
        workflow.save_stage_settings(definition, stage.name, _user_task_config('Read Only'))
        self.assertEqual(self._stored_access(stage), 'Read Only')

    def test_approval_stage_applies_the_same_rule(self):
        definition, stages = make_definition(self.company, approvals=1, fields=[])
        # Design edits are only allowed on an inactive workflow with no running instance.
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        approval = next(item for item in stages.values() if item.stage_type == 'Approval')
        stored = {"title": "تأیید", "assignment_type": "Direct Manager", "approval_mode": "Any",
                  "document_access": "Limited Edit"}
        frappe.db.set_value('ASOUD Workflow Stage', approval.name, 'config_json',
                            json.dumps(stored, ensure_ascii=False))
        # App 0.31.0 rewrite is protected on Approval stages too.
        workflow.save_stage_settings(definition, approval.name, {**stored, 'document_access': 'Edit'})
        self.assertEqual(json.loads(frappe.db.get_value('ASOUD Workflow Stage', approval.name, 'config_json'))['document_access'],
                         'Limited Edit')
        # A stored Limited Edit re-sent (even with the flag) is kept, not rejected.
        workflow.save_stage_settings(definition, approval.name, {**stored, 'document_access': 'Limited Edit',
            'document_access_changed': True})
        self.assertEqual(json.loads(frappe.db.get_value('ASOUD Workflow Stage', approval.name, 'config_json'))['document_access'],
                         'Limited Edit')
