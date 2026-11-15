import json
from typing import Any


def preceding_stages(stage: str, transitions: list[dict[str, Any]]) -> set[str]:
    """Design-time predecessors, ignoring explicit rejection/correction loops."""
    incoming: dict[str, list[str]] = {}
    for row in transitions:
        raw = row.get('condition_json') or {}
        condition = json.loads(raw) if isinstance(raw, str) else raw
        action = str(condition.get('action') or row.get('transition_label') or '').strip().casefold()
        if action in {'return', 'reject', 'بازگشت برای اصلاح', 'رد'}:
            continue
        incoming.setdefault(row['to_stage'], []).append(row['from_stage'])
    result: set[str] = set()
    pending = [stage]
    while pending:
        for parent in incoming.get(pending.pop(), []):
            if parent not in result:
                result.add(parent)
                pending.append(parent)
    return result - {stage}


def merge_completed_responses(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge responses oldest-to-newest so later corrections win."""
    merged: dict[str, Any] = {}
    for row in rows:
        raw = row.get("response_json") or "{}"
        response = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(response, dict):
            merged.update(response)
    return merged


def select_return_stage(rows: list[dict[str, Any]]) -> str:
    """Prefer the newest editable human stage, then the newest user task.

    An Approval stage that collected a supplementary form is editable as well.
    """
    user_tasks = [row for row in rows if row.get("stage_type") == "User Task"]
    supplementary = [row for row in rows
                     if row.get("stage_type") == "Approval" and row.get("has_supplementary_form")]
    editable = [row for row in rows if row in supplementary or (row in user_tasks and row.get("has_form_fields"))]
    candidates = editable or user_tasks
    if not candidates or not candidates[0].get("workflow_stage"):
        raise ValueError("Workflow has no previous editable user task")
    return str(candidates[0]["workflow_stage"])


_PRIVATE_TYPES = {'File', 'Image', 'Signature'}


def _keep(field: dict[str, Any]) -> bool:
    return not field.get('sensitive') and field.get('type') not in _PRIVATE_TYPES


def carried_draft(rows: list[dict[str, Any]], stage: str, schema: dict[str, Any] | None) -> dict[str, Any]:
    """Draft for a returned user action: the newest earlier answer of the same stage.

    `rows` are completed tasks, newest first. Only fields of the stage's current schema
    are kept; sensitive values and attachments are never copied into a new draft (the
    assignee re-attaches files, and the attachment checks only trust the task's own files).
    """
    if not isinstance(schema, dict):
        return {}
    for row in rows:
        if row.get('workflow_stage') != stage:
            continue
        raw = row.get('response_json') or '{}'
        try:
            response = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return {}
        if not isinstance(response, dict):
            return {}
        result: dict[str, Any] = {}
        for section in schema.get('sections', []):
            for field in section.get('fields', []):
                key = field.get('key')
                if not _keep(field) or key not in response:
                    continue
                value = response[key]
                if field.get('type') == 'Table':
                    columns = {c.get('key') for c in field.get('columns', []) if _keep(c)}
                    value = [{k: v for k, v in item.items() if k in columns}
                             for item in value if isinstance(item, dict)] if isinstance(value, list) else []
                result[key] = value
        return result
    return {}
