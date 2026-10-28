# احکام افزایش یا تغییر حقوق و مزایا — `asoud_erp.api.v1.salary_change_orders`

این ماژول چرخه کامل حکم افزایش یا تغییر حقوق و مزایا را از پرسنل (`Employee`)، احکام حقوقی (`Salary Structure Assignment`)، قالب منتشرشدهٔ فرم‌ساز و موتور مقایسه محاسباتی پیاده‌سازی می‌کند. این ماژول داده‌های حقوق جاری را به شکل زنده مخدوش نمی‌کند و تفکیک سخت‌گیرانه‌ای میان وضعیت تأیید حکم و وضعیت اعمال مالی آن برقرار می‌سازد.

همهٔ پاسخ‌ها envelope استاندارد `success(data, meta)` هستند. خواندن و ویرایش احکام برای `HR Manager` و `System Manager` است. دسترسی به ارقام حقوق و همچنین متد اعمال بر سیستم حقوق و دستمزد منحصراً متعلق به `Payroll Manager`، `Accounts Manager` و `System Manager` است.

## ۱. چرخه حیات قالب (Template Lifecycle)

| متد | نوع | پارامترها | خروجی | شرح |
| --- | --- | --- | --- | --- |
| `get_salary_change_order_template` | GET | `company` | `{template: dict \| null}` | دریافت آخرین پیش‌نویس یا نسخه منتشرشده قالب ۶ ماده‌ای |
| `save_salary_change_order_template` | POST | `company`, `revision`, `template` | `{revision: int, template: dict}` | ذخیره پیش‌نویس قالب با کنترل خوش‌بینانه نسخه |
| `publish_salary_change_order_template` | POST | `company`, `revision` | `{revision: int, template: dict}` | انتشار قطعی و تغییرناپذیر نسخه جدید قالب |

### ساختار شیء قالب (`template`)
- `articles`: آرایه‌ای دقیقاً شامل ۶ ماده با شناسه‌های پایدار (`employee_details`, `subject_reason`, `effective_date`, `salary_comparison`, `terms`, `issuing_authority`):
  - `id`: شناسه پایدار یکتا (مانند `salary_comparison`)
  - `title`: عنوان ماده (قابل ویرایش در فرم‌ساز)
  - `body`: متن ماده با متغیرهای جایگزین (`[نام و نام خانوادگی پرسنل]`, `[کد پرسنلی]`, `[علت تغییر حقوق]`, `[تاریخ اجرای تغییر]` و ...)
- `comparison_rows`: آرایه ردیف‌های مقایسه حقوق و مزایا (ماده ۴):
  - `id`: شناسه پایدار ردیف (مانند `base_salary`, `housing`, `food`)
  - `title`: عنوان قلم (مانند «حقوق پایه»)
  - `period`: دوره پرداخت (`monthly`, `yearly`, `one_off`)
  - `old_ref`: منبع فیلد مبلغ قبلی (مانند `payroll.base_salary`)
  - `new_ref`: منبع فیلد مبلغ جدید (مانند `document.new.base_salary`)

---

## ۲. منابع داده صدور (Issuance Sources)

| متد | نوع | پارامترها | خروجی | شرح |
| --- | --- | --- | --- | --- |
| `list_salary_change_order_people` | GET | `company`, `search?`, `limit_start?`, `limit_page_length?` | `[{name, display_name, employee_number, department, designation}]` + `meta` | فهرست پرسنل فعال با جست‌وجوی نرمال‌شده |
| `get_salary_change_order_payroll` | GET | `company`, `employee`, `effective_date` | `{currency: str, rows: list[dict], message?: str}` | استعلام مبالغ قبلی به تاریخ اجرا از احکام حقوقی معتبر |

### قوانین داده‌های حقوق قبلی:
- اگر به تاریخ اجرای تعیین‌شده، حکم فعالی یافت نشود، مقدار `amount: null` با وضعیت `state: "missing"` و پیام صریح `message: "اطلاعات موجود نیست"` برگردانده می‌شود.
- صفر هرگز جانشین مقادیر ناموجود نمی‌شود.

---

## ۳. محاسبات جدول مقایسه (Comparison Calculation Rules)

در زمان صدور یا ذخیره، مقادیر جدول مقایسه با قوانین ریاضی زیر محاسبه می‌شوند:
- اختلاف ریالی: $\Delta = \text{new\_amount} - \text{previous\_amount}$ (محاسبه دقیق با Decimal، بدون ممیز شناور).
- درصد تغییر: $(\Delta / \text{previous\_amount}) \times 100$
  - تنها در صورتی محاسبه می‌شود که مبلغ قبلی عددی و غیرصفر باشد.
  - اگر مبلغ قبلی صفر باشد: برچسب «قابل محاسبه نیست» درج می‌شود (عدم تقسیم بر صفر).
  - اگر مبلغ قبلی یا جدید ناموجود باشد: وضعیت صریح «اطلاعات موجود نیست» درج می‌شود.
