# Approval output destinations

This is the existing designer route API, not an additional workflow engine.

`POST asoud_erp.api.v1.workflow.save_stage_routes`

Arguments: `definition`, `stage` and `routes` (an object or JSON object with
`Approve`, `Reject`, `Return` mapped to stage names). Roles: System Manager or
Accounts Manager, permitted company, native definition write permission. Checks
run before the definition lock. Response: existing `success(design)` envelope.

Options are actual nodes from `get_workflow_design(definition)`, not templates or
example destinations. Each non-empty value is a persistent stage name; title
changes do not affect the connection. Choosing a target never creates a node.
The Flutter sheets reload the design before opening and before saving, retain
the existing styles, and show a search field for lists longer than eight nodes.

- Approve: an existing forward node, never the current node/Start/predecessor.
  An End must have Completed outcome. No synthetic success node is generated;
  if there is no valid forward node the designer must add one through the
  existing Canvas controls.
- Reject: an existing handling node (supported by the current runtime), or empty
  target to terminate this execution as Rejected. A direct Reject-to-End also
  terminates as Rejected, even if that shared End is used by successful paths.
  The End configuration itself is not rewritten.
- Return: a preceding human node (User Task/Approval), or empty target to select
  the latest editable user task from this instance's completed history. Modern
  action result forms/reports participate in that existing history selection.
  An explicit Return target must have completed in this execution; another
  branch's unvisited task is not a valid runtime destination.

All supplied targets are validated before any route is removed. Missing targets
produce a Persian reselection error. Existing stage ownership and native Link
checks remain in force. Runtime rechecks missing/invalid targets and cannot use
a Reject-only edge as an Approval default. The ordinary legacy default-route
behavior of other station types is unchanged.

During execution the actor supplies only the decision, not a destination. The
existing runtime resolves the stored transition, or the documented empty-target
fallback. Returning reactivates a node within the same instance/request; no new
request is created by destination selection. Existing correction/version history
and permissions are unchanged. No schema migration is required.
