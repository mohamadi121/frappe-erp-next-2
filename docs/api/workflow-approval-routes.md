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

## Approval decision mode (quorum)

An Approval stage with several approvers decides by `approval_mode`, a key of the
stage config saved through `save_stage_settings`:

- `Any` — one Approve is enough; the other approvers' Open tasks are cancelled.
- `All` — every assigned approver must Approve.
- `Majority` — more than half of the assigned approvers must Approve
  (2 of 3, 3 of 5, …).

The default is the legacy behaviour: a missing or unrecognised value is treated
as `All`, so configs written before this feature are unchanged. `Majority` is the
new value; `Any` and `All` behave exactly as before.

Counting is per activation round. A Return route can re-activate the same
Approval stage with a fresh set of tasks; only the most recent round's tasks
count toward the decision (the earlier round is already settled). A Reject or
Return by any approver still cancels the whole stage, as before.

When an Approve does not yet satisfy the mode, the stage stays `Running`, the
other approvers keep their Open tasks, and a Persian activity is recorded
(`تأیید ثبت شد؛ برای ادامهٔ مرحله N تأیید دیگر لازم است`, with `N` in Persian
digits). The stage advances and the remaining Open tasks are cancelled only when
the mode is met.

`save_stage_settings` rejects any other value with the Persian error
`حالت رأی‌گیری مرحلهٔ تأیید نامعتبر است؛ فقط هر یک، همه یا اکثریت مجاز است.`

## Editability guard (PA-015)

`save_stage_routes` rechecks editability **under the definition row lock** before
touching any transition. It is refused with the existing Persian message
(`برای حفظ اجراها، گردش کار را غیرفعال کنید و تا پایان اجراهای جاری منتظر بمانید؛
یا یک کپی مستقل برای طراحی بسازید.`) when the workflow is `Active` **or** has a
`Running` instance, and the database is left unchanged. This is what stops a
designer from rerouting a stage out from under an in-flight instance (which
previously let an old instance skip an approval). The same guard now applies to
`save_stage_settings`, `connect_workflow_stages`, `insert_workflow_stage`,
`add_workflow_stage`, `add_condition_branch`, `save_start_settings` (legacy path)
and the `workflow_paths` removals — every graph/config mutation. Pure layout
(`update_stage_positions`) and presentation text (`update_request_type_info`) are
deliberately unguarded because they never affect execution.

## Approval assignees and the initiator

Nobody approves their own request. When an Approval stage resolves to the initiator
only, the stage's `escalation_roles` users (without the initiator) receive the task.
When no independent approver exists, entering the stage fails with the Persian error
«برای این مرحلهٔ تأیید، تأییدکننده‌ای غیر از درخواست‌دهنده پیدا نشد؛ تأییدکننده یا نقش تصاعد مستقل تعریف کنید.»
and the whole transition (start or completion of the previous task) is rolled back;
no Open task is created.
