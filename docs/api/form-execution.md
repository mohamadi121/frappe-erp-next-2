# Form execution after approval

## Employee advance (`employee_advance`)

Internal executor: `services/form_execution/employee_advance.py`. The approval dispatcher
owns the savepoint, failure recording and retry; this module does not implement a hook.
It returns the existing `NativeResult(doctype, name, status, reason)` shape using named fields.
Successful execution returns `Created`, `Employee Advance`, the inserted name and an empty reason.
Invalid input or missing prerequisites raise `ValueError` with a Persian reason for the dispatcher.

| Parameter | Allowed field types | Required | Native mapping |
| --- | --- | --- | --- |
| `amount` | Integer, Decimal, Money | yes | `advance_amount`, positive finite number |
| `purpose` | Text, LongText | yes | trimmed `purpose` |
| `posting_date` | Date | no | ISO `posting_date`; missing, null or empty uses `ctx.today` |
| `repay_from_salary` | Boolean, Checkbox | no | `repay_unclaimed_amount_from_salary`; missing, null or empty is 0; accepts booleans and 0/1 |

`build(params, ctx)` is pure and uses the E2 context: company, employee, user,
request_name and today. Company and employee must be present. It produces a draft
(`docstatus = 0`), with `exchange_rate = 1`. `apply` resolves the requester's active
Employee in the request company, using `requester_employee` when provided and otherwise
`requester`; the resolved employee must belong to the requester and company.
Currency is `Company.default_currency`, and advance account is
`Company.default_employee_advance_account`. The account must exist, belong to the
company, be enabled, be a leaf and have type Receivable. No holiday list, approver,
asset custodian, bank account or salary structure is required for a draft advance.
Insertion uses the existing `as_administrator` scope; nothing is submitted or paid.

The installed HRMS Employee Advance JSON/controller impose no maximum requested
advance amount. Its maximum rules concern later payment (paid <= requested) and
return (returned <= unclaimed paid); these remain owned by HRMS. This executor
creates no payment or return and invents no salary-based ceiling.

Persian validation errors:

- «مبلغ مساعده باید عددی مثبت و متناهی باشد.»
- «شرح درخواست مساعده الزامی است.»
- «تاریخ ثبت مساعده معتبر نیست.»
- «گزینه بازپرداخت از حقوق باید بله یا خیر باشد.»
- «شرکت درخواست مشخص نشده است.»
- «پرونده پرسنلی درخواست‌دهنده ثبت نشده است.»
- «شرکت درخواست یافت نشد.»
- «واحد پول شرکت مشخص نشده است.»
- «حساب پیش‌فرض مساعده کارکنان در شرکت تنظیم نشده است.»
- «حساب مساعده کارکنان باید حساب دریافتنی فعال و غیرگروهی همین شرکت باشد.»

No new endpoint, DocType, migration or site configuration is introduced here.
