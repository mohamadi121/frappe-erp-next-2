import sys
import types
from types import SimpleNamespace

import pytest

USERS = {"ali@example.com": {"enabled": 1}, "old@example.com": {"enabled": 0}}
EMPLOYEES = [
    {"user_id": "ali@example.com", "status": "Active", "company": "Tabaan"},
    {"user_id": "old@example.com", "status": "Active", "company": "Tabaan"},
]
DEPARTMENTS = {
    "IT - T": {"company": "Tabaan", "disabled": 0},
    "HR - O": {"company": "Other", "disabled": 0},
    "Old - T": {"company": "Tabaan", "disabled": 1},
}
ITEMS = {
    "PAPER": {"item_name": "کاغذ A4", "stock_uom": "Nos", "has_variants": 0, "disabled": 0,
              "end_of_life": None, "variant_of": None},
    "SHIRT": {"item_name": "Shirt", "stock_uom": "Nos", "has_variants": 1, "disabled": 0,
              "end_of_life": None, "variant_of": None},
    "OLD": {"item_name": "Old", "stock_uom": "Nos", "has_variants": 0, "disabled": 1,
            "end_of_life": None, "variant_of": None},
}
UOM_CONVERSIONS = [{"parent": "PAPER", "uom": "Box", "conversion_factor": 500}]


class _DB:
    tables = {"User": USERS, "Department": DEPARTMENTS, "Item": ITEMS}

    def get_value(self, doctype, name, fields, as_dict=False):
        row = self.tables.get(doctype, {}).get(name)
        if row is None:
            return None
        if isinstance(fields, str):
            return row.get(fields)
        return SimpleNamespace(**{field: row.get(field) for field in fields})

    def exists(self, doctype, filters):
        assert doctype == "Employee"
        return any(all(row.get(k) == v for k, v in filters.items()) for row in EMPLOYEES)


def _get_all(doctype, filters, pluck):
    assert doctype == "UOM Conversion Detail"
    return [row[pluck] for row in UOM_CONVERSIONS if row["parent"] in filters["parent"][1]]


def _conversion_factor(item_code, uom):
    if uom == ITEMS[item_code]["stock_uom"]:
        return {"conversion_factor": 1.0}
    match = [row["conversion_factor"] for row in UOM_CONVERSIONS
             if row["parent"] == item_code and row["uom"] == uom]
    return {"conversion_factor": match[0] if match else 1.0}


def _end_of_life(item_code, end_of_life=None, disabled=None):
    if disabled:
        raise ValueError(f"Item {item_code} is disabled")


@pytest.fixture
def links(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda value: value
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
    frappe.db = _DB()
    frappe.get_all = _get_all
    utils = types.ModuleType("frappe.utils")
    utils.flt = lambda value, precision=None: round(float(value or 0), precision or 9)
    frappe.utils = utils
    details = types.ModuleType("erpnext.stock.get_item_details")
    details.get_conversion_factor = _conversion_factor
    item = types.ModuleType("erpnext.stock.doctype.item.item")
    item.validate_end_of_life = _end_of_life
    for name, module in {
        "frappe": frappe, "frappe.utils": utils,
        "erpnext": types.ModuleType("erpnext"), "erpnext.stock": types.ModuleType("erpnext.stock"),
        "erpnext.stock.get_item_details": details,
        "erpnext.stock.doctype": types.ModuleType("erpnext.stock.doctype"),
        "erpnext.stock.doctype.item": types.ModuleType("erpnext.stock.doctype.item"),
        "erpnext.stock.doctype.item.item": item,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("asoud_erp.services.request_link_values", None)
    from asoud_erp.services import request_link_values

    return request_link_values


FIELDS = [
    {"key": "owner_user", "type": "User"},
    {"key": "unit", "type": "Department"},
    {"key": "items", "type": "Item Table"},
    {"key": "note", "type": "Short Text"},
]


def test_valid_values_pass_and_item_rows_get_erpnext_data(links):
    values = links.validate_link_values(FIELDS, {
        "owner_user": "ali@example.com",
        "unit": "IT - T",
        "items": [
            {"item_code": "PAPER", "qty": 2.0, "uom": "Box", "description": ""},
            {"item_code": "PAPER", "qty": 3.0, "uom": None, "description": "یدکی"},
        ],
        "note": None,
    }, "Tabaan")
    assert values["items"][0] == {
        "item_code": "PAPER", "item_name": "کاغذ A4", "qty": 2.0, "uom": "Box",
        "stock_uom": "Nos", "conversion_factor": 500.0, "stock_qty": 1000.0, "description": "",
    }
    assert values["items"][1]["uom"] == "Nos"
    assert values["items"][1]["stock_qty"] == 3.0


@pytest.mark.parametrize("values", [
    {"owner_user": "old@example.com"},
    {"owner_user": "nobody@example.com"},
    {"unit": "HR - O"},
    {"unit": "Old - T"},
    {"unit": "Missing"},
    {"items": [{"item_code": "MISSING", "qty": 1.0, "uom": None}]},
    {"items": [{"item_code": "SHIRT", "qty": 1.0, "uom": None}]},
    {"items": [{"item_code": "OLD", "qty": 1.0, "uom": None}]},
    {"items": [{"item_code": "PAPER", "qty": 1.0, "uom": "Kg"}]},
])
def test_invalid_erpnext_references_are_rejected(links, values):
    with pytest.raises(ValueError):
        links.validate_link_values(FIELDS, values, "Tabaan")


def test_user_must_belong_to_the_request_company(links):
    with pytest.raises(ValueError):
        links.validate_link_values(FIELDS, {"owner_user": "ali@example.com"}, "Other")


def test_item_uoms_list_stock_uom_first(links):
    assert links.item_uoms("PAPER") == [
        {"uom": "Nos", "conversion_factor": 1.0},
        {"uom": "Box", "conversion_factor": 500.0},
    ]
