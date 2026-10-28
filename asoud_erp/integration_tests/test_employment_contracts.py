"""Integration tests for Employment Contracts API (template builder and issuance)."""


import frappe
from frappe.utils import nowdate

from asoud_erp.api.v1 import employment_contracts as api
from asoud_erp.integration_tests.fixtures import APITestCase, company
from asoud_erp.integration_tests.tenancy import (
    EMPLOYEE_A_USER,
    EMPLOYEE_B_USER,
    HR_MANAGER_USER,
    setup_tenancy,
)
from asoud_erp.services.employment_contract import DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS


class TestEmploymentContracts(APITestCase):
    def test_client_salary_tampering_is_ignored(self):
        import json
        from uuid import uuid4

        frappe.set_user(HR_MANAGER_USER)
        comp = company()
        employee = frappe.db.get_value("Employee", {"company": comp, "status": "Active"}, "name")
        draft = api.save_contract_draft(comp, employee, "2020-01-01",
                                        salary_values={"payroll.base_salary": 999999999999,
                                                       "payroll.housing": 888888888888},
                                        client_id=uuid4().hex)["data"]
        encoded = frappe.db.get_value("ASOUD Form Entry", {"reference_name": draft["contract_id"]}, "values_json")
        values = json.loads(encoded)["salary_values"]
        self.assertNotIn(999999999999, values.values())
        self.assertNotIn("payroll.housing", values)
        assignments = frappe.get_all("Salary Structure Assignment",
                                      filters={"employee": employee, "company": comp, "docstatus": 1,
                                               "from_date": ["<=", "2020-01-01"]},
                                      fields=["base"], order_by="from_date desc, creation desc", limit_page_length=1)
        self.assertEqual(values, {"payroll.base_salary": assignments[0].base} if assignments else {})

    def test_salary_is_masked_in_detail_and_print(self):
        import json
        from uuid import uuid4

        frappe.set_user("Administrator")
        comp = company()
        employee = frappe.db.get_value("Employee", {"company": comp, "status": "Active"}, "name")
        draft = api.save_contract_draft(comp, employee, nowdate(), client_id=uuid4().hex)["data"]
        entry = frappe.db.get_value("ASOUD Form Entry", {"reference_name": draft["contract_id"]}, "name")
        snapshot = json.loads(frappe.db.get_value("ASOUD Form Entry", entry, "values_json"))
        snapshot.update(salary_table=[{"name": "حقوق", "formatted_amount": "SECRET-SALARY"}],
                        total_monthly=987654321, formatted_total_monthly="SECRET-SALARY")
        frappe.db.set_value("ASOUD Form Entry", entry, "values_json", json.dumps(snapshot))
        frappe.set_user(HR_MANAGER_USER)
        detail = api.get_contract(draft["contract_id"])["data"]
        self.assertEqual(detail["salary_table"], [])
        self.assertEqual(detail["total_monthly"], 0)
        self.assertNotIn("SECRET-SALARY", json.dumps(detail))
        self.assertNotIn("SECRET-SALARY", json.dumps(api.get_contract_print(draft["contract_id"])))
        self.assertNotIn("SECRET-SALARY", json.dumps(api.list_contracts(comp)))

    def test_hr_manager_has_no_implicit_payroll_permission(self):
        frappe.set_user(HR_MANAGER_USER)
        self.assertFalse(api._has_payroll_permission(company()))
        catalog = api.get_contract_field_catalog(company())["data"]
        payroll = next(row for row in catalog["categories"] if row["key"] == "payroll")
        self.assertFalse(payroll["authorized"])

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

        # Ensure an active HR User exists
        if not frappe.db.exists("User", "asoud.test-hr-user@example.com"):
            user = frappe.get_doc({
                "doctype": "User",
                "email": "asoud.test-hr-user@example.com",
                "first_name": "کارشناس",
                "last_name": "منابع انسانی",
                "roles": [{"role": "HR User"}],
            })
            user.flags.ignore_permissions = True
            user.insert()

            perm = frappe.get_doc({
                "doctype": "User Permission",
                "user": "asoud.test-hr-user@example.com",
                "allow": "Company",
                "for_value": company(),
                "apply_to_all_doctypes": 1,
            })
            perm.flags.ignore_permissions = True
            perm.insert()

        if not frappe.db.exists("Employee", {"user_id": "asoud.test-hr-user@example.com"}):
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "کارشناس",
                "last_name": "منابع انسانی",
                "user_id": "asoud.test-hr-user@example.com",
                "company": company(),
                "status": "Active",
                "gender": "Male",
                "date_of_birth": "1990-01-01",
                "date_of_joining": nowdate(),
            })
            emp.flags.ignore_permissions = True
            emp.insert()

        frappe.db.commit()

    def test_unauthorized_user_is_denied(self):
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            api.get_contract_template(company())

        with self.assertRaises(frappe.PermissionError):
            api.list_contracts(company())

    def test_hr_user_can_operate_but_cannot_edit_template(self):
        frappe.set_user("asoud.test-hr-user@example.com")

        # Operational HR user CAN view template and field catalog
        res = api.get_contract_template(company())
        self.assertTrue(res["ok"])
        self.assertFalse(res["data"]["can_edit_template"])

        catalog = api.get_contract_field_catalog(company())
        self.assertTrue(catalog["ok"])

        # Operational HR user CANNOT save or publish template!
        with self.assertRaises(frappe.PermissionError):
            api.save_contract_template(company(), DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS)

        with self.assertRaises(frappe.PermissionError):
            api.publish_contract_template(company())

    def test_cross_office_leak_is_prevented(self):
        # User restricted to Company B cannot access Company A's contracts
        frappe.set_user(EMPLOYEE_B_USER)
        with self.assertRaises(frappe.PermissionError):
            api.list_contracts(company())

        with self.assertRaises(frappe.PermissionError):
            api.get_contract_template(company())

    def test_template_versioning_and_snapshot_preservation(self):
        frappe.set_user(HR_MANAGER_USER)
        comp = company()

        # 1. Designer saves template draft and publishes revision 1
        save_res = api.save_contract_template(comp, DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS)
        self.assertTrue(save_res["ok"])
        template_id = save_res["data"]["template_id"]

        pub1 = api.publish_contract_template(comp, template_id=template_id, change_note="نسخه اول")
        self.assertTrue(pub1["ok"])
        self.assertEqual(pub1["data"]["version"], 1)

        # Find or create an employee in Company A
        emp_name = frappe.db.get_value("Employee", {"company": comp, "status": "Active"}, "name")
        if not emp_name:
            emp = frappe.get_doc({
                "doctype": "Employee",
                "first_name": "تست",
                "last_name": "قرارداد",
                "company": comp,
                "status": "Active",
                "gender": "Male",
                "date_of_birth": "1990-01-01",
                "date_of_joining": nowdate(),
            })
            emp.flags.ignore_permissions = True
            emp.insert()
            emp_name = emp.name

        # 2. Issue a draft contract for this employee
        draft_res = api.save_contract_draft(
            company=comp,
            employee=emp_name,
            start_date=nowdate(),
            contract_type="مدت‌معین",
            salary_values={"payroll.base_salary": 200000000},
            client_id="test-client-draft-1",
        )
        self.assertTrue(draft_res["ok"])
        contract_id = draft_res["data"]["contract_id"]

        # Finalize the contract
        fin_res = api.finalize_contract(contract_id)
        self.assertTrue(fin_res["ok"])
        self.assertEqual(fin_res["data"]["status"], "نهایی")
        official_number = fin_res["data"]["contract_number"]
        self.assertTrue(official_number.startswith("CNT-"))

        # Verify contract snapshot under revision 1
        contract_doc = api.get_contract(contract_id)["data"]
        self.assertEqual(contract_doc["template_version"], 1)
        self.assertEqual(len(contract_doc["rendered_clauses"]), len(DEFAULT_CLAUSES))
        original_clause_text = contract_doc["rendered_clauses"][0]["body"]

        # 3. Designer updates template with new clause and publishes revision 2
        updated_clauses = list(DEFAULT_CLAUSES) + [
            {"id": "clause_new", "title": "ماده جدید آزمایشی", "body": "متن ماده جدید", "order": len(DEFAULT_CLAUSES) + 1}
        ]
        api.save_contract_template(comp, updated_clauses, DEFAULT_SALARY_ROWS)
        pub2 = api.publish_contract_template(comp, template_id=template_id, change_note="نسخه دوم با ماده جدید")
        self.assertEqual(pub2["data"]["version"], 2)

        # 4. HARD RULE: Previously issued contract MUST NOT change!
        contract_after = api.get_contract(contract_id)["data"]
        self.assertEqual(contract_after["template_version"], 1)
        self.assertEqual(len(contract_after["rendered_clauses"]), len(DEFAULT_CLAUSES))
        self.assertEqual(contract_after["rendered_clauses"][0]["body"], original_clause_text)

    def test_list_and_search_contracts(self):
        frappe.set_user(HR_MANAGER_USER)
        comp = company()

        emp_name = frappe.db.get_value("Employee", {"company": comp, "status": "Active"}, "name")
        emp_full_name = frappe.db.get_value("Employee", emp_name, "employee_name")

        draft = api.save_contract_draft(
            company=comp,
            employee=emp_name,
            start_date=nowdate(),
            client_id="test-search-draft",
        )
        self.assertTrue(draft["ok"])

        # List all
        lst = api.list_contracts(comp, status="all")
        self.assertTrue(lst["ok"])
        self.assertGreaterEqual(lst["meta"]["total"], 1)

        # Search by employee name with Arabic characters normalization
        search_query = emp_full_name.replace("ی", "ي").replace("ک", "ك")
        searched = api.list_contracts(comp, search=search_query)
        self.assertTrue(searched["ok"])
        self.assertGreaterEqual(len(searched["data"]), 1)

    def test_print_payload_draft_vs_final(self):
        frappe.set_user(HR_MANAGER_USER)
        comp = company()

        emp_name = frappe.db.get_value("Employee", {"company": comp, "status": "Active"}, "name")
        draft = api.save_contract_draft(
            company=comp,
            employee=emp_name,
            start_date=nowdate(),
            client_id="test-print-draft",
        )
        contract_id = draft["data"]["contract_id"]

        print_res = api.get_contract_print(contract_id)
        self.assertTrue(print_res["ok"])
        self.assertTrue(print_res["data"]["is_draft"])
        self.assertEqual(print_res["data"]["draft_banner"], "«پیش‌نویس ـ فاقد اعتبار نهایی»")

        # After finalization
        api.finalize_contract(contract_id)
        final_print = api.get_contract_print(contract_id)
        self.assertFalse(final_print["data"]["is_draft"])
        self.assertIsNone(final_print["data"]["draft_banner"])
        self.assertTrue(final_print["data"]["contract_number"].startswith("CNT-"))
