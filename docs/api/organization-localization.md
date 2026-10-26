# Persian organization labels

Additive presentation-only localization for the existing organization API.
Native Department identifiers, `department_name`, chart `title`, `department`,
parent links, revisions and assignments are never renamed by a read.

`organization.list_units` adds `display_name` to each unit, derived by an exact,
case-insensitive known-standard-title dictionary. Chart snapshots (`get_chart`,
`save_chart`, `apply_import`) add `display_title` and `department_display_name`
to each position. `preview_import` adds the same display fields to `rows` and
`additions`, plus `display_title` to proposed units. Original fields stay intact.
Presentation fields are not authoritative input and are not stored in chart JSON.

Unknown/custom titles and existing Persian names stay unchanged. No fuzzy,
substring, company-suffix stripping or machine translation is performed. The
Flutter fallback dictionary is identical to the backend dictionary, for cached
records and older servers. Forms retain raw titles unless the user explicitly
edits the title; changing capacity or parent must not silently rename a record.
Built-in ASOUD templates continue to create actual Persian titles using existing
native import endpoints, not English records with translated IDs.

This is not a data migration or a replacement backend. No DocType fields or
permissions change; no bench migration is needed for this localization change.
Release the backend and app together. A server with unrelated pending schema
changes may still require their migrations.
