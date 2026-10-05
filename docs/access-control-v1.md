# ASOUD personnel access contract (v1)

ERPNext v15 remains the authority for authentication and authorization. UI
labels and the `employee_roles` JSON field are metadata and must never be used
as permission checks.

## Personnel role mapping

| ASOUD key | ERPNext role |
| --- | --- |
| `office_manager` | `Accounts Manager` |
| `accountant` | `Accounts User` |
| `salesperson` | `Sales User` |
| `marketer` | `Sales User` |
| `cashier` | `Accounts User` |
| `petty_cash_custodian` | `Accounts User` |

Operational labels that are absent from this table do not grant a Frappe role.
The server silently ignores unknown labels when normalizing legacy profile data
and rejects a provisioning request if no supported access role remains.

## Current user

`POST /api/method/asoud_erp.api.v1.auth.current_user`

The endpoint requires an authenticated Frappe session and returns the standard
ASOUD v1 envelope. Its data contains `user_id`, `full_name`, authoritative
Frappe `roles`, and an optional active `employee` object with `name`,
`employee_name`, and `company`.

## Employee access provisioning

`POST /api/method/asoud_erp.api.v1.auth.sync_employee_access`

Only a `System Manager` may call this endpoint. Required inputs are
`party_profile`, a unique login `email`, and `personnel_roles`. The operation:

1. verifies that the ASOUD profile is linked to an ERPNext Employee;
2. creates or reuses an enabled System User;
3. applies only the allow-listed ERPNext roles and removes stale ASOUD-managed
   roles;
4. links `Employee.user_id` to the User;
5. enables ERPNext's Employee and Company User Permissions; and
6. stores canonical ASOUD role keys on the party profile.

Flutter must use this context to shape navigation, but every API remains
responsible for enforcing permissions on the server.

## Role gates and company scope

Two gates, always both, on every company-scoped method:

1. `erp_documents.require_roles(...)` for the Frappe roles a method accepts. It is
   the same check as `frappe.only_for`, except that it is **not** skipped when
   `frappe.flags.in_test` is set, so an integration test can prove that a role is
   refused. `frappe.only_for` must not be used in `asoud_erp/api/v1`.
2. `request_access.require_company(company)` with the `company` the method acts
   on, called before any query. A manager needs read access to that Company;
   everyone else needs an active Employee in it. This is what makes a User
   Permission on `Company` a real tenant boundary, because `frappe.get_all()` and
   `frappe.db.sql()` set `ignore_permissions=True` and therefore never apply
   User Permissions on their own.

A method whose `company` argument is optional must not fall back to "every
company": an absent company is either refused or resolved from the record the
method already resolved, never from a site-wide list. Records that are genuinely
site-wide (`ASOUD Settings`, `ASOUD Detail Group`, the role catalog) carry no
company field and are documented as such in their `docs/api/*.md` page.

Bank details (`bank_name`, `iban`, `account_number`, `card_number`,
`account_holder`) live on the ERPNext Employee form. No ASOUD API returns them to
a role that is not a personnel manager, and `personnel.update_personnel` refuses
them outright.

## Employee is HR-only master data

`ASOUD Party Profile` with the `Employee` role is the party view of an ERPNext
`Employee`. Two rules follow:

- Only `System Manager` and `HR Manager` may save such a profile through
  `party.save_party`, which writes the Employee and mirrors the `PERSONAL_FIELDS`
  subset onto it. Everyone else keeps `PermissionError`, even for a party in their
  own company.
- `party.list_parties` returns `bank_name`, `iban`, `account_number`,
  `card_number` and `account_holder` only to `System Manager` and
  `Accounts Manager`; other roles get the profile without those keys.

The sanctioned personnel path stays `personnel.update_personnel`: an allow-list,
a revision check, an idempotency receipt and an audit record.
