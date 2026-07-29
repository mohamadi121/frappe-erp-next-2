from asoud_erp.services.jalali import jalali_fiscal_period, jalali_to_gregorian


def test_jalali_new_year_1405():
    assert jalali_to_gregorian(1405, 1, 1).isoformat() == "2026-03-21"


def test_fiscal_period_ends_before_next_start():
    start, end = jalali_fiscal_period(1405, 1, 1)
    assert start.isoformat() == "2026-03-21"
    assert end.isoformat() == "2027-03-20"
