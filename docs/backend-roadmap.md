# Backend module map and roadmap

This is the contract between the Flutter client and the ASOUD backend. Each row
names the app screen, the API module that serves it, and the ERPNext/HRMS
DocTypes underneath. API conventions (envelope, errors, idempotency) are in
[api/README.md](api/README.md).

Status: **Live** — used by the app today · **Ready** — implemented and tested on
the backend, the app does not call it yet · **Planned** — not implemented.

## Modules

| Area | App screen / action | API module | ERPNext / HRMS DocTypes | Status |
| --- | --- | --- | --- | --- |
| Auth & access | login, current user, employee access | `auth` | User, Role, Employee, User Permission | Live |
| Offices & setup | offices, company setup, fiscal years, base setup | `setup`, `organization` | Company, Fiscal Year, ASOUD Company Setup | Live |
| Chart & details | chart of accounts, detail groups, floating details | `account`, `detail_group`, `floating_detail` | Account, ASOUD Detail Group, ASOUD Floating Detail | Live |
| Parties | people and companies, party links | `party` | Customer, Supplier, Employee, ASOUD Party Profile | Live |
| Vouchers | accounting vouchers and approval | `voucher` | Journal Entry | Live |
| Reports | trial balance, general ledger | `report` | GL Entry | Live |
| Personnel & HR | personnel records, work reports, communications | `personnel`, `hr` | Employee, ASOUD Personnel Record, ASOUD Internal Communication | Live |
| Workflows | designer, runtime, tasks, notifications | `workflow`, `workflow_runtime` | ASOUD Workflow *, Notification Log | Live |
| Requests | request types, generic requests | `workflow_request`, `workflow` | ASOUD Workflow Request, User, Department, Item, UOM | Live (new field types Ready) |
| Purchase requests | purchase request | `purchase_request` | Material Request | Live |
| **Dashboard** | home figures (today's receipts and sales, bank balance, open documents), settings status cards | [`dashboard`](api/dashboard.md) | Payment Entry, Sales Invoice, Account/GL Entry, User, File, Error Log | Ready |
| **Selling** | home "فاکتور فروش" | [`selling`](api/selling.md) | Sales Invoice, Customer, Item Price, Sales Taxes and Charges Template | Ready |
| **Payments** | home "دریافت و پرداخت" | [`payments`](api/payments.md) | Payment Entry, Mode of Payment, Bank Account | Ready |
| **Stock** | items, stock balance, receipts, issues, transfers | [`stock`](api/stock.md) | Item, Bin, Stock Entry, Warehouse | Ready |
| **Buying** | purchase orders, receipts, supplier invoices | [`buying`](api/buying.md) | Purchase Order, Purchase Receipt, Purchase Invoice, Supplier | Ready |
| **HR self-service** | requests: leave, mission, advance, expense; check-in; payslips, attendance, holidays | [`hr_self_service`](api/hr_self_service.md) | Leave Application, Employee Checkin, Travel Request, Employee Advance, Expense Claim, Salary Slip, Attendance, Holiday List | Ready |
| **Support & assets** | requests: IT service, equipment | [`support`](api/support.md) | Issue, Asset | Ready |
| Correspondence (مکاتبات) | bottom navigation tab | `hr` communications | ASOUD Internal Communication | Live, UI pending |
| **Sales pipeline** | quotations, sales orders, deliveries | [`sales_orders`](api/sales_orders.md) | Quotation, Sales Order, Delivery Note | Ready |
| Payroll processing | — | — | Salary Structure, Payroll Entry (employees already see their slips) | Planned |
| Projects & timesheets | — | — | Project, Task, Timesheet | Planned |
| POS | — | — | POS Profile, POS Invoice | Planned |

## Request cards → native documents

The request list in the app ("درخواست خرید", "مرخصی", ...) should open the native
flow when one exists, and fall back to a builder-defined request type otherwise:

| Card | Native endpoint | Document |
| --- | --- | --- |
| درخواست خرید | `purchase_request.create_purchase_request` | Material Request (Purchase) |
| درخواست مرخصی | `hr_self_service.create_leave_application` | Leave Application |
| درخواست مأموریت | `hr_self_service.create_travel_request` | Travel Request |
| درخواست مساعده | `hr_self_service.create_employee_advance` | Employee Advance |
| هزینه (تنخواه) | `hr_self_service.create_expense_claim` | Expense Claim |
| درخواست خدمات IT | `support.create_issue` | Issue |
| درخواست تجهیزات | `purchase_request.create_purchase_request`, or a builder request type with an Item Table | Material Request / ASOUD Workflow Request |
| سایر درخواست‌ها | `workflow_request.create_request` | ASOUD Workflow Request |

Native documents keep their HRMS/ERPNext approval (leave approver, expense
approver, Support team). Builder request types use the ASOUD workflow runtime.

## What the app should change next

1. Home: replace the four "—" metric cards with `dashboard.get_home_summary`;
   show `null` figures as "—".
2. Settings: fill the six status cards from `dashboard.get_system_summary`
   (System Manager only; hide the cards for other users).
3. Home quick actions "فاکتور فروش" and "دریافت و پرداخت": build on `selling`
   and `payments`; send writes through `sync.execute_mutation`.
4. Request list: route the six fixed cards to the native endpoints above.
5. Request type builder: enable the `Multi Choice`, `User`, `Department` and
   `Item Table` field types, and render them in the request form with
   `workflow_request.request_field_options`.

## Development bench

Integration tests need a site with ERPNext and HRMS `version-15`. Any bench works;
the one used for this work was created with:

```bash
bench init bench --frappe-branch version-15 --python python3.11
cd bench && bench get-app --branch version-15 erpnext && bench get-app --branch version-15 hrms
bench get-app /path/to/frappe-erp-next-2      # this app
bench new-site asoud.test --install-app erpnext --install-app hrms
bench --site asoud.test install-app asoud_erp
bench --site asoud.test set-config allow_tests true
bench --site asoud.test run-tests --module asoud_erp.integration_tests.test_selling_payments
```

Run every integration module with `--module`. `run-tests --app asoud_erp` stops
in Frappe's test-record generator (it follows links to `Payment Gateway`, which
belongs to the separate `payments` app). The pure `asoud_erp/tests` suite uses
pytest and runs without a site.

| Module | Tests |
| --- | --- |
| `asoud_erp.integration_tests.test_selling_payments` | 8 |
| `asoud_erp.integration_tests.test_stock_buying` | 7 |
| `asoud_erp.integration_tests.test_sales_orders` | 3 |
| `asoud_erp.integration_tests.test_hr_self_service` | 6 |
| `asoud_erp.integration_tests.test_dashboard_support_sync` | 6 |
| `asoud_erp.asoud_erp.doctype.asoud_workflow_request.test_asoud_workflow_request` | 12 |
| `asoud_erp.asoud_erp.doctype.asoud_personnel_record.test_asoud_personnel_record` | 9 |
| `asoud_erp.asoud_erp.doctype.asoud_company_setup.test_asoud_company_setup` | 4 |
| `asoud_erp.asoud_erp.doctype.asoud_party_profile.test_asoud_party_profile` | 1 |
