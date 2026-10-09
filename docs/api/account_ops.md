# Account operations — `asoud_erp.api.v1.auth`

The login account behind a personnel profile: «فعال/غیرفعال کردن حساب»,
«ارسال مجدد دعوت» and «مشاهده سوابق ورود», plus the access metadata the ⋮ menu
shows («سطح دسترسی»). Every value is read from the standard Frappe records —
`User`, `User Permission`, `Module Def`, `Activity Log`, `tabSessions` — so a
change here is visible in Frappe's own user list, roles page and login feed. No
parallel account table exists in this app.

| Concern | Native record |
| --- | --- |
| enabled / disabled | `User.enabled` |
| ending an open session | `frappe.sessions.clear_sessions(user)` |
| login history | `Activity Log` with `operation = Login` / `Logout` |
| open sessions | `tabSessions` (device and IP only, never the `sid`) |
| what the login may see | `Module Def` minus `User.get_blocked_modules()` |
| data scope | `User Permission` rows of the login |

**Access.** HR Manager / System Manager of the profile's company, checked with
`services.erp_documents.require_roles` and `services.request_access.require_company`.
An employee calling any of these methods gets `PermissionError`; another
company's HR Manager gets `PermissionError` as well. Privileged logins
(`System Manager`, `HR Manager`, Administrator, Guest) are refused here and stay in
system administration.

**The personnel file is never touched.** These methods do not change the
Employee, its status, department or any ASOUD Personnel Record; they only flip
`User.enabled` and end sessions. Unlinking a login from an Employee is a separate,
system-administration action and is deliberately not exposed in this API.

## Reading

| Method | HTTP | Purpose |
| --- | --- | --- |
| `get_employee_access(party_profile)` | GET | the ⋮ menu payload of a profile: login, enabled, personnel roles, `access_level`, `modules`, `data_scope` |
| `get_account_status(party_profile)` | GET | the account state alone, for a refresh after a change |
| `get_login_history(party_profile, limit=20)` | GET | `last_login`, `last_ip`, recent login/logout events and the open sessions |
| `list_employee_invitations(company)` | GET | invitation log of a company |

### Account status

```json
{"user": "employee@example.com", "enabled": 1, "has_logged_in": true,
 "last_login": "2026-02-03 09:15:00", "last_ip": "5.62.9.10",
 "can_resend_invitation": false,
 "roles": ["Employee", "Accounts User"],
 "modules": ["Accounts", "ASOUD ERP", "HR", "…"],
 "data_scope": [{"allow": "Company", "value": "Tabaan", "apply_to_all_doctypes": 1},
                {"allow": "Department", "value": "Sales - T", "apply_to_all_doctypes": 1},
                {"allow": "Employee", "value": "HR-EMP-00042", "apply_to_all_doctypes": 1}],
 "employee": "HR-EMP-00042", "access_level": "user"}
```

- `enabled` is `User.enabled` as `0`/`1`; a profile without a login reports `0`
  with `user: ""`.
- `has_logged_in` is `User.last_login` being set, and drives
  `can_resend_invitation` (see below).
- `roles` are the Frappe roles the login actually holds; `access_level` is
  `manager` for a supervisory role (`services.access_policy.MANAGER_ROLES`),
  `user` for any other role and `none` without one.
- `modules` are the installed `Module Def` entries minus the ones Frappe hides
  for this login (Module Profile or `User.block_modules`), so the app can hide
  menus the login cannot reach.

### Login history

```json
{"last_login": "2026-02-03 09:15:00", "last_ip": "5.62.9.10",
 "events": [{"datetime": "2026-02-03 09:15:00", "operation": "Login", "status": "Success", "ip": "5.62.9.10"},
            {"datetime": "2026-02-01 07:00:00", "operation": "Login", "status": "Failed", "ip": "5.62.9.11"}],
 "sessions": [{"device": "Chrome / Android", "ip": "5.62.9.10",
               "last_active": "2026-02-03 09:20:00", "status": "Active"}]}
```

`events` are the native Activity Log rows newest first, at most `limit` of them
(clamped to 1…50, default 20). `sessions` carries the device label and the IP of
each row in `tabSessions`; the `sid`, the csrf token and the rest of the stored
session blob are never returned.

## Writing

| Method | HTTP | Purpose |
| --- | --- | --- |
| `set_account_enabled(party_profile, enabled, request_id)` | POST | «فعال/غیرفعال کردن حساب» |
| `send_employee_invitation(party_profile, email, personnel_roles, request_id, access_matrix, method)` | POST | invite or re-send an invitation |
| `sync_employee_access(party_profile, email, personnel_roles, access_matrix)` | POST | create/link the login and apply the allow-listed ERPNext roles |

`enabled` is a truthy/falsy value; `1` re-enables, `0` disables. A disabled
login's open sessions are cleared in the same call (`clear_sessions`), which also
logs the logout out. `request_id` (8…100 characters) is stored as an **ASOUD
Personnel Operation** receipt with a fingerprint of the party, the action and the
requested state:

- the same `request_id` and the same arguments returns the current status with
  `replayed: true` and writes nothing again (offline retries are safe);
- the same `request_id` with different arguments is refused with
  `ValidationError` (`Request ID conflict`);
- no login yet, your own login, a privileged login, or another company is a
  `ValidationError` / `PermissionError` before any write.

### «ارسال مجدد دعوت» is refused after the first login

`send_employee_invitation` refuses (Persian `ValidationError`) when the login
already exists **and** `User.last_login` is set:

> ارسال مجدد دعوت برای این حساب ممکن نیست؛ کاربر قبلاً وارد سامانه شده است.
> برای حساب فعال، از «بازنشانی رمز عبور» در تنظیمات کاربر استفاده کنید.

A new login, or one that was invited but never signed in, may be invited again.
`can_resend_invitation` in the status payload tells the client which case it is
before the button is pressed.

`sync_employee_access` keeps the Employee's Company and Department in step with
native `User Permission` rows (`apply_to_all_doctypes = 1`) after every successful
call, so the login's data scope matches the personnel file.

## Tests

- `asoud_erp/tests/test_account_status.py` and `test_access_policy.py` — the
  pure rules (resend refusal, module hiding, event order, session fields, limits).
- `asoud_erp/integration_tests/test_account_ops.py` — the live records: disabling
  keeps the HR file and clears the sessions, replay and conflict of a request id,
  roles/modules/data scope, the resend refusal, login history without secrets,
  the Employee and other-company refusals, and the manager photo in the
  personnel file.