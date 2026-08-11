from typing import Any


def assignment_values(config: dict[str, Any], stage_type: str) -> tuple[str, list[str]]:
    prefix = "approver" if stage_type == "Approval" else "assignee"
    assignment_type = str(config.get("assignment_type") or "Role")
    if assignment_type == "Initiator":
        return assignment_type, []
    suffix = {"Role": "roles", "Department": "departments", "Employee": "employees"}.get(
        assignment_type
    )
    if not suffix:
        raise ValueError("Invalid assignment type")
    values = config.get(f"{prefix}_{suffix}")
    if not isinstance(values, list):
        return assignment_type, []
    return assignment_type, list(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )
