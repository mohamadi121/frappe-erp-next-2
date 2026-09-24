# Buying — `asoud_erp.api.v1.buying`

Purchase orders, receipts and supplier invoices. Roles: System Manager,
Purchase Manager, Purchase User, Accounts Manager, Accounts User.

Documents are either created directly or mapped with ERPNext's own mappers, so
ERPNext tracks what is already ordered, received and billed:

```
Material Request ──make_purchase_order──▶ Purchase Order ──make_purchase_receipt──▶ Purchase Receipt
                                                        └──make_purchase_invoice──▶ Purchase Invoice
```

| Method | HTTP | Purpose |
| --- | --- | --- |
| `buying_options(company)` | GET | suppliers, purchase tax templates, buying price list, warehouses |
| `create_purchase_order(company, supplier, items, schedule_date, transaction_date?, taxes_and_charges?, submit=0)` | POST | direct order |
| `create_purchase_order_from_request(material_request, supplier, submit=0)` | POST | orders what is not yet ordered from a submitted purchase request |
| `create_purchase_receipt_from_order(purchase_order, submit=0)` | POST | receives what is not yet received |
| `create_purchase_invoice(company, supplier, items, posting_date?, bill_no?, bill_date?, taxes_and_charges?, update_stock=0, submit=0)` | POST | direct supplier invoice |
| `create_purchase_invoice_from_order(purchase_order, bill_no?, bill_date?, submit=0)` | POST | bills what is not yet billed |
| `list_purchase_documents(company, doctype, supplier?, status?, from_date?, to_date?, …)` | GET | `doctype` ∈ Purchase Order, Purchase Receipt, Purchase Invoice; rows carry `date` |
| `get_purchase_document(doctype, name)` | GET | |
| `submit_purchase_document(doctype, name)` · `cancel_purchase_document(doctype, name)` | POST | |

Lines use the same shape as [selling](selling.md#invoice-lines); a line without
`rate` is priced from the buying price list.

The returned object has `doctype`, supplier and totals, `items` (with
`material_request` / `purchase_order` back-links), and per type:
Purchase Order `transaction_date`, `schedule_date`, `per_received`,
`per_billed`; Purchase Receipt/Invoice `posting_date`; Purchase Invoice
`bill_no`, `bill_date`, `due_date`, `outstanding_amount`.

Pay a supplier invoice with [`payments.create_payment_entry`](payments.md)
(`payment_type=Pay`, `party_type=Supplier`).
