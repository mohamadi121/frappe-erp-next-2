"""Calendar personal scope and organization holiday integration tests."""

import frappe

from asoud_erp.api.v1 import calendar
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.tenancy import HR_MANAGER_USER, MANAGER_USER, setup_tenancy


class TestCalendar(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

    def test_personal_scope_lifecycle_and_company_isolation(self):
        # 1. Manager saves a personal reminder
        frappe.set_user(MANAGER_USER)
        client_id = "a" * 24
        mutation_id = "b" * 24
        calendar.save_personal(
            company=self.company,
            payload={
                "id": client_id,
                "mutation_id": mutation_id,
                "kind": "Reminder",
                "title": "جلسه برنامه‌ریزی فصلی",
                "date": "2026-10-25",
                "time": "10:30",
            },
        )

        # 2. Verify reminder is present in calendar items
        items = calendar.get_calendar(company=self.company, start="2026-10-25", end="2026-10-25")["data"]["items"]
        matched = [it for it in items if it["id"] == client_id]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["title"], "جلسه برنامه‌ریزی فصلی")
        self.assertEqual(matched[0]["time"], "10:30")
        self.assertFalse(matched[0]["done"])

        # 3. Update reminder to completed
        calendar.save_personal(
            company=self.company,
            payload={
                "id": client_id,
                "mutation_id": "c" * 24,
                "kind": "Reminder",
                "title": "جلسه برنامه‌ریزی فصلی",
                "date": "2026-10-25",
                "time": "10:30",
                "done": True,
                "version": matched[0]["version"],
            },
        )
        updated_items = calendar.get_calendar(company=self.company, start="2026-10-25", end="2026-10-25")["data"]["items"]
        updated_matched = [it for it in updated_items if it["id"] == client_id]
        self.assertTrue(updated_matched[0]["done"])

        # 4. Cross-company access is refused
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.second, start="2026-10-25", end="2026-10-25")
        with self.assertRaises(frappe.PermissionError):
            calendar.save_personal(
                company=self.second,
                payload={"id": "d" * 24, "mutation_id": "e" * 24, "kind": "Reminder", "title": "تست", "date": "2026-10-25"},
            )

    def test_holiday_management_and_role_permissions(self):
        # 1. HR Manager saves an organization holiday
        frappe.set_user(HR_MANAGER_USER)
        holiday_id = "f" * 24
        calendar.save_holiday(
            company=self.company,
            payload={
                "id": holiday_id,
                "title": "تعطیلی سالگرد تأسیس سازمان",
                "date": "2026-11-01",
                "end_date": "2026-11-01",
            },
        )

        # 2. Holiday appears in calendar response
        frappe.set_user(MANAGER_USER)
        data = calendar.get_calendar(company=self.company, start="2026-11-01", end="2026-11-01")["data"]
        holiday_titles = [h["title"] for h in data["items"] if h.get("kind") == "Organization"]
        self.assertIn("تعطیلی سالگرد تأسیس سازمان", holiday_titles)

        # 3. Non-manager employee cannot save holiday
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            calendar.save_holiday(
                company=self.company,
                payload={
                    "id": "1" * 24,
                    "title": "تعطیلی غیرمجاز",
                    "date": "2026-11-02",
                    "end_date": "2026-11-02",
                },
            )
