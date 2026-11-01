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
