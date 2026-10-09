# ASOUD personnel access contract (v1)

ERPNext v15 remains the authority for authentication and authorization. UI
labels and the `employee_roles` JSON field are metadata and must never be used
as permission checks.

## Personnel role mapping

| ASOUD key | ERPNext role |
| --- | --- |
| `office_manager` | `Accounts Manager` |
| `accountant` | `Accounts User` |
| `salesperson` | `Sales User` |
| `marketer` | `Sales User` |
| `cashier` | `Accounts User` |
| `petty_cash_custodian` | `Accounts User` |

Operational labels that are absent from this table do not grant a Frappe role.
The server silently ignores unknown labels when normalizing legacy profile data
and rejects a provisioning request if no supported access role remains.

## Current user

`POST /api/method/asoud_erp.api.v1.auth.current_user`

The endpoint requires an authenticated Frappe session and returns the standard
ASOUD v1 envelope. Its data contains `user_id`, `full_name`, authoritative
Frappe `roles`, and an optional active `employee` object with `name`,
`employee_name`, and `company`.

## Employee access provisioning

`POST /api/method/asoud_erp.api.v1.auth.sync_employee_access`

Only a `System Manager` may call this endpoint. Required inputs are
`party_profile`, a unique login `email`, and `personnel_roles`. The operation:

1. verifies that the ASOUD profile is linked to an ERPNext Employee;
2. creates or reuses an enabled System User;
3. applies only the allow-listed ERPNext roles and removes stale ASOUD-managed
   roles;
4. links `Employee.user_id` to the User;
5. enables ERPNext's Employee and Company User Permissions; and
6. stores canonical ASOUD role keys on the party profile.

Flutter must use this context to shape navigation, but every API remains
responsible for enforcing permissions on the server.

## Role gates and company scope

Two gates, always both, on every company-scoped method:

1. `erp_documents.require_roles(...)` for the Frappe roles a method accepts. It is
   the same check as `frappe.only_for`, except that it is **not** skipped when
   `frappe.flags.in_test` is set, so an integration test can prove that a role is
   refused. `frappe.only_for` must not be used in `asoud_erp/api/v1`.
2. `request_access.require_company(company)` with the `company` the method acts
   on, called before any query. A manager needs read access to that Company;
   everyone else needs an active Employee in it. This is what makes a User
   Permission on `Company` a real tenant boundary, because `frappe.get_all()` and
   `frappe.db.sql()` set `ignore_permissions=True` and therefore never apply
   User Permissions on their own.

A method whose `company` argument is optional must not fall back to "every
company": an absent company is either refused or resolved from the record the
method already resolved, never from a site-wide list. Records that are genuinely
site-wide (`ASOUD Settings`, `ASOUD Detail Group`, the role catalog) carry no
company field and are documented as such in their `docs/api/*.md` page.

Bank details (`bank_name`, `iban`, `account_number`, `card_number`,
`account_holder`) live on the ERPNext Employee form. No ASOUD API returns them to
a role that is not a personnel manager, and `personnel.update_personnel` refuses
them outright.

## Employee is HR-only master data

`ASOUD Party Profile` with the `Employee` role is the party view of an ERPNext
`Employee`. Two rules follow:

- Only `System Manager` and `HR Manager` may save such a profile through
  `party.save_party`, which writes the Employee and mirrors the `PERSONAL_FIELDS`
  subset onto it. Everyone else keeps `PermissionError`, even for a party in their
  own company.
- `party.list_parties` returns `bank_name`, `iban`, `account_number`,
  `card_number` and `account_holder` only to `System Manager` and
  `Accounts Manager`; other roles get the profile without those keys.

The sanctioned personnel path stays `personnel.update_personnel`: an allow-list,
a revision check, an idempotency receipt and an audit record.

## Manager screens and role gates policy

The app displays manager views (office dashboard, settings hub, request types and workflow designer) to users holding management roles including `HR Manager`. To allow navigation without unauthorized access or privilege escalation:

- **Read-only manager views**: Endpoints required to render manager navigation and setup status (`setup.get_setup_status`, `role_management.catalog`, `role_management.permission_preview`, `workflow.list_workflows`, `workflow.get_workflow_design`, `workflow.workflow_form_options`, `workflow.workflow_condition_fields`) permit `HR Manager`. All company-scoped endpoints enforce `require_company(company)`.
- **Configuration and definition writes**: Endpoints modifying roles, permissions, workflow definitions, stages, accounting parameters or office identity remain restricted to `System Manager` / `Accounts Manager`. `HR Manager` cannot edit role definitions or grant roles (preventing privilege escalation).
- **Financial reports and ledgers**: Endpoints returning GL entries, trial balances, or bank ledger details remain restricted to accounting roles.

