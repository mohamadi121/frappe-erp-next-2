from asoud_erp.services.request_serializer import (
    build_search_text,
    default_summary,
    first_per_key,
    item_count,
    item_rows_of,
    with_attachment_refs,
)

ROWS = [{"item_code": "ICU-MON-01", "item_name": "مانیتور ICU", "qty": 2}, {"item_code": "A-2", "item_name": "کابل"}]


def test_item_rows_are_found_by_shape():
    assert item_rows_of({"items": ROWS}) == ROWS
    assert item_rows_of({"lines": ROWS, "reason": "x"}) == ROWS
    assert item_rows_of({"items": [], "reason": "x"}) == []
    assert item_rows_of({"table": [{"file": "a"}]}) == []
    assert item_rows_of(None) == []
    assert item_count({"items": ROWS}) == 2 and item_count({}) == 0


def test_search_text_joins_unique_parts_and_item_names():
    text = build_search_text("PR-1405-0023", "خرید تجهیزات ICU", "سارا محمدی", "ICU", "ICU", ROWS)
    assert text == "PR-1405-0023 خرید تجهیزات ICU سارا محمدی ICU ICU-MON-01 مانیتور ICU A-2 کابل"
    assert build_search_text("N", "s") == "N s"
    assert build_search_text("N", "  a   b ") == "N a b"


def test_search_text_is_capped():
    big = [{"item_code": f"CODE-{index:04d}", "item_name": f"نام {index} " * 20} for index in range(100)]
    assert len(build_search_text("N", "s", items=big)) == 4000


def test_attachment_refs_are_added_to_a_copy():
    values = {"items": [{"item_code": "A", "attachment": "/private/files/m.png"}, {"item_code": "B"}],
              "reason": "x"}
    entries = {"/private/files/m.png": {"name": "1a2b3c", "filename": "m.png", "is_image": True}}
    result = with_attachment_refs(values, entries)
    assert result["items"][0]["attachment_ref"] == {"name": "1a2b3c", "filename": "m.png", "is_image": True}
    assert "attachment_ref" not in result["items"][1]
    assert "attachment_ref" not in values["items"][0]
    unknown = with_attachment_refs({"items": [{"item_code": "A", "attachment": "/private/files/x"}]}, entries)
    assert "attachment_ref" not in unknown["items"][0]


def test_default_summary_uses_values_then_the_row():
    row = {"department": "ICU - WP", "project": "", "priority": "High", "required_by": "2026-10-20"}
    summary = default_summary({"org_unit": "ICU - WP", "priority": "High", "needed_date": "2026-10-20"}, row,
                              {"department": {"ICU - WP": "ICU"}, "project": {}})
    assert summary == {"org_unit": "ICU - WP", "org_unit_label": "ICU", "project": "", "project_label": "",
                       "priority": "High", "priority_label": "مهم", "needed_date": "2026-10-20"}
    fallback = default_summary({}, row)
    assert fallback["org_unit"] == "ICU - WP" and fallback["needed_date"] == "2026-10-20"
    assert default_summary({}, {})["priority_label"] == "عادی"


def test_first_per_key_keeps_the_newest_row():
    rows = [{"i": "a", "c": "new"}, {"i": "b", "c": "x"}, {"i": "a", "c": "old"}]
    assert first_per_key(rows, "i") == {"a": {"i": "a", "c": "new"}, "b": {"i": "b", "c": "x"}}
