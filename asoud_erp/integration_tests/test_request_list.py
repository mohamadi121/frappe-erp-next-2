"""`list_my_requests`: status tabs and counts, filters, search, pagination and scoping."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition, patched_specs, seed_test_templates
from asoud_erp.integration_tests.request_helpers import act, clear_request_records, create
from asoud_erp.integration_tests.tenancy import EMPLOYEE_A_USER, setup_tenancy


class TestRequestList(APITestCase):
    def setUp(self):
        super().setUp()
        clear_request_records()
        self.specs = patched_specs()
        self.specs.__enter__()
        self.definitions = seed_test_templates(self.company)
        self.custom, _stages = make_definition(self.company)
        # pending, approved, rejected, cancelled (custom type) and returned.
        self.pending = create(self.company, template_key="purchase", subject="خرید تجهیزات ICU",
                              values={"priority": "High", "reason": "تجهیز بخش"})
        self.approved = create(self.company, template_key="purchase", subject="خرید کاغذ")
        act(self.approved["workflow_instance"], "Approve")
        self.rejected = create(self.company, template_key="leave")
        act(self.rejected["workflow_instance"], "Reject", comment="مقدور نیست")
        self.cancelled = create(self.company, definition=self.custom, subject="درخواست لغوشده")
        frappe.set_user(EMPLOYEE_USER)
        workflow_request.cancel_request(self.cancelled["name"], "نیاز نیست")
        self.returned = create(self.company, template_key="purchase", subject="خرید اصلاحی")
        act(self.returned["workflow_instance"], "Return", comment="اصلاح شود")
        frappe.set_user(EMPLOYEE_USER)

    def tearDown(self):
        self.specs.__exit__()
        super().tearDown()

    def _list(self, **kwargs):
        return workflow_request.list_my_requests(company=self.company, **kwargs)

    def _names(self, **kwargs):
        return {row["name"] for row in self._list(**kwargs)["data"]}

    def test_tabs_and_counts(self):
        everything = self._list()
        self.assertEqual(everything["meta"]["counts"], {"all": 5, "pending": 2, "approved": 1, "rejected": 1})
        self.assertEqual(everything["meta"]["total"], 5)
        self.assertEqual(self._names(status_group="pending"), {self.pending["name"], self.returned["name"]})
        self.assertEqual(self._names(status_group="approved"), {self.approved["name"]})
        self.assertEqual(self._names(status_group="rejected"), {self.rejected["name"]})
        self.assertEqual(self._names(), {r["name"] for r in (self.pending, self.approved, self.rejected,
                                                            self.cancelled, self.returned)})
        tab = self._list(status_group="pending")
        self.assertEqual((tab["meta"]["total"], tab["meta"]["counts"]["all"]), (2, 5))
        by_name = {row["name"]: row for row in everything["data"]}
        self.assertEqual(by_name[self.returned["name"]]["status_key"], "returned")
        self.assertEqual(by_name[self.cancelled["name"]]["status_key"], "cancelled")
        self.assertEqual(by_name[self.cancelled["name"]]["status_group"], "")
        self.assertEqual(by_name[self.rejected["name"]]["summary"]["rejection_reason"], "مقدور نیست")
        self.assertEqual(by_name[self.approved["name"]]["status"], "Completed")

    def test_filters_and_counts_follow_them_but_not_the_tab(self):
        self.assertEqual(self._names(template_key="leave"), {self.rejected["name"]})
        purchases = self._list(template_key="purchase")
        self.assertEqual(purchases["meta"]["counts"], {"all": 3, "pending": 2, "approved": 1, "rejected": 0})
        self.assertEqual(self._names(priority="High"), {self.pending["name"]})
        self.assertEqual(self._names(search="ICU"), {self.pending["name"]})
        self.assertEqual(self._names(search=self.approved["name"]), {self.approved["name"]})
        self.assertEqual(self._names(search="کاغذ", status_group="approved"), {self.approved["name"]})
        self.assertEqual(self._names(search="no-such-text"), set())
        today = nowdate()
        self.assertEqual(len(self._names(date_from=today, date_to=today)), 5)
        self.assertEqual(self._names(date_from=add_days(today, 1)), set())
        self.assertEqual(self._names(date_to=add_days(today, -1)), set())
        self.assertEqual(self._list(search="ICU")["meta"]["counts"]["all"], 1)

    def test_pagination(self):
        pages = [self._list(limit_start=start, limit_page_length=2) for start in (0, 2, 4)]
        self.assertEqual([len(page["data"]) for page in pages], [2, 2, 1])
        self.assertEqual({page["meta"]["total"] for page in pages}, {5})
        names = [row["name"] for page in pages for row in page["data"]]
        self.assertEqual(len(set(names)), 5)
        creations = [row["creation"] for page in pages for row in page["data"]]
        self.assertEqual(creations, sorted(creations, reverse=True))
        self.assertEqual(self._list(limit_page_length=1000)["meta"]["limit_page_length"], 100)

    def test_list_rows_keep_the_legacy_keys_and_add_the_new_ones(self):
        row = self._list(limit_page_length=1)["data"][0]
        for key in ("name", "company", "workflow_definition", "request_type", "subject", "priority", "required_by",
                    "project", "department", "workflow_instance", "status", "request_id", "display_status", "owner",
                    "requester_name", "creation", "number", "template_key", "status_key", "status_label",
                    "status_group", "item_count", "attachment_count", "summary", "native_status"):
            self.assertIn(key, row)
        self.assertNotIn("values", row)
        self.assertNotIn("attachments", row)

    def test_no_per_row_get_doc_and_a_constant_number_of_queries(self):
        self._list()  # warm the caches
        with patch("frappe.get_doc", wraps=frappe.get_doc) as get_doc, \
                patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
            self._list(limit_page_length=2)
            small = sql.call_count
            sql.reset_mock()
            self._list(limit_page_length=5)
            large = sql.call_count
        self.assertEqual(small, large)
        self.assertFalse([call for call in get_doc.call_args_list
                          if call.args and call.args[0] == "ASOUD Workflow Request"])

    def test_another_company_and_other_users_are_out_of_reach(self):
        second = setup_tenancy()["second"]
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.list_my_requests(company=second)
        frappe.set_user(APPROVER_USER)
        theirs = workflow_request.list_my_requests(company=self.company)
        self.assertEqual(theirs["data"], [])
        self.assertEqual(theirs["meta"]["counts"], {"all": 0, "pending": 0, "approved": 0, "rejected": 0})
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.list_my_requests(company=second)

    def test_bad_arguments_are_refused(self):
        for kwargs in ({"status_group": "everything"}, {"priority": "Whenever"}):
            with self.assertRaises(frappe.ValidationError):
                workflow_request.list_my_requests(company=self.company, **kwargs)
