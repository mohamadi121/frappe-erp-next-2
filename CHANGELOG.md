# Changelog

## Unreleased

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
