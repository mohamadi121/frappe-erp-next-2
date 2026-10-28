"""Integration tests for Salary Change Orders API (template builder, issuance, workflow, and payroll application)."""

import json
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

    def test_save_requires_real_revision_and_rejects_final_or_pending_edits(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)
        emp = employee_a()
        req_id = f"req-{uuid4().hex[:8]}"
        saved = api.save_salary_change_order(
            company=comp,
            request_id=req_id,
            employee=emp,
            effective_date=nowdate(),
            reason="annual",
            description="حکم سالانه",
        )
        order_name = saved["data"]["name"]
        rev = saved["data"]["revision"]

        # 1. Revision 0 is rejected on existing order
        with self.assertRaises(frappe.ValidationError):
            api.save_salary_change_order(
                company=comp,
                request_id=f"r0-{uuid4().hex[:8]}",
                order=order_name,
                revision=0,
                employee=emp,
                effective_date=nowdate(),
            )

        # 2. Mismatched revision is rejected
        with self.assertRaises(frappe.ValidationError):
            api.save_salary_change_order(
                company=comp,
                request_id=f"rwrong-{uuid4().hex[:8]}",
                order=order_name,
                revision=rev + 5,
                employee=emp,
                effective_date=nowdate(),
            )

        # 3. Editing in pending state is rejected
        rev_res = api.send_salary_change_order_for_review(
            name=order_name, revision=rev, request_id=f"rev-{uuid4().hex[:8]}"
        )
        with self.assertRaises(frappe.ValidationError):
            api.save_salary_change_order(
                company=comp,
                request_id=f"edit-pending-{uuid4().hex[:8]}",
                order=order_name,
                revision=rev_res["data"]["revision"],
                employee=emp,
                effective_date=nowdate(),
            )

        # 4. Editing in final state is rejected
        app_res = api.approve_salary_change_order(
            name=order_name, revision=rev_res["data"]["revision"], request_id=f"app-{uuid4().hex[:8]}"
        )
        with self.assertRaises(frappe.ValidationError):
            api.save_salary_change_order(
                company=comp,
                request_id=f"edit-final-{uuid4().hex[:8]}",
                order=order_name,
                revision=app_res["data"]["revision"],
                employee=emp,
                effective_date=nowdate(),
            )

    def test_approval_without_workflow_event_cannot_finalize(self):
        from asoud_erp.api.v1.workflow_runtime import complete_workflow_task
        from asoud_erp.integration_tests.request_fixtures import make_definition

        comp = company()
        frappe.set_user("Administrator")
        definition, stages = make_definition(comp, fields=[])
        approval = next(stage for stage in stages.values() if stage.stage_type == "Approval")
        config = json.loads(approval.config_json)
        config.update(assignment_type="Role", approver_roles=["System Manager"])
        frappe.db.set_value("ASOUD Workflow Stage", approval.name, "config_json", json.dumps(config))

        frappe.set_user(HR_MANAGER_USER)
        template = default_template()
        template["workflow"] = definition
        api.save_salary_change_order_template(comp, 0, template)
        api.publish_salary_change_order_template(comp, 0)

        emp = employee_a()
        req_id = f"wf-order-{uuid4().hex[:8]}"
        saved = api.save_salary_change_order(
            company=comp,
            request_id=req_id,
            employee=emp,
            effective_date=nowdate(),
            reason="promotion",
            description="حکم ارتقا با گردش کار",
        )
        order_name = saved["data"]["name"]
        pending = api.send_salary_change_order_for_review(
            name=order_name, revision=saved["data"]["revision"], request_id=f"send-{uuid4().hex[:8]}"
        )
        self.assertEqual(pending["data"]["status"], "pending")
        self.assertTrue(pending["data"].get("workflow_instance"))

        # Direct approval without completing the workflow event MUST FAIL and cannot finalize
        with self.assertRaises(frappe.ValidationError):
            api.approve_salary_change_order(
                name=order_name, revision=pending["data"]["revision"], request_id=f"app-{uuid4().hex[:8]}"
            )
        order_check = api.get_salary_change_order(order_name)["data"]
        self.assertEqual(order_check["status"], "pending")
        self.assertFalse(order_check.get("number"))

        # Real workflow completion triggers on_instance_update and finalizes the order
        instance = pending["data"]["workflow_instance"]
        task = frappe.db.get_value(
            "ASOUD Workflow Task",
            {"workflow_instance": instance, "status": "Open"},
            ["name", "assigned_to"],
            as_dict=True,
        )
        self.assertTrue(task)
        frappe.set_user(task.assigned_to or "Administrator")
        complete_workflow_task(task.name, "Approve", comment="تأیید شد")

        finalized = api.get_salary_change_order(order_name)["data"]
        self.assertEqual(finalized["status"], "final")
        self.assertTrue(finalized["number"].startswith("SAL-"))

    def test_concurrent_finalizations_never_share_a_number(self):
        from asoud_erp.services.salary_change_order_workflow import _finalize

        comp = company()
        order_data_1 = {"company": comp, "status": "pending"}
        order_data_2 = {"company": comp, "status": "pending"}
        _finalize(order_data_1)
        _finalize(order_data_2)

        self.assertTrue(order_data_1["number"].startswith("SAL-"))
        self.assertTrue(order_data_2["number"].startswith("SAL-"))
        self.assertNotEqual(order_data_1["number"], order_data_2["number"])
