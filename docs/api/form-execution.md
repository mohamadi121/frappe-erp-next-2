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
Employee with `user_id = request.owner` in the request company. When
`requester_employee` is provided, the lookup also requires that employee name; the
resolved employee must belong to the owner and company.
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

## Attendance correction (`attendance_correction`)

قرارداد داخلی E2/E5؛ `kind=attendance_correction`، عنوان «اصلاح تردد».
این ماژول endpoint مستقل ندارد. فراخوانی `apply(request, params)` فقط پس از
تأیید نهایی از چارچوب اجرای درخواست است؛ نقش و دسترسی درخواست در آن مسیر
کنترل می‌شود. این تغییر چارچوب یا hook جدیدی ایجاد نمی‌کند.

### پارامترها

| پارامتر | عنوان | نوع | الزامی | نگاشت |
| --- | --- | --- | --- | --- |
| `date` | تاریخ تردد | `Date` | بله | روز کاری، میلادی `YYYY-MM-DD` در سرور |
| `kind` | نوع اصلاح | `Select` | بله | چهار مقدار جدول بعد |
| `in_time` | ساعت ورود پیشنهادی | `Time` | فقط برای `missing_entry` | ساعت `Employee Checkin.time` |
| `out_time` | ساعت خروج پیشنهادی | `Time` | فقط برای `missing_exit` | ساعت `Employee Checkin.time` |
| `reason` | دلیل اصلاح تردد | `LongText` | خیر | در درخواست اصلی محفوظ است؛ Checkin فیلد دلیل ندارد |

ساعت `HH:MM` یا `HH:MM:SS` است. کلید همراه `in_time__next_day` یا
`out_time__next_day` یک مقدار بولی است؛ `true` یعنی ساعت در `date + 1 day`.
کلید همراه پارامتر مستقل نیست. مقدار غایب، `null` یا خالی برای همراه روز بعد
به‌معنی همان روز است. ساعت مربوط به نوع دیگر نادیده گرفته می‌شود، حتی اگر
خالی باشد. دلیل غایب، `null` یا خالی مجاز است؛ دلیل غیرمتنی رد می‌شود.

`build(params, ctx)` خالص است؛ `ctx` شامل `company`, `employee`, `user`,
`request_name`, `today` است. شرکت و کارمند باید غیرخالی باشند. خروجی برای
رخداد مفقود دیکشنری قابل استفاده در `frappe.get_doc` است. برای دو نوع نیازمند
بررسی، `build` مقدار `{"needs_review": REVIEW_REASONS[kind]}` برمی‌گرداند؛
`apply` کلید `needs_review` را به نتیجه متناظر تبدیل می‌کند. استثنا فقط برای
ورودی نامعتبر است و متن خطا برای تشخیص نتیجه بررسی مقایسه نمی‌شود.

### نگاشت بومی و نتیجه

| `kind` | رفتار | نتیجه |
| --- | --- | --- |
| `missing_entry` | افزودن یک `Employee Checkin`، `employee=ctx.employee`, `log_type=IN`, `time=date + in_time` با لحاظ روز بعد | `Created`, `doctype=Employee Checkin`, `name=<new name>`, `reason=''` |
| `missing_exit` | همان مسیر با `log_type=OUT`, `out_time` | همان نتیجه |
| `correct_recorded_time` | هیچ رخداد قبلی تغییر یا حذف نمی‌شود و رخداد جایگزین ساخته نمی‌شود | `needs_review`, `doctype=null`, `name=null`, `reason=نیاز به اقدام HR؛ اصلاح ساعت ثبت‌شده باید با بررسی رکورد اصلی انجام شود.` |
| `other` | شرح آزاد به مأموریت یا حضور تمام‌روز تبدیل نمی‌شود | `needs_review`, `doctype=null`, `name=null`, `reason=نیاز به اقدام HR؛ نوع عملیات برای سایر موارد مشخص نشده است.` |

نتیجه همان `services.request_templates.base.NativeResult` است.
Checkin قابل ارسال نیست و با `docstatus=0` درج می‌شود؛ درج به‌تنهایی تضمین
محاسبه مجدد Attendance نیست. شرکت در Employee تعیین می‌شود، نه در Checkin.
هیچ Checkin قبلی در هیچ مسیری ویرایش یا حذف نمی‌شود.

`apply` در صورت وجود `requester_employee` همان کارمند را با فیلتر هم‌زمان
نام، مالک درخواست (`user_id`)، شرکت و وضعیت `Active` پیدا می‌کند؛ در صورت
نبود این فیلد، جست‌وجو با مالک، شرکت و وضعیت `Active` انجام می‌شود. کارمند
منتخب نامعتبر با کارمند دیگری جایگزین نمی‌شود. رخداد یکسان کارمند/زمان/نوع با خطای فارسی رد می‌شود، نه با موفقیت
ساختگی. درج فقط در `as_administrator` با `ignore_permissions=True` انجام
می‌شود؛ اعتبارسنجی استاندارد HRMS فعال می‌ماند. savepoint و rollback متعلق
به dispatcher موجود است. این ماژول چارچوب اجرای مجدد یا receipt موازی ندارد.

