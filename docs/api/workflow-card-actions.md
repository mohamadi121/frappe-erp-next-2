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

Deletion uses existing POST `frappe.client.delete(doctype="ASOUD Workflow Definition",
name=...)`, not a parallel API. Native delete permission, company scope and manager
role are required. The definition controller rejects system definitions, any execution
or request history, version history, referenced form revisions, and ordinary native
link dependencies. Only its own technical transitions/stages may be removed, within
the same transaction; unrelated documents are never force-deleted. Failures retain
the original graph/status. Persian messages explain incomplete design, permissions,
history/dependency blocks; no framework names appear in UI errors.

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