| Endpoint | Kind | Scope | Roles (Before) | Roles (After) | Policy & Rationale |
| --- | --- | --- | --- | --- | --- |
| `setup.get_setup_status` | READ | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User`, `HR Manager` | Manager home office card and setup status. Company scoped. |
| `role_management.catalog` | READ | Site-wide | `System Manager` | `System Manager`, `HR Manager` | Role catalog tree view. Metadata only. |
| `role_management.permission_preview` | READ | Site-wide | `System Manager` | `System Manager`, `HR Manager` | DocPerm preview for role inspect view. |
| `workflow.list_workflows` | READ | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User`, `HR Manager` | Workflows and request-types listing. Company scoped. |
| `workflow.get_workflow_design` | READ | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User`, `HR Manager` | Workflow design and stage graph view. Company scoped. |
| `workflow.workflow_form_options` | READ | Site-wide | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager`, `HR Manager` | Module, doctype, role and department options. |
| `workflow.workflow_condition_fields` | READ | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager`, `HR Manager` | Target doctype condition field definitions. Company scoped. |
| `dashboard.get_home_summary` | READ | Company | Caller with Company read access | Caller with Company read access | Unchanged. Ledgers/banks return `null` when caller lacks accounting permissions. |
| `dashboard.get_system_summary` | READ | Site-wide | `System Manager` | `System Manager` | Unchanged. Site health and storage telemetry. |
| `setup.get_company_settings` | READ | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User` | Unchanged. Accounting base setup parameters. |
| `setup.list_fiscal_years` | READ | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User` | Unchanged. Fiscal years list. |
| `setup.get_account_code_settings` | READ | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User` | Unchanged. Account code settings. |
| `role_management.save_role` | WRITE | Site-wide | `System Manager` | `System Manager` | Unchanged. Privilege escalation prevention. |
| `role_management.create_category` | WRITE | Site-wide | `System Manager` | `System Manager` | Unchanged. Role category creation. |
| `role_management.apply_templates` | WRITE | Site-wide | `System Manager` | `System Manager` | Unchanged. Role template application. |
| `workflow.create_workflow_draft` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Workflow creation. |
| `workflow.save_start_settings` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Workflow start node settings. |
| `workflow.add_workflow_stage` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Workflow stage addition. |
| `workflow.update_stage_positions` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Canvas position coordinates. |
| `workflow.connect_workflow_stages` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Transition routing. |
| `workflow.insert_workflow_stage` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Route split and stage insertion. |
| `workflow.add_condition_branch` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Condition branching. |
| `workflow.save_stage_settings` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Stage configuration. |
| `workflow.save_stage_routes` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Decision exit routes. |
| `workflow.update_request_type_info` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Request type metadata. |
| `workflow.set_workflow_status` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Workflow state activation/archival. |
| `setup.save_office` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Office setup changes. |
| `setup.update_company_settings` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Accounting parameters. |
| `setup.create_fiscal_year` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Fiscal year mutation. |
| `setup.update_enabled_roles` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Enabled role configuration. |
| `setup.update_settings` | WRITE | Site-wide | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Global system digits/currency. |
| `setup.update_account_code_settings` | WRITE | Company | `System Manager`, `Accounts Manager` | `System Manager`, `Accounts Manager` | Unchanged. Account code digits. |
| `setup.set_default_office` | WRITE | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User` | Unchanged. Active office selection. |
| `document_templates.save_document_template` | WRITE | Company | `System Manager`, `Accounts Manager`, `Purchase Manager` | `System Manager`, `Accounts Manager`, `Purchase Manager` | Unchanged. Template document mapping. |
| `voucher.save_voucher` | WRITE | Company | `System Manager`, `Accounts Manager`, `Accounts User` | `System Manager`, `Accounts Manager`, `Accounts User` | Unchanged. Accounting voucher write. |
| `report.trial_balance` | READ | Company | `Accounts Manager`, `Accounts User` | `Accounts Manager`, `Accounts User` | Unchanged. Trial balance financial report. |
| `report.general_ledger` | READ | Company | `Accounts Manager`, `Accounts User` | `Accounts Manager`, `Accounts User` | Unchanged. General ledger report. |

