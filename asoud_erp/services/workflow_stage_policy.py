import re
from typing import Any

STAGE_TYPES = {"User Task", "Approval", "Condition", "System Action", "Wait", "End"}
ROLE_BASED_TYPES = {"User Task": "assignee_roles", "Approval": "approver_roles"}
FORM_FIELD_TYPES = {"Short Text", "Long Text", "Number", "Currency", "Date", "Choice", "Attachment", "Checkbox"}
ASSIGNMENT_TYPES = {"Role", "Department", "Employee"}


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _normalize_form_fields(values: Any) -> list[dict[str, Any]]:
    if values in (None, []):
        return []
    if not isinstance(values, list) or len(values) > 30:
        raise ValueError("Form fields must be a list with at most 30 items")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for position, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            raise ValueError("Invalid form field")
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        field_type = item.get("type")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", key) or key in keys:
            raise ValueError("Form field keys must be unique safe identifiers")
        if not 2 <= len(label) <= 80:
            raise ValueError("Form field label is required")
        if field_type not in FORM_FIELD_TYPES:
            raise ValueError("Unsupported form field type")
        options = _unique_strings(item.get("options"))
        if field_type == "Choice" and len(options) < 2:
            raise ValueError("Choice fields require at least two options")
        if field_type != "Choice":
            options = []
        keys.add(key)
        result.append({
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required", False)),
            "options": options,
            "position": position,
        })
    return result


def _normalize_assignment(raw: dict[str, Any], prefix: str) -> dict[str, Any]:
    assignment_type = str(raw.get("assignment_type") or "Role")
    if assignment_type not in ASSIGNMENT_TYPES:
        raise ValueError("Invalid assignment type")
    roles = _unique_strings(raw.get(f"{prefix}_roles"))
    departments = _unique_strings(raw.get(f"{prefix}_departments"))
    employees = _unique_strings(raw.get(f"{prefix}_employees"))
    selected = {
        "Role": roles,
        "Department": departments,
        "Employee": employees,
    }[assignment_type]
    if not selected:
        raise ValueError("At least one assignment target is required")
    return {
        "assignment_type": assignment_type,
        f"{prefix}_roles": roles if assignment_type == "Role" else [],
        f"{prefix}_departments": departments if assignment_type == "Department" else [],
        f"{prefix}_employees": employees if assignment_type == "Employee" else [],
    }


def normalize_stage_config(stage_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    if stage_type not in STAGE_TYPES:
        raise ValueError("Unsupported stage type")
    title = str(raw.get("title") or "").strip()
    if len(title) < 2:
        raise ValueError("Stage title is required")

    if stage_type == "User Task":
        activity_type = raw.get("activity_type")
        if activity_type not in {"Data Entry", "Review", "Correction", "Task"}:
            raise ValueError("Invalid user task activity")
        assignment = _normalize_assignment(raw, "assignee")
        return {
            "title": title,
            "activity_type": activity_type,
            **assignment,
            "instructions": str(raw.get("instructions") or "").strip(),
            "form_fields": _normalize_form_fields(raw.get("form_fields")),
        }

    if stage_type == "Approval":
        assignment = _normalize_assignment(raw, "approver")
        mode = raw.get("approval_mode")
        if mode not in {"Any", "All"}:
            raise ValueError("Invalid approval mode")
        return {
            "title": title,
            **assignment,
            "approval_mode": mode,
            "allow_reject": bool(raw.get("allow_reject", True)),
            "allow_return": bool(raw.get("allow_return", True)),
            "comment_required": bool(raw.get("comment_required", False)),
        }

    if stage_type == "Condition":
        source_kind = raw.get("source_kind") or "Document"
        if source_kind not in {"Document", "Form"}:
            raise ValueError("Invalid condition source")
        source_field = str(raw.get("source_field") or "").strip()
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", source_field):
            raise ValueError("Invalid condition field")
        operator = raw.get("operator")
        if operator not in {"Equals", "Not Equals", "Greater Than", "Less Than", "Contains", "Is Set"}:
            raise ValueError("Invalid condition operator")
        compare_value = str(raw.get("compare_value") or "").strip()
        if operator != "Is Set" and not compare_value:
            raise ValueError("Condition comparison value is required")
        return {
            "title": title,
            "source_kind": source_kind,
            "source_field": source_field,
            "operator": operator,
            "compare_value": compare_value,
        }

    if stage_type == "System Action":
        action_type = raw.get("action_type")
        if action_type not in {"Send Notification", "Assign Role"}:
            raise ValueError("Unsafe or unsupported system action")
        target_roles = _unique_strings(raw.get("target_roles"))
        if not target_roles:
            raise ValueError("At least one target role is required")
        return {
            "title": title,
            "action_type": action_type,
            "target_roles": target_roles,
            "message": str(raw.get("message") or "").strip(),
        }

    if stage_type == "Wait":
        wait_type = raw.get("wait_type")
        if wait_type not in {"Duration", "Date", "Event"}:
            raise ValueError("Invalid wait type")
        value = str(raw.get("wait_value") or "").strip()
        if not value:
            raise ValueError("Wait value is required")
        if wait_type == "Duration" and (not value.isdigit() or not 1 <= int(value) <= 3650):
            raise ValueError("Wait duration must be between 1 and 3650")
        unit = raw.get("wait_unit") or "Day"
        if wait_type == "Duration" and unit not in {"Minute", "Hour", "Day"}:
            raise ValueError("Invalid wait unit")
        return {"title": title, "wait_type": wait_type, "wait_value": value, "wait_unit": unit}

    outcome = raw.get("outcome")
    if outcome not in {"Completed", "Rejected", "Cancelled", "Stopped"}:
        raise ValueError("Invalid workflow outcome")
    return {"title": title, "outcome": outcome, "result_label": str(raw.get("result_label") or "").strip()}
