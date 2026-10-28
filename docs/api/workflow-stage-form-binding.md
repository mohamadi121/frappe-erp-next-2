# User-task form binding (no new request or document)

> SUPERSEDED DRAFT — NOT SHIPPED. The owner clarified that selecting a request
> or document selects the submitted record type whose workflow should run, not
> a schema to fill out again inside a task. The design below does not implement
> that requirement. No `form_binding` runtime or `stage_binding_version` capability
> is released with the template-copy changes. Preserve legacy runtime behavior
> until a submission-trigger contract, permissions and record linkage are complete.

Additive user-task config: `form_binding: {form: string, revision: string}`.
`workflow.save_stage_settings` verifies a published, enabled ASOUD Form and its
active immutable revision in the workflow's company, with the existing form access
rules. Server injects the trusted frozen schema as `bound_form_schema` and the form
title/kind; client-supplied schema is ignored. Binding forces `task_purpose=Existing`
and empty legacy `form_fields`; it never creates or posts a request/document.
Missing binding leaves old stages unchanged, including their old output behavior.

The task-detail config includes this frozen schema and source identity. Assigned
users must also satisfy the frozen form access rules. The same form-builder renderer
and server `form_schema.validate_values` handle bound responses, including tables,
calculations, links and private files. Stage draft keys are limited to schema keys.
Required checks apply on completion; draft persistence does not claim validity.
Previous-task data masks sensitive fields. No form publication, execution intent,
native posting or form-entry submission is triggered by binding or completion.

Picker uses existing `forms.list_forms(company, kind, manage=1)` and
`forms.get_form(name, manage=0)`; only published forms may be bound. Built-in defaults
use existing `forms.open_builtin` to materialize their existing trusted identity;
no request/document transaction is created. Request/Document tabs and module/search
filters affect selection only. Unsupported/unpublished or forbidden forms fail
explicitly, preserving previous selection. No schema migration is required.
`forms.get_form` adds `stage_binding_version: 1`; the picker requires it, so an
older backend cannot silently discard an unsupported binding on stage save.

Deploy the matching backend before Flutter. Existing workflow stages remain on
their legacy path unless a binding is explicitly chosen. Tests are not executed
at the user's request; site/device verification remains required.
