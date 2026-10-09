"""Pure helpers that shape request rows for the list and detail responses."""

from __future__ import annotations

import copy
from typing import Any

from asoud_erp.services.request_status import priority_label

SEARCH_TEXT_LIMIT = 4000


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
