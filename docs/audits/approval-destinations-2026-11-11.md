# Approval destinations verification — 2026-11-11

## Findings and minimal repair

The existing sheets already used real stage IDs and native transitions; these
were retained. They now reload the current definition when opening and before
saving, filter invalid successful End outcomes, and search longer lists without
changing card colors, fonts, sheet height or the main designer.

Three regression tests failed before implementation on the isolated real site:
Reject-to-normal-End incorrectly produced Completed; Approve accepted a
Rejected End; a missing target exposed a raw technical missing-record message.
`runtime-checks/approval-before.log` records these failures.

The existing `save_stage_routes` now authorizes before locking and validates the
missing target and End outcome. Runtime decision separation is preserved:
Approval never falls back to a sole Reject edge. Direct rejection to End sets
only that instance to Rejected, not the shared End's configuration. Correction
history includes modern action-result schemas; explicit returns must refer to
a human stage already completed in the same execution. No alternate API, model,
form builder, routing engine or destination-creation behavior was added.

## Acceptance evidence

| Scenario | Executed coverage |
| --- | --- |
| One valid forward target | Dedicated Flutter widget test |
| Multiple real targets | Widget and real native route save/reload tests |
| Many targets | 24 added nodes, simple search, stable selected ID in widget test |
| Added node appears | Repository design changes while settings stay open; reopened sheet reloads it |
| Rename keeps connection | Widget, native database and HTTP assertions use the same node ID |
| Removed target cannot save | Widget removes selected node before save; API missing-target regression rejects it |
| Approve executes selected node | Real request reaches selected successful End |
| Reject executes correctly | Direct End becomes Rejected; explicit handling Approval remains Running at selected node |
| Return stays on same request | Explicit Return and existing correction/resubmit integration suites; request/instance identity preserved |
| Save/reopen restores choices | Existing widget and real native/HTTP design reload assertions |

Final related Flutter suite: `flutter test test/features/workflows
test/ui/stage_settings_page_test.dart test/ui/workflow_form_page_test.dart
--no-pub --reporter expanded`. Analysis targets workflow sources and the modified
widget tests. Backend pure suite: `python -X utf8 -m pytest -q`; lint:
`python -m ruff check .`.

Final results: **527 related Flutter tests passed**, **1,498 backend pure tests
passed**, Flutter analysis had no issues and Ruff passed.

Real database modules: `test_workflow_return_route` (13),
`test_workflow_return_phase4` (8), `test_request_execution` (7),
`test_request_resubmit` (7): **35 passed**. Real HTTP: the approval routing test
in `workflow-start-settings.spec.ts`: **1 passed**, including administrator
without Employee, denied employee and foreign-company account checks.

The existing return-route module is already registered in
`.github/integration-modules.txt`; the existing HTTP spec is already part of the
API suite. Logs are disposable files under `runtime-checks/approval-*` and
Flutter `build/approval-*`, not committed test-site configuration.
Legacy Persian decision labels are also covered by a real execution test; the
new rejection-only fallback guard does not break their existing connections.

## Changed files in this task

Backend: `asoud_erp/api/v1/workflow.py`, `asoud_erp/api/v1/workflow_runtime.py`,
`asoud_erp/integration_tests/test_workflow_return_route.py`,
`e2e/tests/workflow-start-settings.spec.ts`, `docs/workflow-runtime-v1.md`,
`docs/api/workflow-approval-routes.md`, `docs/api/README.md`, this report,
and `CHANGELOG.md`.

Flutter: `lib/features/workflows/presentation/pages/stage_approval.dart`,
`lib/features/workflows/presentation/pages/stage_settings_page.dart`,
`test/ui/stage_settings_page_test.dart`, `CHANGELOG.md`.

Other dirty HR, condition, start and approval form work existed beforehand and
was preserved. No Canvas, shape or connection-rendering implementation was
modified for this task. No emulator/device sign-in or production-server test
was performed. All database writes used the isolated test site. No production
history was rewritten and no commit/push/deployment was performed. Graphify CLI
was unavailable; graph regeneration is not claimed.
