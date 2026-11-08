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
When a condition fails at runtime, the failure is written to the Error Log with
the workflow instance as its reference and a deferred insert, so the row survives
the request rollback and the admin can find why the condition failed.

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
- `currency`: the ISO currency code for a form-builder `Money` field, taken
  from the workflow company's default currency. A native `Currency` field's
  currency is per document (its `options` name another field), so it is left
  `null`. `null` for every other field.

`field_type` is unchanged for every existing entry; these keys are additive.

The System source now exposes, in addition to `started_by` and `started_on`:

- `requester_unit` (Text, `value_source: department`, `link_doctype: Department`):
  the requester's organisational unit, resolved at evaluation time from the
  requester's Employee `department`. If the requester has no Employee or the
  Employee has no department, evaluation raises a Persian error instead of
  guessing.

`started_by` keeps `field_type: Text` and its stored `source_field` so existing
configs keep working, and gains `value_source: user` and `link_doctype: User`.
There is no "subject person" System field: the instance has no person field
other than the requester, so none is invented. There is also no instance-status
System field: a condition is evaluated only while the instance is Running, so
`instance.status` is always `Running` at that moment and could never route
differently; a native document's own status field (if it exists and is allowed)
already appears under the Original source.

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

## Condition test

`POST asoud_erp.api.v1.workflow.test_workflow_condition(definition, stage, config, samples)`
evaluates a condition with caller-supplied sample values so a designer can check a rule
before saving or activating it. It is read-only: it creates no documents, tasks,
transitions, activities, logs or notifications, and runs inside a savepoint that is
rolled back as a guard.

Arguments:
- `definition`: the workflow definition name.
- `stage`: the Condition stage name (must belong to `definition`).
- `config`: the v2 condition config (object or JSON string), the same shape `save_stage_settings`
  accepts. It is parsed with `normalize_group` and its bindings checked with `catalog` +
  `validate_bindings`, exactly as on save.
- `samples`: an object (or JSON string) mapping each condition row `id` to a sample value.

Roles and company scope are the same as `workflow_condition_fields`:
`System Manager`, `Accounts Manager`, `HR Manager`, plus the definition's company scope.

Response `data`:
- `result`: `true | false | null`. `null` when any row errored.
- `rows`: one entry per condition row, in config order: `{id, result, error}`. `result` is
  `true | false | null` and `error` is a Persian string or `null`.

Per-row evaluation uses the same `evaluate_group` logic as the runtime (each row is evaluated
on a one-row config, then the full config is evaluated for the final result), so the test
outcome can never differ from a real run. A row whose operator needs a value but has no
sample gets `result: null` and the error «برای این شرط مقدار نمونه وارد نشده است.».
A `ValueError` from `normalize_group` or `validate_bindings` is returned as a Persian
validation error.

The runtime Condition stage records the chosen output in the Activity comment for both
versions, e.g. «نتیجه: برقرار است؛ مسیر: <destination stage title>» or «نتیجه: برقرار
نیست؛ مسیر: <destination stage title>». The legacy comment no longer writes the compared
field value, so a condition on a sensitive field (for example a salary) never leaks it.
