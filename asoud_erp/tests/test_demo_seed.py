"""Pure tests for the demo-seed markers and safety guard (no site needed)."""

import unittest
from datetime import date

from asoud_erp.demo import markers as m


class TestDemoSiteGuard(unittest.TestCase):
    def test_only_test_and_demo_sites_are_allowed(self):
        for site in ("asoud.test", "test.localhost", "demo.local", "my-DEMO-site", "TEST"):
            self.assertTrue(m.site_allowed(site), site)
        for site in ("erp.local", "prod.example.com", "", None):
            self.assertFalse(m.site_allowed(site), str(site))

    def test_guard_refuses_real_site_even_with_developer_mode(self):
        error = m.guard_error("erp.local", True, False)
        self.assertIn("test", error)
        self.assertIn("demo", error)

    def test_guard_refuses_without_developer_mode(self):
        error = m.guard_error("asoud.test", False, False)
        self.assertIn("developer_mode", error)

    def test_guard_passes_on_test_site_with_developer_mode(self):
        self.assertIsNone(m.guard_error("asoud.test", True, False))

    def test_force_overrides_both_guards(self):
        self.assertIsNone(m.guard_error("erp.local", False, True))
        self.assertIsNone(m.guard_error("erp.local", True, True))


class TestDemoNaming(unittest.TestCase):
    def test_company_identity(self):
        self.assertEqual((m.COMPANY, m.ABBR, m.CURRENCY, m.COUNTRY),
                         ("شرکت نمونه آسود", "ASDM", "IRR", "Iran"))

    def test_twelve_employees_with_a_valid_reporting_chain(self):
        self.assertEqual(len(m.EMPLOYEES), 12)
        for index, (name, dept_no, desig_no, reports_to, gender) in enumerate(m.EMPLOYEES):
            self.assertTrue(name.strip(), f"employee {index} needs a name")
            self.assertIn(gender, ("Male", "Female"))
            self.assertTrue(0 <= desig_no < len(m.DESIGNATIONS))
            if dept_no is not None:
                self.assertTrue(0 <= dept_no < len(m.DEPARTMENTS))
            if reports_to is not None:
                # Managers come before their reports, so chains resolve in one pass.
                self.assertTrue(0 <= reports_to < index)

    def test_four_departments_and_users(self):
        self.assertEqual(len(m.DEPARTMENTS), 4)
        self.assertEqual(len(m.USERS), 4)
        emails = [m.demo_email(local) for local, _i, _r, _n in m.USERS]
        self.assertEqual(len(set(emails)), 4)
        self.assertTrue(all(email.endswith("@" + m.EMAIL_DOMAIN) for email in emails))
        for _local, emp_index, roles, _note in m.USERS:
            self.assertTrue(0 <= emp_index < len(m.EMPLOYEES))
            self.assertTrue(roles)

    def test_designations_carry_the_display_marker(self):
        self.assertGreaterEqual(len(m.DESIGNATIONS), len(m.DEPARTMENTS))
        self.assertTrue(all(m.FA_MARKER in name for name in m.DESIGNATIONS))

    def test_shared_masters_are_prefixed_or_marked(self):
        codes = [code for code, _t, _s, _r in m.ITEMS]
        self.assertEqual(len(set(codes)), len(codes))
        self.assertTrue(all(code.startswith(m.PREFIX) for code in codes))
        leave_names = [name for name, _max_leaves in m.LEAVE_TYPES]
        self.assertEqual(len(set(leave_names)), len(leave_names))
        self.assertTrue(all(m.FA_MARKER in name for name in leave_names))
        self.assertIn(m.FA_MARKER, m.SALARY_STRUCTURE)
        self.assertIn(m.FA_MARKER, m.SALARY_EARNING)
        self.assertTrue(all(m.FA_MARKER in name for name in m.CUSTOMERS + m.SUPPLIERS))

    def test_request_ids_are_unique_and_prefixed(self):
        ids = list(m.REQUEST_IDS.values())
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(set(m.REQUEST_IDS), {
            "leave-approved", "leave-pending", "leave-cancelled",
            "purchase-approved", "purchase-rejected", "supply-approved"})
        self.assertTrue(all(len(request_id) >= 8 for request_id in ids))

    def test_demo_price_lists_are_prefixed_and_distinct(self):
        self.assertNotEqual(m.PRICE_LIST_SELLING, m.PRICE_LIST_BUYING)
        self.assertTrue(m.PRICE_LIST_SELLING.startswith(m.PREFIX))
        self.assertTrue(m.PRICE_LIST_BUYING.startswith(m.PREFIX))


