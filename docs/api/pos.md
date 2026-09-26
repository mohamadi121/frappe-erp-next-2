# Point of sale — `asoud_erp.api.v1.pos`

ERPNext POS. It reuses ERPNext's own point-of-sale page functions (profile
access, opening voucher, item search) and closing flow. When a session closes,
ERPNext consolidates its POS invoices into regular Sales Invoices.

Standard permissions apply. Opening and closing entries need their ERPNext
rights (by default Sales Manager / System Manager), POS invoices need Accounts
User/Manager, and the user must be allowed on the POS Profile (its
*Applicable for Users*, when set).

```
create_pos_session ─▶ create_pos_invoice … ─▶ close_pos_session ─▶ consolidated Sales Invoice(s)
```

| Method | HTTP | Purpose |
| --- | --- | --- |
| `pos_options(company)` | GET | profiles the user may use (warehouse, price list, currency, default customer, payment modes) and the user's open session |
| `get_pos_items(pos_profile, search_term?, item_group?, start=0, page_length=40)` | GET | items with price and stock (ERPNext POS search, also by barcode) |
| `get_open_pos_session(pos_profile?)` | GET | the user's open POS Opening Entry, or `null` |
| `create_pos_session(pos_profile, opening_balances?)` | POST | `opening_balances`: `[{"mode_of_payment", "amount"}]`; one open session per profile |
| `create_pos_invoice(pos_profile, items, payments, customer?)` | POST | submitted, paid invoice in the open session; stock leaves the profile warehouse; `payments`: `[{"mode_of_payment", "amount"}]`; overpaid cash comes back as `change_amount` |
| `list_pos_invoices(pos_session)` | GET | invoices of that session only, oldest first (open: ERPNext's session query; closed: the closing entry's invoices) — `name`, `customer`, `grand_total`, `posting_date`, `is_return` |
| `close_pos_session(pos_session, closing_balances?)` | POST | counted amount per mode (default: expected); returns the reconciliation (`opening_amount`, `expected_amount`, `closing_amount`, `difference`) |

## Site configuration

A **POS Profile** per till with company, warehouse, selling price list, write-off
account and cost center, and at least one payment mode whose Mode of Payment has
an account for the company.
