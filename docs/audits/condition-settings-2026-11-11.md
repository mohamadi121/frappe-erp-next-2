# Condition & Routing audit — 2026-11-11

## Scope and preservation

This change repairs the existing Condition station and its metadata adapter, value
controls, validation and sample API integration. It does not redesign Canvas,
station geometry, connection controls, output cards or the form builder. No
production records, existing definitions or history were migrated or deleted.
Unrelated HR, approval and shared-form changes already in the worktrees are not
part of this audit's implementation claims. No commit, push or deployment was
performed for this task.

## Existing data path inspected

| Concern | Existing implementation / integration point |
| --- | --- |
| Field definitions and saved types/options | `services/form_schema.py`: `validate_schema`, `fields`; existing Form Revision schema JSON |
| Form/request binding | `services/workflow_submission_source.py`; `api/v1/workflow_request.py`: `_fields_by_name` for legacy first-task request fields |
| Available Original, Stage and System sources | `services/workflow_condition_binding.py`: `catalog`, `_fields`, `original_request_fields` |
| Prior actions guaranteed on the path | `services/workflow_condition.py`: `guaranteed_predecessors`; existing completed-task history resolution in binding `resolver` |
| Metadata and native reference choices | `api/v1/workflow.py`: `workflow_condition_fields`; binding `reference_choices`, `_reference_labels` |
| Flutter metadata model | `workflow_definition.dart`: `WorkflowFieldOption`; `frappe_workflow_repository.dart` metadata decoding |
| Typed comparison inputs and inline errors | `workflow_condition_settings.dart`: `_ConditionSettingsState`, `rowProblem`, `collectErrors`, `focusError` |
| Sample HTTP call | `data/workflow_condition_repository.dart`: `test`; existing `test_workflow_condition` API |
| Normalize/compare and AND/OR | `services/workflow_condition.py`: `normalize_group`, `condition_value`, `evaluate_group` |
| Real execution and true/false route | `api/v1/workflow_runtime.py`: existing Condition branch, binding `resolver`, `select_boolean_transition` |
| Save/reload | Existing `save_stage_settings`, stage `config_json`, metadata catalog; Flutter settings page |

## Findings and fixes

1. The inspected Flutter page validated settings but did not invoke the already
   available sample-test API. It now calls that endpoint directly, not through an
   offline write queue, and displays true, false and evaluation error separately.
2. The server exposed reference/currency metadata that Flutter discarded. The
   model now retains real data type, reference DocType, choice IDs/labels and
   currency. Native permitted reference choices are read through the existing
   catalog endpoint with optional binding/query parameters; no client-selected
   DocType or parallel endpoint was added.
3. Original fields now include the existing legacy request-form definition when
   there is no pinned revision. Pinned source and action-result revisions remain
   authoritative. No leave/purchase-specific choices or label-based type guesses
   were introduced.
4. Boolean, MultiSelect, DateTime and Time reuse the existing normalizer/evaluator.
   Money and numeric bounds use exact decimal comparison. MultiSelect compares
   membership of one real option ID using the existing Contains operator family.
   Null, zero, false and an empty selection remain distinct.
5. Invalid bounds, missing fields/options and incompatible types are shown inside
   their own condition card. Validation collects all row errors and scrolls to
   the first invalid row. Changing a source/field clears incompatible values;
   sample/API errors do not erase user input.
6. System requester-unit resolution was not scoped by workflow company and active
   employment. It now resolves the active employee in that company; missing
   authoritative data is an error, not a guessed department.
7. Long actual action reports incorrectly shared the 2,000-character comparison
   constant limit. Actual text has a separate bounded limit (100,000), without
   truncation; comparison constants retain their existing bound.
8. Saved reference labels are fetched in batches with native read permissions
   and company filters. Runtime checks of already-approved reference IDs do not
   grant document read access to the process initiator. Design/save/test perform
   native permission checks; existing execution permissions remain in force.

## Reported production sample error: what is and is not proven

The reported date scenario was reproduced successfully against the actual
Frappe/ERPNext application on an isolated site, through both native calls and
HTTP. Bounds `2026-11-18..2026-11-21` (1405/08/27..30), sample `2026-11-10`
(1405/08/19) returns false; `2026-11-19` (1405/08/28) returns true. Both bounds
are inclusive. Invalid dates return an error/null, not false.

