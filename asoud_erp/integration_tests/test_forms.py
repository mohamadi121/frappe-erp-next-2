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


def document_schema(title="سند آزمایشی"):
    return {
        "kind": "Document",
        "target": "Journal Entry",
        "title": title,
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "posting_date", "label": "تاریخ ثبت", "type": "Date", "native_key": "posting_date"},
                {"key": "accounts", "label": "ردیف‌ها", "type": "Table", "native_key": "accounts", "columns": [
                    {"key": "debit", "label": "مبلغ", "type": "Money", "native_key": "debit_in_account_currency"},
                ]},
            ],
        }],
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

    def test_employee_consumption_and_permission_boundaries(self):
        # 1. Active employee with only the Employee role
        emp_user = "asoud.form-employee@example.com"
        if not frappe.db.exists("User", emp_user):
            frappe.get_doc({
                "doctype": "User", "email": emp_user, "first_name": "Form employee",
                "send_welcome_email": 0, "user_type": "System User",
                "roles": [{"role": "Employee"}],
            }).insert(ignore_permissions=True)
        if not frappe.db.exists("Employee", {"user_id": emp_user}):
            frappe.get_doc({
                "doctype": "Employee", "first_name": "Form employee", "gender": "Male",
                "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01",
                "company": self.company, "status": "Active", "user_id": emp_user,
                "create_user_permission": 0,
            }).insert(ignore_permissions=True)

        # 2. User without an active Employee record in this company
        stranger_user = "asoud.form-stranger@example.com"
        if not frappe.db.exists("User", stranger_user):
            frappe.get_doc({
                "doctype": "User", "email": stranger_user, "first_name": "Form stranger",
                "send_welcome_email": 0, "user_type": "System User",
                "roles": [{"role": "Employee"}],
            }).insert(ignore_permissions=True)

        # 3. Publish a Request form and a Document form as Administrator
        frappe.set_user("Administrator")
        req_form = forms.save_form(company=self.company, schema=schema("فرم درخواست پرسنلی"), client_id="r" * 24)["data"]
        published_req = forms.transition(name=req_form["name"], action="publish", expected_version=1)["data"]

        doc_form = forms.save_form(company=self.company, schema=document_schema("فرم سند حسابداری"), client_id="d" * 24)["data"]
        published_doc = forms.transition(name=doc_form["name"], action="publish", expected_version=1)["data"]

        # 4. As an Employee-only user:
        frappe.set_user(emp_user)

        # a) CAN list published forms
        published_req_names = [f["name"] for f in forms.list_forms(company=self.company, kind="Request")["data"]]
        self.assertIn(req_form["name"], published_req_names)

        published_doc_names = [f["name"] for f in forms.list_forms(company=self.company, kind="Document")["data"]]
        self.assertIn(doc_form["name"], published_doc_names)

        # b) CAN submit a Request form and read own entries
        entry = forms.submit_form(
            name=req_form["name"],
            revision_name=published_req["active_revision"],
            subject="درخواست اداری پرسنل",
            values={"amount": "250", "priority": "urgent"},
            request_key="k" * 24,
        )["data"]
        self.assertIsNotNone(entry["name"])

        read_entry = forms.get_entry(entry["name"])["data"]
        self.assertEqual(read_entry["subject"], "درخواست اداری پرسنل")
        self.assertEqual(read_entry["values"]["amount"], "250")

        my_entries = [e["name"] for e in forms.list_my_entries(company=self.company)["data"]]
        self.assertIn(entry["name"], my_entries)

        # c) CAN use the personal calendar
        cal_res = calendar.save_personal(
            company=self.company,
            payload={
                "id": "1" * 24, "mutation_id": "2" * 24, "kind": "Reminder",
                "title": "یادآوری کارمند", "date": "2026-10-22",
            },
        )
        self.assertTrue(cal_res["data"]["saved"])
        cal_items = calendar.get_calendar(company=self.company, start="2026-10-22", end="2026-10-22")["data"]["items"]
        self.assertTrue(any(item["id"] == "1" * 24 for item in cal_items))

        # d) CANNOT call designer/management operations
        with self.assertRaises(frappe.PermissionError):
            forms.save_form(company=self.company, schema=schema("فرم غیرمجاز"), client_id="x" * 24)
        with self.assertRaises(frappe.PermissionError):
            forms.transition(name=req_form["name"], action="disable", expected_version=1)
        with self.assertRaises(frappe.PermissionError):
            forms.get_history(name=req_form["name"])
        with self.assertRaises(frappe.PermissionError):
            calendar.save_holiday(company=self.company, payload={"id": "3" * 24, "title": "تعطیلی", "date": "2026-10-22"})

        # e) CANNOT read another company's forms
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.second)
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.second, start="2026-10-22", end="2026-10-22")

        # f) For document forms: employee without native permission on target DocType is refused by ERPNext
        with self.assertRaises(frappe.PermissionError):
            forms.submit_form(
                name=doc_form["name"],
                revision_name=published_doc["active_revision"],
                subject="ثبت سند مالی",
                values={
                    "posting_date": "2026-10-22",
                    "accounts": [{"debit": "100"}],
                },
                request_key="doc-k-" + "4" * 20,
            )

        # 5. A user who is not an active employee of the company is refused
        frappe.set_user(stranger_user)
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.company)
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.company, start="2026-10-22", end="2026-10-22")


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
