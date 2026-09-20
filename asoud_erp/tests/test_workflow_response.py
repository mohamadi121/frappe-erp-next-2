import pytest

from asoud_erp.services.workflow_response import normalize_form_response

FIELDS = [
    {"key": "title", "type": "Short Text", "required": True},
    {"key": "amount", "type": "Currency", "required": False},
    {"key": "priority", "type": "Choice", "options": ["Normal", "Urgent"]},
]


def test_form_response_is_normalized() -> None:
    result = normalize_form_response(
        FIELDS, {"title": "Request", "amount": "1200", "priority": "Urgent"}
    )
    assert result["amount"] == 1200.0


def test_required_form_response_is_enforced() -> None:
    with pytest.raises(ValueError):
        normalize_form_response(FIELDS, {"title": ""})


def test_unknown_form_response_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_form_response(FIELDS, {"title": "Request", "script": "unsafe"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "-inf", True, {}, []])
def test_invalid_numbers(value):
    with pytest.raises(ValueError):
        normalize_form_response([{"key": "n", "type": "Number", "required": True}], {"n": value})


def test_private_attachment_and_date_validation():
    assert normalize_form_response([{"key": "f", "type": "Attachment"}],
        {"f": "/private/files/test.pdf"})["f"] == "/private/files/test.pdf"
    with pytest.raises(ValueError):
        normalize_form_response([{"key": "d", "type": "Date"}], {"d": "2026-02-30"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "abc", 10**16])
def test_financial_invalid_amounts(value):
    from asoud_erp.services.personnel_contract import FINANCIAL_FIELDS, validate_financial
    with pytest.raises(ValueError):
        validate_financial({next(iter(FINANCIAL_FIELDS)): value})


@pytest.mark.parametrize("value", [{"unexpected": 1}, "true", 2])
def test_invalid_checkbox(value):
    with pytest.raises(ValueError):
        normalize_form_response([{"key": "flag", "type": "Checkbox"}], {"flag": value})


def test_required_whitespace_is_not_a_value():
    with pytest.raises(ValueError):
        normalize_form_response(FIELDS, {"title": "   "})
