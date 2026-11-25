# Office-bound access templates and user accounts

## Architecture and migration

Templates extend `ASOUD Role Definition` with optional `company`,
`template_permissions` and unique `template_key`. Native `Role Profile` remains
the technical identity; a new template has no base roles and is never attached
to users as a shared permission role. `ASOUD Access Assignment` adds optional
`company` and `employee`. `managed_role` is optional only for a valid scoped
assignment. Actual rights remain native `Custom DocPerm` on a deterministic
account/office `Role`. No parallel permission engine or core patch is introduced.

Deployment requires **`bench migrate`**, not manual SQL. No deployment is performed
by this change. No existing office, profile, assignment or user is converted,
rewritten or deleted. Existing companyless profiles are returned read-only.
`user_access.editor` remains available for inspection; the old companyless
`user_access.apply` mutation now rejects new global grants explicitly.

Only built-in `Administrator` has an unconditional office-membership bypass.
`System Manager` by itself no longer establishes membership of every office.
Existing explicit Company User Permissions, office role assignments, active
Employee membership and the existing restricted service-identity policy remain.
The native last-named-admin protection is unchanged.

## Common contract

Prefix: `asoud_erp.api.v1.access_profiles.`. All methods are authenticated and
require an existing `company`, office membership and either `Administrator` or
the existing `ASOUD Role Assigner` delegation (global or assigned in that office).
No Employee record is required for the administrator/delegate. Every specific
Employee or profile is checked against the requested office before use.
Read methods accept GET/POST; mutations accept POST only, with native CSRF.
Responses use the normal `message: {ok, data, meta:{api_version:'v1'}}` envelope.
Unauthorized calls return PermissionError (403); invalid inputs or stale data
return the normal Persian validation/conflict error. No offline queued grant writes.

| Method | Arguments | `data` |
| --- | --- | --- |
| `list_profiles` | company | profiles, catalog, examples |
| `get_profile` | company, name | profile |
| `save_profile` | company, title, grants; optional description, name, modified | saved profile |
| `delete_profile` | company, name, modified | deleted template name |
| `list_accounts` | company | active Employee rows, including department, account_status and available contact_methods (not contact values) |
| `get_account` | company, employee | employee, title, designation, company, user, legacy, profile, token, grants, catalog |
| `create_account` | company, employee; optional contact; method=mobile/email, invite=0 | account; optional activation |
| `save_account_access` | company, employee, grants, token; optional profile | account |
| `invite_account` | company, employee; optional registered=1 | activation-service response |
| `get_legacy_report` | company | assignments, profiles, notice |

Profile shape: `name,title,description,company,modified,readonly,grants`.
`grants` is a map of actual DocType to arrays of `read/create/write/delete`.
Missing actions revoke that account's previously copied matrix rights only.
Read is required for nonempty action selections. Unsupported keys/actions reject,
never silently disappear. Submit/cancel/amend and other advanced actions are not
granted by create/write. A non-root delegate cannot grant rights beyond his own
real permissions in that office.

Duplicate titles are rejected within one office (case insensitive). Different
offices may reuse a title. Updates require the returned `modified` token;
account updates require the assignment `token`. Company and User row locks
serialize competing changes. Native unique role/template keys prevent duplicates.

Deletion is restricted to an unused template in the same office. Legacy/global
profiles and templates referenced by accounts cannot be deleted. Detaching a
template in account access can retain its already-copied grants.

### Adding modules and documents

Register real DocTypes in `services/permission_catalog.py:MODULES`, or use the
app-side hook `asoud_office_permission_catalog = ["my_app.permissions.catalog_rows"]`.
A provider returns rows with `module`, `doctype`, `title`, optional `group` and
`actions` (a subset of read/create/write/delete). It cannot override existing rows.
Flutter reads this catalog; catalog-only additions need no Flutter code change.

Before adding a document or request, verify office ownership and enforcement in
lists, direct reads, writes and custom APIs. Only installed, company-bound DocTypes
with supported native operations are offered. Forms sharing one DocType don't
automatically gain separate privileges. Child-table and field-detail permissions
are not offered until the server can enforce them consistently.

## Account and application behavior

Account creation locks and links an existing active Employee; it never creates an
Employee or a Party Profile. The account initially has the native Employee role
plus an empty scoped grant role. No HR/accounting role is inferred from Designation.
The Company User Permission is created explicitly. No permanent Employee or
Department User Permission is introduced that would prevent a later legitimate
HR grant. Native personal access is still checked.

Omitting `contact` makes the server use the Employee's saved contact. With
`invite=1`, email delivers the login and one-time activation code; SMS delivers
the login and expiring temporary password (not returned to the client). SMS needs
an HTTPS POST gateway and email needs outgoing mail. Registered re-invites verify
that the current Employee contact still matches the login. Gateway acceptance does
not prove handset delivery. Existing explicit-contact clients remain compatible.

An existing login is not silently linked to a second Employee. Native HRMS v15
forbids a single login on two active Employees. The employer explicitly requires
**one shared login**, not independent accounts. That acceptance criterion is **open**:
the existing Party Profile also has one Company/Employee link and a globally unique
national identity. A reviewed extension of the existing identity/office links and
all affected personnel resolvers is required; neither invariant is bypassed here.

Invitations use existing activation services: configured outgoing email or an
existing one-time temporary-password response for mobile logins. Temporary passwords
are displayed once, never persisted by Flutter, and must be changed before normal
API use. No SMS delivery is invented. Without outgoing email, invite returns the
existing explanatory error. Creating without immediately inviting remains supported.

Home/settings replaces the roles tile at its existing location with
`پروفایل‌های دسترسی` → `AccessProfilesPage(company)`. User management remains a
separate tile → `OfficeUsersPage(company)`. Profile selection exists only in the
account details Access tab. Selection previews a union with manual selections;
only explicit Save writes it. Editing a template does not change any user grant.

## Server office boundary and supported matrix

Native wildcard permission/query hooks add a denial-only office boundary over
Frappe permissions for company-owned documents and employee-linked records.
Foreign document reads (including `frappe.client.get`) are denied. List filters,
personal records and same-office writes are scoped as well; changing company via
ordinary document editing is rejected for managed accounts. Existing workflow
record gates remain authoritative inside the office.

Only installed catalogue documents with an actual Company owner and native
supported operations are exposed as selectable template rows. Unavailable actions
are `—`, supported but ungranted actions are unchecked. Expand/collapse has no
grant side effect and parent rows never cascade rights.

### Explicitly not claimed as complete

- Shared masters with no office ownership, query reports, and field/child-table
  detail permissions are not exposed as fake selectable controls. Native field
  readers currently combine roles globally; office-scoped field controls need
  full reader coverage before exposure.
- Existing role-gated ASOUD business APIs and capability navigation still use
  their technical role policies. A native DocPerm alone does not yet unlock every
  specialist app API. No broad base role is inferred to conceal this gap.
- The accountant example is an optional, unsaved preview limited to installed,
  genuinely supported catalogue rights. It never overwrites an existing accountant
  profile and never assigns rights to users automatically. Reports not enforceable
  by the current office-scoped paths are omitted, not represented by fake grants.
- The legacy report is read-only. Resolving/migrating old global grants is an
  explicit manager-reviewed future action, not an automatic conversion.
- One shared login across two offices is required but not implemented. Tests with
  independent accounts prove only office-grant isolation, not this shared-login
  acceptance criterion. Do not deploy this partial feature as complete.

These limitations mean the entire requested specialist-permission experience must
not be advertised as fully finished or deployed yet.
