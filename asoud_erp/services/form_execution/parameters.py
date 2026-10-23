"""Pure E3 overlay of mapped request values and completed workflow responses."""

from datetime import datetime
from typing import Any


def _mapped(fields: list[dict], values: dict) -> dict:
    return {field['execution_key']: values[field['key']] for field in fields
            if field.get('execution_key') and field['key'] in values}


def _completion_order(task: dict) -> tuple[datetime, str]:
    value = task.get('completed_on')
    if not value:
        raise ValueError('زمان تکمیل مرحله ثبت نشده است.')
    try:
        completed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError('زمان تکمیل مرحله معتبر نیست.') from error
    return completed, task.get('name') or ''


def collect_parameters(request_fields: list[dict], request_values: dict,
                       tasks: list[dict[str, Any]]) -> dict:
    """Overlay each completed task, sorted by completed_on and name for ties.

    The caller supplies revision fields and unmasked values. Each task supplies
    its stage fields as ``fields`` and decoded final response as ``values``.
    Repeated tasks from the same stage remain separate decisions. Missing values
    leave earlier decisions intact; explicit null, false and empty values win.
    """
    params = _mapped(request_fields, request_values)
    completed = sorted((task for task in tasks if task.get('status') == 'Completed'),
                       key=_completion_order)
    for task in completed:
        params.update(_mapped(task.get('fields') or [], task.get('values') or {}))
    return params
