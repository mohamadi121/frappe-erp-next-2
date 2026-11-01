# Setup reset correction — implementation and verification

## Cause and scope

Ordinary workflow deletion correctly rejects seeded system definitions and edit
history. The full-office reset used that same native deletion path without a
verified reset capability, causing the whole transaction to roll back. The queued
receipt also lost its original digest on transition to running. Cached setup data
survived successful server reset; office caches did not separate actors/sites.

The existing authenticated preview/perform/status API is retained. The worker now
has an exact actor/job/digest/company/document capability, restored in `finally`;
only it may remove the confirmed offices' system definition configuration. Native
link checks, execution-history protection, fresh password, backup acknowledgement,
typed confirmation, write barrier, rollback and mandatory durable audit remain.
Ordinary workflow deletion has not been weakened. No force or ignore-links deletion.

The completion response includes actor/office scope. The client clears matching
cache/drafts only after durable completion and never repeats server deletion to
recover local-cache errors. Office caches use owner/server namespaces and exclude
ownerless legacy records. Pending personnel/office writes also block submission.

## Files for this correction

Backend:

- `asoud_erp/services/setup_reset.py`
- `asoud_erp/services/setup_reset_policy.py`
- `asoud_erp/services/workflow_lifecycle.py` (reset capability only; includes earlier card-action work)
- `asoud_erp/tests/test_setup_reset_policy.py`
- `asoud_erp/integration_tests/test_setup_reset.py` (already registered in CI)
- `docs/api/setup-reset.md`, `docs/setup-reset-review.md`, `CHANGELOG.md`

Paired Flutter repository:

- `lib/features/auth/data/setup_reset_cache.dart`
- `lib/features/auth/presentation/pages/setup_reset_page.dart`
- `lib/features/auth/presentation/pages/login_page.dart`
- `lib/features/office_setup/data/repositories/server_first_office_repository.dart`
- `lib/app/app.dart` (office-cache identity injection only; earlier workflow providers retained)
- `test/features/auth/setup_reset_cache_test.dart`
- `test/features/auth/setup_reset_tracking_test.dart`
- `test/features/office_setup/server_first_office_repository_test.dart`
- `CHANGELOG.md`

Other pre-existing dirty changes are not part of this reset correction and were preserved.

## Actual local verification

- `python -m ruff check .`: **All checks passed!**
- `python -X utf8 -m pytest -q`: **1312 passed in 2.67s** (pure service suite, not Frappe integration).
- `flutter analyze --no-pub`: **No issues found! (ran in 3.2s)**.
- `flutter test --no-pub --exclude-tags golden test/features/auth test/features/office_setup --reporter expanded`:
  **161 tests passed**, including reset completion/failure at RTL 320/390/430,
  cleanup failure/retry without repeat perform, scope separation and onboarding regressions.
- `git diff --check`: clean (only Windows line-ending notices).

New tests first exposed malformed URI cache keys raising ArgumentError and the
indeterminate progress indicator surviving a local cleanup failure; both were fixed
without weakening the assertions. The broad Flutter run includes these regressions.

## Not verified / deployment still required

Frappe/Bench, Node and npm are unavailable here. Real-site integration and HTTP
tests were **not run**. The integration module contains transaction-local disposable
office/admin/personnel/department/role tests, seeded-workflow protection, native-link
rollback, execution-history blockers, preserved login hash and durable receipt checks.
Run it on an isolated test bench before enabling production reset:

```sh
bench --site <disposable-test-site> run-tests --app asoud_erp --skip-test-records --module asoud_erp.integration_tests.test_setup_reset
```

The existing HTTP reset denial/receipt suite is already included in `npm run test:api`.
Neither production deployment, site flag activation, live deletion nor git push was
performed. Deploy backend and matching Flutter, restart web/long workers, verify on
the disposable site, then deliberately enable `asoud_allow_setup_reset` only while
needed on the backed-up target site. Paired source-link fields need the previously
documented migration if that earlier release has not yet been deployed.

This is an owned-setup reset, **not an unconditional whole-site wipe**. Posted
records, workflow execution history and unsupported/outside dependencies block
the entire operation rather than being silently erased. Other owners' offices,
security audit and essential native roles remain. Unknown external dependencies
may need administrative review; no production success is claimed here.
