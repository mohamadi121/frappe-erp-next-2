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


def test_schema_versions_accepted_and_rejected(schema):
    payload = valid_schema()
    # Omitting schema_version defaults to 1 and is accepted
    res = schema.validate_schema(payload)
    assert res["title"] == "درخواست آزمایشی"

    # Version 1 is accepted
    payload["schema_version"] = 1
    res1 = schema.validate_schema(payload)
    assert res1["schema_version"] == 1

    # Version 2 is accepted
    payload["schema_version"] = 2
    res2 = schema.validate_schema(payload)
    assert res2["schema_version"] == 2

    # Unknown or invalid versions are rejected
    for invalid in (0, 3, -1, "2", True, False):
        payload["schema_version"] = invalid
        with pytest.raises(ValueError, match="نسخه ساختار فرم معتبر نیست"):
            schema.validate_schema(payload)


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


def test_form_formula_vectors(schema):
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / "fixtures" / "form_formula_vectors.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    for item in data["cases"]:
        name = item.get("name", "")
        if "schema" in item:
            with pytest.raises(ValueError):
                schema.validate_schema(item["schema"])
            envelope = {
                "kind": "Request",
                "title": "فرم آزمایشی",
                "sections": [
                    {"id": f"sec_{idx}", "title": "بخش", "fields": section.get("fields", [])}
                    for idx, section in enumerate(item["schema"].get("sections", []))
                ],
                "rules": item["schema"].get("rules", []),
            }
            with pytest.raises(ValueError):
                schema.validate_schema(envelope)
        elif "error" in item:
            with pytest.raises(ValueError):
                schema.calculate(item["formula"], item["values"])
        else:
            result = schema.calculate(item["formula"], item["values"])
            assert result == item["expected"], f"{name}: expected {item['expected']}, got {result}"
