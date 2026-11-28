# Error contract

Two channels carry errors to the client. Both are already on the wire; this page
documents the stable machine-readable codes.

## 1. The envelope channel (`ok: false`)

Methods that return a dict (the offline outbox, `sync.execute_mutation`) answer with
the `ok: false` envelope:

```
{"ok": false, "error": {"code": "...", "message": "..."}, "meta": {"api_version": "v1"}}
```

`failure(code, message, *, retryable=None, field=None, hint=None)` builds it. The
three extra keys are **additive**: each appears in `error` only when the caller
passes it, so the `ok/data/meta/error` envelope and existing callers are unchanged.

| key | meaning |
| --- | --- |
| `code` | stable machine code (e.g. `METHOD_NOT_ALLOWED`, `REQUEST_IN_PROGRESS`). |
| `message` | the Persian sentence to show. |
| `retryable` | `true`/`false`, **derived only from the status class** (429 / 5xx / `REQUEST_IN_PROGRESS`), never from the message text. Absent when the caller does not decide. |
| `field` | the offending field, when the error is about one input. |
| `hint` | a short Persian hint for the fix. |

The sync protocol codes are `INVALID_REQUEST_KEY`, `METHOD_NOT_ALLOWED`,
`REQUEST_KEY_CONFLICT`, `REQUEST_IN_PROGRESS`, `INVALID_RESPONSE`.

## 2. The throw channel (`frappe.throw`)

Most methods raise `frappe.throw(...)`; the client sees a standard Frappe error. The
stable contract is the triple **(HTTP status, `exc_type`, `title`)**:

| HTTP | `exc_type` | `title` | retryable |
| --- | --- | --- | --- |
| 403 | `PermissionError` | `ROLE_REQUIRED` (no role) / `COMPANY_ACCESS_DENIED` (no company access) / none (document permission) | no |
| 417 | `ValidationError` (and subclasses) | a business code where one is defined, else none | no |
| 404 | `DoesNotExistError` | — | no |
| 429 | `RateLimit` | — | yes |
| 5xx | — | — | yes (keep the mutation in the outbox) |

`title` is a machine code carried in `_server_messages[0].title`; the Flutter client
already parses it into `ApiException.code` and treats unknown titles as inert. The two
shared guards now always set a stable title:

* `services/erp_documents.require_roles` → `ROLE_REQUIRED`
* `services/request_access.require_company` → `COMPANY_ACCESS_DENIED`

The Persian `message` is still the user-facing text; `title` is the stable code. A
client that does not read `title` is unaffected.
