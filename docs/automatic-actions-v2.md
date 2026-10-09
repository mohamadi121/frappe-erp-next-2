# Automatic actions, schema 2

## Deployment and safe default

This is an additive extension to the existing ASOUD stage engine, not a new
business ledger. Deploy the extension app, run the site's normal `bench migrate`
to install **ASOUD Action Execution**, and restart workers/scheduler. No site
migration, service-account provisioning, test or live operation was performed
as part of this change.

An administrator must set both site configuration keys:

```json
{
  "asoud_workflow_service_user": "<dedicated existing System User>",
  "asoud_workflow_service_companies": ["<exact Company name>"]
}
```

Do not use Administrator, Guest or a System Manager. Grant only the native
DocType/Company permissions required by the selected operations, using a custom
role and User Permissions. Request creation additionally uses the existing
request-submission API, its initiator restrictions and its role requirements
(for example Employee); it is not a privileged backdoor. Request write/create
permissions are **not** granted by the new code: a dedicated role must explicitly
provide them. Standard request ownership restrictions remain unchanged for
ordinary users. The configured service user is subject to ordinary DocType
permissions and the explicit company allowlist.

Without the account/allowlist, drafts can be designed but execution stops with
`ServiceIdentityMissing`. Workflow activation through the workflow API checks
this prerequisite and native role permissions. Existing legacy actions also
require the restricted identity; legacy document creation no longer bypasses
native document permissions. No default account is automatically created.

## API and compatibility

- `automatic_actions.options(definition, stage)`: company-scoped field schemas,
  graph predecessors, request types, native document capabilities, recipient
  employees and permitted service-role workflow transitions.
- `automatic_actions.save(definition, stage, config, routes)`: validates and
  saves settings and Success/Error routes in one POST transaction.
- Config: `schema_version: 2`, `action_type`, independent `operation`, `execution`.
- Execution: `extra_attempts` (0–5 **after** the first attempt), `retry_seconds`
  (30–3600), `timeout_seconds` (10–300). Backoff doubles up to 3600 seconds.
- Source: `current`, `stage` with an explicit predecessor ID, `constant`, or
  `system`. Transform: `none`, text `trim`, numeric `round2`. Empty: `error` or
  optional-field `skip`. Required fields cannot skip empty input.
- Unknown operations/fields, hidden action settings and audit-off switches are
  rejected. There is no arbitrary API/script action.

Unversioned stages retain their old configuration and editor. Flutter offers
explicit, confirmed conversion; no automatic reinterpretation of a legacy
display-status label as a real native workflow transition occurs. New stages
use schema 2. Deployment of both frontend and backend is required; there is no
fake offline metadata/success fallback for this editor.

## Implemented operations and deliberate limits

1. **Create Request** uses the existing request API and full form/link validation.
   It supplies an execution-derived request ID. Private attachments may be copied
   only from the current source record or tasks in the same instance, with native
   read checks and existing upload limits. Recursive request-type dependencies
   are rejected. The new request has its own workflow and service-user ownership.
2. **Create Document** supports the existing native **Material Request** and
   **Journal Entry** adapters only. It creates an independent draft (default),
   or submits with explicit native permission. Item/UOM rules use existing
   validators/controllers. Journal accounts must use the company currency;
   automatic currency/unit conversion is not provided.
3. **Update Fields** applies an allowlisted mapping using native `save`. For
   ASOUD requests it validates merged custom form values. Ownership, status,
   company, identifiers, opaque JSON and other protected fields cannot be mapped.
4. **Change Status** calls native `get_transitions`/`apply_workflow`, never direct
   status assignment. Design-time choices are service-role workflow actions,
   **not proof that a particular runtime record satisfies a conditional rule**.
   Current state, self-approval and conditions are checked again at execution.
   Without a configured service user, no authorized status choices are offered.
   Native background submission is not supported in this transactional action.
5. **Send Notification** supports in-app `Notification Log` alerts and queued
   email to the initiator and selected active company users. Recipient company
   and document access are checked. The standard Alert type does not also emit
   an implicit email. Each channel has an independent result/savepoint. Email
   results say **queued**, not delivered; channel failures mark the action
   **Completed With Errors**, not successful delivery. SMTP failures/retries are owned by
   native Email Queue. An outgoing account is required. SMS/push, role-based
   recipients and department recipient expansion are not implemented here.
6. **Calculate Value** supports sum, average and bounded arithmetic formulas
   over mapped numeric operands. The AST allowlist has no calls, attributes,
   indexing, power operator, imports or code execution. Nonfinite/oversized
   results and division by zero fail. There is no implicit currency conversion.
7. **Link Record** performs an exact equality lookup on an allowlisted field,
   restricted to the company. No match explicitly errors or skips; multiple
   matches always error, including matches hidden from the execution user.
   The relation is recorded as a native timeline Comment and technical receipt
   reference; it does not populate an arbitrary business Link field or create
   a separate business relationship ledger.

The initial source/target record allowlist is ASOUD Workflow Request, Material
Request and Journal Entry. Other DocTypes require reviewed native adapters,
not a frontend-only option. Data-dependent permissions, values, currencies,
UOM and workflow conditions necessarily receive their final check at runtime.

## Reliable execution

Each stage activation gets a deterministic receipt ID from instance, stage and
activation trigger. Duplicate workers lock that receipt; completed receipts do
not execute again. Pure automatic-stage loops are refused within the same
trigger; a new human task visit provides a new trigger.

The scheduler dispatches pending receipts to native background workers with a
real per-job timeout. Cron requests a one-minute cadence, but actual dispatch
precision depends on the site's scheduler polling interval, not subsecond timing.
Attempt count is committed **before** effects.
Business effects, native links, successful result and graph advancement commit
together. Failure performs a full worker-transaction rollback (including native
File cleanup/after-commit callbacks), then persists the error and audit. A worker
interruption can be recovered after timeout plus a 60-second grace period without
resetting the extra-attempt budget. This relies on native controllers respecting
Frappe transaction semantics; external custom hooks that commit or call external
services cannot be made exactly-once by this extension.

Only explicit connection/time-out exceptions retry. Permission, validation and
unexpected programming errors fail closed. Final failure either goes to an
existing human User Task or marks the instance Failed. Audit entries include
execution ID, action, attempt, timestamp and result/error code; detailed errors
are on the company-scoped, manager-readable technical receipt. Email delivery
failure does not roll back a document from a previous stage.

Configuration and routes are snapshotted on the receipt. Completed record
output values are retained separately by stage ID; selecting one previous
stage does not silently merge all previous stage responses.

## Verification status

Source review and formatting only. The user explicitly asked not to run tests
during this implementation. No Flutter analyzer/build, unit/widget/golden test,
Frappe migration, database integration test, RQ timeout test or SMTP delivery
test was run. The implementation is **not a verified production deployment**.
Before enabling it, exercise duplicate dispatch, crash recovery, create/link
rollback, native permissions/transitions and the seven mobile form modes in an
isolated migrated site. Existing standard app sources were inspected read-only;
ERPNext/Frappe source was not modified.
