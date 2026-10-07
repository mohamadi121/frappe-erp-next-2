"""Supply template: the supply method decides the Material Request type, or no document."""

import frappe

from asoud_erp.integration_tests.fixtures import ITEM, SERVICE, warehouse
from asoud_erp.integration_tests.request_template_support import TemplateTestCase, weekday


def material_requests(request_name: str) -> list:
    return frappe.get_all("Material Request", filters={"asoud_request": request_name},
                          fields=["name", "material_request_type", "set_warehouse", "docstatus"])


class TestSupplyRequestTemplate(TemplateTestCase):
    def supply_values(self, method: str, **extra) -> dict:
        return {**self.requester(), "delivery_location": f"warehouse:{warehouse()}", "needed_date": weekday(7),
                "supply_method": method, "priority": "Normal", "reason": "نیاز واحد",
                "items": [{"item_code": ITEM, "qty": 3, "uom": "Nos", "description": "شرح"}], **extra}

    def approve_and_read(self, values: dict):
        name = self.create("supply", values, "تأمین کالا")["name"]
        self.assertRegex(name, r"^SP-\d{4}-\d{4}$")
        self.decide(name)
        return name, self.row(name)

    def test_purchase_method_creates_a_purchase_material_request(self):
        name, row = self.approve_and_read(self.supply_values("Purchase"))
        (mr,) = material_requests(name)
        self.assertEqual((mr.material_request_type, mr.set_warehouse, mr.docstatus),
                         ("Purchase", warehouse(), 0))
        self.assertEqual((row.native_status, row.native_name), ("Created", mr.name))

    def test_purchase_method_to_a_branch_uses_the_default_warehouse(self):
        values = self.supply_values("Purchase", delivery_location=f"branch:{self.branch}")
        name, _row = self.approve_and_read(values)
        (mr,) = material_requests(name)
        self.assertEqual(mr.set_warehouse, warehouse())

    def test_warehouse_method_creates_a_material_issue(self):
        name, _row = self.approve_and_read(self.supply_values("Warehouse"))
        (mr,) = material_requests(name)
        self.assertEqual(mr.material_request_type, "Material Issue")
        self.assertFalse(mr.set_warehouse)

    def test_transfer_method_creates_a_material_transfer_to_the_delivery_warehouse(self):
        name, _row = self.approve_and_read(self.supply_values("Transfer"))
        (mr,) = material_requests(name)
        self.assertEqual((mr.material_request_type, mr.set_warehouse), ("Material Transfer", warehouse()))
        self.assertFalse(frappe.db.get_value("Material Request", mr.name, "set_from_warehouse"))

    def test_contract_and_unspecified_create_no_document(self):
        for method in ("Contract", "Unspecified"):
            name, row = self.approve_and_read(self.supply_values(method))
            self.assertEqual(self.instance_status(name), "Completed", method)
            self.assertEqual((row.native_status, row.native_error), ("Skipped", "NO_NATIVE_DOCUMENT"), method)
            self.assertFalse(material_requests(name), method)

    def test_missing_supply_method_counts_as_unspecified(self):
        values = self.supply_values("Unspecified")
        values.pop("supply_method")
        name, row = self.approve_and_read(values)
        self.assertEqual(row.native_status, "Skipped")

    def test_transfer_needs_a_warehouse_delivery(self):
        values = self.supply_values("Transfer", delivery_location=f"branch:{self.branch}")
        with self.assertCode("DELIVERY_NOT_WAREHOUSE"):
            self.create("supply", values, "تأمین کالا")

    def test_service_items_are_refused_for_stock_methods(self):
        service_rows = [{"item_code": SERVICE, "qty": 1, "uom": "Nos"}]
        for method in ("Warehouse", "Transfer"):
            with self.assertCode("ITEM_NOT_STOCKABLE"):
                self.create("supply", self.supply_values(method, items=service_rows), "تأمین خدمت")
        # Services are fine when the method buys them.
        name, row = self.approve_and_read(self.supply_values("Purchase", items=service_rows))
        self.assertEqual(row.native_status, "Created")

    def test_invalid_delivery_location_is_refused(self):
        for bad in ("Stores", "room:1", "warehouse:No Such Warehouse"):
            with self.assertRaises(frappe.ValidationError):
                self.create("supply", self.supply_values("Purchase", delivery_location=bad), "تأمین کالا")
