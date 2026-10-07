"""Leave template: daily and hourly leave, balance, preview and the post-approval documents."""

import frappe
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import hr_self_service as hr
from asoud_erp.api.v1 import leave_request, workflow_request
from asoud_erp.integration_tests.fixtures import ACCOUNTANT_USER, APPROVER_USER, EMPLOYEE_USER, LEAVE_TYPE
from asoud_erp.integration_tests.request_template_support import (
    TemplateTestCase,
    make_leave_type,
    weekday,
)

LEDGER = "ASOUD Workflow Request"


def ledger_entries(request_name: str) -> list:
    return frappe.get_all("Leave Ledger Entry", filters={"transaction_type": LEDGER,
                                                          "transaction_name": request_name},
                          fields=["name", "leaves", "from_date", "to_date", "docstatus", "leave_type",
                                  "is_lwp", "employee"])


def leave_applications(request_name: str) -> list:
    return frappe.get_all("Leave Application", filters={"asoud_request": request_name},
                          fields=["name", "docstatus", "status", "from_date", "to_date", "total_leave_days",
                                  "leave_type"])


class TestLeaveRequestTemplate(TemplateTestCase):
    def daily(self, start: str, end: str | None = None, leave_type: str = LEAVE_TYPE, **extra) -> dict:
        return {**self.requester(), "leave_type": leave_type, "request_kind": "Daily", "start_date": start,
                "end_date": end or start, "reason": "سفر شخصی", **extra}

    def hourly(self, day: str, start: str = "09:00", end: str = "13:00", leave_type: str = LEAVE_TYPE,
               **extra) -> dict:
        return {**self.requester(), "leave_type": leave_type, "request_kind": "Hourly", "leave_date": day,
                "start_time": start, "end_time": end, "reason": "مراجعه به پزشک", **extra}

    def balance(self, leave_type: str = LEAVE_TYPE) -> dict:
        data = leave_request.get_leave_balance(self.company)["data"]
        return next(row for row in data["leave_types"] if row["leave_type"] == leave_type)

    def native_remaining(self, leave_type: str = LEAVE_TYPE) -> float:
        from hrms.hr.doctype.leave_application.leave_application import get_leave_details

        employee = self.records["employee"]
        return get_leave_details(employee, nowdate())["leave_allocation"][leave_type]["remaining_leaves"]

    # ---------------------------------------------------------------- daily

    def test_daily_approval_creates_a_submitted_leave_application_and_attendance(self):
        day = weekday(5)
        data = self.create("leave", self.daily(day), subject="ignored by the server")
        name = data["name"]
        self.assertRegex(name, r"^LV-\d{4}-\d{4}$")
        self.assertEqual(self.row(name).subject, "مرخصی سالانه (روزانه)")
        self.assertEqual(self.row(name).department, self.department)
        self.decide(name)
        row = self.row(name)
        self.assertEqual((row.status_key, row.native_status, row.native_doctype),
                         ("approved", "Created", "Leave Application"))
        (application,) = leave_applications(name)
        self.assertEqual((application.docstatus, application.status, application.total_leave_days),
                         (1, "Approved", 1))
        self.assertEqual(row.native_name, application.name)
        self.assertEqual(frappe.db.get_value("Leave Application", application.name, "leave_approver"),
                         APPROVER_USER)
        self.assertTrue(frappe.db.exists("Attendance", {"employee": self.records["employee"],
                                                        "attendance_date": day, "status": "On Leave",
                                                        "docstatus": 1}))
        from hrms.hr.doctype.leave_application.leave_application import get_leave_details

        taken = get_leave_details(self.records["employee"], nowdate())["leave_allocation"][LEAVE_TYPE]
        self.assertEqual(taken["leaves_taken"], 1)
        # Dispatching again creates nothing.
        from asoud_erp.services import request_native_documents as native

        frappe.db.set_value("ASOUD Workflow Request", name, "native_status", "")
        native.dispatch(frappe.get_doc("ASOUD Workflow Request", name))
        self.assertEqual(len(leave_applications(name)), 1)

    def test_final_approval_leaves_the_approvers_request_session_untouched(self):
        # The post-approval step runs HRMS code as Administrator inside the approver's request; the
        # approver's sid, session data (csrf token) and form_dict must come back exactly as they were.
        daily = self.create("leave", self.daily(weekday(5)))["name"]
        self.decide(daily, probe_session=True)
        self.assertEqual(self.row(daily).native_status, "Created")
        hourly = self.create("leave", self.hourly(weekday(6)))["name"]
        self.decide(hourly, probe_session=True)
        self.assertEqual(self.row(hourly).native_status, "Created")

    def test_client_subject_is_ignored_and_category_label_used(self):
        frappe.db.set_value("Leave Type", LEAVE_TYPE, "asoud_leave_category", "sick")
        name = self.create("leave", self.hourly(weekday(4)), subject="anything")["name"]
        self.assertEqual(self.row(name).subject, "مرخصی استعلاجی (ساعتی)")

    def test_daily_validation_codes(self):
        day = weekday(5)
        with self.assertCode("INVALID_DATE_RANGE"):
            self.create("leave", self.daily(add_days(day, 2), day))
        with self.assertCode("REQUESTER_MISMATCH"):
            self.create("leave", {**self.daily(day), "requester": APPROVER_USER})
        # Every selected day is a holiday of the employee's list.
        holidays = frappe.get_doc("Holiday List", frappe.db.get_value("Employee", self.records["employee"],
                                                                      "holiday_list"))
        holiday = weekday(12)
        holidays.append("holidays", {"holiday_date": holiday, "description": "تعطیل آزمایشی"})
        holidays.save(ignore_permissions=True)
        with self.assertCode("LEAVE_ALL_HOLIDAYS"):
            self.create("leave", self.daily(holiday))

    def test_insufficient_balance_at_create(self):
        one_day = make_leave_type("ASOUD One Day Leave", 1)
        day = weekday(6)
        with self.assertCode("INSUFFICIENT_LEAVE_BALANCE"):
            self.create("leave", self.daily(day, add_days(day, 1), leave_type=one_day))
        # Exactly the available day is fine.
        self.assertTrue(self.create("leave", self.daily(day, leave_type=one_day))["name"])

    def test_overlapping_daily_requests_are_refused(self):
        day = weekday(8)
        self.create("leave", self.daily(day, add_days(day, 1)))
        with self.assertCode("LEAVE_OVERLAP"):
            self.create("leave", self.daily(add_days(day, 1)))
        with self.assertCode("LEAVE_OVERLAP"):
            self.create("leave", self.hourly(day))

    def test_cancel_while_pending_creates_nothing(self):
        name = self.create("leave", self.daily(weekday(9)))["name"]
        workflow_request.cancel_request(name, reason="انصراف")
        self.assertEqual(self.row(name).status_key, "cancelled")
        self.assertFalse(leave_applications(name) or ledger_entries(name))
        self.assertFalse(self.row(name).native_status)
        # The cancelled request no longer reserves balance or calendar.
        self.assertTrue(self.create("leave", self.daily(weekday(9)))["name"])

    # ---------------------------------------------------------------- hourly

    def test_hourly_approval_creates_one_ledger_entry_and_lowers_the_balance(self):
        day = weekday(5)
        before = self.balance()
        native_before = self.native_remaining()
        name = self.create("leave", self.hourly(day, "09:00", "13:00"))["name"]
        pending = self.balance()
        self.assertEqual(pending["leaves_pending"], before["leaves_pending"] + 0.5)
        self.assertEqual(pending["available"], before["available"] - 0.5)
        self.assertEqual(pending["remaining"], before["remaining"])
        self.decide(name)
        row = self.row(name)
        self.assertEqual((row.native_status, row.native_doctype), ("Created", "Leave Ledger Entry"))
        (entry,) = ledger_entries(name)
        self.assertEqual((entry.leaves, entry.docstatus, entry.leave_type, entry.is_lwp),
                         (-0.5, 1, LEAVE_TYPE, 0))
        self.assertEqual((str(entry.from_date), str(entry.to_date)), (day, day))
        self.assertEqual(row.native_name, entry.name)
        after = self.balance()
        self.assertEqual(after["remaining"], before["remaining"] - 0.5)
        self.assertEqual(after["hourly_taken"], 0.5)
        self.assertEqual(after["leaves_pending"], before["leaves_pending"])  # reservation became a deduction
        self.assertEqual(self.native_remaining(), native_before)  # HRMS does not see it
        self.assertFalse(leave_applications(name))
        # And never twice.
        from asoud_erp.services import request_native_documents as native

        frappe.db.set_value("ASOUD Workflow Request", name, "native_status", "")
        native.dispatch(frappe.get_doc("ASOUD Workflow Request", name))
        self.assertEqual(len(ledger_entries(name)), 1)

    def test_one_and_a_half_hours_and_a_seven_and_a_half_hour_company(self):
        frappe.db.set_value("Company", self.company, "asoud_daily_working_hours", 7.5)
        day = weekday(5)
        name = self.create("leave", self.hourly(day, "10:00", "11:30"))["name"]
        self.decide(name)
        (entry,) = ledger_entries(name)
        self.assertEqual(entry.leaves, -0.2)  # 1.5 / 7.5

    def test_hourly_validation_codes(self):
        day = weekday(5)
        with self.assertCode("INVALID_TIME_RANGE"):
            self.create("leave", self.hourly(day, "13:00", "09:00"))
        with self.assertCode("INVALID_TIME_RANGE"):
            self.create("leave", self.hourly(day, "09:00", "09:10"))
        with self.assertCode("HOURLY_EXCEEDS_DAY"):
            self.create("leave", self.hourly(day, "07:00", "16:00"))

    def test_overlapping_hourly_request_and_holiday_are_refused(self):
        day = weekday(5)
        self.create("leave", self.hourly(day, "09:00", "11:00"))
        with self.assertCode("LEAVE_OVERLAP"):
            self.create("leave", self.hourly(day, "10:30", "12:00"))
        # Back to back is not an overlap, the day total (8 h) still fits.
        self.assertTrue(self.create("leave", self.hourly(day, "11:00", "13:00"))["name"])
        with self.assertCode("HOURLY_EXCEEDS_DAY"):
            self.create("leave", self.hourly(day, "13:00", "20:00"))
        holiday = weekday(14)
        holidays = frappe.get_doc("Holiday List", frappe.db.get_value("Employee", self.records["employee"],
                                                                      "holiday_list"))
        holidays.append("holidays", {"holiday_date": holiday, "description": "تعطیل آزمایشی"})
        holidays.save(ignore_permissions=True)
        with self.assertCode("HOURLY_ON_HOLIDAY"):
            self.create("leave", self.hourly(holiday))

    def test_hourly_leave_against_an_approved_daily_leave_is_refused(self):
        day = weekday(5)
        name = self.create("leave", self.daily(day))["name"]
        self.decide(name)
        with self.assertCode("LEAVE_OVERLAP"):
            self.create("leave", self.hourly(day))

    def test_a_later_full_day_leave_cannot_spend_what_hourly_leave_took(self):
        one_day = make_leave_type("ASOUD One Day Leave", 1)
        day = weekday(5)
        name = self.create("leave", self.hourly(day, "09:00", "13:00", leave_type=one_day))["name"]
        self.decide(name)
        self.assertEqual(self.balance(one_day)["remaining"], 0.5)
        other = weekday(12)
        # HRMS alone would allow 1 day (it sees 1 allocated, 0 taken); the overlay refuses.
        with self.assertRaises(frappe.ValidationError) as caught:
            hr.create_leave_application(one_day, other, other, reason="کار شخصی")
        self.assertEqual(type(caught.exception).__name__, "InsufficientLeaveBalanceError")
        # The remaining half day is fine.
        leave = hr.create_leave_application(one_day, other, other, reason="نیم‌روز", half_day=1,
                                            half_day_date=other)["data"]
        self.assertEqual(leave["status"], "Open")

    def test_final_approval_rechecks_the_balance_and_reports_it(self):
        one_day = make_leave_type("ASOUD One Day Leave", 1)
        day = weekday(5)
        first = self.create("leave", self.hourly(day, "09:00", "13:00", leave_type=one_day))["name"]
        second = self.create("leave", self.hourly(add_days(day, 1), "09:00", "13:00", leave_type=one_day))["name"]
        self.decide(first)
        # Another approved leave consumed the allocation meanwhile: the second one cannot be booked.
        extra = frappe.get_doc({"doctype": "Leave Ledger Entry", "employee": self.records["employee"],
                                "employee_name": "x", "company": self.company, "leave_type": one_day,
                                "transaction_type": LEDGER, "transaction_name": first, "leaves": -0.5,
                                "from_date": day, "to_date": day})
        extra.flags.ignore_permissions = 1
        extra.submit()
        self.decide(second)
        row = self.row(second)
        self.assertEqual(self.instance_status(second), "Completed")
        self.assertEqual((row.status_key, row.native_status), ("approved", "Failed"))
        self.assertTrue("INSUFFICIENT_LEAVE_BALANCE" in row.native_error or "مانده مرخصی" in row.native_error)
        self.assertFalse(ledger_entries(second))

    # ---------------------------------------------------------------- native failure and retry

    def test_native_failure_keeps_the_approval_and_retry_succeeds_once(self):
        day = weekday(5)
        name = self.create("leave", self.daily(day))["name"]
        block_list = frappe.get_doc({
            "doctype": "Leave Block List", "leave_block_list_name": "ASOUD Request Block", "company": self.company,
            "applies_to_all_departments": 1,
            "leave_block_list_dates": [{"block_date": day, "reason": "بسته"}]}).insert(ignore_permissions=True)
        self.decide(name)
        row = self.row(name)
        self.assertEqual(self.instance_status(name), "Completed")
        self.assertEqual((row.status_key, row.native_status), ("approved", "Failed"))
        self.assertTrue(row.native_error)
        self.assertFalse(leave_applications(name))
        self.assertNotified(name, EMPLOYEE_USER)
        frappe.delete_doc("Leave Block List", block_list.name, ignore_permissions=True, force=True)
        frappe.set_user("Administrator")
        workflow_request.create_native_document(name)
        self.assertEqual(self.row(name).native_status, "Created")
        self.assertEqual(len(leave_applications(name)), 1)
        with self.assertRaises(frappe.ValidationError):
            workflow_request.create_native_document(name)
        self.assertEqual(len(leave_applications(name)), 1)

    # ---------------------------------------------------------------- endpoints

    def test_preview_returns_errors_as_data(self):
        day = weekday(5)
        short = leave_request.preview_leave_request(
            self.company, LEAVE_TYPE, "Hourly", leave_date=day, start_time="09:00", end_time="09:10")["data"]
        self.assertFalse(short["valid"])
        self.assertEqual([error["code"] for error in short["errors"]], ["INVALID_TIME_RANGE"])
        self.assertTrue(short["errors"][0]["message"])
        ok = leave_request.preview_leave_request(
            self.company, LEAVE_TYPE, "Hourly", leave_date=day, start_time="09:00", end_time="13:00")["data"]
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["errors"], [])
        self.assertEqual(ok["duration"], {"unit": "hour", "days": None, "hours": 4.0, "day_equivalent": 0.5})
        self.assertEqual(ok["balance"]["requested_days"], 0.5)
        self.assertEqual(ok["balance"]["remaining_after"], ok["balance"]["remaining_before"] - 0.5)
        daily = leave_request.preview_leave_request(self.company, LEAVE_TYPE, "Daily", start_date=day,
                                                    end_date=add_days(day, 1))["data"]
        self.assertEqual((daily["duration"]["unit"], daily["duration"]["days"]), ("day", 2.0))
        one_day = make_leave_type("ASOUD One Day Leave", 1)
        low = leave_request.preview_leave_request(self.company, one_day, "Daily", start_date=day,
                                                  end_date=add_days(day, 1))["data"]
        self.assertFalse(low["valid"])
        self.assertEqual(low["errors"][0]["code"], "INSUFFICIENT_LEAVE_BALANCE")
        incomplete = leave_request.preview_leave_request(self.company, LEAVE_TYPE, "Daily")["data"]
        self.assertEqual((incomplete["valid"], incomplete["errors"], incomplete["duration"]), (False, [], None))

    def test_balance_endpoint_shape_and_scoping(self):
        data = leave_request.get_leave_balance(self.company)["data"]
        self.assertEqual(data["employee"], self.records["employee"])
        self.assertEqual(data["daily_working_hours"], 8)
        self.assertEqual(data["leave_approver"], APPROVER_USER)
        self.assertEqual([row["category"] for row in data["categories"]], ["annual", "sick", "other"])
        row = next(row for row in data["leave_types"] if row["leave_type"] == LEAVE_TYPE)
        self.assertEqual((row["has_allocation"], row["total_leaves"], row["hourly_taken"]), (True, 10, 0))
        self.assertEqual((row["category"], row["label"], row["is_lwp"]), ("annual", "سالانه", 0))
        annual = data["categories"][0]
        self.assertGreaterEqual(annual["remaining_days"], row["remaining"])
        # A company the user does not belong to is refused.
        with self.assertRaises(frappe.PermissionError):
            leave_request.get_leave_balance("No Such Company")
        # A company user without an active Employee gets EMPLOYEE_NOT_FOUND.
        frappe.set_user("Administrator")
        frappe.db.set_value("Employee", {"user_id": ACCOUNTANT_USER}, "status", "Left")
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertCode("EMPLOYEE_NOT_FOUND"):
            leave_request.get_leave_balance(self.company)

    def test_my_leave_summary_keeps_its_keys_and_adds_the_new_ones(self):
        name = self.create("leave", self.hourly(weekday(5), "09:00", "13:00"))["name"]
        self.decide(name)
        summary = hr.get_my_leave_summary()["data"]
        balance = next(row for row in summary["balances"] if row["leave_type"] == LEAVE_TYPE)
        for key in ("leave_type", "total_leaves", "expired_leaves", "leaves_taken", "leaves_pending_approval",
                    "remaining_leaves"):
            self.assertIn(key, balance)
        self.assertEqual(balance["total_leaves"], 10)
        self.assertEqual(balance["remaining_leaves"], 10)  # native, unchanged by hourly leave
        self.assertEqual(balance["hourly_leaves_taken"], 0.5)
        self.assertEqual(balance["available_leaves"], 9.5)
        self.assertEqual(balance["category"], "annual")
        self.assertEqual(summary["leave_approver"], APPROVER_USER)
