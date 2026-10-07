# Request templates — `asoud_erp.api.v1.workflow_request`

Purchase (`purchase`), supply (`supply`) and leave (`leave`) requests run on the generic
request engine. A template is described in code (`services/request_templates/`), seeded
into one `ASOUD Workflow Definition` per company, and approved through the usual
workflow stages (form, direct-manager approval, end). Custom request types use the same
endpoints with `template_key = ""`.

Envelope: `{"ok": true, "data": ..., "meta": {"api_version": "v1", ...}}`. Business errors
are `frappe.throw` with a code in `_server_messages[].title` (see the table at the end).

## Endpoints

| Method | HTTP | Offline name rule | Purpose |
| --- | --- | --- | --- |
| `request_options(company)` | GET | read | submittable types with fields, resolved defaults, `settings`, `attachments` limits |
| `request_field_options(company, field_type, txt?, item_code?, scope?, limit_start?, limit_page_length≤50)` | GET | read | choices for a field |
| `create_request(company, template_key? \| workflow_definition?, request_id, subject?, values, priority?, required_by?, project?, department?, attachments?)` | POST | `create_` (repository outbox) | create and submit |
| `update_request(name, subject?, values, attachments?, remove_attachments?)` | POST | `update_` | edit while nobody else has acted |
| `cancel_request(name, reason?)` | POST | `cancel_` | withdraw while in progress |
| `list_my_requests(company?, template_key?, status_group?, search?, priority?, date_from?, date_to?, limit_start?, limit_page_length≤100)` | GET | read | the caller's own requests |
| `get_request(name)` | GET | read | detail (owner, System/HR Manager or a task assignee) |
| `list_request_comments(name, limit_start?, limit_page_length≤100)` | GET | read | free comments, oldest first |
| `add_request_comment(name, content)` | POST | `add_` | add a comment (1–2000 characters, HTML stripped) |
| `get_attachment(name, thumbnail?)` | GET | read | one file; `thumbnail=1` scales an image to at most 256 px |
| `create_native_document(name)` | POST | `create_` | retry a failed native document (System, HR or Purchase Manager) |

`create_request` takes `workflow_definition` or `template_key`; the key wins and resolves
the company's active definition (`TEMPLATE_NOT_AVAILABLE` otherwise). `request_id` is the
idempotency key (8–100 characters): a repeat with the same payload returns the same
request, a different payload fails with `REQUEST_ID_CONFLICT`. For a system template the
priority, required-by date, project, department and (for generated subjects) the subject
come from the template; client values for them are ignored. The positional argument order
is `company, workflow_definition, subject, request_id, ...` (unchanged); clients call by
name.

### Companies and scoping

Every endpoint that takes `company` calls `request_access.require_company`; name-based
endpoints check `request_permission` on the request. `list_my_requests` returns only the
caller's own requests. `native.error` of a request is shown to System and HR Managers
only. No endpoint returns another company's data.

## Form fields

Besides the scalar types: `Time` (`HH:MM`, 24 hour), `System Select` (needs `source`),
`Auto` (server computed, never sent by a client, never stored except the leave
`duration`). Field attributes: `visible_when` (`{"field", "equals"}` or `{"field", "in"}`;
a hidden field is stored as `null` and not required), `option_labels` and `widget` for
`Choice`, `default_source` (`session_user`, `employee_department`, `employee_branch`,
`today`), `editable`, `min_date` (`"today"`), `max_length`, `required_by_setting`
(`request_cost_center_required`) and, for `Item Table`, `row_options`
(`item_scope`, `note`, `attachment`, `min_rows`, `max_rows`).

`request_options` replaces `default_source` with `default_value`/`default_label` for the
caller and resolves `required_by_setting` from the Company. The requester field
(`editable: false`, `default_source: session_user`) is filled with the session user; any
other value fails with `REQUESTER_MISMATCH`.

System Select sources (`request_field_options.field_type`): `cost_center` (Cost Center),
`project` (Project), `warehouse` (Warehouse), `branch` (Branch), `supplier` (Supplier),
`leave_type` (Leave Type, categorised only), `delivery_location` (`<kind>:<name>` with
kind `warehouse`, `branch` or `department`). Values are validated against the record,
the company (where scoped) and the disabled flag.

Item rows: input `item_code`, `qty`, `uom`, `description` (≤ 1000), `note` (≤ 500) and
`attachment`; derived `item_name`, `stock_uom`, `conversion_factor`, `stock_qty`,
`is_stock_item`. `item_scope: "purchase"` limits rows to purchase items. The detail adds
`attachment_ref` to a row with a file; it is not stored and is ignored if sent back.

## Attachments

