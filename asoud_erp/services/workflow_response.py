import math
import re
from datetime import date
from typing import Any

from asoud_erp.services.request_lookup import parse_delivery_location

MAX_ITEM_ROWS = 100
MAX_TEXT_LENGTH = 10000
ITEM_ROW_INPUTS = {"item_code", "qty", "uom", "description"}
# Filled from ERPNext on save; accepted back (and recomputed) when a draft is resubmitted.
ITEM_ROW_DERIVED = {"item_name", "stock_uom", "conversion_factor", "stock_qty", "is_stock_item"}
# Added by the detail serializer only; never stored, ignored when a client sends it back.
ITEM_ROW_TRANSIENT = {"attachment_ref"}
ROW_NOTE_LENGTH = 500
ROW_DESCRIPTION_LENGTH = 1000
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
FILE_PREFIXES = ("/private/files/", "/files/")


def _finite_number(value: Any, key: str) -> float:
    try:
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError("Numeric value must be finite")
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid numeric workflow field: {key}") from error


def _file_reference(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.startswith(FILE_PREFIXES):
        raise ValueError(f"Invalid workflow attachment: {key}")
    return value


def _item_rows(value: Any, key: str, row_options: dict | None = None) -> list[dict[str, Any]]:
    """Shape of an item table; item and UOM names are checked against ERPNext later.

    Without `row_options` the legacy rows (code, quantity, UOM, description) are kept.
    With them the row may also carry a `note` and a file `attachment`, if enabled.
    """
    options = row_options if isinstance(row_options, dict) else None
    max_rows = min(int((options or {}).get("max_rows") or MAX_ITEM_ROWS), MAX_ITEM_ROWS)
    min_rows = int((options or {}).get("min_rows") or 0)
    if not isinstance(value, list) or len(value) > max_rows or len(value) < min_rows:
        raise ValueError(f"Invalid item table: {key}")
    allow_note = bool(options and options.get("note"))
    allow_attachment = bool(options and options.get("attachment"))
    allowed = ITEM_ROW_INPUTS | ITEM_ROW_DERIVED | ITEM_ROW_TRANSIENT
    if allow_note:
        allowed = allowed | {"note"}
    if allow_attachment:
        allowed = allowed | {"attachment"}
    rows = []
    for row in value:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError(f"Invalid item table row: {key}")
        item_code = str(row.get("item_code") or "").strip()
        qty = _finite_number(row.get("qty"), key)
        if not item_code or len(item_code) > 140 or qty <= 0:
            raise ValueError(f"Item table rows need an item and a positive quantity: {key}")
        uom = str(row.get("uom") or "").strip()
        description = str(row.get("description") or "").strip()
        if len(uom) > 140 or len(description) > ROW_DESCRIPTION_LENGTH:
            raise ValueError(f"Invalid item table row: {key}")
        result = {"item_code": item_code, "qty": qty, "uom": uom or None, "description": description}
        if allow_note:
            note = str(row.get("note") or "").strip()
            if len(note) > ROW_NOTE_LENGTH:
                raise ValueError(f"Invalid item table row: {key}")
            result["note"] = note
        if allow_attachment:
            attachment = row.get("attachment")
            result["attachment"] = _file_reference(attachment, key) if attachment else None
        rows.append(result)
    return rows


def _is_visible(field: dict, raw: dict) -> bool:
    rule = field.get("visible_when")
    if not isinstance(rule, dict):
        return True
    actual = raw.get(rule.get("field"))
    if "in" in rule:
        return actual in (rule.get("in") or [])
    return actual == rule.get("equals")


def _visibility(definitions: dict[str, dict], raw: dict) -> dict[str, bool]:
    """`visible_when` of every field against the raw response; a hidden field counts as unset."""
    visible: dict[str, bool] = {}
    for _round in range(len(definitions) + 1):
        view = {key: raw.get(key) if visible.get(key, True) else None for key in definitions}
        current = {key: _is_visible(field, view) for key, field in definitions.items()}
        if current == visible:
            break
        visible = current
    return visible


def _text(value: Any, key: str, field: dict) -> str:
    limit = min(int(field.get("max_length") or MAX_TEXT_LENGTH), MAX_TEXT_LENGTH)
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Invalid text field: {key}")
    return value.strip()


def normalize_form_response(fields: Any, response: Any, allow_auto: bool = False) -> dict[str, Any]:
    """Validates a form response against the field definitions.

    `Auto` fields are computed by the server: a client value is rejected unless
    `allow_auto` is set (a form task draft carries values the server computed earlier),
    in which case it is ignored. They never appear in the result.
    """
    if not isinstance(fields, list) or not isinstance(response, dict):
        raise ValueError("Invalid workflow form response")
    definitions = {str(field.get("key")): field for field in fields if isinstance(field, dict)}
    unknown = set(response) - set(definitions)
    if unknown:
        raise ValueError("Workflow response contains unknown fields")
    if not allow_auto and any(
        definitions[key].get("type") == "Auto" and response[key] not in (None, "") for key in response
    ):
        raise ValueError("Auto fields are computed by the server")
    visible = _visibility(definitions, response)
    result: dict[str, Any] = {}
    for key, field in definitions.items():
        field_type = field.get("type")
        if field_type == "Auto":
            continue
        if not visible.get(key, True):
            result[key] = None
            continue
        value = response.get(key)
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
        elif field_type == "System Select":
            if not isinstance(value, str) or not value.strip() or len(value) > 140:
                raise ValueError(f"Invalid linked record: {key}")
            result[key] = value.strip()
            if field.get("source") == "delivery_location":
                parse_delivery_location(result[key])
        elif field_type == "Time":
            if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
                raise ValueError(f"Invalid time field: {key}")
            result[key] = value
        elif field_type == "Item Table":
            result[key] = _item_rows(value, key, field.get("row_options"))
        elif field_type == "Table":
            if not isinstance(value, list) or len(value) > MAX_ITEM_ROWS:
                raise ValueError(f"Invalid table: {key}")
            columns = field.get("columns")
            if not isinstance(columns, list) or not columns:
                raise ValueError(f"Table columns are missing: {key}")
            result[key] = [normalize_form_response(columns, row) for row in value]
        elif field_type == "Attachment":
            result[key] = _file_reference(value, key)
        elif field_type == "Date":
            result[key] = date.fromisoformat(str(value)).isoformat()
        else:
            result[key] = _text(value, key, field)
            if field.get("required") and not result[key]:
                raise ValueError(f"Required workflow field is empty: {key}")
    return result


def map_attachment_values(fields: list, response: dict, mapper) -> dict:
    """Transform attachment references without dropping unknown keys.

    Shape validation remains the responsibility of normalize_form_response.
    Used before upload validation and after private File records are created.
    Attachment fields, the file of an Item Table row and Table columns are mapped.
    """
    result = dict(response)
    for field in fields:
        key = field.get("key")
        value = result.get(key)
        if field.get("type") == "Attachment" and value:
            result[key] = mapper(value)
        elif field.get("type") == "Item Table" and isinstance(value, list):
            result[key] = [
                {**row, "attachment": mapper(row["attachment"])}
                if isinstance(row, dict) and row.get("attachment") else row
                for row in value
            ]
        elif field.get("type") == "Table" and isinstance(value, list):
            result[key] = [
                map_attachment_values(field.get("columns") or [], row, mapper)
                if isinstance(row, dict) else row
                for row in value
            ]
    return result


def attachment_references(fields: list, response: dict) -> list[tuple[str, str]]:
    """`(scope, reference)` of every file a response points to.

    Scopes are `field:<key>` and `row:<field_key>:<index>`; a Table column counts as its field.
    """
    found: list[tuple[str, str]] = []
    for field in fields:
        key = field.get("key")
        value = response.get(key)
        if field.get("type") == "Attachment" and isinstance(value, str) and value:
            found.append((f"field:{key}", value))
        elif field.get("type") == "Item Table" and isinstance(value, list):
            for index, row in enumerate(value):
                if isinstance(row, dict) and isinstance(row.get("attachment"), str) and row["attachment"]:
                    found.append((f"row:{key}:{index}", row["attachment"]))
        elif field.get("type") == "Table" and isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    found.extend((f"field:{key}", ref) for _scope, ref in
                                 attachment_references(field.get("columns") or [], row))
    return found
