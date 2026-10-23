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
