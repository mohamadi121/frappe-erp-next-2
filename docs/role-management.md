# Role management

The mobile role manager uses native Frappe v15 **Role Profile** and its **Has Role**
children. It does not duplicate the permission engine, change standard Role or
DocPerm records, or assign privileges to users merely by creating a definition.

`ASOUD Role Category` and `ASOUD Role Definition` store presentation metadata:
category, title, immutable code, description, availability and an optional parent.
The parent is classification only, not permission inheritance or HR supervision.
Native profiles use `ASOUD:<CODE>` and are site-wide. Company/Employee User
Permissions and explicit user/Employee linkage remain separate responsibilities.

## Deployment

Install/update the extension, then run `bench --site <site> migrate` and restart
the site's processes normally. This synchronizes the two new metadata DocTypes
and the User validation hook. No migration, server deployment or tests were run
as part of this change. Templates are never installed automatically.

## API

All endpoints under `asoud_erp.api.v1.role_management` require System Manager.

- `catalog`: categories, managed definitions, available native roles and template suggestions.
- `create_category(payload)`: explicit category creation.
- `save_role(payload)`: native profile + metadata in one transaction; existing
  definitions require both metadata and profile modification timestamps.
- `apply_templates(codes)`: selected templates only; existing definitions are
  skipped, never overwritten; unavailable base roles reject the operation.
- `permission_preview(roles)`: direct rules from resolved Frappe metadata, including
  custom overrides, field permission levels and owner-only restrictions. This is
  not a claim about any specific user's effective access.

The mobile client can persist category/role drafts on the device when offline.
Storage is scoped by server and authenticated user; unsigned preview data has a
separate namespace and is never automatically adopted by another account.
Drafts are sent only through an explicit sync action, categories and parent
roles first, using the original modification timestamps. Authorization,
validation and conflict errors retain the unsent draft; they are not reported
as remote success. Applied entries are removed individually to allow retry.
No local draft is treated as an active security grant. Editing a profile used by existing users invokes Frappe's native
propagation when its base roles change. The mobile single-page form edits basic
metadata only, preserving existing base roles without re-saving the native
profile. New manual profiles may have no base roles and grant no access;
standard permission-bearing profiles can be created from templates.
Disabling an assigned definition is
rejected. A User validation hook prevents assignment of a disabled managed profile.
Native role rights are additive. In particular Accounts User is not marketed as
a treasury-only role, and System Manager is explicitly labelled as broad access.

Existing authentication provisioning APIs are unchanged. Assigning these new
profiles to users from a new mobile user-management screen is not part of this
change; a System Manager can assign an active profile using native Frappe User.

References: Frappe v15 `core/doctype/role_profile/role_profile.py`,
`role_profile.json`, `has_role/has_role.json`, and `frappe/permissions.py`.
