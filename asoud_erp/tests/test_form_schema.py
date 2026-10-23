import importlib
import sys
import types
from datetime import date

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


def test_form_builder_presentation_extensions_are_validated(schema):
    payload = valid_schema()
    section = payload["sections"][0]
    section.update({
        "description": "راهنمای بخش",
        "icon": "event",
        "color": "blue",
        "background_color": "#e3f2fd",
        "collapsible": True,
        "collapsed": False,
    })
    select = section["fields"][2]
    select["style"] = "radio"
    select["help"] = "یک گزینه را انتخاب کنید."
    result = schema.validate_schema(payload)
    assert result["sections"][0]["collapsible"] is True
    assert result["sections"][0]["fields"][2]["style"] == "radio"

    select["style"] = "buttons"
    with pytest.raises(ValueError, match="شیوه نمایش"):
        schema.validate_schema(payload)
    select.pop("style")
    section["collapsible"] = "yes"
    with pytest.raises(ValueError, match="بخش"):
        schema.validate_schema(payload)


def test_date_after_or_equal_requires_another_date_and_rejects_earlier_visible_value(schema):
    payload = {
        "kind": "Request", "title": "بازه زمانی", "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "start_date", "label": "تاریخ شروع", "type": "Date"},
            {"key": "end_date", "label": "تاریخ پایان", "type": "Date", "after_or_equal": "start_date"},
        ]}],
    }
    validated = schema.validate_schema(payload)
    with pytest.raises(ValueError, match="تاریخ پایان نباید قبل از تاریخ شروع باشد"):
        schema.validate_values(validated, {"start_date": "2026-10-23", "end_date": "2026-10-22"}, "ACME")
    assert schema.validate_values(validated, {"start_date": "2026-10-23", "end_date": "2026-10-23"}, "ACME")["end_date"] == "2026-10-23"

    payload["sections"][0]["fields"][1]["after_or_equal"] = "end_date"
    with pytest.raises(ValueError, match="تاریخ"):
        schema.validate_schema(payload)
    payload["sections"][0]["fields"][1]["after_or_equal"] = "missing_date"
    with pytest.raises(ValueError, match="تاریخ"):
        schema.validate_schema(payload)
    payload["sections"][0]["fields"].append(
        {"key": "other_date", "label": "تاریخ دیگر", "type": "Date", "after_or_equal": "end_date"}
    )
    payload["sections"][0]["fields"][1]["after_or_equal"] = "other_date"
    with pytest.raises(ValueError, match="چرخه"):
        schema.validate_schema(payload)


def test_hidden_date_and_required_table_do_not_bypass_their_validation(schema):
    payload = {
        "kind": "Request", "title": "کنترل جدول", "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "show_end", "label": "نمایش پایان", "type": "Boolean"},
            {"key": "start_date", "label": "تاریخ شروع", "type": "Date"},
            {"key": "end_date", "label": "تاریخ پایان", "type": "Date", "after_or_equal": "start_date"},
            {"key": "items", "label": "اقلام", "type": "Table", "required": True, "min_rows": 2,
             "columns": [{"key": "name", "label": "نام", "type": "Text"}]},
        ]}],
        "rules": [{"target": "end_date", "action": "visible", "join": "and",
                   "conditions": [{"field": "show_end", "op": "eq", "value": True}]}],
    }
    validated = schema.validate_schema(payload)
    with pytest.raises(ValueError, match="حداقل 2 ردیف لازم است"):
        schema.validate_values(validated, {"show_end": False, "start_date": "2026-10-23", "end_date": "2026-10-01", "items": [{"name": "الف"}]}, "ACME")


def test_employee_designation_and_joining_date_defaults(schema):
    schema.frappe.db.get_value = lambda doctype, filters, field: {
        "designation": "کارشناس منابع انسانی",
        "date_of_joining": date(2020, 1, 2),
    }.get(field)
    assert schema.default_value({"default_source": "designation"}, "ACME") == "کارشناس منابع انسانی"
    assert schema.default_value({"default_source": "joining_date"}, "ACME") == "2020-01-02"
    schema.frappe.db.get_value = lambda *args: None
    assert schema.default_value({"default_source": "designation"}, "ACME") is None
    assert schema.default_value({"default_source": "joining_date"}, "ACME") is None


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


