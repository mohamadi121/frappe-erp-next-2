# ASOUD ERP end-to-end tests (Playwright)

Real HTTP end-to-end tests for the `asoud_erp` Frappe app: every assertion goes
through a running Frappe web server, a real session cookie, the real CSRF check
and the real `asoud_erp` API envelope. The pytest suite in
`asoud_erp/integration_tests` calls API functions in-process, so it cannot catch
anything broken between the socket and the endpoint — this suite can.

Nothing here mocks Frappe. Frappe's own `login`, `logout`, `get_logged_user`,
`client.get` and `client.get_value` are used as building blocks; `Playwright`'s
`APIRequestContext` is the only client, and each test gets its own cookie jar
from `support/fixtures.ts`.

## Layout

| Path | What it is |
| --- | --- |
| `playwright.config.ts` | projects (`api`, `ui`), reporters and the reproducible dev server |
| `support/api.ts` | `ApiSession`: login, CSRF, envelope unwrapping, `METHOD` names |
| `support/fixtures.ts` | per-test, per-user `APIRequestContext` storage states |
| `support/global-setup.ts` | site preparation and the request type designed over HTTP |
| `support/py/serve.py` | Frappe dev server with the site pinned in code |
| `support/py/site_prep.py` | idempotent bench writes (users, Employee rows, second company, native Workflow link) |
| `tests/*.spec.ts` | the suites |

## Requirements

* A bench with this app installed and a site (default `asoud.test`, override with `E2E_SITE`).
* `~/frappe-dev/bench/env` — override with `E2E_BENCH_PATH`.
* MariaDB and Redis running.
* Node 18+ and `npm ci` in this folder.
* Chromium: `npx playwright install chromium`.

On an unsupported host release (Ubuntu 26.04 reports as `ubuntu24.04-x64` to
Playwright 1.56), install with:

```bash
PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="ubuntu24.04-x64" npx playwright install chromium
```

No `/etc/hosts` entry is needed. `support/py/serve.py` calls
`frappe.app.serve(site=...)`, so every request to the port is the configured
site and no `Host` header is involved.

## Running

```bash
cd e2e
npm ci
npx playwright test                 # every suite, both projects
npm run test:api                    # the API suites only
npm run test:ui                     # the Desk browser suite only
npm run report                      # open the last HTML report
```

Playwright starts and stops the dev server itself on port 8010 (`E2E_PORT`),
never 8000, so a running bench web server is left alone. Set `E2E_BASE_URL` to
reuse a server you started yourself; in that case no server is launched and code
changes are **not** picked up without a restart, which matters when mutating the
backend to prove a test fails.

Each run repeats global setup, which is idempotent:

1. `bench add-user` / `bench set-password` create the three E2E logins and give
   the three shared fixture users a known password. Bench is used because it
   needs no HTTP session.
2. `support/py/site_prep.py ensure` runs `integration_tests.fixtures.setup_records`,
   adds Employee rows for the E2E-only logins and creates a second company.
3. The request type used by `requests.spec.ts` and `permissions.spec.ts` is
   designed over HTTP as a System Manager through the real `workflow.*`
   endpoints (Start → User Task → Approval → System Action → End). Only the
   native Frappe `Workflow` link that no `asoud_erp` endpoint exposes is written
   by the helper; activation still goes through `set_workflow_status`.

A definition left half-designed by an interrupted run is dropped and redesigned
rather than patched, so a green run always means a fully configured request type.

`test-results/site-state.json` is written by global setup and read by the suites
(company, abbreviations, accounts, the request type name). It is generated, and
git-ignored.

## What the suites cover

| Suite | Focus |
| --- | --- |
| `auth.spec.ts` | login, `sid`, `current_user` identity and roles, wrong password, logout, CSRF refusal, anonymous writes, unknown methods, envelope shape |
| `requests.spec.ts` | create with an idempotency key, replay, update, cancel, task list, complete task, instance timeline |
| `documents.spec.ts` | document template save, permission-filtered options, `frappe.client.get` on a created document |
| `permissions.spec.ts` | a second company, non-participants, role and company isolation on requests and instances |
| `desk.spec.ts` | the Desk in a real browser: login page, workspace, list view |

## CI

`.github/workflows/e2e.yml` is a `workflow_dispatch`-only proposal and has not
been executed on a runner. It needs a bench with MariaDB and Redis, and secrets
for the site. It is not part of any branch protection yet.