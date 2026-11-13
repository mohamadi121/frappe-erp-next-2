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
    """Prefer the newest editable user task, then the newest user task."""
    user_tasks = [row for row in rows if row.get("stage_type") == "User Task"]
    editable = [row for row in user_tasks if row.get("has_form_fields")]
    candidates = editable or user_tasks
    if not candidates or not candidates[0].get("workflow_stage"):
        raise ValueError("Workflow has no previous editable user task")
    return str(candidates[0]["workflow_stage"])
