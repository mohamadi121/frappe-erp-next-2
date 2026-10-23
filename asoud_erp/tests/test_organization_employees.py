import importlib
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture
def employees(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
    frappe.get_doc = lambda doctype, name: SimpleNamespace(check_permission=lambda permission: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    module = importlib.reload(importlib.import_module("asoud_erp.services.organization_employees"))
    monkeypatch.setattr(module, "resolve_employee",
        lambda value, company, **kwargs: SimpleNamespace(name=value.removeprefix("employee:")))
    return module


def v2(code, *occupants):
    return {"code": code, "occupants": list(occupants), "capacity": len(occupants) or 1}


def test_distinct_occupants_across_positions_are_normalized(employees):
    rows = employees.normalize_assignments([v2("A", "employee:E1"), v2("B", "employee:E2")], "C")
    assert [row["occupants"] for row in rows] == [["employee:E1"], ["employee:E2"]]


def test_one_employee_in_two_positions_is_refused(employees):
    with pytest.raises(ValueError, match="در بیش از یک جایگاه منتصب شده است") as error:
        employees.normalize_assignments([v2("A", "employee:E1"), v2("B", "employee:E1")], "C")
    assert "E1" in str(error.value)


def test_same_employee_under_bare_and_namespaced_ids_across_positions_is_refused(employees):
    with pytest.raises(ValueError, match="در بیش از یک جایگاه"):
        employees.normalize_assignments([v2("A", "E1"), v2("B", "employee:E1")], "C")


def test_legacy_row_and_v2_occupant_of_same_employee_is_refused(employees):
    legacy = {"code": "L", "employee": "E1"}
    with pytest.raises(ValueError, match="در بیش از یک جایگاه منتصب شده است"):
        employees.normalize_assignments([legacy, v2("B", "employee:E1")], "C")


def test_duplicate_inside_one_position_keeps_its_own_message(employees):
    with pytest.raises(ValueError, match="همان جایگاه") as error:
        employees.normalize_assignments([v2("A", "employee:E1", "employee:E1")], "C")
    assert "بیش از یک جایگاه" not in str(error.value)
