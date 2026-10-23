# Form builder

`asoud_erp.api.v1.forms` manages company-scoped, versioned presentation forms. It
does not replace ERPNext documents or validation.

Designers (`System Manager`, `HR Manager`, `Accounts Manager`, or `Purchase
Manager`) use `save_form`, `get_validation`, `get_options`, `get_history`, and
`transition`. Only a System Manager may publish, enable, or disable a form.
Every call takes or resolves the form's company and checks company access.

## Schema and revisions

`save_form(company, schema, name?, expected_version?, client_id?)` saves a draft.
Accepted `schema_version` values are 1 and 2; `save_form` always stores version 2,
while unknown versions are rejected with a validation error.
Section, field, table-column, and select-option identifiers are stable ASCII IDs;
select options are `{id, label}` objects. Formula inputs and rule conditions refer
to field IDs, never labels. Payloads, field counts, rows, attachments, and text
lengths are bounded. A published revision is immutable: changing a draft and
publishing creates a new revision, while re-publishing unchanged JSON only enables
the existing revision. Legacy v1 schemas (plain-string options without IDs) are
migrated on read by `get_form`, `list_forms`, and `get_entry` using deterministic
position-based option IDs while keeping database snapshot revisions immutable.
Formula evaluation normalizes Persian/Arabic numerals and the Persian decimal
separator (`٫`) to ASCII Decimal arithmetic with Half-Up rounding. Supported
formula operations include binary operations (`add`, `subtract`, `multiply`,
`divide`, `percent`), table aggregations (`sum`, `average`, `count`,
`sum_product`, `min`, `max`), scalar functions (`min`, `max`, `round`),
conditional branching (`if` with lazy evaluation avoiding evaluation of inactive
branches), standard comparison operators in conditions (`>`, `<`, `=`, `==`, `>=`, `<=`, `!=`),
operator precedence (`*`, `/`, `%` evaluated before `+`, `-`), negative numbers,
parentheses `()`, and nested expressions (`expression` / `chain`).

### Additive presentation and entry-validation keys (schema version 2)

The following optional keys are additive and do not change `schema_version`.
Every field may include `help` (up to 1,000 characters). Sections may include
`description`, `icon`, `color`, and `background_color` (each up to 500 characters),
plus boolean `collapsible` and `collapsed` values. These keys are presentation metadata
and are retained in published revisions.

A `Select` field may set `style` to `dropdown` (the default) or `radio`; other styles
are rejected. A `Date` field may set `after_or_equal` to the key of another Date field
in the same schema. The target cannot refer to itself or participate in a dependency
cycle. When both visible values are supplied, submission rejects an end date before its
referenced date with `after_or_equal_message`, or the default message
`تاریخ پایان نباید قبل از تاریخ شروع باشد.`.

Visible `Table` fields enforce both `required` and `min_rows` during submission. A
missing required row or too-short table is rejected as `حداقل N ردیف لازم است.`.

`default_source` supports `user`, `company`, `today`, `employee`, `department`,
`designation`, and `joining_date`. The last two read the signed-in active Employee in
the form company: designation is the Employee designation and joining date is returned
as ISO (`YYYY-MM-DD`). Missing Employee data produces no default value.

## Record sources and derived fields

`get_link_options(company, source, query, form, filter_field, filter_value, exclude_self=0)`
returns `{name, label}` rows. Sources `Attendance`, `Shift Type`, `Training Event` and `Asset`
are scoped to the signed-in user and enforced again by `submit_form`
(`«رکورد انتخاب‌شده در محدوده مجاز شما نیست.»`):

| source | rows |
|---|---|
| `Attendance` | submitted records of the user's active Employee in the company; `link_filter {field: 'attendance_date', value_field}` allowed |
| `Shift Type` | all Shift Types (v15 has no `disabled` field) |
| `Training Event` | company events with `event_status = Scheduled`, `start_time >= now`, not cancelled |
| `Asset` | submitted company Assets whose `custodian` is the user's Employee |

