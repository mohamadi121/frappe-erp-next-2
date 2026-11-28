# Method classification registry

`asoud_erp/api/v1/registry.py` is the single place that decides, for every
whitelisted `asoud_erp.api.v1.*` method, whether it is a **read** or a **write**,
and whether the offline outbox (`sync.execute_mutation`) may queue it. It is pure
(no `frappe` import) so it runs in the lightweight CI and can be read by the
Flutter app's generated registry.

## The two questions

The registry answers two questions separately, because they currently disagree for
a few methods and must not be conflated:

| Function | Answers | Consumed by |
| --- | --- | --- |
| `classify(method) -> "read" \| "write"` | the *semantic* kind | the AST test, the future Flutter read-only set |
| `is_queued_mutation(method) -> bool` | whether `sync.execute_mutation` accepts the method into the offline outbox | `sync._is_mutation` |
| `is_impactful(method) -> bool` | whether the write changes submitted / financial / HR state | the future dry-run / confirmation gate (defined and tested here, not yet enforced) |

`classify` resolves in this order: an explicit `EXACT` entry, then a write-verb
prefix, then the read rules. A method matching none raises `UnregisteredMethod`.

## How a method is classified

* **Write-verb prefix** — `add_`, `apply_`, `approve_`, `archive_`, `cancel_`,
  `complete_`, `connect_`, `create_`, `delete_`, `disable_`, `import_`, `insert_`,
  `link_`, `mark_`, `publish_`, `reject_`, `return_`, `save_`, `seed_`, `start_`,
  `submit_`, `update_`, `upload_`.
* **Read rules** (ported from the Flutter client's `isReadOnlyMethod`): the exact
  names `first_office_setup.status`, `employment_contracts.prepare_contract`,
  `workflow.validate_workflow`, `workflow.simulate_workflow`; the action names
  `execution_kinds`, `options`, `catalog`, `organization_tree`, `permission_preview`,
  `directory`, `editor`, `stock_balance`, `components`, `run_financial_report`,
  `tree`, `reports`, `history`, `download_attachment`; any `print_*` action; any
  action ending in `_options`, `_fields`, `_tree`, `_report`, `_summary`,
  `_preview`; and any action starting with `current_`, `get_`, `list_`, `preview_`,
  `trial_balance`, `general_ledger`, `purchase_request_options`.
* **`EXACT`** — an explicit `read`/`write` for every method that matches neither a
  write prefix nor a read rule, each with a one-line reason. This is where the
  verb-less writes (`directives.*`, `setup.set_default_office`,
  `workflow_request.void_native_document`, `workflow_request.reissue_native_document`,
  `calendar.read_alert`, `session.logout`, `organization.reset_chart`, …) and the
  verb-less reads (`session.login_state`, `setup_reset.status`,
  `workflow.test_workflow_condition`, `organization.employee_photo`, …) live.

## The offline outbox

`sync.execute_mutation` accepts a method into the outbox when
`is_queued_mutation(method)` is true: a write-verb prefix, or one of the exact
names in `QUEUED_EXACT` (the six `directives.*` verbs, `setup.set_default_office`,
and — since F-1 — `workflow_request.void_native_document` and
`workflow_request.reissue_native_document`). This reproduces the previous
`sync.py` allow-list exactly, so routing behaviour does not change except the F-1
fix.

## The `hr.save_report` mismatch (documented, not silently fixed)

`hr.save_report` is a **write** (`save_` prefix, queued by the outbox) but the
Flutter client still treats it as **read-only** (the `_report` suffix). The registry
classifies it `write` so the sync behaviour is preserved; the Flutter side is fixed
separately. Until then the app calls it directly, so an offline write is lost
instead of queued. This is the one known read/write disagreement and is listed in
the delivery report rather than changed here.

## Guard

`asoud_erp/tests/test_api_registry.py::test_every_whitelisted_method_is_classified`
AST-walks every `api/v1` module and asserts `classify` resolves each whitelisted
method. It fails the moment a new method is added with a name that matches no rule
and no `EXACT` entry, so a method can never ship unclassified. A companion test
asserts `sync._is_mutation` agrees with `is_queued_mutation` for every method, so
the outbox and the registry cannot drift.
