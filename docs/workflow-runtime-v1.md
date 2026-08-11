# ASOUD workflow runtime v1

Workflow stages can target an ERPNext role, department, a specific Employee, or
the user who initiated the workflow. Initiator assignment is intended for
correction routes and always resolves from the immutable `started_by` value of
the workflow instance.
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

The runtime supports User Task, Approval, End, and safe Condition execution.
Condition values may come from a whitelisted field on the referenced ERPNext
document or from the latest completed workflow form. Supported operators are
`Is Set`, `Equals`, `Not Equals`, `Contains`, `Greater Than`, and `Less Than`.
Every condition requires exactly one true and one false transition; the selected
result is written to the immutable activity history before the destination task
is assigned. Arbitrary expressions are never evaluated. Wait and System Action
execution remain blocked until their dedicated secure executors are implemented.

Task forms support server-side validation, drafts, private attachments up to 10 MB,
final responses, an immutable activity trail, rejection, and return to the previous
editable user task. Reviewers and approvers receive read-only context from completed
form stages. A return always requires a reason, preserves the latest submitted data
as the correction draft, and cancels sibling tasks before reassignment. Reject also
cancels sibling tasks to prevent a second decision. Flutter offline records are
explicitly local-only and are not treated as ERPNext transactions.
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
