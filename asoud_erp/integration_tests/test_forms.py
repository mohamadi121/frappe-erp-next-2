"""Versioned forms and calendar records remain inside the caller's company."""

import frappe

from asoud_erp.api.v1 import calendar, forms
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


def schema(title="فرم آزمایشی"):
    return {
        "kind": "Request",
        "title": title,
        "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "amount", "label": "مبلغ", "type": "Money", "required": True},
            {"key": "priority", "label": "اولویت", "type": "Select", "required": True,
             "options": [{"id": "normal", "label": "عادی"}, {"id": "urgent", "label": "فوری"}]},
        ]}],
    }


class TestForms(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

    def test_draft_publish_revision_and_entry_are_company_scoped(self):
        created = forms.save_form(company=self.company, schema=schema(), client_id="a" * 24)["data"]
        self.assertEqual(created["status"], "Draft")
        self.assertEqual(forms.list_forms(company=self.company, manage=1)["data"][0]["name"], created["name"])

        published = forms.transition(name=created["name"], action="publish", expected_version=1)["data"]
        first_revision = published["active_revision"]
        self.assertEqual(published["version"], 1)

        updated_schema = schema("فرم بازبینی‌شده")
        revised = forms.save_form(name=created["name"], company=self.company, schema=updated_schema,
                                  expected_version=published["draft_version"])["data"]
        published = forms.transition(name=created["name"], action="publish",
                                     expected_version=revised["draft_version"])["data"]
        self.assertNotEqual(published["active_revision"], first_revision)
        self.assertEqual(forms.get_form(name=created["name"])["data"]["revision"], published["active_revision"])

        frappe.set_user(MANAGER_USER)
        entry = forms.submit_form(name=created["name"], revision_name=published["active_revision"],
                                  subject="ثبت آزمایشی", values={"amount": "125", "priority": "normal"},
                                  request_key="b" * 24)["data"]
        self.assertEqual(forms.get_entry(entry["name"])["data"]["values"]["priority"], "normal")
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.second)

    def test_active_employee_without_an_application_role_cannot_read_forms(self):
        user = "asoud.form-no-role@example.com"
        frappe.get_doc({"doctype": "User", "email": user, "first_name": "Form no role",
                        "send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "Employee", "first_name": "Form no role", "gender": "Male",
                        "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01",
                        "company": self.company, "status": "Active", "user_id": user,
                        "create_user_permission": 0}).insert(ignore_permissions=True)
        frappe.set_user(user)
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.company)
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.company, start="2026-10-20", end="2026-10-20")


class TestCalendarCompanyScope(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = setup_tenancy()["second"]

    def test_personal_scope_is_private_and_second_company_is_refused(self):
        frappe.set_user(MANAGER_USER)
        calendar.save_personal(company=self.company, payload={
            "id": "1" * 24, "mutation_id": "2" * 24, "kind": "Reminder", "title": "پیگیری آزمایشی",
            "date": "2026-10-20", "time": "09:00",
        })
        items = calendar.get_calendar(company=self.company, start="2026-10-20", end="2026-10-20")["data"]["items"]
        self.assertEqual([(item["id"], item["title"]) for item in items if item["id"] == "1" * 24],
                         [("1" * 24, "پیگیری آزمایشی")])
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.second, start="2026-10-20", end="2026-10-20")
