from datetime import date

from asoud_erp.services.jalali import current_jalali_year, jalali_fiscal_period, jalali_to_gregorian


def test_jalali_new_year_1405():
    assert jalali_to_gregorian(1405, 1, 1).isoformat() == "2026-03-21"


def test_current_jalali_year_changes_on_new_year():
    assert current_jalali_year(date(2026, 3, 20)) == 1404
    assert current_jalali_year(date(2026, 3, 21)) == 1405


def test_fiscal_period_ends_before_next_start():
    start, end = jalali_fiscal_period(1405, 1, 1)
    assert start.isoformat() == "2026-03-21"
    assert end.isoformat() == "2027-03-20"


def test_gregorian_to_jalali_known_pairs_and_leap_years():
    from datetime import date, timedelta

    from asoud_erp.services.jalali import gregorian_to_jalali, jalali_to_gregorian

    assert gregorian_to_jalali(date(2026, 10, 20)) == (1405, 7, 28)
    assert gregorian_to_jalali(date(2026, 3, 21)) == (1405, 1, 1)
    assert gregorian_to_jalali(date(2026, 3, 20)) == (1404, 12, 29)
    # 1403 is a leap year: it has a 30th of Esfand
    assert gregorian_to_jalali(date(2025, 3, 20)) == (1403, 12, 30)
    assert gregorian_to_jalali(date(2025, 3, 21)) == (1404, 1, 1)
    day = date(2019, 1, 1)
    for offset in range(0, 4000, 7):
        assert jalali_to_gregorian(*gregorian_to_jalali(day + timedelta(offset))) == day + timedelta(offset)