Without an active Employee, `Attendance` and `Asset` return `[]` with `meta.reason = 'no_employee'`
(submission fails with `«پرونده پرسنلی شما ثبت نشده است.»`). These four sources are read with the
scope filter as the only authorization (Employees have no native read permission on Training Event
and Asset). Labels are Persian with Jalali dates and Persian digits:
Attendance `«۱۴۰۵/۰۷/۲۸ · حاضر · ورود ۰۸:۰۱ · خروج ۱۶:۳۰»` (statuses حاضر, غایب, مرخصی, نیم‌روز,
دورکاری; missing parts are omitted), Shift Type `«<name> · ۰۸:۰۰ تا ۱۶:۰۰»`, Training Event
`«<event_name> · <Jalali start date>»`, Asset `«<asset_name> (<name>)»`.

Sources with fetchable attributes return `extra` on every row: Attendance `in_time, out_time,
attendance_date, status, shift`; Shift Type `start_time, end_time`; Training Event `start_time,
end_time, type, level, training_program`; Asset `asset_name, item_code, location`; Employee
`department, designation, employee_number`. The `extra` values stay raw ISO (the app formats them): datetimes `YYYY-MM-DDTHH:MM:SS`, times `HH:MM:SS`.

Field keys (all validated by `save_form`):

- `exclude_self: true` — Employee Link only. `get_link_options(..., exclude_self=1)` omits the
  user's own Employee (non-designers get a Persian error unless the form really has an Employee Link with `exclude_self`); submission rejects it (`نمی‌توانید خودتان را انتخاب کنید.`).
- `fetch_from: '<link key>.<attribute>'` — the key must be a Link field in the same container with an
  allowed attribute. Submission recomputes the value from the database (Date/Time fields take the
  date/time part) and ignores the client value.
- `not_equal: '<key>'` (+ `not_equal_message`) — Text/Integer/Decimal/Money/Date/Time/Select; checked
  when both values are visible and non-empty. Default message
  `مقدار جدید نباید با مقدار فعلی یکسان باشد.`
- Table column `unique: true` — duplicate non-empty values are rejected: `ردیف تکراری: <label>`.
- `default_source` also accepts `employee_number` (falls back to the Employee name) and `default_shift`.

## Workflow step validation against request values

Fields in a `User Task` or `Approval` stage form may validate the handler's response
against the original request values. These keys are optional and do not change
`schema_version: 2`:

| Key | Allowed on | Meaning |
|---|---|---|
| `max_from_request` | `Integer`, `Decimal`, `Money` | Request field key whose numeric value is the inclusive upper bound. |
| `min_value_exclusive` | `Integer`, `Decimal`, `Money` | Numeric exclusive lower bound. For example, `0` requires a positive value. |
| `reason_required_if_less_than` | `Integer`, `Decimal`, `Money` | Request field key used as the comparison value. When the response is lower, the field named by `reason_field` must contain non-whitespace text. |
| `reason_field` | A field using `reason_required_if_less_than` | Key of a `Text` or `LongText` field in the same step form. |
| `rows_from_request` | top-level `Table` | Request table key. The runtime projects those request rows into this step table and keeps request columns read-only. |
| `max_from_row` | numeric column inside a table using `rows_from_request` | Column key in the corresponding request row whose numeric value is the inclusive upper bound. |

Request references must name fields in the request form schema. A
`rows_from_request` reference must name a request `Table`; its request columns must be
present in the step table with the same keys and compatible types. The step may add
editable response columns. Request-derived rows cannot be added, removed, reordered,
or have their request columns changed. A response row therefore corresponds to the
request row at the same index; the server compares the complete row count and every
projected request value when the task is completed.

The client applies these rules for immediate feedback, but the server repeats every
check in `complete_workflow_task`. Missing or non-numeric referenced values, modified
request rows, a value at or below an exclusive minimum, a value above its request
limit, and a missing reduction reason reject task completion with a Persian validation
message. The stored task response remains independent from the request values and from
responses of other workflow stages.

### Salary advance step example (T2)

The raw request preset contains only request data. A workflow designer may attach this
stage form to the authorized approval stage:

```json
{
  "form_fields": [
    {
      "key": "approved_amount",
      "label": "مبلغ مورد تأیید",
      "type": "Money",
      "required": true,
      "max_from_request": "requested_amount",
      "min_value_exclusive": 0,
      "reason_required_if_less_than": "requested_amount",
      "reason_field": "reduction_reason"
    },
    {
      "key": "reduction_reason",
      "label": "علت کاهش مبلغ",
      "type": "LongText"
    }
  ]
}
```

