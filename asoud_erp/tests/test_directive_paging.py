import re

from asoud_erp.services.directive_paging import HISTORY_SQL, history_limits, next_cursor, review_index


def test_cursor_follows_raw_page_even_when_access_filter_hides_every_row():
    # The caller filters rows after reading them; the cursor only sees the raw count.
    assert next_cursor(0, 200, 200) == "200"
    assert next_cursor(400, 200, 200) == "600"


def test_short_raw_page_ends_paging():
    assert next_cursor(0, 199, 200) is None
    assert next_cursor(200, 0, 200) is None


def test_negative_start_is_clamped_before_adding_the_page():
    assert next_cursor("-5", 200, 200) == "200"


def test_review_index_maps_each_report_to_its_review_row():
    rows = [
        {"directive_subject_task": "T-1", "status": "Completed", "action": "Approve"},
        {"directive_subject_task": "T-2", "status": "Open", "action": None},
    ]
    index = review_index(rows)
    assert index["T-1"]["action"] == "Approve"
    assert index["T-2"]["status"] == "Open"
    assert index.get("T-3") is None


def test_review_index_keeps_the_first_review_for_a_report():
    rows = [
        {"directive_subject_task": "T-1", "action": "Return"},
        {"directive_subject_task": "T-1", "action": "Approve"},
    ]
    assert review_index(rows)["T-1"]["action"] == "Return"


def test_review_index_skips_rows_without_a_subject():
    assert review_index([{"directive_subject_task": None, "action": "Approve"}]) == {}


def test_history_limits_read_one_row_past_the_page_in_each_branch():
    assert history_limits(0) == dict(offset=0, branch_limit=51, page_limit=51)
    assert history_limits(100) == dict(offset=100, branch_limit=151, page_limit=51)


def test_history_sql_binds_every_value_as_a_named_parameter():
    names = set(re.findall(r"%\((\w+)\)s", HISTORY_SQL))
    assert names == {"instance", "issuer", "user", "doctype", "name", "branch_limit", "page_limit", "offset"}
    # No positional placeholders, no leftover f-string braces, no literal LIMIT/OFFSET numbers.
    assert "%s" not in HISTORY_SQL
    assert "{" not in HISTORY_SQL and "}" not in HISTORY_SQL
    assert re.search(r"LIMIT \d|OFFSET \d", HISTORY_SQL) is None


def test_history_sql_orders_each_branch_by_the_indexed_column_before_its_limit():
    assert HISTORY_SQL.count("LIMIT %(branch_limit)s") == 2
    assert "ORDER BY a.created_on DESC, a.name DESC" in HISTORY_SQL
    assert "ORDER BY c.creation DESC, c.name DESC" in HISTORY_SQL
    assert "LIMIT %(page_limit)s OFFSET %(offset)s" in HISTORY_SQL


def test_lookahead_page_sets_cursor_only_when_another_row_exists():
    from asoud_erp.services.directive_paging import lookahead_page
    assert lookahead_page(0, list(range(3)), 2) == ([0, 1], "2")
    assert lookahead_page(4, [1, 2], 2) == ([1, 2], None)


def test_site_naive_datetime_converts_offsets_and_keeps_naive():
    from datetime import datetime

    from asoud_erp.services.directive_paging import site_naive_datetime
    assert site_naive_datetime("2026-10-23T09:00:00", "Asia/Tehran") == datetime(2026, 10, 23, 9)
    assert site_naive_datetime("2026-10-23T06:00:00Z", "Asia/Tehran") == datetime(2026, 10, 23, 9, 30)
