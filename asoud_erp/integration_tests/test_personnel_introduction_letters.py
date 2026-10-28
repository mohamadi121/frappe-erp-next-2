"""Integration tests for Personnel Introduction Letters API."""

import frappe
import json
from uuid import uuid4

from asoud_erp.api.v1 import personnel_introduction_letters as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.api.v1 import workflow_request, workflow_runtime
from asoud_erp.services.request_templates.base import series_key
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    EMPLOYEE_B_USER,
    HR_MANAGER_USER,
    SECOND_COMPANY,
    setup_tenancy,
)


class TestPersonnelIntroductionLetters(APITestCase):
    def tearDown(self):
        super().tearDown()
        frappe.clear_cache(user=EMPLOYEE_A_USER)

    def _workflow_letter(self, workflow=""):
        frappe.set_user(HR_MANAGER_USER)
        template = api.get_template(company=company())["data"]
        saved = api.save_template_draft(
            company=company(), revision=template["revision"], clauses=template["clauses"], workflow=workflow,
        )["data"]
        api.publish_template(company=company(), revision=saved["revision"])
        employee = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER}, "name")
        return api.save_draft(company=company(), employee=employee, bank_name="بانک ملت",
            purpose="افتتاح حساب", request_key=uuid4().hex)["data"]

    def _letter_definition(self, approvals=1):
        frappe.set_user("Administrator")
        definition, stages = make_definition(company(), approvals=approvals, fields=[])
        for stage in stages.values():
            if stage.stage_type == "Approval":
                config = json.loads(stage.config_json)
                config.update(assignment_type="Role", approver_roles=["System Manager"])
                frappe.db.set_value("ASOUD Workflow Stage", stage.name, "config_json", json.dumps(config))
        return definition

    def test_no_workflow_uses_direct_hr_policy_and_shared_number_once(self):
        draft = self._workflow_letter()
        key = uuid4().hex
        first = api.finalize_letter(draft["name"], draft["revision"], key)["data"]
        retry = api.finalize_letter(draft["name"], draft["revision"], key)["data"]
        assert first["status"] == "Final"
        assert first["number"].startswith(series_key("INTRO"))
        assert first["number"] == retry["number"]
        assert first["print_html"] == retry["print_html"]
        assert not first.get("workflow_instance")
        with self.assertRaises(frappe.ValidationError):
            api.save_draft(company=company(), employee=draft["employee"], name=draft["name"],
                revision=first["revision"], bank_name="بانک دیگر", purpose="تغییر پس از صدور",
                request_key=uuid4().hex)

    def test_configured_workflow_finalizes_only_after_real_approval(self):
        definition = self._letter_definition()
        draft = self._workflow_letter(definition)
        key = uuid4().hex
        pending = api.finalize_letter(draft["name"], draft["revision"], key)["data"]
        assert pending["status"] == "Pending"
        assert pending["number"] == "—"
        assert "پیش‌نویس ـ فاقد اعتبار نهایی" in pending["print_html"]
        retry = api.finalize_letter(draft["name"], draft["revision"], key)["data"]
        assert retry["workflow_instance"] == pending["workflow_instance"]
        assert retry["workflow_request"] == pending["workflow_request"]
        task = frappe.db.get_value("ASOUD Workflow Task", {
            "workflow_instance": pending["workflow_instance"], "status": "Open",
            "assigned_to": ["!=", HR_MANAGER_USER],
        }, ["name", "assigned_to"], as_dict=True)
        assert task
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, "Approve", comment="تأیید معرفی‌نامه")
        final = api.get_letter(draft["name"])["data"]
        assert final["status"] == "Final"
        assert final["number"].startswith(series_key("INTRO"))
        assert final["template_snapshot"] == draft["template_snapshot"]
        assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in final["print_html"]

    def test_real_rejection_and_cancellation_never_allocate_official_number(self):
        for action, expected in (("Reject", "Rejected"), ("Cancel", "Cancelled")):
            definition = self._letter_definition()
            draft = self._workflow_letter(definition)
            pending = api.finalize_letter(draft["name"], draft["revision"], uuid4().hex)["data"]
            if action == "Cancel":
                workflow_request.cancel_request(pending["workflow_request"], "انصراف از معرفی‌نامه")
            else:
                task = frappe.db.get_value("ASOUD Workflow Task", {
                    "workflow_instance": pending["workflow_instance"], "status": "Open",
                    "assigned_to": ["!=", HR_MANAGER_USER],
                }, ["name", "assigned_to"], as_dict=True)
                assert task
                frappe.set_user(task.assigned_to)
                workflow_runtime.complete_workflow_task(task.name, action, comment="درخواست رد شد")
            frappe.set_user(HR_MANAGER_USER)
            result = api.get_letter(draft["name"])["data"]
            assert result["status"] == expected
            assert result["number"] == "—"

    def test_immediate_workflow_completion_is_observed_after_request_creation(self):
        definition = self._letter_definition(approvals=0)
        draft = self._workflow_letter(definition)
        final = api.finalize_letter(draft["name"], draft["revision"], uuid4().hex)["data"]
        assert final["status"] == "Final"
        assert frappe.db.get_value("ASOUD Workflow Instance", final["workflow_instance"], "status") == "Completed"
        assert final["number"].startswith(series_key("INTRO"))

    def test_unavailable_configured_workflow_does_not_fall_back_to_direct_issue(self):
        definition = self._letter_definition()
        draft = self._workflow_letter(definition)
        frappe.db.set_value("ASOUD Workflow Definition", definition, "status", "Inactive")
        with self.assertRaises(frappe.ValidationError):
            api.finalize_letter(draft["name"], draft["revision"], uuid4().hex)
        current = api.get_letter(draft["name"])["data"]
        assert current["status"] == "Draft"
        assert current["number"] == "—"
        assert not current.get("workflow_request")

    def test_operational_hr_starts_only_own_request_workflows(self):
        definition = self._letter_definition()
        draft = self._workflow_letter(definition)
        frappe.set_user("Administrator")
        frappe.get_doc("User", EMPLOYEE_A_USER).add_roles("HR User")
        frappe.get_doc("User", EMPLOYEE_A_USER).remove_roles("Employee")
        frappe.set_user(EMPLOYEE_A_USER)
        pending = api.finalize_letter(draft["name"], draft["revision"], uuid4().hex)["data"]
        assert "Employee" not in frappe.get_roles()
        assert pending["status"] == "Pending"
        assert frappe.db.get_value("ASOUD Workflow Request", pending["workflow_request"], "owner") == EMPLOYEE_A_USER
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.start_workflow_instance(definition=definition, subject="گردش بدون درخواست")

    def test_foreign_workflow_is_not_selectable_or_saved_in_own_template(self):
        frappe.set_user("Administrator")
        foreign, _ = make_definition(SECOND_COMPANY, fields=[])
        frappe.set_user(HR_MANAGER_USER)
        template = api.get_template(company=company())["data"]
        assert foreign not in {option["name"] for option in template["workflow_options"]}
        with self.assertRaises(frappe.ValidationError):
            api.save_template_draft(company=company(), revision=template["revision"],
                clauses=template["clauses"], workflow=foreign)

    def test_real_failed_workflow_never_issues_letter(self):
        definition = self._letter_definition(approvals=0)
        end = frappe.db.get_value("ASOUD Workflow Stage", {
            "workflow_definition": definition, "stage_type": "End",
        }, "name")
        # The runtime treats an unknown End outcome as Failed, never Completed.
        frappe.db.set_value("ASOUD Workflow Stage", end, "config_json", json.dumps({"outcome": "Invalid"}))
        draft = self._workflow_letter(definition)
        failed = api.finalize_letter(draft["name"], draft["revision"], uuid4().hex)["data"]
        assert failed["status"] == "Failed"
        assert failed["number"] == "—"
        assert frappe.db.get_value("ASOUD Workflow Instance", failed["workflow_instance"], "status") == "Failed"

    def test_scoped_manager_without_employee_can_submit_letter_workflow(self):
        definition = self._letter_definition(approvals=0)
        draft = self._workflow_letter(definition)
        own_employee = frappe.db.get_value("Employee", {"user_id": HR_MANAGER_USER}, "name")
        frappe.db.set_value("Employee", own_employee, "user_id", None)
        assert not frappe.db.exists("Employee", {"user_id": HR_MANAGER_USER})
        final = api.finalize_letter(draft["name"], draft["revision"], uuid4().hex)["data"]
        assert final["status"] == "Final"
        assert final["employee"] == draft["employee"]

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
        assert res["data"]["can_manage_template"] is True

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

    def test_final_print_survives_template_republication_and_employee_edit(self):
        comp = company()
        employee = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_A_USER}, "name")
        frappe.set_user(HR_MANAGER_USER)
        template = api.get_template(company=comp)["data"]
        api.publish_template(company=comp, revision=template["revision"])
        draft = api.save_draft(
            company=comp, employee=employee, bank_name="بانک ملت",
            purpose="افتتاح حساب", request_key="snapshot-before-master-edit",
        )["data"]
        final = api.finalize_letter(
            name=draft["name"], revision=draft["revision"], request_key="snapshot-final",
        )["data"]
        assert final["status"] == "Final"
        assert final["values_snapshot"]["employee"]["employee_name"]
        original_print = final["print_html"]
        head = frappe.get_doc({
            "doctype": "Letter Head", "letter_head_name": "معرفی‌نامه " + uuid4().hex,
            "source": "HTML", "content": "<p>سربرگ تغییر یافته پس از صدور</p>",
        }).insert(ignore_permissions=True)
        frappe.db.set_value("Company", comp, "default_letter_head", head.name)
        frappe.db.set_value("Employee", employee, "employee_name", "نام تغییر یافته پس از صدور")
        template = api.get_template(company=comp)["data"]
        replacement = api.save_template_draft(
            company=comp, revision=template["revision"], clauses=[{
                "id": "replaced", "title": "متن جدید", "body": "قالب تغییر یافته پس از صدور",
                "enabled": True,
            }],
        )["data"]
        api.publish_template(company=comp, revision=replacement["revision"])
        fetched = api.get_letter(final["name"])["data"]
        assert fetched["print_html"] == original_print
        assert fetched["values_snapshot"] == final["values_snapshot"]
        assert "قالب تغییر یافته پس از صدور" not in fetched["print_html"]
        assert "نام تغییر یافته پس از صدور" not in fetched["print_html"]
        assert "سربرگ تغییر یافته پس از صدور" not in fetched["print_html"]

    def test_operational_hr_cannot_save_or_publish_templates(self):
        comp = company()
        frappe.set_user("Administrator")
        frappe.get_doc("User", EMPLOYEE_A_USER).add_roles("HR User")
        frappe.set_user(EMPLOYEE_A_USER)
        template = api.get_template(company=comp)["data"]
        with self.assertRaises(frappe.PermissionError):
            api.save_template_draft(
                company=comp, revision=template["revision"], clauses=template["clauses"],
            )
        with self.assertRaises(frappe.PermissionError):
            api.publish_template(company=comp, revision=template["revision"])
        assert template["can_manage_template"] is False

    def test_other_company_letters_are_inaccessible_in_list_search_get_and_print(self):
        frappe.set_user("Administrator")
        employee_b = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_B_USER}, "name")
        foreign = api.save_draft(
            company=SECOND_COMPANY, employee=employee_b, bank_name="بانک خصوصی شرکت دوم",
            purpose="اطلاعات محرمانه شرکت دوم", request_key="foreign-company-letter",
        )["data"]
        frappe.get_doc("User", EMPLOYEE_A_USER).add_roles("HR User")
        frappe.set_user(EMPLOYEE_A_USER)
        for query in ("", "اطلاعات محرمانه شرکت دوم", foreign["name"]):
            own = api.list_letters(company=company(), query=query)["data"]["items"]
            assert all(row["name"] != foreign["name"] for row in own)
            with self.assertRaises(frappe.PermissionError):
                api.list_letters(company=SECOND_COMPANY, query=query)
        with self.assertRaises(frappe.PermissionError):
            api.get_employee_options(company=SECOND_COMPANY)
        # get_letter is also the server print-payload endpoint.
        with self.assertRaises(frappe.PermissionError):
            api.get_letter(foreign["name"])
