# Changelog

## Unreleased

Deployment: run `bench --site <site> migrate` (adds a search index on `ASOUD Workflow Activity.workflow_instance`; new `reminder_at` field on `ASOUD Internal Communication`; new `In Progress` option on the recipient `directive_state`).

Fixed:

- Paged workflow task/instance lists filter directive access in SQL (no per-row `get_doc`), keep `meta.total`, and compute the cursor after filtering.
- `dispatch_reminders` isolates each task; `reminder_at` with an offset or `Z` is converted to the site timezone. Reminders need the scheduler enabled (see `docs/directives-implementation.md`).

Added:

- Request-bound workflow step validation for approved amounts and per-row quantities, enforced during task completion. No migration. See `docs/api/forms.md`.
- `get_request` returns `viewer` (is the caller the requester, and their own open task with the stage's decision flags) for an in-page decision card.
- `get_request` returns `stages` (real workflow steps with status, assignees and times) and instance activity rows carry `actor_name` (`services/request_timeline.py`, `integration_tests/test_request_stages.py`).
- Form builder record sources: Link sources `Attendance`, `Shift Type`, `Training Event`, `Asset` scoped to the signed-in Employee on both `get_link_options` and submission (`meta.reason = 'no_employee'`), row `extra` attributes, `exclude_self`, `fetch_from` (recomputed server side), `not_equal`, unique table columns, and `default_source` `employee_number` / `default_shift`. No migration. See `docs/api/forms.md`.
- Form schema support for Select display styles, section presentation/collapse metadata,
  field help text, Date `after_or_equal` validation, and Employee designation and joining-date defaults.
- Submission enforcement for visible required repeatable tables and their minimum row count.
- Directive `start` action: the assigned recipient moves from Pending to In Progress without completing the execution task. Only the recipient can start, and only once.
- Directive progress reports: `report` accepts `report_type` (`final`, the default, or `progress`). A progress report is stored as a completed Workflow Task, keeps the execution task open, notifies the issuer and never requests approval.
- Directive reminders: the issuer can set `reminder_at` on a draft. At issue time it must be in the future and before the due date. A minute scheduler job (`dispatch_reminders`) notifies the assignee once per open report task.
- Paginated directive `reports` and `history` (50 rows per page, `next_cursor`), with access scoping applied in the database before pagination. `reports` accepts an `author` filter: the issuer may filter by any executor, an executor only by self.
- Workflow task and instance list endpoints accept `start` and `paged=1` and return `{items, next_cursor}`. The default list response is unchanged.
- Integration tests for start, progress reports, report type validation, reminders, and pagination (`integration_tests/test_directives.py`), plus a pure test for the directive status summary (`tests/test_directive_state.py`).

Changed:

- A directive whose executors are all Pending reads as `Issued`; it previously read as `In Progress`.

Changed:

- One Employee may occupy at most one position across the whole organization chart, including v2 `occupants` rows. Chart saves and import previews/applies that would place the same Employee in two positions are refused with a Persian message naming the Employee. Charts that already contain such duplicates must be corrected before they can be saved again.

Fixed:

- Plain Department saves no longer take a company-wide lock. Deleting, disabling, moving a unit with positions, or deleting a unit that positions reference still locks the company and is refused.
- Renaming a unit's title is refused while legacy chart positions (no `department_id`) reference it by title, so those positions are not orphaned. Link them to the unit in the chart first.

Tests and documentation:

- Pure tests for the Department guard and cross-position occupant rule; integration tests for the cross-position refusal and title rename behaviour; `test_organization` added to the integration module loop.
- API reference for organization units and import in `docs/api/organization.md`.

Performance and contract:

- `directives.reports` reads the review tasks of a page in one query instead of one lookup per report. Response shape and statuses are unchanged; when a report has more than one review row, the earliest one is used.
- `directives.history` applies access scope and the page limit inside each UNION branch, and orders each branch by the indexed `created_on`, so the query reads at most one page per branch.
- `list_my_workflow_tasks` and `list_my_workflow_instances` with `paged=1` document that a page can be short or empty while `next_cursor` is set. The cursor is computed from the raw database page, so clients keep paging until `next_cursor` is null (see `docs/workflow-runtime-v1.md`).

## 0.16.0 - 2026-10-18

Deployment: run `bench --site <site> migrate` (new DocTypes: `ASOUD Form`, `ASOUD Form Revision`, `ASOUD Form Entry`, `ASOUD Calendar Scope`, `ASOUD Calendar Holiday`; directive receipts). Pairs with app 0.28.0.

Added:

- Advanced formula functions `IF` (with lazy branch evaluation), `ROUND`, `MAX`, and `MIN` across scalar values and repeatable table columns.
- Comparison operators (`>`, `<`, `=`, `==`, `>=`, `<=`, `!=`) for conditional formula evaluation.
- Arithmetic operator precedence (`*`, `/`, `%` before `+`, `-`), negative numbers, parentheses `()`, and nested expressions in formula calculation.
- Extended shared formula vectors fixture to 55 test cases with parity verification against Flutter engine.
- Multi-step `chain` formula operator in form schema validation and Decimal evaluation matching Flutter engine parity, with left-to-right calculation, precision rounding, divide-by-zero protection, and dependency cycle validation.
- Shared formula evaluation vectors test suite ensuring backend/Flutter engine parity across operations, precision, rounding, and Persian numerals.
- Versioned form schema validation supporting `schema_version` 1 and 2, enforcing version 2 on `save_form`, and rejecting unsupported versions.
- Pure `migrate_schema` and `migrate_record` functions upgrading legacy v1 schemas to v2 with deterministic option IDs and value/rule mapping on read across `get_form`, `list_forms`, and `get_entry` while preserving immutable database revisions.
- Fixture test pair `form_schema_legacy_v1.json` and `form_schema_legacy_v2.json` for cross-engine migration parity.
- Versioned form-builder API coverage and documentation, including stable schema IDs,
  immutable published revisions, entry revision checks, and company-scoped calendar coverage.
- Integration tests for directives lifecycle (`test_directives.py`: draft, issue, transfer,
  report submission, change request, review approval, close, and cross-company tenant isolation).
- Dedicated integration tests for calendar scope and organization holidays (`test_calendar.py`).

Fixed:

- Restore active employee consumption on form-builder and calendar personal endpoints (plain
  employees can list published forms, submit request forms, read own entries, and manage personal
  reminders; designer endpoints and holiday management remain manager-gated, and document forms
  rely on native ERPNext DocType permissions).
- Persist new `ASOUD Form`, `ASOUD Calendar Scope`, and `ASOUD Calendar Holiday` records via `insert`
  to support deterministic identifiers before insert.

## 0.15.3 - 2026-10-11

Deployment: the release contains a patch (`v0_15_3.normalize_persian_digits`): run `bench --site <site> migrate`. No new DocTypes.

Security:

- `party.save_party` calls `require_company` on the loaded profile's own company, so a role scoped to another company can no longer move a foreign party into its own tenant and read its PII (F-P1).
- `account.delete_account`/`update_account` resolve the floating detail's linked record and `require_company` it, so a detail of another company can no longer be deleted, renamed or disabled through a shared detail group (F-P2).
- `floating_detail.disable_floating_detail` requires the loaded detail's linked company before disabling (F-P3).
- `account.list_accounts` filters expanded floating details by the linked record's tenant, matching `floating_detail.list_floating_details` (F-P4).
- `projects.update_task_status` requires the task's project company when the caller is not the assignee, so a manager can no longer move tasks of a foreign company (F-P5).

Fixed:

- Persian (۰-۹) and Arabic-Indic (٠-٩) digits are normalised to ASCII at the write boundaries of `party.save_party`, `setup.save_office` and `personnel.update_personnel` (plus the Employee mirrors), so identifier and number columns (national/economic/registration/postal codes, phone/mobile/fax, account/card/IBAN numbers, fiscal year and code digit counts) never store non-ASCII digits.
- Migration patch `v0_15_3.normalize_persian_digits` converts existing values in those columns of `ASOUD Party Profile`, `ASOUD Company Setup`, `ASOUD Personnel Record` and `Employee`; it only rewrites rows that contain a Persian/Arabic-Indic digit and is safe to re-run.

## 0.15.2 - 2026-10-10

Security:

- `party.save_party` redacts `bank_name`, `iban`, `account_number`, `card_number` and `account_holder` from its response for roles without bank access (and ignores such `bank_*` inputs), matching `party.list_parties` (F5).
- `hr.organization_tree` calls `require_company(company)` before reading the department tree, closing a cross-company read (F7).
- `floating_detail.list_floating_details` returns only details whose linked record belongs to a company the caller may access; rows with no linked record stay visible to `System Manager`/`Accounts Manager` only (F8).

## 0.15.1 - 2026-10-10

Fixed:

- Seed `ASOUD Company Setup` row for demo company with office_saved, accounting_saved, roles_saved all 1 and enabled_roles_json `["System Manager"]` so setup status resolves as complete.
- Return management-only dashboard payload with `manager_access: true` for System Manager and HR Manager users without a linked Employee in `hr.get_dashboard`.
- Accept str, JSON list string and list for `item_code` normalization in `stock_balance` report filters and API.
- Document and pin with regression tests the current behaviour of `request_query` (list) vs `request_permission` (read) for privileged roles in `docs/access-control-v1.md`.

## 0.15.0 - 2026-10-09

Deployment: run `bench migrate` (new DocTypes ASOUD Action Execution, ASOUD Access Assignment). Workflows with System Action stages need `asoud_workflow_service_user` and `asoud_workflow_service_companies` in the site config.

Added:

- HR Manager read access to manager screens (writes and financial reports stay closed).
- Playwright e2e suites for HR access, automatic actions and sync request keys.
- Guarded automatic workflow actions and execution audit (`docs/automatic-actions-v2.md`).
- Preserved validated supplementary approval form fields.
- Workflow task outputs and terminal outcomes (`services/user_task_output.py`).
- Native role and personal access assignments (`api/v1/user_access.py`).

Fixed:

- Allowed `HR Manager` to access read-only manager endpoints required to open the office and settings dashboards (`setup.get_setup_status`, `role_management.catalog`, `role_management.permission_preview`, `workflow.list_workflows`, `workflow.get_workflow_design`, `workflow.workflow_form_options`, `workflow.workflow_condition_fields`) while preserving company isolation and preventing privilege escalation on definitions and writes (`docs/access-control-v1.md`).

## 0.14.0

Added:

- Request engine for the purchase, supply and leave templates (`docs/api/request_templates.md`).
  - `ASOUD Workflow Request` gains `template_key`, `template_version`, `requester_employee`,
    `status_key`, `search_text` and the `native_*` fields; `ASOUD Workflow Definition` gains
    `template_key`, `template_version` and `is_system_template`. Custom Fields:
    `Company.asoud_daily_working_hours`, `Company.asoud_request_cost_center_required`,
    `Leave Type.asoud_leave_category` and `asoud_request` on Material Request and Leave Application.
  - Template registry (`services/request_templates`), idempotent seeding per company on migrate
    and on company creation, and a locked form stage for system templates.
  - Request numbers `PR|SP|LV-<Jalali year>-####`; custom types keep `REQ-#####` without a gap.
  - New form field types `Time`, `System Select` and `Auto`, `visible_when`, `option_labels`,
    item-row notes and files, and the lookup sources behind `request_field_options`.
  - Stored `status_key` mirrored from the workflow instance, and a query-based
    `list_my_requests` with status tabs, `meta.counts`, search, filters and pagination.
  - Richer `get_request` (status, `can_edit`, `can_cancel`, attachments with scope, row files,
    comment count, native document), `list_request_comments`, `add_request_comment`,
    `get_attachment(thumbnail=1)`, and `create_native_document` to retry a failed native document.
  - `create_request` accepts `template_key`; uploads take a `ref` so duplicate file names work;
    `update_request` adds and removes files; `.xls` and `.doc` are allowed.
  - Error codes travel in `_server_messages[].title` (for example `REQUESTER_MISMATCH`).
  - Patches `v0_14`: backfill `status_key`/`search_text`, map Leave Type categories.
- Leave requests (`docs/api/leave_request.md`): `leave_request.get_leave_balance` and
  `leave_request.preview_leave_request` (read-only, business errors come back as data), daily and hourly
  leave with exact half-up hour/day maths, overlap, balance and HRMS dry-run rules, and error code
  `LEAVE_RULE_VIOLATION` for HRMS validations without a contract code.
  After final approval a daily request becomes an approved Leave Application and an hourly request a
  Leave Ledger Entry; purchase and supply requests become Material Requests. A failure is stored as
  `native_status = Failed` and can be retried with `create_native_document`.
- The demo seed creates the three system templates and six requests with template keys; reset keeps the
  shared native Workflow while a definition links it (`docs/demo-seed.md`).

Changed:

- `workflow_request.list_my_requests` no longer returns `values` and `attachments` per row
  (use `get_request`) and returns at most 100 rows per page.
- `workflow_request.create_request` takes `request_id` as before but its other arguments are
  keyword-friendly (`workflow_definition` or `template_key`); invalid JSON arguments now raise
  a validation error instead of a server error.

## 0.13.1

Security:

- `party.list_parties` now restores the accounting role gate before company-scope checks, so an Employee-only user cannot list party profiles for their own company.

Fixed:

- Demo seed fiscal-year handling now reuses a global Fiscal Year without adding a company row, avoiding accidental restriction of a shared year. Demo reset only deletes a seed-shaped Fiscal Year owned solely by the demo company and otherwise removes just the demo company row.

## 0.13.0

Fixed:

- `sync.execute_mutation` now binds an idempotency key to both the target method
  and payload fingerprint. Retrying the same write still returns the stored
  envelope, but reusing that key for different work returns
  `REQUEST_KEY_CONFLICT` instead of a successful response from the first write.
- `financial_reports.run_financial_report(..., report="stock_balance")` accepts a
  single `item_code` string and passes it to ERPNext's Stock Balance report in
  the list form the report expects.
- Workflow request list permission now matches direct-read permission for
  System Manager and HR Manager users within companies they can access, including
  request-related instances, tasks and activities.

Security:

- Replaced `frappe.only_for` with `erp_documents.require_roles` across all `api/v1`
  modules (`account`, `detail_group`, `floating_detail`, `party`, `purchase_request`,
  `role_management`, `setup`, `voucher`, `workflow`, `workflow_runtime`).
  `frappe.only_for` was bypassed in test mode (`in_test=True`), leaving role gates
  unprotected against regressions; `require_roles` enforces role requirements under tests.
- `projects.create_timesheet` now validates foreign and unknown projects on time
  logs without a task. Such logs now require a project belonging to the caller's
  company and read permission, preventing employees from logging time to projects
  of other companies.
- Every `voucher.*` endpoint (`list_vouchers`, `save_voucher`, `submit_for_approval`,
  `approve_voucher`, `reject_voucher`) now checks company access with
  `request_access.require_company`. `list_vouchers` and `save_voucher` require
  access to the specified company, and voucher state transitions verify access to
  the company owning the voucher.
- `party.save_party` and `party.disable_party` now check the company of the profile
  they act on. `save_party` also keeps the profile's company when the argument is
  omitted instead of clearing it, which could move a party out of its tenant.
- `detail_group.list_account_mappings` and `detail_group.save_account_mapping` now
  check `company` with `request_access.require_company`. `ASOUD Account Mapping`
  carries a company, and the read was built with `frappe.get_all`, so it returned
  another company's account-to-detail-group mapping. The detail group catalogue
  itself (`ASOUD Detail Group`) has no company and stays site-wide.
- `floating_detail.create_floating_detail` and `floating_detail.link_floating_detail`
  now check the company of the record a detail is attached to. `ASOUD Floating
  Detail` has no company column, so a Company User Permission never applied to it:
  an Accounts User of Company A could attach a detail to a Company B party, and
  that write altered the other company's party.
- Every `account.*` endpoint now checks `company` with
  `request_access.require_company`. The module gated on roles only and read with
  `frappe.get_all`, so a Company User Permission did not limit the chart of
  accounts at all.
- `purchase_request.purchase_request_options`, `create_purchase_request` and
  `list_my_purchase_requests` now check `company` with
  `request_access.require_company`. The option lists are built with
  `frappe.get_all`, which skips User Permissions, so an Accounts Manager restricted
  to one company received another company's warehouse list.
- `party.save_party` now refuses a profile with the `Employee` role unless the
  caller is `System Manager` or `HR Manager`. An accountant could otherwise
  rewrite Employee master data (gender, birth date, date of joining, designation)
  with permission checks disabled, and set the employee's bank details, bypassing
  the `PERSONAL_FIELDS` allow-list of `personnel.update_personnel`. The Employee
  write now goes through Frappe's own permission check, and only allow-listed
  fields are mirrored onto it.
- `party.list_parties` requires `company` and checks it with
  `request_access.require_company`. Without it the endpoint answered for every
  company and returned the bank name, IBAN and account numbers of parties the
  caller could not see. Bank fields are now returned only to `System Manager` and
  `Accounts Manager`, the roles that own the party master; an `Accounts User` gets
  the profile without them. See `docs/api/party.md`.
- `report.trial_balance` and `report.general_ledger` are now company scoped
  (`request_access.require_company`) instead of only role scoped, so a User
  Permission on `Company` really limits the ledger. `report.general_ledger` also
  works again on ERPNext v15 (it called `frappe.get_descendants_of`, removed in
  v15, and raised `AttributeError` for every request). See `docs/api/report.md`.

- Demo seed command for real test sites: `bench --site <site> execute
  asoud_erp.demo.seed.run` (and `reset=True` to remove exactly the marked
  records). Creates «شرکت نمونه آسود» (IRR, Iran) with fiscal year,
  departments, designations, 12 employees with a reporting chain, 4 users,
  leave/payroll/attendance, customers/suppliers/items with stock,
  submitted sales/purchase invoices, and workflow request types with
  requests in several statuses — all through standard ERPNext/HRMS
  documents and the asoud APIs. Refuses without developer_mode (or off
  test/demo sites) unless forced.   Demo parties carry the company currency
  and IRR price lists so every invoice is created without conversion;
  `asoud_erp.demo.seed.check` reports remaining demo-marked records.
  `selling.create_sales_invoice` and `buying.create_purchase_order` accept
  optional `currency` and price-list overrides (a new document otherwise
  inherits both from the default price list).
  See `docs/demo-seed.md`.

## 0.12.0

- Account operations of the personnel file (`auth`): enable/disable a login with
  `set_account_enabled` (idempotent per request id, and it clears the open
  sessions of a disabled account), `get_account_status` with roles, allowed
  modules and data scope, and `get_login_history` from the native Activity Log
  and sessions without exposing session ids.
- «ارسال مجدد دعوت» is refused once the account has a recorded login, with a
  Persian message pointing at the password reset instead.
- `get_employee_access` also returns `access_level`, `modules` and `data_scope`,
  and `sync_employee_access` keeps the Company and Department User Permissions of
  the login in step with the Employee.
- The direct manager's photo is part of the organization section of the personnel
  file (the private Employee file first, the personnel photo record as fallback).
- Document templates (`document_templates`): map request, user, company and system values onto an
  ERPNext Journal Entry or Material Request; ready-made presets; account and warehouse checks.
- Workflow System Action stages now run: create a document from a template, change the request's
  display status, or send an in-app notification. Failures roll back and follow the Error route
  (or stop the instance as Failed and notify System Managers).
- `workflow.save_stage_routes` sets a stage's exits per decision (approve, reject, return,
  success, error).
