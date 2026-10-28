# Submitted request/document workflow source

`User Task` settings accept optional `submission_source: {form, revision}`.
This is workflow routing metadata, NOT a task form, template copy or business write.
The source must be a published enabled same-company ASOUD Form; management requires
System Manager/Accounts Manager, company scope and native definition write access.
Saving takes the source-form lock, pins its immutable revision, and stores indexed
`source_form`/`source_revision` links on the workflow definition. All source-bearing
stages in one definition must agree. A form has at most one non-archived bound
workflow, including drafts; an existing schema.workflow route cannot be overridden.
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
