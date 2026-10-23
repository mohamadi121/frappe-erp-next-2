"""`get_request.viewer` is derived from the signed-in user's own open task."""

import base64

import frappe

from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    ITEM,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, create, open_task, valid_pdf_bytes


class TestRequestViewer(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل"})

    def _viewer(self, user):
        frappe.set_user(user)
        return workflow_request.get_request(self.request["name"])["data"]["viewer"]

    def test_the_owner_has_no_action_card(self):
        self.assertEqual(self._viewer(EMPLOYEE_USER), {"is_requester": True, "open_task": None})

    def test_the_assignee_gets_the_stage_flags_and_is_not_the_requester(self):
        viewer = self._viewer(APPROVER_USER)
        task = open_task(self.request["workflow_instance"], APPROVER_USER)
        self.assertFalse(viewer["is_requester"])
        self.assertEqual(viewer["open_task"], {
            "name": task.name, "stage_title": "تأیید 1", "stage_type": "Approval", "approve_action": "Approve",
            "allow_reject": True, "allow_return": True, "comment_required": False,
            "reject_comment_required": True, "has_form": False})

    def test_a_user_who_is_not_assigned_cannot_read_the_request_or_its_task(self):
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(self.request["name"])

    def test_the_card_disappears_after_the_decision(self):
        act(self.request["workflow_instance"], "Approve")
        self.assertEqual(self._viewer(APPROVER_USER), {"is_requester": False, "open_task": None})

    def test_a_returned_request_offers_the_requester_their_own_task(self):
        act(self.request["workflow_instance"], "Return", comment="اصلاح کنید")
        viewer = self._viewer(EMPLOYEE_USER)
        self.assertTrue(viewer["is_requester"])
        self.assertEqual(viewer["open_task"]["stage_type"], "User Task")
        self.assertEqual(viewer["open_task"]["approve_action"], "Complete")
        self.assertTrue(viewer["open_task"]["has_form"])

    def test_the_task_names_its_request_and_the_assignee_can_open_it(self):
        task = open_task(self.request["workflow_instance"], APPROVER_USER)
        frappe.set_user(APPROVER_USER)
        data = workflow_runtime.get_workflow_task(task.name)["data"]
        request_name = data["request_name"]
        self.assertEqual(data["request_company"], self.company)
        self.assertEqual(request_name, self.request["name"])
        self.assertEqual(workflow_request.get_request(request_name)["data"]["name"], self.request["name"])

    def test_reject_always_requires_a_reason_even_for_legacy_stage_setting(self):
        task = open_task(self.request["workflow_instance"], APPROVER_USER)
        stage = frappe.get_doc("ASOUD Workflow Stage", frappe.db.get_value(
            "ASOUD Workflow Task", task.name, "workflow_stage"))
        config = frappe.parse_json(stage.config_json)
        config["reject_comment_required"] = False
        stage.config_json = frappe.as_json(config)
        stage.save(ignore_permissions=True)
        frappe.set_user(APPROVER_USER)
        with self.assertRaisesRegex(frappe.ValidationError, "ثبت دلیل رد یا بازگشت الزامی است"):
            workflow_runtime.complete_workflow_task(task.name, "Reject")

    def test_request_owner_cannot_decide_their_own_approval_task(self):
        task = open_task(self.request["workflow_instance"], APPROVER_USER)
        frappe.db.set_value("ASOUD Workflow Task", task.name, "assigned_to", EMPLOYEE_USER)
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaisesRegex(frappe.PermissionError, "تأیید درخواست خودتان مجاز نیست"):
            workflow_runtime.complete_workflow_task(task.name, "Approve")

    def test_sensitive_value_is_masked_for_a_third_user_without_task_history(self):
        form_stage = frappe.get_doc("ASOUD Workflow Stage", workflow_request.form_stage_name(self.definition))
        config = frappe.parse_json(form_stage.config_json)
        next(field for field in config["form_fields"] if field["key"] == "reason")["sensitive"] = True
        form_stage.config_json = frappe.as_json(config)
        form_stage.save(ignore_permissions=True)
        frappe.set_user(ACCOUNTANT_USER)
        detail = workflow_request._detail(frappe.get_doc("ASOUD Workflow Request", self.request["name"]))
        self.assertEqual(detail["values"]["reason"], "محرمانه")


class TestSensitiveValues(APITestCase):
    def setUp(self):
        super().setUp()
        fields = [
            {"key": "reason", "label": "دلیل", "type": "Long Text", "max_length": 2000},
            {"key": "secret", "label": "شرح محرمانه", "type": "Long Text", "max_length": 2000, "sensitive": True},
            {"key": "proof", "label": "مدرک", "type": "Attachment", "sensitive": True},
            {"key": "items", "label": "اقلام", "type": "Item Table", "sensitive": True,
             "row_options": {"item_scope": "all", "note": True, "attachment": False, "min_rows": 0, "max_rows": 10}},
        ]
        self.definition, _stages = make_definition(self.company, approvals=1, fields=fields)
        upload = {"filename": "p.pdf", "content_base64": base64.b64encode(valid_pdf_bytes()).decode(), "ref": "a1"}
        self.request = create(
            self.company, definition=self.definition, attachments=[upload],
            values={"reason": "عادی", "secret": "رمز-۱۲۳", "proof": "attachment:a1",
                    "items": [{"item_code": ITEM, "qty": 1}]})

    def _detail_as(self, user):
        frappe.set_user(user)
        return workflow_request._detail(frappe.get_doc("ASOUD Workflow Request", self.request["name"]))

    def test_owner_and_task_holder_see_the_values_and_files(self):
        for user in (EMPLOYEE_USER, APPROVER_USER):
            detail = self._detail_as(user)
            self.assertEqual(detail["values"]["secret"], "رمز-۱۲۳")
            self.assertEqual(len(detail["attachments"]), 1)

    def test_past_task_holder_still_sees_the_values(self):
        act(self.request["workflow_instance"], "Approve")
        self.assertEqual(self._detail_as(APPROVER_USER)["values"]["secret"], "رمز-۱۲۳")

    def test_a_user_without_a_task_gets_the_mask_and_no_file(self):
        detail = self._detail_as(ACCOUNTANT_USER)
        self.assertEqual(detail["values"]["secret"], "محرمانه")
        self.assertEqual(detail["values"]["proof"], "محرمانه")
        self.assertEqual(detail["values"]["items"], "محرمانه")
        self.assertEqual(detail["values"]["reason"], "عادی")
        self.assertEqual(detail["attachments"], [])
        self.assertEqual(detail["attachment_count"], 0)
        self.assertNotIn("p.pdf", frappe.as_json(detail["values"]))
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(self.request["name"])

    def test_search_text_never_holds_sensitive_values(self):
        text = frappe.db.get_value("ASOUD Workflow Request", self.request["name"], "search_text")
        self.assertNotIn(ITEM, text)
        self.assertIn(self.request["name"], text)

    def test_the_same_items_are_searchable_when_the_field_is_not_sensitive(self):
        definition, _stages = make_definition(self.company, approvals=1)
        plain = create(self.company, definition=definition, values={"items": [{"item_code": ITEM, "qty": 1}]})
        self.assertIn(ITEM, frappe.db.get_value("ASOUD Workflow Request", plain["name"], "search_text"))


class TestSelfApprovalRouting(APITestCase):
    def _request(self, approvers, escalation_roles=None):
        definition, _stages = make_definition(self.company, approvals=1)
        stage = frappe.get_doc("ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Approval"})
        config = frappe.parse_json(stage.config_json)
        config.update(assignment_type="Employee", approver_employees=[
            frappe.db.get_value("Employee", {"user_id": user}) for user in approvers])
        if escalation_roles:
            config["escalation_roles"] = escalation_roles
        stage.config_json = frappe.as_json(config)
        stage.save(ignore_permissions=True)
        return create(self.company, definition=definition, values={"reason": "دلیل"})

    def _assignees(self, request):
        return frappe.get_all("ASOUD Workflow Task", filters={
            "workflow_instance": request["workflow_instance"], "status": "Open"}, pluck="assigned_to")

    def test_the_owner_gets_no_task_when_other_approvers_exist(self):
        request = self._request([EMPLOYEE_USER, APPROVER_USER])
        self.assertEqual(self._assignees(request), [APPROVER_USER])

    def test_the_owner_alone_escalates_to_the_fallback_role(self):
        request = self._request([EMPLOYEE_USER], ["Accounts User"])
        assignees = self._assignees(request)
        self.assertIn(ACCOUNTANT_USER, assignees)
        self.assertNotIn(EMPLOYEE_USER, assignees)

    def test_the_owner_alone_without_a_fallback_keeps_the_task_and_leaves_a_note(self):
        request = self._request([EMPLOYEE_USER])
        self.assertEqual(self._assignees(request), [EMPLOYEE_USER])
        notes = frappe.get_all("ASOUD Workflow Activity", filters={
            "workflow_instance": request["workflow_instance"], "action": "Note"}, pluck="comment")
        self.assertEqual(notes, ["تأییدکننده‌ای غیر از درخواست‌دهنده برای این مرحله تعریف نشده است."])
        task = open_task(request["workflow_instance"], EMPLOYEE_USER)
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaisesRegex(frappe.PermissionError, "تأیید درخواست خودتان مجاز نیست"):
            workflow_runtime.complete_workflow_task(task.name, "Approve")
