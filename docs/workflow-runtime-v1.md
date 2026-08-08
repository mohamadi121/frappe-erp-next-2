# ASOUD workflow runtime v1

Workflow stages can target an ERPNext role, department, or a specific Employee.
Specific Employee and department assignments resolve only to active Employees that
have an active ERPNext User account. The Employee identifier is persisted in the
workflow definition; display names are never used as relational identifiers.

Runtime records are stored in `ASOUD Workflow Instance` and `ASOUD Workflow Task`.
Users can list only their own tasks through the API and cannot complete another
user's task. Network failures may activate the Flutter in-memory preview, while
permission and validation failures remain visible and never become fake success.

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
linear stage. Flutter offline records are explicitly local-only and are not treated
as ERPNext transactions.
