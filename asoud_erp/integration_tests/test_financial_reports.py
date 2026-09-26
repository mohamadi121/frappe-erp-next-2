import frappe
from frappe.utils import add_days, get_year_ending, get_year_start, nowdate

from asoud_erp.api.v1 import financial_reports, selling
from asoud_erp.integration_tests.fixtures import CUSTOMER, EMPLOYEE_USER, SERVICE, APITestCase


class TestFinancialReports(APITestCase):
    def test_receivable_shows_an_unpaid_invoice(self):
        invoice = selling.create_sales_invoice(self.company, CUSTOMER, [{"item_code": SERVICE, "qty": 1}],
                                               submit=1)["data"]
        data = financial_reports.run_financial_report(self.company, "receivable",
                                                      report_date=add_days(nowdate(), 1),
                                                      party=CUSTOMER)["data"]
        self.assertIn("outstanding", [column["fieldname"] for column in data["columns"]])
        self.assertIn(invoice["name"], [row.get("voucher_no") for row in data["rows"]])

    def test_statements_and_stock_balance_run(self):
        start, end = str(get_year_start(nowdate())), str(get_year_ending(nowdate()))
        for report in ("profit_and_loss", "balance_sheet", "stock_balance"):
            data = financial_reports.run_financial_report(self.company, report, from_date=start, to_date=end)
            self.assertTrue(data["data"]["columns"], report)

    def test_report_roles_are_erpnexts(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            financial_reports.run_financial_report(self.company, "balance_sheet", from_date=nowdate(),
                                                   to_date=nowdate())
