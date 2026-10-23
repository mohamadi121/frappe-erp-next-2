# Agent guidelines — asoud_erp (Frappe / ERPNext / HRMS v15)

Read this whole file before you change anything. It applies to every coding agent and every
human working in this repository. Each rule below exists because the mistake really happened
here and had to be fixed afterwards.

The Flutter app (`flutter-asoud-erp`) consumes this API. Its own `AGENTS.md` has the app-side rules.

## 1. Architecture contract

- This is an extension app for ERPNext/Frappe/HRMS v15, not a replacement ERP backend.
- Before implementing a business feature, inspect the installed standard app's DocTypes, controllers and APIs. Reuse them if they implement the requested behavior (mappers such as `make_sales_invoice`, `get_payment_entry`, HRMS `get_leave_details`, query reports, POS functions).
- Keep Iranian accounting/localization and genuinely missing behavior in `asoud_erp`. Never modify ERPNext/Frappe/HRMS source code.
- Do not create a custom business ledger or JSON store that duplicates standard transactions. Technical idempotency receipts, compatibility references and explicit presentation metadata are allowed.
- Employee is authoritative for shared HR master fields. Employee Checkin/Attendance, Appraisal, private File and Comment own their corresponding records. Department is the organization unit.
- Preserve legacy data. Migration must be explicit, report unresolved records and be safe to retry. Never guess Employee identities or fabricate appraisal cycles.
- See `docs/personnel-native-architecture.md` for migration and verification details. Keep the Flutter accordion form style contract unchanged.

## 2. Layers