def test_formula_if_lazy_evaluation(schema):
    # Division by zero in unused false branch must not fail
    res_true = schema.calculate({
        "op": "if",
        "condition": {"op": ">", "inputs": ["a", "zero"]},
        "then": {"op": "divide", "inputs": ["x", "a"]},
        "else": {"op": "divide", "inputs": ["x", "zero"]},
    }, {"a": "5", "x": "100", "zero": "0"})
    assert res_true == "20.00"

    # Division by zero in unused true branch must not fail
    res_false = schema.calculate({
        "op": "if",
        "condition": {"op": "=", "inputs": ["a", "zero"]},
        "then": {"op": "divide", "inputs": ["x", "zero"]},
        "else": {"op": "divide", "inputs": ["x", "b"]},
    }, {"a": "1", "b": "5", "x": "100", "zero": "0"})
    assert res_false == "20.00"


def test_formula_round_min_max(schema):
    assert schema.calculate({"op": "round", "inputs": ["a", "b"]}, {"a": "2.555", "b": "2"}) == "2.56"
    assert schema.calculate({"op": "round", "inputs": ["a"], "precision": 0}, {"a": "15.6"}) == "16"
    assert schema.calculate({"op": "min", "inputs": ["a", "b", "c"]}, {"a": "15", "b": "3.5", "c": "7"}) == "3.50"
    assert schema.calculate({"op": "max", "inputs": ["a", "b", "c"]}, {"a": "15", "b": "3.5", "c": "7"}) == "15.00"


def test_formula_operator_precedence(schema):
    # * and / before + and -
    res = schema.calculate({
        "op": "chain",
        "inputs": ["a", "b", "c"],
        "ops": ["add", "multiply"],
    }, {"a": "2", "b": "3", "c": "4"})
    assert res == "14.00"

    res_sub = schema.calculate({
        "op": "chain",
        "inputs": ["a", "b", "c"],
        "ops": ["subtract", "divide"],
    }, {"a": "10", "b": "6", "c": "2"})
    assert res_sub == "7.00"


def test_formula_table_min_max(schema):
    rows = [{"amount": "10"}, {"amount": "2.5"}, {"amount": "8"}]
    assert schema.calculate({"op": "min", "table": "rows", "columns": ["amount"]}, {"rows": rows}) == "2.50"
    assert schema.calculate({"op": "max", "table": "rows", "columns": ["amount"]}, {"rows": rows}) == "10.00"
    assert schema.calculate({"op": "min", "table": "rows", "columns": ["amount"]}, {"rows": []}) == "0.00"
    assert schema.calculate({"op": "max", "table": "rows", "columns": ["amount"]}, {"rows": []}) == "0.00"


def test_formula_nested_expressions(schema):
    res = schema.calculate({
        "expression": "IF(a > 0, ROUND(b / a, 2), 0)",
        "inputs": ["a", "b"],
    }, {"a": "3", "b": "10"})
    assert res == "3.33"

    res_mm = schema.calculate({
        "expression": "MAX(a, MIN(b, c))",
        "inputs": ["a", "b", "c"],
    }, {"a": "5", "b": "10", "c": "3"})
    assert res_mm == "5.00"


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


def source_schema(extra_fields, columns=None):
    return {"kind": "Request", "title": "منابع", "sections": [{"id": "main", "title": "اصلی", "fields": extra_fields}]}


def link(key, source, **extra):
    return {"key": key, "label": key, "type": "Link", "source": source, **extra}


def test_new_sources_and_attendance_link_filter_accepted(schema):
    fields = [{"key": "day", "label": "روز", "type": "Date"},
              link("att", "Attendance", link_filter={"field": "attendance_date", "value_field": "day"}),
              link("shift", "Shift Type"), link("event", "Training Event"), link("asset", "Asset")]
    assert len(schema.validate_schema(source_schema(fields))["sections"][0]["fields"]) == 5
    fields[1]["link_filter"]["field"] = "status"
    with pytest.raises(ValueError, match="فیلتر اطلاعات سیستم"):
        schema.validate_schema(source_schema(fields))


def test_exclude_self_only_on_employee_link(schema):
    schema.validate_schema(source_schema([link("boss", "Employee", exclude_self=True)]))
    for bad in (link("c", "Customer", exclude_self=True), {"key": "t", "label": "t", "type": "Text", "exclude_self": True},
                link("e", "Employee", exclude_self="yes")):
        with pytest.raises(ValueError, match="حذف خود"):
            schema.validate_schema(source_schema([bad]))


