"""Input shape of transaction lines (sales, purchase and stock documents).

Only the shape is checked here; item, UOM, warehouse and price rules stay with
ERPNext's own controllers, which run when the document is validated.
"""

import json
import math
from typing import Any

MAX_LINES = 200


def parse_json(value: Any, name: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{name} is not valid JSON") from error
    return value


def number(value: Any, name: str, *, minimum: float | None = None, allow_equal: bool = True) -> float:
    try:
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error
    if minimum is not None and (result < minimum or (not allow_equal and result == minimum)):
        raise ValueError(f"{name} must be {'at least' if allow_equal else 'greater than'} {minimum:g}")
    return result


def _text(row: dict, key: str, limit: int = 140) -> str | None:
    value = str(row.get(key) or "").strip()
    if len(value) > limit:
        raise ValueError(f"{key} is too long")
    return value or None


def normalize_lines(
    items: Any,
    *,
    rates: bool = False,
    warehouses: bool = False,
    target_warehouses: bool = False,
) -> list[dict]:
    """Returns ``[{item_code, qty, uom?, rate?, discount_percentage?, warehouse?, ...}]``.

    ``rate`` and ``discount_percentage`` are kept only when ``rates`` is true; a
    missing rate lets ERPNext price the line from the price list.
    """
    values = parse_json(items, "items")
    if not isinstance(values, list) or not values:
        raise ValueError("At least one item line is required")
    if len(values) > MAX_LINES:
        raise ValueError(f"At most {MAX_LINES} item lines are allowed")
    lines = []
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("Item line is not valid")
        item_code = _text(row, "item_code")
        if not item_code:
            raise ValueError("Item code is required")
        line: dict[str, Any] = {
            "item_code": item_code,
            "qty": number(row.get("qty"), "Quantity", minimum=0, allow_equal=False),
        }
        if uom := _text(row, "uom"):
            line["uom"] = uom
        if description := _text(row, "description", 1000):
            line["description"] = description
        if rates:
            if row.get("rate") not in (None, ""):
                line["rate"] = number(row["rate"], "Rate", minimum=0)
            if row.get("discount_percentage") not in (None, ""):
                discount = number(row["discount_percentage"], "Discount", minimum=0)
                if discount > 100:
                    raise ValueError("Discount must be at most 100")
                line["discount_percentage"] = discount
        if warehouses and (warehouse := _text(row, "warehouse")):
            line["warehouse"] = warehouse
        if target_warehouses:
            if source := _text(row, "s_warehouse"):
                line["s_warehouse"] = source
            if target := _text(row, "t_warehouse"):
                line["t_warehouse"] = target
        lines.append(line)
    return lines


def paging(limit_start: Any, limit_page_length: Any, maximum: int = 100) -> tuple[int, int]:
    start = int(number(limit_start or 0, "limit_start", minimum=0))
    length = int(number(limit_page_length or 20, "limit_page_length", minimum=1))
    return start, min(length, maximum)


PAYMENT_TYPES = {"Receive", "Pay"}
PARTY_TYPES = {"Customer", "Supplier", "Employee"}
REFERENCE_DOCTYPES = {
    "Customer": {"Sales Invoice", "Sales Order"},
    "Supplier": {"Purchase Invoice", "Purchase Order"},
    "Employee": {"Expense Claim", "Employee Advance"},
}


def normalize_references(references: Any, party_type: str, amount: float) -> list[dict]:
    """Invoice/order allocations of a payment; their total may not exceed ``amount``."""
    values = parse_json(references, "references") or []
    if not isinstance(values, list) or len(values) > MAX_LINES:
        raise ValueError("references must be a list")
    allowed = REFERENCE_DOCTYPES.get(party_type, set())
    rows, seen = [], set()
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("Payment reference is not valid")
        doctype = str(row.get("reference_doctype") or "").strip()
        name = str(row.get("reference_name") or "").strip()
        if doctype not in allowed or not name:
            raise ValueError(f"{party_type} payments cannot reference {doctype or 'this document'}")
        if (doctype, name) in seen:
            raise ValueError("A document is referenced twice")
        seen.add((doctype, name))
        rows.append({
            "reference_doctype": doctype,
            "reference_name": name,
            "allocated_amount": number(row.get("allocated_amount"), "Allocated amount",
                                       minimum=0, allow_equal=False),
        })
    if round(sum(row["allocated_amount"] for row in rows), 6) > round(amount, 6):
        raise ValueError("Allocated amounts exceed the payment amount")
    return rows
