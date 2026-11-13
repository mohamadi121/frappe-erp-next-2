# Native draft path editing

These methods edit the existing ASOUD Workflow Stage/Transition records. They
are not an execution engine and do not add business tables. All methods require
System Manager or Accounts Manager, native definition write permission and
company access **before** taking a definition lock.

## Existing insertion API

`POST workflow.insert_workflow_stage(definition, transition, stage_type, draft_edit=1)`
splits the selected native edge. The additive flag refuses Active definitions
and any definition with execution history. The response is the usual design
plus an encrypted, actor/definition/stage-bound `insertion_token` (24-hour life).
The paired client opens the existing stage editor before refreshing the canvas.
On confirmed settings save it refreshes the parent design; on cancellation it
uses the token to restore the original edge.

## Cancellation

`POST workflow_paths.discard_inserted_stage(definition, stage, original)` takes
the insertion token as `original`. It refuses forged tokens, changed topology,
shared/dependent stages and changed incoming route settings. It restores the
split edge with its original label, condition and sequence in a savepoint.
The restored edge receives a native new transition ID; surviving stage IDs do
not change. Cancellation may not discard somebody else's subsequent edits.

## Delete preview and confirmation

`GET workflow_paths.preview_path_removal(definition, transition)` returns
`stages`, `transitions`, `stage_labels` and definition `version`.

`POST workflow_paths.remove_path(definition, transition, version)` recalculates
the plan under a definition lock and rejects stale versions. Only the selected
edge and its exclusively owned downstream branch are removed. Shared nodes,
other branches and configuration dependencies are protected. A configuration
reference to a proposed removed stage blocks deletion. Active or ever-executed
definitions must be copied before destructive edits. All native deletions and
the version change roll back together on error.

The former node-side chain and its connection sheet have been removed from the
client at the user's explicit request. Path chains have exactly two actions:
add stage / delete path. The old backend connection API is left compatible for
existing callers and stored designs; no existing connections are deleted merely
because their old entry point was removed.

## Limits

Preview is bounded to 1,000 stages/4,000 edges; oversized designs fail closed.
An interrupted HTTP insertion with no response cannot supply its cancellation
token to the client; automatic crash recovery for that case is not implemented.
Deleting the final edge does not create a replacement/dangling native edge.
No new editor for shared-node reconnection is introduced.

Deploy backend before the paired client and restart normal web/workers. There
is no new schema migration. Roll back both code versions together; do not
restore an old database over newer business history. Production service account
configuration is separate from deploying these UI/path changes.
