import json

from asoud_erp.services.request_resubmit import changes_comment, diff_values

FIELDS = [
    {"key": "reason", "label": "دلیل", "type": "Long Text"},
    {"key": "secret", "label": "شرح محرمانه", "type": "Long Text", "sensitive": True},
    {"key": "items", "label": "اقلام", "type": "Item Table"},
]


def test_only_changed_keys_are_listed_with_old_and_new_values():
    rows = diff_values({"reason": "الف", "other": 1}, {"reason": "ب", "other": 1}, FIELDS)
    assert rows == [{"key": "reason", "label": "دلیل", "before": "الف", "after": "ب"}]


def test_a_sensitive_value_is_masked_on_both_sides():
    rows = diff_values({"secret": "رمز-۱"}, {"secret": "رمز-۲"}, FIELDS)
    assert rows == [{"key": "secret", "label": "شرح محرمانه", "before": "محرمانه", "after": "محرمانه"}]


def test_a_table_shows_its_row_count_and_an_unchanged_table_is_skipped():
    old = {"items": [{"item_code": "A", "qty": 1}]}
    assert diff_values(old, {"items": [{"item_code": "A", "qty": 1}]}, FIELDS) == []
    rows = diff_values(old, {"items": [{"item_code": "A", "qty": 2}, {"item_code": "B", "qty": 1}]}, FIELDS)
    assert rows[0]["before"] == "1 ردیف" and rows[0]["after"] == "2 ردیف"


def test_a_value_added_or_cleared_is_a_change_and_long_text_is_cut():
    rows = diff_values({}, {"reason": "x" * 500}, FIELDS)
    assert rows[0]["before"] == "" and len(rows[0]["after"]) == 200
    assert diff_values({"reason": "الف"}, {"reason": None}, FIELDS)[0]["after"] == ""


def test_the_comment_is_valid_json_with_the_changes():
    rows = diff_values({"reason": "الف"}, {"reason": "ب"}, FIELDS)
    assert json.loads(changes_comment(rows)) == {"changes": rows}
    assert json.loads(changes_comment([])) == {"changes": []}
