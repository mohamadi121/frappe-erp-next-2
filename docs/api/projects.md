# Projects, tasks and timesheets — `asoud_erp.api.v1.projects`

ERPNext Projects module. Managers (System Manager, Projects Manager, Projects
User) run projects and tasks; employees work on the tasks assigned to them and
log time.

## Managers

| Method | HTTP | Purpose |
| --- | --- | --- |
| `list_projects(company, status?, search?, …)` | GET | name, title, status, `percent_complete`, dates, priority |
| `get_project(name)` | GET | project with its tasks (`assigned_to` users) and logged hours |
| `create_project(company, project_name, expected_start_date?, expected_end_date?, notes?)` | POST | returns `get_project` |
| `create_task(project, subject, priority=Medium, exp_start_date?, exp_end_date?, description?, assign_to?)` | POST | `assign_to`: list of users; uses Frappe assign-to, so assignees also get a ToDo |
| `submit_timesheet(name)` | POST | also HR User and Accounts User |

## Employees

| Method | HTTP | Purpose |
| --- | --- | --- |
| `list_my_tasks(status?, …)` | GET | tasks assigned to the session user (default: not Cancelled) |
| `update_task_status(name, status, progress?)` | POST | status ∈ Open, Working, Pending Review, Completed, Cancelled; progress 0–100 |
| `timesheet_options()` | GET | enabled activity types |
| `create_timesheet(time_logs, note?)` | POST | a draft for the session user's Employee |
| `list_my_timesheets(…)` | GET | |

`time_logs`: `[{"activity_type", "from_time": "2026-09-24 09:00:00", "hours": 2, "task"?, "project"?, "description"?}]`
(1–50 rows, at most 24 hours each). A log on a task needs the caller to be assigned
to it; the project is taken from the task. ERPNext computes `to_time` and totals.

Task object: `name`, `subject`, `project`, `status`, `priority`, `progress`,
`exp_start_date`, `exp_end_date`, `description`, `assigned_to`.

ERPNext gives employees no write access to Task, so `update_task_status` saves
on behalf of an assignee after checking the assignment.