Files travel inline: `attachments: [{"filename", "content_base64", "ref"?}]`. A form value
refers to an upload as `attachment:<ref>` (or `attachment:<filename>` without `ref`).
With `ref`, duplicate file names are fine. Limits: 10 files, 10 MB each, 25 MB in total,
extensions `pdf png jpg jpeg xls xlsx doc docx` (a template may narrow them with its
`attachments.extensions`). Stored entries are
`{name, filename, file_url, size, content_type, is_image, scope}` with `scope` `general`,
`field:<key>` or `row:<field_key>:<index>`. `update_request` adds files, removes files by
File name (values pointing at them are cleared; a required attachment field cannot lose
its file) and keeps an attachment key that is missing from `values`. Re-sending the same
new file after a replay reuses the stored one.

## Status model

`status_key` is stored on the request and mirrored by the `ASOUD Workflow Instance`
`on_update` hook (`request_templates.lifecycle`) from the pure
`services/request_status.py`:

| `status_key` | Label | Tab | When |
| --- | --- | --- | --- |
| `submitted` | ارسال شده | `pending` | Running, no non-form task acted yet |
| `in_review` | در حال بررسی | `pending` | Running, a non-form task was completed or rejected |
| `returned` | برگشت برای اصلاح | `pending` | Running and back at the form stage after it was submitted |
| `failed` | نیازمند بررسی | `pending` | instance `Failed` |
| `approved` | تأیید شده | `approved` | instance `Completed` |
| `rejected` | رد شده | `rejected` | instance `Rejected` |
| `cancelled` | لغو شده | — | instance `Cancelled` |
| `draft` | پیش‌نویس | — | legacy `Draft` without an instance |

`status_label` is the custom `display_status` while the instance runs. `list_my_requests`
filters `status_group` on the stored key; `meta.counts` (`all`, `pending`, `approved`,
`rejected`) ignores `status_group` but respects the other filters. `date_from` and
`date_to` bound the request date (creation). `search` is a `LIKE` on `search_text`
(number, subject, requester, department, project, item codes and names).
Each list row also carries `summary` (template specific, with `rejection_reason`),
`item_count`, `attachment_count` and `native_status`; `values` and `attachments` come from
`get_request`.

## Numbering

`PREFIX-<Jalali year>-<4 digits>` from `tabSeries` (keys `PR-1405-`, `SP-1405-`, `LV-1405-`),
global across companies, new series each Nowruz. Custom types keep `REQ-#####` on the same
`REQ-` series as before. Existing numbers are never renamed.

## Seeding

`seed.ensure_system_templates(company?)` runs after every migrate and when a Company is
inserted. For each spec and company it creates the definition `SYS-<KEY>-<ABBR>` with the
stages Start → Form (requester) → Approval (direct manager) → End, linked to the shared
inactive workflow `ASOUD-SYSTEM-REQUEST-NATIVE`. A second run changes nothing. When a
spec's `version` is higher, only the form fields and `template_version` are rewritten.
`save_stage_settings` refuses the form stage of a system template.

## Post-approval native documents

When a template request's instance becomes `Completed`, the hook calls
`request_native_documents.dispatch(request)`, which creates the native document
(Material Request, Leave Application or Leave Ledger Entry) and stores
`native_doctype`, `native_name`, `native_status` and `native_error`. A failure leaves the
request `approved` with `native_status = "Failed"`; `create_native_document` retries it.
Anything `dispatch` does not handle itself is caught by the hook, rolled back to a
savepoint and recorded as `Failed`.

## Error codes

`TEMPLATE_NOT_AVAILABLE`, `REQUEST_ID_CONFLICT`, `REQUEST_NOT_EDITABLE`,
`REQUESTER_MISMATCH`, `EMPLOYEE_NOT_FOUND`, `COST_CENTER_REQUIRED`, `DATE_IN_PAST`,
`INVALID_DATE_RANGE`, `INVALID_TIME_RANGE`, `LEAVE_ALL_HOLIDAYS`, `HOURLY_ON_HOLIDAY`,
`HOURLY_EXCEEDS_DAY`, `LEAVE_OVERLAP`, `INSUFFICIENT_LEAVE_BALANCE`,
`DELIVERY_NOT_WAREHOUSE`, `ITEM_NOT_STOCKABLE`, `ATTACHMENT_INVALID`, `EMPTY_COMMENT`,
`NATIVE_NOT_RETRYABLE`. The engine raises the first seven that concern forms, plus the
attachment, comment and retry codes; the template specs raise the rest. Messages are
Persian.

## For template authors

`services/request_templates/base.py` defines `TemplateSpec`, `NativeResult`,
`ValidationContext`, `register`, `get`, `all_specs`, `throw_error(code)` and
`validate_form_stage_response`. A spec module either calls `register(SPEC)` or exposes a
module-level `SPEC`. `workflow_request.effective_values(name)` returns the request values
overlaid with the completed form task responses. The engine passes `request_row` to
`summarize` with `rejection_reason` and `_labels` (`department`, `project`, `branch` name
→ label maps built in one query each).
