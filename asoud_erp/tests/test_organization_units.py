import importlib
import json
import sys
import types

import pytest


class Refused(Exception):
    pass


@pytest.fixture
def units(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(Refused(message))
    frappe.state = {"locks": 0, "chart": [], "title": "Old title"}

    def sql(query, *args):
        if "for update" in query:
            frappe.state["locks"] += 1

    def get_value(doctype, filters, fieldname=None):
        if doctype == "ASOUD Organization Chart":
            return json.dumps(frappe.state["chart"])
        return frappe.state["title"]

    frappe.db = types.SimpleNamespace(sql=sql, get_value=get_value)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    module = importlib.import_module("asoud_erp.services.organization_units")
    module = importlib.reload(module)
    module.frappe_state = frappe.state
    return module


def unit(old_title="Old title", company="C1", disabled=0, new_title=None, new_company=None,
         new_disabled=None, old_company=None):
    old = types.SimpleNamespace(company=old_company or company, disabled=0, department_name=old_title)
    doc = types.SimpleNamespace(
        name="DEPT-1", company=new_company or company, disabled=disabled,
        department_name=new_title or old_title, get_doc_before_save=lambda: old,
    )
    return doc


def test_plain_save_takes_no_company_lock_even_with_linked_positions(units):
    units.frappe_state["chart"] = [{"code": "P", "department_id": "DEPT-1"}]
    units.guard_department(unit(), "on_update")
    assert units.frappe_state["locks"] == 0


def test_disabling_linked_unit_locks_and_is_refused(units):
    units.frappe_state["chart"] = [{"code": "P", "department_id": "DEPT-1"}]
    with pytest.raises(Refused, match="غیرفعال"):
        units.guard_department(unit(disabled=1), "on_update")
    assert units.frappe_state["locks"] == 1


def test_disabling_unlinked_unit_is_allowed(units):
    units.guard_department(unit(disabled=1), "on_update")
    assert units.frappe_state["locks"] == 1


def test_moving_linked_unit_to_another_company_is_refused(units):
    units.frappe_state["chart"] = [{"code": "P", "department_id": "DEPT-1"}]
    with pytest.raises(Refused, match="غیرفعال یا به شرکت دیگر"):
        units.guard_department(unit(new_company="C2"), "on_update")


def test_trash_of_linked_unit_is_refused_and_unlinked_trash_passes(units):
    units.frappe_state["chart"] = [{"code": "P", "department_id": "DEPT-1"}]
    with pytest.raises(Refused, match="حذف مجاز نیست"):
        units.guard_department(unit(), "on_trash")
    units.frappe_state["chart"] = []
    units.guard_department(unit(), "on_trash")
    assert units.frappe_state["locks"] == 2


def test_title_change_is_refused_while_legacy_title_rows_depend_on_it(units):
    units.frappe_state["chart"] = [{"code": "P", "department": "Old title"}]
    with pytest.raises(Refused, match="بدون شناسه"):
        units.guard_department(unit(new_title="New title"), "on_update")


def test_title_change_passes_when_only_id_linked_rows_exist(units):
    units.frappe_state["chart"] = [{"code": "P", "department_id": "DEPT-1", "department": "Old title"}]
    units.guard_department(unit(new_title="New title"), "on_update")
    assert units.frappe_state["locks"] == 1


def test_title_change_with_unrelated_legacy_text_passes(units):
    units.frappe_state["chart"] = [{"code": "P", "department": "Someone else"}]
    units.guard_department(unit(new_title="New title"), "on_update")


def test_new_unit_insert_takes_no_lock(units):
    new = types.SimpleNamespace(name="new", company="C1", disabled=1, department_name="New",
        get_doc_before_save=lambda: None)
    units.guard_department(new, "on_update")
    assert units.frappe_state["locks"] == 0
