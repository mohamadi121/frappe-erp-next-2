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

## 3. Definition of done (a feature is NOT finished without all of these)

1. Pure service code with pytest tests, including the failure paths.
2. An integration test in `asoud_erp/integration_tests/test_<module>.py` that runs on an installed site.
3. **The module is added to the CI loop** in `.github/workflows/erpnext-v15-integration.yml`. A test file that CI never runs does not count. (The organization v2 tests were written and never ran in CI.)
4. `docs/api/<module>.md` describing every public endpoint: method path, arguments, roles, response keys, error cases, plus a link in `docs/api/README.md`. An internal audit or design note is not API documentation.
5. A `CHANGELOG.md` entry under `## Unreleased` (create it at the top if missing), including deployment notes (new DocType or field → `bench migrate`; new site config keys).
6. `ruff check .` and `pytest -q` pass locally, and the integration module passes on a bench. Write the real command output in the PR description.

## 4. Data integrity and invariants

- When you add a new data format next to an old one (for example a v2 structure), **every validation the old format had must also apply to the new one**. The v2 organization chart accepted the same employee in two active positions because the global single-position check only looked at the legacy field. Write the cross-record test first.
- Check uniqueness across the whole company, not only inside one row or one request.
- Concurrent writes to shared structures (charts, sequences, balances) need a lock or revision check plus a savepoint/rollback. Lock as narrowly as possible.
- A renamed or deleted master record (Department, Employee, Item) must not silently break references. Guard it or update the references.
- A DocType or field change needs a migration/patch (`patches.txt`), a CHANGELOG note, and a test with a real restricted user, not Administrator.

## 5. Performance

- No N+1 queries: never call `frappe.get_doc` / `frappe.db.get_value` inside a loop over rows. Load with one `frappe.get_all(..., filters={'name': ['in', names]})` and map in Python.
- Every list or history endpoint is paginated (`limit`/`cursor` or `start`/`page_length`) and has a sane maximum. Never return an unbounded history.
- Add a database index for fields you filter or sort by on large tables, and say so in the CHANGELOG.
- Do not return images or large blobs inside list responses. Return a URL or id and serve the file through a permission-checked endpoint.

## 6. API contract with the app

- Response shapes are a contract. Adding keys is fine. Renaming or removing keys, or changing a type, breaks the released app: do it only with a version note and the matching app change.
- Error messages shown to users are **Persian sentences with a reason** (`frappe.throw(_('...'))`). Never leak tracebacks, internal ids or English ERPNext names as the message.
- Frappe answers `417` for a missing whitelisted method. The app treats unknown failures as a network problem, so a missing endpoint looks like an outage. Ship the endpoint and the app call together.
- Form builder schema (`services/form_schema.py`, `docs/api/forms.md`): a schema key exists only when the validator accepts it, `get_form`/entries honour it, it is documented and tested, **and** the Flutter runtime implements it. Do not let presets or clients send keys nobody implements.
- Requests, workflows, directives: reuse `request_access`, `request_status` and the workflow runtime. Do not write a second permission or status model.

## 7. Tests

- Integration tests create fresh records (HRMS and POS commit internally), clean up after themselves, and tolerate already-renamed or removed rows during cleanup. Leftover rows have broken unrelated modules.
- Do not import a `TestCase` class into another test module: its tests then run twice.
- Run per module: `bench --site <site> run-tests --app asoud_erp --skip-test-records --module asoud_erp.integration_tests.test_<module>` (the whole app run fails on Payment Gateway test records).
- Assert net amounts, not totals that depend on default tax templates. ERPNext `before_tests` deletes Item Prices, so fixtures recreate them.
- Test permission boundaries: another company's user, an employee without the role, and a user without an Employee record.
- Never weaken or delete an existing test to make your change pass. If the behavior changed on purpose, change the expectation and explain why in the commit message.
- The lightweight CI installs only `pytest` and `ruff`. Heavy imports (Pillow, frappe) in pure tests need `pytest.importorskip` or a guard.

## 8. Git and pull requests

- Never push to `main` directly. Work on a branch (`feat/...`, `fix/...`) and open a pull request; the other developer reviews and merges.
- One topic per commit, with a conventional message that says what changed (`fix(org): reject one employee in two active positions`). Messages like `codex changes` or `update` are not acceptable.
- Keep a PR small enough to review. Split backend, migration and docs into separate commits.
- The PR description lists the endpoints touched, migrations, and the real output of `ruff`, `pytest` and the bench modules you ran.
- Never commit secrets, `site_config.json` contents, passwords, tokens or server addresses with credentials. Use the site config on the server.

## 9. Before you say "done"

- Re-read your diff from top to bottom.
- Confirm every item in section 3.
- Write down what you did **not** test. A report that says "all tests pass" without the command output will be rejected.
