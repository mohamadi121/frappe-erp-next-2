import math
from datetime import date
from typing import Any

MAX_ITEM_ROWS = 100
ITEM_ROW_INPUTS = {"item_code", "qty", "uom", "description"}
# Filled from ERPNext on save; accepted back (and recomputed) when a draft is resubmitted.
ITEM_ROW_DERIVED = {"item_name", "stock_uom", "conversion_factor", "stock_qty"}


def _finite_number(value: Any, key: str) -> float:
    try:
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError("Numeric value must be finite")
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid numeric workflow field: {key}") from error


def _item_rows(value: Any, key: str) -> list[dict[str, Any]]:
    """Shape of an item table; item and UOM names are checked against ERPNext later."""
    if not isinstance(value, list) or len(value) > MAX_ITEM_ROWS:
        raise ValueError(f"Invalid item table: {key}")
    rows = []
    for row in value:
        if not isinstance(row, dict) or set(row) - ITEM_ROW_INPUTS - ITEM_ROW_DERIVED:
            raise ValueError(f"Invalid item table row: {key}")
        item_code = str(row.get("item_code") or "").strip()
        qty = _finite_number(row.get("qty"), key)
        if not item_code or len(item_code) > 140 or qty <= 0:
            raise ValueError(f"Item table rows need an item and a positive quantity: {key}")
        uom = str(row.get("uom") or "").strip()
        description = str(row.get("description") or "").strip()
        if len(uom) > 140 or len(description) > 1000:
            raise ValueError(f"Invalid item table row: {key}")
        rows.append({"item_code": item_code, "qty": qty, "uom": uom or None, "description": description})
    return rows


def normalize_form_response(fields: Any, response: Any) -> dict[str, Any]:
    if not isinstance(fields, list) or not isinstance(response, dict):
        raise ValueError("Invalid workflow form response")
    definitions = {str(field.get("key")): field for field in fields if isinstance(field, dict)}
    unknown = set(response) - set(definitions)
    if unknown:
        raise ValueError("Workflow response contains unknown fields")
    result: dict[str, Any] = {}
    for key, field in definitions.items():
        value = response.get(key)
        field_type = field.get("type")
        empty = value is None or value == "" or value == []
        if field.get("required") and empty:
            raise ValueError(f"Required workflow field is empty: {key}")
        if empty:
            result[key] = None
        elif field_type in {"Number", "Currency"}:
            result[key] = _finite_number(value, key)
        elif field_type == "Checkbox":
            if not isinstance(value, (bool, int)) or value not in (0, 1):
                raise ValueError(f"Invalid checkbox workflow field: {key}")
            result[key] = bool(value)
        elif field_type == "Choice":
            options = field.get("options") or []
            if value not in options:
                raise ValueError(f"Invalid workflow choice: {key}")
            result[key] = str(value)
        elif field_type == "Multi Choice":
            options = field.get("options") or []
            if not isinstance(value, list) or any(item not in options for item in value):
                raise ValueError(f"Invalid workflow choice: {key}")
            result[key] = [str(item) for item in dict.fromkeys(value)]
        elif field_type in {"User", "Department"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 140:
                raise ValueError(f"Invalid linked record: {key}")
            result[key] = value.strip()
        elif field_type == "Item Table":
            result[key] = _item_rows(value, key)
        elif field_type == "Attachment":
            if not isinstance(value, str) or not value.startswith(("/private/files/", "/files/")):
                raise ValueError(f"Invalid workflow attachment: {key}")
            result[key] = value
        elif field_type == "Date":
            result[key] = date.fromisoformat(str(value)).isoformat()
        else:
            if not isinstance(value, str) or len(value) > 10000:
                raise ValueError(f"Invalid text field: {key}")
            result[key] = value.strip()
            if field.get("required") and not result[key]:
                raise ValueError(f"Required workflow field is empty: {key}")
    return result
