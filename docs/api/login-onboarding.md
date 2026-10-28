# Login, first-run onboarding, system administrator, roles and HR onboarding

Modules: `asoud_erp.api.v1.session`, `account_security`, `onboarding`, `role_access`, `hr_onboarding`,
plus additions to `role_management`, `user_access`, `setup`, `hr` and `directives`.
Every answer uses the standard envelope `{ok, data, meta}` (see [README](README.md)). Errors are Persian
sentences. Audit: every security event is written to the append-only `ASOUD Security Audit` DocType
(`SEC-YYYY-#######`) with actor, time, result, target, company and source, never a password, token or one-time code.

## System administrator («مدیر کل سیستم»)

The administrator is an enabled System User holding the native `System Manager` role. It is recognised by
that role (never by "first login" or a user name), is global over every office of the site, and cannot reach
another site. The last enabled named administrator cannot be disabled, deleted or stripped of the role
(`PermissionError`: «آخرین مدیر کل فعال سیستم را نمی‌توان حذف، غیرفعال یا از نقش مدیر کل خارج کرد؛ …»).
The administrator needs no Employee record: directives, work reports and team lists work without one.

## session

### `session.login_state` — GET
Roles: any signed-in user (Guest: `AuthenticationError`). One server-authoritative answer after sign-in.

```
data: {
  user: {id, full_name, first_name, last_name, mobile, email},
  account: {active, must_change_password, temporary_password_expired},
  roles: [native role names], is_system_admin, role_title ("مدیر کل سیستم" or ""),
  scope: "global" | "office",
  capabilities: {create_office, manage_roles, delegate_roles, register_personnel},
  offices: [{id, title, office_type, roles, office_roles}],
  selected_office, first_office_exists, admin_profile_complete,
  verification: {mobile_verified, email_verified},
  next: {route, office, message}
}
```
`next.route` is one of `account-disabled`, `change-password`, `create-first-office`, `setup-first-office`, `complete-admin-profile`,
`office-select`, `home` (with `next.office`), `no-office` (with the Persian `message`
«هنوز دسترسی به دفتر کاری برای شما تعیین نشده است.»). Priority: disabled, change password, admin bootstrap
(essential profile, then first office, then office setup), no office, one office goes home,
several offices use `selected_office` or ask. An incomplete administrator profile always
returns `complete-admin-profile`, including before any office exists and during unfinished setup.
A non-admin never gets `create-first-office`.

`setup-first-office` returns `next.office` for the persisted
`ASOUD Settings.first_office_company` when it is accessible to the system
administrator but has no enabled native Fiscal Year linked through Fiscal Year
Company, or has not explicitly completed bootstrap. It comes after profile completion and office creation,
and resumes after sign-out/restart. Legacy sites without that bootstrap marker
are not redirected. Completion uses the existing server-side `bootstrap_completed` marker.
`setup.list_fiscal_years(company)` returns [{name, year, year_start_date,
year_end_date, disabled}]. `setup.create_fiscal_year(company, fiscal_year,
start_month, start_day)` persists a native year and its company link and returns
one such row. Input is Jalali; ISO Gregorian dates are stored/returned. The end
is the day before the same Jalali date next year. Existing years with a different
period are rejected; matching ones are linked, never overwritten. Only the fiscal
step is implemented in this iteration; HR-lead and final-review cards are pending,
not falsely marked complete. Saving a fiscal year does not mark accounting or HR
setup complete. No new API or schema migration is required.

### `session.logout` — POST
Revokes the current server session (`Sessions` row) and audits it. `data: {revoked: true}`.

### `session.select_office(company)` — POST
Stores the active office default; only an office listed in `login_state.offices` is accepted
(`PermissionError` «به این دفتر دسترسی ندارید.»). Blocked while a temporary password is pending.
Returns the fresh `login_state` payload.

## account_security

