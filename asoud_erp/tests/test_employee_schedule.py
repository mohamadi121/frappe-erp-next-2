from datetime import date

import pytest

from asoud_erp.services.employee_schedule import build_schedule, parse_range


def test_schedule_uses_assignment_then_default_then_holiday():
    rows = build_schedule(
        date(2026, 10, 23), date(2026, 10, 25),
        [{"shift_type": "شب", "start_date": date(2026, 10, 23), "end_date": date(2026, 10, 23)}],
        "صبح", {date(2026, 10, 24)},
        {"صبح": {"start_time": "08:00:00", "end_time": "16:00:00"},
         "شب": {"start_time": "20:00:00", "end_time": "04:00:00"}},
    )
    assert [row["source"] for row in rows] == ["assignment", "holiday", "default"]
    assert rows[0]["end_time"] == "04:00:00"
    assert rows[0]["date_label"] == "۱۴۰۵/۰۸/۰۱"


def test_schedule_marks_holiday_and_none_without_default():
    rows = build_schedule(date(2026, 10, 23), date(2026, 10, 24), [], None, {date(2026, 10, 23)}, {})
    assert [(row["source"], row["shift_type"]) for row in rows] == [("holiday", None), ("none", None)]


def test_schedule_range_is_bounded():
    with pytest.raises(ValueError, match="۶۲"):
        parse_range("2026-01-01", "2026-03-04")