- جمع کل ماهانه: صرفاً اقلام با دوره پرداخت `monthly` با یکدیگر جمع می‌شوند. اقلام سالانه یا یک‌باره هرگز با اقلام ماهانه جمع زده نمی‌شوند.

---

## ۴. احکام و گردش‌کار (Orders & Lifecycle)

| متد | نوع | پارامترها | خروجی | شرح |
| --- | --- | --- | --- | --- |
| `list_salary_change_orders` | GET | `company`, `search?`, `status?`, `application_status?`, `limit_start?`, `limit_page_length?` | `{items: [summary]}` + `meta` | جست‌وجوی نام، کد پرسنلی، شماره حکم با نرمال‌سازی ی/ك و ارقام؛ فیلتر وضعیت و اعمال |
| `get_salary_change_order` | GET | `name` | جزئیات کامل حکم شامل تصویر لحظه‌ای قالب، مقادیر، جدول مقایسه و وضعیت‌ها |
| `save_salary_change_order` | POST | `company`, `request_id`, `revision?`, `order?`, `employee`, `effective_date`, `reason`, `description?`, `issue_date?`, `values?`, `comparison_rows?` | ذخیره پیش‌نویس بدون تغییر حقوق زنده پرسنل؛ تضمین idempotency با `request_id` |
| `send_salary_change_order_for_review` | POST | `name`, `revision`, `request_id` | ارسال حکم به گردش‌کار جهت بررسی و تأیید (تغییر وضعیت به `pending`) |
| `approve_salary_change_order` | POST | `name`, `revision`, `request_id` | تأیید نهایی حکم کارگزینی (تغییر وضعیت به `final`)؛ شماره‌گذاری رسمی سند |
| `reject_salary_change_order` | POST | `name`, `revision`, `reason?` | رد حکم کارگزینی (تغییر وضعیت به `rejected`) |
| `apply_salary_change_order_to_payroll` | POST | `name`, `operation_id` | **اعمال رسمی بر سیستم حقوق و دستمزد**: نیازمند نقش مالی/حقوق و وضعیت `final` |
| `print_salary_change_order` | GET | `name` | خروجی استاندارد چاپ A4 راست‌به‌چپ با سربرگ شرکتی و نوار پیش‌نویس |

### وضعیت‌های تأیید (`status`):
- `draft` (پیش‌نویس)
- `pending` (در جریان بررسی)
- `final` (نهایی و تأییدشده)
- `rejected` (رد شده)

### وضعیت‌های اعمال بر سیستم حقوق (`application_status`):
- `not_applied` (اعمال‌نشده)
- `applied` (اعمال‌شده بر حقوق)
- `failed` (خطا در اعمال)

### قوانین حیاتی اعمال بر حقوق (`apply_salary_change_order_to_payroll`):
1. **استقلال پیش‌نویس**: ذخیره پیش‌نویس یا پیش‌نمایش به هیچ وجه رکورد `Salary Structure Assignment` یا حقوق پرسنل را تغییر نمی‌دهد.
2. **شرط تأیید رسمی**: اعمال تغییر حقوق تنها زمانی مجاز است که `status == "final"` باشد. درخواست اعمال روی حکم در وضعیت پیش‌نویس یا در جریان با خطای صریح رد می‌شود.
3. **تفکیک دسترسی**: این متد به نقش‌های اختصاصی `Payroll Manager`، `Accounts Manager` یا `System Manager` نیاز دارد.
4. **تضمین تکرارپذیری (Idempotency)**: با ارسال `operation_id` پایدار، کلیک مضاعف یا اجرای مجدد، عملیات را تکرار نمی‌کند و رکورد قبلی را برمی‌گرداند.
5. **ثبت ردپا (Audit Trail)**: شناسه کاربر اعمال‌کننده، زمان دقیق اعمال و `operation_id` در سند ذخیره می‌شود.

---

## ۵. چاپ و خروجی A4 (`print_salary_change_order`)

- ساختار صفحه: استاندارد A4 عمودی راست‌به‌چپ (RTL).
- نوار پیش‌نویس: در صورتی که وضعیت حکم `final` نباشد، برچسب آب‌رنگ با عنوان «پیش‌نویس ـ فاقد اعتبار نهایی» نمایش داده می‌شود.
- تکرار سرستون: جدول مقایسه اقلام حقوق با `thead { display: table-header-group; }` در صورت چندصفحه‌ای شدن تکرار می‌شود.
- سربرگ و پابرگ: از تنظیمات Letter Head شرکت استخراج می‌گردد.
