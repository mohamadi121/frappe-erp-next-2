import frappe

from asoud_erp.api.v1 import sales_orders, stock
from asoud_erp.integration_tests.fixtures import (
    CUSTOMER,
    EMPLOYEE_USER,
    ITEM,
    SERVICE,
    APITestCase,
    warehouse,
)


class TestSalesPipeline(APITestCase):
    def test_quotation_to_order_to_delivery_to_invoice(self):
        stock.create_stock_entry(self.company, "Material Receipt",
                                 [{"item_code": ITEM, "qty": 5, "rate": 100, "t_warehouse": warehouse()}],
                                 submit=1)
        quote = sales_orders.create_quotation(self.company, CUSTOMER,
                                              [{"item_code": ITEM, "qty": 2, "warehouse": warehouse()}],
                                              valid_till=self.future(30), submit=1)["data"]
        self.assertEqual((quote["docstatus"], quote["items"][0]["rate"]), (1, 250))
        order = sales_orders.create_sales_order_from_quotation(quote["name"], self.future(), submit=1)["data"]
        self.assertEqual(order["items"][0]["prevdoc_docname"], quote["name"])
        delivery = sales_orders.create_delivery_note_from_order(order["name"], submit=1)["data"]
        self.assertEqual((delivery["docstatus"], delivery["items"][0]["against_sales_order"]),
                         (1, order["name"]))
        invoice = sales_orders.create_sales_invoice_from("Delivery Note", delivery["name"], submit=1)["data"]
        self.assertEqual(invoice["grand_total"], delivery["grand_total"])
        state = sales_orders.get_sales_document("Sales Order", order["name"])["data"]
        self.assertEqual((state["per_delivered"], state["per_billed"]), (100, 100))

    def test_direct_order_billed_from_order(self):
        order = sales_orders.create_sales_order(self.company, CUSTOMER, [{"item_code": SERVICE, "qty": 1}],
                                                delivery_date=self.future(), submit=1)["data"]
        invoice = sales_orders.create_sales_invoice_from("Sales Order", order["name"])["data"]
        self.assertEqual((invoice["docstatus"], invoice["net_total"]), (0, 1000))
        rows = sales_orders.list_sales_documents(self.company, "Sales Order", customer=CUSTOMER)["data"]
        self.assertIn(order["name"], [row.name for row in rows])

    def test_rules(self):
        draft = sales_orders.create_quotation(self.company, CUSTOMER, [{"item_code": SERVICE, "qty": 1}])["data"]
        with self.assertRaises(frappe.ValidationError):
            sales_orders.create_sales_order_from_quotation(draft["name"], self.future())
        with self.assertRaises(frappe.ValidationError):
            sales_orders.create_sales_invoice_from("Quotation", draft["name"])
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            sales_orders.list_sales_documents(self.company, "Quotation")