This records a stage decision only; it does not create a payment, payroll deduction,
or final approval outside the configured workflow.

### Equipment row approval step example (T7)

For a request table `equipment_items` with `item`, `quantity`, and `item_notes`, a
workflow stage can show the submitted rows and collect an approved quantity:

```json
{
  "form_fields": [
    {
      "key": "approved_items",
      "label": "بررسی اقلام تجهیزات",
      "type": "Table",
      "rows_from_request": "equipment_items",
      "columns": [
        {"key": "item", "label": "کالا یا تجهیز", "type": "Short Text", "readonly": true},
        {"key": "quantity", "label": "تعداد درخواستی", "type": "Integer", "readonly": true},
        {"key": "item_notes", "label": "مشخصات تکمیلی", "type": "LongText", "readonly": true},
        {"key": "approved_quantity", "label": "تعداد مورد تأیید", "type": "Integer", "required": true, "min": 0, "max_from_row": "quantity"}
      ]
    }
  ]
}
```

This example constrains each approved quantity to its submitted row. Whether all-zero
approval is allowed and whether a per-row reduction reason is mandatory are workflow
policies and must be configured separately when that policy capability is available;
the example does not perform stock delivery, return, or inventory movement.

## Consumption

Any active employee of the company consumes forms: `list_forms(company)`, `get_form(name)`,
`get_link_options(company, source, ...)`, `upload_file(form, filename, content)`,
`submit_form(name, revision_name, subject, values, request_key)`, `list_my_entries(company)`,
and `get_entry(name)`. Plain employees without an application role can list published forms,
submit request forms (which run through the active ASOUD workflow), read their own entries,
and use the personal calendar API. Users who are not active employees of the company are
refused access.

Designer and lifecycle operations (`save_form`, `transition`, `get_history`, `get_validation`,
`get_options`) remain gated by `DESIGNERS` and `System Manager`. Submission accepts only the
active revision of an enabled, company-scoped form. Entries retain their revision and cannot be
redirected to a draft or foreign revision.

Document forms create an ERPNext draft with native permissions and controllers; employees without
native permission on the target document type are refused by ERPNext. Request forms use the
selected active ASOUD workflow. Neither path auto-submits a native document.

## Execution after approval — contract

## E1 Schema keys (form level and field level, additive, schema_version stays 2)
- Form level, `kind == 'Request'` only: `execution: {"kind": "<executor kind>"}`.
- Field level, both on request-form fields and on workflow step-form fields (`form_fields` in
  stage config): `execution_key: "<parameter name>"`.
- The validator (`save_form` / stage settings) rejects an unknown kind, an `execution_key` that is not a
  parameter of that kind, a required parameter of that kind that no field maps, and two fields with the
  same `execution_key` in the same form.

## E2 Registry (backend)
- Package `asoud_erp/services/form_execution/`.
- `__init__.py` holds `EXECUTORS: dict[str, Executor]`.
- Each executor lives in its own module `form_execution/<kind>.py`, which defines:
  - `KIND = "<kind>"`;
  - `LABEL = "<Persian label for the editor>"`;
  - `PARAMETERS = {"<name>": {"label": "<Persian>", "types": [<allowed field types>], "required": bool}}`;
  - `build(params: dict, ctx: dict) -> dict`: **pure**, no frappe import. It returns the `frappe.get_doc` dict, or raises `ValueError("<Persian reason>")`;
  - `apply(request, params: dict) -> Result`: does the lookups (accounts, approver, defaults), inserts the document, and returns `Result(doctype, name, status, reason)`, the same shape the existing template specs return.
- `ctx` = `{company, employee, user, request_name, today}`. The requester's active Employee in the company is resolved by the framework. If there is none, the result is `Failed` with «پرونده پرسنلی درخواست‌دهنده ثبت نشده است.».
- Registration is one line per executor in `__init__.py` (merge conflicts there are trivial).

## E3 Parameter values
`params` = the request-form values by `execution_key`. They are then overlaid by the values of every
**completed** step task whose stage form has fields with an `execution_key`, in completion order. The
last decision wins (for example, the amount the manager or HR approved overrides the requested amount).
Sensitive masking does not apply here (server side).

