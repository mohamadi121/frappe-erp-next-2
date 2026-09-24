"""Projects, tasks and timesheets on ERPNext's Projects module.

Managers (Projects User/Manager) create projects and tasks and assign tasks
with Frappe's standard assignment (ToDo). Employees see the tasks assigned to
them, move them forward, and log time on their own Timesheets.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company
from asoud_erp.services.transaction_lines import number, paging, parse_json

MANAGER_ROLES = ("System Manager", "Projects Manager", "Projects User")
TASK_STATUSES = {"Open", "Working", "Pending Review", "Completed", "Cancelled"}
PRIORITIES = {"Low", "Medium", "High", "Urgent"}
MAX_LOGS = 50


def _me():
    name = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
    if not name:
        frappe.throw(_("No active Employee is linked to this user"), frappe.PermissionError)
    return frappe.get_cached_doc("Employee", name)


def _assignees(task) -> list[str]:
    return json.loads(task.get("_assign") or "[]")


def serialize_task(doc) -> dict:
    return {
        "name": doc.name, "subject": doc.subject, "project": doc.project or "", "status": doc.status,
        "priority": doc.priority, "progress": flt(doc.progress), "exp_start_date": str(doc.exp_start_date or ""),
        "exp_end_date": str(doc.exp_end_date or ""), "description": doc.description or "",
        "assigned_to": _assignees(doc),
    }


# ---------------------------------------------------------------- managers

@frappe.whitelist()
def list_projects(company: str, status: str | None = None, search: str | None = None,
                  limit_start: int = 0, limit_page_length: int = 20) -> dict:
    erp_documents.require_roles(MANAGER_ROLES)
    require_company(company)
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"company": company}
    if status:
        filters["status"] = status
    or_filters = None
    if search:
        term = f"%{search.strip()}%"
        or_filters = {"name": ["like", term], "project_name": ["like", term]}
    rows = frappe.get_list("Project", filters=filters, or_filters=or_filters,
                           fields=["name", "project_name", "status", "percent_complete",
                                   "expected_start_date", "expected_end_date", "priority"],
                           order_by="modified desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist()
def get_project(name: str) -> dict:
    erp_documents.require_roles(MANAGER_ROLES)
    doc = erp_documents.load("Project", name)
    tasks = frappe.get_all("Task", filters={"project": doc.name},
                           fields=["name", "subject", "status", "priority", "progress", "exp_end_date", "_assign"],
                           order_by="creation asc")
    for task in tasks:
        task["assigned_to"] = json.loads(task.pop("_assign") or "[]")
    return success({
        "name": doc.name, "project_name": doc.project_name, "company": doc.company, "status": doc.status,
        "percent_complete": flt(doc.percent_complete), "expected_start_date": str(doc.expected_start_date or ""),
        "expected_end_date": str(doc.expected_end_date or ""), "notes": doc.notes or "",
        "total_hours": flt(doc.actual_time), "tasks": tasks,
    })


@frappe.whitelist(methods=["POST"])
def create_project(company: str, project_name: str, expected_start_date: str | None = None,
                   expected_end_date: str | None = None, notes: str | None = None) -> dict:
    erp_documents.require_roles(MANAGER_ROLES)
    require_company(company)
    title = (project_name or "").strip()
    if not title:
        frappe.throw(_("Project name is required"))
    doc = frappe.get_doc({
        "doctype": "Project", "company": company, "project_name": title,
        "expected_start_date": getdate(expected_start_date) if expected_start_date else None,
        "expected_end_date": getdate(expected_end_date) if expected_end_date else None,
        "notes": (notes or "").strip() or None,
    }).insert()
    return get_project(doc.name)


@frappe.whitelist(methods=["POST"])
def create_task(project: str, subject: str, priority: str = "Medium", exp_start_date: str | None = None,
                exp_end_date: str | None = None, description: str | None = None, assign_to=None) -> dict:
    """A task on a project, optionally assigned to users (Frappe assign-to, i.e. ToDo)."""
    erp_documents.require_roles(MANAGER_ROLES)
    from frappe.desk.form.assign_to import add as assign

    erp_documents.load("Project", project)
    if priority not in PRIORITIES:
        frappe.throw(_("Invalid priority"))
    users = parse_json(assign_to, "assign_to") or []
    if not isinstance(users, list) or any(not isinstance(user, str) for user in users):
        frappe.throw(_("assign_to must be a list of users"))
    doc = frappe.get_doc({
        "doctype": "Task", "project": project, "subject": (subject or "").strip(), "priority": priority,
        "exp_start_date": getdate(exp_start_date) if exp_start_date else None,
        "exp_end_date": getdate(exp_end_date) if exp_end_date else None,
        "description": (description or "").strip() or None,
    }).insert()
    if users:
        assign({"assign_to": users, "doctype": "Task", "name": doc.name, "description": doc.subject})
        doc.reload()
    return success(serialize_task(doc))


# ---------------------------------------------------------------- employees

@frappe.whitelist()
def list_my_tasks(status: str | None = None, limit_start: int = 0, limit_page_length: int = 20) -> dict:
    """Tasks assigned to the session user."""
    start, length = paging(limit_start, limit_page_length)
    filters: dict = {"_assign": ["like", f'%"{frappe.session.user}"%']}
    if status:
        if status not in TASK_STATUSES:
            frappe.throw(_("Invalid task status"))
        filters["status"] = status
    else:
        filters["status"] = ["not in", ["Cancelled", "Template"]]
    rows = frappe.get_all("Task", filters=filters,
                          fields=["name", "subject", "project", "status", "priority", "progress", "exp_end_date"],
                          order_by="exp_end_date asc, creation asc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist(methods=["POST"])
def update_task_status(name: str, status: str, progress=None) -> dict:
    """Assignees (who have no Task write role in ERPNext) and managers may move a task forward."""
    if status not in TASK_STATUSES:
        frappe.throw(_("Invalid task status"))
    if not frappe.db.exists("Task", name):
        frappe.throw(_("Task {0} does not exist").format(name), frappe.DoesNotExistError)
    doc = frappe.get_doc("Task", name)
    is_manager = frappe.session.user == "Administrator" or set(MANAGER_ROLES) & set(frappe.get_roles())
    if not is_manager and frappe.session.user not in _assignees(doc):
        frappe.throw(_("This task is not assigned to you"), frappe.PermissionError)
    doc.status = status
    if progress not in (None, ""):
        try:
            value = number(progress, "Progress", minimum=0)
        except ValueError as error:
            frappe.throw(_(str(error)))
        if value > 100:
            frappe.throw(_("Progress must be at most 100"))
        doc.progress = value
    # Assignment was checked above; employees hold no Task write permission in ERPNext.
    doc.save(ignore_permissions=not is_manager)
    return success(serialize_task(doc))


def _time_logs(value) -> list[dict]:
    rows = parse_json(value, "time_logs")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_LOGS:
        frappe.throw(_("time_logs must be a list of 1 to {0} rows").format(MAX_LOGS))
    logs = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("activity_type") or not row.get("from_time"):
            frappe.throw(_("Each time log needs activity_type, from_time and hours"))
        try:
            hours = number(row.get("hours"), "Hours", minimum=0, allow_equal=False)
        except ValueError as error:
            frappe.throw(_(str(error)))
        if hours > 24:
            frappe.throw(_("A time log may not exceed 24 hours"))
        task = row.get("task") or None
        if task and frappe.session.user not in _assignees(frappe.get_doc("Task", task)) \
                and not set(MANAGER_ROLES) & set(frappe.get_roles()):
            frappe.throw(_("You can log time only on tasks assigned to you"), frappe.PermissionError)
        logs.append({"activity_type": row["activity_type"], "from_time": get_datetime(row["from_time"]),
                     "hours": hours, "project": row.get("project") or (
                         frappe.db.get_value("Task", task, "project") if task else None),
                     "task": task, "description": str(row.get("description") or "").strip()[:1000]})
    return logs


@frappe.whitelist()
def timesheet_options() -> dict:
    return success({"activity_types": frappe.get_all("Activity Type", filters={"disabled": 0}, pluck="name",
                                                     order_by="name asc")})


@frappe.whitelist(methods=["POST"])
def create_timesheet(time_logs, note: str | None = None) -> dict:
    """A draft Timesheet for the session user's Employee; a Projects User submits it."""
    me = _me()
    doc = frappe.get_doc({"doctype": "Timesheet", "employee": me.name, "company": me.company,
                          "note": (note or "").strip() or None, "time_logs": _time_logs(time_logs)})
    doc.insert()
    return success(_serialize_timesheet(doc))


