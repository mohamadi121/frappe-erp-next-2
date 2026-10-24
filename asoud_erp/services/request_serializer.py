"""Pure helpers that shape request rows for the list and detail responses."""

from __future__ import annotations

import copy
from typing import Any

from asoud_erp.services.request_status import priority_label

SEARCH_TEXT_LIMIT = 4000
SENSITIVE_MASK = "محرمانه"


def mask_sensitive_values(values: dict, fields: list[dict], can_view: bool) -> dict:
    """Copy request values and mask schema-marked values for non-participants."""
    result = copy.deepcopy(values or {})
    if can_view:
        return result
    for field in fields or []:
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if key not in result:
            continue
        if field.get("sensitive") is True:
            result[key] = SENSITIVE_MASK
            continue
        if field.get("type") == "Table" and isinstance(result[key], list):
            result[key] = [mask_sensitive_values(row, field.get("columns") or [], False)
                           if isinstance(row, dict) else row for row in result[key]]
    return result


def schema_fields(schema: dict) -> list[dict]:
    """The flat field list of a form-builder schema."""
    return [field for section in (schema or {}).get("sections", []) or []
            for field in section.get("fields", []) or [] if isinstance(field, dict)]


def overlay_sensitive(fields: list[dict], form_fields: list[dict]) -> list[dict]:
    """Workflow fields where a field the form marks `sensitive` (by `workflow_key`) is sensitive too.

    The form designer sets the flag on its own field; the request is stored under the workflow
    field, so the flag is carried over (columns by their own `workflow_key`). The input is not changed.
    """
    flagged = {field.get("workflow_key") for field in form_fields or []
               if field.get("workflow_key") and field.get("sensitive") is True}
    flagged_columns: dict[str, set] = {}
    for field in form_fields or []:
        if field.get("workflow_key") and isinstance(field.get("columns"), list):
            flagged_columns[field["workflow_key"]] = {
                column.get("workflow_key") for column in field["columns"]
                if isinstance(column, dict) and column.get("workflow_key") and column.get("sensitive") is True}
    result = copy.deepcopy(fields or [])
    for field in result:
        if not isinstance(field, dict):
            continue
        if field.get("key") in flagged:
            field["sensitive"] = True
        for column in field.get("columns") or []:
            if isinstance(column, dict) and column.get("key") in flagged_columns.get(field.get("key"), ()):
                column["sensitive"] = True
    return result


def hidden_file_urls(values: dict, fields: list[dict], can_view: bool) -> set[str]:
    """File urls that only sensitive fields point to, which a non-participant must not receive."""
    if can_view:
        return set()
    from asoud_erp.services.workflow_response import attachment_references

    masked = mask_sensitive_values(values, fields, False)
    return ({ref for _scope, ref in attachment_references(fields, values or {})}
            - {ref for _scope, ref in attachment_references(fields, masked)})


def item_rows_of(values: dict | None) -> list[dict]:
    """The item rows of a request: the `items` field, else the first list of rows with an item code."""
    values = values or {}
    candidates = [values.get("items")] + [value for key, value in values.items() if key != "items"]
    for candidate in candidates:
        if isinstance(candidate, list) and candidate and all(
                isinstance(row, dict) and "item_code" in row for row in candidate):
            return candidate
    return []


def item_count(values: dict | None) -> int:
    return len(item_rows_of(values))


def build_search_text(number: str, subject: str, requester_name: str = "", department_name: str = "",
                      project: str = "", items: list[dict] | None = None) -> str:
    """The denormalized text the list search matches (a LIKE on this one column)."""
    parts = [number, subject, requester_name, department_name, project]
    for row in items or []:
        parts += [row.get("item_code"), row.get("item_name")]
    seen: list[str] = []
    for part in parts:
        text = " ".join(str(part or "").split())
        if text and text not in seen:
            seen.append(text)
    return " ".join(seen)[:SEARCH_TEXT_LIMIT]


def with_attachment_refs(values: dict, entries_by_url: dict[str, dict]) -> dict:
    """A copy of `values` whose item rows with a file gain `attachment_ref` (never stored)."""
    result = copy.deepcopy(values)
    for rows in (value for value in result.values() if isinstance(value, list)):
        for row in rows:
            if not isinstance(row, dict) or not row.get("attachment") or "item_code" not in row:
                continue
            entry = entries_by_url.get(row["attachment"])
            if entry:
                row["attachment_ref"] = {"name": entry["name"], "filename": entry["filename"],
                                         "is_image": bool(entry.get("is_image"))}
    return result


def default_summary(values: dict, request_row: dict, labels: dict | None = None) -> dict:
    """List-card summary used when a template has none: organisation, project, priority, date."""
    labels = labels or {}
    values = values or {}
    org_unit = values.get("org_unit") or request_row.get("department") or ""
    project = values.get("project") or request_row.get("project") or ""
    priority = values.get("priority") or request_row.get("priority") or "Normal"
    return {
        "org_unit": org_unit or "",
        "org_unit_label": (labels.get("department") or {}).get(org_unit, org_unit or ""),
        "project": project or "",
        "project_label": (labels.get("project") or {}).get(project, project or ""),
        "priority": priority,
        "priority_label": priority_label(priority),
        "needed_date": str(values.get("needed_date") or request_row.get("required_by") or ""),
    }


def first_per_key(rows: list[dict], key: str) -> dict[Any, dict]:
    """The first row for every value of `key`; rows are expected newest first."""
    result: dict[Any, dict] = {}
    for row in rows:
        result.setdefault(row[key], row)
    return result
