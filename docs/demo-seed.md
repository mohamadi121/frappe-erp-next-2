# Demo seed (`asoud_erp.demo.seed`)

A re-runnable seed command for a **real test site**, so the phone app can
be pointed at a server with every feature filled. Everything is built on
standard ERPNext/HRMS DocTypes and controller functions (wrapped through
the thin `asoud_erp.api.v1` layer where one exists); ERPNext/HRMS source
is never touched.

## Run

```sh
bench --site <site> execute asoud_erp.demo.seed.run
bench --site <site> execute asoud_erp.demo.seed.run --kwargs "{'reset': True}"
bench --site <site> execute asoud_erp.demo.seed.run --kwargs "{'password': 's3cret'}"
```

Safety (see `asoud_erp/demo/markers.py`):

- Refuses to run when `frappe.conf.developer_mode` is off, unless
  `force=True`.
- Refuses on any site whose name contains neither `test` nor `demo`,
  unless `force=True`.

Passwords: all four demo users share one password. Pass it with
`password=...`; otherwise a random one is generated and **printed once**
(on re-runs, when the users already exist, nothing is printed and
passwords are left alone).

## What it creates

Company «شرکت نمونه آسود» (IRR, Iran, Standard chart) with a fiscal year
for the current calendar year, then:

- Departments (فروش، مالی، فناوری اطلاعات، اداری و منابع انسانی —
  ERPNext adds its own standard departments to the new company as well),
  9 designations, 12 employees with a `reports_to` chain created through
  the asoud personnel API (`party.save_party`), and 4 users
  (`hr-manager@`, `sales-manager@`, `employee@`, `newcomer@asoud-demo.local`
  with HR Manager / Sales Manager / Employee roles). `newcomer` never
  logs in, for the resend-invitation case.
- Personnel records through `personnel.add_record`: a history row for the
  CEO and an employment-contract document for the sales manager.
- Holiday List (company default), 2 leave types, allocations for all
  employees, 2 approved leave applications in the current month.
- 2 salary components, a monthly salary structure and assignments for all
  employees; attendance for the current month (Present, On Leave on the
  approved leave days).
- 3 customers, 2 suppliers, 4 items priced in `ASOUD-DEMO Selling` /
  `ASOUD-DEMO Buying` price lists (company currency IRR). The parties carry
  `default_currency` IRR and point at these lists, so every invoice and
  order is created in IRR with no currency conversion (the site defaults
  are usually in the site currency and would fail without an exchange
  rate). Stock via a submitted Material Receipt; 2 submitted sales
  invoices; a purchase order → receipt → purchase invoice flow (all
  submitted).
- 2 workflow definitions (request types) with a linked native Frappe
  Workflow: «درخواست مرخصی نمونه» (form → direct-manager approval) and
  «درخواست خرید نمونه» (form → approval → Change Status system action),
  plus 4 requests in Completed / Running / Rejected / Cancelled states.

Running twice creates nothing new: every section looks its records up
first (company, prefixed codes, fixed `request_id`s).

## Reset

`reset=True` cancels submitted documents, purges the ledger rows
(GL / Payment Ledger / Stock Ledger / Leave Ledger) of exactly the
vouchers the seed created — the same tables ERPNext's own
company-transaction purge touches — then deletes every marked record in
dependency order (transactions → workflow records → personnel →
employees/users → masters → fiscal-year row → company). The `reports_to`
chain is cleared before employees are deleted, and the request/instance
link before the instances. Cancelling stock vouchers spawns fresh Repost
Item Valuation rows, so those are wiped after the vouchers; a Queued
repost cannot be cancelled (and never runs where the scheduler is off),
so such rows are marked Failed first. Records are identified by the demo
company, the `ASOUD-DEMO` code prefix, or Persian display names
containing «نمونه آسود» (constants in `asoud_erp/demo/markers.py`).

## Check

`bench --site <site> execute asoud_erp.demo.seed.check` returns the
count of demo-marked records per DocType plus a `TOTAL` (all zero means
the site is clean). Read-only; useful before and after a seed/reset
cycle.

Deliberate leftovers: the hidden Custom Field a native `Workflow` adds
to `ASOUD Workflow Request` (a compatibility reference shared with any
workflow on that DocType), and Frappe `Version` audit rows. The
`ASOUD-DEMO Draft` Workflow State is removed only when nothing else on
the site references it (states live in a shared namespace); otherwise it
is reported under `kept` and left alone. Nothing else is touched.

## Tests

- Pure: `asoud_erp/tests/test_demo_seed.py` (guard rules, naming).
- Integration: `asoud_erp/integration_tests/test_demo_seed.py` — seed
  twice (counts identical, second run creates nothing), reset (marked
  records gone, ledger purged, an unrelated Employee untouched),
  refusal without developer_mode/force. In the CI loop in
  `.github/workflows/erpnext-v15-integration.yml`.
