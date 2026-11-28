# In-product assistant (LLM layer) — design

This is the LLM-facing layer for the in-product assistant, built on the private
**Gemloy** "Gemma Messages API" (Anthropic wire format). It is **not** an API
endpoint yet: there is no `api/v1` module and no live call. The layer is pure
service code driven by tests with a fake transport and a fake executor. A
whitelisted endpoint that wires the orchestrator to a signed-in session is a
later step and must ship together with the matching app call.

## Files

| File | Role |
| --- | --- |
| `asoud_erp/services/ai/gemloy_client.py` | Small stdlib (`urllib`) client for the Gemloy Messages API |
| `asoud_erp/services/ai/tool_catalog.py` | Curated pilot catalog of read-only tools |
| `asoud_erp/services/ai/orchestrator.py` | The tool loop with hard caps, masking and truncation |
| `asoud_erp/tests/test_ai_assistant.py` | Pure tests (fake transport / executor) |
| `asoud_erp/integration_tests/test_ai_assistant.py` | Real-site tests (whitelisted methods, in-session execution) |
| `scripts/ai_smoke.py` | Manual smoke script (only runs when the site config has a key) |

## The model and why the design is strict

The model is **Gemma 4 26B (4-bit, llama.cpp)**, served privately. It is small
and slower than frontier models, and weaker at tool selection. The service runs
**2 generations at a time**, **60 requests/minute/key**, with a **131k** context.
The layer is therefore designed for a weak router:

- **Few tools, small flat schemas.** At most 12 tools, each a flat
  `input_schema` with one-line English descriptions and a Persian example value
  where it helps.
- **`tool_choice` is `{"type": "auto"}`.**
- **Thinking disabled for tool routing, low for the answer.** Routing uses
  `thinking: {"type": "disabled"}` (guaranteed, no thinking block); the final
  answer uses `{"type": "enabled", "budget_tokens": 1024}` (a low level).
- **Low temperature** (`0.2`).
- **Hard caps:** at most **5 tool calls per conversation turn**, a bounded
  `max_tokens` (1024 for the tool-routing turn; **2048 for the answer turn**,
  because reasoning tokens count inside `max_tokens` and a 1024 budget with a
  1024 thinking budget can cut the visible answer to nothing), and a
  **wall-clock budget** (default 60 s). If the answer turn stops on
  `max_tokens` with no visible text, the user gets a Persian
  «پاسخ کامل نشد؛ لطفاً دوباره بپرسید.» message instead of an empty string.
- **Result truncation:** a tool result is never fed back to the model in more
  than ~6k tokens (12 000 characters of JSON, Persian-heavy).
- **Strict loop guard:** the same tool with the same arguments twice stops the
  loop with a Persian message.

## The client (`gemloy_client.py`)

- Base URL and key come from the site config keys **`gemloy_base_url`** and
  **`gemloy_api_key`**. They are **never hard-coded, never logged, and never
  placed in an error message or an audit row.** If either is missing,
  `GemloyClient.from_site_config()` raises a Persian `ValueError`:
  «دستیار هوشمند پیکربندی نشده است».
- Auth is the `x-api-key` header; each request carries a `request-id`
  (1–128 chars of `[A-Za-z0-9_-]`).
- **Retry only on 429 `rate_limit_error` and 529 `overloaded_error`**, using
  `Retry-After` (capped at 30 s). A 429 **`quota_exceeded_error`** has no
  `Retry-After` and is **never retried**.
- The transport is injectable, so the pure tests run against a fake transport
  and never touch the network.
- `extract_text()` picks the block with `type == "text"` — it **never reads
  `content[0]`**, because a `thinking` block may come first.

## The tool catalog (`tool_catalog.py`)

A curated pilot of **read-only** tools, each an existing whitelisted read method
under `asoud_erp.api.v1.*`. Every entry has a `name` (matching
`^[a-zA-Z0-9_-]{1,64}$`), a `description`, an `input_schema`, the dotted
`method` it calls, and a `risk` field that is `"read"` for every entry in this
pilot.

The pilot set (10 tools):

| Tool | Method |
| --- | --- |
| `get_leave_balance` | `leave_request.get_leave_balance` |
| `get_my_leave_summary` | `hr_self_service.get_my_leave_summary` |
| `list_my_leave_applications` | `hr_self_service.list_my_leave_applications` |
| `list_my_workflow_tasks` | `workflow_runtime.list_my_workflow_tasks` |
| `list_my_workflow_instances` | `workflow_runtime.list_my_workflow_instances` |
| `get_workflow_task` | `workflow_runtime.get_workflow_task` |
| `get_request` | `workflow_request.get_request` |
| `get_calendar` | `calendar.get_calendar` |
| `get_my_personnel_file` | `personnel_file.get_my_personnel_file` |
| `list_my_issues` | `support.list_my_issues` |

`support.create_issue` is **not** read-only and is deliberately excluded. Write
tools are a later phase and must not be added here without the human-confirmation
design.

The catalog is cross-checked by tests against the real sources: each method must
exist, be `@frappe.whitelisted` in the real file, and **not** be treated as a
mutation by `asoud_erp/api/v1/sync.py` (`_is_mutation`). A renamed, un-whitelisted
or write method in the catalog fails CI.

## The orchestrator (`orchestrator.py`)

`run_assistant(question, acting_user, client, catalog, …)` runs the tool loop
with the caps above and returns `{"answer", "stop_reason", "tool_calls"}` where
`stop_reason` is one of `end_turn`, `loop_guard`, `tool_call_cap`, `time_budget`.

**The acting user is the principal.** Tools are executed **only** through the
whitelisted read methods in the acting user's session. The default executor is
`frappe.call` in the current session and **refuses to run when the session user
is not the acting user** — so the user's own Frappe permissions decide what comes
back and there is no privilege elevation.

**Masking is on by default.** Before a tool result goes back to the model, the
values of sensitive keys are replaced with a Persian marker («مخفی»). A key is
masked when it **contains** any of the sensitive stems in
`orchestrator.SENSITIVE_KEYS` (case-insensitive): `national`, `iban`, `bank`,
`salary`, `wage`, `mobile`, `phone`, `cell_number`, `address`, `postal`,
`birth`, `passport`, `email`, `father_name`, `emergency`, `tax_id`,
`insurance`. This is a **conservative default** — the read tools return more
personal data than just national ID / bank / salary (contact, address, birth
date, …), and the operator may retain request bodies — so the deny-list is
deliberately broad. Harmless business keys (`status`, `title`, `leave_type`,
request names and dates, `company`, `employee`, …) are not masked. The owner can
relax it per field by removing a stem from `SENSITIVE_KEYS`. It reuses the same
intent as the PA-055 masking but is independent so the assistant layer does not
depend on the request serializer.

## Privacy — what is sent

The operator **may retain request/response bodies**, so:

- Sensitive values (national ID, bank, salary) are **masked before** they are
  sent to the model.
- The API key is only ever in the `x-api-key` header; it is never in the body,
  never logged, and never in an error or audit row.
- **During development nothing from this repo's data goes to the API:** all tests
  use a fake transport and a fake executor, and the smoke script only runs when a
  key is configured.
- The model is called **only from the backend** (never from Flutter client code);
  the key must never reach the client.

## Limits and what is not built yet

- No `api/v1` endpoint, no live call, no streaming.
- No write tools, no human-confirmation flow for actions.
- The catalog is a pilot; the full read-only surface is a later phase.
- The integration tests run only on a bench site (CI); they are not run locally.
