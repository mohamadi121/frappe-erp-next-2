"""Filters of the ERPNext query reports exposed by `api.v1.financial_reports`."""

from datetime import date

REPORTS = {
    "receivable": "Accounts Receivable",
    "payable": "Accounts Payable",
    "profit_and_loss": "Profit and Loss Statement",
    "balance_sheet": "Balance Sheet",
    "stock_balance": "Stock Balance",
}
PERIODICITIES = {"Monthly", "Quarterly", "Half-Yearly", "Yearly"}
AGEING_RANGE = "30, 60, 90, 120"


def _date(value, name: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise ValueError(f"{name} must be a YYYY-MM-DD date") from error


def report_filters(report: str, company: str, *, from_date=None, to_date=None, report_date=None,
                   periodicity: str = "Yearly", party=None, warehouse=None, item_code=None) -> tuple[str, dict]:
    """(ERPNext report name, filters) for one of ``REPORTS``."""
    if report not in REPORTS:
        raise ValueError("Unknown report")
    name = REPORTS[report]
    filters: dict = {"company": company}
    if report in {"receivable", "payable"}:
        filters.update({"report_date": _date(report_date, "Report date"), "ageing_based_on": "Due Date",
                        "range": AGEING_RANGE, "party_type": "Customer" if report == "receivable" else "Supplier"})
        if party:
            filters["party"] = [party]
        return name, filters
    start, end = _date(from_date, "From date"), _date(to_date, "To date")
    if start > end:
        raise ValueError("From date must not be after to date")
    if report == "stock_balance":
        filters.update({"from_date": start, "to_date": end})
        if warehouse:
            filters["warehouse"] = warehouse
        if item_code:
            filters["item_code"] = item_code
        return name, filters
    if periodicity not in PERIODICITIES:
        raise ValueError("Invalid periodicity")
    filters.update({"filter_based_on": "Date Range", "period_start_date": start, "period_end_date": end,
                    "periodicity": periodicity, "accumulated_values": 1 if report == "balance_sheet" else 0,
                    "include_default_book_entries": 1})
    return name, filters
