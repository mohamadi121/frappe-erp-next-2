"""Request numbers: `PR-<jalali year>-0001`, independent series, `REQ-` continuity."""

import re

import frappe
from frappe.utils import getdate, nowdate

from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition, patched_specs, seed_test_templates
from asoud_erp.integration_tests.request_helpers import create
from asoud_erp.services.jalali import current_jalali_year


class TestRequestNumbering(APITestCase):
    def setUp(self):
        super().setUp()
        self.specs = patched_specs()
        self.specs.__enter__()
        self.definitions = seed_test_templates(self.company)
        self.year = current_jalali_year(getdate(nowdate()))

    def tearDown(self):
        self.specs.__exit__()
        super().tearDown()

    def _reset_series(self, key: str, current: int | None = None):
        frappe.db.sql("delete from `tabSeries` where name = %s", key)
        if current is not None:
            frappe.db.sql("insert into `tabSeries` (name, `current`) values (%s, %s)", (key, current))

    def _current(self, key: str):
        rows = frappe.db.sql("select `current` from `tabSeries` where name = %s", key)
        return rows[0][0] if rows else None

    def test_first_requests_count_from_one_in_the_jalali_year(self):
        self._reset_series(f"PR-{self.year}-")
        first = create(self.company, template_key="purchase")
        second = create(self.company, template_key="purchase")
        self.assertEqual(first["name"], f"PR-{self.year}-0001")
        self.assertEqual(second["name"], f"PR-{self.year}-0002")
        self.assertEqual(first["number"], first["name"])
        self.assertRegex(first["name"], r"^PR-\d{4}-\d{4}$")

    def test_each_prefix_has_its_own_series(self):
        self._reset_series(f"PR-{self.year}-")
        self._reset_series(f"LV-{self.year}-")
        purchase = create(self.company, template_key="purchase")
        leave = create(self.company, template_key="leave")
        another = create(self.company, template_key="purchase")
        self.assertEqual([purchase["name"], leave["name"], another["name"]],
                         [f"PR-{self.year}-0001", f"LV-{self.year}-0001", f"PR-{self.year}-0002"])

    def test_a_new_year_starts_a_new_series(self):
        self._reset_series(f"PR-{self.year}-", 41)
        self._reset_series(f"PR-{self.year + 1}-")
        self.assertEqual(create(self.company, template_key="purchase")["name"], f"PR-{self.year}-0042")
        self.assertIsNone(self._current(f"PR-{self.year + 1}-"))
        self.assertEqual(self._current(f"PR-{self.year}-"), 42)

    def test_custom_request_types_continue_the_legacy_series(self):
        definition, _stages = make_definition(self.company)
        self._reset_series("REQ-", 7)
        created = create(self.company, definition=definition)
        self.assertEqual(created["name"], "REQ-00008")
        self.assertTrue(re.fullmatch(r"REQ-\d{5}", created["number"]))
        self.assertEqual(self._current("REQ-"), 8)
