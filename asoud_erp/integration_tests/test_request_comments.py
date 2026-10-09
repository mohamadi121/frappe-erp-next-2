"""Free comments on a request: permissions, ordering, notifications and replay safety."""

import frappe

from asoud_erp.api.v1 import sync, workflow_request
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create

METHOD = "asoud_erp.api.v1.workflow_request.add_request_comment"


class TestRequestComments(APITestCase):
    def setUp(self):
        super().setUp()
        definition, _stages = make_definition(self.company)
        self.request = create(self.company, definition=definition)["name"]

    def _count(self):
        return frappe.db.count("Comment", {"comment_type": "Comment", "reference_doctype": "ASOUD Workflow Request",
                                           "reference_name": self.request})

    def test_the_owner_and_the_current_assignee_can_comment_and_list(self):
        frappe.set_user(EMPLOYEE_USER)
        mine = workflow_request.add_request_comment(self.request, "  <b>سلام</b> مدیر  ")["data"]
        self.assertEqual((mine["content"], mine["author"], mine["is_mine"]), ("سلام مدیر", EMPLOYEE_USER, True))
        self.assertEqual(mine["author_name"], frappe.db.get_value("Employee", {"user_id": EMPLOYEE_USER},
                                                                  "employee_name"))
        frappe.set_user(APPROVER_USER)
        reply = workflow_request.add_request_comment(self.request, "لطفاً پیش‌فاکتور را پیوست کنید.")["data"]
        listed = workflow_request.list_request_comments(self.request)
        self.assertEqual([row["content"] for row in listed["data"]], ["سلام مدیر", reply["content"]])
        self.assertEqual([row["is_mine"] for row in listed["data"]], [False, True])
        self.assertEqual(listed["meta"]["total"], 2)
        detail = workflow_request.get_request(self.request)["data"]
        self.assertEqual(detail["comment_count"], 2)

    def test_comments_notify_the_other_participants_but_not_the_author(self):
        frappe.set_user(APPROVER_USER)
        workflow_request.add_request_comment(self.request, "بررسی شد")
        recipients = frappe.get_all("Notification Log", filters={"subject": ["like", "%" + self.request + "%"]},
                                    pluck="for_user")
        self.assertIn(EMPLOYEE_USER, recipients)
        self.assertNotIn(APPROVER_USER, recipients)

    def test_a_stranger_cannot_read_or_write_comments(self):
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.add_request_comment(self.request, "خصوصی")
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.list_request_comments(self.request)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.add_request_comment(self.request, "نباید ثبت شود")
        self.assertEqual(self._count(), 1)

    def test_empty_comments_are_refused_with_their_code(self):
        frappe.set_user(EMPLOYEE_USER)
        for content in ("", "   ", "<br>", "<p> </p>"):
            with self.assertRaises(frappe.ValidationError):
                workflow_request.add_request_comment(self.request, content)
        with self.assertRaises(frappe.ValidationError):
            workflow_request.add_request_comment(self.request, "x" * 2001)
        self.assertEqual(self._count(), 0)

    def test_a_replay_through_the_sync_layer_creates_one_comment(self):
        frappe.set_user(EMPLOYEE_USER)
        payload = {"name": self.request, "content": "فقط یک بار"}
        first = sync.execute_mutation("comment-key-" + self.request, METHOD, payload)
        again = sync.execute_mutation("comment-key-" + self.request, METHOD, payload)
        self.assertTrue(first["ok"])
        self.assertEqual(again, first)
        self.assertEqual(self._count(), 1)
        other = sync.execute_mutation("comment-key-2-" + self.request, METHOD, payload)
        self.assertNotEqual(other["data"]["name"], first["data"]["name"])
        self.assertEqual(self._count(), 2)

    def test_comments_are_paginated_oldest_first(self):
        frappe.set_user(EMPLOYEE_USER)
        for index in range(3):
            workflow_request.add_request_comment(self.request, f"نظر {index}")
        page = workflow_request.list_request_comments(self.request, limit_start=1, limit_page_length=1)
        self.assertEqual([row["content"] for row in page["data"]], ["نظر 1"])
        self.assertEqual((page["meta"]["total"], page["meta"]["limit_start"]), (3, 1))
