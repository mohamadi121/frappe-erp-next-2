"""Input shape of HR self-service documents (HRMS keeps all business rules)."""

from datetime import date
from typing import Any

from asoud_erp.services.transaction_lines import number, parse_json

LOG_TYPES = {"IN", "OUT"}
TRAVEL_TYPES = {"Domestic", "International"}
TRAVEL_MODES = {"Air", "Rail", "Bus", "Taxi", "Car", "Other", ""}
MAX_ROWS = 50


def iso_date(value: Any, name: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as error:
        raise ValueError(f"{name} must be a YYYY-MM-DD date") from error


def date_span(from_date: Any, to_date: Any) -> tuple[str, str]:
    start, end = iso_date(from_date, "From date"), iso_date(to_date, "To date")
    if start > end:
        raise ValueError("From date must not be after to date")
    return start, end


def coordinates(latitude: Any, longitude: Any) -> tuple[float, float] | None:
    if latitude in (None, "") and longitude in (None, ""):
        return None
    lat, lon = number(latitude, "Latitude"), number(longitude, "Longitude")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Location is out of range")
    return lat, lon


def _rows(value: Any, name: str, required: bool) -> list[dict]:
    rows = parse_json(value, name) or []
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(r, dict) for r in rows):
        raise ValueError(f"{name} must be a list of objects")
    if required and not rows:
        raise ValueError(f"At least one {name} row is required")
    return rows


def _text(row: dict, key: str, limit: int = 140, required: bool = False) -> str:
    text = str(row.get(key) or "").strip()
    if required and not text:
        raise ValueError(f"{key} is required")
    if len(text) > limit:
        raise ValueError(f"{key} is too long")
    return text


def normalize_itinerary(value: Any) -> list[dict]:
    """Travel Itinerary rows of a mission (Travel Request)."""
    result = []
    for row in _rows(value, "itinerary", required=True):
        departure = iso_date(row.get("departure_date"), "Departure date")
        arrival = row.get("arrival_date")
        mode = _text(row, "mode_of_travel")
        if mode not in TRAVEL_MODES:
            raise ValueError("Invalid mode of travel")
        item = {
            "travel_from": _text(row, "travel_from", required=True),
            "travel_to": _text(row, "travel_to", required=True),
            "departure_date": departure,
        }
        if arrival not in (None, ""):
            item["arrival_date"] = iso_date(arrival, "Arrival date")
            if item["arrival_date"] < departure:
                raise ValueError("Arrival must not be before departure")
        if mode:
            item["mode_of_travel"] = mode
        result.append(item)
    return result


def normalize_costings(value: Any) -> list[dict]:
    """Travel Request Costing rows (`expense_type` is an Expense Claim Type)."""
    return [
        {
            "expense_type": _text(row, "expense_type", required=True),
            "total_amount": number(row.get("total_amount"), "Amount", minimum=0, allow_equal=False),
            "comments": _text(row, "comments", 500),
        }
        for row in _rows(value, "costings", required=False)
    ]


def normalize_expenses(value: Any) -> list[dict]:
    """Expense Claim Detail rows."""
    return [
        {
            "expense_type": _text(row, "expense_type", required=True),
            "expense_date": iso_date(row.get("expense_date"), "Expense date"),
            "amount": number(row.get("amount"), "Amount", minimum=0, allow_equal=False),
            "description": _text(row, "description", 500),
        }
        for row in _rows(value, "expenses", required=True)
    ]
