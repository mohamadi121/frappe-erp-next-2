# Wait & Scheduling — additive contract v1

Wait uses existing Workflow Instance/Stage/Transition and the existing Frappe
minute scheduler/queue. It is not a human deadline or a separate workflow engine.

`GET asoud_erp.api.v1.workflow_wait.get_wait_options(definition, stage)` requires
System Manager/Accounts Manager, company access and definition write permission.
Returns `wait_version:1`, `fields` (only Date/DateTime, stable original/prior-stage
keys from the existing condition metadata adapter), `time_zone`, `zone_source`,
`execution_ready`, `output_valid`, `output_label` and a Persian `blocked_message`.

`POST asoud_erp.api.v1.workflow_wait.save_wait_settings(definition, stage, config)`
checks the same access, rejects Active definitions or running instances, validates
the source and exactly one existing outgoing edge, then uses the existing stage
save. It never creates a route or starts a schedule. Local drafts are client-only.
The client scopes drafts by server/user/definition/stage and records the server
configuration they were based on. A stale draft never silently replaces newer
server settings. A metadata retry does not restore a draft over current edits.

Readiness rejects a missing migration or disabled/paused native scheduler before
save/activation. It checks configuration, not worker heartbeat; deployment must
still verify that scheduler and queue workers are actually consuming jobs.

Config: `wait_version:1`, `title`, `description`, `wait_type` (`Duration`, `Date`,
`FormDate`), `past_policy` (`Continue` default / `Error`). Duration: positive
integer `wait_value` 1..3650, `wait_unit` Minute/Hour/Day. Date: `wait_value` is an
ISO Gregorian local date+time. FormDate: `date_source` with `source_kind`
Original/Stage, `source_stage`, `source_field`, `field_type` Date/DateTime;
`offset_direction` Same/Before/After, `offset_days` 0..3650; Date needs `clock`
HH:MM, DateTime uses its own clock. `date_change_policy`: Keep (default) or
Recalculate. Inactive mode fields are omitted, not interpreted at runtime.

Timezone is Company.time_zone if that existing native/custom field is present
and set; otherwise the existing site System Settings timezone (explicitly labeled
as such). No new company setting is invented. Ambiguous/nonexistent local times
fail clearly. Minutes/hours are elapsed time; Day/offsets advance calendar dates
in the office timezone and preserve local clock, not fixed 24-hour increments.

Migration adds only `wait_due_utc` (UTC-naive technical Datetime, indexed) and
`wait_snapshot_json` on Workflow Instance. Snapshot pins config, entry time,
definition version, timezone, original scheduled time, current due time and next
native node. Instance remains Running with no human task while waiting.

The minute scheduler enqueues bounded pages of waiting instances. Worker locks
the instance and verifies Running/current Wait/state before resuming; schedule
and transition commit in the same transaction. Repeated workers cannot advance
twice. Queue loss/restart is recovered from the persistent snapshot. Recalculate
checks actual source values at the scheduler cadence; reads/visits never schedule.
Cancellation/termination or a changed current stage makes an old wait inert.
Source errors and invalid destinations fail with an audit activity, never False
or a silent immediate continuation. History stores planned and actual times.

Legacy Duration/Date/Event configs are preserved and remain non-executable until
explicitly saved as v1. Event is not reinterpreted as a form date. No legacy
history is rewritten. Deploy backend, `bench --site <site> migrate`, restart web,
workers and scheduler, then paired client. Roll back code together without
dropping the additive fields or erasing pending snapshots/history.
