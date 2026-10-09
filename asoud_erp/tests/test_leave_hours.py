"""Pure tests for the leave hour/day maths (no site needed)."""

import pytest

from asoud_erp.services import leave_hours as lh


def test_four_hours_at_eight_is_half_a_day():
    duration = lh.hourly_duration("09:00", "13:00", 8)
    assert duration == {"unit": "hour", "days": None, "hours": 4.0, "day_equivalent": 0.5}
    assert lh.ledger_leaves(4.0, 8) == -0.5


def test_one_and_a_half_hours_is_0_1875_of_a_day():
    duration = lh.hourly_duration("10:00", "11:30", 8)
    assert duration["hours"] == 1.5
    assert duration["day_equivalent"] == 0.1875
    assert lh.ledger_leaves(1.5, 8) == -0.1875


def test_more_than_the_daily_hours_is_refused():
    with pytest.raises(lh.LeaveRuleError) as error:
        lh.hourly_duration("07:00", "16:00", 8)  # 9 hours
    assert error.value.code == "HOURLY_EXCEEDS_DAY"
    assert error.value.field == "end_time"


def test_exactly_the_daily_hours_is_allowed():
    duration = lh.hourly_duration("08:00", "16:00", 8)
    assert (duration["hours"], duration["day_equivalent"]) == (8.0, 1.0)


def test_ten_minutes_fails_the_minimum_and_fifteen_passes():
    with pytest.raises(lh.LeaveRuleError) as error:
        lh.hourly_duration("09:00", "09:10", 8)
    assert error.value.code == "INVALID_TIME_RANGE"
    assert "۱۵" in error.value.message
    assert lh.hourly_duration("09:00", "09:15", 8)["hours"] == 0.25
    assert lh.hourly_duration("09:00", "09:15", 8)["day_equivalent"] == 0.0313  # 0.03125 half-up


@pytest.mark.parametrize("start,end", [("10:00", "10:00"), ("11:00", "10:00")])
def test_end_must_be_after_start(start, end):
    with pytest.raises(lh.LeaveRuleError) as error:
        lh.hourly_duration(start, end, 8)
    assert error.value.code == "INVALID_TIME_RANGE"


@pytest.mark.parametrize("value", ["24:00", "9:30", "09:60", "", None, 930, "09-30"])
def test_malformed_times_are_refused(value):
    with pytest.raises(lh.LeaveRuleError) as error:
        lh.hourly_duration(value, "12:00", 8)
    assert error.value.code == "INVALID_TIME_RANGE"


def test_seven_and_a_half_hour_company():
    # The limit is 450 minutes, not 480.
    assert lh.hourly_duration("08:00", "15:30", 7.5)["day_equivalent"] == 1.0
    with pytest.raises(lh.LeaveRuleError) as error:
        lh.hourly_duration("08:00", "15:31", 7.5)
    assert error.value.code == "HOURLY_EXCEEDS_DAY"
    # 4 h of 7.5 h: 0.53333.. -> 0.5333; the ledger keeps six decimals.
    assert lh.day_equivalent(4.0, 7.5) == 0.5333
    assert lh.ledger_leaves(4.0, 7.5) == -0.533333
    assert lh.day_equivalent(3.75, 7.5) == 0.5
    assert lh.ledger_leaves(3.75, 7.5) == -0.5


def test_day_equivalent_rounds_half_up_to_four_decimals():
    # 1/3 h = 0.33 h stored; 0.33 / 8 = 0.04125 -> 0.0413 (banker's rounding would give 0.0412).
    assert lh.hours_from_minutes(20) == 0.33
    assert lh.day_equivalent(0.33, 8) == 0.0413
    assert lh.hours_from_minutes(40) == 0.67
    assert lh.hours_from_minutes(45) == 0.75
    assert lh.round_half_up(0.125, 2) == 0.13
    assert lh.round_half_up(2.675, 2) == 2.68  # float repr trap: round() gives 2.67


def test_negative_zero_is_never_produced():
    assert str(lh.round_half_up(-0.0004, 3)) == "0.0"
    assert str(lh.round_half_up(-0.0, 2)) == "0.0"
    assert lh.round_half_up(-0.0005, 3) == -0.001


def test_total_of_the_day_is_capped_by_other_hourly_leave():
    lh.hourly_duration("09:00", "13:00", 8, other_minutes=4 * 60)  # 8 h in total: fine
    with pytest.raises(lh.LeaveRuleError) as error:
        lh.hourly_duration("09:00", "13:01", 8, other_minutes=4 * 60)
    assert error.value.code == "HOURLY_EXCEEDS_DAY"
    assert "مجموع" in error.value.message


def test_daily_hours_fall_back_to_eight():
    for junk in (None, "", 0, -3, "abc"):
        assert lh.daily_hours_value(junk) == 8
    assert lh.day_equivalent(4, None) == 0.5


def test_daily_duration_is_one_decimal_and_equals_day_equivalent():
    assert lh.daily_duration(3) == {"unit": "day", "days": 3.0, "hours": None, "day_equivalent": 3.0}
    assert lh.daily_duration(2.5)["day_equivalent"] == 2.5


def test_overlap_is_half_open():
    a, b = lh.parse_hhmm("09:00"), lh.parse_hhmm("10:00")
    c, d = lh.parse_hhmm("10:00"), lh.parse_hhmm("11:00")
    assert not lh.minutes_overlap(a, b, c, d)
    assert lh.minutes_overlap(a, d, c, d)
    assert lh.minutes_overlap(a, b, a, b)


def test_generated_subject():
    assert lh.leave_subject("annual", "Daily") == "مرخصی سالانه (روزانه)"
    assert lh.leave_subject("sick", "Hourly") == "مرخصی استعلاجی (ساعتی)"
    assert lh.leave_subject("unpaid", "Daily") == "مرخصی بدون حقوق (روزانه)"
    assert lh.leave_subject(None, "Daily") == "مرخصی سایر (روزانه)"


def test_duration_text():
    assert lh.duration_text(lh.hourly_duration("09:00", "10:30", 8)) == "1.5 ساعت"
    assert lh.duration_text(lh.daily_duration(3)) == "3 روز"
