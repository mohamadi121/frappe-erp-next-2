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
