# Approval stage supplementary form (pinned ASOUD Form revision)

An **Approval** stage can be bound to a published ASOUD Form of kind `Stage`
(«فرم مرحله گردش کار»). Each approver fills the form on their own task; the values
are stored per approver, exactly like the existing inline approval form.

The legacy inline approval form (`form_fields` / `form_layout`) keeps working
unchanged. A stage uses **either** the inline fields **or** the supplementary
form, never both.

## Stage settings

`workflow.save_stage_settings(definition, stage, config)` — Approval stages only.

Additive config key:

```json
"supplementary_form": {"form": "<ASOUD Form name>", "revision": "<ASOUD Form Revision name>"}
```

Server validation (all errors are Persian):

- The form exists, has `kind = "Stage"`, belongs to the workflow's company, and is
  not disabled.
- The revision belongs to that form.
- The server fills `title` (the pinned revision's schema title) and stores the
  binding as given.
- When `supplementary_form` is set, `form_fields` / `form_layout` must be empty.
- Sending `supplementary_form` for any non-Approval stage is rejected.
- Removing it (`null` / absent) never deletes the form or its revisions.

The existing rule that edits are refused while the workflow is Active/Running
applies as today.

## Task detail

`workflow_runtime.get_workflow_task(task)` adds, only when the stage config has a
binding:

```json
"supplementary_form": {
  "form": "<name>", "revision": "<pinned revision>", "title": "<schema title>",
  "schema": { /* the pinned revision's migrated schema */ },
  "values": { /* saved draft or submitted values, {} if none */ }
}
```

The key is absent otherwise. Values are returned only where the task response is
already returned (same permission path); there is no new permission. The binding
pins a revision, so publishing a new revision of the form does not change running
or finished tasks — they keep reading the pinned revision.

## Completing the task

`workflow_runtime.complete_workflow_task(task, action, ..., supplementary_values)`
accepts an optional `supplementary_values` (object or JSON string):

- Validated with `form_schema.validate_values` against the **pinned** revision's
  schema.
- Required fields are enforced only for `Approve`. For `Reject` / `Return` the
  values are optional but still validated when sent.
- When `supplementary_values` is omitted, the saved draft values are used, so a
  required field is still enforced on `Approve`.
- Stored in the same task's `response_json` under the reserved key
  `_supplementary = {"form", "revision", "values"}`. Field keys must match
  `[a-z][a-z0-9_]*`, so `_supplementary` can never collide with a real field.
- The approve/reject decision never depends on these values.

`workflow_runtime.save_workflow_task_draft(task, response, supplementary_values)`
also accepts `supplementary_values` and keeps them the same way; when omitted, the
previously saved supplementary values are preserved.

## Multi-approver policy

Values are stored per approver (each approver's own task), which is today's model.
The final multi-approver policy is not yet decided.
