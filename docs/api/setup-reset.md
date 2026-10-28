# Temporary, administrator-authenticated setup reset

Implementation requires explicit site config activation; no site flag is enabled
and no live deletion is performed by development. The UI authenticates first.

`perform` queues a password-free background operation and returns `{job}`. New
authenticated `status(job)` returns `{job, state, message}` with queued/running/
completed/failed states. Receipts and the actor's latest job live in Redis for one
day; preview returns a pending job instead of authorizing a duplicate operation.
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

Deployment: no schema migration. Explicitly enable on the intended backed-up site,
use the temporary login entry, then disable/remove the flag. This environment does
not execute a live reset. User requested no tests; tests must not be reported passed.
