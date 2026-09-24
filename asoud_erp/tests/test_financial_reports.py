import pytest

from asoud_erp.services.financial_reports import REPORTS, report_filters


def test_ageing_reports_need_a_report_date_and_set_the_party_type() -> None:
    name, filters = report_filters("receivable", "Tabaan", report_date="2026-09-24", party="CUST-1")
    assert name == "Accounts Receivable"
    assert filters == {"company": "Tabaan", "report_date": "2026-09-24", "ageing_based_on": "Due Date",
                       "range": "30, 60, 90, 120", "party_type": "Customer", "party": ["CUST-1"]}
    assert report_filters("payable", "Tabaan", report_date="2026-09-24")[1]["party_type"] == "Supplier"


def test_statements_use_a_date_range() -> None:
    name, filters = report_filters("balance_sheet", "Tabaan", from_date="2026-03-21", to_date="2027-03-20",
                                   periodicity="Monthly")
    assert name == "Balance Sheet"
    assert (filters["filter_based_on"], filters["periodicity"], filters["accumulated_values"]) == (
        "Date Range", "Monthly", 1)
    assert report_filters("profit_and_loss", "T", from_date="2026-01-01", to_date="2026-12-31")[1][
        "accumulated_values"] == 0
    _, stock = report_filters("stock_balance", "T", from_date="2026-01-01", to_date="2026-01-31",
                              warehouse="Stores - T")
    assert stock == {"company": "T", "from_date": "2026-01-01", "to_date": "2026-01-31",
                     "warehouse": "Stores - T"}


@pytest.mark.parametrize("args", [
    {"report": "cash_flow"},
    {"report": "receivable"},
    {"report": "balance_sheet", "from_date": "2026-12-31", "to_date": "2026-01-01"},
    {"report": "profit_and_loss", "from_date": "2026-01-01", "to_date": "2026-12-31", "periodicity": "Daily"},
    {"report": "stock_balance", "from_date": "1405/01/01", "to_date": "2026-12-31"},
])
def test_invalid_filters(args) -> None:
    with pytest.raises(ValueError):
        report_filters(args.pop("report"), "T", **args)


def test_every_report_has_an_erpnext_name() -> None:
    assert set(REPORTS) == {"receivable", "payable", "profit_and_loss", "balance_sheet", "stock_balance"}
