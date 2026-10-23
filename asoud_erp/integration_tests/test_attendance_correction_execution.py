import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from asoud_erp.services.form_execution import attendance_correction as execution


class TestAttendanceCorrectionExecution(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.addCleanup(frappe.set_user, "Administrator")
        self.addCleanup(frappe.db.rollback)
        token = frappe.generate_hash(length=8)
        self.company = frappe.get_doc({
            "doctype": "Company", "company_name": f"Attendance {token}", "abbr": token,
            "country": "United States", "default_currency": "USD",
            "chart_of_accounts": "Standard", "enable_perpetual_inventory": 0,
        }).insert().name
        self.user = frappe.get_doc({
            "doctype": "User", "email": f"attendance-{token}@example.com", "first_name": "تردد",
            "send_welcome_email": 0, "user_type": "System User",
            "roles": [{"role": "Employee"}],
        }).insert().name
        self.employee = frappe.get_doc({
            "doctype": "Employee", "first_name": "کارمند تردد", "company": self.company,
            "status": "Active", "gender": "Male", "date_of_birth": "1990-01-01",
            "date_of_joining": add_days(nowdate(), -365), "user_id": self.user,
            "create_user_permission": 0,
        }).insert().name
        self.definition = frappe.get_doc({
            "doctype": "ASOUD Workflow Definition", "workflow_code": f"ATT-{token}",
            "workflow_title": "اصلاح تردد", "module_key": "HR", "company": self.company,
            "target_doctype": "ASOUD Workflow Request", "status": "Inactive",
        }).insert().name
        self.request = self.create_request()
        self.day = str(add_days(nowdate(), -1))
        # Checkin does not require a shift, holiday list or account. Keep those fields empty.
        self.assertIsNone(frappe.db.get_value("Employee", self.employee, "holiday_list"))
        settings = frappe.get_single("HR Settings")
        settings.allow_geolocation_tracking = 0
        settings.save()

    def create_request(self, **overrides):
        request = frappe.get_doc({
            "doctype": "ASOUD Workflow Request", "company": self.company,
            "owner": self.user, "requester_employee": self.employee,
            "workflow_definition": self.definition, "request_type": "اصلاح تردد",
            "subject": "اصلاح تردد", "status": "Completed", **overrides,
        }).insert()
        # Frappe stamps owner from the inserting session, even when supplied in the payload.
        request.db_set("owner", overrides.get("owner", self.user))
        request.reload()
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Request", request.name,
                                            ["owner", "company", "requester_employee"]),
                         (overrides.get("owner", self.user), overrides.get("company", self.company),
                          overrides.get("requester_employee", self.employee)))
        return request

    def punch(self, kind="missing_entry", **extra):
        return {"date": self.day, "kind": kind, "in_time": "08:05", "out_time": "01:20",
                "reason": "", **extra}

    def assert_punch(self, result, log_type, timestamp):
        self.assertEqual((result.status, result.doctype, result.reason),
                         ("Created", "Employee Checkin", ""))
        doc = frappe.get_doc(result.doctype, result.name)
        self.assertEqual((doc.employee, doc.log_type, str(doc.time), doc.docstatus),
                         (self.employee, log_type, timestamp, 0))
        self.assertIsNone(doc.shift)
        self.assertEqual(doc.offshift, 1)
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 1)

    def test_missing_entry_with_employee_only_caller(self):
        frappe.set_user(self.user)
        result = execution.apply(self.request, self.punch())
        self.assertEqual(frappe.session.user, self.user)
        self.assert_punch(result, "IN", f"{self.day} 08:05:00")

    def test_missing_exit_next_day(self):
        self.request.db_set("requester_employee", None)
        self.request.reload()
        result = execution.apply(self.request, self.punch("missing_exit", out_time__next_day=True))
        self.assert_punch(result, "OUT", f"{add_days(self.day, 1)} 01:20:00")

    def test_both_review_kinds_preserve_original_checkin(self):
        original = frappe.get_doc({
            "doctype": "Employee Checkin", "employee": self.employee, "log_type": "IN",
            "time": f"{self.day} 08:00:00",
        }).insert()
        before = original.reload().as_dict()
        for kind, reason in [
            ("correct_recorded_time", "نیاز به اقدام HR؛ اصلاح ساعت ثبت‌شده باید با بررسی رکورد اصلی انجام شود."),
            ("other", "نیاز به اقدام HR؛ نوع عملیات برای سایر موارد مشخص نشده است."),
        ]:
            with self.subTest(kind=kind):
                result = execution.apply(self.request, {"date": self.day, "kind": kind})
                self.assertEqual((result.status, result.doctype, result.name, result.reason),
                                 ("needs_review", None, None, reason))
                self.assertEqual(original.reload().as_dict(), before)
                self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 1)
                self.assertEqual(frappe.db.count("Attendance Request", {"employee": self.employee}), 0)

    def test_duplicate_checkin_has_persian_failure_and_preserves_original(self):
        first = execution.apply(self.request, self.punch())
        before = frappe.get_doc(first.doctype, first.name).as_dict()
        with self.assertRaisesRegex(frappe.ValidationError,
                                    "برای این کارمند تردد با همین زمان و نوع قبلاً ثبت شده است."):
            execution.apply(self.request, self.punch())
        self.assertEqual(frappe.get_doc(first.doctype, first.name).as_dict(), before)
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 1)

    def test_other_time_and_log_type_are_not_duplicate(self):
        execution.apply(self.request, self.punch())
        execution.apply(self.request, self.punch(in_time="08:06"))
        execution.apply(self.request, self.punch("missing_exit", out_time="08:05"))
        rows = frappe.get_all("Employee Checkin", filters={"employee": self.employee},
                              fields=["log_type", "time"], order_by="time, log_type")
        self.assertEqual([(r.log_type, str(r.time)) for r in rows], [
            ("IN", f"{self.day} 08:05:00"), ("OUT", f"{self.day} 08:05:00"),
            ("IN", f"{self.day} 08:06:00"),
        ])

    def test_inactive_employee_is_rejected_for_every_kind(self):
        frappe.db.set_value("Employee", self.employee, "status", "Inactive")
        for kind in ["missing_entry", "missing_exit", "correct_recorded_time", "other"]:
            with self.subTest(kind=kind), self.assertRaisesRegex(
                frappe.ValidationError, "پرونده پرسنلی درخواست‌دهنده فعال نیست.",
            ):
                execution.apply(self.request, self.punch(kind))
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 0)

    def test_employee_must_belong_to_request_owner_and_company(self):
        token = frappe.generate_hash(length=8)
        other_company = frappe.get_doc({
            "doctype": "Company", "company_name": f"Attendance other {token}", "abbr": token,
            "country": "United States", "default_currency": "USD",
            "chart_of_accounts": "Standard", "enable_perpetual_inventory": 0,
        }).insert().name
        for override in [{"owner": "Administrator"}, {"company": other_company}]:
            request = self.create_request(**override)
            with self.subTest(override=override), self.assertRaisesRegex(
                frappe.ValidationError, "پرونده پرسنلی درخواست‌دهنده ثبت نشده است.",
            ):
                execution.apply(request, self.punch())
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 0)

    def test_required_geolocation_has_persian_failure(self):
        settings = frappe.get_single("HR Settings")
        settings.allow_geolocation_tracking = 1
        settings.save()
        with self.assertRaisesRegex(frappe.ValidationError,
                                    "ثبت تردد به موقعیت مکانی نیاز دارد؛ درخواست باید توسط منابع انسانی بررسی شود."):
            execution.apply(self.request, self.punch())
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 0)

    def test_selected_employee_must_match_owner_without_falling_back(self):
        other = frappe.get_doc({
            "doctype": "Employee", "first_name": "کارمند دیگر", "company": self.company,
            "status": "Active", "gender": "Male", "date_of_birth": "1990-01-01",
            "date_of_joining": add_days(nowdate(), -365), "create_user_permission": 0,
        }).insert()
        self.request.db_set("requester_employee", other.name)
        self.request.reload()
        # The owner also has a valid active Employee; a mismatched explicit selection must fail.
        with self.assertRaisesRegex(frappe.ValidationError,
                                    "پرونده پرسنلی درخواست‌دهنده ثبت نشده است."):
            execution.apply(self.request, self.punch())
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 0)
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": other.name}), 0)

    def test_invalid_input_cannot_create_a_checkin(self):
        with self.assertRaisesRegex(ValueError, "ساعت ورود پیشنهادی معتبر نیست."):
            execution.apply(self.request, self.punch(in_time="25:00"))
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), 0)
        self.assertLess(getdate(self.day), getdate())