def test_fetch_from_schema_rules(schema):
    ok = [link("att", "Attendance"), {"key": "in_t", "label": "ورود", "type": "Time", "readonly": True, "fetch_from": "att.in_time"}]
    schema.validate_schema(source_schema(ok))
    for fetch in ("att.employee", "nope.in_time", "in_t.in_time", "att", "att.in_time.x", 5):
        ok[1]["fetch_from"] = fetch
        with pytest.raises(ValueError, match="منبع مقدار خودکار"):
            schema.validate_schema(source_schema(ok))
    # the referenced key must be a Link field
    bad = [{"key": "a", "label": "a", "type": "Text"}, {"key": "b", "label": "b", "type": "Text", "fetch_from": "a.in_time"}]
    with pytest.raises(ValueError, match="منبع مقدار خودکار"):
        schema.validate_schema(source_schema(bad))
    # attribute of another source is refused
    ok[1]["fetch_from"] = "att.asset_name"
    with pytest.raises(ValueError, match="منبع مقدار خودکار"):
        schema.validate_schema(source_schema(ok))


def test_not_equal_and_unique_schema_rules(schema):
    fields = [{"key": "old", "label": "قدیم", "type": "Text"},
              {"key": "new", "label": "جدید", "type": "Text", "not_equal": "old", "not_equal_message": "یکسان است"}]
    schema.validate_schema(source_schema(fields))
    for bad in ("new", "missing", 3):
        fields[1]["not_equal"] = bad
        with pytest.raises(ValueError, match="یکسان نبودن"):
            schema.validate_schema(source_schema(fields))
    table = {"key": "rows", "label": "ردیف", "type": "Table", "columns": [{"key": "n", "label": "نام", "type": "Text", "unique": "yes"}]}
    with pytest.raises(ValueError, match="یکتا"):
        schema.validate_schema(source_schema([table]))
    table["columns"][0]["unique"] = True
    schema.validate_schema(source_schema([table]))
    with pytest.raises(ValueError, match="یکتا"):
        schema.validate_schema(source_schema([{"key": "t", "label": "t", "type": "Text", "unique": True}]))


def test_new_default_sources(schema):
    schema.validate_schema(source_schema([{"key": "n", "label": "n", "type": "Text", "default_source": "employee_number"},
                                          {"key": "s", "label": "s", "type": "Text", "default_source": "default_shift"}]))
    with pytest.raises(ValueError, match="پیش‌فرض"):
        schema.validate_schema(source_schema([{"key": "n", "label": "n", "type": "Text", "default_source": "x"}]))
    values = {"employee_number": "E-7", "default_shift": "صبح"}
    schema.frappe.db.get_value = lambda doctype, filters, field: values.get(field)
    assert schema.default_value({"default_source": "employee_number"}, "ACME") == "E-7"
    assert schema.default_value({"default_source": "default_shift"}, "ACME") == "صبح"
    values.pop("employee_number")
    values["name"] = "HR-EMP-1"
    assert schema.default_value({"default_source": "employee_number"}, "ACME") == "HR-EMP-1"


def test_schedule_references_employee_and_dates(schema):
    fields = [
        link("colleague", "Employee"),
        {"key": "start", "label": "شروع", "type": "Date"},
        {"key": "end", "label": "پایان", "type": "Date"},
        {"key": "schedule", "label": "برنامه", "type": "Schedule",
         "schedule_of": "colleague", "from_field": "start", "to_field": "end"},
    ]
    assert schema.validate_schema(source_schema(fields))["sections"][0]["fields"][-1]["type"] == "Schedule"
    invalid = [*fields[:-1], {**fields[-1], "from_field": "colleague"}]
    with pytest.raises(Exception, match="تاریخ برنامه"):
        schema.validate_schema(source_schema(invalid))


def test_schedule_value_is_never_persisted(schema):
    raw = source_schema([
        {"key": "day", "label": "روز", "type": "Date"},
        {"key": "schedule", "label": "برنامه", "type": "Schedule",
         "schedule_of": "self", "from_field": "day", "to_field": "day"},
    ])
    assert schema.validate_values(raw, {"day": "2026-10-23", "schedule": "ساختگی"}, "ACME") == {"day": "2026-10-23"}


def test_fetch_value_normalises_types(schema):
    from datetime import datetime, timedelta
    moment = datetime(2026, 10, 23, 8, 30, 15, 99)
    assert schema.fetch_value(moment) == "2026-10-23T08:30:15"
    assert schema.fetch_value(moment, "Time") == "08:30:15"
    assert schema.fetch_value(moment, "Date") == "2026-10-23"
    assert schema.fetch_value(timedelta(hours=8, minutes=5)) == "08:05:00"
    assert schema.fetch_value(None) is None


