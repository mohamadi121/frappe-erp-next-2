import json
from pathlib import Path

import pytest

from asoud_erp.services.workflow_stage_policy import normalize_stage_config

CONTRACT_FIELDS = json.loads((Path(__file__).parent / "fixtures" / "contract_form_fields.json").read_text())


def _stage(fields):
    return {"title": "فرم درخواست", "activity_type": "Data Entry", "assignment_type": "Initiator",
            "form_fields": fields, "allow_draft": False}


@pytest.mark.parametrize("template", sorted(CONTRACT_FIELDS))
def test_template_form_fields_round_trip_unchanged(template):
    fields = CONTRACT_FIELDS[template]
    normalized = normalize_stage_config("User Task", _stage(fields))["form_fields"]
    assert len(normalized) == len(fields)
    for original, result in zip(fields, normalized, strict=True):
        # Every attribute the template sets survives; only defaults are added.
        assert {key: result[key] for key in original} == original
    again = normalize_stage_config("User Task", _stage(normalized))["form_fields"]
    assert again == normalized


def test_more_than_thirty_fields_are_rejected():
    fields = [{"key": f"field_{index}", "label": f"فیلد {index}", "type": "Short Text"} for index in range(31)]
    with pytest.raises(ValueError):
        normalize_stage_config("User Task", _stage(fields))
    assert len(normalize_stage_config("User Task", _stage(fields[:30]))["form_fields"]) == 30


def test_plain_fields_do_not_gain_extension_keys():
    result = normalize_stage_config("User Task", _stage(
        [{"key": "title", "label": "عنوان", "type": "Short Text"}]))["form_fields"][0]
    assert not {"source", "auto", "visible_when", "option_labels", "widget", "default_source", "editable",
                "min_date", "max_length", "required_by_setting", "row_options"} & set(result)


@pytest.mark.parametrize("field", [
    {"key": "unit", "label": "واحد", "type": "System Select"},
    {"key": "unit", "label": "واحد", "type": "System Select", "source": "nowhere"},
    {"key": "unit", "label": "واحد", "type": "Short Text", "source": "branch"},
    {"key": "num", "label": "شماره", "type": "Auto"},
    {"key": "num", "label": "شماره", "type": "Auto", "auto": "other"},
    {"key": "txt", "label": "متن", "type": "Short Text", "auto": "request_number"},
    {"key": "txt", "label": "متن", "type": "Short Text", "widget": "segmented"},
    {"key": "pick", "label": "گزینه", "type": "Choice", "options": ["a", "b"], "widget": "textarea"},
    {"key": "pick", "label": "گزینه", "type": "Choice", "options": ["a", "b"], "option_labels": {"c": "ث"}},
    {"key": "txt", "label": "متن", "type": "Short Text", "option_labels": {"a": "الف"}},
    {"key": "when", "label": "تاریخ", "type": "Date", "min_date": "tomorrow"},
    {"key": "txt", "label": "متن", "type": "Short Text", "min_date": "today"},
    {"key": "when", "label": "تاریخ", "type": "Date", "default_source": "session_user"},
    {"key": "txt", "label": "متن", "type": "Short Text", "max_length": 0},
    {"key": "txt", "label": "متن", "type": "Short Text", "max_length": "20"},
    {"key": "num", "label": "عدد", "type": "Number", "max_length": 20},
    {"key": "txt", "label": "متن", "type": "Short Text", "required_by_setting": "other_setting"},
    {"key": "txt", "label": "متن", "type": "Short Text", "row_options": {}},
    {"key": "rows", "label": "اقلام", "type": "Item Table", "row_options": {"item_scope": "none"}},
    {"key": "rows", "label": "اقلام", "type": "Item Table", "row_options": {"min_rows": 5, "max_rows": 2}},
    {"key": "rows", "label": "اقلام", "type": "Item Table", "row_options": {"max_rows": 101}},
    {"key": "txt", "label": "متن", "type": "Short Text", "visible_when": {"field": "txt", "equals": "x"}},
    {"key": "txt", "label": "متن", "type": "Short Text", "visible_when": {"field": "ghost", "equals": "x"}},
    {"key": "txt", "label": "متن", "type": "Short Text", "visible_when": {"field": "other"}},
    {"key": "txt", "label": "متن", "type": "Short Text", "visible_when": {"field": "other", "in": []}},
    {"key": "clock", "label": "ساعت", "type": "Time", "default_value": "25:00"},
])
def test_invalid_extension_attributes_are_rejected(field):
    other = {"key": "other", "label": "دیگر", "type": "Short Text"}
    with pytest.raises(ValueError):
        normalize_stage_config("User Task", _stage([other, field]))


def test_valid_extension_attributes_are_normalized():
    result = normalize_stage_config("User Task", _stage([
        {"key": "kind", "label": "نوع", "type": "Choice", "options": ["a", "b"], "widget": "chips",
         "option_labels": {"a": " الف "}},
        {"key": "when", "label": "زمان", "type": "Time", "default_value": "08:30",
         "visible_when": {"field": "kind", "in": ["a", "b"]}},
        {"key": "rows", "label": "اقلام", "type": "Item Table", "row_options": {"note": 1}},
    ]))["form_fields"]
    assert result[0]["option_labels"] == {"a": "الف"}
    assert result[1]["visible_when"] == {"field": "kind", "in": ["a", "b"]}
    assert result[2]["row_options"] == {"item_scope": "all", "note": True, "attachment": False,
                                        "min_rows": 0, "max_rows": 100}
