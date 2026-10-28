"""Integration tests for Personnel Introduction Letters API."""

import frappe

from asoud_erp.api.v1 import personnel_introduction_letters as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    setup_tenancy,
)


class TestPersonnelIntroductionLetters(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

        emp_name = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER}, "name")
        if emp_name:
            emp = frappe.get_doc("Employee", emp_name)
            emp.status = "Active"
            emp.date_of_joining = emp.date_of_joining or "2020-01-01"
            emp.flags.ignore_permissions = True
            emp.save()

    def test_template_draft_and_publish_flow(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        res = api.get_template(company=comp)
        assert res["ok"] is True
        initial_rev = res["data"]["revision"]

        draft_clauses = [
            {"id": "recipient", "title": "مخاطب", "body": "به: {{letter.recipient}}", "enabled": True},
            {"id": "main_body", "title": "متن", "body": "{{employee.employee_name}} شاغل در {{company.company_name}}", "enabled": True},
            {"id": "purpose", "title": "هدف", "body": "جهت {{letter.purpose}}", "enabled": True},
        ]
        save_res = api.save_template_draft(
            company=comp,
            revision=initial_rev,
            clauses=draft_clauses,
            required_recipient=True,
            required_purpose=True,
            has_expiry=False,
        )
        assert save_res["ok"] is True
        new_rev = save_res["data"]["revision"]
        assert new_rev > initial_rev

        pub_res = api.publish_template(company=comp, revision=new_rev)
        assert pub_res["ok"] is True
        assert pub_res["data"]["status"] == "Published"

    def test_letter_issuance_flow(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        emp_name = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER}, "name")
        assert emp_name is not None

        # Employee options
        options_res = api.get_employee_options(company=comp)
        assert options_res["ok"] is True
        assert any(e["employee"] == emp_name for e in options_res["data"])

        # 1. Save draft
        draft_res = api.save_draft(
            company=comp,
            employee=emp_name,
            recipient_type="bank",
            bank_name="بانک تجارت",
            branch_name="شعبه مرکزی",
            purpose="افتتاح حساب",
            request_key="test-req-key-intro-1",
            revision=0,
        )
        assert draft_res["ok"] is True
        letter_data = draft_res["data"]
        letter_name = letter_data["name"]
        assert letter_data["status"] == "Draft"
        assert letter_data["number"] == "—"
        assert "پیش‌نویس ـ فاقد اعتبار نهایی" in letter_data["print_html"]
        assert "بانک تجارت ـ شعبه مرکزی" in letter_data["recipient_text"]

        # 2. Idempotency test: repeating with same request_key returns identical data
        dup_res = api.save_draft(
            company=comp,
            employee=emp_name,
            recipient_type="bank",
            bank_name="بانک تجارت",
            branch_name="شعبه مرکزی",
            purpose="افتتاح حساب",
            request_key="test-req-key-intro-1",
        )
        assert dup_res["ok"] is True
        assert dup_res["data"]["name"] == letter_name

        # 3. List letters
        list_res = api.list_letters(company=comp, query="تجارت", status="draft")
        assert list_res["ok"] is True
        assert any(item["name"] == letter_name for item in list_res["data"]["items"])

        # 4. Get letter
        get_res = api.get_letter(letter_name)
        assert get_res["ok"] is True
        assert get_res["data"]["employee"] == emp_name

        # 5. Finalize letter
        final_res = api.finalize_letter(
            name=letter_name,
            revision=letter_data["revision"],
            request_key="test-final-key-intro-1",
        )
        assert final_res["ok"] is True
        final_data = final_res["data"]
        assert final_data["status"] == "Final"
        assert final_data["number"] != "—"
        assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in final_data["print_html"]

    def test_personnel_code_is_used_in_options_snapshot_and_search(self):
        comp = company()
        employee = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER}, "name")
        code = "975310"
        frappe.db.set_value("Employee", employee, "employee_number", code)
        frappe.set_user(HR_MANAGER_USER)
        options = api.get_employee_options(company=comp)["data"]
        assert next(row for row in options if row["employee"] == employee)["employee_number"] == code
        draft = api.save_draft(
            company=comp, employee=employee, bank_name="بانک ملت",
            purpose="افتتاح حساب", request_key="personnel-code-search",
        )["data"]
        assert draft["employee_number"] == code
        assert draft["values_snapshot"]["employee"]["employee_number"] == code
        results = api.list_letters(company=comp, query="۹۷۵۳۱۰")["data"]["items"]
        assert any(row["name"] == draft["name"] for row in results)

    def test_inactive_employee_cannot_be_issued_letter(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        emp = frappe.get_doc({
            "doctype": "Employee",
            "first_name": "کارمند",
            "last_name": "سابق",
            "company": comp,
            "status": "Left",
            "relieving_date": "2023-01-01",
            "gender": "Male",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2019-01-01",
        })
        emp.flags.ignore_permissions = True
        emp.insert()

        with self.assertRaises(frappe.ValidationError):
            api.save_draft(
                company=comp,
                employee=emp.name,
                bank_name="بانک ملت",
                purpose="افتتاح حساب",
                request_key="test-inactive-intro-key",
            )
