# ASOUD ERP API v1 — conventions

The Flutter client talks to this app only through whitelisted methods under
`asoud_erp.api.v1.*`. Each module wraps standard ERPNext/HRMS DocTypes and
controller functions; it adds Iranian localization, company scoping, and a stable
contract, never a parallel ledger or master (see `AGENTS.md`).

Module references: [module map](../backend-roadmap.md) ·
[dashboard](dashboard.md) · [selling](selling.md) · [sales pipeline](sales_orders.md) · [payments](payments.md) ·
[stock](stock.md) · [buying](buying.md) · [HR self-service](hr_self_service.md) ·
[projects](projects.md) ·
[support](support.md) · [request types](../workflow-runtime-v1.md#request-types)

## Calling a method

```
POST /api/method/asoud_erp.api.v1.<module>.<method>
Content-Type: application/json
Cookie: sid=...            (or Authorization: token <api_key>:<api_secret>)

{"company": "Tabaan", ...}
```

Read methods also accept `GET` with query parameters. List and object parameters
(`items`, `references`, ...) may be sent as JSON values or JSON-encoded strings.

## Response envelope

Frappe wraps the return value in `message`:

```json
{"message": {"ok": true, "data": {...}, "meta": {"api_version": "v1"}}}
```

`meta` may add `total`, `limit_start`, and `limit_page_length` for lists.

## Errors

Validation and permission failures are raised with `frappe.throw` and reach the
client as standard Frappe errors, never as `ok: true`:

| HTTP | `exc_type` | Meaning for the client |
| --- | --- | --- |
| 403 | `PermissionError` | The user's ERPNext roles or company access do not allow it. Do not retry, do not fall back to cache. |
| 417 | `ValidationError` (and subclasses) | Input was rejected; `_server_messages` carries the translated message to show. |
| 404 | `DoesNotExistError` | The referenced record does not exist or is hidden. |
| 5xx / network | — | Transient; the client may keep the mutation in its outbox and retry. |

`sync.execute_mutation` returns `{"ok": false, "error": {"code", "message"}}`
only for its own protocol errors (`INVALID_REQUEST_KEY`, `METHOD_NOT_ALLOWED`,
`REQUEST_IN_PROGRESS`).

## Authorization

- ERPNext roles and DocType permissions are the authority. Modules check the
  roles listed in each doc with `services.erp_documents.require_roles` (unlike
  `frappe.only_for`, it is also enforced under tests) and create/submit
  documents *without* `ignore_permissions`, so ERPNext's own permission rules,
  User Permissions and workflow states still apply.
- `company` is required on company-scoped methods and is checked with
  `services.request_access.require_company`: managers need read access to the
  Company; everyone else needs an active Employee in it.
- Self-service methods (leave, check-in, advances, issues) always act for the
  Employee linked to the session user; an `employee` argument is never accepted.

## Idempotent writes (offline outbox)

Every mutating method is named with a prefix from
`sync._MUTATION_PREFIXES` (`create_`, `submit_`, `cancel_`, ...). To make a write
safe to retry, call it through:

```
POST /api/method/asoud_erp.api.v1.sync.execute_mutation
{"request_key": "<uuid from the client outbox>",
 "target_method": "asoud_erp.api.v1.selling.create_sales_invoice",
 "payload": {...same arguments...}}
```

The first call runs the method and stores its envelope in `ASOUD API Request`;
later calls with the same key by the same user return the stored envelope. A key
already used by another user is rejected with `INVALID_REQUEST_KEY`.

## Dates, numbers and money

- Dates are ISO `YYYY-MM-DD` (Gregorian) on the wire; the client converts to and
  from Jalali for display.
- Amounts are numbers in the company currency unless a field is named `*_currency`.
- Documents keep ERPNext `docstatus`: `0` draft, `1` submitted, `2` cancelled.
  Lists also return ERPNext's own `status` text (e.g. `Unpaid`, `Paid`, `Overdue`).

## Tests

- `asoud_erp/tests/` — pure unit tests, run anywhere:
  `uvx --with pytest pytest -q asoud_erp/tests`.
- `asoud_erp/integration_tests/` (API modules) and `asoud_erp/asoud_erp/doctype/*/test_*.py`
  (DocTypes) — Frappe integration tests on a site with ERPNext and HRMS, one module at a time:
  `bench --site <test-site> run-tests --module asoud_erp.integration_tests.test_selling_payments`.
  See [the roadmap](../backend-roadmap.md#development-bench) for creating such a site.
