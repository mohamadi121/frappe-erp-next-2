# Condition stages, version 2

The existing `workflow_condition_fields(definition, stage)` and
`save_stage_settings(definition, stage, config)` endpoints remain authoritative.
Existing single-condition configs without `condition_version` retain their
existing evaluation semantics. There are no new tables or parallel engine.

The new optional `condition_version: 2` config contains `title`, `description`,
`combine: All | Any` and `conditions` (1–50 rows; a bounded evaluation budget).
Each row has a unique stable `id`, `source_kind: Original | Stage | System`,
`source_field`, optional `source_stage` (required for Stage), `field_type:
Number | Text | Date | Select`, `operator`, and `value`/`value_to` when applicable.
Operators: Equals, Not Equals, Greater Than, Greater Or Equal, Less Than,
Less Or Equal, Between, Contains, Not Contains, Is Empty, Is Set.
Operators are restricted by the server-owned field type. Decimal comparisons
are exact; numeric/date Between includes both endpoints. Empty comparisons need
no value. Invalid ranges, missing fields or missing prior-stage data are errors,
not the False outcome. All predicates are evaluated before combining results.

The existing fields response adds `condition_fields_v2`, an array of allowed
field bindings with source_kind/source_stage, source_field, label, field_type,
options for Select, and stage_title for prior actions. Original uses the pinned
source form (or existing native document metadata); Stage uses a prior User Task
guaranteed on every graph path to this condition. System exposes only actual
instance fields. Hidden/sensitive fields are excluded. Save and runtime recheck
the catalog, not client-supplied field types or options.

Both boolean outputs remain in existing native Workflow Transition rows with
`condition_json.result: true | false`. Destination selection is Canvas-only.
Draft settings may be saved without exits; activation requires exactly one of
each output via existing graph validation. Condition v2 updates are rejected
while the definition is active or instances of that definition are running. Use an independent definition
copy for redesign; existing execution history is never rewritten.

Errors are Persian validation messages, identifying the row where possible.
The existing company scope and designer/native document permissions apply.
The existing `connect_workflow_stages` accepts `{result: true|false}` for a
Condition source, updates the existing output transition in place, and removes
only that connection when `to_stage` is empty. It never deletes the destination.
Evaluation does not execute code or SQL supplied by users and does not create
documents or human tasks during settings validation. No migration is needed
because config JSON is additive; deploy client and backend together.

Correction policy selected for the separate approval work: preserve the original
submitted entry and create an explicitly linked amended version within the same
workflow instance, using native document amendment where applicable. This
condition contract does not claim that amendment workflow is implemented.
