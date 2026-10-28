"""Integration tests for Employment Certificates API."""

import frappe

from asoud_erp.api.v1 import employment_certificates as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    setup_tenancy,
)


class TestEmploymentCertificates(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

        # Ensure employee exists and is active
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

        # Save draft
        draft_clauses = [
            {"id": "recipient", "title": "مخاطب", "body": "به: {{certificate.addressee_name}}", "enabled": True},
            {"id": "main_body", "title": "متن", "body": "{{employee.employee_name}} شاغل در {{company.company_name}}", "enabled": True},
            {"id": "purpose", "title": "هدف", "body": "جهت {{certificate.purpose}}", "enabled": True},
        ]
        save_res = api.save_template_draft(
            company=comp,
            revision=initial_rev,
            clauses=draft_clauses,
            salary_enabled=False,
            salary_rows=[],
        )
        assert save_res["ok"] is True
        new_rev = save_res["data"]["revision"]
        assert new_rev > initial_rev

        # Publish template
        pub_res = api.publish_template(company=comp, revision=new_rev)
        assert pub_res["ok"] is True
        assert pub_res["data"]["status"] == "Published"

    def test_certificate_issuance_flow(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        emp_name = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER}, "name")
        assert emp_name is not None

        # 1. Save draft
        draft_res = api.save_draft(
            company=comp,
            employee=emp_name,
            addressee_type="بانک",
            addressee_name="بانک ملی ایران",
            purpose="دریافت تسهیلات",
            request_key="test-req-key-cert-1",
            revision=0,
            include_salary=False,
        )
        assert draft_res["ok"] is True
        cert_data = draft_res["data"]
        cert_name = cert_data["name"]
        assert cert_data["status"] == "Draft"
        assert cert_data["number"] == "—"
        assert "پیش‌نویس ـ فاقد اعتبار نهایی" in cert_data["print_html"]

        # 2. Idempotency test: repeating with same request_key returns identical data
        dup_res = api.save_draft(
            company=comp,
            employee=emp_name,
            addressee_type="بانک",
            addressee_name="بانک ملی ایران",
            purpose="دریافت تسهیلات",
            request_key="test-req-key-cert-1",
        )
        assert dup_res["ok"] is True
        assert dup_res["data"]["name"] == cert_name

        # 3. List certificates
        list_res = api.list_certificates(company=comp, query="بانک ملی", status="draft")
        assert list_res["ok"] is True
        assert any(item["name"] == cert_name for item in list_res["data"]["items"])

        # 4. Get certificate
        get_res = api.get_certificate(cert_name)
        assert get_res["ok"] is True
        assert get_res["data"]["employee"] == emp_name

        # 5. Finalize certificate
        final_res = api.finalize_certificate(
            name=cert_name,
            revision=cert_data["revision"],
            request_key="test-final-key-cert-1",
        )
        assert final_res["ok"] is True
        final_data = final_res["data"]
        assert final_data["status"] == "Final"
        assert final_data["number"] != "—"
        assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in final_data["print_html"]

    def test_inactive_employee_cannot_be_issued_certificate(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        # Create or update inactive employee
        emp = frappe.get_doc({
            "doctype": "Employee",
            "first_name": "شخص",
            "last_name": "غیرفعال",
            "company": comp,
            "status": "Left",
            "relieving_date": "2023-01-01",
            "gender": "Male",
            "date_of_birth": "1992-01-01",
            "date_of_joining": "2021-01-01",
        })
        emp.flags.ignore_permissions = True
        emp.insert()

        with self.assertRaises(frappe.ValidationError):
            api.save_draft(
                company=comp,
                employee=emp.name,
                addressee_name="بانک",
                request_key="test-inactive-key",
            )

