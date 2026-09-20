import math
from datetime import date
from typing import Any


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
            try:
                if isinstance(value, bool) or not math.isfinite(float(value)):
                    raise ValueError("Numeric value must be finite")
                result[key] = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid numeric workflow field: {key}") from error
        elif field_type == "Checkbox":
            if not isinstance(value, (bool, int)) or value not in (0, 1):
                raise ValueError(f"Invalid checkbox workflow field: {key}")
            result[key] = bool(value)
        elif field_type == "Choice":
            options = field.get("options") or []
            if value not in options:
                raise ValueError(f"Invalid workflow choice: {key}")
            result[key] = str(value)
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
