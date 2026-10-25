# Organization units and import

`asoud_erp.api.v1.organization` manages native ERPNext `Department` units and the
organization chart preview/import. Units are the native `Department` DocType: this
module adds company scoping and Persian messages, and never creates a parallel unit
store. Positions stay in the company's `ASOUD Organization Chart` JSON, which
references units by native `department_id`.

Every method below checks the company first (`Company` read permission plus the
roles listed). Frappe errors follow the [API conventions](README.md#errors):
`PermissionError` is 403, `ValidationError` and its subclasses (including
`TimestampMismatchError`) are 417, and a missing record is 404.

## Roles

| Role group | Methods |
| --- | --- |
| Read: `System Manager`, `HR Manager`, `HR User` | `list_units`, `employee_photo` |
| Write: `System Manager`, `HR Manager` | `save_unit`, `delete_unit`, `preview_import`, `apply_import` |

Each write also needs the matching native `Department` or `Employee` permission
for the user. Users without the roles get `PermissionError` with message
`Not permitted`.

## list_units

`GET` or `POST` `asoud_erp.api.v1.organization.list_units(company)`

Returns the company's units ordered by tree position, and whether the caller may
manage them.

```json
{"ok": true, "data": {"units": [
  {"name": "...", "department_name": "...", "parent_department": null,
   "is_group": 1, "disabled": 0, "modified": "2026-10-20 10:00:00"}
], "can_manage": true}}
```

`can_manage` is true only for `System Manager` or `HR Manager` with
`Department` write permission.

## save_unit

`POST` `save_unit(company, payload)`

`payload` is an object or a JSON string:

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | no | Existing unit. Omit to create. |
| `modified` | yes when `name` is set | Last `modified` value from `list_units`. |
| `title` | yes | Display title (`department_name`), trimmed. |
| `parent` | no | Parent unit `name` of the same company. |
| `is_group` | no | `1` lets the unit have sub-units. |

Returns `{"name": "...", "modified": "..."}`.

Errors:

- `اطلاعات واحد معتبر نیست.`: payload is not an object.
- `TimestampMismatchError` (417): `modified` is stale; reload the units.
- `عنوان واحد الزامی است.`: empty title.
- Parent checks: circular hierarchy, parent missing, disabled, or in another company.
- `ابتدا گزینه پذیرش زیرواحد را در واحد بالادستی فعال کنید.`: parent is not a group.
- `واحد دارای زیرواحد باید پذیرش زیرواحد داشته باشد.`: unit has children but is not a group.
- Title change while legacy chart rows match this unit by title only
  (`واحد با جایگاه‌های قدیمی بدون شناسه مرتبط است…`). Connect those positions to the
  unit in the organization chart first, then rename.

A title change of a unit that positions reference by `department_id` is allowed;
those positions show the new title on the next read.

## delete_unit

`POST` `delete_unit(company, name, modified)`

Deletes a native `Department`. Requires `Department` delete permission and a
matching `modified` value.

Returns `{"deleted": "<name>"}`. Errors:

- `TimestampMismatchError` (417): unit changed since it was loaded.
- `واحد دارای جایگاه سازمانی است؛ حذف مجاز نیست.`: a position (by `department_id`
  or by legacy title) references the unit, including historical records.
- `واحد دارای زیرواحد است؛ حذف مجاز نیست.`: sub-units exist.

A Frappe-level refusal (for example a native link) is returned unchanged.

## employee_photo

## preview_delete_position

`GET` or `POST` `preview_delete_position(company, code, revision)` is read-only.
Requires `System Manager` or `HR Manager`, Company read permission, and write
permission on the existing `ASOUD Organization Chart`. It checks the current
server revision and exact position code. Missing positions fail with
`جایگاه موردنظر در ساختار فعلی وجود ندارد.`; stale revisions fail with
`ساختار تغییر کرده است؛ دوباره بارگذاری کنید.` (TimestampMismatchError).

Returns `{"can_delete": false, "blockers": ["..."], "counts":
{"occupants": 1, "subordinates": 0, "history": 1}, "revision": 7}`.
Counts cover active occupants (including legacy employee), direct reporting
positions and server-owned assignment history. These are the position references
supported by the existing chart model; native workflow documents do not link to
individual JSON position codes. This endpoint does not delete or cascade.
Deletion still uses `save_chart`, under the company lock and revision check;
the controller rechecks the same blockers against the previous server chart.
Move/reparent children in a separate saved operation before deleting their parent.

## preview_delete_unit

`GET` or `POST` `preview_delete_unit(company, name, modified)` requires the write
role group and native Department delete permission. Returns
`{"can_delete": false, "blockers": ["..."], "modified": "..."}`.
Checks child units, position references and native static/dynamic document links.
Stale modified values fail; `delete_unit` repeats checks under the company lock.

## employee_photo

`GET` `employee_photo(company, employee)`

`employee` is `employee:<Employee name>` or the bare name. Returns a JPEG thumbnail
no larger than 160 px, base64-encoded, from the Employee's private `File`:

```json
{"ok": true, "data": {"content": "/9j/4AAQ..."}}
```

`content` is `null` when the Employee has no image, the file is not readable, or
the image cannot be decoded. Errors: the Employee must belong to `company`
(`پرسنل متعلق به این شرکت نیست.`, 403) and the caller needs read permission on the
Employee and its `File`. Remote image URLs are never fetched.

## preview_import

`POST` `preview_import(company, payload)`

Dry run of an XLSX-derived import. Nothing is written. `payload` contains
`units` (rows with `code`, `title`, `parent`, optional `name` to match an existing
native unit) and `rows` (positions with `code`, `title`, `department_id` or a unit
alias from `units`, `capacity`, `occupants`, `duties`). Optional `template` is
accepted only for an empty company chart.

Returns `{"units": [...], "rows": [...], "additions": [...], "revision": <int>}`.
Keep `revision`: `apply_import` requires it. Errors include:

- `ساختار فایل ورود معتبر نیست.`: `units` is not a list.
- `ساختار موجود است؛ قالب جدید روی آن اعمال نمی‌شود.`: a template was sent to a
  non-empty chart.
- `واحد تکراری است…`: a title matches an existing unit without an explicit `name`.
- `واحد جایگاه غیرفعال است.`: a position references a disabled unit.
- `پرسنل … در بیش از یک جایگاه منتصب شده است.`: one Employee in two positions
  (see [organization assignment rules](../organization-v2-audit.md)).

## apply_import

`POST` `apply_import(company, payload, revision)`

Creates the units and then saves the chart in one transaction. `revision` must equal
the value returned by `preview_import`; otherwise nothing is written and the call
fails with `ساختار پس از پیش‌نمایش تغییر کرده است.` (`TimestampMismatchError`, 417).
The company is locked for the whole call. Any failure, including a rejected chart
save, rolls back the new units and the chart write.

Returns the same envelope as a chart save, with `data` set to `{"rows": [...], "revision": <int>, "warnings": [...]}`.
Unit names created by the import must equal the names shown in the preview; otherwise
the import stops with `نام‌گذاری سفارشی واحد با پیش‌نمایش متفاوت است؛ ورود متوقف شد.`
