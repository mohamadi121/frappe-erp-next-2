"""Tests for HR Manager access to read-only manager views.

Policy:
- HR Manager may read setup status, role catalog/preview, workflow/request-type lists and designs,
  and workflow options within their assigned company.
- HR Manager is denied foreign company access for company-scoped endpoints.
- HR Manager is denied on all write endpoints that change setup, roles, workflows, templates or vouchers.
- HR Manager is denied on financial reports.
- Plain Employee is denied on all of these.
- System Manager and Accounts Manager access remains unchanged.
"""

import frappe

from asoud_erp.api.v1 import (
    document_templates,
    hr,
    report,
    role_management,
    setup,
    voucher,
    workflow,
)
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import (
    DEPARTMENT_A,
    DEPARTMENT_B,
    EMPLOYEE_A_USER,
    HR_MANAGER_USER,
    MANAGER_USER,
    setup_tenancy,
)


class TestHrManagerAccess(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.first = cls.scope["first"]
        cls.second = cls.scope["second"]

        for c in (cls.first, cls.second):
            if not frappe.db.exists("ASOUD Company Setup", c):
                frappe.get_doc({
                    "doctype": "ASOUD Company Setup",
                    "company": c,
                    "office_type": "Legal",
                    "office_saved": 1,
                    "accounting_saved": 1,
                    "roles_saved": 1,
                }).insert(ignore_permissions=True)

        cls.wf_a, _ = make_definition(cls.first)
        cls.wf_b, _ = make_definition(cls.second)
        frappe.db.commit()

    def test_hr_manager_can_read_setup_status_own_company(self):
        frappe.set_user(HR_MANAGER_USER)
        res_explicit = setup.get_setup_status(company=self.first)
        self.assertEqual(res_explicit["data"]["company"], self.first)

        res_implicit = setup.get_setup_status()
        self.assertEqual(res_implicit["data"]["company"], self.first)

    def test_hr_manager_rejected_setup_status_foreign_company(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            setup.get_setup_status(company=self.second)

    def test_organization_tree_is_company_scoped(self):
        """F7: the department tree must be gated by `require_company`."""
        frappe.set_user(HR_MANAGER_USER)
        tree = hr.organization_tree(company=self.first)["data"]
        names = {row["department_name"] for row in tree}
        self.assertIn(DEPARTMENT_A, names)
        self.assertNotIn(DEPARTMENT_B, names)
        with self.assertRaises(frappe.PermissionError):
            hr.organization_tree(company=self.second)

    def test_hr_manager_can_read_role_catalog_and_preview(self):
        frappe.set_user(HR_MANAGER_USER)
        catalog_res = role_management.catalog()
        self.assertIn("roles", catalog_res["data"])
        self.assertIn("categories", catalog_res["data"])

        preview_res = role_management.permission_preview(roles=["HR Manager"])
        self.assertIsInstance(preview_res["data"], list)

    def test_hr_manager_can_read_workflows_own_company(self):
        frappe.set_user(HR_MANAGER_USER)
        list_res = workflow.list_workflows(company=self.first)
        self.assertIsInstance(list_res["data"], list)

        design_res = workflow.get_workflow_design(definition=self.wf_a)
        self.assertEqual(design_res["data"]["workflow"]["name"], self.wf_a)

        options_res = workflow.workflow_form_options()
        self.assertIn("modules", options_res["data"])

        cond_res = workflow.workflow_condition_fields(definition=self.wf_a)
        self.assertIn("fields", cond_res["data"])

    def test_hr_manager_rejected_workflows_foreign_company(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.list_workflows(company=self.second)

        with self.assertRaises(frappe.PermissionError):
            workflow.get_workflow_design(definition=self.wf_b)

        with self.assertRaises(frappe.PermissionError):
            workflow.workflow_condition_fields(definition=self.wf_b)

    def test_hr_manager_denied_on_role_writes(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            role_management.save_role(payload={"code": "HR_TEST", "title": "Test"})

        with self.assertRaises(frappe.PermissionError):
            role_management.create_category(payload={"code": "TEST_CAT", "title": "Cat"})

        with self.assertRaises(frappe.PermissionError):
            role_management.apply_templates(codes=["FINANCE_MANAGER"])

    def test_hr_manager_denied_on_workflow_writes(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow.create_workflow_draft(
                workflow_title="HR Attempt",
                module_key="HR",
                target_doctype="Leave Application",
                company=self.first,
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.save_start_settings(
                definition=self.wf_a,
                trigger_type="Manual",
                initiator_roles=["HR User"],
                subject_source="Referenced Document",
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.add_workflow_stage(
                definition=self.wf_a, stage_type="User Task", after_stage="any"
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.update_stage_positions(definition=self.wf_a, positions={})

        with self.assertRaises(frappe.PermissionError):
            workflow.connect_workflow_stages(
                definition=self.wf_a, from_stage="s1", to_stage="s2", action="Approve"
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.insert_workflow_stage(
                definition=self.wf_a, transition="t1", stage_type="User Task"
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.add_condition_branch(
                definition=self.wf_a, condition_stage="c1", stage_type="End", result=True
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.save_stage_settings(
                definition=self.wf_a, stage="s1", config={}
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.save_stage_routes(
                definition=self.wf_a, stage="s1", routes={}
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.update_request_type_info(
                name=self.wf_a, workflow_title="New Title"
            )

        with self.assertRaises(frappe.PermissionError):
            workflow.set_workflow_status(name=self.wf_a, status="Archived")

    def test_hr_manager_denied_on_setup_writes(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            setup.save_office(office_type="Legal", company_name="Test Office")

        with self.assertRaises(frappe.PermissionError):
            setup.update_company_settings(
                company=self.first,
                display_currency="Rial",
                fiscal_year_start_month=1,
                chart_template="Iran Standard",
            )

        with self.assertRaises(frappe.PermissionError):
            setup.create_fiscal_year(
                company=self.first, fiscal_year=1405, start_month=1, start_day=1
            )

        with self.assertRaises(frappe.PermissionError):
            setup.update_enabled_roles(company=self.first, roles=["HR Manager"])

        with self.assertRaises(frappe.PermissionError):
            setup.update_settings(display_currency="Rial")

        with self.assertRaises(frappe.PermissionError):
            setup.update_account_code_settings(company=self.first)

        with self.assertRaises(frappe.PermissionError):
            setup.set_default_office(company=self.first)

    def test_hr_manager_denied_on_other_writes_and_reports(self):
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            document_templates.save_document_template(
                company=self.first, template={"title": "T", "module": "Finance", "document_type": "Journal Entry"}
            )

        with self.assertRaises(frappe.PermissionError):
            voucher.save_voucher(
                company=self.first, posting_date="2026-01-01", lines=[]
            )

        with self.assertRaises(frappe.PermissionError):
            report.trial_balance(company=self.first, from_date="2026-01-01", to_date="2026-12-31")

        with self.assertRaises(frappe.PermissionError):
            report.general_ledger(
                company=self.first, from_date="2026-01-01", to_date="2026-12-31", account="any"
            )

    def test_employee_denied_on_all_newly_opened_endpoints(self):
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            setup.get_setup_status(company=self.first)

        with self.assertRaises(frappe.PermissionError):
            role_management.catalog()

        with self.assertRaises(frappe.PermissionError):
            role_management.permission_preview(roles=["HR Manager"])

        with self.assertRaises(frappe.PermissionError):
            workflow.list_workflows(company=self.first)

        with self.assertRaises(frappe.PermissionError):
            workflow.get_workflow_design(definition=self.wf_a)

        with self.assertRaises(frappe.PermissionError):
            workflow.workflow_form_options()

        with self.assertRaises(frappe.PermissionError):
            workflow.workflow_condition_fields(definition=self.wf_a)

    def test_system_and_accounts_managers_unchanged(self):
        # Accounts Manager
        frappe.set_user(MANAGER_USER)
        self.assertEqual(setup.get_setup_status(company=self.first)["data"]["company"], self.first)
        self.assertIsInstance(workflow.list_workflows(company=self.first)["data"], list)
        self.assertEqual(workflow.get_workflow_design(definition=self.wf_a)["data"]["workflow"]["name"], self.wf_a)
        self.assertIn("modules", workflow.workflow_form_options()["data"])
        self.assertIn("fields", workflow.workflow_condition_fields(definition=self.wf_a)["data"])

        # Accounts Manager rejected on foreign company
        with self.assertRaises(frappe.PermissionError):
            setup.get_setup_status(company=self.second)
        with self.assertRaises(frappe.PermissionError):
            workflow.list_workflows(company=self.second)
        with self.assertRaises(frappe.PermissionError):
            workflow.get_workflow_design(definition=self.wf_b)
        with self.assertRaises(frappe.PermissionError):
            workflow.workflow_condition_fields(definition=self.wf_b)

        # System Manager (Administrator)
        frappe.set_user("Administrator")
        self.assertIn("roles", role_management.catalog()["data"])
        self.assertIsInstance(role_management.permission_preview(roles=["HR Manager"])["data"], list)
        self.assertEqual(setup.get_setup_status(company=self.first)["data"]["company"], self.first)

    def test_hr_dashboard_without_employee_record(self):
        # Administrator has System Manager and no linked Employee
        frappe.set_user("Administrator")
        self.assertIsNone(frappe.db.get_value("Employee", {"user_id": "Administrator", "status": "Active"}))
        res_admin = hr.get_dashboard(company=self.first)
        self.assertTrue(res_admin["data"].get("manager_access"))
        self.assertNotIn("employee", res_admin["data"])
        self.assertNotIn("today_report", res_admin["data"])
        self.assertEqual(res_admin["data"]["company"], self.first)

        # Employee-only user without linked Employee record keeps current error
        token = frappe.generate_hash(length=8)
        no_record_user = f"emp-norec-{token}@example.com"
        frappe.get_doc({
            "doctype": "User",
            "email": no_record_user,
            "first_name": "No",
            "last_name": "Record",
            "enabled": 1,
            "roles": [{"role": "Employee"}],
        }).insert(ignore_permissions=True)
        try:
            frappe.set_user(no_record_user)
            with self.assertRaises(frappe.ValidationError):
                hr.get_dashboard(company=self.first)
        finally:
            frappe.set_user("Administrator")
            frappe.delete_doc("User", no_record_user, ignore_permissions=True)
