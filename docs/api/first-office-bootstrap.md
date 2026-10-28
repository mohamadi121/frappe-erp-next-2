# First-office bootstrap (account-only HR lead)

This additive flow does not change `hr_onboarding.register_personnel` or create an
Employee/Party Profile. Complete the personnel file later through HR.

All endpoints are POST under `asoud_erp.api.v1.first_office_setup`, require an
active System Manager, company access, and the company recorded in
`ASOUD Settings.first_office_company`. Responses use `success(data)`.

## `status(company)`

Returns `{company, hr_lead: null | {full_name, username, role_title},
hr_ready: bool, completed: bool}`. No password or technical email is returned.
Read-only, online; no offline write queue.

## `create_hr_lead(company, full_name, username, contact, temporary_password)`

Requires a saved office and an enabled linked native Fiscal Year. Full name is
required (up to 60 characters); username is 3–40 ASCII letters/digits/underscore,
starts with a letter and is case-insensitive. Contact is either an Iranian mobile
or a real email, not both required. Password is 8–128 characters, not trimmed.
Only creates a new native System User; never upgrades, overwrites or resets an
existing account. Duplicate identity and protected usernames are rejected.
Missing name, username, contact or password arguments receive the same Persian
field validation as empty values. Numeric-only/repeated-character passwords are
rejected, and the native site password-strength policy is also enforced before writes.
Validation errors name the field: «نام کاربری قبلاً برای حساب دیگری ثبت شده است؛ نام دیگری انتخاب کنید.»,
«ایمیل تماس قبلاً برای حساب دیگری ثبت شده است.»,
«شماره موبایل قبلاً برای حساب دیگری ثبت شده است.»,
«شماره موبایل یا ایمیل را وارد کنید.» and «رمز موقت ضعیف است؛ از حروف و نویسه‌های متنوع استفاده کنید.».

Mobile-only accounts use a random internal `@users.asoud.invalid` native User ID;
it is not a contact email, verified identity or deliverable address. Outgoing mail
to this namespace is blocked, recovery by email is unavailable. Native username
login is enabled in System Settings when this account is created (no custom auth).
Only native HR Manager is granted, with Company User Permission. No System Manager,
Employee, personnel file or payroll role is granted. Password uses native hashing,
must be changed at first login, and expires after 72 hours. Permanent password
policy is unchanged. Hand the initial credentials to the recipient securely;
there is no demo invitation code or claim of SMS/email delivery.

Locks the setup row; an existing lead returns status, never a new password. An
ambiguous network response is resolved by reloading status before retrying.
User creation, permissions and setup pointer are one transaction; exceptions
roll back. Secret never goes in audit, offline storage or response.

## `complete(company)`

Rechecks saved office, administrator/company access and active fiscal year, then
stores completion and selects the office. Creating the first HR account is optional:
completion does not require `hr_ready` or create/alter any User, role or permission.
Existing HR accounts remain unchanged. Returns status with
`completed: true`. Repeat is safe. App enters home only after this acknowledgement.
The Flutter setup flow proceeds from fiscal year directly to final review; HR
provisioning is no longer a required setup screen. Progress is based on saved state.

## Deployment / migration

`bench migrate` adds read-only `first_hr_user` (Link User) and
`bootstrap_completed` (Check) to ASOUD Company Setup. Controller protects these
from ordinary document writes. Migration does not infer a lead from old employees
or invent completion. Sites without a first-office marker retain their routing.
For a marked first office, login resumes setup until explicit completion.

Errors are Persian: missing fiscal year, unavailable role, invalid identity,
duplicate username/contact, missing migration and missing privilege. No invitations
or contact verification are fabricated. Tests were not run at the user's request;
native site integration and device visual verification remain deployment checks.
