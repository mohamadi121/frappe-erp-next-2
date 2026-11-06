# Engineering principles for ASOUD ERP work (workers and manager)

Each rule comes from a real defect found while building or releasing this project. Check your change against all of them before you report.

## API contract and server
1. **Read the backend before calling it.** Before adding an app call, open the backend endpoint: method name, envelope (`success(data, meta)`), response keys, required roles. Compare the app's calls with the backend once per release (a matrix of all calls found `automatic_actions.*` missing on the server).
2. **Test with real response shapes.** Fake HTTP clients must return the JSON the backend really returns, copied from its code or a real call, never a shape the worker guessed. (Roles showed «0 نقش» and the setup card never resolved because of guessed shapes.)
3. **Separate failure kinds.** `401/403` (permission), `417` (inner validation error, terminal), `5xx`, timeout and no connection need different Persian messages. One message («ارتباط با سرور برقرار نشد») for all of them hides the cause.
4. **No blank page.** Every failed or empty call shows a Persian message with the reason and a retry button (the HR hub was blank with only «تلاش دوباره»).
5. **Do not assume an Employee record.** Administrator and other managers may have no Employee: services and screens must still work.

## Backend (Frappe / ERPNext / HRMS)
6. **Layers.** `api/v1/*` stays thin; logic lives in pure `services/*` with pytest tests; `require_roles` and `require_company` come first in every endpoint.
7. **No silent fallback around permissions or data** (`ignore_permissions` when config is missing, default dates). If a prerequisite is not configured, fail with a clear error.
8. **A DocType change means a migration.** Note it in `CHANGELOG.md` and `docs/`, and test with a real restricted user (the workflow service user), not Administrator.
9. **Seed data must be complete**: company, `ASOUD Company Setup`, roles, users. A missing setup row made every demo user see the first-run wizard.
10. **Integration tests run on clean data** and clean up after themselves; leftover rows failed unrelated modules.

## Flutter app
11. **Release builds differ from debug.** The main `AndroidManifest.xml` must declare `INTERNET` and `usesCleartextTraffic` (HTTP server); keep a test for it. Always smoke-test the release APK with a real sign-in.
12. **Keep session and server address across process restarts** (secure storage). Never store the password.
13. **Dates are Jalali, labels Persian.** One shared Jalali formatter and one shared Persian label map for ERPNext enums and role names; no per-screen `if` chains.
14. **Offline/demo uses the same code path as online.** No separate branches; preview identifiers (`PREVIEW-*`, «- DEMO») never reach the user.
15. **No dead controls.** Every button navigates, acts, shows «به‌زودی», or shows a validation message naming the missing field.
16. **Loading states must end.** Every cubit/provider reaches loaded or error; an endless «در حال دریافت» line is a bug.
17. **Test layouts at 320, 390 and 430 px in RTL**, with scrollable sheets, to catch overflow.

## Quality
18. **One bug, one commit, one regression test** that fails before the fix.
19. **Never weaken an existing test to make it pass.** If behaviour changed on purpose, update the expectation and say why in the commit message.
20. **Run `flutter analyze` / `ruff check .` before every commit.** The lightweight backend CI installs only pytest and ruff, so heavy dependencies (Pillow, frappe) need `pytest.importorskip` or a guard.
