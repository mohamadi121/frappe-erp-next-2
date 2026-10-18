import importlib
import sys
import types

import pytest


@pytest.fixture
def schema(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
    frappe.db = types.SimpleNamespace(exists=lambda *args: True, get_value=lambda *args: None)
    frappe.session = types.SimpleNamespace(user="test@example.com")
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    module = importlib.import_module("asoud_erp.services.form_schema")
    return importlib.reload(module)


def valid_schema():
    return {
        "kind": "Request",
        "title": "درخواست آزمایشی",
        "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "amount", "label": "مبلغ", "type": "Money"},
            {"key": "tax", "label": "مالیات", "type": "Formula",
             "formula": {"op": "percent", "inputs": ["amount", "amount"], "precision": 2}},
            {"key": "priority", "label": "اولویت", "type": "Select",
             "options": [{"id": "normal", "label": "عادی"}, {"id": "urgent", "label": "فوری"}]},
        ]}],
    }


def test_valid_schema_uses_stable_option_ids(schema):
    result = schema.validate_schema(valid_schema())
    assert [option["id"] for option in result["sections"][0]["fields"][2]["options"]] == ["normal", "urgent"]


def test_duplicate_field_ids_are_rejected(schema):
    payload = valid_schema()
    payload["sections"][0]["fields"][1]["key"] = "amount"
    with pytest.raises(ValueError, match="شناسه فیلد"):
        schema.validate_schema(payload)


def test_unknown_field_type_is_rejected(schema):
    payload = valid_schema()
    payload["sections"][0]["fields"][0]["type"] = "Script"
    with pytest.raises(ValueError, match="نوع فیلد"):
        schema.validate_schema(payload)


def test_cyclic_formula_ids_are_rejected(schema):
    payload = valid_schema()
    payload["sections"][0]["fields"][0]["type"] = "Formula"
    payload["sections"][0]["fields"][0]["formula"] = {"op": "add", "inputs": ["tax"]}
    with pytest.raises(ValueError, match="چرخه"):
        schema.validate_schema(payload)


def test_duplicate_or_label_only_option_ids_are_rejected(schema):
    payload = valid_schema()
    payload["sections"][0]["fields"][2]["options"] = [
        {"id": "same", "label": "الف"}, {"id": "same", "label": "ب"}
    ]
    with pytest.raises(ValueError, match="گزینه"):
        schema.validate_schema(payload)
    payload["sections"][0]["fields"][2]["options"] = ["عادی"]
    with pytest.raises(ValueError, match="گزینه"):
        schema.validate_schema(payload)


def test_unbounded_section_id_and_formula_shape_are_rejected(schema):
    payload = valid_schema()
    payload["sections"][0]["id"] = "x" * 61
    with pytest.raises(ValueError, match="شناسه بخش"):
        schema.validate_schema(payload)
    payload = valid_schema()
    payload["sections"][0]["fields"][1]["formula"] = "amount + amount"
    with pytest.raises(ValueError, match="فرمول"):
        schema.validate_schema(payload)