- Submitting a generic request completes the requester's own form stage, so it reaches the next
  stage at once; the requester can edit it until it is reviewed (`update_request`) or cancel it
  (`cancel_request`).
- New assignees: the initiator's department and direct manager. Stage settings: description,
  rejection reason required, and for user tasks drafts on/off and all fields required.

Fixes:

- A rejection without its own route no longer continues along the stage's default route.
- A stage assignee who is not the requester (for example the direct manager) can open the generic
  request they act on; before, completing such a task failed with a permission error.

## 0.11.0

- Personnel file API (`personnel_file`): one aggregated file per employee from Employee, ERPNext
  Contract, HRMS promotions, transfers, salary assignments and slips, attendance, leave, private
  files and change history; the employee's own file and home screen; public announcements.
- HR writes: contracts with signed copies, promotions applied by HRMS, announcements.
- Personnel documents keep category, number and expiry; Employee fields for marital status, blood
  group, emergency contact, company email, branch, direct manager, probation and contract dates are
  editable through `personnel.update_personnel`. Bank details stay out of this API.

## 0.10.0

API modules on ERPNext/HRMS, each documented in `docs/api/` and covered by
integration tests on a real site (see `docs/backend-roadmap.md`):

- Dashboard: home figures (today's receipts and sales, bank and cash balances, open
  documents) and system status for the settings screen.
- Selling, sales pipeline and payments: sales invoices and returns, quotations,
  sales orders, delivery notes, payment entries with allocation.
- Stock and buying: items, stock balances, stock entries, purchase orders,
  receipts and supplier invoices.
- HR self-service: leave (balance, apply, approve), check-in, missions, salary
  advances, expense claims, payslips, attendance and holidays.
- Payroll (structure assignments, payroll runs), projects and timesheets, POS
  sessions and invoices, ERPNext financial and stock reports, IT issues and assets.
- Request types: short title, category and visibility settings; Multi Choice, User,
  Department and Item Table form fields validated against ERPNext masters; default
  values and help text on fields.

Security:

- Request creation enforces the request type's initiator roles and user-submission
  setting (both were stored but not checked).
- `sync.execute_mutation` binds a request key to its user; another user's key no
  longer replays that user's response.
