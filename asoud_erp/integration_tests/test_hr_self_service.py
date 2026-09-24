import frappe
from frappe.utils import add_days, get_first_day, nowdate

from asoud_erp.api.v1 import hr_self_service as hr
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    EXPENSE_TYPE,
    LEAVE_TYPE,
    APITestCase,
)


def next_weekday(days: int) -> str:
    date = add_days(nowdate(), days)
    while frappe.utils.getdate(date).weekday() >= 5:
        date = add_days(date, 1)
    return str(date)


class TestHRSelfService(APITestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user(EMPLOYEE_USER)

    def test_leave_balance_apply_and_approve(self):
        summary = hr.get_my_leave_summary()["data"]
        balance = next(row for row in summary["balances"] if row["leave_type"] == LEAVE_TYPE)
        self.assertEqual(balance["total_leaves"], 10)
        self.assertEqual(summary["leave_approver"], APPROVER_USER)
        day = next_weekday(3)
        self.assertEqual(hr.get_leave_days(LEAVE_TYPE, day, day)["data"]["days"], 1)
        leave = hr.create_leave_application(LEAVE_TYPE, day, day, reason="کار شخصی")["data"]
        self.assertEqual((leave["status"], leave["leave_approver"]), ("Open", APPROVER_USER))
        mine = hr.list_my_leave_applications()["data"]
        self.assertIn(leave["name"], [row.name for row in mine])
        frappe.set_user(APPROVER_USER)
        self.assertIn(leave["name"], [row.name for row in hr.list_leave_approvals()["data"]])
        approved = hr.approve_leave_application(leave["name"])["data"]
        self.assertEqual((approved["status"], approved["docstatus"]), ("Approved", 1))

    def test_employee_cannot_approve_own_leave(self):
        day = next_weekday(10)
        leave = hr.create_leave_application(LEAVE_TYPE, day, day)["data"]
        with self.assertRaises(frappe.PermissionError):
            hr.approve_leave_application(leave["name"])
        self.assertEqual(hr.cancel_leave_application(leave["name"])["data"]["status"], "Cancelled")

    def test_checkin(self):
        entry = hr.create_checkin("IN", latitude=35.7, longitude=51.4)["data"]
        self.assertEqual(entry["log_type"], "IN")
        self.assertEqual(hr.list_my_checkins()["data"][0].name, entry["name"])
        with self.assertRaises(frappe.ValidationError):
            hr.create_checkin("LUNCH")

    def test_mission_advance_and_expense(self):
        mission = hr.create_travel_request(
            "Domestic", "ASOUD Mission",
            [{"travel_from": "تهران", "travel_to": "مشهد", "departure_date": str(add_days(nowdate(), 5))}],
            description="بازدید شعبه")["data"]
        self.assertEqual(mission["travel_type"], "Domestic")
        advance = hr.create_employee_advance(5_000_000, "مساعده")["data"]
        self.assertEqual(advance["advance_amount"], 5_000_000)
        self.assertEqual(len(hr.list_my_employee_advances()["data"]), 1)
        claim = hr.create_expense_claim([{"expense_type": EXPENSE_TYPE, "amount": 120_000,
                                          "expense_date": str(get_first_day(nowdate()))}])["data"]
        self.assertEqual((claim["total_claimed_amount"], claim["docstatus"]), (120_000, 0))

    def test_user_without_employee_is_refused(self):
        frappe.set_user("Administrator")
        frappe.db.set_value("Employee", {"user_id": ACCOUNTANT_USER}, "status", "Left")
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            hr.get_my_leave_summary()
