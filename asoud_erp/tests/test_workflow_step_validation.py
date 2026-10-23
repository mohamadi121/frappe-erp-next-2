import pytest

from asoud_erp.services.workflow_step_validation import validate_request_bounds


def test_salary_advance_requires_positive_bounded_amount_and_reduction_reason():
    fields = [
        {"key": "approved", "label": "مبلغ مصوب", "type": "Currency", "max_from_request": "requested",
         "min_value_exclusive": 0, "reason_required_if_less_than": "requested", "reason_field": "reason"},
        {"key": "reason", "label": "علت کاهش", "type": "Long Text"},
    ]
    with pytest.raises(ValueError, match="بیشتر از 0"):
        validate_request_bounds(fields, {"requested": 100}, {"approved": 0})
    with pytest.raises(ValueError, match="بیشتر باشد"):
        validate_request_bounds(fields, {"requested": 100}, {"approved": 101})
    with pytest.raises(ValueError, match="علت کاهش"):
        validate_request_bounds(fields, {"requested": 100}, {"approved": 80, "reason": " "})
    assert validate_request_bounds(fields, {"requested": 100}, {"approved": 80, "reason": "بودجه"})["approved"] == 80


def test_equipment_rows_are_projected_and_each_quantity_is_bounded():
    fields = [{"key": "approved_items", "label": "اقلام", "type": "Table",
               "rows_from_request": "items", "columns": [
                   {"key": "item", "label": "کالا", "type": "Short Text", "readonly": True},
                   {"key": "quantity", "label": "درخواستی", "type": "Number", "readonly": True},
                   {"key": "approved", "label": "تأییدشده", "type": "Number", "max_from_row": "quantity"},
               ]}]
    request = {"items": [{"item": "A", "quantity": 2}, {"item": "B", "quantity": 4}]}
    projected = validate_request_bounds(fields, request, {"approved_items": [{"approved": 2}, {"approved": 3}]})
    assert projected["approved_items"][0] == {"item": "A", "quantity": 2, "approved": 2}
    with pytest.raises(ValueError, match="ردیف 2"):
        validate_request_bounds(fields, request, {"approved_items": [{"approved": 2}, {"approved": 5}]})
    with pytest.raises(ValueError, match="قابل تغییر نیست"):
        validate_request_bounds(fields, request, {"approved_items": [
            {"item": "X", "approved": 2}, {"approved": 3}]})
