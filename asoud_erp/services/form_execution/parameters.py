"""Pure E3 overlay of mapped request values and completed workflow responses."""

from datetime import datetime
from typing import Any

CONFIDENTIAL_POINTER = 'محرمانه؛ جزئیات در درخواست {request} است.'


def _mapped(fields: list[dict], values: dict, request_name=None, text_keys=None) -> dict:
    result = {}
    for field in fields:
        key = field.get('execution_key')
        if not key or field['key'] not in values:
            continue
        value = values[field['key']]
        if (text_keys is not None and key in text_keys and field.get('sensitive') is True
                and isinstance(value, str) and value.strip()):
            value = CONFIDENTIAL_POINTER.format(request=request_name or '')
        result[key] = value
        if field.get('type') == 'Time':
            # A new time always replaces its day marker too; a field without the toggle means same day.
            companion = f"{field['key']}__next_day"
            result[f'{key}__next_day'] = (
                values[companion] if field.get('next_day_allowed') is True and companion in values else False)
    return result


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
                       tasks: list[dict[str, Any]], request_name: str | None = None,
                       text_keys: set | None = None) -> dict:
    """Overlay each completed task, sorted by completed_on and name for ties.

    A non-empty value of a `sensitive` field whose parameter is in `text_keys` (free text copied
    into a native document) is replaced by a pointer to the request.
    The caller supplies revision fields and unmasked values. Each task supplies
    its stage fields as ``fields`` and decoded final response as ``values``.
    Repeated tasks from the same stage remain separate decisions. Missing values
    leave earlier decisions intact; explicit null, false and empty values win.
    """
    params = _mapped(request_fields, request_values, request_name, text_keys)
    completed = sorted((task for task in tasks if task.get('status') == 'Completed'),
                       key=_completion_order)
    for task in completed:
        params.update(_mapped(task.get('fields') or [], task.get('values') or {}, request_name, text_keys))
    return params
