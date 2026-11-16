"""Pure contract regressions for the v2 automatic-action policy (Calculate Value)."""
import pytest

from asoud_erp.services.automatic_action_policy import normalize_action


def constant(value):
    return {"source": "constant", "value": value}


def calculate_action(method, inputs=None, formula=None):
    operation = {
        "target": {"source": "current"},
        "field": "amount",
        "method": method,
        "inputs": inputs if inputs is not None else {"a": constant(1), "b": constant(2)},
    }
    if formula is not None:
        operation["formula"] = formula
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
