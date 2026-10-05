# Accounting vouchers — `asoud_erp.api.v1.voucher`

Accounting vouchers (`ASOUD Accounting Voucher`): draft voucher creation,
review and workflow approval translating approved vouchers into ERPNext
`Journal Entry` documents.

| Method | HTTP | Roles | Purpose |
| --- | --- | --- | --- |
| `list_vouchers(company, status?, search?)` | GET | System Manager, Accounts Manager, Accounts User | lists vouchers of one company |
| `save_voucher(company, posting_date, lines, description?, name?)` | POST | System Manager, Accounts Manager, Accounts User | creates or updates a draft voucher |
| `submit_for_approval(name)` | POST | System Manager, Accounts Manager, Accounts User | advances draft/rejected voucher to Pending Approval |
| `approve_voucher(name)` | POST | System Manager, Accounts Manager | approves voucher and creates/submits Journal Entry |
| `reject_voucher(name, reason)` | POST | System Manager, Accounts Manager | rejects voucher with required reason |

## Company scope

Every voucher endpoint enforces company access via `request_access.require_company`:

- `list_vouchers` and `save_voucher` check `require_company(company)` for the requested company.
- `submit_for_approval`, `approve_voucher`, and `reject_voucher` resolve the voucher document and verify `require_company(doc.company)` before modifying state.
- Foreign company vouchers cannot be enumerated or acted upon by users restricted by a Company User Permission.
