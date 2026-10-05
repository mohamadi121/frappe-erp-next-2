"""SEC-BP-03: an accounting role without HR may not rewrite Employee HR master data.

`party.save_party` writes the linked ERPNext `Employee` (gender, birth date,
date of joining) and mirrors `job_title` onto its designation with permission
checks disabled, so an `Accounts Manager` could edit HR master data through a
party form and set the employee's bank details. `personnel.update_personnel` is
the HR-only path and refuses the same writes.
"""

import json

import frappe

from asoud_erp.api.v1 import party
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import (
    DESIGNATION_A,
    DESIGNATION_OTHER,
    MANAGER_USER,
    PERSONNEL_USER,
    setup_tenancy,
)


class TestPartyEmployeeSoD(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.personnel = cls.scope["personnel_a"]
        cls.employee = cls.scope["employee_a"]

    def _payload(self, **extra) -> dict:
        return {
            "name": self.personnel,
            "party_type": "Individual",
            "display_name": "ASOUD Scope Personnel A",
            "roles": json.dumps(["Employee"]),
            "company": self.company,
            "employee_gender": "Male",
            "birth_date": "1990-01-01",
            "date_of_joining": "2020-01-01",
            **extra,
        }

    def test_accounts_manager_cannot_rewrite_employee_designation(self):
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            party.save_party(**self._payload(job_title=DESIGNATION_OTHER))
        self.assertEqual(frappe.db.get_value("Employee", self.employee, "designation"), DESIGNATION_A)
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", self.personnel, "job_title"), DESIGNATION_A)

    def test_accounts_manager_cannot_write_employee_bank_details(self):
        frappe.set_user(MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            party.save_party(**self._payload(iban="IR000000000000000000000099"))
        self.assertNotEqual(frappe.db.get_value("ASOUD Party Profile", self.personnel, "iban"),
                            "IR000000000000000000000099")

    def test_hr_manager_still_writes_the_employee(self):
        """The gate must not lock the legitimate HR path out.

        ``save_party`` also allocates the personnel party's floating details,
        which needs ``Accounts Manager``, so the legitimate user here is the
        person who holds both roles.
        """
        frappe.set_user(PERSONNEL_USER)
        party.save_party(**self._payload(job_title=DESIGNATION_OTHER))
        self.assertEqual(frappe.db.get_value("Employee", self.employee, "designation"), DESIGNATION_OTHER)