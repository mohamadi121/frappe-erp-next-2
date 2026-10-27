"""Integration tests for Hiring Orders API (template builder and issuance)."""

from uuid import uuid4

import frappe
from frappe.utils import nowdate

from asoud_erp.api.v1 import hiring_orders as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    setup_tenancy,
)
from asoud_erp.services.hiring_orders import default_template


class TestHiringOrders(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

        comp = company()
        if not frappe.db.exists("Employee", {"user_id": EMPLOYEE_A_USER, "company": comp}):
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "پرسنل",
                "last_name": "آزمایشی",
                "user_id": EMPLOYEE_A_USER,
                "company": comp,
                "status": "Active",
                "gender": "Male",
                "date_of_birth": "1992-01-01",
                "date_of_joining": nowdate(),
            })
            emp.flags.ignore_permissions = True
            emp.insert()

    def test_hiring_order_template_lifecycle(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        tpl = default_template()
        saved = api.save_hiring_order_template(company=comp, revision=0, template=tpl)
        self.assertEqual(saved["data"]["template"]["articles"][0]["id"], "employee_details")

        pub = api.publish_hiring_order_template(company=comp, revision=saved["data"]["revision"])
        self.assertEqual(pub["data"]["revision"], 1)

        active = api.get_hiring_order_template(company=comp)
        self.assertIsNotNone(active["data"]["template"])
        self.assertEqual(active["data"]["template"]["revision"], 1)

    def test_hiring_order_issuance_lifecycle(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)

        api.publish_hiring_order_template(company=comp, revision=0)

        people = api.list_hiring_order_people(company=comp)
        self.assertTrue(len(people["data"]) > 0)
        emp_id = people["data"][0]["name"]

        req_id = f"hire-req-{uuid4().hex[:8]}"
        saved = api.save_hiring_order(
            company=comp,
            request_id=req_id,
            employee=emp_id,
            effective_date=nowdate(),
            values={
                "employment": "تمام‌وقت",
                "unit": "اداری",
                "position": "کارشناس اداری",
                "location": "دفتر مرکزی",
                "note": "توضیحات تست",
            },
            payroll_rows=[
                {"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "amount": 100000000},
            ],
        )
        order_name = saved["data"]["name"]
        self.assertEqual(saved["data"]["status"], "draft")
        self.assertEqual(saved["data"]["status_label"], "پیش‌نویس")

        # Idempotency: same request_id returns existing record
        dup = api.save_hiring_order(
            company=comp,
            request_id=req_id,
            employee=emp_id,
            effective_date=nowdate(),
            values={},
        )
        self.assertEqual(dup["data"]["name"], order_name)

        orders = api.list_hiring_orders(company=comp)
        self.assertTrue(any(row["name"] == order_name for row in orders["data"]["items"]))

        # Send for review
        reviewed = api.send_hiring_order_for_review(name=order_name, revision=saved["data"]["revision"], request_id=f"rev-{req_id}")
        self.assertEqual(reviewed["data"]["status"], "pending")
        self.assertEqual(reviewed["data"]["status_label"], "در جریان")

        # Print
        print_data = api.print_hiring_order(name=order_name)
        self.assertTrue(print_data["data"]["draft_banner"])
        self.assertIn("پیش‌نویس ـ فاقد اعتبار نهایی", print_data["data"]["html"])
        self.assertIn("حکم استخدام", print_data["data"]["html"])

    def test_hiring_order_employee_access_denied(self):
        comp = company()
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            api.list_hiring_orders(company=comp)