### `account_security.change_password(current_password, new_password, repeat_password)` — POST
The only password-change service (used by the settings page and the forced change after a temporary password).
Checks the current password, the repeat, a policy (at least 12 characters, no identifier parts, different from the
current one, zxcvbn score of at least 2), rate-limits failures (5 per 15 minutes per account, even for a correct
password afterwards), stores the hash with Frappe's native algorithm, clears the temporary-password flag and
revokes every other session of the account. `data: {changed, must_change_password: false, other_sessions_revoked,
reauthentication_required_for_saved_credentials}`. Errors: `ValidationError` (wrong current password, weak or
mismatching new password, too many attempts); `AuthenticationError` for Guest.

While `must_change_password` is set the server refuses every `/api/method/*` call except `session.login_state`,
`session.logout`, `account_security.change_password`, `logout` and ping with `PermissionError`
«رمز عبور موقت شما باید ابتدا تغییر کند؛ …». An expired temporary password cannot sign in.

### Recovery (guest endpoints)
- `recovery_status()` GET: `data: {available}`; true only when an outgoing e-mail account exists. The app
  shows «رمز عبور خود را فراموش کرده‌اید؟» only if true.
- `request_password_reset(identifier)` POST: identical answer for known and unknown accounts
  (`{requested: true, expires_in_minutes: 30}`); throttled per IP and per identifier. The one-time code is e-mailed.
- `confirm_password_reset(identifier, code, new_password, repeat_password)` POST: `{changed, login_required}`; hashed
  single-use code, 5 attempts, 30 minutes; same password policy; all sessions of the account are revoked.
- `activate_account(identifier, code, new_password, repeat_password)` POST: invitation activation (code valid 72 hours).
Disabled and built-in accounts are never recoverable.

## onboarding (system administrator only)

### `onboarding.create_first_office(office_type, company_name, ...)` — POST
Same arguments as `setup.save_office`. Idempotent and serialised by a global lock: when an office already exists nothing
is created and the answer is `{created: false, already_exists: true, office}`; otherwise `{created: true, office}`.
Records `first_office_company/created_by/created_on` in `ASOUD Settings` and `office_admin` on the office.
Non-admins: `PermissionError`, audited as `onboarding.denied`.

### `onboarding.get_admin_profile()` — GET / `onboarding.save_admin_profile(first_name, last_name, mobile, national_id?, email?)` — POST
Attaches identity data to the existing account (never creates a User, Employee, role or tafsili code).
Persian digits are normalised; mobile (`09xxxxxxxxx`), national id (checksum) and e-mail are validated; a mobile used by
another account is refused. Changing the mobile or e-mail resets its verified flag. Returns
`{username, role, active, first_name, last_name, mobile, national_id, email, mobile_verified, email_verified, completed, person}`.
Mobile/e-mail verification flows are not implemented: the flags stay false.

## Create-office permission

`setup.save_office` for a **new** office requires `System Manager` or the dedicated role `ASOUD Office Creator`
(independent of office management; the creator does not become a manager of the office). Editing an existing office
requires the office-manager roles. The role is part of the role-management catalog and audited
(`office.create_permission_grant`, `office.create`, `office.update`, `office.settings_change`).

## Roles and permissions

- `role_management.save_role` accepts `scope: "global" | "office"`; rows and the catalog expose `scope` and `system`.
  A definition whose base roles include `System Manager` can only be global.
- `role_management.system_admin_permissions()` returns the administrator row (title «مدیر کل سیستم», scope global,
  full permission list derived from the real permissions plus the ASOUD capabilities).
- `role_management.catalog` adds `system_roles`.
- `role_access.assign_role(user, role, company?)` / `unassign_role(user, role, company?)` POST: global definitions use
  `ASOUD Access Assignment`; office definitions use `ASOUD Office Role Assignment` (one account may hold different roles
  in different offices; they never leak into the global roles). Gates: administrator or holder of `ASOUD Role Assigner`;
  nobody grants or removes their own roles; a delegate cannot grant roles they do not hold (no escalation, never
  `System Manager`); audited (`role.assign`, `role.unassign`, denied attempts included). Reply:
  `{user, role, scope, company, assigned, already_assigned}` / `{removed, ...}`.
