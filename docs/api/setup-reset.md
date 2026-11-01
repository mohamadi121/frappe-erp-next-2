# Temporary, administrator-authenticated setup reset

## Complete first-entry reset correction

The existing `preview`/`perform`/`status` flow deletes the authenticated owner's
offices, organization charts/positions/units, personnel and custom roles. Login
identity/password/System Manager authority, native essential roles, other owners'
offices and security audit are preserved. Operational/posted dependencies still
block deletion; this is not a site-wide accounting purge.

Only the authenticated, queued reset worker may remove the previewed offices'
system workflow definitions and their technical edit history. Its in-process
capability includes actor, job and the exact freshly verified document scope;
ordinary workflow deletion remains protected, and native dependency checks are
never forced or skipped. Owned form/revision/source cycles are broken within
the same rollback-capable transaction. Any remaining relationship aborts all
changes. Counts include technical edit history affected by native deletion.

Completed `status` adds `actor: string` and `companies: string[]`, recovered from the mandatory durable
receipt (also after lost Redis state). The client clears only that user's related
organization drafts/caches, personnel/office caches and custom role drafts on the same server **after**
durable server success; failure/queued/running never clear them. Credentials and
queued offline writes/other users' drafts are not cleared. Related organization and
role drafts are explicitly discarded with the administrator's confirmation.
Cache-cleanup failure does not
repeat server deletion or falsely report that the committed reset failed.
Office caches now use an owner/server namespace; ownerless legacy records are
not adopted or erased, so a deleted office cannot reappear from a legacy fallback.
The preflight also checks the separate personnel outbox and scoped pending office
records, not only the generic offline mutation queue.

The reset still requires the explicitly enabled server flag, admin sign-in, fresh
password, preview, backup acknowledgment and typed confirmation. No SSH interaction
is part of the app's button. The next sign-in loads server-authoritative first-entry
state; deploying this code does not itself delete production data.

Implementation requires explicit site config activation; no site flag is enabled
and no live deletion is performed by development. The UI authenticates first.

`perform` queues a password-free background operation and returns `{job}`. New
authenticated `status(job)` returns `{job, state, message}` with queued/running/
completed/failed states. Receipts and the actor's latest job live in Redis for one
day; preview returns a pending job instead of authorizing a duplicate operation.
`status(preview_token=...)` recovers only the job accepted for that exact actor-bound
preview when the enqueue response is lost; it never reuses an unrelated old success.
Queued authorization expires after five minutes if a worker has not started it.
Timeout/unknown status is never reported as success. The worker revalidates the
actor and exact preview, blocks application requests/writes during reset, uses a
site-wide lock and native transactional deletion. A failure is rolled back and
recorded as failed; completion is recorded only after the database commit.

Disabled unless site config `asoud_allow_setup_reset` is explicitly true. Never
guest-accessible. Uses the authenticated enabled System Manager, native password
verification and no offline/idempotency queue (passwords must never be staged).

POST `asoud_erp.api.v1.setup_reset.preview()` returns `{token, companies: [title],
counts: {doctype: count}, blockers: [Persian reason], preserved: [Persian text]}`.
Token is actor-bound, expires in 5 minutes and commits to names/modified tokens.
With an unfinished previous operation, preview returns `{job}` instead of a plan.
Scope is companies the actor created/administers, their setup/personnel/organization
records, unused owned custom role definitions/profiles and the actor's profile.
Source ownership is verified on server; native/system roles and other companies
are never reset. Posted/operational or unsupported dependent records block reset.

POST `asoud_erp.api.v1.setup_reset.perform(token, password, confirmation,
backup_confirmed=0)` requires exact phrase `شروع دوباره`, a confirmed recoverable
backup, fresh native password verification and unchanged preview. Uses native
deletion hooks without force/ignore_links, in one transaction/savepoint. Any native
dependency/business-rule failure rolls all reset writes back. No business-document
cancellation, ledger deletion, security-audit deletion or cross-office erasure.

Preserves current User identity/email-as-key, username, password hash, enabled
System User status, System Manager role and essential system metadata. Clears
personal onboarding fields/contact profile and first-office markers only for scoped
offices; existing other offices are not erased. A successful reset returns
`status.state == 'completed'`; client signs out so the ordinary login router can start again.
Role definitions in use by other accounts, active workflow/form entries or unknown
dependencies are blockers, not silently skipped. This is intentionally not a whole
site/database wipe. Native accounting/stock transaction deletion requires its own
reviewed workflow.

## Deployment and recovery

Run migration for the paired workflow source fields, restart web and background
workers, then deliberately enable `asoud_allow_setup_reset` on the intended site.
Do not enable it permanently. The long queue must have a running worker. No server
configuration or production reset is performed by this change. Turn the flag off
after confirming completion; status receipts remain readable by the same admin.
Each success has a mandatory append-only database receipt in the same transaction,
so status can recover after a lost Redis response or a worker exit after commit.
Failed/stopped RQ jobs cannot report success. Unknown/missing receipts require
server review, not an automatic destructive retry. Direct database/bench writes
outside application hooks must not run during this administrative operation.
The current administrator's recovery tokens are invalidated, but the native login
identity, username and password are preserved. Posted and unsupported dependencies
block the reset rather than being forcibly erased. Existing ledgers are not wiped.
Live destructive/site verification is required on a disposable, backed-up site
before enabling production reset; local pure/widget tests cannot prove native deletion.

Background execution uses the native
[Frappe v15 queue and job status API](https://github.com/frappe/frappe/blob/version-15/frappe/utils/background_jobs.py).

Deployment: no schema migration. Explicitly enable on the intended backed-up site,
use the temporary login entry, then disable/remove the flag. This environment does
not execute a live reset. See [the reset review report](../setup-reset-review.md)
for actual verification results.
