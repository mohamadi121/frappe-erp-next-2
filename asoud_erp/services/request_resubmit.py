"""Pure helpers that describe what the requester changed when resubmitting a returned request."""

import json

from asoud_erp.services.request_serializer import SENSITIVE_MASK

_MAX_TEXT = 200


def _shown(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        return f"{len(value)} ردیف"
    return (json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value))[:_MAX_TEXT]


def diff_values(before: dict, after: dict, fields: list[dict]) -> list[dict]:
    """The changed keys as `{key, label, before, after}`; sensitive values are masked."""
    before, after = before or {}, after or {}
    labels = {field.get("key"): field for field in fields or [] if isinstance(field, dict)}
    rows = []
    for key in list(after) + [key for key in before if key not in after]:
        old, new = before.get(key), after.get(key)
        if (old or None) == (new or None):
            continue
        field = labels.get(key) or {}
        masked = field.get("sensitive") is True
        rows.append({"key": key, "label": field.get("label") or key,
                     "before": SENSITIVE_MASK if masked and old else _shown(old),
                     "after": SENSITIVE_MASK if masked and new else _shown(new)})
    return rows


def changes_comment(rows: list[dict]) -> str:
    return json.dumps({"changes": rows}, ensure_ascii=False)
