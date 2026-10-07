import pytest

from asoud_erp.services.workflow_response import (
    attachment_references,
    map_attachment_values,
    normalize_form_response,
)

TIME = [{"key": "at", "type": "Time"}]


@pytest.mark.parametrize("value", ["00:00", "09:30", "23:59"])
def test_time_accepts_24_hour_values(value):
    assert normalize_form_response(TIME, {"at": value}) == {"at": value}


@pytest.mark.parametrize("value", ["24:00", "9:3", "9:30", "12:60", "09:30:00", "0930", 930, "ab:cd", " 09:30"])
def test_time_rejects_other_formats(value):
    with pytest.raises(ValueError):
        normalize_form_response(TIME, {"at": value})


LEAVE = [
    {"key": "request_kind", "type": "Choice", "required": True, "options": ["Daily", "Hourly"],
     "option_labels": {"Daily": "روزانه", "Hourly": "ساعتی"}},
    {"key": "start_date", "type": "Date", "required": True, "visible_when": {"field": "request_kind", "equals": "Daily"}},
    {"key": "leave_date", "type": "Date", "required": True, "visible_when": {"field": "request_kind", "equals": "Hourly"}},
    {"key": "start_time", "type": "Time", "required": True, "visible_when": {"field": "request_kind", "equals": "Hourly"}},
]


def test_hidden_fields_are_dropped_and_not_required():
    daily = normalize_form_response(LEAVE, {"request_kind": "Daily", "start_date": "2026-10-10"})
    assert daily == {"request_kind": "Daily", "start_date": "2026-10-10", "leave_date": None, "start_time": None}
    hourly = normalize_form_response(LEAVE, {
        "request_kind": "Hourly", "leave_date": "2026-10-10", "start_time": "09:00", "start_date": "2026-10-01"})
    assert hourly["start_date"] is None
    assert hourly["start_time"] == "09:00"


def test_visible_fields_are_still_required():
    with pytest.raises(ValueError):
        normalize_form_response(LEAVE, {"request_kind": "Daily"})
    with pytest.raises(ValueError):
        normalize_form_response(LEAVE, {"request_kind": "Hourly", "leave_date": "2026-10-10"})


def test_in_rule_and_chained_visibility():
    fields = [
        {"key": "mode", "type": "Choice", "options": ["a", "b", "c"]},
        {"key": "detail", "type": "Short Text", "visible_when": {"field": "mode", "in": ["a", "b"]}},
        {"key": "more", "type": "Short Text", "required": True,
         "visible_when": {"field": "detail", "equals": "yes"}},
    ]
    assert normalize_form_response(fields, {"mode": "c", "detail": "yes"}) == {
        "mode": "c", "detail": None, "more": None}
    assert normalize_form_response(fields, {"mode": "a", "detail": "no"})["more"] is None
    with pytest.raises(ValueError):
        normalize_form_response(fields, {"mode": "a", "detail": "yes"})


def test_choice_stores_the_key_and_rejects_the_label():
    fields = [LEAVE[0]]
    assert normalize_form_response(fields, {"request_kind": "Hourly"}) == {"request_kind": "Hourly"}
    with pytest.raises(ValueError):
        normalize_form_response(fields, {"request_kind": "ساعتی"})


def test_auto_values_from_a_client_are_rejected_and_never_returned():
    fields = [{"key": "number", "type": "Auto", "auto": "request_number"},
              {"key": "duration", "type": "Auto", "auto": "leave_duration"},
              {"key": "title", "type": "Short Text"}]
    assert normalize_form_response(fields, {"title": "x"}) == {"title": "x"}
    assert normalize_form_response(fields, {"title": "x", "number": None}) == {"title": "x"}
    with pytest.raises(ValueError):
        normalize_form_response(fields, {"number": "PR-1405-0001"})
    with pytest.raises(ValueError):
        normalize_form_response(fields, {"duration": {"unit": "day", "days": 3}})
    # A cartable draft carries what the server computed earlier: ignored, not trusted.
    assert normalize_form_response(fields, {"duration": {"unit": "day"}}, allow_auto=True) == {"title": None}


def test_required_auto_fields_do_not_need_a_value():
    fields = [{"key": "number", "type": "Auto", "auto": "request_number", "required": True}]
    assert normalize_form_response(fields, {}) == {}


def test_system_select_shape():
    fields = [{"key": "cc", "type": "System Select", "source": "cost_center"},
              {"key": "place", "type": "System Select", "source": "delivery_location"}]
    assert normalize_form_response(fields, {"cc": " Main - WP ", "place": "warehouse:Stores - WP"}) == {
        "cc": "Main - WP", "place": "warehouse:Stores - WP"}
    for bad in ({"cc": 5}, {"cc": ["Main"]}, {"cc": "x" * 141}, {"cc": "   "}):
        with pytest.raises(ValueError):
            normalize_form_response(fields, bad)
    for bad_place in ("Stores - WP", "city:Tehran", "warehouse:"):
        with pytest.raises(ValueError):
            normalize_form_response(fields, {"place": bad_place})


