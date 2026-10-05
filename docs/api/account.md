# Chart of accounts — `asoud_erp.api.v1.account`

ERPNext `Account` plus the ASOUD coded chart: a manual account number per level,
and floating details presented as terminal rows under their mapped account.

| Method | HTTP | Roles | Purpose |
| --- | --- | --- | --- |
| `list_accounts(company)` | GET | A, M, U | coded accounts of one company plus `DETAIL::` rows for floating details |
| `preview_next_code(company, level, parent_account?)` | GET | A, M, U | the next free account number |
| `create_account(company, account_name, level, …)` | POST | A, M | creates an account; `level` ∈ Group, General, Ledger, Detail |
| `import_accounts(company, rows)` | POST | A, M | 1–500 rows, applied atomically |
| `preview_chart_template(company, template?)` | GET | A, M, U | the `Iran Standard` template rows, nothing written |
| `apply_chart_template(company, template?)` | POST | A, M | creates the template's accounts; refused over existing coded accounts |
| `update_account(company, account, account_name, …)` | POST | A, M | renames, re-parents, disables, sets level and detail groups |
| `delete_account(company, account)` | POST | A, M | deletes an unused leaf account |

Roles: A = `Accounts Manager`, U = `Accounts User`, both with `System Manager`.

## Company scope

`company` is required on every method and is checked with
`request_access.require_company` before anything is read or written, so a User
Permission on `Company` decides what the chart of accounts shows and what it may
change. A company the caller cannot read raises `PermissionError`; the account
list of a foreign company is never returned.

`account` must belong to `company`; the pseudo id `DETAIL::<detail>::<account>` is
resolved through the company's own account mapping. `delete_account` refuses an
account with children or posted GL entries, and an account with children can never
become terminal.

Account numbers are unique per company; ERPNext's own Account validation still
applies to every create and update.

## Detail groups and floating details

`asoud_erp.api.v1.detail_group` manages the `ASOUD Detail Group` catalogue and the
per-company `ASOUD Account Mapping` rows
(`list_detail_groups`, `save_detail_group`, `disable_detail_group`,
`seed_default_detail_groups`, `list_account_mappings`, `save_account_mapping`).
`asoud_erp.api.v1.floating_detail` manages `ASOUD Floating Detail`
(`preview_next_detail_code`, `list_floating_details`, `create_floating_detail`,
`link_floating_detail`, `disable_floating_detail`).

Neither DocType has a `company` column: a detail group is a site-wide catalogue of
*kinds* of detail, and a floating detail is a reusable value. The tenant boundary is
therefore the company of the record a detail is attached to:

- `list_account_mappings` and `save_account_mapping` take `company` and check it
  with `require_company`, because `ASOUD Account Mapping` does carry a company.
- `create_floating_detail(linked_doctype, linked_document)` and
  `link_floating_detail(name, party_profile)` check the **linked** record's company
  when that DocType has one, and refuse a foreign company with `PermissionError`.
  A floating detail may therefore not be attached to another company's party.
- `preview_next_detail_code`, `list_floating_details` and `disable_floating_detail`
  take no company and are site-wide by construction.