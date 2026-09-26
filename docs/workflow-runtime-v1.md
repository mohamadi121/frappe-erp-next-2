# ASOUD workflow runtime v1

Workflow stages can target an ERPNext role, department, a specific Employee, the
user who initiated the workflow, every active Employee of the initiator's
department (`Initiator Department`), or the initiator's direct manager
(`Direct Manager`, the Employee `reports_to`). Initiator-relative assignments
always resolve from the immutable `started_by` value of the workflow instance
and the initiator's active Employee record in the workflow company; a missing
manager or an empty department stops the step with a validation error.
Specific Employee and department assignments resolve only to active Employees that
have an active ERPNext User account. The Employee identifier is persisted in the
workflow definition; display names are never used as relational identifiers.

Runtime records are stored in `ASOUD Workflow Instance` and `ASOUD Workflow Task`.
Users can list only their own tasks through the API and cannot complete another
user's task. Network failures may activate the Flutter in-memory preview, while
permission and validation failures remain visible and never become fake success.
Initiators can list their own sent instances and inspect the current stage, open
assignees, referenced ERPNext document, and ordered activity timeline. Instance
details are also available to task assignees and system/accounting managers.

Workflow assignments create standard Frappe v15 `Notification Log` records for
the assignee. Completion, approval, rejection, and return actions notify the
workflow initiator. The API exposes only the current user's workflow
notifications and validates ownership before marking one as read. This phase is
in-app only; external push delivery is intentionally deferred until production
server credentials and delivery infrastructure are available.

User Task and Approval stages may define a deadline in minutes, hours, or days,
an optional pre-deadline reminder, escalation roles, and explicit automatic
reassignment. New tasks persist their calculated due/reminder timestamps. An
hourly scheduler sends each reminder and overdue escalation once. Overdue tasks
remain with their original owner unless automatic reassignment was explicitly
enabled and at least one active user resolves from the configured escalation
roles; every reassignment is written to workflow activity history.

The runtime supports User Task, Approval, System Action, End, and safe Condition execution.
Condition values may come from a whitelisted field on the referenced ERPNext
document or from the latest completed workflow form. Supported operators are
`Is Set`, `Equals`, `Not Equals`, `Contains`, `Greater Than`, and `Less Than`.
Every condition requires exactly one true and one false transition; the selected
result is written to the immutable activity history before the destination task
is assigned. Arbitrary expressions are never evaluated. Wait execution remains
blocked until its scheduler-based executor is implemented.

## Decision routes

`workflow.save_stage_routes(definition, stage, routes)` sets a stage's exits by
decision: `Approve`/`Reject`/`Return` for Approval, `Complete`/`Reject`/`Return`
for User Task and `Success`/`Error` for System Action. Each route is a standard
`ASOUD Workflow Transition` with `condition_json = {"action": ...}`; an empty
target removes it. Saving the main route (Approve, Complete, Success) replaces
the unlabeled default route the designer creates. Without its own route a
rejection ends the instance as Rejected and a return goes back to the latest
editable user task; only forward decisions fall back to a single default route.

Stage settings stored with the configuration: `description`,
`reject_comment_required` (User Task and Approval), and for User Task
`allow_draft` (drafts rejected when off), `require_all_fields` (every form field
becomes required on completion) and `allow_edit_after_submit` (stored for the
client; not enforced yet).

## System actions

A System Action stage runs as soon as it is reached, in the transaction of the
decision that reached it, inside a savepoint:

| `action_type` | Configuration | Effect |
| --- | --- | --- |
| `Create Document` | `document_template`, `transfer_values`, `document_remark` | Inserts the ERPNext document of an [`ASOUD Document Template`](api/document_templates.md) (draft, or submitted when the template says so). |
| `Change Status` | `request_status` (label) | Sets `display_status` on the `ASOUD Workflow Request`; the request's own `status` is unchanged. |
| `Send Notification` | `target_roles`, `notify_initiator`, `message` (`{{RequestNo}}`-style placeholders) | In-app `Notification Log` to the role users and/or the initiator. |

Calling external APIs is not a system action. On failure the savepoint is rolled
back, a `System Action Failed` activity records the error, and the `Error` route
is followed; without one the instance becomes `Failed` and System Managers are
notified. A success writes `System Action Succeeded` with the created document in
`reference_doctype`/`reference_name`, then follows the `Success` route (or the
single unlabeled route).

## Request access

A generic request (`ASOUD Workflow Request`) is readable by its owner, System and
HR Managers, and any user holding a task on its workflow instance, so a
department colleague or direct manager can open the request they act on.

Task forms support server-side validation, drafts, private attachments up to 10 MB,
final responses, an immutable activity trail, rejection, and return to the previous
editable user task. Reviewers and approvers receive read-only context from completed
form stages. A return always requires a reason, preserves the latest submitted data
as the correction draft, and cancels sibling tasks before reassignment. Reject also
cancels sibling tasks to prevent a second decision. Flutter offline records are
explicitly local-only and are not treated as ERPNext transactions.
# Request types

A request type is an `ASOUD Workflow Definition` on `ASOUD Workflow Request`. Its
presentation metadata (short title, category, icon, list visibility) lives on the
definition and is edited through `update_request_type_info`. `allow_user_submission`
and the Start stage's `initiator_roles` are enforced by `create_request`, and
`request_options` lists only the types the current user may submit.

The form is the User Task directly after Start. Besides the scalar types, fields may
be `Multi Choice`, `User`, `Department` or `Item Table`. These never introduce new
masters: a User value must be the ERPNext user of an active Employee of the request
company, a Department must belong to that company, and item rows reference ERPNext
`Item` records. Item rows reuse ERPNext's end-of-life check and
`get_conversion_factor`; the stored row carries `item_name`, `stock_uom`,
`conversion_factor` and `stock_qty`. `request_field_options` returns the choices
for these fields from the same masters. Fields also keep an optional
`default_value`, `help_text` and `show_in_list` flag.

# Purchase request integration

`create_purchase_request` creates an ERPNext v15 `Material Request` with
`material_request_type = Purchase`, resolves the single active and ready ASOUD
purchase workflow for the company, and starts an ASOUD workflow instance that
references the created document. The whole request runs in the same Frappe
transaction, so failure to start the workflow prevents a partial committed
request.

`purchase_request_options` returns enabled purchase items and non-group
warehouses. `list_my_purchase_requests` returns only purchase requests owned by
the current ERPNext user.
