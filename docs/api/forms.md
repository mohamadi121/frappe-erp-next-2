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
separator (`٫`) to ASCII Decimal arithmetic with Half-Up rounding.

## Consumption

`list_forms(company)`, `get_form(name)`, `get_link_options(company, source, ...)`,
`upload_file(form, filename, content)`, `submit_form(name, revision_name, subject,
values, request_key)`, `list_my_entries(company)`, and `get_entry(name)` are for
the current user. Submission accepts only the active revision of an enabled,
company-scoped form. Entries retain their revision and cannot be redirected to a
draft or a revision belonging to another form.

Document forms create an ERPNext draft with native permissions and controllers;
request forms use the selected active ASOUD workflow. Neither path auto-submits a
native document.
