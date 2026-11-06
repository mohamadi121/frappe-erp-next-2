# Workflow start settings (additive v1)

Existing `workflow.save_start_settings` accepts optional `settings` object.
Legacy calls retain their contract for unversioned Starts. Once explicitly saved
as v1, the legacy settings editor is refused with a Persian upgrade message, so it
cannot erase the source/policies. Versioned settings contain
`trigger_type` (Manual or Document Event), `initiator_roles` (enabled native roles),
`submission_source` (published `{form, revision}` only for Document Event),
`allow_manager_restart` (boolean), and `require_manual_reason` (must be true).
The saved Start config includes `start_settings_version: 1`. Duplicate active
record prevention and start auditing are always enabled and cannot be disabled.
No fixed start reason is stored by the designer: the initiator supplies it at runtime.

Only existing workflow managers with company scope and native write permission
may save. Existing start identity, positions and unrelated config are preserved.
Running instances block changes. Identical settings are a no-op, so metadata-only
saves remain possible during execution. Source metadata moves explicitly from
legacy User Task configs to Start; form contents/task settings and history are preserved.
Existing source binding validation/locks are reused; saving the binding itself
creates no form or instance. The existing picker may materialize a built-in form
definition/revision through `open_builtin`, never a business entry or execution.
Manual start clears the form routing link. Changing mode
requires explicit save; other workflows are untouched.

Existing `workflow_runtime.start_workflow_instance` accepts optional `reason`
and `restart` (0/1). For v1 Manual starts, allowed initiator roles and company scope
are enforced; a nonblank reason is mandatory. Manual mode cannot
be started by submitted Form Entry. A v1 Document Event workflow requires its
validated original Form Entry. Legacy workflows keep their existing entry paths.

Record-bound repeated calls normally return their existing instance (idempotency).
Explicit restart never duplicates a Running instance. Closed-record restart is
allowed only when configured and explicitly requested by a System Manager or
Accounts Manager with native workflow write and company permission, with a reason (supports
entries submitted by other users in the company, whereas plain starts require entry ownership).
It appends a new instance/activity; it never rewrites previous instances/history.
Start actor/time/reference and reason are recorded in existing Instance/Activity
records in the same transaction. General-subject manual starts have no record to
deduplicate; each intentional call is a separate run. No new engine/ledger/schema.

`workflow.list_workflows` adds boolean `can_start_manual`, computed from persisted
Active/Ready state, v1 Manual mode and the session's configured native roles. It
does not grant access to the management list or management actions. Runtime checks
company and initiator roles again. A configured role need not be in the legacy
hard-coded initiator role list. Existing reference read/ownership restrictions
still apply to explicit restarts; the exception does not grant document access.

`workflow_runtime.get_workflow_instance` adds boolean `can_restart` for an
authorized closed referenced execution only. It checks the same configured
exception, active/ready definition, company, native manager/write permission,
original reference ownership/read rules and absence of a Running execution for
that record. The existing runtime RPC revalidates under lock when starting;
the display flag is not authority. The client supplies the original reference,
`restart: 1` and a fresh reason, then opens the new execution without replacing
the previous instance or its history. Independent unreferenced manual runs are
new intentional starts, not record restarts.

UI saves definition metadata/draft via existing APIs then configures its Start.
On second-step failure the existing draft identity is retained for retry, not
created twice. It does not report complete success until Start save is confirmed.
Older servers lacking `start_settings_version: 1` must produce a clear upgrade
error rather than silently accepting unsupported settings. Existing templates
remain independent copies. System templates cannot be rebound to a new form.

Deploy paired backend/client and restart workers. No new migration is required
if the previously deployed submission-source fields/index exist. Site integration
and HTTP tests must run on a disposable bench before production rollout.

Local verification (2026-11-01): `python -X utf8 -m pytest -q` — 1330 passed;
`ruff check .` — all checks passed. The new pure policy test initially failed
before implementation because the new policy module did not exist. The real-site
module `test_workflow_start_settings` is registered in the integration CI loop;
`e2e/tests/workflow-start-settings.spec.ts` is included in `test:api` and has a
dedicated `test:workflow-start` script. These live suites were not run locally
(Bench/Frappe and Node/npm are absent); no production execution or reset was made.
