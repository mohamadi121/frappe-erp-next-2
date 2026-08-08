import pytest

from asoud_erp.services.workflow_condition import (
    evaluate_condition,
    select_boolean_transition,
)


def test_numeric_condition_is_typed() -> None:
    assert evaluate_condition("Greater Than", "1200.50", "1000") is True


def test_contains_and_is_set_are_safe() -> None:
    assert evaluate_condition("Contains", "درخواست فوری", "فوری") is True
    assert evaluate_condition("Is Set", "تهران") is True


def test_invalid_numeric_condition_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_condition("Less Than", "not-number", "10")


def test_boolean_transition_requires_one_exact_match() -> None:
    transitions = [
        {"to_stage": "YES", "condition": {"result": True}},
        {"to_stage": "NO", "condition": {"result": False}},
    ]
    assert select_boolean_transition(transitions, False) == "NO"
    with pytest.raises(ValueError):
        select_boolean_transition(transitions[:1], False)
