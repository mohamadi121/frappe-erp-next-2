# Support and assets — `asoud_erp.api.v1.support`

IT and service requests (درخواست خدمات IT) on ERPNext `Issue`; equipment on
ERPNext `Asset`.

| Method | HTTP | Who | Purpose |
| --- | --- | --- | --- |
| `issue_options()` | GET | signed-in users | issue types and priorities |
| `create_issue(subject, description?, issue_type?, priority?, company?)` | POST | signed-in users | subject 3–140 characters; `raised_by` is the session user |
| `list_my_issues(status?, …)` | GET | signed-in users | issues raised by the session user |
| `get_issue(name)` | GET | raiser or Support Team | issue with its comments |
| `add_issue_comment(name, comment)` | POST | raiser or Support Team | |
| `list_my_assets()` | GET | employees | submitted assets whose custodian is the user's Employee |
| `list_assets(company, search?, …)` | GET | System Manager, Accounts Manager/User, Quality Manager | company assets with custodian, location and value |

Employees have no Issue role in ERPNext, so `create_issue` inserts on their
behalf and all reads are limited to the raiser; the Support team handles
assignment, SLAs and replies in ERPNext's Support module.

Issue object: `name`, `subject`, `description`, `status` (`Open`, `Replied`,
`On Hold`, `Resolved`, `Closed`), `priority`, `issue_type`, `raised_by`,
`company`, `opening_date`, `resolution_details`, `comments`
(`[{"by", "on", "text"}]`).
