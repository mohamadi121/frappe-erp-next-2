# Architecture

## Backend (`asoud_erp`)

- `api/v1/*.py` whitelisted methods → `responses.success(data, meta)` envelope
  (`{"ok": true, "data": ..., "meta": {"api_version": "v1"}}` inside Frappe's `message`).
  Errors are `frappe.throw` (417 ValidationError, 403 PermissionError).
- `services/*.py` pure logic (no frappe import where possible) tested with plain pytest
  in `asoud_erp/tests/`. Examples: `workflow_stage_policy.normalize_stage_config`,
  `document_templates` (catalog, `normalize_template`, `resolve_values`, `build_document`,
  `PRESETS`), `personnel_file` helpers, `transaction_lines`, `financial_reports`.
- `services/erp_documents.py`: `require_roles`, `load`, `submit`, `cancel`, `insert`,
  `date_range`, `list_meta`. `services/request_access.py`: company access,
  `request_permission` (owner, System/HR Manager, or a stage assignee of the instance).
- Doctypes live in `asoud_erp/asoud_erp/doctype/` (ASOUD Workflow Definition/Stage/
  Transition/Instance/Task/Activity/Request, ASOUD Document Template, ASOUD Personnel
  Record, ...). After adding fields: `bench --site <site> migrate`.

### Workflow engine
- Definition → stages (`Start`, `User Task`, `Approval`, `Condition`, `System Action`,
  `Wait`, `End`) + transitions (`condition_json.action` = Approve/Reject/Return/Complete/
  Success/Error, Persian `transition_label`).
- Request form = the User Task right after Start (`workflow_request._form_stage`).
  `create_request` starts the instance and completes the requester's own form task.
- Assignments: Role, Department, Employee, Initiator, Initiator Department, Direct Manager
  (Employee `reports_to`).
- `_next_stage`: label/action match; only forward decisions (Complete/Approve) fall back
  to a single unlabeled route — a Reject with no route ends the instance as Rejected.
- System Action (`_run_system_action`): Create Document (template → ERPNext Journal Entry
  or Material Request, draft or submitted), Change Status (`display_status` on the
  request), Send Notification. Runs in a savepoint; failure → rollback, `System Action
  Failed` activity, Error route or instance `Failed` + notify System Managers.
  External API calls are deliberately not supported.
- Two System Action schemas: Schema 1 (legacy: Create Document / Change Status / Send Notification, run inline) and Schema 2 (`schema_version: 2`, `automatic_actions.options/save`, scheduled by `automatic_action_runtime`, audited in `ASOUD Action Execution`, exits `Success`/`Error`). Schema 2 and activation of any System Action stage run under the restricted service identity (`automatic_action_metadata.service_user`: site config `asoud_workflow_service_user` + `asoud_workflow_service_companies`, never System Manager). Docs: `docs/automatic-actions-v2.md`, `docs/workflow-runtime-v1.md`, `docs/api/document_templates.md`.

### Access, setup and roles
- `api/v1/user_access.py` + `ASOUD Access Assignment` (native role and personal access assignments), `role_management.py` (`catalog`; `ASOUD Role Category/Definition`), `setup.py` (`ASOUD Company Setup`: one row per company, `get_setup_status` needs System/Accounts/HR Manager). Policy table: `docs/access-control-v1.md` (HR Manager: reads open, writes and financial reports closed on purpose).
- Demo data: `asoud_erp.demo.seed` (see `docs/demo-seed.md`): four demo users sharing one password; the seed must also create the `ASOUD Company Setup` row.

## App (Flutter)

- State: bloc/cubit; repositories per feature; `FrappeApiClient.callAsoudMethod` unwraps
  the envelope. Methods whose last segment starts with `current_`, `get_`, `list_`,
  `preview_` or ends with `_options`/`_fields` are reads; everything else is a **queued
  mutation** (OfflineMutationStore) when the network fails.
- `AppConfig.offlineDemoMode` defaults to **true**: without a restored session the splash
  opens `DashboardLandingPage(offlinePreview: true)`. In this preview (`!client.isAuthenticated`):
  - workflows: `PreviewFallbackWorkflowRepository` keeps designs in SharedPreferences
    `asoud_workflow_designs_v2`; `saveStageRoutesLocally` for exit routes;
  - document templates: `WorkflowAutomationRepository.isLocal` → SharedPreferences
    `asoud_document_templates_local_v1`, presets/options mirrored in `offline_preview_data.dart`;
  - requests: `GenericRequestRepository.isLocal` → types from local designs + sample
    «درخواست خرید (نمونه آفلاین)», sample masters, outbox rows with status `localOnly`
    (never synced), local number `LOCAL-…`, details and print/PDF work.
  - personnel file falls back to `PersonnelRepository.detail` (cache/local/demo) when the
    file API is unreachable or 404.
- Employee-only users (`employee/domain/employee_mode.dart isEmployeeOnly`) land in
  `EmployeeShell`, not the manager dashboard — manager quick actions are not visible there.
  `DashboardLandingPage` resolves the user's roles BEFORE it asks for the office status: employee-only -> `EmployeeShell`; a forbidden office status -> a Persian «no office access» page; only managers get the office dashboard and the first-run setup card (`first_office_card.dart`).
- Session: `SecureSessionVault` keeps the server-scoped session, `SecureServerAddressStore` the last server address (restored in `restoreSession`); passwords are never stored. Offices: `ServerFirstOfficeRepository` (cache) over `FrappeOfficeRepository`; setup completeness comes from `get_setup_status`.
- Localisation helpers: `core/utils/jalali_date.dart` (dates, Persian digits) and `core/utils/persian_server_values.dart` (ERPNext roles, genders, stage types, failure kinds -> Persian). Use them instead of per-screen `if`s.
- Print/PDF: packages `pdf` + `printing`; fonts Vazirmatn from `assets/fonts/`; PDF text
  must replace ZWNJ (U+200C) — the PDF font has no glyph (see `_p` in `request_print.dart`).
