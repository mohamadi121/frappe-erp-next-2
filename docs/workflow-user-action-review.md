# User actions — implementation and verification boundary

This change uses the existing stage configuration, Workflow Task, Activity,
definition-copy, form revision/schema validation and Canvas completion paths.
No new engine, business ledger, queue DocType or arbitrary document write is added.

## Intentional behavior

- New edits opt into action v1; old stages remain legacy until explicitly saved.
- Original submitted entries remain immutable. Native request editing retains its
  existing owner/state permission checks; selecting Edit never grants a new right.
- Result forms pin a published revision. Activation rechecks availability; active
  tasks retain that revision. Historical actions render their saved schema.
- Tasks with history prevent config rewriting. Copy design first, review Pending
  stages and bind the new Start explicitly; no old task/history/file is transferred.
- Shared candidates must claim; first claim cancels peers in the same native task
  group under instance-first locks. Eligibility includes result-form access.
- Follow Up/Blocked require a note, remain Open and do not reject the original.
- Drafts remain partial; Complete validates the entire payload, recomputes formulas
  and uses the existing Canvas output. JSON null/non-object payloads are rejected.
- Reassignment is the existing configured overdue path, not an unrestricted new
  manual-transfer API. Prior drafts/private files stay on the same native task.

## Verification

Owner requested **no test execution**. No pytest, bench, HTTP test suite, emulator,
Flutter tests, golden updates or production mutations were performed in this task.
Pure, installed-site, HTTP and Flutter regressions are authored/registered but are
not represented as passing. Static analysis/lint and diff checks are reported in
the paired pull requests. Existing Workflow Designer golden images remain unchanged
despite the intentional Persian default-label change; refresh only after review.

Before production approval, run the registered user-action tests, simultaneous
claim requests against a test site, native reassignment/file-read permission checks,
and the 320/390/430 RTL drawer with an open keyboard. These remain unverified.
