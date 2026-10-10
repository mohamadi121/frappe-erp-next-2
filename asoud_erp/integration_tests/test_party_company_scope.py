"""SEC-BP-02: party.list_parties must be company scoped and must not dump bank data.

`company` used to be optional, so the endpoint answered for every company and
returned the bank name, IBAN and account numbers of parties the caller could not
even see. Before the fix an Accounts User restricted to Company A received every
party of Company B, IBAN included.
"""

import json

import frappe

from asoud_erp.api.v1 import party
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import (
    ACCOUNTS_A_USER,
    EMPLOYEE_A_USER,
    IBAN_A,
    IBAN_B,
    MANAGER_USER,
    setup_tenancy,
)


def _rows(**kwargs) -> list[dict]:
    return party.list_parties(**kwargs)["data"]


class TestPartyCompanyScope(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        cls.party_a = cls.scope["party_a"]
        cls.party_b = cls.scope["party_b"]

    def test_company_is_required(self):
        """No company means no answer, instead of every company."""
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(TypeError):
            party.list_parties()
        with self.assertRaises(frappe.PermissionError):
            party.list_parties(company="")

    def test_foreign_company_is_rejected(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            party.list_parties(company=self.second)

    def test_employee_role_cannot_list_parties_of_own_company(self):
        """An Active Employee passes the company check but holds no accounting role."""
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            party.list_parties(company=self.company)

    def test_foreign_party_and_bank_details_never_leak(self):
        """Company B's party exists and carries IBAN_B, so the leak is observable."""
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", self.party_b, "iban"), IBAN_B)
        frappe.set_user(ACCOUNTS_A_USER)
        body = json.dumps(_rows(company=self.company), ensure_ascii=False, default=str)
        self.assertNotIn(self.party_b, body)
        self.assertNotIn(IBAN_B, body)

    def test_bank_details_need_the_party_master_roles(self):
        """Accounts Manager pays suppliers and keeps them; an Accounts User may not."""
        frappe.set_user(MANAGER_USER)
        manager_rows = _rows(company=self.company)
        self.assertEqual([row["iban"] for row in manager_rows if row["name"] == self.party_a], [frappe.db.get_value("ASOUD Party Profile", self.party_a, "iban")])
        frappe.set_user(ACCOUNTS_A_USER)
        own = next(row for row in _rows(company=self.company) if row["name"] == self.party_a)
        for field in ("iban", "bank_name", "account_number", "card_number", "account_holder"):
            self.assertNotIn(field, own)

    def test_save_party_response_redacts_bank_details_for_accounts_user(self):
        """SEC-BP-05: the write response must not hand a cashier the bank data.

        `save_party` redacted only the salary `FINANCIAL_FIELDS`; the party's bank
        keys came back to an `Accounts User` even though `list_parties` hides them.
        """
        frappe.set_user(ACCOUNTS_A_USER)
        data = party.save_party(
            name=self.party_a,
            party_type="Individual",
            display_name="ASOUD Scope Party A",
            roles=json.dumps(["Other"]),
            company=self.company,
            iban=IBAN_B,
        )["data"]
        for field in ("bank_name", "iban", "account_number", "card_number", "account_holder"):
            self.assertNotIn(field, data)
        # The same role must not silently overwrite the stored bank data either.
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", self.party_a, "iban"), IBAN_A)

    def test_save_party_response_keeps_bank_details_for_accounts_manager(self):
        frappe.set_user(MANAGER_USER)
        data = party.save_party(
            name=self.party_a,
            party_type="Individual",
            display_name="ASOUD Scope Party A",
            roles=json.dumps(["Other"]),
            company=self.company,
        )["data"]
        for field in ("bank_name", "iban", "account_number", "card_number", "account_holder"):
            self.assertIn(field, data)


class TestPartyWriteCompanyScope(APITestCase):
    """SEC-BP-04: a party write must stay inside the caller's company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]
        cls.party_a = cls.scope["party_a"]
        cls.party_b = cls.scope["party_b"]

    def _payload(self, name: str, **extra) -> dict:
        return {"name": name, "party_type": "Individual", "roles": json.dumps(["Other"]), **extra}

    def test_writing_a_foreign_party_is_refused(self):
        frappe.set_user(ACCOUNTS_A_USER)
        with self.assertRaises(frappe.PermissionError):
            party.save_party(**self._payload(self.party_b, display_name="ASOUD Scope Party B",
                                            company=self.second))
        with self.assertRaises(frappe.PermissionError):
            party.disable_party(name=self.party_b)
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", self.party_b, "disabled"), 0)

    def test_update_keeps_the_company_when_the_argument_is_omitted(self):
        """Omitting `company` must not move a profile out of its tenant."""
        frappe.set_user(ACCOUNTS_A_USER)
        party.save_party(**self._payload(self.party_a, display_name="ASOUD Scope Party A"))
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", self.party_a, "company"), self.company)