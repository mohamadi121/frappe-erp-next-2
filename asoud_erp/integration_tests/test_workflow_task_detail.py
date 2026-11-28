"""Integration regressions for the task-detail history and document context.

The task-detail ``history`` is additive-equal to the instance history: a FULL viewer
sees every actor's rows with ``actor_name`` and the parsed change lines
(``before``/``after``/``labels``), while a MASKED previous assignee sees only their
own rows (PA-055 close-out) — another actor's comment or change lines are absent.
The ``document`` values carry the field's ``fieldtype`` where the field definition
is known (F3). Runs on a real site; no mocked DB.
"""

import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase, _employee, _user
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create

OTHER_ACTOR = "asoud.task-detail-other@example.com"
OTHER_NAME = "شرکت‌کنندهٔ دیگر"
OTHER_SECRET = "یادداشت محرمانهٔ شرکت‌کنندهٔ دیگر"


def _activity(instance, actor, action, comment="", change=None):
    frappe.get_doc({"doctype": "ASOUD Workflow Activity",
                    "workflow_instance": instance, "actor": actor, "action": action,
                    "comment": comment, "created_on": "2026-01-01 00:00:00",
                    "change_json": json.dumps(change, ensure_ascii=False) if change else None}
                   ).insert(ignore_permissions=True)


class TestWorkflowTaskDetailHistory(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("User", OTHER_ACTOR):
            frappe.get_doc({"doctype": "User", "email": OTHER_ACTOR, "first_name": OTHER_NAME,
                            "send_welcome_email": 0, "user_type": "System User",
                            "roles": [{"role": "Employee"}]}).insert(ignore_permissions=True)
        frappe.db.commit()

    def _make_action(self):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(item for item in stages.values() if item.stage_type == 'User Task')
        config = {'title': 'بررسی', 'activity_type': 'Data Entry', 'assignment_type': 'Initiator',
                  'action_contract_version': 1, 'result_mode': 'Simple', 'allow_draft': True,
                  'allow_add_attachments': False,
                  'assignment_rule': {'basis': 'Subject', 'subject': 'Initiator'}}
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Inactive')
        workflow.save_stage_settings(definition, stage.name, config)
        workflow.save_start_settings(definition, 'Manual', ['Employee', 'System Manager'], 'General Subject',
                                     settings={'trigger_type': 'Manual',
                                                'initiator_roles': ['Employee', 'System Manager']})
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'status', 'Active')
        return definition

    def test_full_viewer_sees_actor_names_and_change_lines(self):
        definition = self._make_action()
        frappe.set_user(EMPLOYEE_USER)
        instance = workflow_runtime.start_workflow_instance(definition, 'بررسی جزئیات وظیفه',
                                                            reason='آزمون')['data']['name']
        task = frappe.db.get_value('ASOUD Workflow Task',
                                   {'workflow_instance': instance, 'assigned_to': EMPLOYEE_USER}, 'name')
        self.assertTrue(task)
        # A second participant's activity row carries a comment and change lines.
        _activity(instance, OTHER_ACTOR, 'Follow Up', comment='نظر شرکت‌کنندهٔ دیگر',
                  change={"before": {}, "after": {"note": OTHER_SECRET}, "labels": {"note": "یادداشت"}})
        frappe.set_user(EMPLOYEE_USER)
        try:
            data = workflow_runtime.get_workflow_task(task)['data']
        finally:
            frappe.set_user('Administrator')
        by_actor = {row['actor']: row for row in data['history']}
        self.assertIn(OTHER_ACTOR, by_actor)
        # The readable actor name comes from the User table, not the raw email.
        self.assertEqual(by_actor[OTHER_ACTOR]['actor_name'], OTHER_NAME)
        self.assertEqual(by_actor[EMPLOYEE_USER]['actor_name'],
                         frappe.db.get_value('User', EMPLOYEE_USER, 'full_name'))
        # The change lines are parsed through the same helper the instance endpoint uses.
        self.assertEqual(by_actor[OTHER_ACTOR]['before'], {})
        self.assertEqual(by_actor[OTHER_ACTOR]['after'], {'note': OTHER_SECRET})
        self.assertEqual(by_actor[OTHER_ACTOR]['labels'], {'note': 'یادداشت'})
        # The raw column is not leaked; existing keys are unchanged.
        for row in data['history']:
            self.assertNotIn('change_json', row)
            for key in ('name', 'workflow_task', 'workflow_stage', 'actor', 'action', 'comment', 'created_on'):
                self.assertIn(key, row)

    def test_masked_viewer_does_not_get_another_actor_change_lines(self):
        fields = [{"key": "reason", "label": "دلیل", "type": "Long Text", "max_length": 2000}]
        definition, _ = make_definition(self.company, approvals=1, fields=fields)
        request = create(self.company, definition=definition, user=EMPLOYEE_USER,
                         values={'reason': 'دلیل آزمایشی'})['name']
        instance = frappe.db.get_value('ASOUD Workflow Request', request, 'workflow_instance')
        approver_task = frappe.db.get_value('ASOUD Workflow Task',
                                            {'workflow_instance': instance, 'assigned_to': APPROVER_USER}, 'name')
        self.assertTrue(approver_task)
        # A second participant's activity row carries a comment and change lines.
        _activity(instance, OTHER_ACTOR, 'Follow Up', comment='نظر شرکت‌کنندهٔ دیگر',
                  change={"before": {}, "after": {"note": OTHER_SECRET}, "labels": {"note": "یادداشت"}})
        # APPROVER_USER acts; their task is Completed -> MASKED.
        act(instance, 'Approve', comment='تأیید شد')
        frappe.set_user(APPROVER_USER)
        try:
            data = workflow_runtime.get_workflow_task(approver_task)['data']
        finally:
            frappe.set_user('Administrator')
        # The MASKED viewer sees only their own rows: the other actor's comment and
        # change lines are not part of their authorized history.
        self.assertEqual({row['actor'] for row in data['history']}, {APPROVER_USER})
        # default=str serializes the datetime columns (created_on); the Persian strings
        # being checked are plain strings and serialize unchanged, so the leak check holds.
        blob = json.dumps(data['history'], ensure_ascii=False, default=str)
        self.assertNotIn('نظر شرکت‌کنندهٔ دیگر', blob)
        self.assertNotIn(OTHER_SECRET, blob)
        # Their own row keeps the readable name.
        self.assertEqual(data['history'][-1]['actor_name'],
                         frappe.db.get_value('User', APPROVER_USER, 'full_name'))


