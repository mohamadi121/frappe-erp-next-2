# Workflow validity check and side-effect-free simulation

Two read-only endpoints on the existing `workflow` module. They inspect a stored
workflow graph and never write: no instance, task, notification, SMS or document
is created, and the simulation runs inside a savepoint that is always rolled back.
They reuse the existing readiness engine (`workflow_contract.activation_requirements`)
and the runtime's route selection (`workflow_condition.select_boolean_transition` and
the same `condition.action`/`transition_label` match the runtime's `_next_stage` uses).

## `workflow.validate_workflow` (GET)

`GET /api/method/asoud_erp.api.v1.workflow.validate_workflow?definition=<name>`

Roles: `System Manager`, `Accounts Manager`, `Accounts User`, `HR Manager` (same as
`get_workflow_design`). Company scope is enforced when the workflow has a company.

Arguments:

- `definition` (str, required) — the `ASOUD Workflow Definition` name.

Returns `success({"ok": bool, "issues": [...]})`. Each issue is
`{"code": str, "severity": "error"|"warning", "message": <Persian>, "stage": <name|null>, "route": <action|null>}`.
`ok` is `true` when there is no `error`-severity issue (warnings do not block).

Checks (the readiness engine owns the first group; the rest are added here):

- `start_end_missing` (error) — exactly one Start and at least one End.
- `route_external` (error) — a route points to a stage outside this workflow.
- `stage_invalid` (error) — a stage's config or its outgoing routes are incomplete/invalid.
- `wait_unsupported` (error) — a Wait stage (the runtime does not execute them yet).
- `disconnected` (error) — a stage is unreachable from Start or cannot reach an End.
- `self_loop` (warning) — a stage routes to itself (a return loop).
- `loop_no_exit` (error) — a stage is in a cycle that has no path to an End.
- `disabled_decision_route` (warning) — a Reject/Return route exists but the stage's
  `allow_reject`/`allow_return` is off, so that action is impossible there.
- `form_missing` (error) — a stage references a form (submission source or result form)
  that no longer exists.

## `workflow.simulate_workflow` (POST)

`POST /api/method/asoud_erp.api.v1.workflow.simulate_workflow`

Roles and company scope: same as `validate_workflow`.

Arguments:

- `definition` (str, required) — the workflow name.
- `decisions` (str JSON or list) — ordered decisions, each
  `{"stage": <name>, "action": <action>}`. Actions: `Approve`, `Reject`, `Return`,
  `Complete` for decision stages; `True`/`False` for a Condition stage.

The walk starts at Start and follows the stored graph using the same route-selection
as the runtime. **Condition stages are not evaluated against data**: the caller chooses
`True`/`False` (this is a design-time preview, not a real run). Decisions are consumed
in order; when the walk reaches a stage with no matching decision it stops and reports
`needs_decision`.

Returns `success({...})`:

- `steps` — `[{stage, title, stage_type, action, next}]` in walk order.
- `status` — `needs_decision` | `finished` | `error`.
- `waiting_stage` — the stage awaiting a decision, or `null`.
- `allowed_actions` — the actions valid at `waiting_stage` (empty otherwise).
- `outcome` — the End stage's `outcome` (`Completed`/`Rejected`/`Cancelled`/`Stopped`),
  or `Rejected` when a Reject has no route (the runtime ends the instance as Rejected),
  or `null` when not finished.
- `errors` — Persian error strings (empty unless `status` is `error`).

A walk that exceeds 200 steps stops with an error (loop guard).

## Snapshot backfill (PA-015)

`asoud_erp/patches/v0_19/backfill_graph_snapshots.py` runs once on `bench migrate`
for Running instances that predate the `graph_snapshot_json` field (empty snapshot).
There is no stored design history, so a historical snapshot cannot be recovered. For
each such instance the patch checks the **live** graph against what the instance
already executed: `current_stage` exists and is reachable from the single Start, and
every stage the instance's tasks/activities touched still exists. When consistent it
freezes the live graph using the same builder `start_workflow_instance` uses, tagged
with `snapshot_source: "backfill_live_graph"` (readers ignore the extra key). When
inconsistent it leaves the instance untouched and writes one `Error Log` entry
(`PA-015 snapshot backfill needs review`) listing the names. Idempotent: a re-run
changes nothing.

## Tests

- Pure: `asoud_erp/tests/test_workflow_check.py`, `asoud_erp/tests/test_workflow_simulation.py`,
  `asoud_erp/tests/test_workflow_contract.py` (`structural_issues` — the start-time
  structural check), `asoud_erp/tests/test_workflow_graph_snapshot.py` (snapshot +
  backfill consistency).
- Integration (real site, no mocks): `asoud_erp/integration_tests/test_workflow_check.py`,
  `asoud_erp/integration_tests/test_workflow_design_guard.py` (guards, start-time
  validity — including that the seeded system templates still start and a
  DB-corrupted one is refused — backfill) — both registered in
  `.github/integration-modules.txt`.
