# Workflow card lifecycle (existing APIs)

`workflow.list_workflows` retains its envelope/list shape and includes the existing
`is_system_template`, `template_key` fields plus additive boolean `can_delete`.
Deletion is advertised only for non-system definitions with native delete permission.
System identifiers (`SYS-`), template flags and template keys are protected.

POST `asoud_erp.api.v1.workflow.set_workflow_status(name, status)` keeps its existing
serialized-definition response (also includes `can_delete`). System/Accounts Managers require company access and
native write permission. Activation validates the saved stage graph and configuration,
then updates readiness and status atomically. The ASOUD runtime does not require a
separate native Workflow link; an existing link is preserved and checked as before.
Deactivation only prevents new starts; running instances and historical rows remain.

## Start-time validity (PA-015)

Activation validates the saved graph, but a design can be corrupted after it is
Active (a stage deleted at the DB level, a route left dangling). `start_workflow_instance`
therefore re-checks the stored graph under the definition lock and refuses to start
when the pure `services/workflow_contract.structural_issues` reports breakage, with the
Persian message `این گردش‌کار معتبر نیست و تا اصلاح طراحی قابل اجرا نیست.` This covers
every start path (`create_request`, form submission, purchase requests). Saving an
`Inactive` draft is unaffected — designers still save incomplete drafts step by step;
the check runs only at start, and only for an `Active` workflow.

The check mirrors what the runtime (`workflow_runtime._next_stage` and
`start_workflow_instance`) can actually follow, not the designer's activation rules.
It rejects: a missing Start/End; a Start stage with no outgoing route (the runtime
throws «گردش‌کار مرحلهٔ قابل‌اجرا ندارد.»); a route to a stage outside the
definition; and a route whose `condition_json` does not parse to a dict. It does
**not** require every stage to be reachable from Start, to reach an End, or to have an
outgoing route: the runtime only navigates from the current stage (its outgoing
routes) or back to a previously-completed stage (Return, which walks the instance's
completed tasks, not the transitions), so a stage with no incoming transition (e.g. a
User Task that is only a Return target) and a stage reached via an Error route are
valid designs. It deliberately does **not** apply the designer's activation rules —
neither `_validate_saved_stage` (the Start trigger/initiator and other config rules)
nor `_validate_saved_routes` (the route-shape rules). That matters for two real cases:
the system request types (leave/purchase/supply) are started through `create_request`
and their Start stage has no `trigger_type`/`initiator_roles`; and a user-edited
workflow
may give a stage a single unlabeled default route (e.g. a System Action or Approval
whose only exit is an unlabeled `Continue` route), which the runtime treats as the
stage's main route.

Deletion uses whitelisted POST `workflow.delete_workflow(name)` (or existing POST `frappe.client.delete(doctype="ASOUD Workflow Definition",
name=...)`). Native delete permission, company scope and manager
role (`System Manager` or `Accounts Manager`) are required. Deletion is allowed
only for a non-system definition that has never run: no execution, task, activity
or request history may reference it. Form/source bindings, referenced form revisions,
and ordinary native links also block deletion. An eligible definition is deleted
with its owned stages, transitions and edit Version rows in one savepoint.
Execution-history refusal is a Persian ValidationError (417); soft deletion is
planned under #47. Success returns `{name: string, deleted: true}` in the standard
`success(data, meta)` envelope. Invalid/missing names are rejected in Persian.
Failures retain the original graph/status and edit history. Unrelated documents
are never force-deleted.

A successful deletion writes one `ASOUD Security Audit` row
(`action: workflow.definition.deleted`, actor, target, company and the workflow
code/title in `details`) inside the same savepoint as the deletion, so a failed
audit rolls the deletion back.

The client confirms deletion, does not optimistically mutate cards, and reloads the
current search/status/sort after success. Network failures do not imply success or
change local status. Both actions require an online session and are not queued.

## Read-only details dialog

Existing `workflow.get_workflow_design(definition)` keeps its role/company gates,
`workflow`, `stages`, and `transitions` response. Additive `details_summary` contains
`steps_count` (saved stages excluding Start), `stages_complete`, `routes_complete`,
and Persian `requirements` (list). It comes from the existing activation graph
validator, with diagnostic grouping only: activation rules/results are unchanged.
It does not persist readiness, alter status, run a workflow, or change history.
Stored `missing_requirements_json` may be stale; the dialog must use this fresh
summary, not infer missing routes from the definition's Pending flag. The two
completion flags describe the saved design, not a promise that every runtime
permission/service prerequisite is available. An older server without the summary
is shown as unverified, never as fabricated complete/incomplete information.
Related request/document titles already exist in saved `submission_source` stage
configuration; otherwise use the existing target type's Persian display label.

The ASOUD endpoint authorizes company access and delete permission before calling native deletion. The controller rechecks authorization before its lifecycle lock and execution/request/form/native dependency checks. Edit history alone does not prevent deletion of an unused definition. Version cleanup shares the graph savepoint, so a later dependency failure restores both history and graph. The endpoint delegates to the same native lifecycle guard.