در این شاخه helper اعلان مخصوص `needs_review` یا T6 وجود ندارد. helper نظر
درخواست به مالک و مسئول مرحله اعلان می‌دهد و helper شکست وضعیت را Failed
می‌کند؛ هیچ‌کدام برای این نتیجه مناسب نیست. طبق تصمیم مدیر، فعلاً فقط
`needs_review` برگردانده می‌شود؛ ارسال اعلان HR هنوز اتصال ندارد.

### خطاهای فارسی

| وضعیت | پیام |
| --- | --- |
| ورودی غیر دیکشنری | اطلاعات اصلاح تردد معتبر نیست. |
| شرکت خالی | شرکت درخواست مشخص نشده است. |
| کارمند غایب | پرونده پرسنلی درخواست‌دهنده ثبت نشده است. |
| کارمند غیرفعال | پرونده پرسنلی درخواست‌دهنده فعال نیست. |
| تاریخ غایب یا نامعتبر | تاریخ تردد معتبر نیست. |
| نوع غایب یا ناشناخته | نوع اصلاح تردد معتبر نیست. |
| ساعت ورود غایب یا نامعتبر | ساعت ورود پیشنهادی معتبر نیست. |
| ساعت خروج غایب یا نامعتبر | ساعت خروج پیشنهادی معتبر نیست. |
| همراه روز بعد غیر بولی | گزینه روز بعد معتبر نیست. |
| دلیل غیرمتنی | دلیل اصلاح تردد باید متن باشد. |
| رخداد تکراری | برای این کارمند تردد با همین زمان و نوع قبلاً ثبت شده است. |
| تنظیم موقعیت اجباری | ثبت تردد به موقعیت مکانی نیاز دارد؛ درخواست باید توسط منابع انسانی بررسی شود. |
| سایر خطاهای اعتبارسنجی HRMS هنگام درج | ثبت تردد انجام نشد؛ تنظیمات شیفت و الزامات تردد را بررسی کنید. |

### فیلدها و کنترلرهای بررسی‌شده

- `hrms/hr/doctype/employee_checkin/employee_checkin.json`: `employee`, `time`
  الزامی؛ `log_type` خالی/`IN`/`OUT`؛ `shift`, `attendance`, `device_id` اختیاری.
  `employee_checkin.py` کارمند فعال، تکرار، تغییر ساعت مرتبط با Attendance،
  شیفت و موقعیت مکانی را کنترل می‌کند؛ نبود شیفت، `shift=None`, `offshift=1`
  است و مانع ثبت نیست. حساب، فهرست تعطیلات و متولی دارایی پیش‌نیاز Checkin نیستند.
- `attendance_request.json`: `employee`, `company`, `from_date`, `to_date`,
  `reason` الزامی؛ `reason` فقط `Work From Home` یا `On Duty` است.
  `explanation`, `shift`, `half_day_date` اختیاری‌اند. `on_submit` رکورد Attendance
  می‌سازد یا وضعیت آن را تغییر می‌دهد؛ پیش‌نویس چنین اثری ندارد. هیچ‌یک از
  چهار نوع T1 مأموریت یا حضور تمام‌روز نیست، پس این اجراکننده آن را نمی‌سازد.
- ERPNext `employee.json`: `first_name`, `company`, `status`, `gender`,
  `date_of_birth`, `date_of_joining` الزامی؛ `user_id`, `holiday_list` اختیاری.
  `company.json`: `company_name`, `abbr`, `default_currency`, `country` الزامی.

تصمیم مالک محصول در قرارداد E5 (۲۰۲۶-۱۰-۲۳) شناسه‌های `missing_entry` و
`missing_exit` و مجاز بودن دلیل خالی را تعیین کرده است؛ قرارداد پیشین T1
با شناسه‌های `missing_check_in`/`missing_check_out` مبنای این اجراکننده نیست.

## Asset movement (`asset_movement`)

Internal E2 executor: `asoud_erp.services.form_execution.asset_movement`.
The approved-request dispatcher owns access checks, active requester resolution,
retry, savepoint and failure recording. This module adds no HTTP endpoint.
`apply(request, params)` returns the existing `NativeResult` with `status=Created`,
`doctype=Asset Movement`, the inserted name and an empty reason. Validation raises
with a Persian reason for the dispatcher to record as Failed.

### asset_movement — جابه‌جایی تجهیزات

| Parameter | Field types | Required | Mapping |
|---|---|---|---|
| asset | Link | yes | assets[0].asset |
| direction | Select | yes | Issue or Receipt → purpose |
| date | Date | no | transaction_date at midnight; empty uses ctx.today |
| note | Text, LongText | no | Persian Comment on the draft; no invented native field |