def _serialize_timesheet(doc) -> dict:
    return {
        "name": doc.name, "employee": doc.employee, "status": doc.status, "docstatus": doc.docstatus,
        "total_hours": flt(doc.total_hours), "start_date": str(doc.start_date or ""),
        "end_date": str(doc.end_date or ""),
        "time_logs": [{"activity_type": row.activity_type, "from_time": str(row.from_time),
                       "to_time": str(row.to_time), "hours": flt(row.hours), "project": row.project or "",
                       "task": row.task or "", "description": row.description or ""} for row in doc.time_logs],
    }


@frappe.whitelist()
def list_my_timesheets(limit_start: int = 0, limit_page_length: int = 20) -> dict:
    start, length = paging(limit_start, limit_page_length)
    rows = frappe.get_all("Timesheet", filters={"employee": _me().name},
                          fields=["name", "start_date", "end_date", "total_hours", "status", "docstatus"],
                          order_by="start_date desc", limit_start=start, limit_page_length=length)
    return success(rows, meta=erp_documents.list_meta(start, length, rows))


@frappe.whitelist(methods=["POST"])
def submit_timesheet(name: str) -> dict:
    erp_documents.require_roles(MANAGER_ROLES + ("HR User", "Accounts User"))
    return success(_serialize_timesheet(erp_documents.submit("Timesheet", name)))

