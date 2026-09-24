# Stock — `asoud_erp.api.v1.stock`

Items, quantities and stock movements. Quantities come from ERPNext `Bin`;
valuation and stock ledger postings stay with the `Stock Entry` controller.

Read roles: System Manager, Stock Manager, Stock User, Item Manager, Accounts
Manager, Purchase Manager/User, Sales Manager/User. Write roles (`save_item`,
stock entries): System Manager, Stock Manager, Stock User, Item Manager.

| Method | HTTP | Purpose |
| --- | --- | --- |
| `stock_options(company)` | GET | warehouses, item groups, UOMs, default warehouse, entry purposes |
| `list_items(company, search?, item_group?, stock_only=0, limit_start, limit_page_length)` | GET | enabled, non-template items with `actual_qty` across the company's warehouses |
| `get_item(company, item_code)` | GET | item, UOM conversions, selling rate, last purchase rate, quantities per warehouse |
| `save_item(item_name, item_group, stock_uom, item_code?, is_stock_item=1, description?, standard_rate?, disabled=0)` | POST | create, or update name/group/description/stock flag/disabled |
| `stock_balance(company, warehouse?, item_code?, limit_start, limit_page_length≤200)` | GET | `Bin` rows: actual, projected, reserved, ordered qty, valuation rate, stock value |
| `create_stock_entry(company, purpose, items, posting_date?, remarks?, submit=0)` | POST | receipt, issue or transfer |
| `list_stock_entries(company, purpose?, from_date?, to_date?, …)` · `get_stock_entry(name)` | GET | |
| `submit_stock_entry(name)` · `cancel_stock_entry(name)` | POST | |

## Stock entry lines

| purpose | each line needs |
| --- | --- |
| `Material Receipt` | `t_warehouse`; optional `rate` = valuation rate |
| `Material Issue` | `s_warehouse` |
| `Material Transfer` | `s_warehouse` and `t_warehouse` |

```json
[{"item_code": "ITM-001", "qty": 10, "rate": 120000, "t_warehouse": "Stores - T"}]
```

A line whose warehouses do not match the purpose is rejected before ERPNext is
called. Issuing more than is on hand fails with ERPNext's negative stock error
unless negative stock is allowed in Stock Settings.

`save_item` with `standard_rate` on creation makes ERPNext create the selling
Item Price. `stock_uom` cannot change after transactions exist (ERPNext rule),
so updates keep it.
