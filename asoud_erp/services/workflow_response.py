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
                result[key] = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid numeric workflow field: {key}") from error
        elif field_type == "Checkbox":
            if value not in {True, False, 0, 1}:
                raise ValueError(f"Invalid checkbox workflow field: {key}")
            result[key] = bool(value)
        elif field_type == "Choice":
            options = field.get("options") or []
            if value not in options:
                raise ValueError(f"Invalid workflow choice: {key}")
            result[key] = str(value)
        elif field_type == "Attachment":
            if not isinstance(value, str) or not value.startswith("/files/"):
                raise ValueError(f"Invalid workflow attachment: {key}")
            result[key] = value
        else:
            result[key] = str(value).strip()
    return result
