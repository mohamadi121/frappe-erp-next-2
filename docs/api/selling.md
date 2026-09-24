# Selling — `asoud_erp.api.v1.selling`

Sales invoices on ERPNext `Sales Invoice`. Roles: System Manager, Accounts
Manager, Accounts User, Sales Manager, Sales User; ERPNext document permissions
apply on top.

ERPNext does the business work: party account and due date
(`set_missing_values`), price list rates and pricing rules, the default or
chosen tax template (`set_taxes`), totals, GL postings on submit.

| Method | HTTP | Purpose |
| --- | --- | --- |
| `selling_options(company)` | GET | customers, tax templates, selling price list, warehouses, currency |
| `get_item_price(company, item_code, customer?, qty=1, uom?, posting_date?)` | GET | ERPNext line pricing for one item |
| `create_sales_invoice(company, customer, items, posting_date?, due_date?, taxes_and_charges?, remarks?, update_stock=0, submit=0)` | POST | draft or submitted invoice |
| `list_sales_invoices(company, status?, customer?, search?, from_date?, to_date?, limit_start=0, limit_page_length=20)` | GET | newest first; max 100 per page |
| `get_sales_invoice(name)` | GET | full invoice |
| `submit_sales_invoice(name)` / `cancel_sales_invoice(name)` | POST | docstatus 0→1 / 1→2 |
| `create_sales_return(name, submit=0)` | POST | credit note for the whole invoice (`make_sales_return`) |

## Invoice lines

```json
[{"item_code": "ITM-001", "qty": 2},
 {"item_code": "SRV-010", "qty": 1, "rate": 1500000, "discount_percentage": 10, "uom": "Nos", "warehouse": "Stores - T"}]
```

- `qty` > 0; up to 200 lines.
- Without `rate` the line is priced from the selling price list (and pricing
  rules); with `rate` the given rate is kept.
- `warehouse` matters only with `update_stock=1` (sell and deliver in one step).
- Without `taxes_and_charges`, ERPNext applies the company's **default** Sales
  Taxes and Charges Template, so `grand_total` can exceed the sum of the lines.
  Show `net_total`, `total_taxes_and_charges` and `grand_total` separately.
  Buying documents behave the same with Purchase Taxes and Charges Templates.

## Invoice object

```json
{
  "name": "ACC-SINV-2026-00012", "company": "Tabaan", "customer": "CUST-001", "customer_name": "...",
  "posting_date": "2026-09-24", "due_date": "2026-10-24", "currency": "IRR",
  "is_return": 0, "return_against": "", "taxes_and_charges": "VAT 10% - T",
  "net_total": 2300000, "total_taxes_and_charges": 230000, "discount_amount": 0,
  "grand_total": 2530000, "rounded_total": 2530000, "outstanding_amount": 2530000,
  "status": "Unpaid", "docstatus": 1, "remarks": "",
  "items": [{"item_code": "...", "item_name": "...", "qty": 2, "uom": "Nos", "price_list_rate": 1000000,
             "discount_percentage": 0, "rate": 1000000, "amount": 2000000, "warehouse": ""}],
  "taxes": [{"description": "VAT", "rate": 10, "tax_amount": 230000}]
}
```

`status` is ERPNext's: `Draft`, `Unpaid`, `Overdue`, `Partly Paid`, `Paid`,
`Return`, `Credit Note Issued`, `Cancelled` (also valid `list_sales_invoices`
filters).

## Errors

- Unknown customer or item, missing price with no `rate`, closed fiscal year,
  missing receivable account → `ValidationError` with ERPNext's message.
- Cancelling an invoice that has payments linked → ERPNext `LinkExistsError`
  (unlink or cancel the payment first).