class TestDemoFiscalYearRules(unittest.TestCase):
    def test_global_year_is_used_without_restricting_it(self):
        self.assertEqual(m.fiscal_year_seed_action([], m.COMPANY), "use")

    def test_restricted_year_gets_the_demo_company_when_missing(self):
        self.assertEqual(m.fiscal_year_seed_action(["Other"], m.COMPANY), "append")

    def test_restricted_year_with_demo_company_is_reused(self):
        self.assertEqual(m.fiscal_year_seed_action(["Other", m.COMPANY], m.COMPANY), "present")

    def test_reset_keeps_global_or_unrelated_years(self):
        self.assertEqual(
            m.fiscal_year_reset_action("2026", "2026-01-01", "2026-12-31", [], m.COMPANY),
            "keep",
        )
        self.assertEqual(
            m.fiscal_year_reset_action("2026", "2026-01-01", "2026-12-31", ["Other"], m.COMPANY),
            "keep",
        )

    def test_reset_removes_only_the_demo_row_from_preexisting_years(self):
        self.assertEqual(
            m.fiscal_year_reset_action(
                "2026", "2026-01-01", "2026-12-31", ["Other", m.COMPANY], m.COMPANY
            ),
            "remove_row",
        )
        self.assertEqual(
            m.fiscal_year_reset_action(
                "FY 2026", "2026-01-01", "2026-12-31", [m.COMPANY], m.COMPANY
            ),
            "remove_row",
        )

    def test_reset_deletes_only_seed_shaped_year_owned_by_demo_company(self):
        self.assertEqual(
            m.fiscal_year_reset_action("2026", "2026-01-01", "2026-12-31", [m.COMPANY], m.COMPANY),
            "delete",
        )


class TestDemoLeaveDates(unittest.TestCase):
    YEAR_END = date(2026, 12, 31)

    def test_dates_are_in_the_future_and_do_not_overlap(self):
        dates = m.demo_leave_dates(date(2026, 10, 6), self.YEAR_END)
        self.assertEqual(dates["pending"], date(2026, 10, 7))
        self.assertEqual(dates["cancelled"], (date(2026, 10, 9), date(2026, 10, 10)))
        self.assertEqual(dates["approved"], (date(2026, 10, 13), date(2026, 10, 15)))
        self.assertLess(dates["pending"], dates["cancelled"][0])
        self.assertLess(dates["cancelled"][1], dates["approved"][0])

    def test_hourly_leave_skips_holidays(self):
        dates = m.demo_leave_dates(date(2026, 10, 6), self.YEAR_END, {"2026-10-07"})
        self.assertEqual(dates["pending"], date(2026, 10, 8))
        # ...but never runs into the cancelled leave (then the leave requests are skipped).
        self.assertIsNone(m.demo_leave_dates(date(2026, 10, 6), self.YEAR_END, {"2026-10-07", "2026-10-08"}))

    def test_last_days_of_the_year_have_no_room(self):
        self.assertIsNotNone(m.demo_leave_dates(date(2026, 12, 22), self.YEAR_END))
        self.assertIsNone(m.demo_leave_dates(date(2026, 12, 23), self.YEAR_END))
        self.assertIsNone(m.demo_leave_dates(date(2026, 12, 31), self.YEAR_END))

    def test_leave_categories_cover_the_demo_leave_types(self):
        self.assertEqual(len(m.LEAVE_CATEGORIES), len(m.LEAVE_TYPES))
        self.assertEqual(m.LEAVE_CATEGORIES, ["annual", "sick"])

    def test_system_templates_replace_the_legacy_demo_definitions(self):
        self.assertEqual(m.SYSTEM_TEMPLATE_KEYS, ("purchase", "supply", "leave"))
        self.assertEqual(m.SYSTEM_NATIVE_WORKFLOW, "ASOUD-SYSTEM-REQUEST-NATIVE")
        self.assertEqual(m.LEGACY_WORKFLOW_CODES, ("ASOUD-DEMO-LEAVE", "ASOUD-DEMO-PURCHASE"))


if __name__ == "__main__":
    unittest.main()
