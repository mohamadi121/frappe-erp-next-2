"""The curated pilot catalog of READ-ONLY tools for the in-product assistant.

The model (Gemma 4 26B 4-bit) is weaker than frontier models at tool selection,
so the catalog is deliberately small (at most 12 tools), with flat schemas,
one-line English descriptions and a Persian example value where it helps. Every
entry calls an existing whitelisted read method under ``asoud_erp.api.v1.*``;
the method is executed in the acting user's session, so the user's own
permissions decide what comes back. ``support.create_issue`` is NOT read-only
and is therefore excluded.

``risk`` is ``"read"`` for every entry in this pilot; write tools are a later
phase and must never be added here without the human-confirmation design.
"""

TOOL_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"

_CATALOG = [
    {
        "name": "get_leave_balance",
        "description": "Leave balance of the acting user for a company (days per leave type).",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name, e.g. «شرکت آسود»"},
                "date": {"type": "string", "description": "Optional ISO date, e.g. 2026-11-28"},
            },
            "required": ["company"],
        },
        "method": "asoud_erp.api.v1.leave_request.get_leave_balance",
        "risk": "read",
    },
    {
        "name": "get_my_leave_summary",
        "description": "The acting user's own leave types with taken, pending and remaining days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Optional ISO date, e.g. 2026-11-28"},
            },
            "required": [],
        },
        "method": "asoud_erp.api.v1.hr_self_service.get_my_leave_summary",
        "risk": "read",
    },
    {
        "name": "list_my_leave_applications",
        "description": "The acting user's own leave applications, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit_start": {"type": "integer", "description": "Offset, default 0"},
                "limit_page_length": {"type": "integer", "description": "Page size, default 20"},
            },
            "required": [],
        },
        "method": "asoud_erp.api.v1.hr_self_service.list_my_leave_applications",
        "risk": "read",
    },
    {
        "name": "list_my_workflow_tasks",
        "description": "Workflow tasks assigned to the acting user (Open by default).",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Open, Completed, Rejected or Cancelled"},
                "start": {"type": "integer", "description": "Offset, default 0"},
            },
            "required": [],
        },
        "method": "asoud_erp.api.v1.workflow_runtime.list_my_workflow_tasks",
        "risk": "read",
    },
    {
        "name": "list_my_workflow_instances",
        "description": "Workflow instances started by the acting user, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Running, Completed, Rejected, Cancelled or Failed"},
                "start": {"type": "integer", "description": "Offset, default 0"},
            },
            "required": [],
        },
        "method": "asoud_erp.api.v1.workflow_runtime.list_my_workflow_instances",
        "risk": "read",
    },
    {
        "name": "get_workflow_task",
        "description": "One workflow task by its name (what the acting user may read).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task name, e.g. «TASK-0001»"},
            },
            "required": ["task"],
        },
        "method": "asoud_erp.api.v1.workflow_runtime.get_workflow_task",
        "risk": "read",
    },
    {
        "name": "get_request",
        "description": "One request (workflow request) by its name, with its current status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Request name, e.g. «REQ-0001»"},
            },
            "required": ["name"],
        },
        "method": "asoud_erp.api.v1.workflow_request.get_request",
        "risk": "read",
    },
    {
        "name": "get_calendar",
        "description": "Calendar events for a company between two dates (max 63 days).",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name, e.g. «شرکت آسود»"},
                "start": {"type": "string", "description": "ISO date, e.g. 2026-11-28"},
                "end": {"type": "string", "description": "ISO date, e.g. 2026-12-05"},
            },
            "required": ["company", "start", "end"],
        },
        "method": "asoud_erp.api.v1.calendar.get_calendar",
        "risk": "read",
    },
    {
        "name": "get_my_personnel_file",
        "description": "The acting user's own personnel file (identity, employment, contracts).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "method": "asoud_erp.api.v1.personnel_file.get_my_personnel_file",
        "risk": "read",
    },
    {
        "name": "list_my_issues",
        "description": "Support issues raised by the acting user, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional status filter"},
                "limit_start": {"type": "integer", "description": "Offset, default 0"},
                "limit_page_length": {"type": "integer", "description": "Page size, default 20"},
            },
            "required": [],
        },
        "method": "asoud_erp.api.v1.support.list_my_issues",
        "risk": "read",
    },
]


def catalog() -> list[dict]:
    """The pilot catalog (a fresh copy; callers must not mutate it)."""
    import copy

    return copy.deepcopy(_CATALOG)


def by_name(name: str) -> dict | None:
    for entry in _CATALOG:
        if entry["name"] == name:
            return entry
    return None


def anthropic_tools() -> list[dict]:
    """The catalog in the Anthropic ``tools`` wire shape (declared inline per request)."""
    return [
        {"name": entry["name"], "description": entry["description"],
         "input_schema": entry["input_schema"]}
        for entry in _CATALOG
    ]
