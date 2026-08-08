import json

ALLOWED_WORKFLOW_STATUSES = {"Active", "Inactive", "Archived"}


def serialize_workflow(row: dict) -> dict:
    result = dict(row)
    result["missing_requirements"] = json.loads(
        result.pop("missing_requirements_json") or "[]"
    )
    result["is_locked"] = result["readiness_status"] != "Ready"
    return result
