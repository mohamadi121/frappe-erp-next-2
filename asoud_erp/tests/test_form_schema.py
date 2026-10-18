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


def test_migrate_schema_legacy_v1_to_v2_fixture(schema):
    import json
    from pathlib import Path

    v1_path = Path(__file__).parent / "fixtures" / "form_schema_legacy_v1.json"
    v2_path = Path(__file__).parent / "fixtures" / "form_schema_legacy_v2.json"

    with open(v1_path, encoding="utf-8") as f:
        v1 = json.load(f)
    with open(v2_path, encoding="utf-8") as f:
        v2_expected = json.load(f)

    # Migrate without mutating source
    v2_actual = schema.migrate_schema(v1)
    assert v2_actual == v2_expected
    assert v1["sections"][0]["fields"][0]["options"] == ["مرخصی", "ماموریت"]

    # Validates cleanly under validate_schema
    validated = schema.validate_schema(v2_actual)
    assert validated["schema_version"] == 2


def test_migrate_schema_values_and_rules(schema):
    import json
    from pathlib import Path

    v1_path = Path(__file__).parent / "fixtures" / "form_schema_legacy_v1.json"
    with open(v1_path, encoding="utf-8") as f:
        v1 = json.load(f)

    values = {
        "request_type": "ماموریت",
        "channels": ["پیامک", "ایمیل"],
        "expenses": [{"expense_type": "اقامت"}, {"expense_type": "ایاب و ذهاب"}],
    }

    migrated_schema = schema.migrate_schema(v1, values=values)
    assert migrated_schema["schema_version"] == 2

    # Verify scalar select mapped to option ID
    assert values["request_type"] == "option_0_0_1"
    # Verify multiselect mapped to option IDs
    assert values["channels"] == ["option_0_1_0", "option_0_1_1"]
    # Verify table column select mapped to option IDs
    assert values["expenses"][0]["expense_type"] == "option_0_2_0_0"
    assert values["expenses"][1]["expense_type"] == "option_0_2_0_1"

    # Verify rule condition value was mapped
    assert migrated_schema["rules"][0]["conditions"][0]["value"] == "option_0_0_1"


def test_migrate_record(schema):
    import json
    from pathlib import Path

    v1_path = Path(__file__).parent / "fixtures" / "form_schema_legacy_v1.json"
    with open(v1_path, encoding="utf-8") as f:
        v1 = json.load(f)

    record = {
        "name": "ENTRY-00001",
        "schema": v1,
        "values": {"request_type": "مرخصی"},
    }
    migrated_record = schema.migrate_record(record)
    assert migrated_record["schema"]["schema_version"] == 2
    assert migrated_record["values"]["request_type"] == "option_0_0_0"
    # Original record unmutated
    assert record["schema"]["schema_version"] == 1


def test_chain_formula_validation_and_calculation(schema):
    payload = {
        "kind": "Request",
        "title": "فرمول زنجیره‌ای",
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "a", "label": "الف", "type": "Decimal"},
                {"key": "b", "label": "ب", "type": "Decimal"},
                {"key": "c", "label": "ج", "type": "Decimal"},
                {
                    "key": "result",
                    "label": "نتیجه",
                    "type": "Formula",
                    "formula": {
                        "op": "chain",
                        "ops": ["multiply", "divide"],
                        "inputs": ["a", "b", "c"],
                        "precision": 2,
                    },
                },
            ],
        }],
    }
    validated = schema.validate_schema(payload)
    assert validated["sections"][0]["fields"][3]["formula"]["op"] == "chain"

    # Evaluation via validate_values with Persian digits
    values = {"a": "۳", "b": "۵۰۰۰۰۰", "c": "۱۵۰۰۰۰۰"}
    computed = schema.validate_values(validated, values, company="ACME")
    assert computed["result"] == "1.00"

    # Direct calculation
    formula = {"op": "chain", "ops": ["multiply", "divide"], "inputs": ["a", "b", "c"]}
    assert schema.calculate(formula, {"a": "3", "b": "500000", "c": "1500000"}) == "1.00"

    # Round half-up precision test
    rounding_formula = {"op": "chain", "ops": ["divide"], "inputs": ["a", "b"], "precision": 2}
    assert schema.calculate(rounding_formula, {"a": "1", "b": "8"}) == "0.13"


