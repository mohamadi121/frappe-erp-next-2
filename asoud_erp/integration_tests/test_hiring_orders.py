"""Integration tests for Hiring Orders API (template builder and issuance)."""

import json
from uuid import uuid4

import frappe
from frappe.utils import nowdate

from asoud_erp.api.v1 import hiring_orders as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    PERSONNEL_USER,
    SECOND_COMPANY,
    setup_tenancy,
)
from asoud_erp.integration_tests.test_payroll import STRUCTURE, payroll_employee, setup_payroll
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
        self.assertEqual(reviewed["data"]["status"], "final")
        self.assertEqual(reviewed["data"]["status_label"], "نهایی")

        # Print
        print_data = api.print_hiring_order(name=order_name)
        self.assertFalse(print_data["data"]["draft_banner"])
        self.assertNotIn("پیش‌نویس ـ فاقد اعتبار نهایی", print_data["data"]["html"])
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
        self.assertEqual(result["payroll_snapshot"], {})
        frappe.set_user("Administrator")
        rows = api.get_hiring_order(result["name"])["data"]["payroll_snapshot"]["rows"]
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

    def _workflow_order(self, workflow=None):
        frappe.set_user(HR_MANAGER_USER)
        template = default_template()
        if workflow:
            template["workflow"] = workflow
        saved = api.save_hiring_order_template(company=company(), template=template)["data"]
        api.publish_hiring_order_template(company=company(), revision=saved["revision"])
        employee = api.list_hiring_order_people(company=company())["data"][0]["name"]
        return api.save_hiring_order(company=company(), request_id=uuid4().hex,
                                     employee=employee, effective_date=nowdate())["data"]

    def test_no_workflow_uses_hr_direct_issuance_policy_once(self):
        order = self._workflow_order()
        frappe.set_user(HR_USER)
        key = uuid4().hex
        final = api.send_hiring_order_for_review(order["name"], order["revision"], key)["data"]
        self.assertEqual(final["status"], "final")
        self.assertTrue(final["number"].startswith("HIRE-"))
        self.assertEqual(final["issue_date"], nowdate())
        self.assertEqual(final["template_snapshot"], order["template_snapshot"])
        self.assertEqual(final["payroll_snapshot"], order["payroll_snapshot"])
        self.assertFalse(api.print_hiring_order(order["name"])["data"]["draft_banner"])
        retry = api.send_hiring_order_for_review(order["name"], order["revision"], key)["data"]
        self.assertEqual((retry["number"], retry["revision"]), (final["number"], final["revision"]))
        with self.assertRaises(frappe.ValidationError):
            api.send_hiring_order_for_review(order["name"], final["revision"], uuid4().hex)

    def test_real_workflow_approval_finalizes_but_rejection_does_not(self):
        from asoud_erp.api.v1.workflow_runtime import complete_workflow_task

        frappe.set_user("Administrator")
        definition, stages = make_definition(company(), fields=[])
        approval = next(stage for stage in stages.values() if stage.stage_type == "Approval")
        config = json.loads(approval.config_json)
        config.update(assignment_type="Role", approver_roles=["System Manager"])
        frappe.db.set_value("ASOUD Workflow Stage", approval.name, "config_json", json.dumps(config))
        for action, expected in (("Approve", "final"), ("Reject", "rejected")):
            order = self._workflow_order(definition)
            stored_payroll = json.loads(frappe.db.get_value("ASOUD Form Entry", order["name"], "values_json"))["payroll_snapshot"]
            key = uuid4().hex
            pending = api.send_hiring_order_for_review(order["name"], order["revision"], key)["data"]
            self.assertEqual(pending["status"], "pending")
            self.assertFalse(pending["number"])
            instance = pending["workflow_instance"]
            retry = api.send_hiring_order_for_review(order["name"], order["revision"], key)["data"]
            self.assertEqual(retry["workflow_instance"], instance)
            task = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": instance, "status": "Open", "assigned_to": ["!=", HR_MANAGER_USER],
            }, ["name", "assigned_to"], as_dict=True)
            self.assertTrue(task)
            frappe.set_user(task.assigned_to)
            complete_workflow_task(task.name, action, comment="بررسی انجام شد")
            result = api.get_hiring_order(order["name"])["data"]
            self.assertEqual(result["status"], expected)
            self.assertEqual(bool(result["number"]), action == "Approve")
            self.assertEqual(result["template_snapshot"], order["template_snapshot"])
            self.assertEqual(result["payroll_snapshot"], stored_payroll)

    def test_workflow_without_approval_completes_through_real_engine(self):
        frappe.set_user("Administrator")
        definition, _ = make_definition(company(), approvals=0, fields=[])
        order = self._workflow_order(definition)
        result = api.send_hiring_order_for_review(order["name"], order["revision"], uuid4().hex)["data"]
        self.assertEqual(result["status"], "final")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", result["workflow_instance"], "status"), "Completed")
        self.assertTrue(result["number"])

    def test_configured_unavailable_workflow_never_falls_back_to_direct_issue(self):
        frappe.set_user("Administrator")
        definition, _ = make_definition(company(), fields=[])
        order = self._workflow_order(definition)
        frappe.db.set_value("ASOUD Workflow Definition", definition, "status", "Draft")
        with self.assertRaises(frappe.ValidationError):
            api.send_hiring_order_for_review(order["name"], order["revision"], uuid4().hex)
        result = api.get_hiring_order(order["name"])["data"]
        self.assertEqual(result["status"], "draft")
        self.assertFalse(result["number"])

    def test_component_formulas_use_native_payroll_at_effective_date_without_saving_slips(self):
        from frappe.utils import add_days, get_first_day

        from asoud_erp.api.v1.payroll import create_salary_structure_assignment

        frappe.set_user("Administrator")
        comp = company()
        setup_payroll(comp)
        _, employee, _ = payroll_employee(comp)
        first = get_first_day(nowdate())
        changed = str(add_days(first, 14))
        create_salary_structure_assignment(employee, STRUCTURE, str(first), 30_000_000)
        create_salary_structure_assignment(employee, STRUCTURE, changed, 50_000_000)
        absent_component = frappe.get_doc({
            "doctype": "Salary Component", "salary_component": f"ASOUD Missing {uuid4().hex[:8]}",
            "salary_component_abbr": f"M{uuid4().hex[:5]}", "type": "Earning",
        }).insert().name
        template = default_template()
        template["payroll_rows"] = [
            {"id": "computed", "title": "حقوق محاسبه‌شده", "period": "monthly", "field_ref": "component.ASOUD Basic"},
            {"id": "deduction", "title": "بیمه", "period": "monthly", "field_ref": "component.ASOUD Insurance"},
            {"id": "missing", "title": "فاقد منبع", "period": "monthly", "field_ref": f"component.{absent_component}"},
        ]
        saved = api.save_hiring_order_template(company=comp, template=template)["data"]
        api.publish_hiring_order_template(company=comp, revision=saved["revision"])
        before = frappe.db.count("Salary Slip", {"employee": employee})
        for effective, expected in ((str(first), 30_000_000), (changed, 50_000_000)):
            payroll = api.get_hiring_order_payroll(comp, employee, effective)["data"]
            rows = {row["id"]: row for row in payroll["rows"]}
            self.assertEqual(rows["computed"]["amount"], expected)
            self.assertEqual(rows["deduction"]["amount"], expected * 7 / 100)
            self.assertEqual(rows["computed"]["state"], "available")
            self.assertIsNone(rows["missing"]["amount"])
            self.assertEqual(rows["missing"]["message"], "اطلاعات موجود نیست")
        absent = api.get_hiring_order_payroll(comp, employee, str(add_days(first, -1)))["data"]["rows"]
        self.assertTrue(all(row["amount"] is None for row in absent))
        self.assertTrue(all(row["message"] == "اطلاعات موجود نیست" for row in absent))
        issued = api.save_hiring_order(company=comp, employee=employee, effective_date=changed,
                                      request_id=uuid4().hex)["data"]
        self.assertEqual(issued["payroll_snapshot"]["rows"][0]["amount"], 50_000_000)
        self.assertEqual(frappe.db.count("Salary Slip", {"employee": employee}), before)
