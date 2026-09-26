# Sales pipeline — `asoud_erp.api.v1.sales_orders`

Quotations, sales orders and delivery notes. Roles are the same as
[selling](selling.md). Each step is made from the previous one with ERPNext's
own mapper, so ERPNext tracks what is ordered, delivered and billed:

```
Quotation ──create_sales_order_from_quotation──▶ Sales Order ──create_delivery_note_from_order──▶ Delivery Note
                                                            └──create_sales_invoice_from("Sales Order")──▶ Sales Invoice
Delivery Note ──create_sales_invoice_from("Delivery Note")──▶ Sales Invoice
```

| Method | HTTP | Purpose |
| --- | --- | --- |
| `create_quotation(company, customer, items, transaction_date?, valid_till?, taxes_and_charges?, submit=0)` | POST | |
| `create_sales_order(company, customer, items, delivery_date, transaction_date?, taxes_and_charges?, submit=0)` | POST | direct order |
| `create_sales_order_from_quotation(quotation, delivery_date, submit=0)` | POST | from a submitted quotation |
| `create_delivery_note_from_order(sales_order, submit=0)` | POST | delivers what is not yet delivered; needs stock in the line warehouses |
| `create_sales_invoice_from(doctype, name, submit=0)` | POST | `doctype` ∈ Sales Order, Delivery Note; returns a [selling invoice object](selling.md#invoice-object) |
| `list_sales_documents(company, doctype, customer?, status?, from_date?, to_date?, …)` | GET | `doctype` ∈ Quotation, Sales Order, Delivery Note; rows carry `date` |
| `get_sales_document(doctype, name)` | GET | |
| `submit_sales_document(doctype, name)` · `cancel_sales_document(doctype, name)` | POST | |

Lines use the [selling line shape](selling.md#invoice-lines). The document
object has `doctype`, `customer`, `date`, totals, `status`, `docstatus` and
`items` with `delivered_qty` and back-links (`prevdoc_docname` = quotation,
`against_sales_order`). Quotations add `valid_till`; sales orders add
`delivery_date`, `per_delivered` and `per_billed`.

Continuing from a draft raises a `ValidationError`: submit it first.