def test_chain_formula_wrong_ops_count_rejected(schema):
    payload = {
        "kind": "Request",
        "title": "خطای عملگرها",
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "a", "label": "الف", "type": "Decimal"},
                {"key": "b", "label": "ب", "type": "Decimal"},
                {"key": "c", "label": "ج", "type": "Decimal"},
                {
                    "key": "calc",
                    "label": "محاسبه",
                    "type": "Formula",
                    "formula": {"op": "chain", "ops": ["multiply"], "inputs": ["a", "b", "c"]},
                },
            ],
        }],
    }
    # Ops count too small
    with pytest.raises(ValueError, match="تعداد عملگرهای فرمول معتبر نیست"):
        schema.validate_schema(payload)

    # Less than 2 inputs
    payload["sections"][0]["fields"][3]["formula"] = {
        "op": "chain", "ops": [], "inputs": ["a"]
    }
    with pytest.raises(ValueError, match="تعداد عملگرهای فرمول معتبر نیست"):
        schema.validate_schema(payload)

    # Ops not a list
    payload["sections"][0]["fields"][3]["formula"] = {
        "op": "chain", "ops": "multiply", "inputs": ["a", "b"]
    }
    with pytest.raises(ValueError, match="تعداد عملگرهای فرمول معتبر نیست"):
        schema.validate_schema(payload)

    # Direct calculate with mismatching count
    with pytest.raises(ValueError, match="این محاسبه به دو ورودی نیاز دارد"):
        schema.calculate({"op": "chain", "ops": ["multiply"], "inputs": ["a", "b", "c"]}, {"a": 1, "b": 2, "c": 3})

    # Direct calculate with empty inputs
    with pytest.raises(ValueError, match="این محاسبه به ورودی نیاز دارد"):
        schema.calculate({"op": "chain", "ops": [], "inputs": []}, {})


def test_chain_formula_unknown_op_rejected(schema):
    payload = {
        "kind": "Request",
        "title": "عملگر ناشناخته",
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "a", "label": "الف", "type": "Decimal"},
                {"key": "b", "label": "ب", "type": "Decimal"},
                {
                    "key": "calc",
                    "label": "محاسبه",
                    "type": "Formula",
                    "formula": {"op": "chain", "ops": ["unknown_op"], "inputs": ["a", "b"]},
                },
            ],
        }],
    }
    with pytest.raises(ValueError, match="عملگر فرمول معتبر نیست"):
        schema.validate_schema(payload)

    # Direct calculate with unsupported op
    with pytest.raises(ValueError, match="محاسبه پشتیبانی نمی‌شود"):
        schema.calculate({"op": "chain", "ops": ["power"], "inputs": ["a", "b"]}, {"a": 2, "b": 3})


def test_chain_formula_unknown_input_rejected(schema):
    payload = {
        "kind": "Request",
        "title": "ورودی ناشناخته",
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "a", "label": "الف", "type": "Decimal"},
                {
                    "key": "calc",
                    "label": "محاسبه",
                    "type": "Formula",
                    "formula": {"op": "chain", "ops": ["add"], "inputs": ["a", "missing_key"]},
                },
            ],
        }],
    }
    with pytest.raises(ValueError, match="ورودی"):
        schema.validate_schema(payload)


def test_chain_formula_divide_by_zero_rejected(schema):
    # Direct calculate with explicit zero
    with pytest.raises(ValueError, match="تقسیم بر صفر در فرمول مجاز نیست"):
        schema.calculate({"op": "chain", "ops": ["divide"], "inputs": ["a", "b"]}, {"a": "10", "b": "0"})

    # Missing value treated as zero in divide
    with pytest.raises(ValueError, match="تقسیم بر صفر در فرمول مجاز نیست"):
        schema.calculate({"op": "chain", "ops": ["divide"], "inputs": ["a", "b"]}, {"a": "10"})

    # Via validate_values
    payload = {
        "kind": "Request",
        "title": "تقسیم بر صفر",
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "a", "label": "الف", "type": "Decimal"},
                {"key": "b", "label": "ب", "type": "Decimal"},
                {
                    "key": "calc",
                    "label": "محاسبه",
                    "type": "Formula",
                    "formula": {"op": "chain", "ops": ["divide"], "inputs": ["a", "b"]},
                },
            ],
        }],
    }
    validated = schema.validate_schema(payload)
    with pytest.raises(ValueError, match="تقسیم بر صفر در فرمول مجاز نیست"):
        schema.validate_values(validated, {"a": "10", "b": "0"}, company="ACME")


def test_chain_formula_cycle_rejected(schema):
    payload = {
        "kind": "Request",
        "title": "چرخه فرمول زنجیره‌ای",
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {
                    "key": "a",
                    "label": "الف",
                    "type": "Formula",
                    "formula": {"op": "chain", "ops": ["add"], "inputs": ["b", "b"]},
                },
                {
                    "key": "b",
                    "label": "ب",
                    "type": "Formula",
                    "formula": {"op": "chain", "ops": ["multiply"], "inputs": ["a", "a"]},
                },
            ],
        }],
    }
    with pytest.raises(ValueError, match="چرخه"):
        schema.validate_schema(payload)
