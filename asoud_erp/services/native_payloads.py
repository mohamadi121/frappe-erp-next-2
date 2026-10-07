"""Pure builders of the native documents created after final approval (CONTRACT 4.12).

No ``frappe`` import: each function turns the effective request values into the
dict a ``frappe.get_doc`` call needs, so the mapping tables are unit-tested without a
site. ``request_native_documents`` does the lookups (default warehouse, holiday
list, approver), inserts the documents and keeps idempotency.
"""

from typing import Any

from asoud_erp.services.leave_hours import ledger_leaves

LEDGER_TRANSACTION_TYPE = "ASOUD Workflow Request"
DELIVERY_KINDS = ("warehouse", "branch", "department")

# supply_method -> Material Request type, or None for "no native document" (CONTRACT 4.12).
SUPPLY_MATERIAL_REQUEST_TYPES = {
    "Purchase": "Purchase",
    "Warehouse": "Material Issue",
    "Transfer": "Material Transfer",
    "Contract": None,
    "Unspecified": None,
}
NO_NATIVE_DOCUMENT = "NO_NATIVE_DOCUMENT"


def parse_delivery_location(value: Any) -> tuple[str, str] | None:
    """``"warehouse:Stores - WP"`` -> ``("warehouse", "Stores - WP")``; ``None`` when malformed."""
    if not isinstance(value, str) or ":" not in value:
        return None
    kind, name = value.split(":", 1)
    kind, name = kind.strip(), name.strip()
    if kind not in DELIVERY_KINDS or not name:
        return None
    return kind, name


def supply_material_request_type(supply_method: str | None) -> str | None:
    return SUPPLY_MATERIAL_REQUEST_TYPES.get(supply_method or "")


def row_description(row: dict) -> str:
    """Row description plus row note, joined by a newline; empty parts are skipped."""
    parts = [str(row.get("description") or "").strip(), str(row.get("note") or "").strip()]
    return "\n".join(part for part in parts if part)


def _item_row(row: dict, *, schedule_date: str, warehouse: str | None, project: str | None,
              cost_center: str | None) -> dict:
    result = {
        "item_code": row["item_code"],
        "qty": row["qty"],
        "uom": row.get("uom") or row.get("stock_uom"),
        "stock_uom": row.get("stock_uom"),
        "conversion_factor": row.get("conversion_factor") or 1,
        "schedule_date": schedule_date,
    }
    description = row_description(row)
    if description:
        result["description"] = description
    for key, value in (("warehouse", warehouse), ("project", project), ("cost_center", cost_center)):
        if value:
            result[key] = value
    return result


def material_request_payload(
    *, template_key: str, request_name: str, company: str, creation_date: str, values: dict,
    default_warehouse: str | None = None,
) -> dict | None:
    """Material Request of a purchase or supply request; ``None`` when no document is due.

    Purchase: type Purchase, header ``set_warehouse`` is the Stock Settings default.
    Supply by ``supply_method``:

    * ``Purchase``: type Purchase, ``set_warehouse`` is the delivery warehouse when the
      delivery location is a warehouse, else the default warehouse.
    * ``Warehouse``: type Material Issue, no header warehouse (the storekeeper picks the
      source); rows carry the default warehouse only because ERPNext refuses a stock item
      row without one.
    * ``Transfer``: type Material Transfer, ``set_warehouse`` is the delivery warehouse and
      ``set_from_warehouse`` stays blank.
    * ``Contract``, ``Unspecified`` or empty: ``None`` (the caller records ``Skipped``).
    """
    needed_date = str(values.get("needed_date") or creation_date)
    delivery = parse_delivery_location(values.get("delivery_location"))
    delivery_warehouse = delivery[1] if delivery and delivery[0] == "warehouse" else None
    default_warehouse = default_warehouse or None
    header_warehouse: str | None
    if template_key == "purchase":
        request_type, header_warehouse = "Purchase", default_warehouse
        row_warehouse = header_warehouse
    elif template_key == "supply":
        request_type = supply_material_request_type(values.get("supply_method"))
        if request_type is None:
            return None
        if request_type == "Purchase":
            header_warehouse = delivery_warehouse or default_warehouse
            row_warehouse = header_warehouse
        elif request_type == "Material Transfer":
            header_warehouse = delivery_warehouse
            row_warehouse = header_warehouse
        else:  # Material Issue
            header_warehouse = None
            row_warehouse = default_warehouse
    else:
        raise ValueError(f"No Material Request mapping for template {template_key}")
    project = values.get("project") or None
    cost_center = values.get("cost_center") or None
    payload = {
        "doctype": "Material Request",
        "material_request_type": request_type,
        "company": company,
        "transaction_date": creation_date,
        "schedule_date": needed_date,
        "asoud_request": request_name,
        "items": [
            _item_row(row, schedule_date=needed_date, warehouse=row_warehouse, project=project,
                      cost_center=cost_center)
            for row in values.get("items") or []
        ],
    }
    if header_warehouse:
        payload["set_warehouse"] = header_warehouse
    return payload


def leave_application_payload(
    *, request_name: str, employee: str, company: str, values: dict, creation_date: str,
    approver: str | None,
) -> dict:
    """Daily leave: an already approved Leave Application (CONTRACT 4.12)."""
    return {
        "doctype": "Leave Application",
        "employee": employee,
        "company": company,
        "leave_type": values["leave_type"],
        "from_date": str(values["start_date"]),
        "to_date": str(values["end_date"]),
        "half_day": 0,
        "description": str(values.get("reason") or ""),
        "posting_date": creation_date,
        "leave_approver": approver or None,
        "status": "Approved",
        "asoud_request": request_name,
    }


def leave_ledger_payload(
    *, request_name: str, employee: str, employee_name: str, company: str, values: dict,
    daily_hours: Any, is_lwp: bool, holiday_list: str | None,
) -> dict:
    """Hourly leave: a Leave Ledger Entry of ``-hours / daily hours`` days (CONTRACT 4.12).

    HRMS only counts ``Leave Application`` and ``Leave Encashment`` entries in its own
    balance, so this entry is deducted by ``leave_balance`` instead (CONTRACT 4.11).
    """
    duration = values.get("duration") or {}
    leave_date = str(values["leave_date"])
    return {
        "doctype": "Leave Ledger Entry",
        "employee": employee,
        "employee_name": employee_name,
        "company": company,
        "leave_type": values["leave_type"],
        "transaction_type": LEDGER_TRANSACTION_TYPE,
        "transaction_name": request_name,
        "leaves": ledger_leaves(duration["hours"], daily_hours),
        "from_date": leave_date,
        "to_date": leave_date,
        "is_carry_forward": 0,
        "is_expired": 0,
        "is_lwp": 1 if is_lwp else 0,
        "holiday_list": holiday_list or "",
    }