`build(params, ctx)` is pure. Standard context keys are company, employee, user,
request_name and today. `apply` adds asset_location and asset_custodian read from
Asset. For Issue, to_employee is the requester; for Receipt, from_employee is the
requester and to_employee is empty. Both use the asset's current location as
source_location and target_location. Receipt requires custodian=requester.
Issue uses the current custodian as from_employee when present (empty is valid).
Company, docstatus=0 and reference_doctype/reference_name link the native draft to
the approved request. No submit occurs and the asset's custodian is unchanged.

Prerequisites: existing submitted Asset in the request company, existing Location,
and active requester Employee in that company. Asset Movement does not use accounts
or a holiday list; these are deliberately not prerequisites. The ERPNext controller
also forbids a date before the latest submitted movement; this check is localized.
No new DocType, field or migration is needed.

Persian validation messages:

- «تجهیز را انتخاب کنید.»
- «جهت جابه‌جایی باید تحویل یا بازگشت باشد.»
- «تاریخ جابه‌جایی معتبر نیست.»
- «توضیحات جابه‌جایی معتبر نیست.»
- «پرونده پرسنلی درخواست‌دهنده ثبت نشده است.»
- «تجهیز انتخاب‌شده وجود ندارد.»
- «تجهیز انتخاب‌شده متعلق به شرکت درخواست نیست.»
- «تجهیز انتخاب‌شده باید تأیید شده باشد.»
- «مکان تجهیز ثبت نشده یا معتبر نیست.»
- «تجهیز در اختیار درخواست‌دهنده نیست و قابل بازگشت نیست.»
- «تاریخ جابه‌جایی نمی‌تواند پیش از آخرین جابه‌جایی تجهیز باشد.»

Asset movement Select option ids use the form schema's lowercase names `issue`
and `receipt`. The executor maps them to native `Issue` and `Receipt`; existing
server callers using the native names remain compatible.

## Shift request (`shift_request`)

Internal executor, through the existing approval dispatcher and retry endpoint; no new
HTTP endpoint or role gate. Parameters: `kind` (Select, required: `self_change` or
`swap_with_colleague`), `from_date` (Date, required), `to_date` (Date, optional,
empty means open end as HRMS permits), `shift_type` (Link, required: proposed shift
for requester), `colleague` (Employee Link, required for swap),
`colleague_shift_type` (Shift Type Link, required for swap: proposed shift for colleague),
`reason` (Text/LongText, optional). Parameter mapping uses execution_key, never preset keys.
T4 uses change_type, change_date/start_date, end_date, exchange_colleague; its two
proposed shifts must be explicitly mapped by the designer.

Pure build returns the first Shift Request payload plus `additional_requests` for
the colleague. Both are Draft/docstatus 0. No assignment is submitted or schedule
changed. apply returns Created/Shift Request/first name; the second draft is linked
by a Persian Comment on the first. Reason is preserved as a Comment (no native field).
Both drafts are atomic, including comments; failure rolls back both and dispatcher
records Failed, preserving approval and allowing retry.

Active requester/colleague must belong to the request company and differ. Dates
must be ISO and ordered. Shift Types must exist; installed HRMS has no disabled
field (enable_auto_attendance controls attendance processing, not shift eligibility).
Each employee needs an enabled native shift_request_approver user, falling back
to an enabled department shift approver in row order. HRMS validates
request overlap/default shift; a transient Shift Assignment validates active submitted
assignment overlap without inserting it. Native validation failures become
«ثبت درخواست شیفت انجام نشد؛ هم‌پوشانی برنامه، شیفت پیش‌فرض و تأییدکننده را بررسی کنید.».
Missing dates, shift, colleague, company, employee or approver fail with a Persian
reason identifying the missing prerequisite. No migration or configuration is added.

| خطای ورودی/پیش‌نیاز | پیام |
|---|---|
| ورودی نامعتبر | اطلاعات تغییر شیفت معتبر نیست. |
| شرکت خالی | شرکت درخواست مشخص نشده است. |
| کارمند غایب | پرونده پرسنلی درخواست‌دهنده ثبت نشده است. |
| نوع ناشناخته | نوع تغییر شیفت معتبر نیست. |
| تاریخ نامعتبر | تاریخ تغییر شیفت معتبر نیست. |
| بازه معکوس | تاریخ پایان نمی‌تواند پیش از شروع باشد. |
| دلیل غیرمتنی | دلیل تغییر شیفت باید متن باشد. |
| شیفت خالی | شیفت پیشنهادی را انتخاب کنید. |
| همکار خالی | همکار جایگزین را انتخاب کنید. |
| همکار خود شخص | همکار جایگزین باید با درخواست‌دهنده متفاوت باشد. |
| شیفت همکار خالی | شیفت پیشنهادی همکار را انتخاب کنید. |
| همکار ناموجود، غیرفعال یا شرکت دیگر | همکار انتخاب‌شده باید فعال و متعلق به شرکت درخواست باشد. |
| شیفت ناموجود | شیفت انتخاب‌شده وجود ندارد. |
| تأییدکننده غایب/غیرفعال | تأییدکننده فعال شیفت برای کارکنان تنظیم نشده است. |