- `role_access.list_office_roles(user)` GET.
- `user_access.editor/apply`: the catalog now has the full HR module (Employee, Leave, Attendance, Shift, Payroll, Appraisal,
  Expense claim, ...). `levels` lists the modes (`simple`, `medium`, `advanced`) with their real action sets; `editor` returns
  `advanced_grants` (per DocType: `submit`, `cancel`, `amend` for submittable DocTypes, plus `print`, `email`, `export`, `report`,
  `share`, `import`) and `inherited_advanced`. `apply` accepts an optional `advanced_grants` map in the payload; unknown or
  disallowed actions are refused and the change is audited (`role.permission_change`). Advanced is a strict superset of
  medium, which is a strict superset of simple.

## hr_onboarding

Roles: `System Manager` or `HR Manager` (also an office-scoped HR Manager) with access to the company. Idempotent.

### `hr_onboarding.register_personnel(company, first_name, last_name, mobile, email, national_id?, gender?, birth_date?, date_of_joining?, job_title?, department?, roles?, activation="invite", detail_groups?, request_id?)` — POST
Person (`ASOUD Party Profile`, reused by login, Employee link or national id) -> personnel file (`Employee`) -> login account
(`email` is the user name) -> role definitions (`roles`, with the delegation rules above) -> activation.
`activation = "invite"` e-mails a one-time code (requires an outgoing e-mail account; otherwise a Persian error);
`activation = "temporary_password"` returns a random temporary password exactly once in `data.activation`
(`temporary_password`, `expires_in_hours: 72`, `must_change_on_first_login: true`). A tafsili code is created only when
`detail_groups` is sent. Gender, birth date and joining date are required to create a new personnel file.
Reply: `{person, employee, user, company, reused_person, account_created, roles, activation, hr_lead}`.
Registering the same person again changes nothing; a different e-mail for a person who already has a login is refused.

### `hr_onboarding.bootstrap_hr_lead(company, first_name, last_name, mobile, email, national_id?, activation?, gender?, birth_date?, date_of_joining?, request_id?)` — POST
System administrator only: creates the first HR lead (gets `HR Manager`) without any prior HR account. Audited as
`hr.first_lead_register`.

### `hr_onboarding.issue_temporary_password(party_profile)` — POST
New temporary password (shown once), forces a change at the next sign-in; audited, secret never stored in the log.

## hr and directives (administrator without an Employee)

`hr` endpoints (`save_report`, `list_reports`, `review_report`, `create_communication`, `list_communications`,
`list_team`) and `directives` endpoints (`options`, `save_draft`, `issue`, `start`, `report`, `review`, `transfer`, `close`, ...) now work for the administrator: a virtual actor row replaces the missing
Employee, the whole company is the team, `ASOUD Work Report.reporter` records the sender when there is no Employee,
and reports are routed to the manager pool when there is no direct manager. Nobody can review their own report.

## Errors summary

| Situation | Exception | Message (Persian) |
|---|---|---|
| Not signed in | `AuthenticationError` | ورود به حساب لازم است. |
| Missing role / foreign office | `PermissionError` | Not permitted / Company access denied |
| Temporary password pending | `PermissionError` | رمز عبور موقت شما باید ابتدا تغییر کند؛ … |
| Weak password, wrong current password, rate limit | `ValidationError` | reason in the sentence |
| Last administrator change | `PermissionError` | آخرین مدیر کل فعال سیستم … |
| Escalation by a delegate | `PermissionError` | reason in the sentence |

## Deployment

`bench --site <site> migrate` (new DocTypes `ASOUD Security Audit`, `ASOUD Account State`, `ASOUD Account Token`,
`ASOUD Office Role Assignment`; new fields on `ASOUD Settings`, `ASOUD Company Setup`, `ASOUD Role Definition`,
`ASOUD Party Profile`, `ASOUD Work Report`; patch `v0_18.ensure_security_roles_and_backfill` creates the roles
`ASOUD Office Creator` and `ASOUD Role Assigner` and backfills). Restart afterwards so the new `doc_events`,
`before_request` and `on_login` hooks load.
