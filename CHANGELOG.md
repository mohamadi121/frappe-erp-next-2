# Changelog

## Unreleased

Added:

- Guarded automatic workflow actions and execution audit (`docs/automatic-actions-v2.md`).
- Preserved validated supplementary approval form fields.
- Workflow task outputs and terminal outcomes (`services/user_task_output.py`).
- Native role and personal access assignments (`api/v1/user_access.py`).

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
