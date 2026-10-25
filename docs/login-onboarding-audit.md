# Login, onboarding, system administrator, roles and HR onboarding: audit and decisions

Scope: spec sections 1-38 (login page, logout, system administrator, admin directive/work-report bug, roles and
permissions, create-office permission, per-office roles, first office, admin profile, change password, HR onboarding,
audit log, reversible patches). Classification per feature: **healthy** (existed and kept), **fixed** (existed, was
wrong), **new** (missing, built), **gap** (not done / needs a decision). Verified on a local bench (Frappe, ERPNext and
HRMS v15, MariaDB 10.11); see `CHANGELOG.md` for the exact test commands.

## What existed before

| Area | State before | Class |
|---|---|---|
| Sign-in | Frappe native `/api/method/login`; `auth.current_user` | healthy |
| Logout | only the native `/api/method/logout`; the app only forgot its local token | fixed (`session.logout` revokes and audits) |
| Post-login state | none; the app guessed from roles | new (`session.login_state`) |
| Temporary password | no flag, no expiry, no enforcement | new (`ASOUD Account State`, `before_request` guard) |
| Forgot password | none | new (needs outgoing e-mail; `recovery_status` tells the app) |
| Change password | none in the API | new, single service `password_service.change_password` |
| System administrator | `System Manager` only as a gate on some endpoints | fixed (recognised by role, last-admin guard) |
| Admin cannot direct / report | root cause below | fixed |
| Roles | `ASOUD Role Definition/Category` on native Role Profile; per-user grants through `ASOUD Access Assignment` + Custom DocPerm | healthy, extended |
| HR simple/medium/advanced | server offered only four actions and no HR module; app rendered "advanced" like "medium" | fixed |
| Create-office permission | `save_office` demanded office-manager roles for new and existing offices | fixed (`ASOUD Office Creator`) |
| Per-office roles | none; every role was global | new (`ASOUD Office Role Assignment`) |
| First office / admin profile | none | new (`onboarding`) |
| HR onboarding | `party.save_party` + `auth.sync_employee_access` without activation policy | new orchestration on top of them |
| Audit | Frappe Version/Activity Log only | new (`ASOUD Security Audit`, append-only) |

## Root causes of the administrator bug

* `directives._employee()` required an active Employee linked to the user; the administrator has none.
* `directive_access.active_user` excluded `Administrator`; `can_read`/`communication_query` required an Employee;
  `_people` returned only direct reports.
* `hr.save_report/create_communication/list_team/review_report` used `_employee_for_user()`, which throws without an Employee,
  and `ASOUD Work Report.employee` was mandatory.
Fix: a virtual actor row for the administrator, whole-company people list, `ASOUD Work Report.reporter` (employee optional),
explicit review route (manager pool when no direct manager), self-review forbidden, `require_company` in review.

## Root cause of "advanced equals medium"

`user_access` returned `read/create/write/delete` only. There were no print/email/export/report/share/import/submit/cancel/amend
actions and no HR DocTypes, and the Flutter editor rendered modes 1 and 2 identically. `services/permission_catalog.py` now defines
the modules (including the full HR module) and `levels_for` (simple = read, medium = read/create/write/delete, advanced = medium + submit
actions for submittable DocTypes + print/email/export/report/share/import). Applied as native Custom DocPerm rows.

## Decisions

* Administrator = enabled System User with `System Manager`; global; one site. Last-admin guard in `User.validate/on_trash`
  (compares against the stored row because the standard `User.on_trash` disables the in-memory document first).
* Office-scoped roles are enforced at the ASOUD gates (`require_roles(..., company=)`, `company_access`) and in the setup and
  role endpoints. Native DocType permissions inside Frappe stay global: a native permission cannot be office-scoped without
  User Permissions on Company, which this change does not add.
* Sub-roles: `parent` on a role definition is classification only; there is no permission inheritance.
* Delegation: only the administrator and holders of `ASOUD Role Assigner` grant roles; nobody changes their own roles; a delegate
  cannot grant roles beyond those they hold; `System Manager` can only be granted by the administrator.
* Passwords: Frappe's native password hashing (PBKDF2-SHA256) is kept; Argon2id is **not** used. Policy: 12+ characters,
  no identifier parts, zxcvbn score of 2 or more.
* Temporary passwords: random, shown once, 72-hour expiry, forced change enforced by the server for every API call.
* One-time codes (reset 30 minutes, invitation 72 hours) are stored hashed, single use, 5 attempts.
* `company_access`: a manager role (for example `HR Manager`) without a Company read right but with an active Employee in the office
  now belongs to that office (before, HR Manager without Company read was refused).
* Audit rows are never edited or deleted; secrets are redacted before write.

## Gaps and things not done

* Mobile and e-mail verification (OTP/SMS): flags exist and are reset on change, no verification flow.
* Argon2id: not used (see above).
* The administrator reading other people's directives stays participant-only (not changed).
* Native DocType permissions are not office-scoped (see decisions).
* Playwright API specs for the new endpoints were not written.
* Flutter screens (login page, saved password, change-password UI, admin bootstrap pages) belong to the app repository.
* Invitation e-mail delivery depends on an outgoing e-mail account; without it only `temporary_password` activation works.

## Patches and rollback

`patches/v0_18/ensure_security_roles_and_backfill.py` is idempotent: it creates the roles `ASOUD Office Creator` and `ASOUD Role Assigner`,
sets `scope = global` on existing role definitions, marks definitions whose profile holds `System Manager` as system roles, backfills
`ASOUD Work Report.reporter` from the report's Employee login and records the first office of an existing deployment in `ASOUD Settings`.
It overwrites and deletes nothing. Reversal (manual): remove the new fields by editing the DocType JSON and migrating, delete the two roles,
and remove the `doc_events`/`before_request`/`on_login` hook entries; no existing value was changed.
