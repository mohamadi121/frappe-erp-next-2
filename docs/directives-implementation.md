# Directives: deployment and integration

## Implemented contract

`api/v1/directives.py` owns the directive lifecycle. It reuses Internal
Communication, its recipients, Workflow Instance/Task/Activity, private File,
Comment and Notification Log. Directive Receipt is a technical idempotency
record, not a second business document store.

Each executor submits an independent versioned report. The issuer approves or
requests changes with a required reason. Transferring responsibility completes
the old assignment and appends the new recipient; it does not create a subtask
or delete old reports. The primary executor is a coordinator only. Closing
requires all active recipients approved and no other blocking open tasks.
Post-issue editing, cancellation, self-approval and substitute approval are not
enabled. Closed is not Archived.

Eligible recipients are active direct reports in the issuer's company with
enabled User accounts. The authenticated actor must have an active Employee
record and company access. Moving outside the company revokes directive access;
an inactive issuer cannot be substituted automatically. Former transferred
executors retain access to their own historical reports while company access
remains valid.

The adapter creates a protected **inactive** definition per directive, with
Report/Review/Close stages. It uses the existing workflow task and notification
store, but is not a published generic Workflow Builder/native Frappe Workflow.
Generic task mutation endpoints reject directive tasks. REST/document writes,
deletion, private downloads and list queries have additional directive guards.

Mutations lock the actor and document, then write lifecycle changes and a
receipt in the same request transaction. Repeating an actor/request key with
the same payload replays its result; another payload is rejected. Do not add
manual commits inside these handlers.

Attachments use the existing workflow extension allowlist and 10 MB limit.
The count comes from the communication DocType's max_attachments setting
(unset means no additional count limit). Staged uploads remain private to the
uploader until bound to the directive or report. Removing a staged selection
does not delete its underlying File. A retention/cleanup policy is not added.

## Installation

Deploy this extension revision and the matching Flutter build together. In the
existing Frappe bench, using the actual site name:

```sh
bench --site <site> backup --with-files
bench --site <site> migrate
bench --site <site> clear-cache
bench restart
```

Migration adds recipient state, directive version/instance links, task subtype
and report linkage, and the receipt DocType. Do not deploy only the Flutter app:
the dedicated endpoints and schema must be available. Ensure Employee.user_id,
company, status and reports_to are populated for issuer and executors, and that
the site's scheduler is running. Existing legacy Directive records are not
silently converted into executable instances; plan a separate audited migration.

## Verification and remaining boundaries

Static Python/JSON checks do not replace installation or runtime acceptance.
This implementation has not been exercised on a live Frappe site. Validate with
issuer, two executors and an unrelated employee: issue, file visibility,
independent reports, return/resubmit, transfer, duplicate request replay,
concurrent decisions, revoked company access and final closing.

Reports/history are paginated in the database (50 entries), with access scoping
before pagination. Reports can be filtered by executor; an executor cannot query
another executor's reports. Review identity and time accompany each decision.
History includes native draft comments, primary-executor changes, revised report
submissions and lifecycle events. Notifications use Notification Log; push/SMS
are not activated.
Overdue notifications use the existing hourly scheduler and per-task marker.
The issuer can optionally choose a reminder date and time before issuing. It is
stored in `reminder_at`, interpreted in the site's timezone, and copied to Report
tasks' standard `reminder_on`. The minute scheduler sends it once per eligible
open task; document/task locks and `reminder_sent_on` also prevent duplicate sends
if the hourly scheduler overlaps. Past reminders are rejected at issue time.
No mandatory due-time field or default reminder interval is introduced. Configure
the site's timezone and scheduler correctly; cron frequency is not a delivery SLA.

The cartable combines directives and existing workflow instances. Other HR
correspondence is still served by its existing module. Generic workflow lists
offer opt-in `paged=true` / `start` with `{items,next_cursor}`. Legacy callers retain
their list response. The updated client fetches every page and requires the new
backend contract; deploy the backend before the client. Responses are limited to
200 per page, not 200 for the whole cartable.
Archive membership is never inferred from a closed/completed status.

## Start and progress reports

The explicit `start` action moves the assigned recipient from Pending to In
Progress without completing their Report task. `report` accepts a validated
`report_type` (`final`, the compatible default, or `progress`). Progress records
reuse completed Workflow Tasks and private report files; they leave the blocking
execution task open, notify the issuer and never create an approval task. Final
report versions exclude progress entries. Returned work remains Returned until a
new final report is submitted. All mutations use the same locks, receipts and
server authorization. Transferred recipients also see the directive in Sent.
Deploy with migrate before the new client (recipient state adds In Progress).
No automated tests or live-site migration were run for this change.
