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

Reports/history expose pagination but currently collect a directive's records
before slicing. Notifications use Notification Log; push/SMS are not activated.
Overdue notifications use the existing hourly scheduler and per-task marker.
No arbitrary advance-warning interval is introduced. Due dates use the site's
date and end-of-day convention; configure the site's timezone correctly.

The cartable combines directives and existing workflow instances. Other HR
correspondence is still served by its existing module. Generic workflow lists
remain capped at 200 per query; the client marks incomplete totals explicitly.
Archive membership is never inferred from a closed/completed status.
