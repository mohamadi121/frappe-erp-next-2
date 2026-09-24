# Dashboard — `asoud_erp.api.v1.dashboard`

Figures for the home screen and the settings status cards, read from ERPNext.
A figure the user may not read is `null`, never `0`: show it as "—".

## `get_home_summary(company)` — GET

Any user with access to `company`. Each figure is filtered by the user's own
ERPNext permissions.

```json
{
  "company": "Tabaan", "date": "2026-09-24", "currency": "IRR",
  "today_receipts": 12500000.0,
  "today_payments": 3000000.0,
  "today_sales": 48200000.0,
  "bank_and_cash": {
    "total": 910000000.0,
    "accounts": [{"account": "Cash - T", "account_name": "Cash", "account_type": "Cash", "balance": 10000000.0}]
  },
  "open_documents": {
    "unpaid_sales_invoices": 7, "unpaid_purchase_invoices": 2,
    "draft_sales_invoices": 1, "draft_payment_entries": 0, "draft_journal_entries": 3,
    "pending_material_requests": 4, "my_open_tasks": 5, "total": 22
  }
}
```

| Field | Source |
| --- | --- |
| `today_receipts` / `today_payments` | submitted Payment Entry (`Receive` / `Pay`) posted today, company currency |
| `today_sales` | submitted Sales Invoice posted today; credit notes are negative, so this is net |
| `bank_and_cash` | ERPNext `get_balance_on` for every non-group Bank and Cash account of the company |
| `open_documents.*` | counts the user can see; `my_open_tasks` = open ASOUD workflow tasks assigned to the user |

Home card mapping: "دریافتی امروز" → `today_receipts`, "فروش امروز" →
`today_sales`, "موجودی بانک" → `bank_and_cash.total`, "اسناد باز" →
`open_documents.total`.

## `get_system_summary()` — GET, System Manager

```json
{
  "users": {"total": 150, "active": 124, "online": 18, "online_window_minutes": 15},
  "storage": {"files_bytes": 1932735283, "database_bytes": 644245094,
              "used_bytes": 2576980377, "quota_bytes": 17179869184},
  "pending_workflow_tasks": 7,
  "errors_last_24h": 0,
  "sync": {"last_completed_on": "2026-09-24 10:30:12", "stuck_requests": 0},
  "scheduler_enabled": true
}
```

- `online`: enabled system users whose `last_active` is within 15 minutes.
- `quota_bytes` is `null` unless `limits.space` (GB) is set in the site config.
- `sync.stuck_requests`: `ASOUD API Request` rows still `Processing` after 10 minutes.

Settings card mapping: "کاربران فعال" → `users.active` of `users.total`,
"کاربران آنلاین" → `users.online`, "فضای ذخیره‌سازی" → `storage`,
"درخواست‌های در انتظار" → `pending_workflow_tasks`, "خطاهای سیستم" →
`errors_last_24h`, "وضعیت همگام‌سازی" → `sync`.
