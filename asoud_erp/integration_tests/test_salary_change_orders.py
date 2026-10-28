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


def employee_a() -> str:
    comp = company()
    name = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER, "company": comp}, "name")
    if not name:
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
        name = emp.name
    return name


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

    def test_tampered_client_amounts_are_ignored_and_recomputed_server_side(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)
        emp = employee_a()

        # Seed an active salary assignment
        struct = frappe.db.get_value("Salary Structure", {"company": comp, "docstatus": 1}, "name")
        if not struct:
            st = frappe.get_doc({
                "doctype": "Salary Structure",
                "name": f"Test-Struct-{uuid4().hex[:6]}",
                "company": comp,
                "payroll_frequency": "Monthly",
                "is_active": "Yes",
                "docstatus": 1,
            })
            st.flags.ignore_permissions = True
            st.insert()
            struct = st.name

        assign = frappe.get_doc({
            "doctype": "Salary Structure Assignment",
            "employee": emp,
            "company": comp,
            "salary_structure": struct,
            "from_date": "2020-01-01",
            "base": 150000000,
            "variable": 0,
            "docstatus": 1,
        })
        assign.flags.ignore_permissions = True
        assign.insert()

        # Client sends maliciously tampered previous_amount, difference, percent, and totals
        tampered_rows = [
            {
                "id": "base_salary",
                "title": "حقوق پایه",
                "period": "monthly",
                "old_ref": "payroll.base_salary",
                "new_ref": "document.new.base_salary",
                "previous_amount": 999999999,
                "new_amount": 180000000,
                "difference": 111,
                "percent_change": 1.0,
                "percent_label": "+1.0%",
            }
        ]
        saved = api.save_salary_change_order(
            company=comp,
            request_id=f"tamper-{uuid4().hex[:8]}",
            employee=emp,
            effective_date=nowdate(),
            reason="annual",
            description="تست ارقام جعلی کاربر",
            comparison_rows=tampered_rows,
        )

        order_name = saved["data"]["name"]
        frappe.set_user(MANAGER_USER)
        order_data = api.get_salary_change_order(order_name)["data"]
        table = order_data["comparison_table"]
        base_row = next(r for r in table["rows"] if r["id"] == "base_salary")
        # 1. previous_amount must be taken from server payroll (150000000), NOT client (999999999)
        self.assertEqual(base_row["previous_amount"], 150000000)
        self.assertEqual(base_row["new_amount"], 180000000)
        # 2. difference must be recomputed on server (180000000 - 150000000 = 30000000), NOT 111
        self.assertEqual(base_row["difference"], 30000000)
        # 3. percent_change must be recomputed on server ((30000000 / 150000000) * 100 = 20.0), NOT 1.0
        self.assertEqual(base_row["percent_change"], 20.0)
        # 4. Totals must be recomputed on server
        self.assertEqual(table["monthly_previous_total"], 150000000)
        self.assertEqual(table["monthly_new_total"], 180000000)
        self.assertEqual(table["monthly_difference"], 30000000)

    def test_final_print_preserves_stored_letterhead_snapshot_after_letterhead_changes(self):
        comp = company()
        frappe.set_user(HR_MANAGER_USER)
        emp = employee_a()

        # 1. Create initial letter head and assign to company
        lh_name = f"LH-Original-{uuid4().hex[:6]}"
        lh = frappe.get_doc({
            "doctype": "Letter Head",
            "letter_head_name": lh_name,
            "source": "HTML",
            "content": "<div class='test-lh'>سربرگ اصلی شرکت</div>",
            "disabled": 0,
        })
        lh.flags.ignore_permissions = True
        lh.insert()
        frappe.db.set_value("Company", comp, "default_letter_head", lh.name)

        # 2. Save order and finalize
        saved = api.save_salary_change_order(
            company=comp,
            request_id=f"lh-test-{uuid4().hex[:8]}",
            employee=emp,
            effective_date=nowdate(),
            reason="annual",
            description="تست چاپ سربرگ",
        )
        order_name = saved["data"]["name"]
        rev = api.send_salary_change_order_for_review(
            name=order_name, revision=saved["data"]["revision"], request_id=f"rev-{uuid4().hex[:8]}"
        )
        finalized = api.approve_salary_change_order(
            name=order_name, revision=rev["data"]["revision"], request_id=f"app-{uuid4().hex[:8]}"
        )
        self.assertEqual(finalized["data"]["status"], "final")

        # 3. Print must contain original letterhead
        print_1 = api.print_salary_change_order(name=order_name)
        self.assertIn("سربرگ اصلی شرکت", print_1["data"]["html"])

        # 4. Mutate company's letter head
        frappe.db.set_value("Letter Head", lh.name, "content", "<div class='test-lh'>سربرگ جدید تغییریافته</div>")

        # 5. Print on finalized order must render the stored snapshot and NOT the mutated letterhead
        print_2 = api.print_salary_change_order(name=order_name)
        self.assertIn("سربرگ اصلی شرکت", print_2["data"]["html"])
        self.assertNotIn("سربرگ جدید تغییریافته", print_2["data"]["html"])
