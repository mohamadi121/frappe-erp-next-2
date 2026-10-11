"""Persian and Arabic-Indic digits never reach identifier/number columns.

Proves the write boundaries in ``party.save_party`` and ``setup.save_office`` store
ASCII digits, and that the ``v0_15_3`` migration patch converts legacy rows while
leaving clean rows untouched.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1.party import save_party
from asoud_erp.api.v1.setup import save_office
from asoud_erp.integration_tests.fixtures import company
from asoud_erp.patches.v0_15_3.normalize_persian_digits import execute


class TestPersianDigits(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")

    def test_party_identifier_columns_store_ascii_digits(self):
        result = save_party(
            party_type="Individual",
            display_name=f"ASOUD Digits Party {frappe.generate_hash(length=6)}",
            roles=["Customer"],
            company=company(),
            national_id="۰۰۱۳۵۴۲۴۳۵",
            mobile="۰۹۱۲۱۲۳۴۵۶۷",
            phone="۰۲۱۸۸۸۸۸۸۸۸",
            postal_code="۹۸۷۷۶۶۶۶۶۶",
        )["data"]
        stored = frappe.db.get_value(
            "ASOUD Party Profile",
            result["name"],
            ["national_id", "mobile", "phone", "postal_code"],
            as_dict=True,
            cache=False,
        )
        self.assertEqual(result["national_id"], "0013542435")
        self.assertEqual(
            (stored.national_id, stored.mobile, stored.phone, stored.postal_code),
            ("0013542435", "09121234567", "02188888888", "9877666666"),
        )

    def test_office_number_columns_store_ascii_digits(self):
        result = save_office(
            "Personal",
            f"ASOUD Digits Office {frappe.generate_hash(length=6)}",
            postal_code="۹۸۷۷۶۶۶۶۶۶",
            phone="۰۲۱۸۸۸۸۸۸۸۸",
            fiscal_year="۱۴۰۵",
        )["data"]
        stored = frappe.db.get_value(
            "ASOUD Company Setup",
            result["company"],
            ["postal_code", "phone", "fiscal_year"],
            as_dict=True,
            cache=False,
        )
        self.assertEqual(
            (stored.postal_code, stored.phone, stored.fiscal_year),
            ("9877666666", "02188888888", "1405"),
        )
        self.assertEqual(result["fiscal_year"], 1405)

    def test_migration_patch_converts_legacy_rows_and_skips_clean_rows(self):
        legacy = save_party(
            party_type="Individual",
            display_name=f"ASOUD Digits Legacy {frappe.generate_hash(length=6)}",
            roles=["Customer"],
            company=company(),
            postal_code="1111111111",
        )["data"]["name"]
        clean = save_party(
            party_type="Individual",
            display_name=f"ASOUD Digits Clean {frappe.generate_hash(length=6)}",
            roles=["Customer"],
            company=company(),
            postal_code="2222222222",
        )["data"]["name"]
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": "Digits",
                "gender": "Male",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "company": company(),
                "status": "Active",
            }
        ).insert(ignore_permissions=True)
        # Values that bypassed the write boundary (legacy/import).
        frappe.db.set_value(
            "ASOUD Party Profile", legacy, "postal_code", "۹۸۷۷۶۶۶۶۶۶", update_modified=False
        )
        frappe.db.set_value(
            "Employee", employee.name, "cell_number", "۰۹۱۲۱۲۳۴۵۶۷", update_modified=False
        )

        execute()

        self.assertEqual(
            frappe.db.get_value("ASOUD Party Profile", legacy, "postal_code", cache=False),
            "9877666666",
        )
        self.assertEqual(
            frappe.db.get_value("ASOUD Party Profile", clean, "postal_code", cache=False),
            "2222222222",
        )
        self.assertEqual(
            frappe.db.get_value("Employee", employee.name, "cell_number", cache=False),
            "09121234567",
        )
