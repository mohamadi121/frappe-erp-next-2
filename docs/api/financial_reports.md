# Financial reports — `asoud_erp.api.v1.financial_reports`

ERPNext's standard reports, run by Frappe's report runner. Each report keeps its
own ERPNext role list (e.g. Balance Sheet: Accounts User, Accounts Manager,
Auditor; Stock Balance: Stock User, Accounts Manager).

| Method | HTTP | Purpose |
| --- | --- | --- |
| `list_financial_reports()` | GET | available `key`s and their ERPNext report names |
| `run_financial_report(company, report, from_date?, to_date?, report_date?, periodicity=Yearly, party?, warehouse?, item_code?)` | GET | columns and rows |

| `report` | ERPNext report | Required | Optional |
| --- | --- | --- | --- |
| `receivable` | Accounts Receivable (ageing 30/60/90/120 by due date) | `report_date` | `party` (customer) |
| `payable` | Accounts Payable | `report_date` | `party` (supplier) |
| `profit_and_loss` | Profit and Loss Statement | `from_date`, `to_date` | `periodicity` ∈ Monthly, Quarterly, Half-Yearly, Yearly |
| `balance_sheet` | Balance Sheet (accumulated) | `from_date`, `to_date` | `periodicity` |
| `stock_balance` | Stock Balance | `from_date`, `to_date` | `warehouse`, `item_code` |

Response: `{"report", "report_name", "filters", "columns": [{"fieldname", "label", "fieldtype", "options"}], "rows": [...], "truncated"}`.
Rows are ERPNext's own dicts (statements carry `account`, `indent` and one key
per period); at most 2000 rows are returned.
