# Trial balance and general ledger — `asoud_erp.api.v1.report`

Accounting summaries of ERPNext `GL Entry` rows for one company. Both methods are
tenant scoped: the requested `company` must be one the caller may access, so a
User Permission on `Company` limits the ledger exactly as it does in ERPNext.

| Method | HTTP | Purpose |
| --- | --- | --- |
| `trial_balance(company, from_date, to_date, account?)` | GET | per-account opening/period/closing debit and credit plus totals |
| `general_ledger(company, from_date, to_date, account, party_type?, party?)` | GET | running-balance entries of one account and its descendants |

Roles: `System Manager`, `Accounts Manager`, `Accounts User` — checked with
`erp_documents.require_roles`, which is also enforced while tests run. `company`
is required and checked with `request_access.require_company`; a company the
caller cannot read raises `PermissionError` before any query runs.

`account`, when given, must belong to `company`; otherwise
`ValidationError`. `general_ledger` widens the account to its descendants, so a
group account returns the whole subtree. `from_date`/`to_date` are inclusive
Gregorian ISO dates and must not be inverted. Only one company per call: there is
no cross-company trial balance.

Nothing else is read from the caller-supplied company: party bank data
(`bank_name`, `iban`, `account_number`, `card_number`) never appears in these
responses. Use `asoud_erp.api.v1.personnel` for a person's own file.