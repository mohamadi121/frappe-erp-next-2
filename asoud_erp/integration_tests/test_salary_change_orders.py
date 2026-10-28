"""Integration tests for Salary Change Orders API (template builder, issuance, workflow, and payroll application)."""

from uuid import uuid4

import frappe
from frappe.utils import nowdate

from asoud_erp.api.v1 import salary_change_orders as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    MANAGER_USER,
    SECOND_COMPANY,
    setup_tenancy,
)
from asoud_erp.services.salary_change_orders import default_template


class TestSalaryChangeOrders(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

        comp = company()
        if not frappe.db.exists("Employee", {"user_id": EMPLOYEE_A_USER, "company": comp}):
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "پرسنل",
                "last_name": "حقوقی",
                "user_id": EMPLOYEE_A_USER,
                "company": comp,
                "status": "Active",
                "gender": "Male",
                "date_of_birth": "1990-01-01",
                "date_of_joining": nowdate(),
            })
            emp.flags.ignore_permissions = True
            emp.insert()

    def test_template_lifecycle(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        tpl = default_template()
        saved = api.save_salary_change_order_template(company=comp, revision=0, template=tpl)
        self.assertEqual(saved["data"]["template"]["articles"][0]["id"], "employee_details")

        pub = api.publish_salary_change_order_template(
            company=comp, revision=saved["data"]["revision"]
        )
        self.assertGreaterEqual(pub["data"]["revision"], 1)

        active = api.get_salary_change_order_template(company=comp)
        self.assertIsNotNone(active["data"]["template"])
        self.assertEqual(active["data"]["template"]["revision"], pub["data"]["revision"])

    def test_draft_does_not_change_live_salary_and_apply_only_after_approval(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        api.publish_salary_change_order_template(company=comp, revision=0)
        people = api.list_salary_change_order_people(company=comp)
        self.assertTrue(len(people["data"]) > 0)
        emp_id = people["data"][0]["name"]

        # Initial assignments count for this employee
        initial_assignments = frappe.get_all(
            "Salary Structure Assignment",
            filters={"employee": emp_id, "company": comp},
        )
        initial_count = len(initial_assignments)

        req_id = f"sal-req-{uuid4().hex[:8]}"
        saved = api.save_salary_change_order(
            company=comp,
            request_id=req_id,
            employee=emp_id,
            effective_date=nowdate(),
            reason="annual",
            description="افزایش سنواتی آزمایشی",
            comparison_rows=[
                {
                    "id": "base_salary",
                    "title": "حقوق پایه",
                    "period": "monthly",
                    "old_ref": "payroll.base_salary",
                    "new_ref": "document.new.base_salary",
                    "previous_amount": 200000000,
                    "new_amount": 240000000,
                }
            ],
        )
        order_name = saved["data"]["name"]
        self.assertEqual(saved["data"]["status"], "draft")
        self.assertEqual(saved["data"]["application_status"], "not_applied")

        # CRITICAL TEST: Live salary must NOT have changed by draft or preview
        after_draft_assignments = frappe.get_all(
            "Salary Structure Assignment",
            filters={"employee": emp_id, "company": comp},
        )
        self.assertEqual(len(after_draft_assignments), initial_count)

        # Print preview must also not alter live salary
        print_res = api.print_salary_change_order(name=order_name)
        self.assertTrue(print_res["data"]["draft_banner"])
        self.assertIn("پیش‌نویس ـ فاقد اعتبار نهایی", print_res["data"]["html"])

        # Attempt to apply to payroll while still draft MUST FAIL
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.ValidationError):
            api.apply_salary_change_order_to_payroll(
                name=order_name, operation_id=f"op-{uuid4().hex[:8]}"
            )

        # Send for review
        frappe.set_user(HR_MANAGER_USER)
        rev = api.send_salary_change_order_for_review(
            name=order_name, revision=saved["data"]["revision"], request_id=f"rev-{req_id}"
        )
        self.assertEqual(rev["data"]["status"], "pending")

        # Attempt to apply to payroll while pending MUST ALSO FAIL
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.ValidationError):
            api.apply_salary_change_order_to_payroll(
                name=order_name, operation_id=f"op-{uuid4().hex[:8]}"
            )

        # Approve order
        frappe.set_user(HR_MANAGER_USER)
        app = api.approve_salary_change_order(
            name=order_name, revision=rev["data"]["revision"], request_id=f"app-{req_id}"
        )
        self.assertEqual(app["data"]["status"], "final")
        self.assertTrue(app["data"]["number"].startswith("SAL-"))

        # Non-payroll user cannot apply
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            api.apply_salary_change_order_to_payroll(
                name=order_name, operation_id=f"op-{uuid4().hex[:8]}"
            )

        # Authorized payroll user applies change
        frappe.set_user(MANAGER_USER)
        op_id = f"op-{uuid4().hex[:8]}"
        applied = api.apply_salary_change_order_to_payroll(
            name=order_name, operation_id=op_id
        )
        self.assertEqual(applied["data"]["application_status"], "applied")
        self.assertEqual(applied["data"]["applied_operation_id"], op_id)

        # Idempotency test: repeating with same operation_id does not fail and returns applied state
        applied_again = api.apply_salary_change_order_to_payroll(
            name=order_name, operation_id=op_id
        )
        self.assertEqual(applied_again["data"]["application_status"], "applied")

    def test_employee_access_denied(self):
        comp = company()
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            api.list_salary_change_orders(company=comp)

    def test_cross_office_access_denied(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            api.list_salary_change_orders(company=SECOND_COMPANY)

    def test_save_rejects_cross_company_and_invalid_type_order(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)
        emp = employee_a()
        req_id = f"req-{uuid4().hex[:8]}"
        saved = api.save_salary_change_order(
            company=comp,
            request_id=req_id,
            employee=emp,
            effective_date=nowdate(),
            reason="promotion",
            description="حکم ارتقا",
        )
        order_name = saved["data"]["name"]

        with self.assertRaises(frappe.PermissionError):
            api.save_salary_change_order(
                company=SECOND_COMPANY,
                request_id=f"cross-{uuid4().hex[:8]}",
                order=order_name,
                revision=saved["data"]["revision"],
                employee=emp,
                effective_date=nowdate(),
            )

        frappe.db.set_value("ASOUD Form Entry", order_name, "reference_doctype", "ASOUD Other Document")
        with self.assertRaises(frappe.PermissionError):
            api.save_salary_change_order(
                company=comp,
                request_id=f"type-{uuid4().hex[:8]}",
                order=order_name,
                revision=saved["data"]["revision"],
                employee=emp,
                effective_date=nowdate(),
            )
