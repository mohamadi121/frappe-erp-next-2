"""Integration tests for Hiring Orders API (template builder and issuance)."""

from uuid import uuid4

import frappe
from frappe.utils import nowdate

from asoud_erp.api.v1 import hiring_orders as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    PERSONNEL_USER,
    SECOND_COMPANY,
    setup_tenancy,
)
from asoud_erp.services.hiring_orders import default_template

HR_USER = "asoud.test-hr-user@example.com"


class TestHiringOrders(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

        comp = company()
        if not frappe.db.exists("User", HR_USER):
            user = frappe.get_doc({
                "doctype": "User",
                "email": HR_USER,
                "first_name": "کارشناس",
                "last_name": "منابع انسانی",
                "roles": [{"role": "HR User"}],
            })
            user.flags.ignore_permissions = True
            user.insert()

            perm = frappe.get_doc({
                "doctype": "User Permission",
                "user": HR_USER,
                "allow": "Company",
                "for_value": comp,
                "apply_to_all_doctypes": 1,
            })
            perm.flags.ignore_permissions = True
            perm.insert()

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

    def test_hiring_order_designer_vs_operational_permissions(self):
        comp = company()

        # Operational HR User cannot edit/publish template, gets Persian permission error
        frappe.set_user(HR_USER)
        with self.assertRaises(frappe.PermissionError) as cm_save:
            api.save_hiring_order_template(company=comp, revision=0, template=default_template())
        self.assertIn("شما اجازهٔ ویرایش یا انتشار قالب حکم استخدام را ندارید.", str(cm_save.exception))

        with self.assertRaises(frappe.PermissionError) as cm_pub:
            api.publish_hiring_order_template(company=comp, revision=0)
        self.assertIn("شما اجازهٔ ویرایش یا انتشار قالب حکم استخدام را ندارید.", str(cm_pub.exception))

        # Operational HR User CAN issue orders and list orders
        orders = api.list_hiring_orders(company=comp)
        self.assertIn("items", orders["data"])

        # HR Manager CAN edit and publish template
        frappe.set_user(HR_MANAGER_USER)
        pub = api.publish_hiring_order_template(company=comp, revision=0)
        self.assertIsNotNone(pub["data"]["template"])

    def test_hiring_order_payroll_resolution_with_components(self):
        comp = company()
        frappe.set_user(PERSONNEL_USER)

        # 1. Test catalog endpoint
        catalog = api.get_hiring_order_payroll_catalog(company=comp)
        self.assertIn("items", catalog["data"])
        field_ids = [item["field_id"] for item in catalog["data"]["items"]]
        self.assertIn("base", field_ids)
        self.assertIn("variable", field_ids)

        # Non-payroll user gets PermissionError
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError) as cm:
            api.get_hiring_order_payroll_catalog(company=comp)
        self.assertIn("شما اجازهٔ مشاهدهٔ اطلاعات حقوق را ندارید.", str(cm.exception))

        # 2. Setup template with component binding
        frappe.set_user(PERSONNEL_USER)
        components = [item for item in catalog["data"]["items"] if item["field_id"].startswith("component.")]
        self.assertTrue(components)
        component_ref = components[0]["field_id"]
        tpl = {
            "articles": default_template()["articles"],
            "payroll_rows": [
                {"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "field_ref": "base"},
                {"id": "housing", "title": "حق مسکن", "period": "monthly", "field_ref": component_ref},
                {"id": "unassigned", "title": "پاداش", "period": "yearly", "field_ref": component_ref},
            ],
        }
        saved = api.save_hiring_order_template(company=comp, revision=0, template=tpl)
        api.publish_hiring_order_template(company=comp, revision=saved["data"]["revision"])

        people = api.list_hiring_order_people(company=comp)
        emp_id = people["data"][0]["name"]

        # Call get_hiring_order_payroll
        res = api.get_hiring_order_payroll(company=comp, employee=emp_id, effective_date=nowdate())
        rows = {r["id"]: r for r in res["data"]["rows"]}
        self.assertIn("base_salary", rows)
        self.assertIn("housing", rows)
        self.assertIn("unassigned", rows)
        # Unassigned component row has state="missing", amount=None, message="اطلاعات موجود نیست", never 0
        self.assertEqual(rows["unassigned"]["state"], "missing")
        self.assertIsNone(rows["unassigned"]["amount"])
        self.assertEqual(rows["unassigned"]["message"], "اطلاعات موجود نیست")

    def test_issue_resolves_only_template_rows_and_ignores_client_amounts(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)
        api.publish_hiring_order_template(company=comp, revision=0)
        employee = api.list_hiring_order_people(company=comp)["data"][0]["name"]
        result = api.save_hiring_order(
            company=comp, request_id=uuid4().hex, employee=employee,
            effective_date="1900-01-01",
            payroll_rows=[{"id": "forged", "title": "دستکاری", "period": "monthly", "amount": 999}],
        )["data"]
        rows = result["payroll_snapshot"]["rows"]
        self.assertEqual([row["id"] for row in rows], ["base_salary"])
        self.assertIsNone(rows[0]["amount"])
        self.assertEqual(rows[0]["message"], "اطلاعات موجود نیست")

    def test_order_conflict_scope_and_snapshot_after_republish(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)
        api.publish_hiring_order_template(company=comp, revision=0)
        employee = api.list_hiring_order_people(company=comp)["data"][0]["name"]
        args = dict(company=comp, employee=employee, effective_date=nowdate())
        saved = api.save_hiring_order(request_id=uuid4().hex, **args)["data"]
        with self.assertRaises(frappe.ValidationError):
            api.save_hiring_order(request_id=uuid4().hex, order=saved["name"], revision=999, **args)
        original = saved["template_snapshot"]
        changed = default_template()
        changed["articles"][0]["body"] = "متن نسخه جدید"
        draft = api.save_hiring_order_template(company=comp, template=changed)["data"]
        api.publish_hiring_order_template(company=comp, revision=draft["revision"])
        self.assertEqual(api.get_hiring_order(saved["name"])["data"]["template_snapshot"], original)
        frappe.db.set_value("ASOUD Form Entry", saved["name"], "company", SECOND_COMPANY)
        before = frappe.db.get_value("ASOUD Form Entry", saved["name"], "values_json")
        with self.assertRaises(frappe.PermissionError):
            api.save_hiring_order(request_id=uuid4().hex, order=saved["name"], revision=saved["revision"], **args)
        self.assertEqual(frappe.db.get_value("ASOUD Form Entry", saved["name"], "values_json"), before)