def test_validate_values_not_equal_and_unique(schema):
    sch = schema.validate_schema(source_schema([
        {"key": "old", "label": "قدیم", "type": "Text"},
        {"key": "new", "label": "جدید", "type": "Text", "not_equal": "old"},
        {"key": "rows", "label": "ردیف", "type": "Table", "columns": [{"key": "n", "label": "نام", "type": "Text", "unique": True}]}]))
    assert schema.validate_values(sch, {"old": "a", "new": "b", "rows": [{"n": "x"}, {"n": ""}, {"n": ""}]}, "ACME")["new"] == "b"
    with pytest.raises(ValueError, match="مقدار جدید نباید با مقدار فعلی یکسان باشد"):
        schema.validate_values(sch, {"old": "a", "new": "a"}, "ACME")
    assert schema.validate_values(sch, {"old": "a"}, "ACME")["old"] == "a"
    with pytest.raises(ValueError, match="ردیف تکراری: نام"):
        schema.validate_values(sch, {"rows": [{"n": "x"}, {"n": "y"}, {"n": "x"}]}, "ACME")


def test_validate_values_not_equal_numbers_and_hidden(schema):
    sch = schema.validate_schema(source_schema([
        {"key": "a", "label": "الف", "type": "Decimal"},
        {"key": "b", "label": "ب", "type": "Decimal", "not_equal": "a", "not_equal_message": "برابر است"}]))
    with pytest.raises(ValueError, match="برابر است"):
        schema.validate_values(sch, {"a": "5", "b": "5.0"}, "ACME")
    sch["rules"] = [{"target": "b", "action": "visible", "join": "and", "conditions": [{"field": "a", "op": "eq", "value": "9"}]}]
    assert "b" not in schema.validate_values(sch, {"a": "5", "b": "5"}, "ACME")


def test_validate_values_scoped_sources_and_exclude_self(schema):
    state = {"emp": "EMP-1", "exists": lambda dt, filt: False}
    schema.frappe.db.get_value = lambda dt, filt, field=None: state["emp"] if dt == "Employee" else None
    schema.frappe.db.exists = lambda dt, filt=None: state["exists"](dt, filt)
    schema.frappe.has_permission = lambda *a, **k: True
    schema.frappe.get_doc = lambda dt, name: types.SimpleNamespace(
        meta=types.SimpleNamespace(has_field=lambda f: False), get=lambda f: None)
    asset = schema.validate_schema(source_schema([link("asset", "Asset")]))
    with pytest.raises(ValueError, match="محدوده مجاز شما نیست"):
        schema.validate_values(asset, {"asset": "AST-9"}, "ACME")
    seen = []
    state["exists"] = lambda dt, filt: seen.append(filt) or True
    assert schema.validate_values(asset, {"asset": "AST-1"}, "ACME")["asset"] == "AST-1"
    assert seen[0]["custodian"] == "EMP-1" and seen[0]["name"] == "AST-1" and seen[0]["docstatus"] == 1
    state["emp"] = None
    with pytest.raises(ValueError, match="پرونده پرسنلی شما ثبت نشده"):
        schema.validate_values(asset, {"asset": "AST-1"}, "ACME")
    boss = schema.validate_schema(source_schema([link("boss", "Employee", exclude_self=True)]))
    state["emp"] = "EMP-1"
    with pytest.raises(ValueError, match="نمی‌توانید خودتان را انتخاب کنید"):
        schema.validate_values(boss, {"boss": "EMP-1"}, "ACME")
    assert schema.validate_values(boss, {"boss": "EMP-2"}, "ACME")["boss"] == "EMP-2"


def test_validate_values_fetch_from_ignores_client_value(schema):
    from datetime import datetime
    db = {("Attendance", "ATT-1", "in_time"): datetime(2026, 10, 23, 8, 15, 0)}
    schema.frappe.db.get_value = lambda dt, name, field=None: db.get((dt, name, field)) if not isinstance(name, dict) else "EMP-1"
    schema.frappe.db.exists = lambda *a: True
    schema.frappe.has_permission = lambda *a, **k: True
    sch = schema.validate_schema(source_schema([
        link("att", "Attendance"),
        {"key": "in_t", "label": "ورود", "type": "Time", "readonly": True, "fetch_from": "att.in_time"}]))
    assert schema.validate_values(sch, {"att": "ATT-1", "in_t": "23:59:00"}, "ACME")["in_t"] == "08:15:00"
    assert schema.validate_values(sch, {"att": "ATT-1"}, "ACME")["in_t"] == "08:15:00"
