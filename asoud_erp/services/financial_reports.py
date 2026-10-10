"""Filters of the ERPNext query reports exposed by `api.v1.financial_reports`."""

import json
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


def normalize_item_codes(item_code) -> list[str] | None:
    """Normalizes an item code input (str, JSON list, or list) into a list of strings."""
    if not item_code:
        return None
    if isinstance(item_code, str):
        item_code = item_code.strip()
        if not item_code:
            return None
        if item_code.startswith("[") and item_code.endswith("]"):
            try:
                parsed = json.loads(item_code)
                if isinstance(parsed, list):
                    normalized = [str(x).strip() for x in parsed if str(x).strip()]
                    return normalized or None
            except (json.JSONDecodeError, ValueError):
                pass
        return [item_code]
    if isinstance(item_code, (list, tuple, set)):
        normalized = [str(x).strip() for x in item_code if str(x).strip()]
        return normalized or None
    return [str(item_code).strip()]


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
        items = normalize_item_codes(item_code)
        if items:
            filters["item_code"] = items
        return name, filters
    if periodicity not in PERIODICITIES:
        raise ValueError("Invalid periodicity")
    filters.update({"filter_based_on": "Date Range", "period_start_date": start, "period_end_date": end,
                    "periodicity": periodicity, "accumulated_values": 1 if report == "balance_sheet" else 0,
                    "include_default_book_entries": 1})
    return name, filters
