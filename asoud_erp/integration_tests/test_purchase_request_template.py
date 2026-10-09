"""Purchase template: numbering, validation and the Material Request created after approval."""

import re

import frappe
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import workflow_request
from asoud_erp.integration_tests.fixtures import ITEM, SERVICE, warehouse
from asoud_erp.integration_tests.request_template_support import TemplateTestCase
from asoud_erp.services import request_native_documents as native


def material_requests(request_name: str) -> list:
    return frappe.get_all("Material Request", filters={"asoud_request": request_name}, pluck="name")


class TestPurchaseRequestTemplate(TemplateTestCase):
    def test_create_is_idempotent_and_numbered(self):
        values = self.purchase_values()
        first = self.create("purchase", values, "خرید تجهیزات ICU", request_id="purchase-idem-0001")
        again = self.create("purchase", values, "خرید تجهیزات ICU", request_id="purchase-idem-0001")
        self.assertEqual(first["name"], again["name"])
        self.assertRegex(first["name"], r"^PR-\d{4}-\d{4}$")
        row = self.row(first["name"])
        self.assertEqual((row.template_key, row.status_key, row.priority), ("purchase", "submitted", "High"))
        self.assertEqual((str(row.required_by), row.department), (values["needed_date"], self.department))
        self.assertEqual(frappe.db.count("ASOUD Workflow Request", {"request_id": "purchase-idem-0001"}), 1)
        # The same request_id with another payload is a conflict.
        with self.assertCode("REQUEST_ID_CONFLICT"):
            self.create("purchase", {**values, "reason": "changed"}, "خرید تجهیزات ICU",
                        request_id="purchase-idem-0001")

    def test_approval_creates_exactly_one_material_request(self):
        data = self.create("purchase", self.purchase_values(), "خرید تجهیزات ICU")
        name = data["name"]
        self.assertFalse(material_requests(name))
        self.decide(name)
        self.assertEqual(self.instance_status(name), "Completed")
        row = self.row(name)
        self.assertEqual((row.status_key, row.native_status, row.native_doctype), ("approved", "Created",
                                                                                   "Material Request"))
        self.assertEqual(material_requests(name), [row.native_name])
        mr = frappe.get_doc("Material Request", row.native_name)
        self.assertEqual((mr.material_request_type, mr.docstatus, mr.company), ("Purchase", 0, self.company))
        self.assertEqual(str(mr.schedule_date), self.purchase_values()["needed_date"])
        self.assertEqual(mr.set_warehouse, warehouse())
        self.assertEqual(len(mr.items), 1)
        item = mr.items[0]
        self.assertEqual((item.item_code, item.qty, item.uom, item.stock_uom, item.conversion_factor),
                         (ITEM, 2, "Nos", "Nos", 1))
        self.assertEqual(item.description, "شرح\nیادداشت")
        self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": "Material Request",
                                                     "reference_name": mr.name, "comment_type": "Comment"}))
        # A second dispatch, even with the result forgotten, finds the document by asoud_request.
        request = frappe.get_doc("ASOUD Workflow Request", name)
        native.dispatch(request)
        frappe.db.set_value("ASOUD Workflow Request", name, "native_status", "")
        native.dispatch(frappe.get_doc("ASOUD Workflow Request", name))
        self.assertEqual(material_requests(name), [mr.name])
        self.assertEqual(self.row(name).native_status, "Created")

    def test_project_and_cost_center_go_to_the_rows(self):
        cost_center = frappe.get_all("Cost Center", filters={"company": self.company, "is_group": 0},
                                     pluck="name", limit=1)[0]
        name = self.create("purchase", self.purchase_values(cost_center=cost_center))["name"]
        self.decide(name)
        mr = frappe.get_doc("Material Request", self.row(name).native_name)
        self.assertEqual(mr.items[0].cost_center, cost_center)

    def test_rejected_request_creates_nothing(self):
        name = self.create("purchase", self.purchase_values())["name"]
        self.decide(name, "Reject", "بودجه نیست")
        self.assertEqual(self.row(name).status_key, "rejected")
        self.assertFalse(material_requests(name))
        self.assertFalse(self.row(name).native_status)

    def test_cost_center_required_by_the_company_setting(self):
        frappe.db.set_value("Company", self.company, "asoud_request_cost_center_required", 1)
        with self.assertCode("COST_CENTER_REQUIRED"):
            self.create("purchase", self.purchase_values())
        cost_center = frappe.get_all("Cost Center", filters={"company": self.company, "is_group": 0},
                                     pluck="name", limit=1)[0]
        self.assertRegex(self.create("purchase", self.purchase_values(cost_center=cost_center))["name"],
                         r"^PR-\d{4}-\d{4}$")

    def test_needed_date_in_the_past_is_refused(self):
        with self.assertCode("DATE_IN_PAST"):
            self.create("purchase", self.purchase_values(needed_date=str(add_days(nowdate(), -1))))

    def test_requester_must_be_the_signed_in_user(self):
        with self.assertCode("REQUESTER_MISMATCH"):
            self.create("purchase", {**self.purchase_values(), "requester": "asoud.approver@example.com"})

    def test_native_failure_never_unapproves_and_retry_creates_once(self):
        # ERPNext refuses a stock item row without a warehouse: no default warehouse, no document.
        frappe.db.set_single_value("Stock Settings", "default_warehouse", None)
        name = self.create("purchase", self.purchase_values())["name"]
        self.decide(name)
        row = self.row(name)
        self.assertEqual(self.instance_status(name), "Completed")
        self.assertEqual((row.status_key, row.native_status), ("approved", "Failed"))
        self.assertTrue(row.native_error)
        self.assertFalse(material_requests(name))
        self.assertNotified(name, frappe.session.user)
        # The cause is removed; an administrator retries, twice, and one document results.
        frappe.db.set_single_value("Stock Settings", "default_warehouse", warehouse())
        frappe.set_user("Administrator")
        workflow_request.create_native_document(name)
        self.assertEqual(self.row(name).native_status, "Created")
        with self.assertRaises(frappe.ValidationError):
            workflow_request.create_native_document(name)  # NATIVE_NOT_RETRYABLE
        self.assertEqual(len(material_requests(name)), 1)

    def test_service_items_are_allowed_without_a_warehouse(self):
        frappe.db.set_single_value("Stock Settings", "default_warehouse", None)
        values = self.purchase_values(items=[{"item_code": SERVICE, "qty": 1, "uom": "Nos"}])
        name = self.create("purchase", values)["name"]
        self.decide(name)
        self.assertEqual(self.row(name).native_status, "Created")

    def test_request_number_series_and_options(self):
        options = workflow_request.request_options(company=self.company)["data"]
        purchase = next(row for row in options if row.get("template_key") == "purchase")
        self.assertEqual(purchase["number_prefix"], "PR")
        defaults = {field["key"]: field.get("default_value") for field in purchase["fields"]}
        self.assertEqual((defaults["requester"], defaults["org_unit"]), (frappe.session.user, self.department))
        self.assertTrue(re.match(r"^PR-\d{4}-\d{4}$", self.create("purchase", self.purchase_values())["name"]))
