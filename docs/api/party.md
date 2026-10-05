# Parties — `asoud_erp.api.v1.party`

`ASOUD Party Profile` is the master record for customers, suppliers, employees
and shareholders. `Employee` stays authoritative for the HR master fields of a
person; the profile carries the party view of the same person (roles, contact,
address, bank details).

| Method | HTTP | Purpose |
| --- | --- | --- |
| `list_parties(company, search?, role?)` | GET | profiles of one company, newest first (max 200) |
| `save_party(party_type, display_name, roles, …)` | POST | creates or updates a profile; `name` updates, otherwise creates |
| `disable_party(name)` | POST | sets `disabled = 1`; never deletes |

Roles: `System Manager`, `Accounts Manager`, `Accounts User`.

### Personnel parties

A profile whose `roles` contain `Employee` is a personnel record: it owns the
linked ERPNext `Employee`. `save_party` therefore refuses it unless the caller
holds `System Manager` or `HR Manager` — the same roles
[`personnel.update_personnel`](personnel_file.md) accepts — and it raises
`PermissionError` before applying anything. This is the separation-of-duties
rule: an accountant maintains customers and suppliers, an HR manager maintains
people. An accounting role keeps editing non-personnel parties; to change an
employee's designation, department, birth date, date of joining or contact data,
use `update_personnel`, whose `PERSONAL_FIELDS` allow-list is the only sanctioned
path onto `Employee`.

Only `PERSONAL_FIELDS` are mirrored from the profile onto the Employee; every
other party argument stays on the profile. The Employee write itself goes
through Frappe's own permission check, so the caller's Employee write right and
Company User Permission apply as well.

## Listing

`company` is **required** on `list_parties` and is checked with
`request_access.require_company`, so a User Permission on `Company` limits the
list to that company. There is no site-wide party list; a caller that may read
several companies calls the endpoint once per company.

`role` is one of `Customer`, `Supplier`, `Employee`, `Shareholder`, `Other`;
`search` matches `display_name`, `national_id` or `mobile`.

### Bank details

`bank_name`, `iban`, `account_number`, `card_number` and `account_holder` are
returned **only** to `System Manager` and `Accounts Manager`, the roles that own
the party master and pay from it. For every other role (`Accounts User`, and all
personnel roles) those keys are absent from the response — the rest of the
profile is unaffected. This follows the personnel contract: bank data is
manager-only, and the bank account of an employee is never part of any party
API response.