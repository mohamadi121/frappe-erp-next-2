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

## Field catalog metadata

Every `condition_fields_v2` entry may carry three optional keys so the app can
render a picker that stores the stable id and show the right unit:

- `value_source`: `user`, `employee` or `department` for a reference field the
  app can turn into a picker; `null` otherwise.
- `link_doctype`: the linked DocType of a reference field (`User`, `Employee`,
  `Department`, …); `null` for non-reference fields.
- `currency`: the ISO currency code for an amount field (native `Currency` or
  form-builder `Money`), taken from the workflow company's default currency;
  `null` for every other field.

`field_type` is unchanged for every existing entry; these keys are additive.

The System source now exposes, in addition to `started_by` and `started_on`:

- `requester_unit` (Text, `value_source: department`, `link_doctype: Department`):
  the requester's organisational unit, resolved at evaluation time from the
  requester's Employee `department`. If the requester has no Employee or the
  Employee has no department, evaluation raises a Persian error instead of
  guessing.
- `status` (Select): the workflow instance status, with the real option values
  `Running`, `Completed`, `Rejected`, `Cancelled`, `Failed` and their Persian
  labels.

`started_by` keeps `field_type: Text` and its stored `source_field` so existing
configs keep working, and gains `value_source: user` and `link_doctype: User`.
There is no "subject person" System field: the instance has no person field
other than the requester, so none is invented.

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
