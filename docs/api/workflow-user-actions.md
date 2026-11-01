# User action settings — additive v1

Existing User Task stage identities and legacy configs stay valid. New edits opt
into `action_contract_version: 1`; the Persian name is اقدام کاربر. Existing
`save_stage_settings` manager/write/company checks remain authoritative.

Config: `result_mode` (Simple/Form), `result_form` ({form, revision}, published
same-company form), `allow_add_attachments`, existing `allow_draft` and
`document_access`, and `assignment_rule` with:

- basis: Unit, Subject Unit, Subject, Manager, Role;
- subject: Initiator/Form Employee; employee_field: actual source Employee link;
- department: native unit for Unit or department-scoped Role;
- person: active Employee in that unit for direct assignment;
- role: enabled native Role; scope: Company/Department; delivery: Direct/Shared.

Irrelevant fields are normalized away. Native Employee/Department/User/Has Role
and existing company-access checks resolve recipients at execution. Invalid,
disabled, wrong-company or unresolved targets fail explicitly. No new permission
is granted. Existing legacy/approval assignment behavior is unchanged.

Shared candidate tasks reuse native Open task rows marked `Awaiting Claim` in
action. Existing `complete_workflow_task` accepts Claim: instance/peer locks keep
the first claimant, cancel other candidates and append native Activity history.
Writes before claiming are refused. No parallel queue/engine/schema is created.

Existing `get_workflow_task` adds action_schema, action_form, action_company,
action_contract_version, requires_claim, allow_draft, allow_add_attachments.
Existing form renderer/schema validation handle computed fields and repeating
rows. Values stay on the same native task's draft/response JSON; form submission
is NOT invoked and no unrelated business document is created. Pinned forms must
remain published, enabled, same-company and accessible. Activation rechecks links.

Simple mode fields: action_result (done/follow_up/blocked), action_note and optional
action_files. Designers select the method, never enter execution data. Completion
RPC accepts Follow Up/Blocked for v1 simple tasks: reason is mandatory, task stays
Open, result/history persist and Canvas does not advance. Complete requires done
and validated fields. These outcomes never Reject the original request. Draft
save does not complete the task. Existing attachment/draft/completion APIs enforce
the settings and native private-file rules. Only new owned unattached files may
be linked to the task; old attachments are never deleted or reassigned.

Creation method reuses independent template copies, not fabricated in-place
version branches. Source module selection also fills existing definition
module_key (Finance -> Accounting, Administration -> Support). No classification
store is added. Backend/client deploy together, no migration. The user explicitly
requested no test execution; this change must not be reported as tested.

Stage configs with execution history cannot be rewritten or converted in place;
the existing independent-copy flow is required. A server-derived `result_schema`
snapshot preserves historical rendering even if the source form is later removed.
New publication requires the current published result-form revision; existing
tasks validate against their pinned immutable revision while the form is enabled.
`forms.get_link_options` optionally accepts `task`: it checks the native assigned
task and its pinned form instead of guessing the current form revision. Source,
company, row filters and existing record permissions are unchanged. This is not
an arbitrary older-revision read grant. Native schema validation may accept an
already-attached private File owned by the prior assignee only when the caller
can read it and it was already on the same task; ownership is never rewritten.

Native overdue reassignment is retained: v1 queues are serialized and reduced to
one assigned task before transfer to an enabled escalation-role user in the same
company. Assignment, claim and reassignment use existing Activity rows; former
drafts/files stay on the transferred task. No unrestricted manual transfer API is
introduced. Original submitted form entries remain immutable. `document_access`
does not grant native write access: existing request editing remains subject to
its own owner/state checks; a task result never overwrites original entry values.

The existing workflow-template catalog/copy endpoints also accept accessible
non-archived user definitions in the same company. Copies always receive fresh
definition/stage identities, version 1 and Pending configuration; no execution,
history or native workflow link is copied. Original and other-company records
remain untouched. Pending v1 action copies validate the config's structure;
published-form/subject bindings must be explicitly reviewed before activation.
