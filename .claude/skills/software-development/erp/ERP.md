# ERP / business-app development (sub-skill of software-development)

Distilled from the user's own `asoud-erp-expert` skill (`~/.claude/skills/asoud-erp-expert/`, ASOUD ERP: Persian RTL Flutter app + Frappe/ERPNext/HRMS v15 extension app). Only the generalisable rules are here. Project facts (repo paths, branches, live server, bench/emulator commands, worker flow) stay in that skill and must not be copied elsewhere.

**Routing**: if the work is on the ASOUD repos (`flutter-asoud-erp`, `frappe-erp-next-2` / `asoud_erp`), load `asoud-erp-expert` first and follow it; this file only adds general rules. For any other ERP, accounting, HR, inventory or workflow-heavy business app (Frappe/ERPNext, Odoo, custom), apply the rules below. Frontend for Persian ERP UIs: `../frontend/FRONTEND.md`.

## Security and ops (never relax)
- Secrets (passwords, tokens, `site_config`) never go into prompts, reports, commits, skills or chat; pass through a temp file and delete it; rotate anything pasted into a chat.
- Live/demo/production servers are read-only unless the user approves a specific write; back up first; verify reachability after each step; never read credential files.
- Never trust a bug claim: reproduce live claims with API/`curl` or a fresh sign-in. Worker and agent reports: review per `../workers/WORKERS.md` §2.7.

## Reuse the platform
- Reuse ERPNext/HRMS (or Odoo) standard DocTypes/models and controller functions (mappers like `make_sales_invoice`, `get_payment_entry`); never edit their source or build a parallel ledger/JSON store for transactions. Presentation metadata is fine.
- Thin API layer (`api/v1/<module>.py` returning one envelope, e.g. `success(data, meta)`); pure, testable logic in `services/`.
- Role check and company/tenant scope first in every endpoint. Use an explicit `require_roles` (Frappe's `only_for` is a no-op in tests).
- Every backend feature ships with: integration test, API doc, changelog entry, and its module added to the CI loop.
- A DocType/schema change means a migration: note it in changelog/docs and test with a real restricted user, never only Administrator.
- No silent fallback around permissions or data (`ignore_permissions` when config is missing, default dates): fail with a clear error.
- Don't assume an Employee record exists (admins/managers may have none).
- Sensitive HR/finance fields (bank details, salary) stay out of self-service update paths; tests enforce it.
- Seed data must be complete (company, setup rows, roles, users) or every demo user hits the first-run wizard. Integration tests start from clean data and clean up.

## API contract discipline (app <-> server)
1. Read the backend endpoint before calling it: method name, envelope, response keys, required roles. Diff the app's calls against the backend once per release.
2. Test fakes must return the JSON the backend really returns (copied from code or a real call), never a guessed shape.
3. Distinguish failure kinds with separate user messages: 401/403 permission, 417 validation (terminal), 5xx, timeout, no connection. One generic "server unreachable" hides causes (a missing server method returned 417 and looked like an outage).
4. A 403 for a role-restricted call can be expected: resolve the user's roles first and treat it as "no access", not as offline.
5. List read-only endpoints explicitly in offline-queue logic, otherwise reads get queued as writes and lists look empty.

## UX rules for business apps
- No blank page: every failed or empty call shows a specific message with the reason and a retry.
- Loading states must end (loaded or error); no endless spinners.
- No dead controls: every button navigates, acts, says "coming soon", or names the missing field.
- Hide controls by role instead of showing buttons the server will reject.
- Never show raw exceptions, internal ids, `SYS-`/`WF-` codes or English platform enum names to users; map through one shared label map (per locale).
- Offline/demo mode uses the same code path as online; preview ids never reach users.
- One shared date formatter (Jalali where required) and one shared label map; no per-screen `if` chains.
- Keep session and server address across restarts (secure storage); never store the password.
- Long forms/sheets must be scrollable; test layouts at 320, 390 and 430 px in RTL.

## Flutter specifics
- Release builds differ from debug: the main Android manifest must declare `INTERNET` (and `usesCleartextTraffic` for plain-HTTP servers); keep a test for it; smoke-test the RELEASE build with a real sign-in before shipping.
- Never run `dart format` on existing files in a repo using an older style (it rewrites whole files); format only new files.
- Adding a method to a widely faked repository breaks every test fake: put new server calls in a separate repository class.
- Dispose dialog `TextEditingController`s inside the dialog widget, never right after `showDialog`; don't return a Future from a `setState` callback.
- Test pushed routes under an RTL `Directionality`; use `contains(equals(...))` for map matching in tests.
- Bidi: Latin/number values (emails, codes) LTR; Persian strings starting with digits stay RTL.

## Quality rules
Moved to `../SKILL.md` §3 (they apply to every project). Worker task packs: `../workers/WORKERS.md` §2.3. For ERP "X doesn't work" reports, the role check means manager vs employee-only, and the offline mode is offline preview.
