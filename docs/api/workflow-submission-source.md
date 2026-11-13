# Submitted request/document workflow source

`User Task` settings accept optional `submission_source: {form, revision}`.
This is workflow routing metadata, NOT a task form, template copy or business write.
The source must be a published enabled same-company ASOUD Form; management requires
System Manager/Accounts Manager, company scope and native definition write access.
Saving takes the source-form lock, pins its immutable revision, and stores indexed
`source_form`/`source_revision` links on the workflow definition. All source-bearing
stages in one definition must agree. A form has at most one non-archived bound
workflow in the legacy contract. The additive shared-source contract below
replaces this exclusivity without changing native ERPNext Workflow rules.
An existing system template cannot be rebound. Clearing its last stage binding
clears the definition routing links. Existing workflows without a source are unchanged.

`forms.get_form` returns additive `submission_source_version: 1`. On submit the
ordinary schema/access/value/native-controller validation runs first. A bound
workflow must be Active/Ready and match the selected published revision; otherwise
submission fails before creating anything. The original ASOUD Form Entry is the
workflow reference for requests AND documents; document entries keep their normal
native reference. No second request/form/native document is generated. Entry and
instance are transactional and retries reuse the entry/instance. The ordinary
runtime receives a permission-checked reference owned by the submitter; it does
not allow arbitrary Form Entry references or unbound/manual source starts.

Management selection uses `get_form(manage=1, revision_name=active_revision)`;
published identity and submission rights are separate, so a manager need not be
an eligible submitter. The draft schema is never selected. Built-ins first use
`open_builtin(manage=1)` to resolve their published identity. `get_form` includes
additive `active_revision` and `disabled` fields for stale-selection checks.

Assigned task users see a read-only submitted-form snapshot; sensitive fields and
attachment URLs are omitted from that snapshot. Submitted values are never accepted
as editable task responses. Normal assignee, deadlines, decisions and permission
checks apply. New form revisions require explicit rebinding; no silent migration.
Request values come from the original saved entry. Document values are read from
the original native document under its read permission, not a second ledger or a
frozen copy of a live document. Snapshot rendering prevents client recalculation;
it does not prohibit later native document edits that existing permissions allow.
Native document posting/execution behavior remains unchanged. Manual task form
fields and source routing are separate; no new output is implied by source selection.

Deployment: `bench migrate` for definition source links and index, restart workers,
then release Flutter. Tests are authored but not executed at the owner's request.

## Shared source routing (additive)

Start settings optionally accept `source_route`: `Available`, `Default`, or
`Conditional`. Binding alone is always allowed for published same-company forms.
The first binding becomes Default if there is no existing binding or legacy
schema.workflow route. Later bindings are Available until explicitly configured.
There can be at most one Default binding; existing implicit legacy bindings count
as Default. No existing default or history is silently overwritten.

Conditional routing uses the existing v2 Condition immediately after Start. Its
predicates must use Original fields only; they are evaluated with the existing
exact evaluator against validated submitted values. There is no separate rule
language, table or runtime. Exactly one matching ready/active conditional wins;
multiple matches are a Persian conflict, never first-row selection. If none match,
the unique default must be ready/active, or the existing legacy schema.workflow
route is used unchanged. Inactive/Available designs do not compete with the default.
The saved entry and existing instance stay the authority for retries.

`create_workflow_draft` accepts optional `start_settings`; creation and Start save
are atomic. `workflow_templates.create_from_template` accepts the same optional
`start_settings` and rolls back the copied draft if Start fails.
Both responses include `data.start_settings` with the actually saved Start JSON;
the client verifies trigger/source from that same transaction response, not from
a second network request which could fail after a successful creation.
`save_start_settings` adds `validate_only=1, company` with an empty
definition for a permission-checked read-only preflight before draft/metadata
writes. No preflight creates a definition, entry or instance. It returns
`{valid: true}`. Saving repeats validation under the existing form/definition locks.
Clients keep failed selections, never reinterpret a Pending legacy Manual default
as a deliberate user choice, and open the designer only after complete success.

No new DocType fields or migration are required. Deploy backend before client;
native Workflow active-per-DocType restrictions remain unchanged. Existing drafts
(including WF-1405-044), immutable form revisions and executions are not migrated.
