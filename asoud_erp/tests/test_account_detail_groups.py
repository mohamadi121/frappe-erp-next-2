import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def api(monkeypatch):
    frappe = ModuleType("frappe")
    frappe._ = lambda value: value
    frappe.whitelist = lambda *args, **kwargs: lambda fn: fn
    frappe.only_for = lambda *args: None
    frappe.throw = lambda message: (_ for _ in ()).throw(ValueError(message))
    frappe.db = SimpleNamespace(exists=Mock(return_value=True), get_value=Mock())
    monkeypatch.setitem(__import__("sys").modules, "frappe", frappe)
    path = Path(__file__).parents[1] / "api" / "v1" / "account.py"
    spec = importlib.util.spec_from_file_location("account_selection_test_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selection_deduplicates_and_accepts_json(api):
    assert api._detail_groups('["10000", "30000", "10000"]') == ["10000", "30000"]


@pytest.mark.parametrize("value", [{}, [1], [""]])
def test_invalid_selection_rejected(api, value):
    with pytest.raises(ValueError):
        api._detail_groups(value)


def test_missing_or_disabled_group_rejected(api):
    api.frappe.db.exists.return_value = False
    with pytest.raises(ValueError):
        api._detail_groups(["missing"])


def test_update_with_children_never_saves(api):
    doc = SimpleNamespace(account_number="1", is_group=1,
                          get=lambda name: "Group", save=Mock())
    api.frappe.get_doc = Mock(return_value=doc)
    with pytest.raises(ValueError, match="children"):
        api.update_account("office", "account", "Title", detail_groups=["10000"])
    doc.save.assert_not_called()


@pytest.mark.parametrize("level", ["Group", "General", "Ledger"])
def test_update_keeps_level_and_persists_multiple_groups(api, monkeypatch, level):
    doc = SimpleNamespace(account_number="11", is_group=0,
                          get=lambda name: level, save=Mock(), as_dict=lambda: {})
    api.frappe.get_doc = Mock(return_value=doc)
    api.frappe.db.exists.side_effect = lambda doctype, filters: doctype not in {"GL Entry"} and not (
        doctype == "Account" and "parent_account" in filters)
    save_groups = Mock()
    monkeypatch.setattr(api, "_save_groups", save_groups)
    result = api.update_account("office", "account", "Title", detail_groups=["10000", "30000"])
    assert result["data"]["asoud_level"] == level
    assert result["data"]["detail_groups"] == ["10000", "30000"]
    assert doc.is_group == 0
    save_groups.assert_called_once_with("office", "account", ["10000", "30000"])


@pytest.mark.parametrize("level", ["Group", "General", "Ledger"])
def test_create_terminal_at_requested_level(api, monkeypatch, level):
    payload = {}
    def get_doc(data):
        payload.update(data)
        return SimpleNamespace(name="new", insert=Mock(), as_dict=lambda: dict(data))
    api.frappe.get_doc = get_doc
    save_groups = Mock()
    monkeypatch.setattr(api, "_save_groups", save_groups)
    result = api.create_account("office", "Title", level, parent_account="parent",
                                account_number="11", auto_code=0, detail_groups=["10000"])
    assert payload["is_group"] == 0
    assert payload["asoud_account_level"] == level
    assert result["data"]["detail_groups"] == ["10000"]
    save_groups.assert_called_once_with("office", "new", ["10000"])
