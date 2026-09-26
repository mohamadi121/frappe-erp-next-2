import frappe

from asoud_erp.api.v1 import pos, stock
from asoud_erp.integration_tests.fixtures import CUSTOMER, EMPLOYEE_USER, ITEM, APITestCase, abbr, warehouse

PROFILE = "ASOUD Test POS"


def setup_profile(company: str) -> None:
    if frappe.db.exists("POS Profile", PROFILE):
        return
    frappe.get_doc({
        "doctype": "POS Profile", "name": PROFILE, "company": company, "warehouse": warehouse(),
        "selling_price_list": "Standard Selling", "customer": CUSTOMER,
        "currency": frappe.get_cached_value("Company", company, "default_currency"),
        "write_off_account": f"Write Off - {abbr()}", "write_off_cost_center": f"Main - {abbr()}",
        "payments": [{"mode_of_payment": "Cash", "default": 1}],
    }).insert()


class TestPointOfSale(APITestCase):
    def setUp(self):
        super().setUp()
        setup_profile(self.company)
        stock.create_stock_entry(self.company, "Material Receipt",
                                 [{"item_code": ITEM, "qty": 20, "rate": 100, "t_warehouse": warehouse()}],
                                 submit=1)

    def test_session_sale_and_closing(self):
        options = pos.pos_options(self.company)["data"]
        self.assertIn(PROFILE, [row["name"] for row in options["profiles"]])
        items = pos.get_pos_items(PROFILE, search_term=ITEM)["data"]
        self.assertEqual(items[0]["price_list_rate"], 250)
        session = pos.create_pos_session(PROFILE, [{"mode_of_payment": "Cash", "amount": 1000}])["data"]
        self.assertEqual(pos.get_open_pos_session(PROFILE)["data"].name, session["name"])
        with self.assertRaises(frappe.ValidationError):
            pos.create_pos_session(PROFILE)
        sale = pos.create_pos_invoice(PROFILE, [{"item_code": ITEM, "qty": 2}],
                                      [{"mode_of_payment": "Cash", "amount": 1000}])["data"]
        self.assertEqual((sale["docstatus"], sale["net_total"]), (1, 500))
        self.assertAlmostEqual(sale["change_amount"], 1000 - (sale["rounded_total"] or sale["grand_total"]))
        self.assertEqual([row["name"] for row in pos.list_pos_invoices(session["name"])["data"]], [sale["name"]])
        closed = pos.close_pos_session(session["name"])["data"]
        self.assertEqual(closed["invoices"], 1)
        cash = closed["payment_reconciliation"][0]
        self.assertEqual((cash["opening_amount"], cash["difference"]), (1000, 0))
        self.assertIsNone(pos.get_open_pos_session(PROFILE)["data"])

    def test_sale_needs_an_open_session_and_rights(self):
        with self.assertRaises(frappe.ValidationError):
            pos.create_pos_invoice(PROFILE, [{"item_code": ITEM, "qty": 1}], [{"mode_of_payment": "Cash",
                                                                               "amount": 300}])
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            pos.create_pos_session(PROFILE)