- `asoud_erp/api/v1/<module>.py` stays **thin**: check access, call a service, return `success(data, meta)` (`api/v1/responses.py`).
- Logic that can be pure goes to `asoud_erp/services/*.py` and gets pytest tests in `asoud_erp/tests/` (no Frappe site needed).
- The first lines of every whitelisted endpoint check access:
  - roles with `services/erp_documents.require_roles([...])` (`frappe.only_for` is a no-op in tests, so it proves nothing);
  - company scope with `services/request_access.require_company(company)`;
  - document-level permission for anything that reads a specific record (private files, employee photos, another person's data).
- Never add `ignore_permissions=True` as a fallback "when the config is missing". If a prerequisite is not configured, fail with a clear Persian error.
- Do not assume the signed-in user has an Employee record (Administrator and many managers do not). Handle "no Employee" explicitly.

## 3. How to write a change (the order that keeps quality high)

1. **Read before you write.** Read the spec or issue, the existing endpoint or service you are extending, and the standard ERPNext/HRMS DocType JSON (`frappe.get_meta(...)` or the `doctype/*.json` file). Note which fields are optional: an optional field is `None` in real data.
2. **Write the contract first.** Put the new keys, arguments, response shape and Persian error messages into `docs/api/<module>.md` and commit that before the code. The app is built against this text.
3. **Write the failing test first.** Show that it fails on the old code: run it before the fix, or revert the fix locally, and paste the failure into the PR. A test written only against the new code proved nothing in several reviews here.
4. **Make the smallest generic change** that passes. Then run section 8 in full, re-read the diff, and go through the checklist below.

### Code quality rules (each one was a real defect caught in review)

- **Generic code never keys on a magic field name.** A rule must not look for `values['attendance_date']` or another key a preset happens to use. Take the key from the schema (`*_field` settings), or make the rule independent of it. Example: compare `(next_day, time)` pairs instead of building datetimes from a date the form may not have.
- **Frappe filters are AND only.** `{'end_date': ['in', ['', None, ['>=', today]]]}` is not an OR; it silently matches nothing useful. Use `or_filters`, `['is', 'not set']`, or filter in Python. A unit test that mocks `frappe.db.get_value` cannot catch this, so every new query needs an integration test with real rows that must and must not match.
- **Optional dates are open ranges.** HRMS `Shift Assignment.end_date`, `Contract.end_date`, `Employee.relieving_date` and similar are often empty. Treat `None` as "no end" in the query and in Python comparisons (`None >= date` raises `TypeError`). Also filter on `status`/`docstatus` the way HRMS does (Inactive assignments stay at `docstatus = 1`).
- **The server is the authority.** Every check the app does (scope, `exclude_self`, `not_equal`, unique rows, step limits) is repeated on the server. Values the client cannot change (`fetch_from`, read-only defaults, totals) are recomputed on submit and the client value is ignored.
- **Scope is enforced in every path.** A record source restricted to "my Employee" is filtered in the option list *and* rejected on submit. Hidden data (`sensitive` fields) is masked in every output: detail, task preview, `search_text`, attachments, print and exports. When you add a new output, check the masking.
- **Policies do not depend on configuration.** Rules the business approved (a reason is required to reject or return; nobody approves their own request) are enforced in the runtime even if a stage config says otherwise. Fallbacks are explicit (escalation role, then an activity note), never a silent skip.
- **Unknown ids give a Persian error,** not a raw `DoesNotExistError`. Read only the fields you need with `frappe.db.get_value(..., as_dict=True)` instead of `get_doc`.
- **Every input from the request may be missing or of the wrong type.** Skip or reject empty optional table cells explicitly; never `date.fromisoformat(None)`.

## 4. Definition of done (a feature is NOT finished without all of these)

1. Pure service code with pytest tests, including the failure paths.
2. An integration test in `asoud_erp/integration_tests/test_<module>.py` that runs on an installed site, with real records (no mocks of `frappe.db`).
   - A new or changed **whitelisted endpoint, role gate or permission rule** also gets a Playwright API test in `e2e/tests/*.spec.ts` (real HTTP session, CSRF and envelope, see `e2e/README.md`). It must cover the allowed user, a user without the role, a user of another company, and a user without an Employee record.
3. **The module is added to the CI loop** in `.github/workflows/erpnext-v15-integration.yml`. A test file that CI never runs does not count. (The organization v2 tests were written and never ran in CI.)
4. `docs/api/<module>.md` describing every public endpoint: method path, arguments, roles, response keys, error cases, plus a link in `docs/api/README.md`. An internal audit or design note is not API documentation.
5. A `CHANGELOG.md` entry under `## Unreleased` (create it at the top if missing), including deployment notes (new DocType or field → `bench migrate`; new site config keys).
6. `ruff check .` and `pytest -q` pass locally, and the integration module passes on a bench. Write the real command output in the PR description.

## 5. Data integrity and invariants

- When you add a new data format next to an old one (for example a v2 structure), **every validation the old format had must also apply to the new one**. The v2 organization chart accepted the same employee in two active positions because the global single-position check only looked at the legacy field. Write the cross-record test first.
- Check uniqueness across the whole company, not only inside one row or one request.
- Concurrent writes to shared structures (charts, sequences, balances) need a lock or revision check plus a savepoint/rollback. Lock as narrowly as possible.
- A renamed or deleted master record (Department, Employee, Item) must not silently break references. Guard it or update the references.
- A DocType or field change needs a migration/patch (`patches.txt`), a CHANGELOG note, and a test with a real restricted user, not Administrator.

## 6. Performance

- No N+1 queries: never call `frappe.get_doc` / `frappe.db.get_value` inside a loop over rows. Load with one `frappe.get_all(..., filters={'name': ['in', names]})` and map in Python.
- Every list or history endpoint is paginated (`limit`/`cursor` or `start`/`page_length`) and has a sane maximum. Never return an unbounded history.
- Add a database index for fields you filter or sort by on large tables, and say so in the CHANGELOG.
- Do not return images or large blobs inside list responses. Return a URL or id and serve the file through a permission-checked endpoint.

## 7. API contract with the app

- Response shapes are a contract. Adding keys is fine. Renaming or removing keys, or changing a type, breaks the released app: do it only with a version note and the matching app change.
- Error messages shown to users are **Persian sentences with a reason** (`frappe.throw(_('...'))`). Never leak tracebacks, internal ids or English ERPNext names as the message.
- Frappe answers `417` for a missing whitelisted method. The app treats unknown failures as a network problem, so a missing endpoint looks like an outage. Ship the endpoint and the app call together.
- Form builder schema (`services/form_schema.py`, `docs/api/forms.md`): a schema key exists only when the validator accepts it, `get_form`/entries honour it, it is documented and tested, **and** the Flutter runtime implements it. Do not let presets or clients send keys nobody implements.
- Requests, workflows, directives: reuse `request_access`, `request_status` and the workflow runtime. Do not write a second permission or status model.

## 8. Tests

- Integration tests create fresh records (HRMS and POS commit internally), clean up after themselves, and tolerate already-renamed or removed rows during cleanup. Leftover rows have broken unrelated modules.
- Do not import a `TestCase` class into another test module: its tests then run twice.
- Run per module: `bench --site <site> run-tests --app asoud_erp --skip-test-records --module asoud_erp.integration_tests.test_<module>` (the whole app run fails on Payment Gateway test records).
- Assert net amounts, not totals that depend on default tax templates. ERPNext `before_tests` deletes Item Prices, so fixtures recreate them.
- Test permission boundaries: another company's user, an employee without the role, and a user without an Employee record.
- Never weaken or delete an existing test to make your change pass. If the behavior changed on purpose, change the expectation and explain why in the commit message.
- Which test proves what:

  | Level | Where | Proves | Required for |
  |---|---|---|---|
  | pure pytest | `asoud_erp/tests/` | logic and failure paths, fast | every service change |
  | integration | `asoud_erp/integration_tests/` | queries, permissions and HRMS/ERPNext side effects on a real site | every endpoint, query or DocType write |
  | e2e (Playwright) | `e2e/tests/` | the real HTTP path: login, CSRF, envelope, role gates | new endpoints, role/permission changes, auth |

  Run the e2e suite with `cd e2e && npm ci && npm run test:api` (it starts its own server on port 8010). Add a new spec file to the `test:api` script in `e2e/package.json`, otherwise it never runs. Paste the result into the PR.
- Mocks are for pure logic only. If a test mocks the query whose filter you changed, it does not test the change.
- Bench runs share one MariaDB site: run one integration or e2e suite at a time, otherwise you get `QueryDeadlockError` and false failures.
- The lightweight CI installs only `pytest` and `ruff`. Heavy imports (Pillow, frappe) in pure tests need `pytest.importorskip` or a guard.

## 9. Git and pull requests

- Never push to `main` directly. Work on a branch (`feat/...`, `fix/...`) and open a pull request; the other developer reviews and merges.
- One topic per commit, with a conventional message that says what changed (`fix(org): reject one employee in two active positions`). Messages like `codex changes` or `update` are not acceptable.
- Before you open a PR, and again after any PR it depends on is merged, merge the latest `main` into your branch and rerun the checks. Resolve `CHANGELOG.md` conflicts by keeping both entries. A stacked PR names its parent PR in the description.
- Keep a PR small enough to review. Split backend, migration and docs into separate commits.
- The PR description lists the endpoints touched, migrations, and the real output of `ruff`, `pytest` and the bench modules you ran.
- Never commit secrets, `site_config.json` contents, passwords, tokens or server addresses with credentials. Use the site config on the server.

## 10. Before you say "done"

- Re-read your diff from top to bottom.
- Confirm every item in section 4.
- Write down what you did **not** test. A report that says "all tests pass" without the command output will be rejected.
