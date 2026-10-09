"""SEC-BP-01: report.trial_balance / report.general_ledger must be tenant scoped.

An ``Accounts User`` restricted to Company A by a User Permission must not read
Company B's ledger. Before the fix both calls returned Company B's rows.
"""

import json

import frappe

from asoud_erp.api.v1 import report
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import (
    ACCOUNTS_A_USER,
    GL_AMOUNT,
    IBAN_B,
    journal,
    ledger,
    setup_tenancy,
)

FROM_DATE = "2025-01-01"
TO_DATE = "2027-12-31"


class TestReportCompanyScope(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        cls.second_account = ledger(cls.second, "Expense")

    def test_trial_balance_rejects_foreign_company(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            report.trial_balance(company=self.second, from_date=FROM_DATE, to_date=TO_DATE)
        with self.assertRaises(frappe.PermissionError):
            report.trial_balance(company=self.second, from_date=FROM_DATE, to_date=TO_DATE,
                                 account=self.second_account)

    def test_general_ledger_rejects_foreign_company(self):
        """The foreign company really holds a ledger, so the refusal is not vacuous."""
        self.assertEqual(
            frappe.db.count("GL Entry", {"company": self.second, "voucher_no": journal(self.second)}), 2
        )
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            report.general_ledger(company=self.second, from_date=FROM_DATE, to_date=TO_DATE,
                                  account=self.second_account)

    def test_own_company_ledger_still_reads(self):
        """The fix must not lock an app user out of its own company."""
        first = self.company
        account = ledger(first, "Expense")
        voucher = journal(first)
        frappe.set_user(ACCOUNTS_A_USER)
        data = report.general_ledger(company=first, from_date=FROM_DATE, to_date=TO_DATE,
                                     account=account)["data"]
        entry = next(row for row in data["entries"] if row["voucher_no"] == voucher)
        self.assertEqual((entry["debit"], entry["credit"], entry["voucher_type"]), (GL_AMOUNT, 0.0, "Journal Entry"))
        rows = report.trial_balance(company=first, from_date=FROM_DATE, to_date=TO_DATE)["data"]["rows"]
        self.assertEqual([row["account"] for row in rows].count(self.second_account), 0)
        self.assertEqual(ledger(first, "Equity"), next(row["account"] for row in rows
                                                       if row["closing_credit"] == GL_AMOUNT))

    def test_employee_is_denied_the_reports(self):
        frappe.set_user("asoud.employee@example.com")
        with self.assertRaises(frappe.PermissionError):
            report.trial_balance(company=self.company, from_date=FROM_DATE, to_date=TO_DATE)

    def test_foreign_bank_details_stay_out_of_the_ledger_surface(self):
        """The ledger surface never carries party bank data (defence in depth)."""
        frappe.set_user("Administrator")
        entries = report.general_ledger(company=self.second, from_date=FROM_DATE, to_date=TO_DATE,
                                        account=self.second_account)["data"]["entries"]
        self.assertNotIn(IBAN_B, json.dumps(entries, ensure_ascii=False, default=str))