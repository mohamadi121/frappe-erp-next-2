import frappe

from asoud_erp.api.v1 import payments, selling
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    CUSTOMER,
    EMPLOYEE_USER,
    ITEM,
    SERVICE,
    APITestCase,
)


class TestSellingAndPayments(APITestCase):
    def invoice(self, **changes):
        data = dict(company=self.company, customer=CUSTOMER,
                    items=[{"item_code": SERVICE, "qty": 2}, {"item_code": ITEM, "qty": 1, "rate": 300}])
        data.update(changes)
        return selling.create_sales_invoice(**data)["data"]

    def test_invoice_is_priced_and_totalled_by_erpnext(self):
        draft = self.invoice()
        self.assertEqual(draft["docstatus"], 0)
        service, item = draft["items"]
        self.assertEqual(service["rate"], 1000)  # from the Standard Selling price list
        self.assertEqual(item["rate"], 300)      # an explicit rate is kept
        self.assertEqual(draft["net_total"], 2300)
        # The company's default sales tax template is applied by ERPNext.
        self.assertEqual(draft["grand_total"], draft["net_total"] + draft["total_taxes_and_charges"])
        submitted = selling.submit_sales_invoice(draft["name"])["data"]
        self.assertEqual((submitted["docstatus"], submitted["outstanding_amount"]),
                         (1, submitted["rounded_total"] or submitted["grand_total"]))
        listed = selling.list_sales_invoices(self.company, customer=CUSTOMER)["data"]
        self.assertIn(draft["name"], [row.name for row in listed])

    def test_item_price_comes_from_erpnext(self):
        price = selling.get_item_price(self.company, SERVICE, customer=CUSTOMER, qty=3)["data"]
        self.assertEqual((price["price_list_rate"], price["rate"], price["uom"]), (1000, 1000, "Nos"))

    def test_return_and_cancel(self):
        invoice = self.invoice(submit=1)
        credit = selling.create_sales_return(invoice["name"], submit=1)["data"]
        self.assertEqual((credit["is_return"], credit["return_against"]), (1, invoice["name"]))
        self.assertEqual(credit["grand_total"], -invoice["grand_total"])
        other = self.invoice(submit=1)
        self.assertEqual(selling.cancel_sales_invoice(other["name"])["data"]["docstatus"], 2)

    def test_invalid_lines_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.invoice(items=[{"item_code": SERVICE, "qty": 0}])

    def test_payment_settles_an_invoice(self):
        invoice = self.invoice(submit=1)
        outstanding = payments.list_outstanding_documents(self.company, "Customer", CUSTOMER)["data"]
        self.assertIn(invoice["name"], [row["reference_name"] for row in outstanding])
        due = invoice["outstanding_amount"]
        entry = payments.create_payment_entry(
            self.company, "Receive", "Customer", CUSTOMER, due, "Cash",
            references=[{"reference_doctype": "Sales Invoice", "reference_name": invoice["name"],
                         "allocated_amount": due}], submit=1)["data"]
        self.assertEqual((entry["docstatus"], entry["paid_amount"], entry["unallocated_amount"]), (1, due, 0))
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice["name"], "outstanding_amount"), 0)
        self.assertEqual(payments.get_payment_entry(entry["name"])["data"]["references"][0]["allocated_amount"],
                         due)

    def test_advance_receipt_without_reference(self):
        entry = payments.create_payment_entry(self.company, "Receive", "Customer", CUSTOMER, 500, "Cash")["data"]
        self.assertEqual((entry["docstatus"], entry["unallocated_amount"]), (0, 500))
        self.assertEqual(payments.submit_payment_entry(entry["name"])["data"]["docstatus"], 1)

    def test_over_allocation_is_rejected(self):
        invoice = self.invoice(submit=1)
        with self.assertRaises(frappe.ValidationError):
            payments.create_payment_entry(
                self.company, "Receive", "Customer", CUSTOMER, 100, "Cash",
                references=[{"reference_doctype": "Sales Invoice", "reference_name": invoice["name"],
                             "allocated_amount": 200}])

    def test_roles_are_enforced(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            self.invoice()
        with self.assertRaises(frappe.PermissionError):
            payments.payment_options(self.company)
        frappe.set_user(ACCOUNTANT_USER)
        options = payments.payment_options(self.company)["data"]
        cash = next(row for row in options["modes_of_payment"] if row["name"] == "Cash")
        self.assertTrue(cash["account"])
