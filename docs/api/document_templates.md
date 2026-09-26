# Document templates (`asoud_erp.api.v1.document_templates`)

A document template («الگوی سند») tells a workflow's **Create Document** system
action how to fill a standard ERPNext document from a request. The document is
inserted through ERPNext's own controller (naming, validation, GL posting are
unchanged); the template stores only the field mapping in `ASOUD Document
Template`. Pure validation and value resolution live in
`services/document_templates.py`.

Roles: System Manager, Accounts Manager and Purchase Manager may read templates;
Finance templates are saved by System/Accounts Managers, Purchase templates by
System/Purchase Managers. Every call is scoped to a company the user can access.

## Supported documents

| Module | `document_type` | ERPNext document | Target fields (required in bold) |
| --- | --- | --- | --- |
| Finance | `Journal Entry` | Journal Entry (voucher type Journal Entry) | **posting_date**, **title**, **amount**, **debit_account**, **credit_account**, cost_center, project, user_remark |
| Purchase | `Material Request` | Material Request (type Purchase) | **transaction_date**, **schedule_date**, **items**, set_warehouse |

Other types listed by `document_template_options` have `enabled: false` and are
rejected on save. A Journal Entry has one debit and one credit row of the same
amount; both rows carry the optional cost center and project. Material Request
items come from a request **Item Table** field (item, qty, UOM as validated
against ERPNext when the request was submitted); without a mapped warehouse the
Stock Settings default warehouse is used.

## Value sources

Each target field maps to `{"source": ..., "value": ...}`:

| `source` | `value` |
| --- | --- |
| `fixed` | Literal text. Placeholders `{{RequestNo}}`, `{{Subject}}`, `{{Requester}}`, `{{Today}}`, `{{Company}}` and `{{<request field key>}}` are replaced at run time. Account, Cost Center, Project and Warehouse values must be usable (non-group, enabled) records of the template company. |
| `request` | A request field: `request_number`, `subject`, `requested_on`, `requester`, `requester_department`, `description`, or a custom field key of the source request type. Amounts need a Number/Currency field, dates a Date field, items an Item Table field. |
| `user` | `initiator`, `initiator_name`, `initiator_department`, `actor` (the user whose decision triggered the action). |
| `organization` | `company`, `default_currency`, `cost_center` (company default). |
| `system` | `today`, `now`, `request_number`, `instance`. |

With `transfer_values: false` on the workflow stage, `request` sources are left
empty (a required one then fails the action).

## Methods

| Method | Type | Parameters | Returns |
| --- | --- | --- | --- |
| `document_template_options` | GET | `company`, `workflow?` | `modules` (with `types`), `fields` per type, `sources` per source (request fields include the request type's custom fields when `workflow` is given), `placeholders` |
| `document_template_link_options` | GET | `company`, `target_type` (Account, Cost Center, Project, Warehouse), `txt?` | `[{value, label}]`, at most 50 |
| `list_document_templates` | GET | `company`, `kind` (`custom` or `ready`), `module?`, `document_type?`, `search?` | Saved templates, or the built-in presets (ready templates have no accounts; open one in the wizard and save it as a custom template) |
| `get_document_template` | GET | `name` | Template |
| `save_document_template` | POST | `company`, `template`, `name?` (update), `source_workflow?`, `preset_key?` | Template |
| `set_document_template_status` | POST | `name`, `status` (`Active`, `Inactive`) | Template |

`template`:

```json
{
  "title": "سند هزینه خرید",
  "module": "Finance",
  "document_type": "Journal Entry",
  "description": "ثبت سند هزینه بر اساس درخواست خرید",
  "mapping": {
    "posting_date": {"source": "system", "value": "today"},
    "title": {"source": "fixed", "value": "هزینه خرید بر اساس درخواست {{RequestNo}}"},
    "amount": {"source": "request", "value": "total_amount"},
    "debit_account": {"source": "fixed", "value": "Purchase Expenses - T"},
    "credit_account": {"source": "fixed", "value": "Creditors - T"}
  },
  "create_as_draft": true,
  "auto_submit": false,
  "reusable": true,
  "manager_note": ""
}
```

`auto_submit: true` submits the document after insert and turns `create_as_draft`
off. A template response adds `name`, `company`, `source_workflow`, `preset_key`,
`status` and `modified`.

## Use in a workflow

Save a System Action stage with `{"action_type": "Create Document",
"document_template": "<name>", "transfer_values": true, "document_remark": "..."}`
through `workflow.save_stage_settings`; the template must be Active and belong to
the workflow's company. See [workflow runtime](../workflow-runtime-v1.md#system-actions)
for execution, rollback and routes. The created document is recorded on the
`System Action Succeeded` activity (`reference_doctype`, `reference_name`).