Thus the historical generic production error is **not reproduced and its exact
cause is not established** without the deployed build, original HTTP response
and server logs. The local missing client integration/metadata loss are proven
defects, not proof of that production incident's root cause. `WF-1405-044` on the
production server was not modified. The repaired client uses stable field/stage
bindings and ISO values, with the existing Jalali UI picker.

The sample endpoint uses the same evaluator as runtime and retains its rollback
savepoint. Tests check that sample calls leave request, form entry, workflow
instance, task, activity and notification counts unchanged. It does not launch a
real workflow or send business notifications.

## Final executed verification

Environment: Windows Flutter SDK; isolated WSL site `routing-test.localhost`,
Frappe 15.116.1, ERPNext 15.118.3 and HRMS 15.64.8. The original site and
production server were not used. Native DB and HTTP suites ran serially.

| Suite | Result |
| --- | --- |
| Backend pure regression, `python -X utf8 -m pytest -q` | 1,498 passed |
| Backend `python -m ruff check .` | Passed |
| Flutter related workflow suites plus stage/settings form tests | 524 passed |
| Focused Condition widget suite (included above) | 16 passed |
| Flutter analysis, workflows source and tests | No issues |
| Native Condition v2 integration | 4 passed |
| Native Condition dry-run integration | 13 passed |
| Native shared source regression | 10 passed |
| Real HTTP Condition API tests | 2 passed |

Covered cases include text equality/inequality/contains/emptiness, positive,
negative, zero and fractional numbers, exact monetary bounds, invalid integer
fractions, date boundaries and invalid ranges, DateTime/Time, real Select IDs,
invalid choices, MultiSelect membership, true/false, native Employee/Department
IDs, System User/date/unit, mixed AND/OR and reversed row order. Native tests
save/reload valid typed configurations and assert existing output edges remain
unchanged. Actual prior-action execution is checked for both simple report and
pinned structured result form; the existing latest-completed execution resolver
is reused. Unauthorized and foreign-company access is rejected.

Flutter checks cover widths 320/390/430, typed values, inline range errors,
sample results/failures and stable saved IDs. The existing reference capture was
rendered and inspected; no emulator/physical-device sign-in was performed. This
is a workflow-scoped Flutter regression run, not the entire application's suite.

Local evidence logs are `runtime-checks/condition-native-final.log`,
`runtime-checks/condition-http-final.log`, `runtime-checks/condition-pytest-all.log` and Flutter
`build/condition-{tests,regression,analysis}-final.log`. These disposable logs and
test-site configuration/credentials are not repository artifacts.

## Current-task changed files

Backend: `services/workflow_condition.py`, `services/workflow_condition_binding.py`,
`api/v1/workflow.py`, `tests/test_workflow_condition_v2.py`,
`tests/test_workflow_condition_catalog.py`,
`integration_tests/test_workflow_condition_dryrun.py`,
`integration_tests/test_workflow_condition_v2.py`,
`e2e/tests/workflow-condition.spec.ts`, `docs/api/workflow-condition.md`,
this report and `CHANGELOG.md`.

Flutter: `domain/entities/workflow_definition.dart`,
`data/repositories/frappe_workflow_repository.dart`,
`data/workflow_condition_repository.dart`,
`presentation/pages/workflow_stage_settings_page.dart`,
`presentation/pages/workflow_condition_settings.dart`,
`test/features/workflows/condition_settings_test.dart` and `CHANGELOG.md`
(paths relative to `lib/features/workflows` except tests/changelog).

## Compatibility and remaining limits

- No schema migration or new table/model/engine. Existing operator IDs, v2 JSON,
  legacy evaluation and output connections are retained. Deploy Flutter and
  backend together for added metadata/types.
- Native Link fields use real IDs and permission-aware choices, including a
  native position/designation DocType if the source actually defines it. The
  chart's internal JSON position IDs have no separate form-field/native Link
  contract; a parallel position model or guessed picker was deliberately not
  created. Supporting that source requires an explicit existing-data contract.
- Composite/virtual legacy System Select lookups without a real native DocType
  are excluded rather than represented as fake scalar native references.
- DateTime comparison accepts site-local ISO values; timezone-offset input is
  rejected rather than silently compared incorrectly. Cross-timezone conversion
  is not claimed.
- Historical production incident diagnosis still needs the original deployed
  response/logs. Graphify CLI was unavailable, so no graph regeneration is claimed.
