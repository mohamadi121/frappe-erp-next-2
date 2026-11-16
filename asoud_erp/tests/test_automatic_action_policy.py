"""Pure contract regressions for the v2 automatic-action policy (Calculate Value)."""
import pytest

from asoud_erp.services.automatic_action_policy import (
    normalize_action,
    validate_table_aggregation,
)


def constant(value):
    return {"source": "constant", "value": value}


def calculate_action(method, inputs=None, formula=None, table=None):
    operation = {
        "target": {"source": "current"},
        "field": "amount",
        "method": method,
        "inputs": inputs if inputs is not None else {"a": constant(1), "b": constant(2)},
    }
    if formula is not None:
        operation["formula"] = formula
    if table is not None:
        operation["table"] = table
    return {
        "title": "محاسبه",
        "description": "تست محاسبه مقدار",
        "schema_version": 2,
        "action_type": "Calculate Value",
        "operation": operation,
        "execution": {"extra_attempts": 0, "retry_seconds": 60, "timeout_seconds": 120},
    }


@pytest.mark.parametrize("method", ["sum", "average", "min", "max", "count", "formula"])
def test_calculate_value_accepts_the_documented_methods(method):
    action = calculate_action(method, formula="a + b" if method == "formula" else None)
    result = normalize_action(action)["operation"]
    assert result["method"] == method


def test_min_max_count_round_trip_keep_inputs():
    result = normalize_action(calculate_action("min"))["operation"]
    # source() fills the transform/empty defaults; the mapped keys survive.
    assert set(result["inputs"]) == {"a", "b"}
    assert result["inputs"]["a"]["value"] == 1
    assert result["inputs"]["b"]["value"] == 2
    assert "formula" not in result


def test_formula_method_still_requires_a_formula():
    with pytest.raises(ValueError):
        normalize_action(calculate_action("formula"))


def test_unknown_method_is_rejected():
    with pytest.raises(ValueError, match="Invalid calculation method"):
        normalize_action(calculate_action("median"))


def test_hidden_formula_is_rejected_for_non_formula_methods():
    with pytest.raises(ValueError, match="Hidden formula is not allowed"):
        normalize_action(calculate_action("min", formula="a + b"))


# --- Table-column aggregation (PA-068) ---------------------------------------


def test_table_aggregation_is_accepted_for_numeric_methods():
    for method in ["sum", "average", "min", "max", "count"]:
        result = normalize_action(
            calculate_action(method, inputs={}, table={"table": "items", "column": "qty"})
        )["operation"]
        assert result["table"] == {"table": "items", "column": "qty"}, method
        assert result["method"] == method
        assert "formula" not in result


def test_table_aggregation_rejects_the_formula_method():
    with pytest.raises(ValueError, match="تجمیع جدول"):
        normalize_action(
            calculate_action("formula", formula="a + b", table={"table": "items", "column": "qty"})
        )


def test_table_aggregation_rejects_scalar_inputs():
    with pytest.raises(ValueError, match="ورودی‌های عددی"):
        normalize_action(
            calculate_action("sum", inputs={"a": constant(1)}, table={"table": "items", "column": "qty"})
        )


def test_table_aggregation_requires_table_and_column():
    # A missing key is caught by the identifier check; an extra key by the shape check.
    with pytest.raises(ValueError, match="Invalid field identifier"):
        normalize_action(calculate_action("sum", inputs={}, table={"table": "items"}))
    with pytest.raises(ValueError, match="Invalid field identifier"):
        normalize_action(calculate_action("sum", inputs={}, table={"column": "qty"}))
    with pytest.raises(ValueError, match="ساختار تجمیع جدول"):
        normalize_action(calculate_action("sum", inputs={}, table={"table": "items", "column": "qty", "op": "sum"}))


def test_table_aggregation_rejects_bad_identifiers():
    with pytest.raises(ValueError, match="Invalid field identifier"):
        normalize_action(calculate_action("sum", inputs={}, table={"table": "Items", "column": "qty"}))


def _table_fields():
    return [
        {"key": "amount", "type": "Number"},
        {"key": "items", "type": "Table", "columns": [
            {"key": "qty", "type": "Number"},
            {"key": "note", "type": "Short Text"},
        ]},
        {"key": "other", "type": "Text"},
    ]


def test_validate_table_aggregation_accepts_a_numeric_column():
    validate_table_aggregation({"table": "items", "column": "qty"}, "sum", _table_fields())
    validate_table_aggregation({"table": "items", "column": "qty"}, "count", _table_fields())


def test_validate_table_aggregation_rejects_a_missing_table_field():
    with pytest.raises(ValueError, match="فیلد جدول"):
        validate_table_aggregation({"table": "nope", "column": "qty"}, "sum", _table_fields())


def test_validate_table_aggregation_rejects_a_non_table_field():
    with pytest.raises(ValueError, match="از نوع جدول نیست"):
        validate_table_aggregation({"table": "other", "column": "qty"}, "sum", _table_fields())


def test_validate_table_aggregation_rejects_a_missing_column():
    with pytest.raises(ValueError, match="ستون انتخاب‌شده در جدول"):
        validate_table_aggregation({"table": "items", "column": "nope"}, "sum", _table_fields())


def test_validate_table_aggregation_requires_numeric_for_sum_average_min_max():
    with pytest.raises(ValueError, match="باید عددی باشد"):
        validate_table_aggregation({"table": "items", "column": "note"}, "sum", _table_fields())
    with pytest.raises(ValueError, match="باید عددی باشد"):
        validate_table_aggregation({"table": "items", "column": "note"}, "average", _table_fields())
    with pytest.raises(ValueError, match="باید عددی باشد"):
        validate_table_aggregation({"table": "items", "column": "note"}, "min", _table_fields())
    with pytest.raises(ValueError, match="باید عددی باشد"):
        validate_table_aggregation({"table": "items", "column": "note"}, "max", _table_fields())


def test_validate_table_aggregation_allows_non_numeric_for_count():
    validate_table_aggregation({"table": "items", "column": "note"}, "count", _table_fields())
