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


LINK_FIELDS = [
    {"key": "needs", "type": "Multi Choice", "options": ["Laptop", "Monitor", "Mouse"]},
    {"key": "owner_user", "type": "User"},
    {"key": "unit", "type": "Department"},
    {"key": "items", "type": "Item Table", "required": True},
]


def test_multi_choice_user_department_and_item_rows_are_normalized():
    result = normalize_form_response(LINK_FIELDS, {
        "needs": ["Monitor", "Laptop", "Monitor"],
        "owner_user": " ali@example.com ",
        "unit": "IT - T",
        "items": [{"item_code": "ITM-1", "qty": "2", "uom": "Nos"}, {"item_code": "ITM-2", "qty": 1.5}],
    })
    assert result["needs"] == ["Monitor", "Laptop"]
    assert result["owner_user"] == "ali@example.com"
    assert result["items"] == [
        {"item_code": "ITM-1", "qty": 2.0, "uom": "Nos", "description": ""},
        {"item_code": "ITM-2", "qty": 1.5, "uom": None, "description": ""},
    ]


def test_resubmitted_item_rows_may_carry_erpnext_values():
    row = {"item_code": "ITM-1", "qty": 2, "uom": "Box", "item_name": "Paper",
           "stock_uom": "Nos", "conversion_factor": 10, "stock_qty": 20}
    result = normalize_form_response(LINK_FIELDS, {"items": [row]})
    assert result["items"][0] == {"item_code": "ITM-1", "qty": 2.0, "uom": "Box", "description": ""}


@pytest.mark.parametrize("value", [
    {"items": []},
    {"items": [{"item_code": "ITM-1", "qty": 0}]},
    {"items": [{"item_code": "", "qty": 1}]},
    {"items": [{"item_code": "ITM-1", "qty": 1, "rate": 5}]},
    {"items": [{"item_code": "ITM-1", "qty": 1}] * 101},
    {"items": [{"item_code": "ITM-1", "qty": 1}], "needs": ["Keyboard"]},
    {"items": [{"item_code": "ITM-1", "qty": 1}], "needs": "Laptop"},
    {"items": [{"item_code": "ITM-1", "qty": 1}], "owner_user": ["a"]},
])
def test_invalid_link_field_values(value):
    with pytest.raises(ValueError):
        normalize_form_response(LINK_FIELDS, value)
