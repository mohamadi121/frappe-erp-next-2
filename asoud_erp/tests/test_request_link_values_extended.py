"""System Select sources and Item Table row options, against a stubbed frappe."""

import importlib
import sys
import types
from types import SimpleNamespace

import pytest

ITEMS = {
    "ICU-MON-01": {"item_name": "مانیتور ICU", "stock_uom": "Nos", "has_variants": 0, "disabled": 0,
                   "end_of_life": None, "variant_of": None, "is_stock_item": 1, "is_purchase_item": 1},
    "SERVICE-01": {"item_name": "نصب", "stock_uom": "Nos", "has_variants": 0, "disabled": 0,
                   "end_of_life": None, "variant_of": None, "is_stock_item": 0, "is_purchase_item": 1},
    "INTERNAL-01": {"item_name": "مصرفی", "stock_uom": "Nos", "has_variants": 0, "disabled": 0,
                    "end_of_life": None, "variant_of": None, "is_stock_item": 1, "is_purchase_item": 0},
}
# (doctype, name) -> row; `exists` matches every given filter against the row.
RECORDS = {
    ("Cost Center", "Main - WP"): {"company": "WP", "is_group": 0, "disabled": 0},
    ("Cost Center", "Old - WP"): {"company": "WP", "is_group": 0, "disabled": 1},
    ("Cost Center", "Group - WP"): {"company": "WP", "is_group": 1, "disabled": 0},
    ("Cost Center", "Other - OC"): {"company": "OC", "is_group": 0, "disabled": 0},
    ("Project", "PRJ-1"): {"company": "WP", "status": "Open"},
    ("Project", "PRJ-2"): {"company": "WP", "status": "Completed"},
    ("Warehouse", "Stores - WP"): {"company": "WP", "is_group": 0, "disabled": 0},
    ("Warehouse", "Stores - OC"): {"company": "OC", "is_group": 0, "disabled": 0},
    ("Branch", "Tehran"): {},
    ("Supplier", "Acme"): {"disabled": 0},
    ("Supplier", "Gone"): {"disabled": 1},
    ("Department", "Sales - WP"): {"company": "WP", "disabled": 0},
    ("Department", "Sales - OC"): {"company": "OC", "disabled": 0},
}
LEAVE_TYPES = {"Casual Leave": "annual", "Plain Leave": ""}


class _DB:
    def exists(self, doctype, filters):
        name = filters["name"]
        row = RECORDS.get((doctype, name))
        if row is None:
            return None
        return name if all(row.get(key) == value for key, value in filters.items() if key != "name") else None

    def get_value(self, doctype, name, fields, as_dict=False):
        if doctype == "Leave Type":
            return LEAVE_TYPES.get(name)
        row = ITEMS.get(name)
        if row is None:
            return None
        return SimpleNamespace(**{field: row.get(field) for field in fields})


def _throw(message, *args, **kwargs):
    raise ValueError(message)


