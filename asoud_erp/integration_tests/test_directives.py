"""Directives lifecycle and tenant isolation integration tests."""

import frappe
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import directives
from asoud_erp.integration_tests.fixtures import (
    APPROVER_USER,
    EMPLOYEE_USER,
    APITestCase,
    _employee,
    _user,
)
from asoud_erp.integration_tests.tenancy import ACCOUNTS_B_USER, setup_tenancy

EXECUTOR2_USER = "asoud.directive-exec2@example.com"
UNRELATED_USER = "asoud.directive-unrelated@example.com"


class TestDirectivesLifecycle(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

        frappe.set_user("Administrator")
        _user(EXECUTOR2_USER, ["Employee"])
        _user(UNRELATED_USER, ["Employee"])

        approver_emp = frappe.db.get_value("Employee", {"user_id": APPROVER_USER}, "name")
        _employee(EXECUTOR2_USER, "Executor Two", reports_to=approver_emp)
        _employee(UNRELATED_USER, "Unrelated Person", reports_to=None)
        frappe.db.commit()

    def test_full_directive_lifecycle_and_transfer(self):
        # 1. Approver creates a draft directive with Employee as initial executor
        frappe.set_user(APPROVER_USER)
        draft = directives.save_draft(
            company=self.company,
            payload={
                "subject": "دستور انجام بررسی دوره‌ای تجهیزات",
                "body": "لطفاً بررسی جامع انجام و گزارش ثبت شود.",
                "priority": "Urgent",
                "due_date": str(add_days(nowdate(), 7)),
                "allow_transfer": True,
                "executor_ids": [EMPLOYEE_USER],
                "primary_id": EMPLOYEE_USER,
            },
            request_key="req-draft-" + "1" * 20,
        )["data"]
        directive_id = draft["id"]
        self.assertIsNotNone(directive_id)

        # 2. Before issue, executor cannot see or read draft
        frappe.set_user(EMPLOYEE_USER)
        emp_list = [d["id"] for d in directives.list_directives(company=self.company)["data"]["items"]]
        self.assertNotIn(directive_id, emp_list)
        with self.assertRaises(frappe.PermissionError):
            directives.get_directive(company=self.company, directive=directive_id)

        # 3. Approver issues the directive
        frappe.set_user(APPROVER_USER)
        issued = directives.issue(company=self.company, directive=directive_id, request_key="req-issue-" + "2" * 20)["data"]
        self.assertEqual(issued["id"], directive_id)

        # 4. Employee sees directive with Pending state
        frappe.set_user(EMPLOYEE_USER)
        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "In Progress")
        self.assertIn("report", view["allowed_actions"])
        self.assertIn("transfer", view["allowed_actions"])

        # 5. Employee transfers responsibility to Executor 2
        directives.transfer(
            company=self.company,
            directive=directive_id,
            recipient_id=EXECUTOR2_USER,
            reason="ارجاع به همکار به دلیل مأموریت کاری",
            request_key="req-transfer-" + "3" * 20,
        )

        # 6. Verify transfer: Employee no longer has report action, Executor 2 now has report action
        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertNotIn("report", view["allowed_actions"])

        frappe.set_user(EXECUTOR2_USER)
        exec2_view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertIn("report", exec2_view["allowed_actions"])

        # 7. Executor 2 submits report
        directives.report(
            company=self.company,
            directive=directive_id,
            payload={"body": "بررسی انجام شد؛ گزارش اولیه ارسال گردید.", "done_date": str(nowdate())},
            request_key="req-report-" + "4" * 20,
        )

        # 8. Approver reviews and requests changes (returns report)
        frappe.set_user(APPROVER_USER)
        rep_items = directives.reports(company=self.company, directive=directive_id)["data"]["items"]
        self.assertTrue(len(rep_items) >= 1)
        report_task_id = rep_items[0]["id"]

        directives.review(
            company=self.company,
            directive=directive_id,
            report_id=report_task_id,
            approve=False,
            reason="لطفاً شرح تکمیلی موارد بررسی‌شده اضافه شود.",
            request_key="req-review-return-" + "5" * 20,
        )

        # 9. Executor 2 sees Returned state and resubmits
        frappe.set_user(EXECUTOR2_USER)
        exec2_view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertIn("report", exec2_view["allowed_actions"])

        directives.report(
            company=self.company,
            directive=directive_id,
            payload={"body": "شرح تکمیلی و رفع ایرادات با موفقیت اضافه شد.", "done_date": str(nowdate())},
            request_key="req-report-revised-" + "6" * 20,
        )

        # 10. Approver reviews and approves
        frappe.set_user(APPROVER_USER)
        rep_items = directives.reports(company=self.company, directive=directive_id)["data"]["items"]
        latest_report_task_id = [r["id"] for r in rep_items if r["allowed_actions"]][0]

        directives.review(
            company=self.company,
            directive=directive_id,
            report_id=latest_report_task_id,
            approve=True,
            reason="تأیید شد.",
            request_key="req-review-approve-" + "7" * 20,
        )

        # 11. Approver closes the directive
        appr_view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertIn("close", appr_view["allowed_actions"])

        directives.close(
            company=self.company,
            directive=directive_id,
            request_key="req-close-" + "8" * 20,
        )

        # 12. Verify final closed state
        closed_view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(closed_view["status"], "Closed")

    def test_directive_access_control_and_tenant_isolation(self):
        frappe.set_user(APPROVER_USER)
        draft = directives.save_draft(
            company=self.company,
            payload={
                "subject": "دستور محرمانه واحد",
                "body": "شرح محرمانه",
                "priority": "Medium",
                "due_date": str(add_days(nowdate(), 3)),
                "allow_transfer": False,
                "executor_ids": [EMPLOYEE_USER],
                "primary_id": EMPLOYEE_USER,
            },
            request_key="req-draft-sec-" + "9" * 20,
        )["data"]
        directive_id = draft["id"]

        # Unrelated user in same company cannot read draft or issued directive without recipient/sender link
        frappe.set_user(UNRELATED_USER)
        with self.assertRaises(frappe.PermissionError):
            directives.get_directive(company=self.company, directive=directive_id)

        # Issue the directive
        frappe.set_user(APPROVER_USER)
        directives.issue(company=self.company, directive=directive_id, request_key="req-issue-sec-" + "a" * 20)

        # Unrelated user still cannot read issued directive
        frappe.set_user(UNRELATED_USER)
        with self.assertRaises(frappe.PermissionError):
            directives.get_directive(company=self.company, directive=directive_id)

        # User in second company cannot access
        frappe.set_user(ACCOUNTS_B_USER)
        with self.assertRaises(frappe.PermissionError):
            directives.get_directive(company=self.second, directive=directive_id)
        with self.assertRaises(frappe.PermissionError):
            directives.list_directives(company=self.second)
