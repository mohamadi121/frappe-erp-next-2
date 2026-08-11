import json


def normalize_purchase_items(items: str | list[dict]) -> list[dict]:
    values = json.loads(items) if isinstance(items, str) else items
    if not isinstance(values, list) or not values:
        raise ValueError("At least one purchase item is required")
    normalized = []
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("Purchase item is not valid")
        item_code = str(row.get("item_code") or "").strip()
        if not item_code:
            raise ValueError("Item code is required")
        try:
            qty = float(row.get("qty") or 0)
        except (TypeError, ValueError) as error:
            raise ValueError("Item quantity is not valid") from error
        if qty <= 0:
            raise ValueError("Item quantity must be greater than zero")
        normalized.append(
            {
                "item_code": item_code,
                "qty": qty,
                "uom": str(row.get("uom") or "").strip() or None,
                "warehouse": str(row.get("warehouse") or "").strip() or None,
                "description": str(row.get("description") or "").strip(),
            }
        )
    return normalized
