"""Native regressions for the cartable access, idempotency, history and attachment
endpoints of ``workflow_runtime`` (PA-025, PA-028, PA-039, PA-044, PA-045).

These run on a real site (no mocked DB): the idempotent completion, the bounded
history read, the guest guard, the attachment content check and the previous-assignee
view access all execute against real rows and real permissions.
"""

import base64
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import buying, workflow, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    ITEM,
    SUPPLIER,
    APITestCase,
    _user,
    warehouse,
)
from asoud_erp.integration_tests.request_fixtures import make_definition


class TestWorkflowAccess(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = _user('asoud.access-manager@example.com', ['System Manager'])
        frappe.db.commit()

    def make_action(self, rule=None, **settings):
        definition, stages = make_definition(self.company, approvals=0, fields=[])
        stage = next(item for item in stages.values() if item.stage_type == 'User Task')
        config = {'title': 'اقدام کاربر', 'activity_type': 'Data Entry', 'task_purpose': 'Existing',
            'assignment_type': 'Initiator', 'action_contract_version': 1, 'result_mode': 'Simple',
            'allow_draft': True, 'allow_add_attachments': True,
            'assignment_rule': rule or {'basis': 'Subject', 'subject': 'Initiator'}, **settings}
        workflow.save_stage_settings(definition, stage.name, config)
        workflow.save_start_settings(definition, 'Manual', ['Employee', 'System Manager'], 'General Subject',
            settings={'trigger_type': 'Manual', 'initiator_roles': ['Employee', 'System Manager']})
        return definition, stage.name

    def start(self, definition, user=EMPLOYEE_USER):
        frappe.set_user(user)
        instance = workflow_runtime.start_workflow_instance(definition, 'بررسی دسترسی', reason='آزمون')['data']['name']
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance, 'assigned_to': user}, 'name')
        return instance, task

    # ------------------------------------------------------------------ PA-025
    def test_complete_is_idempotent_on_request_id_retry(self):
        definition, _ = self.make_action()
        instance, task = self.start(definition)
        request_id = 'req-' + uuid4().hex[:12]
        first = workflow_runtime.complete_workflow_task(
            task, 'Complete', response={'action_result': 'done'}, request_id=request_id)
        self.assertEqual(first['data']['task'], task)
        # A network retry re-sends the same request_id after the decision was applied.
        replay = workflow_runtime.complete_workflow_task(
            task, 'Complete', response={'action_result': 'done'}, request_id=request_id)
        self.assertEqual(replay['data']['task'], task)
        self.assertEqual(replay['data']['instance_status'], 'Completed')
        # A different request_id on an already-completed task is still rejected.
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.complete_workflow_task(
                task, 'Complete', response={'action_result': 'done'}, request_id='req-' + uuid4().hex[:12])
        # The completion activity carries the request_id so a retry can find it.
        self.assertEqual(frappe.db.count('ASOUD Workflow Activity', {
            'workflow_task': task, 'action': 'Complete'}), 1)

    # ------------------------------------------------------------------ PA-028
    def test_workflow_history_is_bounded_to_the_newest_rows(self):
        definition, _ = self.make_action()
        instance, task = self.start(definition)
        for i in range(205):
            frappe.get_doc({
                'doctype': 'ASOUD Workflow Activity', 'workflow_instance': instance,
                'workflow_task': task, 'actor': EMPLOYEE_USER, 'action': 'Note',
                'comment': f'ردیف {i}', 'created_on': f'2026-01-01 00:{i // 60:02d}:{i % 60:02d}',
            }).insert(ignore_permissions=True)
        rows = workflow_runtime._workflow_history(instance, ['name', 'comment', 'created_on'])
        # Bounded to the newest 200 rows, returned oldest-first for the timeline.
        self.assertEqual(len(rows), 200)
        self.assertEqual(rows[0]['comment'], 'ردیف 5')
        self.assertEqual(rows[-1]['comment'], 'ردیف 204')

    # ------------------------------------------------------------------ PA-039
    def test_cartable_lists_reject_a_guest(self):
        for call in (
            lambda: workflow_runtime.list_my_workflow_tasks(),
            lambda: workflow_runtime.list_my_workflow_instances(),
            lambda: workflow_runtime.list_my_workflow_notifications(),
        ):
            frappe.set_user('Guest')
            with self.assertRaises(frappe.PermissionError):
                call()
        # A signed-in user is not blocked by the guard.
        frappe.set_user(EMPLOYEE_USER)
        self.assertTrue(workflow_runtime.list_my_workflow_tasks()['ok'])

    # ------------------------------------------------------------------ PA-044
    def test_upload_rejects_content_that_spoofs_the_extension(self):
        definition, _ = self.make_action()
        _, task = self.start(definition)
        # A PNG payload named .pdf must be refused: the bytes are not a PDF.
        png = base64.b64encode(b'\x89PNG\r\n\x1a\n fake-png').decode()
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.upload_workflow_attachment(task, 'invoice.pdf', png)
        # A real PDF header is accepted.
        pdf = base64.b64encode(b'%PDF-1.7 body').decode()
        result = workflow_runtime.upload_workflow_attachment(task, 'invoice.pdf', pdf)
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['file_name'], 'invoice.pdf')
        # An unknown extension is still refused.
        with self.assertRaises(frappe.ValidationError):
            workflow_runtime.upload_workflow_attachment(task, 'malware.exe', base64.b64encode(b'MZ...').decode())

    # ------------------------------------------------------------------ PA-045
    def test_previous_assignee_keeps_view_access_after_reassign(self):
        role = frappe.get_doc({'doctype': 'Role', 'role_name': f'Access {uuid4().hex[:10]}'}).insert().name
        for user in (EMPLOYEE_USER, APPROVER_USER):
            frappe.get_doc('User', user).add_roles(role)
        definition, _ = self.make_action({'basis': 'Role', 'role': role},
            simple_result_style='Report', allow_reassign=True)
        # Start as EMPLOYEE_USER; both role holders get a shared-claim task.
        instance, _ = self.start(definition, EMPLOYEE_USER)
        approver_task = frappe.db.get_value('ASOUD Workflow Task',
            {'workflow_instance': instance, 'assigned_to': APPROVER_USER}, 'name')
        self.assertTrue(approver_task)
        # APPROVER_USER (not the starter) claims, then reassigns to EMPLOYEE_USER.
        frappe.set_user(APPROVER_USER)
        workflow_runtime.complete_workflow_task(approver_task, 'Claim')
        workflow_runtime.complete_workflow_task(approver_task, 'Reassign', assignee=EMPLOYEE_USER)
        # The reassign rewrote assigned_to, so APPROVER_USER has no open task.
        self.assertFalse(frappe.db.exists('ASOUD Workflow Task',
            {'workflow_instance': instance, 'assigned_to': APPROVER_USER, 'status': 'Open'}))
        # The previous assignee keeps read access through their activity history.
        self.assertTrue(workflow_runtime.get_workflow_instance(instance)['ok'])
        # An unrelated user with no task and no activity is still denied.
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.get_workflow_instance(instance)

    # ------------------------------------------------------------------ PA-046
    def test_task_attachment_on_standard_document_follows_native_read(self):
        # A submitted Purchase Order in the test company (Administrator bypasses roles).
        frappe.set_user('Administrator')
        order = buying.create_purchase_order(
            self.company, SUPPLIER,
            [{"item_code": ITEM, "qty": 5, "rate": 90, "warehouse": warehouse()}],
            schedule_date=self.future(), submit=1)["data"]
        po = order["name"]
        # A workflow definition on the Purchase Order with a single user task.
        token = uuid4().hex[:8]
        definition = frappe.get_doc({
            "doctype": "ASOUD Workflow Definition", "workflow_code": f"po-{token}",
            "workflow_title": f"بررسی سفارش {token}", "company": self.company,
            "module_key": "Purchase", "target_doctype": "Purchase Order",
            "status": "Active", "readiness_status": "Ready", "creation_mode": "Custom",
            "allow_user_submission": 1,
        }).insert(ignore_permissions=True)
        stages = []
        for index, (kind, config) in enumerate([
            ("Start", {"title": "شروع"}),
            ("User Task", {"title": "بررسی سفارش", "activity_type": "Data Entry",
                           "assignment_type": "Initiator", "allow_add_attachments": True}),
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
        # Start the workflow on the PO (Administrator can read it and start).
        instance = workflow_runtime.start_workflow_instance(
            definition.name, 'بررسی سفارش خرید', reference_doctype='Purchase Order',
            reference_name=po, reason='آزمون')['data']['name']
        task = frappe.db.get_value('ASOUD Workflow Task', {'workflow_instance': instance}, 'name')
        # The task is assigned to the starter (Administrator); move it to a PO reader.
        frappe.db.set_value('ASOUD Workflow Task', task, 'assigned_to', ACCOUNTANT_USER)
        frappe.set_user(ACCOUNTANT_USER)
        pdf = base64.b64encode(b'%PDF-1.7 body').decode()
        file_name = workflow_runtime.upload_workflow_attachment(task, 'order.pdf', pdf)['data']['name']
        file_doc = frappe.get_doc('File', file_name)
        # A user with native read on the PO can download the task attachment.
        frappe.set_user(ACCOUNTANT_USER)
        self.assertTrue(frappe.has_permission('File', 'read', file_doc))
        # A user without native read on the PO cannot.
        frappe.set_user(EMPLOYEE_USER)
        self.assertFalse(frappe.has_permission('File', 'read', file_doc))
