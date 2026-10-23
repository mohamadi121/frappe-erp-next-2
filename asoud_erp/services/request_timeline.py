"""Pure helpers that turn workflow stages and tasks into the step list shown on a request."""

STAGE_TYPES = ("User Task", "Approval")


def _text(value) -> str:
    return str(value) if value else ""


def _stage_status(tasks) -> str:
    if not tasks:
        return "pending"
    if any(task.get("status") == "Open" for task in tasks):
        return "active"
    closed = [task for task in tasks if task.get("completed_on") or task.get("status") in ("Completed", "Rejected")]
    if not closed:
        return "pending"
    last = max(closed, key=lambda task: str(task.get("completed_on") or ""))
    if last.get("status") == "Rejected" or last.get("action") == "Reject":
        return "rejected"
    if last.get("action") == "Return":
        return "returned"
    return "done"


def build_stages(stages, tasks, names=None) -> list:
    """One row per human stage in sequence order. A stage without tasks is `pending`; nothing is invented."""
    names = names or {}
    by_stage = {}
    for task in tasks:
        by_stage.setdefault(task.get("workflow_stage"), []).append(task)
    rows = []
    for stage in sorted(stages, key=lambda item: (item.get("sequence_no") or 0, str(item.get("name")))):
        if stage.get("stage_type") not in STAGE_TYPES:
            continue
        stage_tasks = sorted(by_stage.get(stage["name"], []), key=lambda task: str(task.get("assigned_on") or ""))
        status = _stage_status(stage_tasks)
        assignees = list(dict.fromkeys(
            names.get(task["assigned_to"]) or task["assigned_to"] for task in stage_tasks if task.get("assigned_to")))
        closed = [task for task in stage_tasks if task.get("completed_on")]
        last = max(closed, key=lambda task: str(task.get("completed_on"))) if closed else None
        rows.append({
            "name": stage["name"], "title": stage.get("stage_title") or "", "status": status,
            "assignee_names": assignees,
            "assigned_on": _text(stage_tasks[0].get("assigned_on")) if stage_tasks else "",
            "completed_on": _text(last.get("completed_on")) if last and status != "active" else "",
            "result": _text(last.get("action")) if last and status != "active" else "",
            "comment": _text(last.get("comment")) if last and status != "active" else "",
        })
    return rows
