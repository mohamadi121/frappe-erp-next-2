import frappe
from frappe.utils import get_first_day, get_last_day, get_year_start, nowdate

from asoud_erp.api.v1 import hr_self_service, payroll
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase, abbr

STRUCTURE = "ASOUD Test Structure"


def _account(root_type: str, name_like: str) -> str:
    rows = frappe.get_all("Account", filters={"company": frappe.defaults.get_global_default("company"),
                                              "root_type": root_type, "is_group": 0,
                                              "account_name": ["like", name_like]}, pluck="name", limit=1)
    return rows[0] if rows else frappe.get_all("Account", filters={"root_type": root_type, "is_group": 0},
                                               pluck="name", limit=1)[0]


def setup_payroll(company: str) -> None:
    payable = f"Payroll Payable - {abbr()}"
    if frappe.db.exists("Account", payable):
        frappe.db.set_value("Company", company, "default_payroll_payable_account", payable)
    for name, component_abbr, kind, account in (
            ("ASOUD Basic", "AB", "Earning", _account("Expense", "%Salary%")),
            ("ASOUD Insurance", "AI", "Deduction", _account("Liability", "%Payroll%"))):
        if not frappe.db.exists("Salary Component", name):
            frappe.get_doc({"doctype": "Salary Component", "salary_component": name,
                            "salary_component_abbr": component_abbr, "type": kind,
                            "accounts": [{"company": company, "account": account}]}).insert()
    if not frappe.db.exists("Salary Structure", STRUCTURE):
        structure = frappe.get_doc({
            "doctype": "Salary Structure", "company": company,
            "payroll_frequency": "Monthly", "is_active": "Yes",
            "currency": frappe.get_cached_value("Company", company, "default_currency"),
            "earnings": [{"salary_component": "ASOUD Basic", "abbr": "AB", "amount_based_on_formula": 1,
                          "formula": "base"}],
            "deductions": [{"salary_component": "ASOUD Insurance", "abbr": "AI", "amount_based_on_formula": 1,
                            "formula": "base * 0.07"}],
        })
        structure.insert(set_name=STRUCTURE)
        structure.submit()


class TestPayroll(APITestCase):
    def setUp(self):
        super().setUp()
        setup_payroll(self.company)

    def test_assign_run_and_submit_payroll(self):
        options = payroll.payroll_options(self.company)["data"]
        self.assertIn(STRUCTURE, [row.name for row in options["salary_structures"]])
        assignment = payroll.create_salary_structure_assignment(self.records["employee"], STRUCTURE,
                                                                str(get_year_start(nowdate())), 30_000_000)["data"]
        self.assertEqual((assignment["docstatus"], assignment["base"]), (1, 30_000_000))
        entry = payroll.create_payroll_entry(self.company, str(get_first_day(nowdate())),
                                             str(get_last_day(nowdate())))["data"]
        slip = next(row for row in entry["salary_slips"] if row.employee == self.records["employee"])
        self.assertEqual((slip.gross_pay, slip.total_deduction, slip.net_pay),
                         (30_000_000, 2_100_000, 27_900_000))
        self.assertEqual(slip.docstatus, 0)
        submitted = payroll.submit_payroll_salary_slips(entry["name"])["data"]
        self.assertTrue(all(row.docstatus == 1 for row in submitted["salary_slips"]))
        frappe.set_user(EMPLOYEE_USER)
        mine = hr_self_service.list_my_salary_slips()["data"]
        self.assertEqual(mine[0].net_pay, 27_900_000)
        detail = hr_self_service.get_my_salary_slip(mine[0].name)["data"]
        self.assertEqual([row["component"] for row in detail["deductions"]], ["ASOUD Insurance"])

    def test_payroll_is_for_hr_managers(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            payroll.create_payroll_entry(self.company, str(get_first_day(nowdate())),
                                         str(get_last_day(nowdate())))
        with self.assertRaises(frappe.PermissionError):
            payroll.payroll_options(self.company)
