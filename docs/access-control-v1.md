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
