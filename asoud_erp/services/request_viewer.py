"""What the signed-in user can do on a request, derived from their own open task.

Pure: the caller passes the user's Open tasks with their stage rows; nothing is read here.
The flags are the ones `complete_workflow_task` enforces, so the app never offers a decision
the server would refuse.
"""

import json


def _config(stage_config) -> dict:
    if isinstance(stage_config, dict):
        return stage_config
    try:
        parsed = json.loads(stage_config or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def open_task_view(task: dict) -> dict:
    """`task` carries `name`, `stage_title`, `stage_type` and `config_json` of the stage."""
    config = _config(task.get("config_json"))
    stage_type = task.get("stage_type") or ""
    form_fields = [field for field in config.get("form_fields") or [] if isinstance(field, dict)]
    return {
        "name": task["name"],
        "stage_title": task.get("stage_title") or "",
        "stage_type": stage_type,
        "approve_action": "Approve" if stage_type == "Approval" else "Complete",
        "allow_reject": bool(config.get("allow_reject", False)),
        "allow_return": bool(config.get("allow_return", False)),
        "comment_required": bool(config.get("comment_required")),
        "reject_comment_required": True,
        "has_form": bool(form_fields),
    }


def build_viewer(is_requester: bool, own_open_tasks: list[dict]) -> dict:
    """`own_open_tasks` must already be limited to tasks assigned to the viewer, oldest first."""
    task = own_open_tasks[0] if own_open_tasks else None
    if is_requester and task and task.get("stage_type") == "Approval":
        return {"is_requester": True, "self_approval_blocked": True, "open_task": None}
    return {"is_requester": bool(is_requester), "open_task": open_task_view(task) if task else None}
