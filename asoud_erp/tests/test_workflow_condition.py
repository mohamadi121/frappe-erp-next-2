from datetime import date

import pytest

from asoud_erp.services.workflow_condition import (
    condition_value,
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


def test_jalali_year_in_date_condition_is_converted_to_gregorian() -> None:
    # A custom form field may store a Jalali date string; the year 1403 is a
    # plausible Jalali year, so it must be converted, not read as 1403 AD.
    assert condition_value("Date", "1403-08-20") == date(2024, 11, 10)
    # Persian digits in the Jalali band are normalized before conversion.
    assert condition_value("Date", "۱۴۰۳-۰۸-۲۰") == date(2024, 11, 10)


def test_gregorian_date_condition_is_unchanged() -> None:
    # Native Date fields carry Gregorian ISO dates; a year outside the Jalali
    # band must not be reinterpreted.
    assert condition_value("Date", "2026-02-11") == date(2026, 2, 11)
    assert condition_value("Date", "1403-08-20") != date(1403, 8, 20)