def test_text_max_length_is_enforced():
    fields = [{"key": "reason", "type": "Long Text", "max_length": 5}]
    assert normalize_form_response(fields, {"reason": "12345"}) == {"reason": "12345"}
    with pytest.raises(ValueError):
        normalize_form_response(fields, {"reason": "123456"})


ITEMS = [{"key": "items", "type": "Item Table", "required": True,
          "row_options": {"item_scope": "purchase", "note": True, "attachment": True, "min_rows": 1, "max_rows": 2}}]
ROW = {"item_code": "ICU-MON-01", "qty": 2, "uom": "Nos", "description": "x" * 1000}


def test_item_rows_accept_note_and_attachment():
    rows = normalize_form_response(ITEMS, {"items": [
        {**ROW, "note": "فوری", "attachment": "/private/files/m.png"}, {"item_code": "A", "qty": "1"}]})["items"]
    assert rows[0] == {"item_code": "ICU-MON-01", "qty": 2.0, "uom": "Nos", "description": "x" * 1000,
                       "note": "فوری", "attachment": "/private/files/m.png"}
    assert rows[1] == {"item_code": "A", "qty": 1.0, "uom": None, "description": "", "note": "", "attachment": None}


def test_item_rows_reject_unknown_keys_and_bad_values():
    for row in ({**ROW, "price": 5}, {**ROW, "note": "n" * 501}, {**ROW, "description": "d" * 1001},
                {**ROW, "attachment": "http://evil/x.png"}, {**ROW, "qty": 0}, {"qty": 1}):
        with pytest.raises(ValueError):
            normalize_form_response(ITEMS, {"items": [row]})


def test_item_rows_respect_row_options():
    no_extras = [{"key": "items", "type": "Item Table", "row_options": {"note": False, "attachment": False}}]
    for extra in ({"note": "x"}, {"attachment": "/private/files/a.pdf"}):
        with pytest.raises(ValueError):
            normalize_form_response(no_extras, {"items": [{**ROW, **extra}]})
    with pytest.raises(ValueError):
        normalize_form_response(ITEMS, {"items": [ROW, ROW, ROW]})  # max_rows 2
    with pytest.raises(ValueError):
        normalize_form_response(ITEMS, {"items": []})  # required
    assert normalize_form_response([{**ITEMS[0], "required": False}], {"items": None}) == {"items": None}


def test_legacy_item_tables_keep_their_shape():
    legacy = [{"key": "items", "type": "Item Table"}]
    assert normalize_form_response(legacy, {"items": [{"item_code": "A", "qty": 1}]}) == {
        "items": [{"item_code": "A", "qty": 1.0, "uom": None, "description": ""}]}
    with pytest.raises(ValueError):
        normalize_form_response(legacy, {"items": [{"item_code": "A", "qty": 1, "note": "x"}]})


def test_server_derived_row_keys_are_accepted_and_the_serializer_key_is_ignored():
    row = {**ROW, "description": "", "item_name": "مانیتور", "stock_uom": "Nos", "conversion_factor": 1,
           "stock_qty": 2, "is_stock_item": 1, "attachment_ref": {"name": "1a2b"}}
    assert normalize_form_response(ITEMS, {"items": [row]})["items"][0]["item_code"] == "ICU-MON-01"


FILES = [
    {"key": "proof", "type": "Attachment"},
    {"key": "items", "type": "Item Table", "row_options": {"attachment": True}},
    {"key": "table", "type": "Table", "columns": [{"key": "file", "type": "Attachment"}]},
]


def test_attachment_values_are_mapped_in_fields_rows_and_table_columns():
    response = {
        "proof": "attachment:att-1",
        "items": [{"item_code": "A", "qty": 1, "attachment": "attachment:att-2"}, {"item_code": "B", "qty": 1}],
        "table": [{"file": "attachment:att-3"}],
        "extra": "kept",
    }
    mapped = map_attachment_values(FILES, response, lambda value: value.replace("attachment:", "/private/files/"))
    assert mapped["proof"] == "/private/files/att-1"
    assert mapped["items"][0]["attachment"] == "/private/files/att-2"
    assert "attachment" not in mapped["items"][1]
    assert mapped["table"][0]["file"] == "/private/files/att-3"
    assert mapped["extra"] == "kept"
    assert response["items"][0]["attachment"] == "attachment:att-2"  # the input is not modified


def test_attachment_references_carry_their_scope():
    response = {
        "proof": "attachment:att-1",
        "items": [{"item_code": "A", "qty": 1}, {"item_code": "B", "qty": 1, "attachment": "attachment:att-2"}],
        "table": [{"file": "attachment:att-3"}],
    }
    assert attachment_references(FILES, response) == [
        ("field:proof", "attachment:att-1"), ("row:items:1", "attachment:att-2"),
        ("field:table", "attachment:att-3")]
    assert attachment_references(FILES, {"proof": None}) == []


def test_table_attachment_columns_are_validated_with_the_table():
    fields = [{"key": "table", "type": "Table", "columns": [{"key": "file", "type": "Attachment"}]}]
    assert normalize_form_response(fields, {"table": [{"file": "/private/files/a.pdf"}]})["table"] == [
        {"file": "/private/files/a.pdf"}]
    with pytest.raises(ValueError):
        normalize_form_response(fields, {"table": [{"file": "attachment:x"}]})
