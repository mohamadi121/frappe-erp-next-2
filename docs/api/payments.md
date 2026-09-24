# Payments — `asoud_erp.api.v1.payments`

Receipts and payments on ERPNext `Payment Entry`. Roles: System Manager,
Accounts Manager, Accounts User.

| Method | HTTP | Purpose |
| --- | --- | --- |
| `payment_options(company)` | GET | modes of payment with their company account, company bank accounts, currency |
| `list_outstanding_documents(company, party_type, party)` | GET | unpaid invoices of a party (`get_outstanding_reference_documents`) |
| `create_payment_entry(company, payment_type, party_type, party, amount, mode_of_payment, posting_date?, reference_no?, reference_date?, references?, remarks?, submit=0)` | POST | receipt or payment |
| `list_payment_entries(company, payment_type?, party?, from_date?, to_date?, limit_start, limit_page_length)` | GET | newest first |
| `get_payment_entry(name)` | GET | full entry with allocations |
| `submit_payment_entry(name)` / `cancel_payment_entry(name)` | POST | docstatus 0→1 / 1→2 |

## Creating a payment

- `payment_type`: `Receive` (money in) or `Pay` (money out).
- `party_type`: `Customer`, `Supplier` or `Employee`.
- `mode_of_payment` must have a default account for the company (Mode of
  Payment → Accounts); that account is the bank/cash side. The party side is
  the party's receivable/payable account from ERPNext.
- `references` (optional) allocate the amount to documents:

```json
[{"reference_doctype": "Sales Invoice", "reference_name": "ACC-SINV-2026-00012", "allocated_amount": 2530000}]
```

| party_type | allowed `reference_doctype` |
| --- | --- |
| Customer | Sales Invoice, Sales Order |
| Supplier | Purchase Invoice, Purchase Order |
| Employee | Expense Claim, Employee Advance |

The allocated total may not exceed `amount`; the rest stays as
`unallocated_amount` (an advance). Bank-type modes of payment need
`reference_no` and `reference_date` (ERPNext rule).

Only company-currency parties and accounts are supported for now; other
currencies are rejected with a clear message.

## Payment object

```json
{
  "name": "ACC-PAY-2026-00031", "company": "Tabaan", "payment_type": "Receive",
  "posting_date": "2026-09-24", "mode_of_payment": "Cash", "party_type": "Customer",
  "party": "CUST-001", "party_name": "...", "paid_from": "Debtors - T", "paid_to": "Cash - T",
  "paid_amount": 2530000, "received_amount": 2530000, "unallocated_amount": 0,
  "reference_no": "", "reference_date": "", "remarks": "", "status": "Submitted", "docstatus": 1,
  "references": [{"reference_doctype": "Sales Invoice", "reference_name": "...", "total_amount": 2530000,
                  "outstanding_amount": 2530000, "allocated_amount": 2530000}]
}
```