@pytest.fixture
def links(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda value: value
    frappe.throw = _throw
    frappe.db = _DB()
    utils = types.ModuleType("frappe.utils")
    utils.flt = lambda value, precision=None: round(float(value or 0), precision or 9)
    frappe.utils = utils
    details = types.ModuleType("erpnext.stock.get_item_details")
    details.get_conversion_factor = lambda item_code, uom: {"conversion_factor": 1.0}
    item = types.ModuleType("erpnext.stock.doctype.item.item")
    item.validate_end_of_life = lambda *args, **kwargs: None
    frappe.get_all = lambda *args, **kwargs: []
    for name, module in {
        "frappe": frappe, "frappe.utils": utils,
        "erpnext": types.ModuleType("erpnext"), "erpnext.stock": types.ModuleType("erpnext.stock"),
        "erpnext.stock.get_item_details": details,
        "erpnext.stock.doctype": types.ModuleType("erpnext.stock.doctype"),
        "erpnext.stock.doctype.item": types.ModuleType("erpnext.stock.doctype.item"),
        "erpnext.stock.doctype.item.item": item,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    # Import fresh copies bound to this fixture's frappe stub, then put the old ones back.
    import asoud_erp.services as services

    saved = {name: sys.modules.pop(f"asoud_erp.services.{name}", None)
             for name in ("request_link_values", "request_lookup")}
    saved_attrs = {name: services.__dict__.get(name) for name in saved}
    module = importlib.import_module("asoud_erp.services.request_link_values")
    yield module
    for name, old in saved.items():
        sys.modules.pop(f"asoud_erp.services.{name}", None)
        if old is not None:
            sys.modules[f"asoud_erp.services.{name}"] = old
        if saved_attrs[name] is not None:
            setattr(services, name, saved_attrs[name])
        else:
            services.__dict__.pop(name, None)


def _select(source):
    return [{"key": "pick", "type": "System Select", "source": source}]


@pytest.mark.parametrize("source,value", [
    ("cost_center", "Main - WP"), ("project", "PRJ-1"), ("warehouse", "Stores - WP"), ("branch", "Tehran"),
    ("supplier", "Acme"), ("leave_type", "Casual Leave"), ("delivery_location", "warehouse:Stores - WP"),
    ("delivery_location", "branch:Tehran"), ("delivery_location", "department:Sales - WP"),
])
def test_valid_system_select_values_pass(links, source, value):
    assert links.validate_link_values(_select(source), {"pick": value}, "WP") == {"pick": value}


@pytest.mark.parametrize("source,value", [
    ("cost_center", "Old - WP"), ("cost_center", "Group - WP"), ("cost_center", "Other - OC"),
    ("cost_center", "Missing"), ("project", "PRJ-2"), ("warehouse", "Stores - OC"), ("branch", "Nowhere"),
    ("supplier", "Gone"), ("leave_type", "Plain Leave"), ("leave_type", "Missing Leave"),
    ("delivery_location", "warehouse:Stores - OC"), ("delivery_location", "department:Sales - OC"),
    ("delivery_location", "branch:Nowhere"), ("delivery_location", "Stores - WP"),
])
def test_invalid_system_select_values_are_rejected(links, source, value):
    with pytest.raises(ValueError):
        links.validate_link_values(_select(source), {"pick": value}, "WP")


def _rows(**options):
    return [{"key": "items", "type": "Item Table", "row_options": {"item_scope": "all", **options}}]


def test_row_options_add_flags_note_and_attachment(links):
    values = links.validate_link_values(_rows(note=True, attachment=True), {"items": [
        {"item_code": "ICU-MON-01", "qty": 2.0, "uom": None, "description": "", "note": "فوری",
         "attachment": "/private/files/m.png"},
        {"item_code": "SERVICE-01", "qty": 1.0, "uom": None, "description": "", "note": "", "attachment": None},
    ]}, "WP")
    first, second = values["items"]
    assert first["is_stock_item"] == 1 and first["note"] == "فوری" and first["attachment"] == "/private/files/m.png"
    assert second["is_stock_item"] == 0 and second["note"] == "" and second["attachment"] is None


def test_row_options_without_note_or_attachment_do_not_store_them(links):
    row = links.validate_link_values(_rows(), {"items": [
        {"item_code": "ICU-MON-01", "qty": 1.0, "uom": None, "description": ""}]}, "WP")["items"][0]
    assert "note" not in row and "attachment" not in row and row["is_stock_item"] == 1


def test_purchase_scope_rejects_non_purchase_items_but_all_accepts_them(links):
    rows = {"items": [{"item_code": "INTERNAL-01", "qty": 1.0, "uom": None, "description": ""}]}
    with pytest.raises(ValueError):
        links.validate_link_values(
            [{"key": "items", "type": "Item Table", "row_options": {"item_scope": "purchase"}}], rows, "WP")
    assert links.validate_link_values(_rows(), rows, "WP")["items"][0]["item_code"] == "INTERNAL-01"
