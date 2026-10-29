# Workflow card lifecycle (existing APIs)

`workflow.list_workflows` retains its envelope/list shape and includes the existing
`is_system_template`, `template_key` fields plus additive boolean `can_delete`.
Deletion is advertised only for non-system definitions with native delete permission.
System identifiers (`SYS-`), template flags and template keys are protected.

POST `asoud_erp.api.v1.workflow.set_workflow_status(name, status)` keeps its existing
serialized-definition response. System/Accounts Managers require company access and
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
