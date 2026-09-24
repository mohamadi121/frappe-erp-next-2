import frappe

from asoud_erp.api.v1 import buying, stock
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, ITEM, SUPPLIER, APITestCase, leaf, warehouse


class TestStockAndBuying(APITestCase):
    def receive(self, qty=10, rate=120):
        return stock.create_stock_entry(self.company, "Material Receipt",
                                        [{"item_code": ITEM, "qty": qty, "rate": rate,
                                          "t_warehouse": warehouse()}], submit=1)["data"]

    def on_hand(self):
        rows = stock.stock_balance(self.company, warehouse=warehouse(), item_code=ITEM)["data"]
        return rows[0].actual_qty if rows else 0

    def test_receipt_issue_and_balance(self):
        before = self.on_hand()
        entry = self.receive()
        self.assertEqual((entry["docstatus"], entry["items"][0]["basic_rate"]), (1, 120))
        self.assertEqual(self.on_hand(), before + 10)
        stock.create_stock_entry(self.company, "Material Issue",
                                 [{"item_code": ITEM, "qty": 4, "s_warehouse": warehouse()}], submit=1)
        self.assertEqual(self.on_hand(), before + 6)
        item = stock.get_item(self.company, ITEM)["data"]
        self.assertEqual(item["actual_qty"], before + 6)
        listed = stock.list_items(self.company, search=ITEM)["data"]
        self.assertEqual(listed[0]["actual_qty"], before + 6)

    def test_warehouses_must_match_purpose(self):
        with self.assertRaises(frappe.ValidationError):
            stock.create_stock_entry(self.company, "Material Receipt",
                                     [{"item_code": ITEM, "qty": 1, "s_warehouse": warehouse()}])
        with self.assertRaises(frappe.ValidationError):
            stock.create_stock_entry(self.company, "Manufacture", [{"item_code": ITEM, "qty": 1}])

    def test_save_item_creates_and_updates(self):
        created = stock.save_item("مداد آزمایشی", leaf("Item Group"), "Nos", item_code="ASOUD-PENCIL",
                                  standard_rate=15)["data"]
        self.assertEqual(created["item_code"], "ASOUD-PENCIL")
        self.assertEqual(stock.get_item(self.company, "ASOUD-PENCIL")["data"]["selling_rate"], 15)
        updated = stock.save_item("مداد", leaf("Item Group"), "Nos", item_code="ASOUD-PENCIL")["data"]
        self.assertEqual(updated["item_name"], "مداد")

    def test_order_receive_and_bill(self):
        order = buying.create_purchase_order(self.company, SUPPLIER,
                                             [{"item_code": ITEM, "qty": 5, "rate": 90,
                                               "warehouse": warehouse()}],
                                             schedule_date=self.future(), submit=1)["data"]
        self.assertEqual((order["docstatus"], order["net_total"]), (1, 450))
        receipt = buying.create_purchase_receipt_from_order(order["name"], submit=1)["data"]
        self.assertEqual(receipt["items"][0]["qty"], 5)
        bill = buying.create_purchase_invoice_from_order(order["name"], bill_no="B-1", submit=1)["data"]
        self.assertEqual((bill["docstatus"], bill["outstanding_amount"]), (1, order["grand_total"]))
        state = buying.get_purchase_document("Purchase Order", order["name"])["data"]
        self.assertEqual((state["per_received"], state["per_billed"]), (100, 100))

    def test_order_from_material_request(self):
        request = frappe.get_doc({"doctype": "Material Request", "material_request_type": "Purchase",
                                  "company": self.company, "schedule_date": self.future(),
                                  "items": [{"item_code": ITEM, "qty": 3, "schedule_date": self.future(),
                                             "warehouse": warehouse()}]}).insert()
        request.submit()
        order = buying.create_purchase_order_from_request(request.name, SUPPLIER)["data"]
        self.assertEqual(order["items"][0]["material_request"], request.name)
        self.assertEqual(order["items"][0]["qty"], 3)

    def test_direct_purchase_invoice_and_list(self):
        bill = buying.create_purchase_invoice(self.company, SUPPLIER, [{"item_code": ITEM, "qty": 2, "rate": 80}],
                                              bill_no="B-2")["data"]
        self.assertEqual((bill["docstatus"], bill["net_total"]), (0, 160))
        rows = buying.list_purchase_documents(self.company, "Purchase Invoice", supplier=SUPPLIER)["data"]
        self.assertIn(bill["name"], [row.name for row in rows])
        with self.assertRaises(frappe.ValidationError):
            buying.list_purchase_documents(self.company, "Journal Entry")

    def test_employee_cannot_move_stock(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            self.receive()
