"""Pure tests for the demo-seed markers and safety guard (no site needed)."""

import unittest

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
        self.assertEqual(len(set(ids)), 4)
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


if __name__ == "__main__":
    unittest.main()
