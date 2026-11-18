# User action settings — additive v1

## Report and optional capabilities (additive)

New action designs set `simple_result_style: Report`. Its only scalar result is
required LongText `action_note` (گزارش انجام اقدام, max 5000). Existing configs
without this key retain `Outcomes`, including their existing result/history.
`Complete` validates the report; Follow Up/Blocked remain Outcomes-only.

Four independent settings are `allow_original_access` (default true for older
configs), `document_access` (Read Only/Edit), `allow_add_attachments`, existing
`allow_draft`, and `allow_reassign` (default false). The first two constitute
one original-access capability. Disabling original access removes original
snapshot/values/request links from this task response, not Canvas evaluation.
Enabling Edit never grants native write permissions, unlocks submitted immutable
form entries or bypasses the original request's owner/state rules.

Existing `get_workflow_task(task, candidate_query?, candidate_start=0)` returns
`reassignment_candidates: [{user, label}]` and `has_more` when candidate_query is
supplied, after task ownership/company/live-stage/claim checks. Page size 25;
search max 100 characters; at most 200 eligible principals are resolved. Unit
direct assignment may transfer within that same unit; shared unit/role scopes
retain their rule. Subject/manager direct assignments may transfer within the
resolved person's active unit; an account without Employee has no such expansion.
Native enabled-user, company and pinned-result-form access are rechecked at write.

Existing `complete_workflow_task` accepts `action: Reassign, assignee: <user>`.
It checks allow_reassign, locks instance then the same task, rejects self/unknown/
ineligible recipients, preserves response/draft/files, transfers assigned_to and
records Reassigned with old/new user/time in native Activity. No stage advance or
new task occurs. Former owner loses access immediately. Successful envelope:
`{task, reassigned: true, instance_status}`. Errors are Persian, e.g.
«واگذاری مجدد برای این اقدام فعال نیست.» / «کاربر انتخاب‌شده واجد شرایط این اقدام نیست.».
Client and backend deploy together; no database migration. Test execution is
explicitly excluded by the user's standing instruction, not reported as passed.

Existing User Task stage identities and legacy configs stay valid. New edits opt
into `action_contract_version: 1`; the default stage title is بررسی یا ویرایش سند. Existing
`save_stage_settings` manager/write/company checks remain authoritative.

Config: `result_mode` (Simple/Form), `result_form` ({form, revision}, published
same-company form of kind `Request` or `Document`), `allow_add_attachments`, existing
`allow_draft` and `document_access`, and `assignment_rule` with:

A `result_form` of kind `Stage` is refused: a Stage form is the supplementary-stage
concept (bound via `supplementary_form` on Approval stages) and must not be reused as a
task result form. The refusal is enforced in the result-form loader at design time and
again at task completion.

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
drafts/files stay on the transferred task. The optional bounded manual transfer
described above reuses this same task API. Original submitted form entries remain immutable. `document_access`
does not grant native write access: existing request editing remains subject to
its own owner/state checks; a task result never overwrites original entry values.

### `document_access` save rule (PA-066)

`document_access` is a design-time setting the app reads to choose the form UI; the
backend does not enforce it at runtime (see the report in the PA-066 findings). On
`save_stage_settings` (User Task and Approval stages, including v1 user-action
configs) the stored value is resolved against the incoming one:

- A stored `Limited Edit` (ویرایش محدود) is **never silently rewritten to `Edit`** by a
  client that re-sends `Edit` without the change flag. App 0.31.0 rewrites a stored
  Limited Edit to Edit on save even when the user did not touch the option, so the
  backend keeps `Limited Edit` in that case.
- A stored `Limited Edit` re-sent as `Limited Edit` is kept.
- `Limited Edit` is **no longer offered as a new choice**: sending it for a stage that
  does not already store it is rejected with
  «گزینهٔ ویرایش محدود دیگر قابل انتخاب نیست؛ «فقط مشاهده» یا «مشاهده و ویرایش» را انتخاب کنید.»
- An explicit change to `Read Only`/`Edit` is saved when the client sends
  `document_access_changed: true` (the fixed app sends this only when the user really
  picked an option). The flag itself is **not** stored in `config_json`.

**Notice on a protected save.** App 0.31.0 normalizes a stored `Limited Edit` to `Edit`
on load and offers only `Read Only`/`Edit`, so it cannot express "the user really picked
Edit" versus "the user only changed another setting" — both send `Edit` without
`document_access_changed`. When the backend therefore keeps a stored `Limited Edit`
against an unflagged `Edit`, the `save_stage_settings` response carries a Persian notice
so the save is not a silent no-op. The notice is returned as a **top-level `notice` key in
the design payload** (`data.notice`) — which the app reads — and also in `meta.notice` for
meta-aware consumers. The key is **absent** when there is no notice (a genuine explicit
change, a `Read Only` pick, or any non-Limited-Edit stage). `Read Only` is unambiguous and
is applied without a notice. The fixed app (which sends `document_access_changed`) is
unaffected.

Existing stored `Limited Edit` values are preserved exactly; nothing is converted to
`Edit` automatically. No new DocType, field, migration, or permission change.

The existing workflow-template catalog/copy endpoints also accept accessible
non-archived user definitions in the same company. Copies always receive fresh
definition/stage identities, version 1 and Pending configuration; no execution,
history or native workflow link is copied. Original and other-company records
remain untouched. Pending v1 action copies validate the config's structure;
published-form/subject bindings must be explicitly reviewed before activation.

Candidate resolution queries (Role and Unit bases) filter candidates by enabled system users and company/department scope directly in the database query. The assignee cap (default 1000, site config `asoud_workflow_max_assignees`) applies to the final company/form/reference-authorised list, so a common role with more than 200 holders no longer blocks activation; above the cap activation fails with «تعداد مسئولان مجاز این اقدام بیش از حد مجاز است؛ نقش یا واحد را محدودتر کنید.» Overdue escalation (`escalate`) notifies all configured escalation roles (avoiding duplicate notifications) and sorts escalation candidates deterministically. Background deadline processing (`process_workflow_deadlines`) isolates each task in a database savepoint with error logging (`frappe.log_error`), preventing a failure in one task from interrupting execution of others. It walks due tasks in bounded keyset pages (500 per page, ordered by name) rather than one unbounded read, so a single run never loads the whole task table into memory while processing the same set of tasks.
