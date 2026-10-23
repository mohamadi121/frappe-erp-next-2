"""Directives lifecycle and tenant isolation integration tests."""

import uuid

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, get_fullname, now_datetime, nowdate

from asoud_erp.api.v1 import directives, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    APPROVER_USER,
    EMPLOYEE_USER,
    APITestCase,
    _employee,
    _user,
)
from asoud_erp.integration_tests.tenancy import ACCOUNTS_B_USER, setup_tenancy
from asoud_erp.services.directive_access import COMMUNICATION

EXECUTOR2_USER = "asoud.directive-exec2@example.com"
UNRELATED_USER = "asoud.directive-unrelated@example.com"
DIRECTIVE_SUBJECT = "دستور پیگیری تجهیزات"
PROGRESS_BODY = "پیشرفت کار تا این لحظه گزارش شد."
FINAL_BODY = "کار انجام شد و گزارش نهایی ثبت گردید."


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

        # 4. Employee sees directive with Pending state (all executors Pending reads as "Issued")
        frappe.set_user(EMPLOYEE_USER)
        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "Issued")
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


def _key(prefix):
    return f"hk1-{prefix}-{uuid.uuid4().hex}"


def _reminder(days):
    return f"{add_days(nowdate(), days)} 09:00:00"


class TestDirectiveStartProgressAndReminders(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        _user(EXECUTOR2_USER, ["Employee"])
        _user(UNRELATED_USER, ["Employee"])

        approver_emp = frappe.db.get_value("Employee", {"user_id": APPROVER_USER}, "name")
        _employee(EXECUTOR2_USER, "Executor Two", reports_to=approver_emp)
        _employee(UNRELATED_USER, "Unrelated Person", reports_to=None)
        frappe.db.commit()

    def _payload(self, executors, primary, due_days=7, reminder_at=None):
        payload = {
            "subject": DIRECTIVE_SUBJECT,
            "body": "لطفاً پیشرفت کار را گزارش کنید.",
            "priority": "Medium",
            "due_date": str(add_days(nowdate(), due_days)),
            "allow_transfer": False,
            "executor_ids": executors,
            "primary_id": primary,
        }
        if reminder_at:
            payload["reminder_at"] = reminder_at
        return payload

    def _issue(self, executors, primary, reminder_at=None):
        frappe.set_user(APPROVER_USER)
        draft = directives.save_draft(
            company=self.company,
            payload=self._payload(executors, primary, reminder_at=reminder_at),
            request_key=_key("draft"),
        )["data"]
        directives.issue(company=self.company, directive=draft["id"], request_key=_key("issue"))
        return draft["id"]

    def _instance(self, directive):
        return frappe.db.get_value(COMMUNICATION, directive, "workflow_instance")

    def _report_task(self, directive, user):
        return frappe.db.get_value("ASOUD Workflow Task", {
            "workflow_instance": self._instance(directive), "assigned_to": user,
            "directive_kind": "Report", "status": "Open",
        }, "name")

    def _progress(self, directive, user):
        frappe.set_user(user)
        return directives.report(
            company=self.company,
            directive=directive,
            payload={"report_type": "progress", "body": PROGRESS_BODY, "done_date": nowdate()},
            request_key=_key("progress"),
        )

    def _reminder_count(self, user):
        return frappe.db.count("Notification Log", {
            "for_user": user, "subject": "یادآوری انجام دستور: " + DIRECTIVE_SUBJECT,
        })

    def test_start_moves_only_the_recipient_from_pending(self):
        directive_id = self._issue([EMPLOYEE_USER, EXECUTOR2_USER], EMPLOYEE_USER)
        instance = self._instance(directive_id)
        task = self._report_task(directive_id, EMPLOYEE_USER)

        # Only a recipient can start; the issuer and an unrelated employee cannot.
        frappe.set_user(APPROVER_USER)
        with self.assertRaises(frappe.PermissionError):
            directives.start(company=self.company, directive=directive_id, request_key=_key("start"))
        frappe.set_user(UNRELATED_USER)
        with self.assertRaises(frappe.PermissionError):
            directives.start(company=self.company, directive=directive_id, request_key=_key("start"))

        frappe.set_user(EMPLOYEE_USER)
        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "Issued")
        self.assertIn("start", view["allowed_actions"])

        directives.start(company=self.company, directive=directive_id, request_key=_key("start"))

        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "In Progress")
        self.assertNotIn("start", view["allowed_actions"])
        self.assertIn("report", view["allowed_actions"])
        self.assertIn("progress", view["allowed_actions"])
        # Starting does not complete the execution task.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task, "status"), "Open")
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity", {"workflow_instance": instance, "action": "شروع کار"}), 1)

        # A second start is rejected once the recipient is In Progress.
        with self.assertRaises(frappe.PermissionError):
            directives.start(company=self.company, directive=directive_id, request_key=_key("start"))

        # The other executor is still Pending.
        frappe.set_user(APPROVER_USER)
        issuer_view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        states = {row["person"]["id"]: row["status"] for row in issuer_view["executors"]}
        self.assertEqual(states, {EMPLOYEE_USER: "In Progress", EXECUTOR2_USER: "Pending"})

    def test_progress_report_keeps_execution_task_open_until_final_report(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        instance = self._instance(directive_id)
        task = self._report_task(directive_id, EMPLOYEE_USER)

        self._progress(directive_id, EMPLOYEE_USER)

        # The execution task stays Open; the progress record is a separate Completed task.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task, "status"), "Open")
        progress_tasks = frappe.get_all("ASOUD Workflow Task", filters={
            "workflow_instance": instance, "action": "Progress"},
            fields=["status", "directive_kind", "assigned_to"])
        self.assertEqual(len(progress_tasks), 1)
        self.assertEqual(progress_tasks[0].status, "Completed")
        self.assertEqual(progress_tasks[0].directive_kind, "Report")
        self.assertEqual(progress_tasks[0].assigned_to, EMPLOYEE_USER)

        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "In Progress")
        self.assertIn("report", view["allowed_actions"])
        self.assertNotIn("start", view["allowed_actions"])

        # A final report without report_type is a final report: it completes the task and asks for review.
        directives.report(
            company=self.company,
            directive=directive_id,
            payload={"body": FINAL_BODY, "done_date": nowdate()},
            request_key=_key("report"),
        )
        final = frappe.db.get_value("ASOUD Workflow Task", task, ["status", "action"], as_dict=True)
        self.assertEqual(final.status, "Completed")
        self.assertEqual(final.action, "Report")

        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "Awaiting Review")
        self.assertNotIn("report", view["allowed_actions"])

        frappe.set_user(APPROVER_USER)
        rows = directives.reports(company=self.company, directive=directive_id)["data"]["items"]
        self.assertEqual(sorted(row["status"] for row in rows), ["Awaiting Review", "Progress"])

    def test_report_rejects_unknown_report_type_without_recording(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        instance = self._instance(directive_id)

        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            directives.report(
                company=self.company,
                directive=directive_id,
                payload={"report_type": "draft", "body": PROGRESS_BODY, "done_date": nowdate()},
                request_key=_key("report"),
            )

        recorded = frappe.get_all("ASOUD Workflow Task", filters={
            "workflow_instance": instance, "action": ["in", ["Report", "Progress"]]}, pluck="name")
        self.assertEqual(recorded, [])
        view = directives.get_directive(company=self.company, directive=directive_id)["data"]
        self.assertEqual(view["status"], "Issued")

    def test_reports_paginate_in_database_with_next_cursor(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        instance = self._instance(directive_id)
        for _ in range(51):
            self._progress(directive_id, EMPLOYEE_USER)

        frappe.set_user(APPROVER_USER)
        first = directives.reports(company=self.company, directive=directive_id)["data"]
        last = directives.reports(company=self.company, directive=directive_id, start=50)["data"]

        self.assertEqual(len(first["items"]), 50)
        self.assertEqual(first["next_cursor"], "50")
        self.assertEqual(len(last["items"]), 1)
        self.assertIsNone(last["next_cursor"])
        ids = [row["id"] for row in first["items"] + last["items"]]
        self.assertEqual(len(set(ids)), 51)
        self.assertEqual(
            frappe.db.count("ASOUD Workflow Task", {"workflow_instance": instance, "action": "Progress"}), 51)

    def test_reports_author_filter_is_limited_to_issuer_or_self(self):
        directive_id = self._issue([EMPLOYEE_USER, EXECUTOR2_USER], EMPLOYEE_USER)
        self._progress(directive_id, EMPLOYEE_USER)
        self._progress(directive_id, EXECUTOR2_USER)

        frappe.set_user(APPROVER_USER)
        everyone = directives.reports(company=self.company, directive=directive_id)["data"]["items"]
        self.assertEqual(sorted(row["author"]["id"] for row in everyone), sorted([EMPLOYEE_USER, EXECUTOR2_USER]))
        only_second = directives.reports(
            company=self.company, directive=directive_id, author=EXECUTOR2_USER)["data"]["items"]
        self.assertEqual([row["author"]["id"] for row in only_second], [EXECUTOR2_USER])

        frappe.set_user(EMPLOYEE_USER)
        own = directives.reports(company=self.company, directive=directive_id)["data"]["items"]
        self.assertEqual([row["author"]["id"] for row in own], [EMPLOYEE_USER])
        own_filtered = directives.reports(
            company=self.company, directive=directive_id, author=EMPLOYEE_USER)["data"]["items"]
        self.assertEqual([row["author"]["id"] for row in own_filtered], [EMPLOYEE_USER])
        with self.assertRaises(frappe.PermissionError):
            directives.reports(company=self.company, directive=directive_id, author=EXECUTOR2_USER)

    def test_history_shows_executor_own_and_public_events_only(self):
        directive_id = self._issue([EMPLOYEE_USER, EXECUTOR2_USER], EMPLOYEE_USER)
        self._progress(directive_id, EMPLOYEE_USER)
        self._progress(directive_id, EXECUTOR2_USER)

        frappe.set_user(EMPLOYEE_USER)
        seen = directives.history(company=self.company, directive=directive_id)["data"]["items"]
        frappe.set_user(APPROVER_USER)
        everything = directives.history(company=self.company, directive=directive_id)["data"]["items"]

        # Own progress and own assignment, plus the public issue event, but not the other executor's work.
        seen_actions = [row["action"] for row in seen]
        self.assertEqual(seen_actions.count("ارسال گزارش پیشرفت"), 1)
        self.assertEqual(seen_actions.count("تخصیص وظیفه"), 1)
        self.assertEqual(seen_actions.count("ابلاغ دستور"), 1)
        self.assertNotIn(get_fullname(EXECUTOR2_USER), [row["actor"] for row in seen])

        # The issuer sees every event.
        everything_actions = [row["action"] for row in everything]
        self.assertEqual(everything_actions.count("ارسال گزارش پیشرفت"), 2)
        self.assertEqual(everything_actions.count("تخصیص وظیفه"), 2)
        self.assertIn(get_fullname(EXECUTOR2_USER), [row["actor"] for row in everything])

    def test_history_paginates_every_row_once(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        instance = self._instance(directive_id)
        for _ in range(51):
            self._progress(directive_id, EMPLOYEE_USER)

        frappe.set_user(APPROVER_USER)
        total = frappe.db.count("ASOUD Workflow Activity", {"workflow_instance": instance}) + frappe.db.count(
            "Comment", {"reference_doctype": COMMUNICATION, "reference_name": directive_id, "comment_type": "Info"})
        self.assertGreater(total, 50)

        first = directives.history(company=self.company, directive=directive_id)["data"]
        second = directives.history(company=self.company, directive=directive_id, start=50)["data"]
        self.assertEqual(len(first["items"]), 50)
        self.assertEqual(first["next_cursor"], "50")
        self.assertEqual(len(second["items"]), total - 50)
        self.assertIsNone(second["next_cursor"])
        # Newest first across the page boundary.
        self.assertGreaterEqual(first["items"][-1]["created_at"], second["items"][0]["created_at"])

    def test_save_draft_rejects_reminder_after_due_date(self):
        frappe.set_user(APPROVER_USER)
        with self.assertRaises(frappe.ValidationError):
            directives.save_draft(
                company=self.company,
                payload=self._payload([EMPLOYEE_USER], EMPLOYEE_USER, due_days=7, reminder_at=_reminder(8)),
                request_key=_key("draft"),
            )

    def test_reminder_inside_window_is_stored_and_copied_to_report_task(self):
        frappe.set_user(APPROVER_USER)
        reminder = _reminder(2)
        draft = directives.save_draft(
            company=self.company,
            payload=self._payload([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=reminder),
            request_key=_key("draft"),
        )["data"]
        view = directives.get_directive(company=self.company, directive=draft["id"])["data"]
        self.assertEqual(get_datetime(view["reminder_at"]), get_datetime(reminder))

        directives.issue(company=self.company, directive=draft["id"], request_key=_key("issue"))
        task = self._report_task(draft["id"], EMPLOYEE_USER)
        self.assertEqual(get_datetime(frappe.db.get_value("ASOUD Workflow Task", task, "reminder_on")),
                         get_datetime(reminder))

    def test_issue_rejects_reminder_in_the_past_or_after_due_date(self):
        # save_draft only rejects a reminder after the due date; issue also rejects a past one.
        # The stored value is changed directly so the issue-time check is what gets exercised.
        for reminder in (_reminder(-1), _reminder(8)):
            with self.subTest(reminder=reminder):
                frappe.set_user(APPROVER_USER)
                draft = directives.save_draft(
                    company=self.company,
                    payload=self._payload([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=_reminder(2)),
                    request_key=_key("draft"),
                )["data"]
                frappe.db.set_value(COMMUNICATION, draft["id"], "reminder_at", reminder)
                with self.assertRaises(frappe.ValidationError):
                    directives.issue(company=self.company, directive=draft["id"], request_key=_key("issue"))
                self.assertEqual(frappe.db.get_value(COMMUNICATION, draft["id"], "status"), "Draft")

    def test_notify_reminder_sends_once(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=_reminder(2))
        task = self._report_task(directive_id, EMPLOYEE_USER)
        frappe.db.set_value("ASOUD Workflow Task", task, "reminder_on", add_to_date(now_datetime(), minutes=-5))

        frappe.set_user("Administrator")
        directives.notify_reminder(frappe.get_doc("ASOUD Workflow Task", task))
        sent_on = frappe.db.get_value("ASOUD Workflow Task", task, "reminder_sent_on")
        self.assertIsNotNone(sent_on)
        self.assertEqual(self._reminder_count(EMPLOYEE_USER), 1)

        directives.notify_reminder(frappe.get_doc("ASOUD Workflow Task", task))
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", task, "reminder_sent_on"), sent_on)
        self.assertEqual(self._reminder_count(EMPLOYEE_USER), 1)

    def test_reminder_is_not_sent_after_due_on(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=_reminder(2))
        task = self._report_task(directive_id, EMPLOYEE_USER)
        past = add_to_date(now_datetime(), minutes=-5)
        frappe.db.set_value("ASOUD Workflow Task", task, {"reminder_on": past, "due_on": past})

        frappe.set_user("Administrator")
        directives.notify_reminder(frappe.get_doc("ASOUD Workflow Task", task))
        directives.dispatch_reminders()

        self.assertIsNone(frappe.db.get_value("ASOUD Workflow Task", task, "reminder_sent_on"))
        self.assertEqual(self._reminder_count(EMPLOYEE_USER), 0)

    def test_dispatch_reminders_sends_due_reminder_once(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=_reminder(2))
        task = self._report_task(directive_id, EMPLOYEE_USER)
        frappe.db.set_value("ASOUD Workflow Task", task, "reminder_on", add_to_date(now_datetime(), minutes=-5))

        frappe.set_user("Administrator")
        directives.dispatch_reminders()
        self.assertIsNotNone(frappe.db.get_value("ASOUD Workflow Task", task, "reminder_sent_on"))
        directives.dispatch_reminders()

        self.assertEqual(self._reminder_count(EMPLOYEE_USER), 1)

    def test_list_my_workflow_tasks_paged_shape_keeps_legacy_list(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        task = self._report_task(directive_id, EMPLOYEE_USER)

        frappe.set_user(EMPLOYEE_USER)
        paged = workflow_runtime.list_my_workflow_tasks(status="Open", paged=1)["data"]
        self.assertEqual(set(paged), {"items", "next_cursor"})
        self.assertIsNone(paged["next_cursor"])
        row = next(item for item in paged["items"] if item["name"] == task)
        self.assertEqual(row["workflow_instance"], self._instance(directive_id))
        self.assertEqual(row["status"], "Open")

        legacy = workflow_runtime.list_my_workflow_tasks(status="Open")
        self.assertIsInstance(legacy["data"], list)
        self.assertEqual(legacy["meta"]["total"], len(legacy["data"]))
        self.assertIn(task, [item["name"] for item in legacy["data"]])

    def test_list_my_workflow_instances_paged_shape(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        instance = self._instance(directive_id)

        # Instances are listed for their starter, which is the issuer here.
        frappe.set_user(APPROVER_USER)
        paged = workflow_runtime.list_my_workflow_instances(status="Running", paged=1)["data"]
        self.assertEqual(set(paged), {"items", "next_cursor"})
        self.assertIsNone(paged["next_cursor"])
        self.assertIn(instance, [item["name"] for item in paged["items"]])

    def test_reminder_with_utc_offset_is_converted_to_site_time(self):
        from frappe.utils import get_system_timezone

        from asoud_erp.services.directive_paging import site_naive_datetime
        day = add_days(nowdate(), 2)
        frappe.set_user(APPROVER_USER)
        draft = directives.save_draft(
            company=self.company,
            payload=self._payload([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=f"{day}T06:00:00Z"),
            request_key=_key("draft"),
        )["data"]
        stored = get_datetime(frappe.db.get_value(COMMUNICATION, draft["id"], "reminder_at"))
        self.assertEqual(stored, site_naive_datetime(f"{day}T06:00:00+00:00", get_system_timezone()))

    def test_dispatch_reminders_survives_a_broken_task(self):
        broken = self._issue([EMPLOYEE_USER], EMPLOYEE_USER, reminder_at=_reminder(2))
        good = self._issue([EXECUTOR2_USER], EXECUTOR2_USER, reminder_at=_reminder(2))
        past = add_to_date(now_datetime(), minutes=-5)
        bad_task = self._report_task(broken, EMPLOYEE_USER)
        good_task = self._report_task(good, EXECUTOR2_USER)
        frappe.db.set_value("ASOUD Workflow Task", bad_task, "reminder_on", past)
        frappe.db.set_value("ASOUD Workflow Task", good_task, "reminder_on", past)
        frappe.set_user("Administrator")
        original = directives.notify_reminder

        def flaky(task):
            if task.name == bad_task:
                raise RuntimeError("boom")
            return original(task)

        directives.notify_reminder = flaky
        try:
            directives.dispatch_reminders()
        finally:
            directives.notify_reminder = original
        self.assertIsNotNone(frappe.db.get_value("ASOUD Workflow Task", good_task, "reminder_sent_on"))
        self.assertIsNone(frappe.db.get_value("ASOUD Workflow Task", bad_task, "reminder_sent_on"))

    def test_paged_task_list_reports_total_and_no_cursor_on_last_page(self):
        directive_id = self._issue([EMPLOYEE_USER], EMPLOYEE_USER)
        task = self._report_task(directive_id, EMPLOYEE_USER)
        frappe.set_user(EMPLOYEE_USER)
        result = workflow_runtime.list_my_workflow_tasks(status="Open", paged=1)
        self.assertIsNone(result["data"]["next_cursor"])
        self.assertGreaterEqual(result["meta"]["total"], 1)
        self.assertIn(task, [i["name"] for i in result["data"]["items"]])
        instances = workflow_runtime.list_my_workflow_instances(paged=1)
        self.assertEqual(set(instances["data"]), {"items", "next_cursor"})