## E4 When and how it runs
- The same hook as today: `lifecycle.on_instance_update` → `request_native_documents.dispatch(request)`
  when the instance becomes Completed (approved). For a request without `template_key`, dispatch finds the
  form entry that references the request (`reference_type = 'ASOUD Workflow Request'`,
  `reference_name = request.name`), reads its revision schema, and runs `EXECUTORS[execution.kind]`.
- Same rules as the existing dispatcher:
  - a savepoint;
  - on failure, roll back only the native document and set `native_status = Failed` with a Persian `native_error`; the approval is never undone;
  - `Created`/`Skipped` are never redone;
  - the retry endpoint `workflow_request.create_native_document` works for these requests too.
- Documents are inserted as **drafts (docstatus 0)** unless the HRMS flow requires a submitted document
  to have any effect, and the executor documents why. A rejected or cancelled request never runs.
- `ignore_permissions` only inside `as_administrator` for the insert. The requester's permission is
  already proven by the approved request.


### Editor catalog contract

`asoud_erp.api.v1.forms.execution_kinds()` is a read-only designer endpoint.
It uses the same designer roles as `save_form`; no Employee record is required.
Its response is `success([{kind, label, parameters}], meta)`, where `parameters`
is an object keyed by parameter name and each value has `label`, `types`, and
`required`. An empty registry returns `data: []`. Unauthorized callers receive
403. Catalog labels and validation errors are Persian.

Execution metadata is optional and additive; existing forms retain their behavior.
Invalid mapping errors identify an unknown execution kind, an unknown or duplicate
parameter, a missing required parameter, or an incompatible field type.

E4's reference type is stored in the existing `reference_doctype` field of Form Entry;
no field rename or migration is needed.

### Pure registry and E3 collector

`services.form_execution` defines the structural `Executor` protocol and
`EXECUTORS` registry. `Result` is an alias of the existing template
`NativeResult`, so status, doctype, name and reason keep their existing meanings.
No example executor is registered in production.

`services.form_execution.parameters.collect_parameters(request_fields,
request_values, tasks)` collects unmasked values by `execution_key`. The caller
supplies each task's decoded `values`, stage `fields`, `status`, `completed_on`,
and `name`. Only `Completed` tasks are applied, sorted by completion timestamp
and name as the deterministic tie breaker. Repeated tasks from the same stage
remain separate decisions. A missing value preserves the earlier value; an
explicit null, false, zero or empty string replaces it. Missing or malformed
completion timestamps are rejected with a Persian validation reason. Inputs
are not mutated. This helper performs no database access or document creation.

### Workflow parameter overrides

Step forms use the workflow field vocabulary (`Currency`, `Short Text`,
`Long Text`, `Choice`, `Checkbox`, `Number`) alongside the form-builder names
(`Money`, `Text`, `LongText`, `Select`, `Checkbox`/`Boolean`, `Decimal`).
Equivalent types are matched when presenting and validating parameter choices;
executor metadata may use `Check` for a boolean parameter. Request forms must
map every required parameter. A step may override a subset, since the required
inputs already come from the request form. Duplicate or incompatible mappings
are rejected. When a workflow is attached to an execution form, its steps are
validated against that kind; subsequent stage edits validate against both draft
and active revision forms attached to the workflow.

The dispatcher locks the request and reads `reference_doctype` / `reference_name`
from Form Entry, then reads its immutable revision. Later draft changes do not
change submitted requests. Corrected request values are translated using
`workflow_key` before completed-step responses are overlaid. The requester must
still have an active Employee in the request company. A workflow that completes
during submission is dispatched once more after Form Entry has been saved.
Created and Skipped results are idempotent; rejection and cancellation cannot
execute. Failures preserve approval, roll back native writes to a savepoint,
and record a Persian reason. The existing role- and company-checked retry endpoint
`workflow_request.create_native_document(name)` handles failed form requests.

No schema version change, native field migration or preset update is needed.
Run `bench --site <site> migrate` to add search indexes on Form Entry
`reference_doctype` and `reference_name` for approval lookups.
The registry intentionally has no production example executor.