class TestWorkflowTaskDetailDocumentFieldtype(APITestCase):
    def test_document_values_carry_the_fieldtype(self):
        # A native document with a non-hidden Attach field (scanned_cheque) and a Select
        # field (cheque_size). Cheque Print Template is controller-free and needs only
        # bank_name, so the fixture stays focused on the document-context contract.
        template = frappe.get_doc({"doctype": "Cheque Print Template",
                                   "bank_name": f"بانک آزمون {uuid4().hex[:8]}",
                                   "cheque_size": "Regular",
                                   "scanned_cheque": "/files/madrak.pdf"}).insert(ignore_permissions=True)
        token = uuid4().hex[:8]
        definition = frappe.get_doc({
            "doctype": "ASOUD Workflow Definition", "workflow_code": f"cpt-{token}",
            "workflow_title": f"بررسی چک {token}", "company": self.company,
            "module_key": "Finance", "target_doctype": "Cheque Print Template",
            "status": "Active", "readiness_status": "Ready", "creation_mode": "Custom",
            "allow_user_submission": 1,
        }).insert(ignore_permissions=True)
        stages = []
        for index, (kind, config) in enumerate([
            ("Start", {"title": "شروع", "trigger_type": "Manual",
                       "initiator_roles": ["Accounts User"]}),
            ("User Task", {"title": "بررسی", "activity_type": "Data Entry",
                           "assignment_type": "Initiator"}),
            ("End", {"title": "پایان", "outcome": "Completed"}),
        ]):
            stages.append(frappe.get_doc({
                "doctype": "ASOUD Workflow Stage", "workflow_definition": definition.name,
                "stage_key": f"{kind.lower().replace(' ', '-')}-{index}-{token}",
                "stage_title": config["title"], "stage_type": kind, "sequence_no": index + 1,
                "config_json": json.dumps(config), "configuration_status": "Complete"}).insert(ignore_permissions=True))
        for first, second in zip(stages, stages[1:]):
            frappe.get_doc({"doctype": "ASOUD Workflow Transition", "workflow_definition": definition.name,
                            "from_stage": first.name, "to_stage": second.name,
                            "condition_json": "{}"}).insert(ignore_permissions=True)
        # Accounts User: a start role, read on Cheque Print Template, and (via the active
        # Employee below) company access to self.company.
        viewer = _user(f"asoud.cpt-{uuid4().hex[:8]}@example.com", ["Accounts User"])
        _employee(viewer, "Cheque Viewer", company=self.company)
        frappe.set_user(viewer)
        try:
            instance = workflow_runtime.start_workflow_instance(
                definition.name, 'بررسی چک', reference_doctype='Cheque Print Template',
                reference_name=template.name, reason='آزمون')['data']['name']
        finally:
            frappe.set_user('Administrator')
        task = frappe.db.get_value('ASOUD Workflow Task',
                                   {'workflow_instance': instance, 'assigned_to': viewer}, 'name')
        self.assertTrue(task)
        frappe.set_user(viewer)
        try:
            data = workflow_runtime.get_workflow_task(task)['data']
        finally:
            frappe.set_user('Administrator')
        by_key = {item['key']: item for item in data['document']['values']}
        # The Attach field carries its fieldtype; values and read_only are unchanged.
        self.assertEqual(by_key['scanned_cheque']['value'], '/files/madrak.pdf')
        self.assertEqual(by_key['scanned_cheque']['fieldtype'], 'Attach')
        self.assertFalse(by_key['scanned_cheque']['read_only'])
        self.assertEqual(by_key['cheque_size']['fieldtype'], 'Select')
