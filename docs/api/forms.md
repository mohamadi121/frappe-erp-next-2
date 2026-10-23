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
`designation`, `joining_date`, and `contract_start`. The employee-backed values read the
signed-in active Employee in the form company. `contract_start` returns the start date of
the employee's current native Employment Contract; only when no current contract exists it
falls back to `Employee.date_of_joining`. Dates are returned as ISO (`YYYY-MM-DD`). Missing
Employee data produces no default value. A field using `contract_start` must label the fallback
explicitly, for example `شروع دوره همکاری (در نبود قرارداد: تاریخ شروع به کار)`.

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
end_time, type, level, training_program, course, location, trainer, employee_count`; Asset `asset_name, item_code, location`; Employee
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
- A read-only `Display` field may set `compare: {current: '<field key>', proposed: '<field key>'}`.
  Both referenced fields must be in the same container. The runtime renders
  `ساعت ثبت‌شده <current> ← پیشنهادی <proposed>` and uses `ثبت نشده` for either empty side.
  Comparison fields are presentation-only and are not stored as submitted values.
- A `Time` field may set `next_day_allowed: true`. The runtime then shows a `روز بعد` toggle and
  submits its boolean value as `<field key>__next_day`. This companion key is accepted only for
  such a Time field. Server validation combines the Time with the request's attendance Date;
  when selected, one day is added before chronological comparisons, so a shift crossing midnight
  is not treated as an earlier same-day time.

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
