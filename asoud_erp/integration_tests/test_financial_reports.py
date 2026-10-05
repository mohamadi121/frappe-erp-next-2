import frappe
from frappe.utils import add_days, get_year_ending, get_year_start, getdate, nowdate

from asoud_erp.api.v1 import financial_reports, selling, stock
from asoud_erp.integration_tests.fixtures import CUSTOMER, EMPLOYEE_USER, ITEM, SERVICE, APITestCase


def allow_fiscal_year(company: str) -> None:
    """Let `company` post inside the fiscal year covering today.

    ERPNext rejects a submission whose date is outside a fiscal year that lists
    the company, and a fiscal year with an empty company list applies to every
    company. So a company created by a test only posts when the shared fiscal
    year is either empty or already lists it.
    """
    today = getdate(nowdate())
    names = frappe.get_all("Fiscal Year", filters={"disabled": 0, "year_start_date": ["<=", today],
        "year_end_date": [">=", today]}, pluck="name", order_by="name desc")
    for name in names:
        fiscal_year = frappe.get_doc("Fiscal Year", name)
        if any(row.company == company for row in fiscal_year.companies):
            return
        if not fiscal_year.companies:
            return
        fiscal_year.append("companies", {"company": company})
        fiscal_year.save(ignore_permissions=True)
        return
    raise AssertionError("no active fiscal year covers today, so no transaction can be submitted")


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

    def test_statements_and_stock_balance_have_exact_transaction_values(self):
        """A fresh company with one journal entry and one receipt, so every reported
        row and total is a known value rather than "some row exists"."""
        token = frappe.generate_hash(length=8)
        company = frappe.get_doc({"doctype": "Company", "company_name": "Report " + token,
            "abbr": token, "default_currency": "USD", "country": "United States",
            "chart_of_accounts": "Standard"}).insert()
        allow_fiscal_year(company.name)
        expense = f"Office Rent - {token}"
        liability = f"Asset Received But Not Billed - {token}"
        entry = frappe.get_doc({"doctype": "Journal Entry", "company": company.name,
            "posting_date": nowdate(), "accounts": [
                {"account": expense, "debit_in_account_currency": 1250,
                 "cost_center": company.cost_center},
                {"account": liability, "credit_in_account_currency": 1250}]}).insert()
        entry.submit()
        start, end = str(get_year_start(nowdate())), str(get_year_ending(nowdate()))

        def report(key):
            data = financial_reports.run_financial_report(
                company.name, key, from_date=start, to_date=end)["data"]
            periods = [column["fieldname"] for column in data["columns"]
                       if column["fieldtype"] == "Currency"]
            self.assertEqual(len(periods), 1, key)
            return [(row.get("account"), row.get("total"), row.get(periods[0]))
                    for row in data["rows"]]

        self.assertEqual(report("profit_and_loss"), [
            (f"Expenses - {token}", 1250, 1250),
            (f"Indirect Expenses - {token}", 1250, 1250),
            (expense, 1250, 1250),
            ("'Total Expense (Debit)'", 1250, 1250),
            (None, None, None),
            ("'Profit for the year'", -1250, -1250),
        ])
        self.assertEqual(report("balance_sheet"), [
            (f"Source of Funds (Liabilities) - {token}", 1250, 1250),
            (f"Current Liabilities - {token}", 1250, 1250),
            (f"Stock Liabilities - {token}", 1250, 1250),
            (liability, 1250, 1250),
            ("'Total Liability (Credit)'", 1250, 1250),
            (None, None, None),
        ])

        warehouse = frappe.db.get_value("Warehouse", {"company": company.name, "warehouse_name": "Stores"})
        stock.create_stock_entry(company.name, "Material Receipt",
            [{"item_code": ITEM, "qty": 7, "rate": 120, "t_warehouse": warehouse}], submit=1)
        data = financial_reports.run_financial_report(company.name, "stock_balance", from_date=start,
            to_date=end, warehouse=warehouse)["data"]
        self.assertEqual([(row["item_code"], row["warehouse"], row["company"], row["stock_uom"],
                           row["opening_qty"], row["in_qty"], row["out_qty"], row["bal_qty"],
                           row["opening_val"], row["in_val"], row["out_val"], row["bal_val"], row["val_rate"])
                          for row in data["rows"]],
                         [(ITEM, warehouse, company.name, "Nos", 0.0, 7.0, 0.0, 7.0,
                           0.0, 840.0, 0.0, 840.0, 120.0)])

    def test_report_roles_are_erpnexts(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            financial_reports.run_financial_report(self.company, "balance_sheet", from_date=nowdate(),
                                                   to_date=nowdate())
